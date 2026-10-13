#!/usr/bin/env python3
"""Tiny static docs-site generator used by the RCD demo project.

Reads content/*.md and changelog.json, writes site/index.html, one page per
Markdown file and site/changelog.html. Standard library only.

    python3 build.py --theme light|dark|auto
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

PAGE = """<!doctype html>
<html lang="en" data-theme="{theme}">
<head><meta charset="utf-8"><title>{title} · RCD demo docs</title>
<style>
:root {{ --bg:#fff; --fg:#1b1f24; --link:#0b5fff; }}
html[data-theme="dark"] {{ --bg:#14171c; --fg:#e6e9ee; --link:#6ea8ff; }}
@media (prefers-color-scheme: dark) {{ html[data-theme="auto"] {{ --bg:#14171c; --fg:#e6e9ee; --link:#6ea8ff; }} }}
body {{ background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,sans-serif; max-width:46rem; margin:2rem auto; padding:0 1rem; }}
a {{ color:var(--link); }} nav a {{ margin-right:1rem; }} code,pre {{ background:rgba(127,127,127,.15); padding:.1rem .3rem; }}
</style></head>
<body><nav>{nav}</nav><main>
{body}
</main></body></html>
"""


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)


def markdown(source: str) -> str:
    out: list[str] = []
    in_list = False
    for line in source.splitlines():
        heading = re.match(r"(#{1,3})\s+(.*)", line)
        item = re.match(r"[-*]\s+(.*)", line)
        if in_list and not item:
            out.append("</ul>")
            in_list = False
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
        elif item:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(item.group(1))}</li>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def changelog_html(entries: list[dict]) -> str:
    rows = ["<h1>Changelog</h1>"]
    for entry in sorted(entries, key=lambda e: e["date"], reverse=True):
        rows.append(f"<h2>{html.escape(entry['version'])} <small>{html.escape(entry['date'])}</small></h2><ul>")
        rows += [f"<li>{inline(change)}</li>" for change in entry["changes"]]
        rows.append("</ul>")
    return "\n".join(rows)


def build(root: Path, theme: str) -> list[str]:
    pages = {p.stem: p for p in sorted((root / "content").glob("*.md"))}
    if "index" not in pages:
        raise SystemExit("content/index.md is required")
    entries = json.loads((root / "changelog.json").read_text())
    names = ["index", *[n for n in pages if n != "index"], "changelog"]
    nav = "".join(f'<a href="{n}.html">{n}</a>' for n in names)
    site = root / "site"
    site.mkdir(exist_ok=True)
    written = []
    for name, path in pages.items():
        title = path.read_text().splitlines()[0].lstrip("# ").strip() or name
        (site / f"{name}.html").write_text(PAGE.format(theme=theme, title=html.escape(title), nav=nav, body=markdown(path.read_text())))
        written.append(f"{name}.html")
    (site / "changelog.html").write_text(PAGE.format(theme=theme, title="Changelog", nav=nav, body=changelog_html(entries)))
    written.append("changelog.html")
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=["light", "dark", "auto"], default="auto")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print("built:", ", ".join(build(args.root, args.theme)))
