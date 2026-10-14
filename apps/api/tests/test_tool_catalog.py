"""The Agent tools catalog, its checker (scripts/tools/check.py) and its place in the release package. No network."""
from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

import tool_install as ti

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps" / "api"
spec = importlib.util.spec_from_file_location("tools_check", ROOT / "scripts" / "tools" / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A private copy of the catalog and lock files that the checker is pointed at, so nothing real is rewritten."""
    api = tmp_path / "api"
    api.mkdir()
    shutil.copy(API / "tool_catalog.json", api / "tool_catalog.json")
    shutil.copytree(API / "tool_locks", api / "tool_locks")
    monkeypatch.setattr(check, "API", api)
    monkeypatch.setattr(check, "CATALOG", api / "tool_catalog.json")
    return api


def slug(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1]).strip("_")


def saved(tmp_path, answers: dict) -> check.SavedSource:
    folder = tmp_path / "saved"
    folder.mkdir()
    for url, value in answers.items():
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        (folder / slug(url)).write_bytes(data)
    return check.SavedSource(folder)


def current_answers() -> dict:
    """What the publishers say right now, as this catalog already pins it."""
    raw = json.loads((API / "tool_catalog.json").read_text())
    h = raw["tools"]["hermes"]
    script = b"#!/bin/bash\n# a pinned script\n"
    answers = {
        "https://nodejs.org/dist/index.json": [{"version": "v25.1.0"}, {"version": f"v{raw['runtimes']['node']['version']}"}, {"version": "v24.2.0"}],
        "https://api.github.com/repos/NousResearch/hermes-agent/releases/latest": {"tag_name": h["tag"]},
        f"https://api.github.com/repos/NousResearch/hermes-agent/commits/{h['tag']}": {"sha": h["commit"]},
        f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{h['commit']}/scripts/install.sh": script,
    }
    answers["https://x.ai/cli/stable"] = raw["tools"]["grok"]["version"].encode()
    for cid, comp in raw["tools"].items():
        if comp["installer"] == "npm-lock":
            answers[f"https://registry.npmjs.org/{comp['package'].replace('/', '%2F')}/latest"] = {"version": comp["version"]}
    return answers


# --- the catalog on disk -----------------------------------------------------------------------------------------


def test_verify_passes_on_the_committed_catalog_and_fails_on_a_tampered_lock(repo, capsys):
    assert check.main(["--verify"]) == 0
    lock = repo / "tool_locks" / "codex" / "package-lock.json"
    lock.write_text(lock.read_text().replace("sha512-", "sha512-A", 1))
    assert check.main(["--verify"]) == 1
    assert "does not match the catalog hash" in capsys.readouterr().out
    assert check.main(["--rehash"]) == 0 and check.main(["--verify"]) == 0           # rehash is the deliberate step


def test_every_pinned_hash_in_the_catalog_has_the_right_shape():
    raw = json.loads((API / "tool_catalog.json").read_text())
    hashes = []
    for comp in raw["tools"].values():
        hashes += list(comp.get("lock", {}).values()) + [comp.get("script", {}).get("sha256")]
        hashes += [a["sha256"] for a in comp.get("binary", {}).values()]
    for comp in raw["runtimes"].values():
        hashes += [a["sha256"] for a in comp["archive"].values()]
    hashes = [h for h in hashes if h]
    assert len(hashes) == 3 * 2 + 1 + 2 + 2 and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)


# --- the checker -------------------------------------------------------------------------------------------------


def test_the_checker_reports_nothing_to_do_when_every_pin_is_current(repo, tmp_path, capsys):
    code = check.main([], src=saved(tmp_path, current_answers()))
    out = capsys.readouterr().out
    assert code == 0 and out.count("current") == 6 and "newer release" not in out


def test_the_checker_proposes_bumps_without_changing_anything(repo, tmp_path, capsys):
    answers = current_answers()
    answers["https://registry.npmjs.org/@openai%2Fcodex/latest"] = {"version": "0.163.0"}
    answers["https://nodejs.org/dist/index.json"].append({"version": "v24.99.1"})
    before = (repo / "tool_catalog.json").read_bytes()
    code = check.main([], src=saved(tmp_path, answers))
    out = capsys.readouterr().out
    assert code == 1
    assert re.search(r"codex\s+pinned 0.162.1\s+latest 0.163.0\s+newer release", out)
    assert re.search(r"node\s+pinned 24.21.0\s+latest 24.99.1\s+newer release", out)       # same major line only: v25 is not proposed
    assert "scripts/tools/check.py --apply" in out
    assert (repo / "tool_catalog.json").read_bytes() == before


def test_applying_an_npm_bump_regenerates_the_lock_and_rehashes_the_catalog(repo, tmp_path):
    answers = current_answers()
    answers["https://registry.npmjs.org/@openai%2Fcodex/latest"] = {"version": "0.163.0"}
    calls = []

    class Done:
        returncode, stderr = 0, ""

    def fake_npm(argv, cwd, **kw):
        calls.append((argv, Path(cwd).name))
        lock = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/@openai/codex": {
            "version": "0.163.0", "resolved": "https://registry.npmjs.org/@openai/codex/-/codex-0.163.0.tgz", "integrity": "sha512-abc"}}}
        (Path(cwd) / "package-lock.json").write_text(json.dumps(lock))
        return Done()

    code = check.main(["--apply", "codex"], src=saved(tmp_path, answers), runner=fake_npm)
    assert code == 0
    (argv, folder), = calls
    assert argv[:3] == ["npm", "install", "--package-lock-only"] and "--ignore-scripts" in argv and folder == "codex"
    raw = json.loads((repo / "tool_catalog.json").read_text())
    assert raw["tools"]["codex"]["version"] == "0.163.0" and raw["tools"]["codex"]["check"]["expect"] == "0.163.0"
    assert json.loads((repo / "tool_locks/codex/package.json").read_text())["dependencies"] == {"@openai/codex": "0.163.0"}
    assert ti.catalog_problems(raw, repo) == []                         # the new pin validates, hashes included
    assert raw["tools"]["claude-code"]["version"] == "2.1.299"          # nothing else moved


def test_applying_a_hermes_bump_pins_the_new_commit_and_installer_hash(repo, tmp_path):
    answers = current_answers()
    new = "a" * 40
    script = b"#!/bin/bash\n# the new installer\n"
    answers["https://api.github.com/repos/NousResearch/hermes-agent/releases/latest"] = {"tag_name": "v0.22.1"}
    answers["https://api.github.com/repos/NousResearch/hermes-agent/commits/v0.22.1"] = {"sha": new}
    answers[f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{new}/scripts/install.sh"] = script
    assert check.main(["--apply", "hermes"], src=saved(tmp_path, answers)) == 0
    h = json.loads((repo / "tool_catalog.json").read_text())["tools"]["hermes"]
    assert (h["version"], h["tag"], h["commit"]) == ("0.22.1", "v0.22.1", new)
    assert h["script"] == {"url": f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{new}/scripts/install.sh",
                           "sha256": hashlib.sha256(script).hexdigest(), "size": len(script)}
    assert h["check"]["expect"] == "0.22.1"


def test_applying_a_node_bump_takes_the_hash_from_the_publishers_shasums(repo, tmp_path):
    answers = current_answers()
    answers["https://nodejs.org/dist/index.json"].append({"version": "v24.30.0"})
    sha = "c" * 64
    answers["https://nodejs.org/dist/v24.30.0/SHASUMS256.txt"] = f"{'d' * 64}  node-v24.30.0-darwin-arm64.tar.gz\n{sha}  node-v24.30.0-linux-arm64.tar.xz\n".encode()
    answers["https://nodejs.org/dist/v24.30.0/node-v24.30.0-linux-arm64.tar.xz.size"] = b"31000000\n"
    answers["https://nodejs.org/dist/v24.30.0/node-v24.30.0-darwin-arm64.tar.gz.size"] = b"53000000\n"
    assert check.main(["--apply", "node"], src=saved(tmp_path, answers)) == 0
    a = json.loads((repo / "tool_catalog.json").read_text())["runtimes"]["node"]["archive"]["linux-arm64"]
    assert a["sha256"] == sha and a["size"] == 31000000 and a["root"] == "node-v24.30.0-linux-arm64"
    assert a["url"].endswith("v24.30.0/node-v24.30.0-linux-arm64.tar.xz") and a["shasums_url"].endswith("v24.30.0/SHASUMS256.txt")


def test_a_node_release_missing_from_its_own_shasums_is_not_adopted(repo, tmp_path):
    answers = current_answers()
    answers["https://nodejs.org/dist/index.json"].append({"version": "v24.30.0"})
    answers["https://nodejs.org/dist/v24.30.0/SHASUMS256.txt"] = b"dddd  something-else.tar.xz\n"
    with pytest.raises(SystemExit, match="does not list"):
        check.main(["--apply", "node"], src=saved(tmp_path, answers))
    assert json.loads((repo / "tool_catalog.json").read_text())["runtimes"]["node"]["version"] == "24.21.0"


# --- the release package -----------------------------------------------------------------------------------------


def test_the_catalog_and_every_lock_file_are_in_the_release_package():
    product = json.loads((ROOT / "packaging" / "product.json").read_text())
    patterns = product["include"]
    wanted = ["apps/api/tool_catalog.json", "apps/api/tool_install.py", "apps/api/tool_install_helper.py", "apps/api/routes/tool_installs.py"]
    wanted += [p.relative_to(ROOT).as_posix() for p in (API / "tool_locks").rglob("*") if p.is_file()]
    assert len(wanted) == 4 + 6
    missing = [rel for rel in wanted if not any(fnmatch.fnmatchcase(rel, pat) for pat in patterns)]
    assert missing == []
    # and the builder's own glob picks them up, not only fnmatch
    picked = {p.relative_to(ROOT).as_posix() for pat in patterns for p in ROOT.glob(pat) if p.is_file()}
    assert set(wanted) <= picked


def test_the_package_cannot_ship_a_node_modules_folder_or_a_stray_lock_file():
    product = json.loads((ROOT / "packaging" / "product.json").read_text())
    for pat in product["include"]:
        assert "node_modules" not in pat and not pat.endswith("**")
    stray = [p for p in (API / "tool_locks").rglob("*") if p.is_file() and p.name not in ("package.json", "package-lock.json")]
    assert stray == []
