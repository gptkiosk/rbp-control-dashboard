"""Agent tools installer engine: refusals, install, update, remove and rollback, with fake installers.

Nothing here touches the network, sudo, the real home folder or port 8800. The fake `Ops` writes small
synthetic tools whose `--version` prints the pinned version, and runs the *real* command wrappers for the
version checks, so the wrappers, links and receipts are exercised for real. A run of each real tool
is a separate step in a Lima guest (docs/install/agent-tools.md).
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

import tool_install as ti

API = Path(__file__).resolve().parents[1]
GB = 1024  # MB


# --- fixtures ----------------------------------------------------------------------------


@pytest.fixture
def catalog_dir(tmp_path):
    """A private copy of the real catalog and lock files, so tests can bump versions."""
    dest = tmp_path / "catalog"
    dest.mkdir()
    shutil.copy(API / "tool_catalog.json", dest / "tool_catalog.json")
    shutil.copytree(API / "tool_locks", dest / "tool_locks")
    return dest


@pytest.fixture
def cfg(tmp_path, catalog_dir):
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "tools-root"
    return ti.ToolsConfig(root=root, catalog_dir=catalog_dir, platform_key="linux-arm64", home=home)


@pytest.fixture
def catalog(cfg):
    return ti.load_catalog(cfg.catalog_dir)


def facts(**over) -> ti.HostFacts:
    base = dict(system="Linux", machine="aarch64", pointer_bits=64, os_name="Raspberry Pi OS", os_family="debian",
                euid=1000, mem_total_mb=3880, mem_available_mb=3000, disk_free_mb=20 * GB,
                commands={c: f"/usr/bin/{c}" for c in ti.PROBED_COMMANDS}, elsewhere={}, can_restrict_privileges=True)
    base.update(over)
    return ti.HostFacts(**base)


def make_tar(path: Path, root: str, files: dict, mode: str = "w:xz", extra=None):
    with tarfile.open(path, mode) as tf:
        top = tarfile.TarInfo(root)
        top.type = tarfile.DIRTYPE
        top.mode = 0o755
        tf.addfile(top)
        for name, (data, perm) in files.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size, info.mode = len(data), perm
            tf.addfile(info, io.BytesIO(data))
        for info in extra or []:
            tf.addfile(info)


def script(text: str) -> bytes:
    return ("#!/bin/sh\n" + text + "\n").encode()


class FakeOps:
    """Stands in for the network and for installers. Records every call so tests can assert on them."""

    def __init__(self, catalog, *, fail_fetch=None, fail_run=None, wrong_version=None):
        self.catalog, self.fail_fetch, self.fail_run, self.wrong_version = catalog, fail_fetch, fail_run, wrong_version
        self.fetched, self.ran, self.envs, self.shasums = [], [], [], []

    def fetch(self, url, dest, sha256, size):
        if self.fail_fetch and self.fail_fetch in url:
            raise ti.ToolError(f"{dest.name}: sha256 differs from the pinned value")
        self.fetched.append(url)
        if url.endswith("install.sh"):
            dest.write_bytes(b"#!/bin/bash\n# fake hermes installer\n")
            return
        comp = next(c for c in self.catalog.raw["runtimes"].values() if c["archive"]["linux-arm64"]["url"] == url)
        a = comp["archive"]["linux-arm64"]
        v = comp["version"]
        files = {"bin/node": (script(f'echo "v{v}"'), 0o755),
                 "bin/npm": (script("exit 0"), 0o755), "lib/README": (b"x", 0o644)}
        make_tar(dest, a["root"], files, "w:xz" if a["format"] == "tar.xz" else "w:gz")

    def fetch_text(self, url):
        self.shasums.append(url)
        comp = next(c for c in self.catalog.raw["runtimes"].values()
                    if c["archive"]["linux-arm64"].get("shasums_url") == url)
        a = comp["archive"]["linux-arm64"]
        return f"{a['sha256']}  {a['url'].rsplit('/', 1)[1]}\n"

    def run(self, argv, cwd, env, timeout, log, label):
        self.ran.append((label, list(argv)))
        self.envs.append(dict(env))
        if label == "check":
            return ti.run_command(argv, cwd, env, timeout, log, label)
        if self.fail_run and self.fail_run in " ".join(argv):
            return 1, "npm error simulated failure"
        cwd = Path(cwd)
        if label == "npm-ci":
            package = json.loads((cwd / "package.json").read_text())["dependencies"]
            (name, version), = package.items()
            comp = next(c for c in self.catalog.raw["tools"].values() if c["package"] == name)
            shown = self.wrong_version or version
            for b in comp["bins"]:
                target = cwd / b["argv"][0]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(script(f'echo "{comp["name"]} {shown}"'))
                target.chmod(0o755)
            return 0, ""
        if label == "script-step":
            return 0, ""
        if label == "script":
            home = Path(env["HERMES_HOME"])
            home.mkdir(parents=True, exist_ok=True)
            (home / "config.yaml").write_text("model: none\n")
            key = hashlib.sha256(str(cwd).encode()).hexdigest()[:16]    # Hermes keeps one dependency state per checkout
            (home / "installs" / key).mkdir(parents=True)
            (home / "installs" / key / "facts.json").write_text("{}")
            launcher = cwd / "hermes-agent" / ".hermes" / "bin" / "hermes"
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(script('echo "Hermes Agent v' + (self.wrong_version or self.catalog.component("hermes")["version"]) + ' (2026.9.24)"'))
            launcher.chmod(0o755)
            return 0, ""
        raise AssertionError(f"unexpected command {label}: {argv}")


def run(cfg, catalog, tool, action, *, ops=None, host=None, expect=None, log=None):
    ops = ops or FakeOps(catalog)
    return ti.run_action(cfg, catalog, tool, action, expect_plan_sha256=expect, ops=ops, facts=host or facts(), log=log)


def plan(cfg, catalog, tool, action, host=None):
    return ti.build_plan(cfg, catalog, host or facts(), tool, action)


def bump(cfg, tool, version):
    """Move the pinned version of an npm tool in the private catalog copy, with its lock files."""
    path = cfg.catalog_dir / "tool_catalog.json"
    raw = json.loads(path.read_text())
    comp = raw["tools"][tool]
    comp["version"] = version
    comp["check"]["expect"] = version
    folder = cfg.catalog_dir / comp["lock_dir"]
    pkg = json.loads((folder / "package.json").read_text())
    pkg["dependencies"] = {comp["package"]: version}
    (folder / "package.json").write_text(json.dumps(pkg))
    comp["lock"]["package_json_sha256"] = ti.sha256_file(folder / "package.json")
    path.write_text(json.dumps(raw))
    return ti.load_catalog(cfg.catalog_dir)


def tree(path: Path) -> set:
    return {str(p.relative_to(path)) for p in path.rglob("*")} if path.exists() else set()


# --- the shipped catalog -------------------------------------------------------------------


def test_the_shipped_catalog_is_valid_and_every_source_is_pinned():
    catalog = ti.load_catalog(API)
    assert catalog.tool_ids() == ["claude-code", "codex", "openclaw", "hermes"] and list(catalog.raw["runtimes"]) == ["node"]
    raw = catalog.raw
    for cid in ("claude-code", "codex", "openclaw"):
        folder = API / raw["tools"][cid]["lock_dir"]
        lock = json.loads((folder / "package-lock.json").read_text())
        assert ti.lock_problems(lock) == [], cid
        fetched = [v for k, v in lock["packages"].items() if k and not v.get("inBundle")]
        assert fetched and all(v["integrity"].startswith("sha512-") for v in fetched), cid


    assert len(raw["tools"]["hermes"]["commit"]) == 40
    node = raw["runtimes"]["node"]["archive"]["linux-arm64"]
    assert node["url"].startswith("https://nodejs.org/dist/v") and node["url"].endswith("-linux-arm64.tar.xz")
    assert node["shasums_url"].endswith("/SHASUMS256.txt")
    assert tuple(int(x) for x in raw["runtimes"]["node"]["version"].split(".")[:2]) >= (24, 16)  # OpenClaw's floor


def test_a_lock_entry_without_an_integrity_hash_or_from_elsewhere_is_refused():
    lock = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/a": {"resolved": "https://registry.npmjs.org/a/-/a-1.tgz"},
                                               "node_modules/b": {"resolved": "https://evil.example/b.tgz", "integrity": "sha512-x"},
                                               "node_modules/c": {"link": True, "resolved": "../c"},
                                               "node_modules/d/node_modules/e": {"inBundle": True, "version": "1"}}}
    problems = ti.lock_problems(lock)
    assert len(problems) == 3 and not any("node_modules/d" in p for p in problems)
    assert ti.lock_problems({"lockfileVersion": 2, "packages": {}})


@pytest.mark.parametrize("mutate,expect", [
    (lambda r: r["tools"]["codex"]["lock"].update(package_lock_sha256="0" * 64), "does not match the catalog hash"),
    (lambda r: r["runtimes"]["node"]["archive"]["linux-arm64"].update(url="http://nodejs.org/x.tar.xz"), "plain https"),
    (lambda r: r["runtimes"]["node"]["archive"]["linux-arm64"].update(url="https://evil.example/x.tar.xz"), "allowlist"),
    (lambda r: r["tools"]["hermes"]["script_args"].remove("--commit"), "--commit"),
    (lambda r: r["tools"]["hermes"]["script"].update(sha256="short"), "script needs url, sha256 and size"),
    (lambda r: r["tools"]["hermes"].update(commit="main"), "40-hex"),
    (lambda r: r["tools"]["codex"].update(installer="curl-pipe-sh"), "unknown installer"),
    (lambda r: r["tools"]["codex"].update(version="1.0.0"), "must depend on exactly"),
    (lambda r: r["tools"]["codex"].update(requires=["python"]), "unknown runtimes"),
    (lambda r: r["tools"]["codex"]["bins"][0].update(argv=["../../etc/passwd"]), "bad bins entry"),
    (lambda r: r.update(surprise=1), "unknown catalog keys"),
])
def test_catalog_validation_refuses_unpinned_or_tampered_sources(mutate, expect):
    raw = json.loads((API / "tool_catalog.json").read_text())
    mutate(raw)
    problems = ti.catalog_problems(raw, API)
    assert any(expect in p for p in problems), problems


def test_a_lock_file_changed_on_disk_stops_the_catalog_loading(cfg):
    lock = cfg.catalog_dir / "tool_locks" / "codex" / "package-lock.json"
    lock.write_text(lock.read_text().replace("sha512-", "sha512-X", 1))
    with pytest.raises(ti.ToolError, match="does not match the catalog hash"):
        ti.load_catalog(cfg.catalog_dir)


def test_duplicate_json_keys_are_refused(cfg):
    path = cfg.catalog_dir / "tool_catalog.json"
    path.write_text(path.read_text().replace('"schema": "dashboard-tool-catalog/v1",', '"schema": "x", "schema": "dashboard-tool-catalog/v1",', 1))
    with pytest.raises(ti.ToolError, match="duplicate key"):
        ti.load_catalog(cfg.catalog_dir)


# --- refusals ----------------------------------------------------------------------------


@pytest.mark.parametrize("over,text", [
    (dict(pointer_bits=32, machine="armv7l"), "32-bit"),
    (dict(pointer_bits=32), "32-bit"),                      # 32-bit userland on a 64-bit kernel
    (dict(machine="armv8l", pointer_bits=64), "32-bit"),   # 32-bit OS image reports armv8l on a Pi 4
    (dict(disk_free_mb=1900), "at least 2048 MB is needed"),
    (dict(disk_free_mb=2047), "at least 2048 MB is needed"),
    (dict(euid=0), "root"),
    (dict(machine="x86_64"), "linux-x64"),
    (dict(system="Darwin", machine="arm64"), "darwin-arm64"),
    (dict(can_restrict_privileges=False), "no-sudo rule"),
])
def test_host_refusals_block_every_tool_and_action(cfg, catalog, over, text):
    for tool in catalog.tool_ids():
        p = plan(cfg, catalog, tool, "install", facts(**over))
        assert any(text in r for r in p["refusals"]), (tool, p["refusals"])
        with pytest.raises(ti.ToolError, match=text):
            run(cfg, catalog, tool, "install", host=facts(**over))
    assert not (cfg.root / "tools").exists() or not os.listdir(cfg.root / "tools")  # nothing was installed


def test_a_refused_install_changes_nothing_on_disk(cfg, catalog, tmp_path):
    before = tree(tmp_path)
    with pytest.raises(ti.ToolError):
        run(cfg, catalog, "codex", "install", host=facts(pointer_bits=32))
    after = tree(tmp_path) - before
    assert all(p.startswith("tools-root") for p in after), after  # only the empty private layout appears


def test_disk_needs_room_for_the_install_plus_working_space(cfg, catalog):
    ok = plan(cfg, catalog, "openclaw", "install", facts(disk_free_mb=3000))
    assert ok["refusals"] == []
    assert ok["disk"]["required_mb"] == 620 + 230
    path = cfg.catalog_dir / "tool_catalog.json"
    raw = json.loads(path.read_text())
    raw["requirements"]["disk_headroom_mb"] = 1500                    # a catalog that wants more working room
    path.write_text(json.dumps(raw))
    tight = plan(cfg, ti.load_catalog(cfg.catalog_dir), "openclaw", "install", facts(disk_free_mb=2100))
    assert any("working room" in r and "2100 MB is free" in r for r in tight["refusals"]), tight["refusals"]


def test_memory_warns_under_four_gb_but_a_four_gb_board_is_not_warned(cfg, catalog):
    # A 4 GB Pi 4 reports about 3.8 GiB of usable memory; that is the target, not a warning.
    assert plan(cfg, catalog, "codex", "install", facts(mem_total_mb=3880))["warnings"] == []
    assert plan(cfg, catalog, "codex", "install", facts(mem_total_mb=7800))["warnings"] == []
    low = plan(cfg, catalog, "codex", "install", facts(mem_total_mb=2000))
    assert low["refusals"] == [] and any("2000 MB of memory" in w and "4 GB" in w for w in low["warnings"])
    busy = plan(cfg, catalog, "codex", "install", facts(mem_available_mb=500))
    assert busy["refusals"] == [] and any("500 MB of memory is available" in w for w in busy["warnings"])


def test_missing_required_packages_refuse_with_one_copyable_command(cfg, catalog):
    host = facts(commands={**facts().commands, "git": None, "curl": None})
    p = plan(cfg, catalog, "hermes", "install", host)
    assert p["system_packages"]["apt_command"].startswith("sudo apt install -y ")
    assert any("git is required" in r for r in p["refusals"])
    assert plan(cfg, catalog, "codex", "install", host)["refusals"] == []  # npm tools need neither


def test_missing_recommended_packages_only_warn_and_the_command_is_never_run(cfg, catalog, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: called.append(a))
    host = facts(commands={**facts().commands, "gcc": None, "g++": None, "make": None, "rg": None, "ffmpeg": None})
    p = plan(cfg, catalog, "hermes", "install", host)
    assert p["refusals"] == []
    cmd = p["system_packages"]["apt_command"]
    assert cmd == "sudo apt install -y build-essential ffmpeg ripgrep"
    assert len([w for w in p["warnings"] if "installs and runs without it" in w]) == 3
    assert all("downloads its own ripgrep and ffmpeg" in w for w in p["warnings"])
    assert called == []  # planning starts nothing


def test_a_non_debian_host_gets_a_generic_package_hint_not_apt(cfg, catalog):
    host = facts(os_family="other", commands={**facts().commands, "rg": None})
    assert plan(cfg, catalog, "codex", "install", host)["system_packages"]["apt_command"].startswith("Install with your package manager")


def test_already_installed_unknown_and_empty_states_are_refused(cfg, catalog):
    assert "not installed" in plan(cfg, catalog, "codex", "update")["refusals"][0]
    assert "not installed" in plan(cfg, catalog, "codex", "remove")["refusals"][0]
    assert "not installed" in plan(cfg, catalog, "codex", "rollback")["refusals"][0]
    run(cfg, catalog, "codex", "install")
    assert "already installed" in plan(cfg, catalog, "codex", "install")["refusals"][0]
    assert "already the pinned version" in plan(cfg, catalog, "codex", "update")["refusals"][0]
    assert "nothing to roll back to" in plan(cfg, catalog, "codex", "rollback")["refusals"][0]
    with pytest.raises(ti.ToolError, match="not an installable tool"):
        plan(cfg, catalog, "node", "install")
    with pytest.raises(ti.ToolError, match="not an installable tool"):
        plan(cfg, catalog, "bash; rm -rf /", "install")
    with pytest.raises(ti.ToolError, match="unknown action"):
        plan(cfg, catalog, "codex", "format")


def test_an_operation_already_in_progress_blocks_another(cfg, catalog):
    ti.prepare_layout(cfg)
    with ti.invocation_lock(cfg):
        assert ti.lock_is_held(cfg)
        with pytest.raises(ti.ToolError, match="already running"):
            run(cfg, catalog, "codex", "install")
    state = ti.load_state(cfg)
    state["tx"] = {"id": "t1", "tool": "codex", "action": "install", "phase": "x", "partials": []}
    ti.save_state(cfg, state)
    assert any("in progress" in r for r in plan(cfg, catalog, "claude-code", "install")["refusals"])


# --- install ---------------------------------------------------------------------------------


def test_installing_a_npm_tool_installs_node_first_then_the_tool_and_both_run(cfg, catalog):
    ops = FakeOps(catalog)
    out = run(cfg, catalog, "codex", "install", ops=ops)
    assert out["outcome"] == "done" and "Installed Codex CLI 0.162.1" in out["detail"]
    # Node came first and was checked against the publisher's SHASUMS256.txt as well as the catalog hash.
    assert ops.fetched == [catalog.raw["runtimes"]["node"]["archive"]["linux-arm64"]["url"]]
    assert ops.shasums == [catalog.raw["runtimes"]["node"]["archive"]["linux-arm64"]["shasums_url"]]
    labels = [label for label, _ in ops.ran]
    assert labels == ["check", "npm-ci", "check"]
    ci = next(argv for label, argv in ops.ran if label == "npm-ci")
    assert ci[1:] == ["ci", "--ignore-scripts", "--no-audit", "--no-fund", "--no-progress", "--loglevel=error"]
    view = ti.installed_view(cfg, "codex")
    assert view["installed"] and view["current"]["version"] == "0.162.1" and view["previous"] is None
    assert ti.installed_view(cfg, "node")["current"]["version"] == "24.21.0"
    wrapper = cfg.bin / "codex"
    assert os.access(wrapper, os.X_OK) and ti.WRAPPER_MARK in wrapper.read_text()
    assert subprocess.run([str(wrapper), "--version"], capture_output=True, text=True).stdout.strip() == "Codex CLI 0.162.1"
    assert os.readlink(cfg.comp_dir("codex") / "current").startswith("versions/0.162.1-")
    state = ti.load_state(cfg)
    assert state["tx"] is None and state["last"]["outcome"] == "done"
    assert (cfg.state_dir / "history.jsonl").read_text().count("\n") == 1
    assert not os.listdir(cfg.tmp) and not os.listdir(cfg.sandbox) and not os.listdir(cfg.cache)  # working space is gone


def test_a_second_npm_tool_reuses_node_and_a_second_run_downloads_nothing(cfg, catalog):
    run(cfg, catalog, "codex", "install")
    ops = FakeOps(catalog)
    run(cfg, catalog, "claude-code", "install", ops=ops)
    assert ops.fetched == [] and [l for l, _ in ops.ran] == ["npm-ci", "script-step", "check"]
    script_step = next(argv for label, argv in ops.ran if label == "script-step")
    assert script_step[1] == "node_modules/@anthropic-ai/claude-code/install.cjs"  # the one script the catalog allows


def test_installers_see_a_private_home_and_none_of_the_services_environment(cfg, catalog, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "MAC_CONTROL_SECRET", "OPENROUTER_API_KEY", "SSH_AUTH_SOCK"):
        monkeypatch.setenv(name, "must-not-leak")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    ops = FakeOps(catalog)
    run(cfg, catalog, "hermes", "install", ops=ops)
    assert ops.envs
    for env in ops.envs:
        assert not [k for k in env if "KEY" in k or "TOKEN" in k or "SECRET" in k or k == "SSH_AUTH_SOCK"], env
        assert env["HOME"] != str(cfg.home) and env["HOME"].startswith(str(cfg.root))
        assert ("node" in env["PATH"].split(":")[0]) == (env.get("HERMES_HOME") is None)   # Hermes installs its own Node
        assert env["GIT_TERMINAL_PROMPT"] == "0" and env["HTTPS_PROXY"] == "http://proxy.invalid:3128"
    hermes_env = next(e for (label, _), e in zip(ops.ran, ops.envs) if label == "script")
    assert hermes_env["HERMES_HOME"] == str(cfg.hermes_home)
    assert hermes_env["HOME"].endswith("/home") and "/tools/hermes/versions/" in hermes_env["HOME"]


def test_hermes_installs_by_pinned_commit_with_the_installers_own_flags(cfg, catalog):
    ops = FakeOps(catalog)
    run(cfg, catalog, "hermes", "install", ops=ops)
    comp = catalog.raw["tools"]["hermes"]
    argv = next(a for l, a in ops.ran if l == "script")
    assert argv[0] == "bash" and argv[1].endswith("install.sh")
    assert argv[argv.index("--commit") + 1] == comp["commit"]
    for flag in ("--non-interactive", "--skip-setup", "--skip-browser", "--skip-computer-use"):
        assert flag in argv
    assert "--ensure" not in argv                      # the system-package path is never taken
    assert argv[argv.index("--hermes-home") + 1] == str(cfg.hermes_home)
    install_dir = argv[argv.index("--dir") + 1]
    assert install_dir.startswith(str(cfg.comp_dir("hermes") / "versions")) and install_dir.endswith("/hermes-agent")
    assert ops.fetched[-1] == comp["script"]["url"] and comp["commit"] in comp["script"]["url"]
    assert subprocess.run([str(cfg.bin / "hermes"), "--version"], capture_output=True, text=True).stdout.strip() \
        == "Hermes Agent v0.21.7 (2026.9.24)"
    # Hermes needs no Node or uv from us: it checks and installs its own toolchain from its pinned commit.
    assert catalog.raw["tools"]["hermes"]["requires"] == [] and not ti.installed_view(cfg, "node")["installed"]
    assert str(cfg.comp_dir("node")) not in ops.envs[0]["PATH"]
    receipt = ti.read_receipt(cfg, "hermes", ti.installed_view(cfg, "hermes")["current"]["vid"])
    assert [Path(p).parent for p in receipt["external"]] == [cfg.hermes_home / "installs"]


def test_install_writes_only_inside_the_tools_root_and_the_named_hermes_folder(cfg, catalog, tmp_path):
    before = tree(tmp_path)
    for tool in ("claude-code", "codex", "openclaw", "hermes"):
        run(cfg, catalog, tool, "install")
    created = tree(tmp_path) - before
    outside = [p for p in created if not p.startswith("tools-root") and not p.startswith("home/.hermes")]
    assert outside == [], outside
    inside = {p for p in created if p.startswith("home/")}
    assert {p for p in inside if p.count("/") <= 2} == {"home/.hermes", "home/.hermes/config.yaml", "home/.hermes/installs"}
    assert len([p for p in inside if p.count("/") == 3]) == 1     # the one dependency-state folder Hermes made
    for name in ("claude", "codex", "openclaw", "hermes"):
        assert (cfg.bin / name).is_file()


def test_the_plan_confirmation_shows_exact_versions_commands_disk_and_memory(cfg, catalog):
    p = plan(cfg, catalog, "openclaw", "install", facts(disk_free_mb=15000, mem_total_mb=3880, mem_available_mb=3100))
    assert (p["tool"], p["action"], p["from"], p["to"]) == ("openclaw", "install", None, "2026.10.3")
    assert [r["id"] for r in p["runtimes"]] == ["node"] and p["runtimes"][0]["version"] == "24.21.0"
    text = "\n".join(p["commands"])
    assert "download https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-arm64.tar.xz" in text
    assert "SHASUMS256.txt" in text and "npm ci --ignore-scripts" in text
    assert [d["sha256"] for d in p["downloads"]] == ["6ad1325edbdb5649c379b75a237147a666c95d4f9ae8d340fef2d1575d289ad2"]
    assert p["disk"] == {"free_mb": 15000, "required_mb": 850, "min_free_mb": 2048, "headroom_mb": 512}
    assert p["memory"]["total_mb"] == 3880 and p["memory"]["available_mb"] == 3100
    assert p["login"]["command"] == "openclaw onboard"
    assert any("dispatch" in u.lower() for u in p["unchanged"]) and any("billing" in u.lower() for u in p["unchanged"])
    assert len(p["plan_sha256"]) == 64


def test_a_fresh_home_gets_the_missing_parent_folders_but_only_inside_the_home(cfg, catalog, tmp_path):
    fresh = ti.ToolsConfig(root=cfg.home / ".local" / "share" / "rcd-agent-tools", catalog_dir=cfg.catalog_dir,
                           platform_key="linux-arm64", home=cfg.home)
    ti.prepare_layout(fresh)
    assert (fresh.root / "state").is_dir() and oct(os.stat(fresh.root).st_mode & 0o777) == "0o700"
    outside = ti.ToolsConfig(root=tmp_path / "nowhere" / "deeper" / "tools", catalog_dir=cfg.catalog_dir,
                             platform_key="linux-arm64", home=cfg.home)
    with pytest.raises(ti.ToolError, match="does not exist"):
        ti.prepare_layout(outside)
    assert not (tmp_path / "nowhere").exists()
    assert ti.inspect(outside, catalog, facts())["tools"]  # reading status creates nothing and does not need the folder


def test_the_plan_digest_ignores_free_disk_and_memory_but_not_versions_or_sources(cfg, catalog):
    a = plan(cfg, catalog, "codex", "install", facts(disk_free_mb=5000, mem_available_mb=2000))["plan_sha256"]
    b = plan(cfg, catalog, "codex", "install", facts(disk_free_mb=9000, mem_available_mb=900))["plan_sha256"]
    assert a == b
    other = bump(cfg, "codex", "0.163.0")
    assert plan(cfg, other, "codex", "install")["plan_sha256"] != a


def test_a_plan_the_operator_did_not_confirm_does_not_run(cfg, catalog):
    confirmed = plan(cfg, catalog, "codex", "install")["plan_sha256"]
    other = bump(cfg, "codex", "0.163.0")
    with pytest.raises(ti.ToolError, match="plan changed"):
        run(cfg, other, "codex", "install", expect=confirmed)
    assert not ti.installed_view(cfg, "codex")["installed"]
    run(cfg, other, "codex", "install", expect=plan(cfg, other, "codex", "install")["plan_sha256"])
    assert ti.installed_view(cfg, "codex")["current"]["version"] == "0.163.0"


# --- failures leave nothing half-installed -----------------------------------------------------


@pytest.mark.parametrize("kw,where", [
    (dict(fail_fetch="nodejs.org"), "sha256 differs"),
    (dict(fail_run="npm"), "npm error simulated failure"),
    (dict(wrong_version="9.9.9"), "version check failed"),
])
def test_a_failed_install_cleans_up_and_never_points_current_at_it(cfg, catalog, kw, where):
    ops = FakeOps(catalog, **kw)
    with pytest.raises(ti.ToolError, match=where):
        run(cfg, catalog, "codex", "install", ops=ops)
    assert not ti.installed_view(cfg, "codex")["installed"] and not (cfg.bin / "codex").exists()
    assert not os.path.lexists(cfg.comp_dir("codex") / "current")
    assert ti.load_state(cfg)["last"]["outcome"] == "failed" and ti.load_state(cfg)["tx"] is None
    for cid in ("codex", "node"):
        leftovers = [v for v in ti.installed_view(cfg, cid)["versions"] if not v["complete"]]
        assert leftovers == [], (cid, leftovers)
    assert not os.listdir(cfg.tmp)


def test_a_failed_update_leaves_the_working_version_in_place(cfg, catalog):
    run(cfg, catalog, "codex", "install")
    newer = bump(cfg, "codex", "0.163.0")
    with pytest.raises(ti.ToolError, match="version check failed"):
        run(cfg, newer, "codex", "update", ops=FakeOps(newer, wrong_version="0.0.1"))
    view = ti.installed_view(cfg, "codex")
    assert view["current"]["version"] == "0.162.1" and view["previous"] is None
    assert subprocess.run([str(cfg.bin / "codex"), "--version"], capture_output=True, text=True).stdout.strip() == "Codex CLI 0.162.1"
    assert [v["complete"] for v in view["versions"]] == [True]


def test_a_killed_helper_is_cleaned_up_by_the_next_call(cfg, catalog):
    class Dies(FakeOps):
        def run(self, argv, cwd, env, timeout, log, label):
            if label == "npm-ci":
                raise SystemExit("killed")
            return super().run(argv, cwd, env, timeout, log, label)

    # Simulate the helper process dying with the journal still open: a tx and an unfinished folder remain.
    ti.prepare_layout(cfg)
    vid = catalog.vid("codex", "linux-arm64")
    partial = cfg.version_dir("codex", vid)
    partial.mkdir(parents=True)
    (partial / "package.json").write_text("{}")
    state = ti.load_state(cfg)
    state["tx"] = {"id": "dead1", "tool": "codex", "action": "install", "phase": "installing", "partials": [{"c": "codex", "vid": vid}],
                   "from": None, "to": "0.162.1"}
    ti.save_state(cfg, state)
    assert ti.inspect(cfg, catalog, facts())["tx"]["id"] == "dead1"
    run(cfg, catalog, "codex", "install")  # recovers, then installs
    last = ti.load_state(cfg)["last"]
    assert last["outcome"] == "done"
    history = [json.loads(l) for l in (cfg.state_dir / "history.jsonl").read_text().splitlines()]
    assert [h["outcome"] for h in history] == ["interrupted", "done"]
    # And an exception that is not a ToolError (a bug, SystemExit) is journalled as failed, not left open.
    cfg2_ops = Dies(catalog)
    with pytest.raises(SystemExit):
        run(cfg, catalog, "claude-code", "install", ops=cfg2_ops)
    assert ti.load_state(cfg)["tx"] is None and ti.load_state(cfg)["last"]["outcome"] == "failed"


def test_a_command_that_is_not_ours_is_never_overwritten(cfg, catalog):
    ti.prepare_layout(cfg)
    (cfg.bin / "codex").write_text("#!/bin/sh\necho somebody else's codex\n")
    assert any("was not written by the Agent tools" in r for r in plan(cfg, catalog, "codex", "install")["refusals"])
    with pytest.raises(ti.ToolError, match="was not written by the Agent tools"):
        run(cfg, catalog, "codex", "install")
    assert "somebody else's" in (cfg.bin / "codex").read_text()
    assert not os.path.lexists(cfg.comp_dir("codex") / "current")


def test_an_existing_copy_elsewhere_is_reported_not_replaced(cfg, catalog):
    p = plan(cfg, catalog, "codex", "install", facts(elsewhere={"codex": "/usr/local/bin/codex"}))
    assert any("/usr/local/bin/codex" in w for w in p["warnings"])


# --- update, rollback, remove ---------------------------------------------------------------


def test_update_keeps_the_old_version_for_rollback_and_rollback_is_a_link_flip(cfg, catalog):
    run(cfg, catalog, "codex", "install")
    old_vid = os.readlink(cfg.comp_dir("codex") / "current")
    newer = bump(cfg, "codex", "0.163.0")
    wrapper_before = (cfg.bin / "codex").read_text()
    out = run(cfg, newer, "codex", "update", ops=FakeOps(newer))
    assert "0.162.1 to 0.163.0" in out["detail"]
    view = ti.installed_view(cfg, "codex")
    assert (view["current"]["version"], view["previous"]["version"]) == ("0.163.0", "0.162.1")
    assert (cfg.bin / "codex").read_text() == wrapper_before            # the wrapper never changes
    assert subprocess.run([str(cfg.bin / "codex"), "--version"], capture_output=True, text=True).stdout.strip() == "Codex CLI 0.163.0"
    # Rollback runs no installer and no download: it only flips links and checks the version.
    ops = FakeOps(newer)
    out = run(cfg, newer, "codex", "rollback", ops=ops)
    assert ops.fetched == [] and [l for l, _ in ops.ran] == ["check"]
    assert "back to 0.162.1" in out["detail"]
    assert os.readlink(cfg.comp_dir("codex") / "current") == old_vid
    view = ti.installed_view(cfg, "codex")
    assert (view["current"]["version"], view["previous"]["version"]) == ("0.162.1", "0.163.0")
    assert subprocess.run([str(cfg.bin / "codex"), "--version"], capture_output=True, text=True).stdout.strip() == "Codex CLI 0.162.1"
    # Rolling forward again reuses the folder that is still there instead of reinstalling it.
    ops = FakeOps(newer)
    run(cfg, newer, "codex", "update", ops=ops)
    assert [l for l, _ in ops.ran] == ["check"] and ops.fetched == []
    assert ti.installed_view(cfg, "codex")["current"]["version"] == "0.163.0"


def test_only_current_and_previous_are_kept_after_updates(cfg, catalog):
    run(cfg, catalog, "codex", "install")
    cat = catalog
    for v in ("0.163.0", "0.164.0"):
        cat = bump(cfg, "codex", v)
        run(cfg, cat, "codex", "update", ops=FakeOps(cat))
    view = ti.installed_view(cfg, "codex")
    assert [x["version"] for x in view["versions"]] == ["0.163.0", "0.164.0"]
    assert (view["current"]["version"], view["previous"]["version"]) == ("0.164.0", "0.163.0")


def test_a_rollback_target_that_fails_its_check_puts_the_current_version_back(cfg, catalog):
    run(cfg, catalog, "codex", "install")
    newer = bump(cfg, "codex", "0.163.0")
    run(cfg, newer, "codex", "update", ops=FakeOps(newer))
    previous_dir = cfg.comp_dir("codex") / "previous"
    broken = (previous_dir.resolve() / "node_modules" / ".bin" / "codex")
    broken.write_bytes(script("exit 3"))
    with pytest.raises(ti.ToolError, match="failed its check"):
        run(cfg, newer, "codex", "rollback", ops=FakeOps(newer))
    assert ti.installed_view(cfg, "codex")["current"]["version"] == "0.163.0"
    assert subprocess.run([str(cfg.bin / "codex"), "--version"], capture_output=True, text=True).stdout.strip() == "Codex CLI 0.163.0"


def test_remove_deletes_the_program_and_its_wrapper_and_the_orphaned_runtime(cfg, catalog):
    run(cfg, catalog, "codex", "install")
    run(cfg, catalog, "openclaw", "install")
    p = plan(cfg, catalog, "codex", "remove")
    assert p["removes"] == []                                  # openclaw still needs Node
    run(cfg, catalog, "codex", "remove")
    assert not (cfg.bin / "codex").exists() and not cfg.comp_dir("codex").exists()
    assert (cfg.bin / "openclaw").exists() and ti.installed_view(cfg, "node")["installed"]
    p = plan(cfg, catalog, "openclaw", "remove")
    assert p["removes"] == ["Node.js 24.21.0 (nothing else uses it)"]
    out = run(cfg, catalog, "openclaw", "remove")
    assert out["outcome"] == "done"
    assert not ti.installed_view(cfg, "node")["installed"] and not cfg.comp_dir("node").exists()
    assert os.listdir(cfg.bin) == []


def test_remove_keeps_hermes_data_and_says_so_but_takes_its_dependency_state(cfg, catalog):
    run(cfg, catalog, "hermes", "install")
    (cfg.hermes_home / "installs" / "someoneelse1234").mkdir()                 # not recorded by us: never touched
    mine = [p for p in (cfg.hermes_home / "installs").iterdir() if p.name != "someoneelse1234"]
    assert len(mine) == 1
    p = plan(cfg, catalog, "hermes", "remove")
    assert any(str(cfg.hermes_home) in w and "kept" in w for w in p["warnings"])
    assert any("dependency folder" in r for r in p["removes"])
    run(cfg, catalog, "hermes", "remove")
    assert (cfg.hermes_home / "config.yaml").read_text() == "model: none\n"
    assert not mine[0].exists() and (cfg.hermes_home / "installs" / "someoneelse1234").is_dir()
    assert not cfg.comp_dir("hermes").exists() and not (cfg.bin / "hermes").exists()


def test_a_failed_hermes_install_removes_the_state_folders_it_made(cfg, catalog):
    class Breaks(FakeOps):
        def run(self, argv, cwd, env, timeout, log, label):
            out = super().run(argv, cwd, env, timeout, log, label)
            return (1, "pm install failed") if label == "script" else out

    with pytest.raises(ti.ToolError, match="pm install failed"):
        run(cfg, catalog, "hermes", "install", ops=Breaks(catalog))
    assert list((cfg.hermes_home / "installs").iterdir()) == []
    assert not (cfg.comp_dir("hermes") / "versions").exists() or not os.listdir(cfg.comp_dir("hermes") / "versions")


def test_updating_hermes_prunes_the_oldest_versions_state_but_keeps_the_previous_ones(cfg, catalog):
    run(cfg, catalog, "hermes", "install")
    raw = json.loads((cfg.catalog_dir / "tool_catalog.json").read_text())
    states = lambda: sorted(p.name for p in (cfg.hermes_home / "installs").iterdir())
    first = states()
    for version in ("0.21.8", "0.21.9"):
        raw["tools"]["hermes"]["version"] = version
        raw["tools"]["hermes"]["check"]["expect"] = version
        (cfg.catalog_dir / "tool_catalog.json").write_text(json.dumps(raw))
        cat = ti.load_catalog(cfg.catalog_dir)
        run(cfg, cat, "hermes", "update", ops=FakeOps(cat, ))
    now = states()
    assert len(now) == 2 and first[0] not in now          # the oldest version's state went with its folder
    view = ti.installed_view(cfg, "hermes")
    assert (view["current"]["version"], view["previous"]["version"]) == ("0.21.9", "0.21.8")


def test_remove_is_allowed_even_on_a_full_disk(cfg, catalog):
    run(cfg, catalog, "codex", "install")
    p = plan(cfg, catalog, "codex", "remove", facts(disk_free_mb=10))
    assert p["refusals"] == []


# --- the installed view and the app's lookup ------------------------------------------------------


def test_inspect_lists_each_tool_with_what_its_buttons_would_do(cfg, catalog):
    view = ti.inspect(cfg, catalog, facts())
    assert [t["id"] for t in view["tools"]] == ["claude-code", "codex", "openclaw", "hermes"]
    codex = view["tools"][1]
    assert codex["installed"] is False and codex["actions"]["install"] == [] and codex["actions"]["remove"] is None
    assert codex["actions"]["update"] is None and codex["actions"]["rollback"] is None
    refused = ti.inspect(cfg, catalog, facts(pointer_bits=32))
    assert all(t["actions"]["install"] and "32-bit" in t["actions"]["install"][0] for t in refused["tools"])
    run(cfg, catalog, "codex", "install")
    newer = bump(cfg, "codex", "0.163.0")
    now = ti.inspect(cfg, newer, facts())["tools"][1]
    assert now["installed_version"] == "0.162.1" and now["pinned_version"] == "0.163.0"
    assert now["actions"]["install"] is None and now["actions"]["update"] == [] and now["actions"]["remove"] == []
    assert now["path"] == str(cfg.bin / "codex")
    assert view["system_packages"]["apt_command"] is None  # everything is present on the fake host


def test_managed_bin_finds_a_working_wrapper_only(cfg, catalog):
    assert ti.managed_bin(cfg.root, "codex") is None
    run(cfg, catalog, "codex", "install")
    assert ti.managed_bin(cfg.root, "codex") == str(cfg.bin / "codex")
    assert ti.managed_bin(None, "codex") is None


# --- archive extraction ---------------------------------------------------------------------------


def _bad(tmp_path, build):
    path = tmp_path / "bad.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        build(tf)
    return path


def _member(name, kind=tarfile.REGTYPE, data=b"x", link=""):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, link
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    info.mode = 0o4755
    return info, io.BytesIO(data) if kind == tarfile.REGTYPE else None


@pytest.mark.parametrize("name,kind,link,why", [
    ("root/../../escape", tarfile.REGTYPE, "", "refused"),
    ("/etc/passwd", tarfile.REGTYPE, "", "refused"),
    ("other/file", tarfile.REGTYPE, "", "refused"),
    ("root/link", tarfile.SYMTYPE, "../../etc", "leaves the folder"),
    ("root/abs", tarfile.SYMTYPE, "/etc/passwd", "leaves the folder"),
    ("root/dev", tarfile.CHRTYPE, "", "type refused"),
    ("root/hard", tarfile.LNKTYPE, "../../etc/passwd", "hard link refused"),
])
def test_extraction_refuses_unsafe_members(tmp_path, name, kind, link, why):
    def build(tf):
        info, data = _member(name, kind, link=link)
        tf.addfile(info, data)
    archive = _bad(tmp_path, build)
    dest = tmp_path / "out"
    with pytest.raises(ti.ToolError, match=why):
        ti.extract_archive(archive, "tar.gz", "root", dest)
    assert not (tmp_path / "etc").exists() and not (tmp_path / "escape").exists()


def test_extraction_strips_the_root_and_drops_setuid_and_group_write(tmp_path):
    def build(tf):
        info, data = _member("root/bin/tool")
        tf.addfile(info, data)
        info, data = _member("root/bin/alias", tarfile.SYMTYPE, link="tool")
        tf.addfile(info, data)
    archive = _bad(tmp_path, build)
    dest = tmp_path / "out"
    ti.extract_archive(archive, "tar.gz", "root", dest)
    assert (dest / "bin" / "tool").stat().st_mode & 0o7777 == 0o755       # setuid removed
    assert os.readlink(dest / "bin" / "alias") == "tool"
    with pytest.raises(ti.ToolError, match="already exists"):
        ti.extract_archive(archive, "tar.gz", "root", dest)


# --- transport ------------------------------------------------------------------------------------


class _Resp:
    def __init__(self, data, headers=None, status=200):
        self.data, self.status, self.pos = data, status, 0
        self.headers = headers if headers is not None else {"Content-Length": str(len(data))}

    def read(self, n=-1):
        chunk = self.data[self.pos:self.pos + (n if n >= 0 else len(self.data))]
        self.pos += len(chunk)
        return chunk

    def close(self):
        pass


def test_fetch_file_checks_size_and_sha256_and_leaves_nothing_on_failure(tmp_path, monkeypatch):
    data = b"payload" * 100
    good = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(ti, "_open_url", lambda url, timeout=30.0: _Resp(data))
    ok = tmp_path / "ok"
    ti.fetch_file("https://nodejs.org/x", ok, good, len(data))
    assert ok.read_bytes() == data
    for sha, size, text in ((("0" * 64), len(data), "differs from the pinned"), (good, len(data) - 1, "length differs"),
                            (good, len(data) + 5, "length differs")):
        dest = tmp_path / f"bad{size}{sha[:2]}"
        with pytest.raises(ti.ToolError, match=text):
            ti.fetch_file("https://nodejs.org/x", dest, sha, size)
        assert not dest.exists()
    monkeypatch.setattr(ti, "_open_url", lambda url, timeout=30.0: _Resp(data, headers={}))
    dest = tmp_path / "streamed"
    with pytest.raises(ti.ToolError, match="larger than the pinned size"):
        ti.fetch_file("https://nodejs.org/x", dest, good, len(data) - 10)
    assert not dest.exists()


@pytest.mark.parametrize("url", ["http://nodejs.org/x", "https://example.com/x", "https://user:pw@nodejs.org/x",
                                 "https://nodejs.org:8443/x", "https://nodejs.org/x?token=1", "file:///etc/passwd", "ftp://nodejs.org/x"])
def test_downloads_are_https_and_allowlisted_only(url):
    assert ti.url_problem(url)
    with pytest.raises(ti.ToolError):
        ti._open_url(url)


def test_redirects_may_only_land_on_allowlisted_https_hosts():
    handler = ti._Redirects()

    class Req:
        full_url = "https://github.com/astral-sh/uv/releases/download/0.13.0/x.tar.gz"

        def header_items(self):
            return [("User-Agent", "x")]

    ok = handler.redirect_request(Req(), None, 302, "Found", {}, "https://release-assets.githubusercontent.com/a/b?sig=1")
    assert ok.full_url.startswith("https://release-assets.githubusercontent.com/")
    for bad in ("http://github.com/x", "https://evil.example/x", "https://objects.githubusercontent.com:444/x"):
        with pytest.raises(ti.ToolError):
            ti._Redirects().redirect_request(Req(), None, 302, "Found", {}, bad)


def test_shasums_must_list_the_pinned_hash(cfg, catalog):
    class Liar(FakeOps):
        def fetch_text(self, url):
            return f"{'0' * 64}  node-v24.21.0-linux-arm64.tar.xz\n"

    with pytest.raises(ti.ToolError, match="SHASUMS256.txt does not list the pinned sha256"):
        run(cfg, catalog, "codex", "install", ops=Liar(catalog))
    assert not ti.installed_view(cfg, "node")["installed"]


# --- no sudo ---------------------------------------------------------------------------------------


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="no_new_privs is Linux only")
def test_the_helper_process_cannot_gain_privileges_even_with_passwordless_sudo():
    code = ("import sys, subprocess; sys.path.insert(0, %r); import tool_install as ti; "
            "assert ti.harden_process(); "
            "print(open('/proc/self/status').read().split('NoNewPrivs:')[1].split()[0]); "
            "r = subprocess.run(['sudo', '-n', 'true'], capture_output=True); print(r.returncode)" % str(API))
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    lines = out.stdout.split()
    assert lines[0] == "1", out.stderr
    if shutil.which("sudo"):
        assert lines[1] != "0"  # sudo (setuid) refuses under no_new_privs; skipped silently where sudo is absent


def test_the_engine_never_names_sudo_or_apt_as_something_it_runs():
    source = (API / "tool_install.py").read_text()
    runs = [line for line in source.splitlines() if "ops.run(" in line or "subprocess." in line]
    assert not [l for l in runs if "sudo" in l or "apt" in l]
    catalog = json.loads((API / "tool_catalog.json").read_text())
    assert "sudo" not in json.dumps(catalog["tools"])
