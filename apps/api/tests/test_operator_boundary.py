"""Agent processes cannot reach operator APIs over loopback, whatever they inherit or forge.

The acceptance test runs a real API server and real short-lived synthetic processes: a runner
recorded on an unfinished run whose detached grandchild makes the calls, and a process started
from a configured agent executable. The test process itself plays the operator.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import select

from db import make_engine, make_session_factory
from dispatcher import Dispatcher
from legacy_adapters import EXTRA_PATH
from models import Run, RunEvent
from operator_boundary import REFUSED, UNVERIFIED, Peer, agent_route, runner_env

HERE = Path(__file__).resolve().parent
HOST = HERE / "boundary_host.py"
AGENT = HERE / "boundary_agent.py"
DENIED = ["approve", "create_card", "resume_project", "github_settings", "report_settings",
          "recover", "read_cards", "bearer_cards"]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _request(base, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"X-Mac-Control": "1", "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()
    except OSError:
        return None, ""


def _wait(path, seconds=60):
    deadline = time.monotonic() + seconds
    while not path.exists():
        assert time.monotonic() < deadline, f"timed out waiting for {path.name}"
        time.sleep(0.05)
    return json.loads(path.read_text())


def _stop(proc, group=False):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL) if group else proc.kill()
        except ProcessLookupError:
            pass
    proc.wait(timeout=10)


def _assert_denied(results):
    for name in DENIED:
        status, body = results[name]
        assert status == 403 and json.loads(body)["detail"] == REFUSED, (name, status, body)
    assert results["health"][0] == 200


def test_runner_env_drops_operator_settings(monkeypatch):
    monkeypatch.setenv("MAC_CONTROL_GOOGLE_CLIENT_SECRET", "operator-secret")
    monkeypatch.setenv("MAC_CONTROL_DATA_DIR", "/private/operator")
    monkeypatch.setenv("RCD_OPERATOR", "x")
    monkeypatch.setenv("mcd_lowercase", "x")
    monkeypatch.setenv("UNRELATED_TOOL_SETTING", "kept")
    for env in (runner_env(), Dispatcher._env()):
        assert not any(k.upper().startswith(("MAC_CONTROL_", "MCD_", "RCD_")) for k in env)
        assert env["UNRELATED_TOOL_SETTING"] == "kept"
    assert Dispatcher._env()["PATH"].startswith(":".join(EXTRA_PATH))


def test_agent_shell_env_restores_managed_tools_after_a_login_shell(tmp_path):
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\nexit 0\n")
    node.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "DASHBOARD_AGENT_RUNTIME_PATH": str(tmp_path),
           "BASH_ENV": str(HERE.parent / "agent_shell_env.sh")}
    result = subprocess.run(["/bin/bash", "-lc", "command -v node"], env=env,
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() == str(node)


def test_only_scoped_agent_routes_are_open_to_agents():
    assert agent_route("GET", "/healthz", False)
    assert agent_route("GET", "/api/agent-tools/tasks", True)
    assert agent_route("POST", "/api/hermes-projects", True)
    assert not agent_route("GET", "/api/agent-tools/tasks", False)
    assert not agent_route("POST", "/api/cards/1/approve", True)
    assert not agent_route("POST", "/api/agent-access", True)
    assert not agent_route("POST", "/auth/recover", False)


def test_unverifiable_caller_cannot_change_state(make_client, monkeypatch):
    client = make_client()
    boundary = client.app.state.operator_boundary
    monkeypatch.setattr(boundary, "peer", lambda client, server: Peer(None, "", None, verified=False))
    response = client.post("/api/cards", json={"title": "x", "agent": "claude"})
    assert response.status_code == 403 and response.json()["detail"] == UNVERIFIED
    assert client.get("/api/cards").status_code == 200
    audit = [json.loads(line) for line in (Path(boundary.settings.data_dir) / "security-audit.jsonl").read_text().splitlines()]
    assert audit[-1]["event"] == "operator_api_unverified" and audit[-1]["request"] == "POST /api/cards"


def test_operator_flows_unaffected_without_agent_peer(make_client, tmp_path):
    client = make_client()
    created = client.post("/api/cards", json={"title": "operator card", "agent": "claude", "body": "Do the thing.",
                                              "working_dir": str(tmp_path / "ws" / "proj")})
    assert created.status_code == 201
    assert client.get("/api/cards").status_code == 200


def test_agent_processes_are_refused_over_real_loopback(tmp_path):
    data_dir, dist, ws = tmp_path / "data", tmp_path / "dist", tmp_path / "ws"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>t</title>")
    (ws / "proj").mkdir(parents=True)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = runner_env() | {
        "MAC_CONTROL_ENVIRONMENT": "test", "MAC_CONTROL_DATA_DIR": str(data_dir),
        "MAC_CONTROL_WEB_DIST": str(dist), "MAC_CONTROL_PORT": str(port),
        "MAC_CONTROL_COLLECTOR_ENABLED": "false", "MAC_CONTROL_DISPATCHER_ENABLED": "false",
        "MAC_CONTROL_AUTH_ENABLED": "false", "MAC_CONTROL_WORKDIR_ROOTS": json.dumps([str(ws)]),
        "MAC_CONTROL_GH_PATH": str(tmp_path / "no-gh"),
        "MAC_CONTROL_ALERTS_CONFIG_PATH": str(tmp_path / "alerts.toml"),
        "MAC_CONTROL_AGENT_EXECUTABLES": json.dumps(["synthetic-agent"]),
    }
    server = subprocess.Popen([sys.executable, "-I", str(HOST), str(port)], env=env, cwd=tmp_path)
    runner = executable_agent = None
    try:
        deadline = time.monotonic() + 30
        while _request(base, "GET", "/healthz")[0] != 200:
            assert server.poll() is None and time.monotonic() < deadline, "test server did not start"
            time.sleep(0.1)

        # The operator (this process) is served.
        assert _request(base, "GET", "/api/cards")[0] == 200
        assert _request(base, "POST", "/api/cards", {"title": "operator card", "agent": "claude", "body": "Do the thing.",
                                                     "working_dir": str(ws / "proj")})[0] == 201

        # A runner in its own session, as the dispatcher starts it, inheriting everything.
        forged = env | {"FORGED_SESSION": "stolen-cookie", "FORGED_RECOVERY_TOKEN": "r" * 64,
                        "MAC_CONTROL_GOOGLE_CLIENT_SECRET": "inherited-secret"}
        out, go = tmp_path / "runner-out.json", tmp_path / "go"
        runner = subprocess.Popen([sys.executable, "-I", str(AGENT), "runner", base, str(out), str(go)],
                                  env=forged, cwd=ws, start_new_session=True)
        sessions = make_session_factory(make_engine(data_dir / "data.db"))
        with sessions.begin() as s:
            run = Run(agent="claude", stage="running", started_at=int(time.time()) - 1, working_dir=str(ws),
                      command="[]", log_path="", pid=runner.pid)
            s.add(run)
            s.flush()
            run_id = run.id
        go.write_text("go")
        results = _wait(out)
        _assert_denied(results)
        assert results["_pid"] != runner.pid  # a detached grandchild, not the runner itself

        # A process started from a configured agent executable, outside any dispatched run.
        script = tmp_path / "synthetic-agent"
        shutil.copy(AGENT, script)
        direct_out = tmp_path / "direct-out.json"
        executable_agent = subprocess.Popen(
            [sys.executable, "-I", str(script), "direct", base, str(direct_out)],
            env=forged | {"AGENT_DELAY_S": "2.5"}, cwd=ws)
        _assert_denied(_wait(direct_out))

        # Still served for the operator while agents are active.
        assert _request(base, "GET", "/api/cards")[0] == 200
        assert _request(base, "POST", "/api/cards/999999/approve", {})[0] == 404

        audit = [json.loads(line) for line in (data_dir / "security-audit.jsonl").read_text().splitlines()]
        from_run = [a for a in audit if a["run_id"] == run_id]
        from_executable = [a for a in audit if a["run_id"] is None]
        assert {a["request"] for a in from_run} >= {"POST /api/cards/1/approve", "POST /api/projects/1/resume",
                                                     "PUT /api/github/config", "POST /auth/recover"}
        assert all(a["event"] == "operator_api_refused" and a["pid"] == results["_pid"] for a in from_run)
        assert len(from_executable) == len(DENIED)
        assert "inherited-secret" not in (data_dir / "security-audit.jsonl").read_text()
        assert oct((data_dir / "security-audit.jsonl").stat().st_mode & 0o777) == "0o600"
        with sessions() as s:
            notes = [e.text for e in s.scalars(select(RunEvent).where(RunEvent.run_id == run_id))]
        assert len([n for n in notes if n.startswith("refused operator API call from an agent process")]) == len(DENIED)
    finally:
        for proc, group in ((executable_agent, False), (runner, True), (server, False)):
            if proc is not None:
                _stop(proc, group)


def test_a_zombie_runner_does_not_make_the_caller_unverifiable(monkeypatch):
    """A runner that exited and is not yet reaped holds no sockets. On Linux psutil reports it as
    AccessDenied, which must not turn every operator request into 'could not be verified'."""
    import time
    from types import SimpleNamespace
    import psutil
    from operator_boundary import OperatorBoundary

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and psutil.Process(child.pid).status() != psutil.STATUS_ZOMBIE:
            time.sleep(0.02)
        assert psutil.Process(child.pid).status() == psutil.STATUS_ZOMBIE
        boundary = OperatorBoundary(SimpleNamespace(agent_executables=()), None)
        monkeypatch.setattr(boundary, "_agent_processes", lambda: {child.pid: 7})
        assert boundary.peer(("127.0.0.1", 50123), ("127.0.0.1", 8800)) is None
    finally:
        child.wait()


def test_zombie_access_denied_has_no_sockets_but_live_process_stays_unverified(monkeypatch):
    from types import SimpleNamespace
    import operator_boundary as boundary

    process = SimpleNamespace(status=lambda: boundary.psutil.STATUS_ZOMBIE)

    def denied(kind):
        raise boundary.psutil.AccessDenied(12345)

    process.net_connections = denied
    monkeypatch.setattr(boundary.psutil, "Process", lambda pid: process)
    guard = boundary.OperatorBoundary(SimpleNamespace(), None)
    monkeypatch.setattr(guard, "_agent_processes", lambda: {12345: 1})
    assert guard.peer(("127.0.0.1", 1234), ("127.0.0.1", 8800)) is None
    process.status = lambda: boundary.psutil.STATUS_RUNNING
    peer = guard.peer(("127.0.0.1", 1234), ("127.0.0.1", 8800))
    assert peer is not None and not peer.verified
