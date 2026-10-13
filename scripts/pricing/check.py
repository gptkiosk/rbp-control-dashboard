#!/usr/bin/env python3
"""Compare MCD's price catalog (apps/api/pricing_catalog.json) with the providers' published prices.

  scripts/pricing/check.py                 report differences, exit 1 when any price differs
  scripts/pricing/check.py --apply         write changed prices and the verification date into the catalog
  scripts/pricing/check.py --source google check one source (openai, anthropic, google, openrouter)
  scripts/pricing/check.py --offline DIR   read saved pages from DIR instead of the network (tests)
  scripts/pricing/check.py --new           also list models on the pages that are not in the catalog
  scripts/pricing/check.py --used          list models used this month with no catalog price, and what the pages say
  scripts/pricing/check.py --used --add    add those the pages list to the catalog (the use is the decision)

The check only trusts what it can read unambiguously: the base prices (input, output, cache read, cache
write), a long-context tier where the page states one, and dated changes. Anything it cannot read is
reported as "review by hand", never guessed. New models are never added automatically: adding one is a
decision about what MCD will use. Nothing here talks to a model or to any account.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "apps" / "api" / "pricing_catalog.json"
PRICE_FIELDS = ("input", "output", "cached", "write", "write_1h")
TOLERANCE = 1e-9


# ---------------------------------------------------------------------------- readers
# Each reader returns {model_id: {field: number, "long": {...}, "changes": [...]}} with only what the
# page states, plus {"_skipped": {model_id: reason}} for rows it could not read.


def read_openai(text: str) -> dict:
    """The Standard-tier table embedded in the page: name, input, cached input, cache write, output.
    A '-' means the provider lists no separate charge, so cache write is the plain input price."""
    page = html.unescape(text)
    start = page.find('"tier":[0,"standard"]')
    if start < 0:
        raise ValueError("OpenAI page has no Standard tier table")
    end = page.find('"tier":[0,"', start + 10)
    segment = page[start: end if end > 0 else len(page)]
    out: dict = {}
    row = re.compile(r'\[0,"([^"]+)"\],\[0,([\d.]+|"-")\],\[0,([\d.]+|"-")\],\[0,([\d.]+|"-")\],\[0,([\d.]+|"-")\]')
    for name, i, c, w, o in row.findall(segment):
        model = re.sub(r"\s*\(.*\)$", "", name).strip().lower()
        num = lambda v: None if v == '"-"' else float(v)
        inp = num(i)
        if inp is None:
            continue
        entry = {"input": inp, "output": num(o)}
        if num(c) is not None:
            entry["cached"] = num(c)
        entry["write"] = num(w) if num(w) is not None else inp
        out[model] = entry
    if not out:
        raise ValueError("OpenAI page: no price rows found")
    return out


def _claude_id(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", name))
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _dollars(cell: str) -> float | None:
    found = re.search(r"\$\s*([\d,]*\.?\d+)", cell)
    return float(found.group(1).replace(",", "")) if found else None


def read_anthropic(text: str) -> dict:
    """The model pricing table: input, 5m cache write, 1h cache write, cache hit, output."""
    out: dict = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or not cells[0].lower().startswith("claude "):
            continue
        values = [_dollars(c) for c in cells[1:]]
        if None in values:
            continue
        model = _claude_id(cells[0])
        entry = {"input": values[0], "write": values[1], "write_1h": values[2], "cached": values[3], "output": values[4]}
        over = re.search(r"over ([\d,]+) tokens", cells[0])
        if over:
            out.setdefault(model, {})["long_rate"] = {"after": int(over.group(1).replace(",", "")), **entry}
            continue
        out.setdefault(model, {}).update(entry)
    if not out:
        raise ValueError("Anthropic page: no price rows found")
    return out


def _clean_google(cell: str) -> str:
    cell = re.sub(r"\^\\?\*+\^|\\\*", "", cell)
    return cell.replace("\\<", "<").replace("\\>", ">").replace("\\=", "=")


def _google_cell(cell: str) -> dict | None:
    """One 'Paid Tier' cell: a base price, optionally a larger price over a prompt size, optionally dated."""
    cell = _clean_google(cell)
    cell = re.sub(r"\$[\d.,]+\s*/\s*1,000,000 tokens per hour \(storage price\)", "", cell)
    cell = re.sub(r"\(audio\)\s*\$[\d.]+|\$[\d.]+\s*\(audio\)", "", cell, flags=re.I)
    result: dict = {}
    dated = re.search(r"\$([\d.]+) through ([A-Z][a-z]+ \d+, \d{4})\.\s*\$([\d.]+) starting ([A-Z][a-z]+ \d+, \d{4})", cell)
    if dated:
        result["value"] = float(dated.group(1))
        result["then"] = {"from": _iso(dated.group(4)), "value": float(dated.group(3))}
        return result
    tiered = re.search(r"\$([\d.]+),?\s*prompts\s*<=\s*([\d.]+)k tokens\s*\$([\d.]+),?\s*prompts\s*>\s*[\d.]+k", cell)
    if tiered:
        return {"value": float(tiered.group(1)), "after": int(float(tiered.group(2)) * 1000), "long_value": float(tiered.group(3))}
    base = re.match(r"\s*\$([\d.]+)", cell)
    if base and not re.search(r"through|starting|prompts", cell):
        return {"value": float(base.group(1))}
    return None


def _iso(text: str) -> str:
    months = {m: i for i, m in enumerate(("January February March April May June July August September October November December").split(), 1)}
    month, day, year = re.match(r"([A-Z][a-z]+) (\d+), (\d{4})", text).groups()
    return f"{int(year):04d}-{months[month]:02d}-{int(day):02d}"


def read_google(text: str) -> dict:
    out: dict = {"_skipped": {}}
    sections = re.split(r"(?m)^## ", text)
    for section in sections[1:]:
        ids = re.findall(r"`(gemini-[a-z0-9.\-]+)`", section.split("\n### ")[0])
        if not ids:
            continue
        standard = re.search(r"### Standard\n(.*?)(?=\n### |\Z)", section, re.S)
        if not standard:
            continue
        rows = {}
        for line in standard.group(1).splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 3:
                rows[cells[0].lower()] = cells[2]
        pick = lambda prefix: next((v for k, v in rows.items() if k.startswith(prefix)), None)
        cells = {"input": pick("input price"), "output": pick("output price"), "cached": pick("context caching price")}
        if not cells["input"] or not cells["output"]:
            continue
        parsed = {k: _google_cell(v) for k, v in cells.items() if v}
        model = ids[0]
        if None in (parsed.get("input"), parsed.get("output")):
            out["_skipped"][model] = "price text not understood; review by hand"
            continue
        entry = {"input": parsed["input"]["value"], "output": parsed["output"]["value"]}
        if parsed.get("cached"):
            entry["cached"] = parsed["cached"]["value"]
        entry["write"] = entry["input"]
        first = parsed["input"]
        if "after" in first:
            entry["long"] = {"after": first["after"], "input_multiplier": round(first["long_value"] / first["value"], 6),
                             "output_multiplier": round(parsed["output"]["long_value"] / parsed["output"]["value"], 6)}
        if "then" in first:
            later = {"from": first["then"]["from"], "input": first["then"]["value"], "write": first["then"]["value"]}
            if parsed["output"].get("then"):
                later["output"] = parsed["output"]["then"]["value"]
            if parsed.get("cached") and parsed["cached"].get("then"):
                later["cached"] = parsed["cached"]["then"]["value"]
            entry["changes"] = [later]
        for alias in ids:
            out[alias] = entry
    return out


def read_xai(text: str) -> dict:
    """xAI's Text API pricing table: one row per model for prompts under 200k tokens and one for 200k and over
    (billed at the higher rate for every token in the request)."""
    out: dict = {}
    row = re.compile(r"^\|\s*(grok-[\w.\-]+)\s*\((<|≥)\s*200k prompt tokens\)\s*\|[^|]*\|\s*\$([\d.]+)\s*\|\s*\$([\d.]+)\s*\|\s*\$([\d.]+)\s*\|", re.M)
    for model, tier, i, c, o in row.findall(text):
        values = {"input": float(i), "cached": float(c), "output": float(o)}
        if tier == "<":
            out.setdefault(model, {}).update(values, write=float(i))
        else:
            out.setdefault(model, {})["long_rate"] = {"after": 200_000, **values}
    if not out:
        raise ValueError("xAI page: no price rows found")
    return out


def read_openrouter(text: str) -> dict:
    data = json.loads(text)["data"]
    out: dict = {}
    for model in data:
        pricing = model.get("pricing") or {}
        try:
            prompt, completion = float(pricing.get("prompt", "x")), float(pricing.get("completion", "x"))
        except ValueError:
            continue
        out[model["id"]] = {"input": prompt * 1e6, "output": completion * 1e6}
    return out


READERS = {"openai": read_openai, "anthropic": read_anthropic, "google": read_google, "xai": read_xai, "openrouter": read_openrouter}


# ---------------------------------------------------------------------------- comparison


def same(a, b) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= TOLERANCE * max(1.0, abs(float(b)))


def source_id(model: str, entry: dict) -> str:
    """The id a model has on its source page when MCD's id differs (Claude ids use dashes in versions)."""
    return entry.get("source_id") or model


