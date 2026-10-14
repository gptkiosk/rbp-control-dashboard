"""The Agent tools API: operator-only, plan then run, and nothing it does touches dispatch, billing or free-only.

The helper is replaced by a function that runs the real engine in-process with the fake installers from
test_tool_install; the real helper and the real tools run in the Lima guest (docs/install/agent-tools.md).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import agents
import tool_install as ti
from routes import tool_installs
from tests.test_tool_install import FakeOps, facts

SECRET_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "OPENROUTER_API_KEY", "MAC_CONTROL_SECRET")


@pytest.fixture
def api(make_client, tmp_path, monkeypatch):
    """A client acting as a signed-in operator, an install folder in tmp_path, a home in tmp_path, and a host that is a good Pi."""
    home = tmp_path / "pihome"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("MAC_CONTROL_AGENT_TOOLS_ROOT", str(tmp_path / "agent-tools"))
    for name in ("CLAUDE", "CODEX", "HERMES", "OPENCLAW"):       # whatever this machine has installed is not found
        monkeypatch.setenv(f"MAC_CONTROL_{name}_PATH", name.lower())
    client = make_client()
    state = {"signed_in": True, "agent": False, "host": facts()}

    @client.app.middleware("http")
    async def operator_session(request, call_next):
        if state["signed_in"]:
            request.state.user = {"email": "operator@example.invalid"}
        if state["agent"]:
            request.state.agent_grant = {"id": "test"}
        return await call_next(request)

    monkeypatch.setattr(ti, "detect_host", lambda root, names=(): state["host"])
    client.state = state
    client.root = tmp_path / "agent-tools"
    client.home = home
    return client


def start(api, monkeypatch, tool, action, ops=None):
    """Plan through the API, then run through the API with the helper replaced by the in-process engine."""
    ran = {}

    def spawn(cfg, body):
        catalog = ti.load_catalog(cfg.catalog_dir)
        ran["outcome"] = ti.run_action(cfg, catalog, body.tool, body.action, expect_plan_sha256=body.plan_sha256,
                                       ops=ops or FakeOps(catalog), facts=api.state["host"])
        return {"started": f"{body.action} {body.tool}", "poll": "/api/agent-installs"}

    monkeypatch.setattr(tool_installs, "_spawn", spawn)
    plan = api.post("/api/agent-installs/plan", json={"tool": tool, "action": action}).json()
    response = api.post("/api/agent-installs/run", json={"tool": tool, "action": action, "plan_sha256": plan["plan_sha256"],
                                                          "confirm": True})
    return plan, response, ran


# --- who may use it ---------------------------------------------------------------------------------


def test_every_route_is_operator_only(api):
    body = {"tool": "codex", "action": "install"}
    run = {**body, "plan_sha256": "0" * 64, "confirm": True}
    api.state["signed_in"] = False
    for method, path, payload in (("get", "/api/agent-installs", None), ("post", "/api/agent-installs/plan", body),
                                  ("post", "/api/agent-installs/run", run)):
        assert getattr(api, method)(path, **({"json": payload} if payload else {})).status_code == 403, path
    api.state["signed_in"], api.state["agent"] = True, True
    for method, path, payload in (("get", "/api/agent-installs", None), ("post", "/api/agent-installs/plan", body),
                                  ("post", "/api/agent-installs/run", run)):
        assert getattr(api, method)(path, **({"json": payload} if payload else {})).status_code == 403, path


def test_bad_input_is_refused_before_anything_runs(api):
    for bad in ({"tool": "../etc", "action": "install"}, {"tool": "codex", "action": "format"}, {"tool": "codex"},
                {"tool": "codex", "action": "install", "extra": 1}):
        assert api.post("/api/agent-installs/plan", json=bad).status_code == 422, bad
    run = {"tool": "codex", "action": "install", "plan_sha256": "xyz", "confirm": True}
    assert api.post("/api/agent-installs/run", json=run).status_code == 422
    run["plan_sha256"] = "0" * 64
    run["confirm"] = False
    assert api.post("/api/agent-installs/run", json=run).status_code == 422
    assert api.post("/api/agent-installs/plan", json={"tool": "node", "action": "install"}).status_code == 422  # a runtime, not a tool


# --- status and plan ---------------------------------------------------------------------------------


def test_status_lists_the_five_tools_with_login_commands_and_no_secrets(api):
    body = api.get("/api/agent-installs").json()
    assert [t["id"] for t in body["tools"]] == ["claude-code", "codex", "openclaw", "hermes", "grok"]
    assert {t["id"]: t["login"]["command"] for t in body["tools"]} == {
        "claude-code": "claude auth login", "codex": "codex login --device-auth", "openclaw": "openclaw onboard", "hermes": "hermes model", "grok": "grok login --device-code"}
    assert body["host"]["bits"] == 64 and body["platform"] == "linux-arm64" and body["tx"] is None and body["running"] is False
    assert body["requirements"]["min_free_disk_mb"] == 2048
    text = json.dumps(body)
    assert "sk-" not in text and "token" not in text.lower().replace("tokens", "")


def test_plan_shows_versions_commands_disk_memory_and_what_stays_unchanged(api):
    plan = api.post("/api/agent-installs/plan", json={"tool": "hermes", "action": "install"}).json()
    assert (plan["from"], plan["to"], plan["tool"], plan["action"]) == (None, "0.22.0", "hermes", "install")
    assert any("--commit e06df9c2eae6901f4c88f464e0ae6e753c0428b8" in c for c in plan["commands"])
    assert plan["disk"]["free_mb"] == 20 * 1024 and plan["memory"]["total_mb"] == 3880
    assert plan["login"]["command"] == "hermes model"
    assert any("Dispatch" in u for u in plan["unchanged"]) and plan["refusals"] == []
    refused = api.post("/api/agent-installs/plan", json={"tool": "codex", "action": "rollback"}).json()
    assert refused["refusals"] and "not installed" in refused["refusals"][0]


# --- refusals through the API -----------------------------------------------------------------------------


@pytest.mark.parametrize("over,text", [(dict(pointer_bits=32, machine="armv7l"), "32-bit"), (dict(disk_free_mb=1500), "2048 MB"),
                                       (dict(euid=0), "root")])
def test_the_api_refuses_to_start_a_run_the_host_cannot_take(api, monkeypatch, over, text):
    plan = api.post("/api/agent-installs/plan", json={"tool": "codex", "action": "install"}).json()
    api.state["host"] = facts(**over)
    spawned = []
    monkeypatch.setattr(tool_installs, "_spawn", lambda *a, **k: spawned.append(a))
    response = api.post("/api/agent-installs/run", json={"tool": "codex", "action": "install", "plan_sha256": plan["plan_sha256"],
                                                          "confirm": True})
    assert response.status_code == 409 and text in json.dumps(response.json())
    assert spawned == []


def test_the_api_refuses_a_plan_that_changed_after_the_operator_confirmed_it(api, monkeypatch):
    spawned = []
    monkeypatch.setattr(tool_installs, "_spawn", lambda *a, **k: spawned.append(a))
    response = api.post("/api/agent-installs/run", json={"tool": "codex", "action": "install", "plan_sha256": "1" * 64, "confirm": True})
    assert response.status_code == 409 and "plan changed" in json.dumps(response.json()) and spawned == []


def test_a_dashboard_update_in_progress_blocks_installs(api, monkeypatch):
    monkeypatch.setattr(tool_installs, "_update_in_progress", lambda: "A dashboard update is in progress or was interrupted. Finish it first.")
    plan, response, ran = start(api, monkeypatch, "codex", "install")
    assert response.status_code == 409 and "update is in progress" in json.dumps(response.json()) and not ran


# --- a full cycle through the API ---------------------------------------------------------------------------


def test_install_update_rollback_remove_through_the_api_with_fake_installers(api, monkeypatch):
    plan, response, ran = start(api, monkeypatch, "codex", "install")
    assert response.status_code == 202 and ran["outcome"]["outcome"] == "done"
    body = api.get("/api/agent-installs").json()
    codex = next(t for t in body["tools"] if t["id"] == "codex")
    assert codex["installed"] and codex["installed_version"] == "0.162.1" and codex["path"].endswith("/bin/codex")
    assert codex["actions"]["install"] is None and codex["actions"]["remove"] == [] and body["last"]["outcome"] == "done"
    assert isinstance(body["log"], list)
    _, response, ran = start(api, monkeypatch, "codex", "remove")
    assert response.status_code == 202
    assert not next(t for t in api.get("/api/agent-installs").json()["tools"] if t["id"] == "codex")["installed"]


def test_installing_changes_no_dispatch_billing_free_only_or_profile_setting(api, monkeypatch):
    import settings as app_settings

    def snapshot():
        s = app_settings.get_settings()
        return json.dumps({"billing": api.get("/api/billing").json(), "free_only": s.dispatch_free_only,
                           "routes": s.dispatch_route_classes, "budget": [s.default_budget_usd, s.dispatch_max_budget_usd],
                           "concurrent": s.max_concurrent_runs, "dispatcher": s.dispatcher_enabled}, sort_keys=True)

    before = snapshot()
    settings = app_settings.get_settings()
    assert not agents.REGISTRY["codex"].available(settings)             # not found before the install
    for tool in ("claude-code", "codex", "openclaw", "hermes"):
        _, response, ran = start(api, monkeypatch, tool, "install")
        assert response.status_code == 202 and ran["outcome"]["outcome"] == "done", tool
    # The program is found and the agent shows as available, without a restart ...
    assert all(agents.REGISTRY[a].available(settings) for a in ("claude", "codex", "openclaw", "hermes"))
    assert agents.REGISTRY["codex"].binary(settings) == str(api.root / "bin" / "codex")
    # ... and nothing about how work is dispatched, billed or limited moved.
    assert snapshot() == before
    assert settings.dispatch_free_only is True


def test_an_explicit_agent_path_is_never_replaced_by_a_managed_copy(api, monkeypatch):
    import settings as app_settings
    monkeypatch.setenv("MAC_CONTROL_CODEX_PATH", "/opt/mine/codex")
    app_settings.get_settings.cache_clear()
    settings = app_settings.get_settings()
    start(api, monkeypatch, "codex", "install")
    assert agents.REGISTRY["codex"].binary(settings) == "/opt/mine/codex"


# --- starting the helper ------------------------------------------------------------------------------------


class PopenSpy:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return object()


def confirmed(api, tool="codex", action="install"):
    plan = api.post("/api/agent-installs/plan", json={"tool": tool, "action": action}).json()
    return {"tool": tool, "action": action, "plan_sha256": plan["plan_sha256"], "confirm": True}


def test_the_helper_starts_outside_the_service_with_a_clean_environment(api, monkeypatch):
    for name in SECRET_NAMES:
        monkeypatch.setenv(name, "must-not-leak")
    spy = PopenSpy()
    monkeypatch.setattr(tool_installs.subprocess, "Popen", spy)
    monkeypatch.setattr(tool_installs, "_systemd_run", lambda: None)
    body = confirmed(api)
    response = api.post("/api/agent-installs/run", json=body)
    assert response.status_code == 202
    (argv, kwargs), = spy.calls
    assert argv[1:3] == ["-I", str(tool_installs.API_DIR / "tool_install_helper.py")]
    assert argv[3:] == ["--root", str(api.root), "run", "codex", "install", "--plan-sha256", body["plan_sha256"]]
    assert kwargs["start_new_session"] is True and kwargs["stdin"] == subprocess.DEVNULL and kwargs["cwd"] == str(api.root)
    assert not [k for k in kwargs["env"] if k in SECRET_NAMES] and kwargs["env"]["HOME"] == str(api.home)
    log = api.root / "state" / "helper.log"
    assert log.exists() and oct(log.stat().st_mode & 0o777) == "0o600"
    assert oct((api.root).stat().st_mode & 0o777) == "0o700"


def test_with_systemd_the_helper_is_a_transient_unit_at_low_priority_with_no_new_privileges(api, monkeypatch):
    spy = PopenSpy()
    monkeypatch.setattr(tool_installs.subprocess, "Popen", spy)
    monkeypatch.setattr(tool_installs, "_systemd_run", lambda: "/usr/bin/systemd-run")
    api.post("/api/agent-installs/run", json=confirmed(api, "openclaw"))
    (argv, _), = spy.calls
    assert argv[:3] == ["/usr/bin/systemd-run", "--user", "--collect"]
    assert any(a.startswith("--unit=rcd-tool-install-") for a in argv)
    props = [argv[i + 1] for i, a in enumerate(argv) if a == "-p"]
    assert {"Nice=10", "OOMScoreAdjust=500", "NoNewPrivileges=yes"} <= set(props)
    log = str(api.root / "state" / "helper.log")
    assert f"StandardOutput=append:{log}" in props and f"StandardError=append:{log}" in props
    assert argv[argv.index("--") + 1:][1:3] == ["-I", str(tool_installs.API_DIR / "tool_install_helper.py")]


def test_a_helper_that_cannot_start_is_reported(api, monkeypatch):
    def boom(*a, **k):
        raise OSError("no")

    monkeypatch.setattr(tool_installs.subprocess, "Popen", boom)
    monkeypatch.setattr(tool_installs, "_systemd_run", lambda: None)
    response = api.post("/api/agent-installs/run", json=confirmed(api))
    assert response.status_code == 409 and "could not be started" in response.text


def test_status_shows_a_running_install_and_the_log_tail(api):
    ti_cfg = ti.ToolsConfig(root=api.root, catalog_dir=tool_installs.API_DIR, platform_key="linux-arm64", home=api.home)
    ti.prepare_layout(ti_cfg)
    (api.root / "state" / "helper.log").write_text("\n".join(f"line {i}" for i in range(200)) + "\n")
    state = ti.load_state(ti_cfg)
    state["tx"] = {"id": "abc", "tool": "codex", "action": "install", "phase": "downloading node", "partials": []}
    ti.save_state(ti_cfg, state)
    with ti.invocation_lock(ti_cfg):
        body = api.get("/api/agent-installs").json()
    assert body["tx"]["phase"] == "downloading node" and body["running"] is True
    assert body["log"][-1] == "line 199" and len(body["log"]) == tool_installs.LOG_LINES
    assert all(t["actions"]["install"] and "in progress" in t["actions"]["install"][0] for t in body["tools"])
