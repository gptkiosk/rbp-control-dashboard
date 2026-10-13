#!/usr/bin/env python3
"""Structure and link check for the built demo site.

    python3 check_site.py [--root DIR]    writes DIR/report.json, exits 1 on any problem
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def check(root: Path) -> dict:
    site = root / "site"
    problems: list[str] = []
    pages = sorted(p.name for p in site.glob("*.html")) if site.is_dir() else []
    for required in ("index.html", "changelog.html"):
        if required not in pages:
            problems.append(f"missing {required}")
    themes = set()
    for name in pages:
        text = (site / name).read_text()
        match = re.search(r'data-theme="(\w+)"', text)
        themes.add(match.group(1) if match else "none")
        for target in re.findall(r'href="([^"#:]+\.html)"', text):
            if not (site / target).is_file():
                problems.append(f"{name} links to missing {target}")
    if len(themes) > 1:
        problems.append(f"mixed themes: {sorted(themes)}")
    return {"pages": pages, "themes": sorted(themes), "problems": problems, "ok": not problems}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = check(args.root)
    (args.root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    raise SystemExit(0 if report["ok"] else 1)