def compare(catalog: dict, source: str, page: dict) -> dict:
    """Differences for the catalog's models that belong to one source."""
    report = {"source": source, "checked": 0, "same": [], "differs": [], "missing": [], "review": [], "changes": {}}
    skipped = page.get("_skipped", {})
    for model, entry in catalog["models"].items():
        if entry.get("source") != source:
            continue
        key = source_id(model, entry)
        report["checked"] += 1
        found = page.get(key)
        if found is None:
            reason = skipped.get(key)
            (report["review"] if reason else report["missing"]).append({"model": model, "note": reason or "not on the source page"})
            continue
        diffs = {}
        for field in PRICE_FIELDS:
            if field in found and not same(entry.get(field), found[field]):
                diffs[field] = {"catalog": entry.get(field), "source": found[field]}
        long_page = found.get("long") or {}
        if long_page:
            for field, own in (("input_multiplier", "long_input_multiplier"), ("output_multiplier", "long_output_multiplier")):
                if field in long_page and not same(entry.get(own), long_page[field]):
                    diffs[own] = {"catalog": entry.get(own), "source": long_page[field]}
            if long_page.get("after") != entry.get("long_after"):
                diffs["long_after"] = {"catalog": entry.get("long_after"), "source": long_page["after"]}
        rate = found.get("long_rate")
        if rate and entry.get("long_after") == rate["after"]:
            if not same(entry["input"] * entry.get("long_input_multiplier", 1), rate["input"]):
                diffs["long_input_multiplier"] = {"catalog": entry.get("long_input_multiplier"), "source": round(rate["input"] / entry["input"], 6)}
            if not same(entry["output"] * entry.get("long_output_multiplier", 1), rate["output"]):
                diffs["long_output_multiplier"] = {"catalog": entry.get("long_output_multiplier"), "source": round(rate["output"] / entry["output"], 6)}
        for field in ("changes",):
            if found.get(field) and found[field] != entry.get(field):
                diffs["changes"] = {"catalog": entry.get(field), "source": found[field]}
        if diffs:
            report["differs"].append({"model": model, "fields": diffs})
        else:
            report["same"].append(model)
    return report


