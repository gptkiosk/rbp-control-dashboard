#!/usr/bin/env python3
"""Keep the Agent tools catalog (apps/api/tool_catalog.json) pinned, hash-locked and current.

  scripts/tools/check.py                   report which pinned tools have a newer release; exit 1 when any do
  scripts/tools/check.py --verify          offline: the catalog validates and every lock file matches its hash; exit 1 if not
  scripts/tools/check.py --rehash          offline: rewrite the lock-file hashes in the catalog from the files on disk
  scripts/tools/check.py --apply ID [ID…]  adopt the newer release of the named tool(s): regenerate the npm lock with
                                           `npm install --package-lock-only --ignore-scripts`, or fetch the new archive /
                                           installer hash from the publisher, then rehash and validate
  scripts/tools/check.py --offline DIR     read saved answers from DIR instead of the network (tests)

Where the answers come from (nothing here talks to a model or an account, and nothing is installed):
  npm tools   https://registry.npmjs.org/<package>/latest
  Node.js     https://nodejs.org/dist/index.json (same major line), and that release's SHASUMS256.txt
  Hermes      the latest GitHub release of NousResearch/hermes-agent, the commit its tag points at, and the sha256 of
              scripts/install.sh at that commit (Hermes's own installer pins its toolchain in pm/lock.json at that commit)

A bump is only ever proposed here; adopting it is a reviewed commit (and the tool is then tried in the Lima guest).
Versions are adopted exactly as published: the checker never installs or runs the new release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"
CATALOG = API / "tool_catalog.json"
sys.path.insert(0, str(API))
import tool_install as ti  # noqa: E402  (standard library only)

UA = {"User-Agent": "rcd-tool-check", "Accept": "application/json"}


# ---------------------------------------------------------------------------- sources


class Source:
    """Where published answers come from. Tests replace this with saved files."""

    def json(self, url: str):
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read(8 * 1024 * 1024))

    def text(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "rcd-tool-check"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read(8 * 1024 * 1024)


class SavedSource(Source):
    """Reads `<dir>/<slug of the URL>` where the slug replaces every non-alphanumeric run with `_`."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _path(self, url: str) -> Path:
        return self.folder / re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1]).strip("_")

    def json(self, url: str):
        return json.loads(self._path(url).read_text())

    def text(self, url: str) -> bytes:
        return self._path(url).read_bytes()


def latest_npm(src: Source, package: str) -> str:
    return src.json(f"https://registry.npmjs.org/{package.replace('/', '%2F')}/latest")["version"]


def latest_node(src: Source, current: str) -> dict:
    """Newest release on the same major line. Returns {version, sha256, size_url}."""
    major = current.split(".")[0]
    rows = [r for r in src.json("https://nodejs.org/dist/index.json") if r["version"].startswith(f"v{major}.")]
    if not rows:
        raise ValueError(f"nodejs.org lists no v{major} release")
    version = max((r["version"] for r in rows), key=lambda v: tuple(int(x) for x in v[1:].split(".")))
    return {"version": version[1:]}


