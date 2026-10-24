"""Host readiness: what the machine still needs before projects can be built and delivered from it, and the few named fixes."""
from __future__ import annotations

import os
import sys
import stat
from pathlib import Path
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


def test_a_bare_machine_says_what_is_missing_and_offers_only_named_fixes(host, monkeypatch):
    home, settings = host
    monkeypatch.setattr(hr.sys, "platform", "linux")
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
    assert check["status"] == "warn" and "has not accepted it yet" in check["detail"] and check["public_key"].startswith("ssh-ed25519 ")   # a key that exists is not a key GitHub accepts
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
    assert hr.report(settings)["ready_to_deliver"] is False                                       # a key that exists but is untested is not "ready to deliver"
    hr._verified_marker().write_text("2026-10-18\n")
    assert hr.report(settings)["ready_to_deliver"] is True and by_id(hr.report(settings))["github_ssh"]["status"] == "ok"


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


def test_the_path_fix_includes_managed_node_and_is_offered_again_when_node_arrives_later(host, tmp_path, monkeypatch):
    home, settings = host
    managed = _managed(tmp_path, monkeypatch)
    hr.apply(settings, "add_tools_to_path")
    assert by_id(hr.report(settings))["tools_path"]["status"] == "ok"
    node = managed / "tools" / "node" / "current" / "bin"
    node.mkdir(parents=True)
    (node / "node").write_text("#!/bin/sh\n")
    check = by_id(hr.report(settings))["tools_path"]                                         # the old block lists only the wrappers folder
    assert check["status"] == "warn" and "node" in check["detail"] and check["fix"]["action"] == "add_tools_to_path"
    assert "Node.js" in hr.apply(settings, "add_tools_to_path")
    for name in (".profile", ".bashrc"):
        text = (home / name).read_text()
        assert text.count(hr.PATH_BEGIN) == 1 and f'export PATH="{managed}/bin:{node}:$PATH"' in text
    assert by_id(hr.report(settings))["tools_path"]["status"] == "ok"


def test_a_missing_verification_tool_points_at_agent_tools_and_an_installed_one_is_found(host, tmp_path, monkeypatch):
    home, settings = host
    for name in ("gitleaks", "csstree-validator"):
        assert hr._how_to_get(name)["kind"] == "agent_tools"
    _managed(tmp_path, monkeypatch, "gitleaks")
    rows = {t["id"]: t for t in by_id(hr.report(settings))["tools"]["tools"]}
    assert rows["gitleaks"]["installed"] is True and "secret scan" in rows["gitleaks"]["needed_for"]
    assert "csstree-validator" in rows


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


def test_testing_github_ignores_the_system_ssh_config_and_records_only_a_success(host, monkeypatch):
    home, settings = host
    hr.apply(settings, "make_github_key")
    seen = []

    def fake_run(cmd, timeout=8, env=None):
        seen.append(cmd)
        return 1, "Hi someone! You've successfully authenticated, but GitHub does not provide shell access."
    monkeypatch.setattr(hr, "_run", fake_run)
    assert "GitHub accepted the key" in hr.apply(settings, "test_github_ssh")
    cmd = seen[0]
    assert cmd[cmd.index("-F") + 1] == os.devnull and "IdentitiesOnly=yes" in cmd and "git" + chr(64) + "github.com" in cmd
    assert hr._verified_marker().is_file() and by_id(hr.report(settings))["github_ssh"]["status"] == "ok"
    hr._verified_marker().unlink()
    monkeypatch.setattr(hr, "_run", lambda *a, **k: (255, "git@github.com: Permission denied (publickey)."))
    with pytest.raises(hr.ReadinessError) as refused:
        hr.apply(settings, "test_github_ssh")
    assert refused.value.status == 409 and not hr._verified_marker().exists()                    # a refusal never marks the key as accepted