def compare_free(catalog: dict, page: dict) -> dict:
    report = {"source": "openrouter free models", "checked": 0, "same": [], "differs": [], "missing": [], "review": [], "changes": {}}
    for model in catalog.get("free_models", {}):
        report["checked"] += 1
        found = page.get(model)
        if found is None:
            report["missing"].append({"model": model, "note": "no longer listed on OpenRouter"})
        elif found["input"] != 0 or found["output"] != 0:
            report["differs"].append({"model": model, "fields": {"input": {"catalog": 0, "source": found["input"]}, "output": {"catalog": 0, "source": found["output"]}}})
        else:
            report["same"].append(model)
    return report


def new_on_page(catalog: dict, source: str, page: dict) -> list[str]:
    known = {source_id(m, e) for m, e in catalog["models"].items()}
    if source == "openai":
        names = [m for m in page if re.match(r"gpt-\d", m) and "pro" not in m]
    elif source == "anthropic":
        names = [m for m in page if m.startswith("claude-") and not m.endswith("-4") and not m.endswith("-4-1")]
    elif source == "xai":
        names = [m for m in page if m.startswith("grok-") and "imagine" not in m]
    elif source == "google":
        names = [m for m in page if m.startswith("gemini-") and not m.startswith("_") and not re.search(r"tts|image|live|audio|embedding|robotics|transcribe|translate", m)]
    else:
        names = []
    return sorted(set(names) - known)