def latest_hermes(src: Source) -> dict:
    release = src.json("https://api.github.com/repos/NousResearch/hermes-agent/releases/latest")
    tag = release["tag_name"]
    commit = src.json(f"https://api.github.com/repos/NousResearch/hermes-agent/commits/{tag}")["sha"]
    script = src.text(f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{commit}/scripts/install.sh")
    return {"version": tag.lstrip("v"), "tag": tag, "commit": commit, "sha256": hashlib.sha256(script).hexdigest(),
            "size": len(script)}


def newest(src: Source, catalog: dict) -> dict:
    """{id: {version, …}} for every component, as published now."""
    found = {}
    for cid, comp in catalog["tools"].items():
        if comp["installer"] == "npm-lock":
            found[cid] = {"version": latest_npm(src, comp["package"])}
        elif comp["installer"] == "binary":
            found[cid] = {"version": src.text("https://x.ai/cli/stable").decode().strip()}
        else:
            found[cid] = latest_hermes(src)
    found["node"] = latest_node(src, catalog["runtimes"]["node"]["version"])
    return found


def newer(a: str, b: str) -> bool:
    """True when version `a` is later than `b` (numeric parts; anything else compares as text)."""
    def key(v):
        return [(0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"[.\-+]", v)]
    return key(a) > key(b)


# ---------------------------------------------------------------------------- catalog


def load() -> dict:
    return json.loads(CATALOG.read_text())


def save(catalog: dict) -> None:
    CATALOG.write_text(json.dumps(catalog, indent=2) + "\n")


def rehash(catalog: dict) -> list[str]:
    """Set each npm tool's lock hashes from the files on disk. Returns what changed."""
    changed = []
    for cid, comp in catalog["tools"].items():
        if comp["installer"] != "npm-lock":
            continue
        folder = API / comp["lock_dir"]
        for fname, key in (("package.json", "package_json_sha256"), ("package-lock.json", "package_lock_sha256")):
            got = ti.sha256_file(folder / fname)
            if comp["lock"][key] != got:
                comp["lock"][key] = got
                changed.append(f"{cid}: {fname}")
    return changed


def problems(catalog: dict) -> list[str]:
    return ti.catalog_problems(catalog, API)


# ---------------------------------------------------------------------------- applying a bump


def write_package_json(comp: dict, cid: str, version: str) -> None:
    folder = API / comp["lock_dir"]
    (folder / "package.json").write_text(json.dumps({
        "name": f"rcd-tool-{cid}", "version": "0.0.0", "private": True,
        "description": f"Pinned install of {comp['package']} for the dashboard's Agent tools panel. "
                       "Bumped only by scripts/tools/check.py.",
        "dependencies": {comp["package"]: version},
    }, indent=2) + "\n")


def apply_bump(catalog: dict, cid: str, found: dict, src: Source, runner=subprocess.run) -> str:
    comp = catalog["tools"].get(cid) or catalog["runtimes"].get(cid)
    if comp is None:
        raise SystemExit(f"unknown tool {cid!r}")
    old = comp["version"]
    if comp["installer"] == "npm-lock":
        write_package_json(comp, cid, found["version"])
        folder = API / comp["lock_dir"]
        (folder / "package-lock.json").unlink(missing_ok=True)
        result = runner(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund",
                         "--registry=https://registry.npmjs.org/"], cwd=folder, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise SystemExit(f"npm could not lock {cid} {found['version']}: {result.stderr[-300:]}")
        comp["version"] = found["version"]
        comp["check"]["expect"] = found["version"]
    elif cid == "hermes":
        base = f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{found['commit']}/scripts/install.sh"
        comp.update(version=found["version"], tag=found["tag"], commit=found["commit"])
        comp["script"] = {"url": base, "sha256": found["sha256"], "size": found["size"]}
        comp["check"]["expect"] = found["version"]
    elif cid == "grok":
        v = found["version"]
        if not ti.VERSION.fullmatch(v):
            raise SystemExit("bad Grok version from publisher")
        for platform, suffix in (("linux-arm64", "linux-aarch64"), ("darwin-arm64", "macos-aarch64")):
            url = f"https://x.ai/cli/grok-{v}-{suffix}"
            comp["binary"][platform] = {"url": url, **src_pin(src, url)}
        comp["version"] = v
        comp["check"]["expect"] = v
    elif cid == "node":
        v = found["version"]
        sums = src.text(f"https://nodejs.org/dist/v{v}/SHASUMS256.txt").decode()
        for platform, archive in comp["archive"].items():
            suffix, extension = ("darwin-arm64", "tar.gz") if platform == "darwin-arm64" else ("linux-arm64", "tar.xz")
            name = f"node-v{v}-{suffix}.{extension}"
            line = next((ln for ln in sums.splitlines() if ln.endswith("  " + name)), None)
            if line is None:
                raise SystemExit(f"nodejs.org SHASUMS256.txt for v{v} does not list {name}")
            archive.update(url=f"https://nodejs.org/dist/v{v}/{name}", sha256=line.split()[0], root=f"node-v{v}-{suffix}",
                           shasums_url=f"https://nodejs.org/dist/v{v}/SHASUMS256.txt")
            archive["size"] = int(src_size(src, archive["url"]))
        comp["version"] = v
        comp["check"]["expect"] = f"v{v}"
    rehash(catalog)
    catalog["checked"] = __import__("datetime").date.today().isoformat()
    bad = problems(catalog)
    if bad:
        raise SystemExit("the catalog does not validate after the bump:\n  " + "\n  ".join(bad))
    return f"{cid}: {old} -> {comp['version']}"


def src_pin(src: Source, url: str) -> dict:
    """Hash the official binary before adopting it; never run the downloaded program."""
    if isinstance(src, SavedSource):
        return json.loads(src.text(url + ".pin"))
    digest, size = hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=60) as response:
        while chunk := response.read(1 << 20):
            size += len(chunk)
            if size > 512 * 1024 ** 2:
                raise SystemExit("binary exceeds download limit")
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "size": size}


def src_size(src: Source, url: str) -> int:
    """Size of a release file. Real run: a HEAD request; saved answers: a `.size` file beside the slug."""
    if isinstance(src, SavedSource):
        return int(src.text(url + ".size").decode().strip())
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "rcd-tool-check"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return int(resp.headers["Content-Length"])


# ---------------------------------------------------------------------------- command line


def main(argv: list[str] | None = None, src: Source | None = None, runner=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--rehash", action="store_true")
    ap.add_argument("--apply", nargs="+", metavar="ID")
    ap.add_argument("--offline", metavar="DIR")
    args = ap.parse_args(argv)
    catalog = load()

    if args.rehash:
        changed = rehash(catalog)
        save(catalog)
        print("rehashed: " + (", ".join(changed) if changed else "nothing changed"))
        return 0
    if args.verify:
        bad = problems(catalog)
        for line in bad:
            print(f"problem: {line}")
        print("catalog ok: every source is pinned and every lock file matches its hash" if not bad else "")
        return 1 if bad else 0

    src = src or (SavedSource(Path(args.offline)) if args.offline else Source())
    found = newest(src, catalog)
    behind = []
    for cid in [*catalog["tools"], *catalog["runtimes"]]:
        comp = catalog["tools"].get(cid) or catalog["runtimes"][cid]
        latest = found[cid]["version"]
        flag = "newer release" if newer(latest, comp["version"]) else ("pinned is ahead of the latest release" if newer(comp["version"], latest) else "current")
        print(f"{cid:12} pinned {comp['version']:12} latest {latest:12} {flag}")
        if newer(latest, comp["version"]):
            behind.append(cid)
    if args.apply:
        for cid in args.apply:
            if cid not in found:
                raise SystemExit(f"unknown tool {cid!r}")
            if cid not in behind:
                print(f"{cid}: already at the latest release; nothing to adopt")
                continue
            print("adopted " + apply_bump(catalog, cid, found[cid], src, runner))
            save(catalog)
        print("Review the diff, then try the tool in the Lima guest before committing.")
        return 0
    if behind:
        print("\nTo adopt one: scripts/tools/check.py --apply " + " ".join(behind[:1]) + "   (then review and test it)")
    return 1 if behind else 0


if __name__ == "__main__":
    sys.exit(main())