def test_tools_are_found_under_the_roots_the_settings_name_and_agents_the_way_the_dashboard_finds_them(host, tmp_path):
    home, settings = host
    managed = tmp_path / "managed"
    (managed / "tools" / "node" / "current" / "bin").mkdir(parents=True)
    node = managed / "tools" / "node" / "current" / "bin" / "node"
    node.write_text("#!/bin/sh\n")
    node.chmod(0o755)
    (managed / "bin").mkdir()
    claude = managed / "bin" / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    settings.agent_tools_path = managed                                       # the settings' own answer wins over the defaults
    checks = by_id(hr.report(settings))
    assert {t["id"]: t["installed"] for t in checks["tools"]["tools"]}["node"] is True
    assert checks["tools_path"]["status"] == "warn" and str(managed / "bin") in checks["tools_path"]["detail"]       # installed tools exist and the shell cannot see them
    assert {a["id"]: a["installed"] for a in checks["agents"]["agents"]}["claude"] is True                         # an agent installed after startup is found, as it is when a task runs


def _serve(status):
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(status)
            self.end_headers()

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_service_that_refuses_unfamiliar_clients_with_403_is_still_reachable(monkeypatch):
    import urllib.request
    server = _serve(403)
    real = urllib.request.urlopen
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=5: real(urllib.request.Request(f"http://127.0.0.1:{server.server_port}", method="HEAD", headers=dict(req.header_items())), timeout=timeout))
    ok, why = hr._reachable("openrouter.ai")
    server.shutdown()
    assert ok is True and "403" in why


def test_a_host_that_cannot_be_connected_to_is_unreachable_and_the_reason_is_named(monkeypatch):
    import socket
    import urllib.request
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                                     # nothing listens here now
    real = urllib.request.urlopen
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=5: real(urllib.request.Request(f"http://127.0.0.1:{port}", method="HEAD"), timeout=timeout))
    ok, why = hr._reachable("github.com")
    assert ok is False and "URLError" in why
    check = hr.check_network()
    assert check["status"] == "warn" and "Cannot reach: github.com (" in check["detail"] and "openrouter.ai (" in check["detail"]


def test_the_network_check_sends_a_real_user_agent_not_the_python_default(monkeypatch):
    import urllib.request
    seen = {}

    class Done(Exception):
        pass

    def fake(req, timeout=5):
        seen.update({k.lower(): v for k, v in req.header_items()})
        raise Done()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    hr._reachable("github.com")
    assert seen["user-agent"].startswith("dashboard-host-readiness") and "python-urllib" not in seen["user-agent"].lower()


def test_each_missing_tool_says_how_to_get_it_and_the_dashboard_never_offers_to_run_a_sudo_command(host, monkeypatch):
    home, settings = host
    monkeypatch.setattr(hr.sys, "platform", "linux")
    monkeypatch.setattr(hr, "_tool", lambda name, settings=None: None)                       # nothing is installed
    tools = {t["id"]: t for t in by_id(hr.report(settings))["tools"]["tools"]}
    assert tools["gh"]["get"]["kind"] == "agent_tools" and tools["gh"]["get"]["tool"] == "gh"
    assert tools["node"]["get"]["kind"] == "agent_tools"
    docker = tools["docker"]["get"]
    assert docker["kind"] == "command" and "docker" in docker["command"] and "does not run it" in docker["note"]
    assert tools["ffmpeg"]["get"]["kind"] == "command" and tools["python3"]["get"]["kind"] == "command"
    monkeypatch.setattr(hr.sys, "platform", "linux")
    assert "apt-get" in hr._how_to_get("docker")["command"] and "usermod" in hr._how_to_get("docker")["command"]
    monkeypatch.setattr(hr.sys, "platform", "darwin")
    assert hr._how_to_get("docker")["command"].startswith("brew install") and hr._how_to_get("unknown") is None


def test_a_tool_that_is_present_carries_no_hint(host):
    home, settings = host
    present = [t for t in by_id(hr.report(settings))["tools"]["tools"] if t["installed"]]
    assert present and all("get" not in t for t in present)


