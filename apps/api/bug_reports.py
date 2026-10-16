"""Bug reports from the header icon: scrub what a person typed, build the GitHub issue, and say how it can be sent.

Nothing here talks to GitHub. A report is built from the form and a short, shown-in-the-preview environment block, and every typed
field is scrubbed of paths, emails, addresses and token-shaped strings first. The target repository is the product's own official one,
fixed in code, never taken from a request."""
from __future__ import annotations

import platform
import re
from urllib.parse import quote

import release_verify as rv
from agents import REGISTRY
from version import __version__

PRODUCT = "rcd"
REPOSITORY = rv.OFFICIAL_REPOSITORIES[PRODUCT]
LABEL = "bug-report"
IMPACTS = {"blocks": "Blocks my work", "annoying": "Annoying", "idea": "Idea or small improvement"}
FIELD_MAX = {"title": 120, "what": 3000, "expected": 2000, "steps": 3000}
BODY_MAX = 9000
URL_MAX = 7500          # GitHub refuses very long query strings
PAGE = re.compile(r"/[a-z0-9/_-]{0,60}\Z")

# Order matters: specific token shapes before the generic ones.
_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("tokens", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})"), "[token]"),
    ("tokens", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[token]"),
    ("tokens", re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret|password|passwd)(\s*[:=]\s*|\s+)[^\s\"',;]{6,}"), r"\1\2[token]"),
    ("credentials in links", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@"), r"\1[credentials]@"),
    ("emails", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[email]"),
    ("home paths", re.compile(r"(?:/Users|/home)/[^/\s\"'`]+"), "~"),
    ("home paths", re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s\"'`]+"), "~"),
    ("host names", re.compile(r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:ts\.net|local|lan|internal|home\.arpa)\b"), "[host]"),
    ("addresses", re.compile(r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?:\d{1,3}\.){3}\d{1,3}\b"), "[address]"),
    ("addresses", re.compile(r"(?i)\b(?:[0-9a-f]{1,4}:){4,7}[0-9a-f]{1,4}\b"), "[address]"),
    ("long secrets", re.compile(r"\b[0-9a-fA-F]{40,}\b"), "[hash-or-secret]"),
    ("long secrets", re.compile(r"\b(?=[A-Za-z0-9+/_-]{40,}\b)(?=[A-Za-z0-9+/_-]*[A-Za-z])(?=[A-Za-z0-9+/_-]*\d)[A-Za-z0-9+/_-]{40,}"), "[token]"),
)


_SINGULAR = {"tokens": "token", "emails": "email", "home paths": "home path", "host names": "host name", "addresses": "address",
             "long secrets": "long secret", "credentials in links": "credentials in a link"}


def scrub(text: str) -> tuple[str, list[str]]:
    """The text with anything that identifies a person, a machine or a credential replaced, and a short list of what was replaced."""
    found: dict[str, int] = {}
    out = text or ""
    for name, pattern, repl in _PATTERNS:
        out, n = pattern.subn(repl, out)
        if n:
            found[name] = found.get(name, 0) + n
    return out, [f"{count} {name if count != 1 else _SINGULAR.get(name, name)}" for name, count in found.items()]


def _clean(value: object, limit: int) -> str:
    return str(value or "").replace("\x00", "").replace("\r\n", "\n").strip()[:limit]


def environment(settings, page: str = "") -> list[str]:
    """What the report says about this installation. No paths, names, addresses, keys or settings values."""
    agents = []
    for name, spec in REGISTRY.items():
        try:
            if spec.available(settings):
                agents.append(name)
        except Exception:   # noqa: BLE001 - an unreadable runtime is simply not listed
            pass
    lines = [f"Product: {settings.product_name} {__version__}", f"System: {platform.system()} {platform.machine()}",
             f"Agent runtimes installed: {', '.join(agents) if agents else 'none'}"]
    if page and PAGE.fullmatch(page):
        lines.append(f"Opened from: {page}")
    return lines


def build(form: dict, settings, include_environment: bool = True) -> dict:
    """The issue to send: title, body, what was scrubbed, and the prefilled GitHub link. Pure; sends nothing."""
    notes: list[str] = []
    fields = {}
    for key, limit in FIELD_MAX.items():
        clean, found = scrub(_clean(form.get(key), limit))
        fields[key] = clean
        notes += [f"{key}: {item}" for item in found]
    if not fields["title"]:
        raise ValueError("A title is required.")
    if not fields["what"]:
        raise ValueError("Say what happened.")
    impact = form.get("impact") if form.get("impact") in IMPACTS else "annoying"
    parts = ["### What happened", fields["what"], "", "### What I expected", fields["expected"] or "_not given_", "",
             "### Steps to reproduce", fields["steps"] or "_not given_", "", "### How much it affects me", IMPACTS[impact]]
    if include_environment:
        parts += ["", "### Environment", *[f"- {line}" for line in environment(settings, str(form.get("page") or ""))]]
    parts += ["", "_Reported from the dashboard's bug report form. Nothing was attached automatically beyond the lines above._"]
    body = "\n".join(parts)[:BODY_MAX]
    link, truncated = prefilled_url(fields["title"], body)
    return {"title": fields["title"], "body": body, "impact": impact, "scrubbed": notes, "url": link, "truncated": truncated,
            "repository": REPOSITORY, "labels_when_filed_here": filing_labels(impact)}


def filing_labels(impact: str) -> list[str]:
    """Labels applied only when this installation's own operator files the issue: that approval is the moderation."""
    return [LABEL, "accepted", "break-fix" if impact == "blocks" else "nice-to-have"]


def prefilled_url(title: str, body: str) -> tuple[str, bool]:
    """https://github.com/<official repo>/issues/new with the title, body and label hint filled in, shortened to fit a link."""
    base = f"https://github.com/{REPOSITORY}/issues/new?labels={quote(LABEL)}&title={quote(title, safe='')}&body="
    text, truncated = body, False
    while len(base) + len(quote(text, safe="")) > URL_MAX and len(text) > 200:
        text, truncated = text[: int(len(text) * 0.85)].rstrip() + "\n\n_[shortened to fit a link; add the rest in the issue]_", True
    return base + quote(text, safe=""), truncated


def capabilities(guard, reader) -> dict:
    """How a report can be sent from this install: filed directly through the guarded GitHub action, or opened prefilled on GitHub."""
    base = {"repository": REPOSITORY, "mode": "prefilled"}
    config = reader.config() if reader is not None else None
    if not getattr(guard, "enabled", False):
        return {**base, "reason": "Filing from this app is off on this install, so the report opens on GitHub for you to submit."}
    if config is None or not getattr(config, "configured", False) or REPOSITORY.lower() not in {r.lower() for r in config.repos}:
        return {**base, "reason": f"Add {REPOSITORY} to the GitHub repositories on this install to file from here. For now the report opens on GitHub for you to submit."}
    return {**base, "mode": "direct", "reason": "You will see the exact issue first. It is filed as your signed-in GitHub account only after you confirm."}
