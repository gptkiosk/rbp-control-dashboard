from __future__ import annotations

import json
import os
import stat

import mcp

CLAUDE_LIST = """Checking MCP server health…

claude.ai Google Drive: https://drivemcp.googleapis.com/mcp/v1 - ✔ Connected
claude.ai Google Calendar: https://calendarmcp.googleapis.com/mcp/v1 - ! Connected · tools fetch failed — Request timed out
headroom: headroom mcp serve - ✔ Connected
"""


def test_parse_claude_list_marks_account_connectors_unremovable():
    servers = {s["name"]: s for s in mcp.parse_claude_list(CLAUDE_LIST)}
    assert set(servers) == {"claude.ai Google Drive", "claude.ai Google Calendar", "headroom"}
    assert servers["claude.ai Google Drive"]["removable"] is False
    assert servers["claude.ai Google Drive"]["transport"] == "http"
    assert servers["headroom"]["removable"] is True and servers["headroom"]["transport"] == "stdio"
    assert "timed out" in servers["claude.ai Google Calendar"]["status"]


def test_parse_codex_and_openclaw():
    codex = json.dumps([{"name": "code-review", "enabled": False, "transport": {
        "type": "stdio", "command": "/bin/sh", "args": ["-c", "x"], "env": {"GITHUB_TOKEN": "ghp_secretsecret1234"}}}])
    out = mcp.parse_codex_list(codex)[0]
    assert out["status"] == "disabled" and out["env_names"] == ["GITHUB_TOKEN"]
    assert "ghp_secret" not in json.dumps(out)
    assert mcp.parse_openclaw_list("{}") == []
    oc = mcp.parse_openclaw_list(json.dumps({"fs": {"command": "npx", "args": ["-y", "pkg"]}}))
    assert oc[0]["name"] == "fs" and oc[0]["target"] == "npx -y pkg"


def test_parse_hermes_empty():
    assert mcp.parse_hermes_list("\n  No MCP servers configured.\n\n  Add one with:\n") == []


def test_hermes_list_and_save_receipts():
    rows = mcp.parse_hermes_list("MCP Servers:\nName Transport Tools Status\nmcd python all ✓ enabled\nfs npx all ✗ disabled\n")
    assert [(r["name"], r["enabled"]) for r in rows] == [("mcd", True), ("fs", False)]
    assert mcp.hermes_change_saved("add", "mcd", "Saved 'mcd' to ~/.hermes/config.yaml (7/7 tools enabled)")
    assert mcp.hermes_change_saved("remove", "mcd", "Removed 'mcd' from config")
    for output in ("Connected! Found 7 tool(s)\nCancelled.", "Saved 'mcd' to config (disabled)", "Saved 'other' to config (7/7 tools enabled)"):
        assert not mcp.hermes_change_saved("add", "mcd", output)


def test_validate_spec():
    ok = {"transport": "stdio", "command": "npx", "args": [], "env_names": ["GITHUB_TOKEN"]}
    mcp.validate_spec("hermes", "add", "github", ok)
    bad = [
        ("hermes", "add", "bad name!", ok, "Name"),
        ("hermes", "add", "x", {**ok, "command": ""}, "command"),
        ("hermes", "add", "x", {"transport": "http", "url": "http://evil.example"}, "https"),
        ("hermes", "add", "x", {**ok, "env_names": ["lower_case"]}, "UPPER"),
        ("skynet", "add", "x", ok, "Unknown agent"),
        ("hermes", "upgrade", "x", ok, "Action"),
    ]
    for agent, action, name, spec, needle in bad:
        try:
            mcp.validate_spec(agent, action, name, spec)
        except ValueError as exc:
            assert needle in str(exc)
        else:
            raise AssertionError(f"accepted {name} {spec}")