def test_on_a_mac_hints_use_homebrew_and_colima_and_start_with_installing_homebrew_when_it_is_missing(host, monkeypatch):
    home, settings = host
    monkeypatch.setattr(hr.sys, "platform", "darwin")
    present = set()
    monkeypatch.setattr(hr, "_tool", lambda name, settings=None: f"/opt/{name}" if name in present else None)
    monkeypatch.setattr(hr, "_colima_running", lambda: False)
    tools = {t["id"]: t for t in by_id(hr.report(settings))["tools"]["tools"]}
    assert {"brew", "colima"} <= set(tools)                                                         # Mac-only rows
    assert tools["brew"]["get"]["command"].startswith("/bin/bash -c") and "asks for your password" in tools["brew"]["get"]["note"]
    for name in ("docker", "ffmpeg", "python3"):
        assert tools[name]["get"]["command"] == hr.BREW_INSTALL and "Homebrew is not installed" in tools[name]["get"]["note"]     # Homebrew first
    present.add("brew")
    tools = {t["id"]: t for t in by_id(hr.report(settings))["tools"]["tools"]}
    assert tools["brew"]["installed"] is True and "get" not in tools["brew"]
    assert tools["docker"]["get"]["command"] == "brew install colima docker docker-compose && colima start" and tools["ffmpeg"]["get"]["command"] == "brew install ffmpeg"
    present.update({"docker", "colima"})
    tools = {t["id"]: t for t in by_id(hr.report(settings))["tools"]["tools"]}
    assert tools["colima"]["installed"] is False and tools["colima"]["stopped"] is True and tools["colima"]["get"]["command"] == "colima start"
    assert "colima (stopped)" in by_id(hr.report(settings))["tools"]["detail"]
    monkeypatch.setattr(hr, "_colima_running", lambda: True)
    assert {t["id"]: t for t in by_id(hr.report(settings))["tools"]["tools"]}["colima"]["installed"] is True


def test_on_linux_there_are_no_homebrew_or_colima_rows(host, monkeypatch):
    home, settings = host
    monkeypatch.setattr(hr.sys, "platform", "linux")
    assert not ({"brew", "colima"} & {t["id"] for t in by_id(hr.report(settings))["tools"]["tools"]})


# ---------------------------------------------------------------- Homebrew installs and Colima, run by the dashboard on a Mac


@pytest.fixture
def mac(host, tmp_path, monkeypatch):
    home, settings = host
    settings.data_dir = tmp_path / "data"
    monkeypatch.setattr(hr.sys, "platform", "darwin")
    hr.JOB["current"] = None
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()

    def tool(name, body):
        path = bin_dir / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
        return str(path)
    paths = {"brew": tool("brew", 'echo "brew $@"; env | grep -E "SECRET|TOKEN"; if [ "$1" = "list" ]; then printf "ffmpeg\\npython\\nwget\\n"; fi; sleep 0.2; exit $(cat "$0.exit" 2>/dev/null || echo 0)'),
             "colima": tool("colima", 'echo "colima $@"; exit 0')}
    present = {"brew", "colima"}
    monkeypatch.setattr(hr, "_tool", lambda name, settings=None: paths.get(name) if name in present else None)
    yield settings, present
    hr.JOB["current"] = None


