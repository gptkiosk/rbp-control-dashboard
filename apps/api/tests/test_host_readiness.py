"""Host readiness: what the machine still needs before projects can be built and delivered from it, and the few named fixes."""
from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import pytest

import host_readiness as hr


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A private HOME and global git config, so nothing touches the real machine."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")                                  # no agent from the machine running the tests can be found
    settings = SimpleNamespace(workdir_roots=(home / "Projects", tmp_path / "data" / "workspaces"), claude_path="claude", codex_path="codex",
                               openclaw_path="openclaw", grok_path="grok", hermes_path="hermes")
    return home, settings


def by_id(report):
    return {c["id"]: c for c in report["checks"]}


def test_a_bare_machine_says_what_is_missing_and_offers_only_named_fixes(host):
    home, settings = host
    checks = by_id(hr.report(settings))
    assert checks["workspace"]["status"] == "missing" and checks["workspace"]["fix"]["action"] == "create_workspace"
    assert "scratch folder" in checks["workspace"]["detail"] and "clone the repository" in checks["workspace"]["detail"]
    assert checks["git_identity"]["status"] == "missing" and checks["git_identity"]["fix"]["inputs"] == ["name", "email"]
    assert checks["github_ssh"]["status"] == "missing" and checks["github_ssh"]["fix"]["action"] == "make_github_key"
    assert {c["fix"]["action"] for c in checks.values() if c["fix"]} <= {"create_workspace", "set_git_identity", "make_github_key", "test_github_ssh"}
    report = hr.report(settings)
    assert report["ready_to_build"] is False and report["ready_to_deliver"] is False


def test_the_workspace_fix_only_creates_an_allowed_folder(host):
    home, settings = host
    assert "Created" in hr.apply(settings, "create_workspace")
    assert (home / "Projects").is_dir() and by_id(hr.report(settings))["workspace"]["status"] == "ok"
    with pytest.raises(hr.ReadinessError):
        hr.apply(settings, "create_workspace", path=str(home / "elsewhere"))
    with pytest.raises(hr.ReadinessError):
        hr.apply(settings, "create_workspace", path=str(home / "Projects" / ".." / "elsewhere"))
    assert not (home / "elsewhere").exists()


def test_the_git_identity_is_validated_and_saved_globally(host):
    home, settings = host
    for bad in (("", "a@b.co"), ("Name", "not-an-email"), ("Na\nme", "a@b.co"), ("N" * 101, "a@b.co")):
        with pytest.raises(hr.ReadinessError):
            hr.apply(settings, "set_git_identity", name=bad[0], email=bad[1])
    assert by_id(hr.report(settings))["git_identity"]["status"] == "missing"
    assert "Commits will be made as Pi Builder <pi@example.com>" in hr.apply(settings, "set_git_identity", name="Pi Builder", email="pi@example.com")
    check = by_id(hr.report(settings))["git_identity"]
    assert check["status"] == "ok" and "Pi Builder" in check["detail"]


def test_the_github_key_is_made_once_kept_private_and_never_returned_as_a_private_key(host):
    home, settings = host
    message = hr.apply(settings, "make_github_key")
    private, public = hr._key_paths()
    assert "private half stays on this host" in message
    assert stat.S_IMODE(private.stat().st_mode) == 0o600 and public.read_text().startswith("ssh-ed25519 ")
    config = (home / ".ssh" / "config").read_text()
    assert config.count(hr.MARK_BEGIN) == 1 and f"IdentityFile {private}" in config and stat.S_IMODE((home / ".ssh" / "config").stat().st_mode) == 0o600
    check = by_id(hr.report(settings))["github_ssh"]
    assert check["status"] == "ok" and check["public_key"].startswith("ssh-ed25519 ")
    assert "PRIVATE" not in str(hr.report(settings)) and private.read_text().strip().splitlines()[1] not in str(hr.report(settings))
    with pytest.raises(hr.ReadinessError) as again:
        hr.apply(settings, "make_github_key")
    assert again.value.status == 409                                              # an existing key is never replaced
    hr._write_ssh_config(private)                                                # rewriting the block is idempotent
    assert (home / ".ssh" / "config").read_text().count(hr.MARK_BEGIN) == 1


def test_an_existing_ssh_config_is_kept_when_the_block_is_added(host):
    home, settings = host
    (home / ".ssh").mkdir(mode=0o700)
    (home / ".ssh" / "config").write_text("Host mine\n  HostName example.org\n")
    hr.apply(settings, "make_github_key")
    text = (home / ".ssh" / "config").read_text()
    assert text.startswith("Host mine\n  HostName example.org") and hr.MARK_BEGIN in text


def test_testing_github_without_a_key_says_to_make_one(host):
    home, settings = host
    with pytest.raises(hr.ReadinessError, match="Make the GitHub key first"):
        hr.apply(settings, "test_github_ssh")


def test_agents_distinguish_builders_from_managers(host, tmp_path):
    home, settings = host
    manager = tmp_path / "bin" / "hermes"
    manager.parent.mkdir(exist_ok=True)
    manager.write_text("#!/bin/sh\n")
    manager.chmod(0o755)
    settings.hermes_path = str(manager)
    check = by_id(hr.report(settings))["agents"]
    assert check["status"] == "missing" and "does not write code" in check["detail"]
    builder = tmp_path / "bin" / "openclaw"
    builder.write_text("#!/bin/sh\n")
    builder.chmod(0o755)
    settings.openclaw_path = str(builder)
    check = by_id(hr.report(settings))["agents"]
    assert check["status"] == "ok" and "openclaw" in check["detail"]
    assert {r["id"]: r["writes_code"] for r in check["agents"]}["hermes"] is False


