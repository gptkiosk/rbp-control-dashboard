#!/usr/bin/env python3
"""Turn CHANGELOG.md into clean GitHub release notes, and refuse a release that has none.

Standard library only:

    python3 -I scripts/release/changelog.py check  VERSION            # section exists, dated, not empty
    python3 -I scripts/release/changelog.py notes  VERSION [--repo OWNER/NAME] [--previous X.Y.Z]
    python3 -I scripts/release/changelog.py latest                    # newest released version in the file

The changelog follows Keep a Changelog: `## [X.Y.Z] - YYYY-MM-DD` with `### Added`, `### Changed`,
`### Fixed` and similar subsections, newest first, plus an `## [Unreleased]` section on top. `notes`
prints the section body (no version heading, GitHub shows the tag already) followed by a link to the
full comparison with the previous release, ready for `gh release create --notes-file`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADING = re.compile(r"^## \[(?P<ver>[^\]]+)\](?:\s+-\s+(?P<date>\d{4}-\d{2}-\d{2}))?\s*$")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
SUBSECTION = re.compile(r"^### (Added|Changed|Deprecated|Removed|Fixed|Security)\s*$")


class ChangelogError(ValueError):
    pass


def sections(text: str) -> list[dict]:
    """Every `## [x]` section in order: version, date, body lines."""
    found: list[dict] = []
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            found.append({"version": m["ver"], "date": m["date"], "body": []})
        elif line.startswith("## "):
            found.append({"version": None, "date": None, "body": []})        # a non-version section ends the previous one
        elif found:
            found[-1]["body"].append(line)
    return [s for s in found if s["version"]]


def find(text: str, version: str) -> dict:
    for s in sections(text):
        if s["version"] == version:
            return s
    raise ChangelogError(f"CHANGELOG.md has no section '## [{version}] - YYYY-MM-DD'")


def body(section: dict) -> str:
    lines = list(section["body"])
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def check(text: str, version: str) -> dict:
    if not SEMVER.match(version):
        raise ChangelogError(f"'{version}' is not a semantic version")
    s = find(text, version)
    if not s["date"]:
        raise ChangelogError(f"## [{version}] needs a release date: '## [{version}] - YYYY-MM-DD'")
    content = body(s)
    if not re.search(r"^\s*[-*] \S", content, re.M):
        raise ChangelogError(f"## [{version}] lists no changes")
    for line in content.splitlines():
        if line.startswith("### ") and not SUBSECTION.match(line):
            raise ChangelogError(f"unknown subsection '{line}' (use Added, Changed, Deprecated, Removed, Fixed or Security)")
    return s


def previous_version(text: str, version: str) -> str | None:
    released = [s["version"] for s in sections(text) if SEMVER.match(s["version"])]
    if version not in released:
        return None
    i = released.index(version)
    return released[i + 1] if i + 1 < len(released) else None


def notes(text: str, version: str, repo: str | None, previous: str | None = None) -> str:
    s = check(text, version)
    out = [body(s)]
    prev = previous or previous_version(text, version)
    if repo and prev:
        out += ["", f"**Full changelog**: https://github.com/{repo}/compare/v{prev}...v{version}"]
    elif repo:
        out += ["", f"**Full changelog**: https://github.com/{repo}/commits/v{version}"]
    return "\n".join(out).rstrip() + "\n"


def latest(text: str) -> str | None:
    released = [s["version"] for s in sections(text) if SEMVER.match(s["version"]) and s["date"]]
    return released[0] if released else None


def default_repo() -> str | None:
    try:
        return json.loads((ROOT / "packaging" / "product.json").read_text())["repository"]
    except (OSError, ValueError, KeyError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "notes"):
        p = sub.add_parser(name); p.add_argument("version")
        p.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
        if name == "notes":
            p.add_argument("--repo"); p.add_argument("--previous")
    p = sub.add_parser("latest"); p.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    args = ap.parse_args(argv)
    try:
        text = args.changelog.read_text(encoding="utf-8")
        if args.cmd == "check":
            check(text, args.version); print(f"CHANGELOG.md is ready for {args.version}")
        elif args.cmd == "notes":
            sys.stdout.write(notes(text, args.version, args.repo or default_repo(), args.previous))
        else:
            v = latest(text); print(v or "")
            return 0 if v else 1
    except (ChangelogError, OSError) as exc:
        print(f"changelog: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