def _wait_done(limit=8.0):
    import time
    end = time.time() + limit
    while time.time() < end:
        job = hr.current_job()
        if job and job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def test_a_homebrew_install_runs_only_whitelisted_formulae_with_a_clean_environment_and_shows_its_log(mac, monkeypatch):
    settings, present = mac
    monkeypatch.setenv("MY_SECRET_VALUE", "do-not-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "do-not-leak")
    message = hr.apply(settings, "brew_install", tool="docker")
    assert "brew install colima docker docker-compose" in message
    job = _wait_done()
    assert job["state"] == "done" and job["exit"] == 0 and job["label"] == "Installing docker with Homebrew"
    log = " ".join(job["tail"])
    assert "install colima docker docker-compose" in log and "do-not-leak" not in log                 # the host's secrets never reach the child
    for tool, formulae in (("ffmpeg", "ffmpeg"), ("python3", "python"), ("colima", "colima")):
        hr.apply(settings, "brew_install", tool=tool)
        assert f"install {formulae}" in " ".join(_wait_done()["tail"])


def test_a_failed_homebrew_install_is_reported_with_its_exit_code(mac, monkeypatch):
    settings, present = mac
    Path(hr._tool("brew") + ".exit").write_text("3")
    hr.apply(settings, "brew_install", tool="ffmpeg")
    job = _wait_done()
    assert job["state"] == "failed" and job["exit"] == 3
    assert hr._job_env().keys() >= {"HOME", "PATH"}


def test_only_one_job_runs_at_a_time_and_unknown_tools_or_a_missing_brew_are_refused(mac):
    settings, present = mac
    hr.apply(settings, "brew_install", tool="ffmpeg")
    with pytest.raises(hr.ReadinessError) as busy:
        hr.apply(settings, "brew_install", tool="python3")
    assert busy.value.status == 409 and "still running" in str(busy.value)
    _wait_done()
    with pytest.raises(hr.ReadinessError, match="Choose ffmpeg"):
        hr.apply(settings, "brew_install", tool="rm")
    present.discard("brew")
    with pytest.raises(hr.ReadinessError) as nobrew:
        hr.apply(settings, "brew_install", tool="ffmpeg")
    assert nobrew.value.status == 409 and "Install it first" in str(nobrew.value)


def test_homebrew_and_colima_actions_are_refused_off_a_mac(host, monkeypatch):
    home, settings = host
    monkeypatch.setattr(hr.sys, "platform", "linux")
    for action, kwargs in (("brew_install", {"tool": "ffmpeg"}), ("colima_start", {})):
        with pytest.raises(hr.ReadinessError) as refused:
            hr.apply(settings, action, **kwargs)
        assert refused.value.status == 409


def test_colima_can_be_started_and_missing_tools_offer_the_matching_fix(mac, monkeypatch):
    settings, present = mac
    assert "colima start" in hr.apply(settings, "colima_start")
    assert "colima start" in " ".join(_wait_done()["tail"])
    monkeypatch.setattr(hr, "_colima_running", lambda: False)
    present.update({"colima", "docker"})
    tools = {t["id"]: t for t in by_id(hr.report(settings))["tools"]["tools"]}
    assert tools["colima"]["get"]["fix"] == {"action": "colima_start", "label": "Start Colima"}
    present.discard("docker")
    present.discard("colima")
    tools = {t["id"]: t for t in by_id(hr.report(settings))["tools"]["tools"]}
    assert tools["docker"]["get"]["fix"] == {"action": "brew_install", "tool": "docker", "label": "Install docker with Homebrew"}
    assert "fix" not in tools["gh"]["get"] and "fix" not in tools["brew"].get("get", {})                 # gh comes from Agent tools; Homebrew itself needs the person's password
    present.discard("brew")
    tools = {t["id"]: t for t in by_id(hr.report(settings))["tools"]["tools"]}
    assert "fix" not in tools["docker"]["get"] and tools["docker"]["get"]["command"] == hr.BREW_INSTALL   # no Homebrew yet: install it first, no button


def test_the_job_route_and_the_tool_field_are_validated(make_client, tmp_path, monkeypatch):
    home = tmp_path / "jhome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    hr.JOB["current"] = None
    c = make_client()
    with c:
        assert c.get("/api/host/readiness/job").json() == {"job": None}
        assert c.post("/api/host/readiness/fix", json={"action": "brew_install", "tool": "rm -rf /"}).status_code == 422
        refused = c.post("/api/host/readiness/fix", json={"action": "brew_install", "tool": "ffmpeg"})
        assert refused.status_code == 409 if sys.platform != "darwin" else refused.status_code in (409, 200)


def test_updating_homebrew_tools_runs_update_then_upgrades_only_the_managed_formulae_that_are_installed(mac):
    settings, present = mac
    assert "brew update, then brew upgrade ffmpeg python" in hr.apply(settings, "brew_update")        # wget is installed too but is not the wizard's tool
    job = _wait_done()
    log = "\n".join(job["tail"])
    assert job["state"] == "done" and "$ " in log and "brew update" in log and "brew upgrade ffmpeg python" in log and "wget" not in log.split("upgrade")[-1]
    tools = by_id(hr.report(settings))["tools"]
    assert tools["fix"] == {"action": "brew_update", "label": "Update tools with Homebrew"}


def test_a_failing_update_stops_before_upgrading_anything(mac):
    settings, present = mac
    Path(hr._tool("brew") + ".exit").write_text("1")
    hr.apply(settings, "brew_update")
    job = _wait_done()
    assert job["state"] == "failed" and job["exit"] == 1
    assert "brew upgrade" not in "\n".join(job["tail"])                                              # nothing is upgraded after a failed update


def test_the_update_action_is_for_a_mac_with_homebrew_and_offered_nowhere_else(host, monkeypatch, mac):
    settings, present = mac
    present.discard("brew")
    with pytest.raises(hr.ReadinessError, match="Install it first"):
        hr.apply(settings, "brew_update")
    assert by_id(hr.report(settings))["tools"]["fix"] is None                                           # no Homebrew: no update button
    monkeypatch.setattr(hr.sys, "platform", "linux")
    with pytest.raises(hr.ReadinessError, match="for a Mac"):
        hr.apply(settings, "brew_update")
    assert by_id(hr.report(settings))["tools"]["fix"] is None


# ---------------------------------------------------------------- the Settings panel: every optional tool, Install (All), Upgrade (All) and a health check


def test_the_system_tools_panel_lists_versions_and_offers_install_all_only_with_homebrew(mac):
    settings, present = mac
    body = hr.system_tools(settings)
    rows = {r["id"]: r for r in body["tools"]}
    assert body["platform"] == "mac" and body["brew"]["installed"] and body["can_install_all"] and body["can_upgrade_all"]
    assert rows["colima"]["installed"] and rows["docker"]["installed"] is False and rows["docker"]["version"] is None
    assert set(body["missing"]) == {"python3", "node", "ffmpeg", "docker", "gh", "gitleaks", "csstree-validator"}
    assert rows["gitleaks"]["formulae"] == [] and rows["csstree-validator"]["formulae"] == []          # they come from Agent tools, so Homebrew's Install (All) leaves them out
    present.discard("brew")
    nobrew = hr.system_tools(settings)
    assert nobrew["brew"]["installed"] is False and nobrew["brew"]["install_command"] == hr.BREW_INSTALL
    assert not nobrew["can_install_all"] and not nobrew["can_upgrade_all"]                     # Homebrew first, and the panel says so


def test_install_all_runs_one_brew_install_for_everything_missing_and_shows_the_log(mac):
    settings, present = mac
    assert "brew install colima docker docker-compose ffmpeg gh python" in hr.apply(settings, "brew_install_all")      # Docker needs Colima; brew skips what is already installed
    job = _wait_done()
    log = "\n".join(job["tail"])
    assert job["state"] == "done" and job["label"] == "Installing optional tools with Homebrew"
    assert "install colima docker docker-compose ffmpeg gh python" in log


def test_upgrade_all_updates_homebrew_then_upgrades_only_the_optional_tools_that_are_installed(mac):
    settings, present = mac
    assert "brew update, then brew upgrade ffmpeg python" in hr.apply(settings, "brew_upgrade_all")
    job = _wait_done()
    assert job["state"] == "done" and "brew upgrade ffmpeg python" in "\n".join(job["tail"]) and job["label"] == "Upgrading optional tools with Homebrew"


def test_install_all_and_upgrade_all_are_refused_without_homebrew_or_off_a_mac(mac, monkeypatch):
    settings, present = mac
    present.discard("brew")
    for action in ("brew_install_all", "brew_upgrade_all"):
        with pytest.raises(hr.ReadinessError, match="Install it first"):
            hr.apply(settings, action)
    monkeypatch.setattr(hr.sys, "platform", "linux")
    body = hr.system_tools(settings)
    assert body["platform"] == "linux" and not body["can_install_all"] and "sudo apt-get install -y" in (body["apt_command"] or "")
    for action in ("brew_install_all", "brew_upgrade_all"):
        with pytest.raises(hr.ReadinessError, match="for a Mac"):
            hr.apply(settings, action)


def test_the_health_check_reports_a_stopped_docker_engine_with_the_next_step(mac, tmp_path, monkeypatch):
    settings, present = mac
    docker = tmp_path / "fakebin" / "docker"
    docker.write_text('#!/bin/sh\nif [ "$1" = "info" ]; then exit 1; fi\necho "Docker version 29.3.0, build x"\n')
    docker.chmod(0o755)
    real = hr._tool
    monkeypatch.setattr(hr, "_tool", lambda name, settings=None: str(docker) if name == "docker" else real(name, settings))
    checks = {c["id"]: c for c in hr.system_tools_health(settings)["checks"]}
    assert checks["docker"]["ok"] is False and checks["docker"]["version"] == "29.3.0"
    assert any("Start Colima" in step for step in checks["docker"]["next"])