def test_everything_ready_reports_ready_to_deliver(host, tmp_path):
    home, settings = host
    builder = tmp_path / "bin" / "codex"
    builder.parent.mkdir()
    builder.write_text("#!/bin/sh\n")
    builder.chmod(0o755)
    settings.codex_path = str(builder)
    hr.apply(settings, "create_workspace")
    hr.apply(settings, "set_git_identity", name="Pi Builder", email="pi@example.com")
    assert hr.report(settings)["ready_to_build"] is True and hr.report(settings)["ready_to_deliver"] is False
    hr.apply(settings, "make_github_key")
    assert hr.report(settings)["ready_to_deliver"] is True


def test_the_routes_are_operator_only_and_reject_unknown_fixes(make_client, tmp_path, monkeypatch):
    home = tmp_path / "rhome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "rgitconfig"))
    c = make_client()
    with c:
        report = c.get("/api/host/readiness").json()
        assert {x["id"] for x in report["checks"]} >= {"workspace", "git", "git_identity", "github_ssh", "agents", "tools", "disk"}
        assert "network" not in {x["id"] for x in report["checks"]}
        assert c.post("/api/host/readiness/fix", json={"action": "rm_rf"}).status_code == 422
        assert c.post("/api/host/readiness/fix", json={"action": "set_git_identity", "name": "X", "email": "bad"}).status_code == 422
        ok = c.post("/api/host/readiness/fix", json={"action": "set_git_identity", "name": "Pi Builder", "email": "pi@example.com"})
        assert ok.status_code == 200 and "Commits will be made as" in ok.json()["message"]
        assert {x["id"]: x["status"] for x in ok.json()["report"]["checks"]}["git_identity"] == "ok"


def test_a_tool_the_dashboard_installed_itself_is_found_even_off_path(host, tmp_path, monkeypatch):
    home, settings = host
    managed = tmp_path / "agent-tools"
    node = managed / "tools" / "node" / "current" / "bin" / "node"
    node.parent.mkdir(parents=True)
    node.write_text("#!/bin/sh\n")
    node.chmod(0o755)
    monkeypatch.setenv("MAC_CONTROL_AGENT_TOOLS_ROOT", str(managed))
    tools = {t["id"]: t["installed"] for t in by_id(hr.report(settings))["tools"]["tools"]}
    assert tools["node"] is True


def _managed(tmp_path, monkeypatch, name="codex"):
    managed = tmp_path / "agent-tools"
    tool = managed / "bin" / name
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    monkeypatch.setenv("MAC_CONTROL_AGENT_TOOLS_ROOT", str(managed))
    return managed


def test_tools_the_dashboard_installed_are_put_on_the_shell_path_on_request_and_idempotently(host, tmp_path, monkeypatch):
    home, settings = host
    assert by_id(hr.report(settings))["tools_path"]["status"] == "info"                     # nothing installed: nothing to say
    managed = _managed(tmp_path, monkeypatch)
    check = by_id(hr.report(settings))["tools_path"]
    assert check["status"] == "warn" and "command not found" in check["detail"] and check["fix"]["action"] == "add_tools_to_path"
    message = hr.apply(settings, "add_tools_to_path")
    assert ".profile" in message and ".bashrc" in message and "new terminal" in message
    for name in (".profile", ".bashrc"):
        text = (home / name).read_text()
        assert text.count(hr.PATH_BEGIN) == 1 and f'export PATH="{managed}/bin:$PATH"' in text
    hr.apply(settings, "add_tools_to_path")
    assert (home / ".profile").read_text().count(hr.PATH_BEGIN) == 1                           # running it again does not stack blocks
    assert by_id(hr.report(settings))["tools_path"]["status"] == "ok"


def test_an_existing_profile_is_kept_when_the_path_block_is_added(host, tmp_path, monkeypatch):
    home, settings = host
    (home / ".profile").write_text('export EDITOR=vi\n')
    _managed(tmp_path, monkeypatch)
    hr.apply(settings, "add_tools_to_path")
    assert (home / ".profile").read_text().startswith("export EDITOR=vi\n")


def test_the_sign_in_command_uses_the_full_path_when_the_tool_is_not_on_the_shell_path(tmp_path, monkeypatch):
    import tool_install as ti
    tool = tmp_path / "managed" / "bin" / "codex"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert ti.login_command("codex login --device-auth", str(tool)) == f"{tool} login --device-auth"
    monkeypatch.setenv("PATH", f"{tool.parent}:/usr/bin:/bin")
    assert ti.login_command("codex login --device-auth", str(tool)) == "codex login --device-auth"        # on the PATH: the short command works
    assert ti.login_command("codex login --device-auth", None) == "codex login --device-auth"             # not installed: unchanged
    assert ti.login_command("hermes model", str(tool)) == "hermes model"                                  # a different tool's path is never substituted
    spaced = tmp_path / "my tools" / "bin" / "codex"
    spaced.parent.mkdir(parents=True)
    spaced.write_text("#!/bin/sh\n")
    spaced.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert ti.login_command("codex login --device-auth", str(spaced)).startswith("'") and "my tools" in ti.login_command("codex login --device-auth", str(spaced))