# ---------------------------------------------------------------------------- models in use


PLATFORMS = {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google", "xai": "xAI"}


def used_unpriced(session) -> dict[str, set[str]]:
    """{model: agents} for models used this month that the catalog has no price for. Free models and
    models that have a price (whose odd records are a data problem, not a catalog gap) are left out."""
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    import billing

    rates = billing.config(session)["rates"]
    found: dict[str, set[str]] = {}
    for agent in billing.dashboard(session, "month")["overview"]:
        for model in agent.get("unpriced_models", []):
            if model != "not reported" and not billing.is_free(model) and billing.find_rate(model, rates) is None:
                found.setdefault(model, set()).add(agent["agent"])
    return found


def match_page(model: str, pages: dict) -> tuple[str, str, dict] | None:
    """(source, page id, prices) when a page lists the model, also behind a gateway or vendor prefix."""
    parts = model.split("/")
    for i in range(len(parts)):
        name = "/".join(parts[i:])
        for key in (name, re.sub(r"-\d{8}$", "", name)):
            for source in ("openai", "anthropic", "google", "xai"):
                found = pages.get(source, {}).get(key)
                if found:
                    return source, key, found
    return None


def candidate_entry(model: str, source: str, found: dict, agents: set[str], today: str) -> dict:
    """A catalog entry for a newly used model, from what the page states. Limits the page does not state are
    set so that a request over them stays unpriced instead of being priced wrongly: review before trusting."""
    entry = {"platform": PLATFORMS[source], "source": source, "agents": sorted(agents), "status": "current"}
    for field in ("input", "output", "cached", "write", "write_1h"):
        if field in found:
            entry[field] = found[field]
    entry.setdefault("cached", entry["input"])
    entry.setdefault("write", entry["input"])
    entry.setdefault("write_1h", entry["write"])
    if found.get("long"):
        entry.update(max_input=None, long_after=found["long"]["after"], long_input_multiplier=found["long"]["input_multiplier"],
                     long_output_multiplier=found["long"]["output_multiplier"])
    elif found.get("long_rate"):
        rate = found["long_rate"]
        entry.update(max_input=None, long_after=rate["after"], long_input_multiplier=round(rate["input"] / entry["input"], 6),
                     long_output_multiplier=round(rate["output"] / entry["output"], 6))
    elif source == "anthropic":
        version = re.search(r"-(\d+)-(\d+)$", model) or re.search(r"-(\d+)$", model)
        major, minor = (int(version.group(1)), int(version.group(2) if version.lastindex == 2 else 0)) if version else (0, 0)
        entry["max_input"] = None if (major, minor) >= (4, 6) else 200_000   # 1M context at standard price from 4.6
    elif source == "google":
        entry["max_input"] = None
    else:
        entry["max_input"] = 272_000   # the page states only the short-context price
    if found.get("changes"):
        entry["changes"] = found["changes"]
    entry["verified"] = today
    return entry


# ---------------------------------------------------------------------------- run


def fetch(url: str, headers: dict | None = None) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "rcd-pricing-check/1", **(headers or {})})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def apply(catalog: dict, reports: list[dict], today: str) -> int:
    changed = 0
    for report in reports:
        for item in report["differs"]:
            entry = catalog["models"].get(item["model"])
            if entry is None:
                continue
            for field, values in item["fields"].items():
                entry[field] = values["source"]
                changed += 1
        for model in report["same"] + [d["model"] for d in report["differs"]]:
            if model in catalog["models"]:
                catalog["models"][model]["verified"] = today
            elif model in catalog.get("free_models", {}):
                catalog["free_models"][model]["verified"] = today
    catalog["verified"] = today
    return changed