def test_apply_argv_per_agent():
    spec = {"transport": "stdio", "command": "npx", "args": ["-y", "pkg", "/dir"], "env_names": ["K"]}
    env = {"K": "v"}
    assert mcp.apply_argv("claude", "add", "fs", spec, env, "claude") == [
        ["claude", "mcp", "add", "-s", "user", "-e", "K=v", "fs", "--", "npx", "-y", "pkg", "/dir"]]
    assert mcp.apply_argv("codex", "add", "fs", spec, env, "codex") == [
        ["codex", "mcp", "add", "fs", "--env", "K=v", "--", "npx", "-y", "pkg", "/dir"]]
    hermes = mcp.apply_argv("hermes", "add", "fs", spec, env, "hermes")[0]
    assert hermes[-4:] == ["--args", "-y", "pkg", "/dir"]  # --args must be last
    oc = mcp.apply_argv("openclaw", "add", "fs", spec, env, "openclaw")
    assert oc[0][:4] == ["openclaw", "mcp", "set", "fs"] and json.loads(oc[0][4])["env"] == {"K": "v"}
    assert oc[1] == ["openclaw", "mcp", "reload"]
    assert mcp.apply_argv("openclaw", "remove", "fs", {}, {}, "openclaw")[0] == [
        "openclaw", "config", "unset", "mcp.servers.fs"]
    assert mcp.apply_argv("claude", "remove", "fs", {}, {}, "claude") == [["claude", "mcp", "remove", "fs", "-s", "user"]]


def test_read_env_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text('# comment\nGITHUB_TOKEN="ghp_abc"\nEMPTY=\nPLAIN=value\n')
    assert mcp.read_env_file(f) == {"GITHUB_TOKEN": "ghp_abc", "EMPTY": "", "PLAIN": "value"}
    assert mcp.read_env_file(tmp_path / "missing") == {}


def _fake_cli(tmp_path):
    """A stand-in agent CLI that echoes its arguments (so tests can check redaction)."""
    script = tmp_path / "fake-hermes"
    script.write_text('''#!/bin/sh
if [ "$2" = "list" ]; then
  echo 'github server all ✓ enabled'
else
  read answer || exit 1
  echo "called: $@"
  echo "Saved 'github' to config.yaml (7/7 tools enabled)"
fi
''')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_change_flow_applies_on_approval_and_never_shows_secret(make_client, tmp_path, monkeypatch):
    monkeypatch.setenv("MAC_CONTROL_HERMES_PATH", str(_fake_cli(tmp_path)))
    client = make_client()
    data_dir = tmp_path / "data"
    (data_dir / ".env").write_text("GITHUB_TOKEN=ghp_SUPERSECRETVALUE123456\n")
    r = client.post("/api/mcp/changes", json={
        "agent": "hermes", "action": "add", "name": "github", "transport": "stdio",
        "command": "github-mcp-server", "args": ["stdio"], "env_names": ["GITHUB_TOKEN"]})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    cid = r.json()["id"]
    assert client.get("/api/mcp/env-names").json() == {"names": ["GITHUB_TOKEN"]}
    applied = client.post(f"/api/mcp/changes/{cid}/approve").json()
    assert applied["status"] == "applied"
    assert "called: mcp add github" in applied["output"]
    everything = json.dumps(client.get("/api/mcp/changes").json())
    assert "SUPERSECRET" not in everything and "ghp_SUPER" not in everything
    assert client.post(f"/api/mcp/changes/{cid}/approve").status_code == 409  # not pending anymore


def test_hermes_zero_exit_cancel_is_not_applied(make_client, tmp_path, monkeypatch):
    script = tmp_path / "cancel-hermes"
    script.write_text("#!/bin/sh\necho 'Connected! Found 7 tools'\necho 'Cancelled.'\nexit 0\n")
    script.chmod(0o700)
    monkeypatch.setenv("MAC_CONTROL_HERMES_PATH", str(script))
    client = make_client()
    cid = client.post("/api/mcp/changes", json={"agent": "hermes", "action": "add", "name": "mcd", "transport": "stdio", "command": "python"}).json()["id"]
    assert client.post(f"/api/mcp/changes/{cid}/approve").json()["status"] == "failed"


def test_hermes_save_receipt_without_persisted_registration_is_not_applied(make_client, tmp_path, monkeypatch):
    script = tmp_path / "unpersisted-hermes"
    script.write_text('''#!/bin/sh
if [ "$2" = "list" ]; then
  echo 'No MCP servers configured.'
else
  read answer || exit 1
  echo "Saved 'mcd' to config.yaml (7/7 tools enabled)"
fi
''')
    script.chmod(0o700)
    monkeypatch.setenv("MAC_CONTROL_HERMES_PATH", str(script))
    client = make_client()
    cid = client.post("/api/mcp/changes", json={"agent": "hermes", "action": "add", "name": "mcd", "transport": "stdio", "command": "python"}).json()["id"]
    applied = client.post(f"/api/mcp/changes/{cid}/approve").json()
    assert applied["status"] == "failed" and "Verification failed" in applied["output"]


def test_approve_with_missing_env_fails_without_running(make_client, tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    script = tmp_path / "fake-codex"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MAC_CONTROL_CODEX_PATH", str(script))
    client = make_client()
    cid = client.post("/api/mcp/changes", json={
        "agent": "codex", "action": "add", "name": "gh", "transport": "stdio",
        "command": "x", "env_names": ["NOT_SET"]}).json()["id"]
    out = client.post(f"/api/mcp/changes/{cid}/approve").json()
    assert out["status"] == "failed" and "NOT_SET" in out["output"]
    assert not os.path.exists(marker)


def test_reject_writes_nothing(make_client):
    client = make_client()
    cid = client.post("/api/mcp/changes", json={"agent": "hermes", "action": "remove", "name": "fs"}).json()["id"]
    assert client.post(f"/api/mcp/changes/{cid}/reject").json()["status"] == "rejected"
    assert client.post(f"/api/mcp/changes/{cid}/approve").status_code == 409


def test_cannot_remove_claude_ai_connector(make_client, monkeypatch):
    import routes.mcp as routes_mcp
    import time
    routes_mcp._CACHE["claude"] = (time.time(), {"agent": "claude", "error": None, "checked_at": 0,
                                                 "servers": mcp.parse_claude_list(CLAUDE_LIST)})
    client = make_client()
    r = client.post("/api/mcp/changes", json={"agent": "claude", "action": "remove", "name": "claude.ai Google Drive"})
    assert r.status_code == 422
    routes_mcp._CACHE.pop("claude", None)


def test_an_agent_whose_command_is_not_on_this_host_is_a_quiet_state_not_an_error(tmp_path, monkeypatch):
    import asyncio
    import routes.mcp as routes_mcp
    from settings import get_settings
    monkeypatch.setenv("MAC_CONTROL_CODEX_PATH", str(tmp_path / "no-such-codex"))
    get_settings.cache_clear()
    routes_mcp._CACHE.clear()
    try:
        listing = asyncio.run(routes_mcp.list_for("codex", refresh=True))
    finally:
        routes_mcp._CACHE.clear()
        get_settings.cache_clear()
    assert listing["installed"] is False and listing["error"] is None and listing["servers"] == []


def test_a_command_that_runs_and_fails_is_still_reported_as_a_failure(tmp_path, monkeypatch):
    import asyncio
    import routes.mcp as routes_mcp
    from settings import get_settings
    script = tmp_path / "bad-codex"
    script.write_text("#!/bin/sh\nexit 3\n")
    script.chmod(0o755)
    monkeypatch.setenv("MAC_CONTROL_CODEX_PATH", str(script))
    get_settings.cache_clear()
    routes_mcp._CACHE.clear()
    try:
        listing = asyncio.run(routes_mcp.list_for("codex", refresh=True))
    finally:
        routes_mcp._CACHE.clear()
        get_settings.cache_clear()
    assert listing["installed"] is True and listing["error"] == "list failed (exit 3)"