def run_used(args, catalog: dict, pages: dict, problems: int) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    with Session(create_engine(f"sqlite:///{args.db}")) as session:
        used = used_unpriced(session)
    if not used:
        print("every model used this month has a price")
        return 1 if problems else 0
    today, added, open_gaps = date.today().isoformat(), 0, 0
    for model, agents in sorted(used.items()):
        match = match_page(model, pages)
        if match is None:
            open_gaps += 1
            print(f"  NO PRICE FOUND  {model}  (used by {', '.join(sorted(agents))}): not on the pages checked; add a rate in Billing & rates or the catalog by hand")
            continue
        source, key, found = match
        entry = candidate_entry(model, source, found, agents, today)
        print(f"  {'ADDED' if args.add else 'CAN ADD'}  {model}  from {source}: input {entry['input']}, output {entry['output']}, cache read {entry['cached']}; "
              f"review the long-context limit ({entry.get('long_after') or entry.get('max_input') or 'none'})")
        if args.add:
            catalog["models"][model] = entry
            added += 1
    if args.add and added:
        Path(args.catalog).write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
        print(f"catalog updated: {added} model(s) added; review the diff and release it")
    return 1 if open_gaps or problems or (not args.add) else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--source", choices=sorted(READERS))
    parser.add_argument("--offline", metavar="DIR")
    parser.add_argument("--new", action="store_true")
    parser.add_argument("--used", action="store_true")
    parser.add_argument("--add", action="store_true", help="with --used: add the models the pages list")
    parser.add_argument("--db", default=str(Path.home() / ".rcd-control" / "data.db"))
    parser.add_argument("--catalog", default=str(CATALOG))
    args = parser.parse_args(argv)

    catalog = json.loads(Path(args.catalog).read_text())
    reports, pages, problems = [], {}, 0
    for source, spec in catalog["sources"].items():
        if args.source and source != args.source:
            continue
        try:
            text = (Path(args.offline) / f"{source}.txt").read_text() if args.offline else fetch(spec["url"], spec.get("headers"))
            pages[source] = READERS[source](text)
        except Exception as exc:  # a source that cannot be read is reported, never treated as unchanged
            print(f"{source}: could not read {spec['url']}: {exc}")
            problems += 1
            continue
        reports.append(compare(catalog, source, pages[source]))
        if source == "openrouter":
            reports.append(compare_free(catalog, pages[source]))

    if args.used:
        return run_used(args, catalog, pages, problems)

    differs = 0
    for report in reports:
        if not report["checked"]:
            continue
        print(f"{report['source']}: {report['checked']} checked, {len(report['same'])} match")
        for item in report["differs"]:
            differs += 1
            for field, v in item["fields"].items():
                print(f"  DIFFERS  {item['model']}  {field}: catalog {v['catalog']} -> source {v['source']}")
        for item in report["missing"]:
            print(f"  MISSING  {item['model']}: {item['note']}")
        for item in report["review"]:
            print(f"  REVIEW   {item['model']}: {item['note']}")
    if args.new:
        for source, page in pages.items():
            names = new_on_page(catalog, source, page)
            if names:
                print(f"{source}: on the page, not in the catalog: {', '.join(names)}")
    if args.apply and reports:
        changed = apply(catalog, reports, date.today().isoformat())
        Path(args.catalog).write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
        print(f"catalog updated: {changed} price field(s) changed, verification date {catalog['verified']}")
        return 1 if problems else 0
    return 1 if differs or problems else 0


if __name__ == "__main__":
    sys.exit(main())
