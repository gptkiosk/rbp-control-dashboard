#!/usr/bin/env python3
"""Scripted acceptance run for the RCD demo project.

Starts a private RCD API on an unused loopback port with a fresh data directory and offline stub agents,
then drives the whole workflow and asserts every checkpoint:

  CP01 preflight       CP05 handoff policy   CP09 timeout         CP13 finish + artifacts
  CP02 create plan     CP06 level-1 run      CP10 cancel
  CP03 review assigns  CP07 interrupt (kill) CP11 human decision
  CP04 submit/execute  CP08 recover          CP12 resume

Modes (see demo/RUNBOOK.md):
  validate   offline fixture checks, standard library only, no server
  rehearsal  (default) private server with the dispatcher OFF; checks plan creation and assignments only
  execute    full run; turns the dispatcher ON for the private instance only, with stub agents

Safety: never touches port 8800 or the live data directory, never stops any process except the API it
started itself (tracked by PID), keeps the collector off, sets HOME to a scratch directory and gives the
stub agents no credentials or network use.

Exit codes: 0 all pass, 1 assertion failed, 2 refused to start (safety/usage), 3 environment blocked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1]
REPO = DEMO.parent
API_DIR = REPO / "apps" / "api"
PLAN_FILE = DEMO / "plan" / "project.json"
FIXTURES = DEMO / "fixtures"
STUB = DEMO / "stubs" / "agent_stub.py"
LIVE_PORT = 8800
AGENTS = ("claude", "codex", "hermes", "openclaw")

# Mirrors apps/api/approval.py OUTWARD_PATTERNS and projects.handoff_exclusion: a story whose text matches
# is excluded from automatic handoff, which would break the unattended part of the scenario.
OUTWARD = re.compile(r"\b(git\s+push|push\s+(to|the|this|it)|merge\s+(to|into|the|this|pr)|force[- ]push|deploy\w*|release\w*|"
                     r"publish\w*|terraform\s+apply|send\s+(an?\s+)?(email|message)|tweet)\b", re.I)
SENSITIVE = re.compile(r"\b(security|credential|secrets?|vulnerabilit\w*|rotat\w*|license|licensing)\b", re.I)


def now() -> float:
    return time.time()


def iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or now(), timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Failed(Exception):
    """An assertion in the current checkpoint did not hold."""


class Blocked(Exception):
    """The environment cannot run this mode."""


class Evidence:
    """Collects checkpoints and assertions; written to JSON after every checkpoint."""

    def __init__(self, path: Path, header: dict):
        self.path, self.header, self.checkpoints, self.current = path, header, [], None

    def begin(self, cp_id: str, name: str) -> None:
        self.current = {"id": cp_id, "name": name, "status": "running", "started": iso(), "assertions": [], "data": {}}
        self.checkpoints.append(self.current)
        print(f"[{cp_id}] {name}", flush=True)

    def check(self, description: str, ok: bool, **data) -> None:
        self.current["assertions"].append({"description": description, "ok": bool(ok), **({"data": data} if data else {})})
        print(f"    {'ok  ' if ok else 'FAIL'} {description}", flush=True)
        if not ok:
            self.current["status"] = "failed"
            self.save()
            raise Failed(f"{self.current['id']}: {description}")

    def note(self, **data) -> None:
        self.current["data"].update(data)

    def end(self) -> None:
        self.current["status"] = "passed"
        self.current["ended"] = iso()
        self.save()

    def skip(self, cp_id: str, name: str, reason: str) -> None:
        self.checkpoints.append({"id": cp_id, "name": name, "status": "skipped", "reason": reason, "assertions": []})
        print(f"[{cp_id}] {name}: skipped ({reason})", flush=True)

    def save(self, **extra) -> None:
        self.path.write_text(json.dumps({**self.header, **extra, "checkpoints": self.checkpoints}, indent=2, default=str) + "\n")


class Http:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 15) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"X-Mac-Control": "1", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode()
                return response.status, (json.loads(raw) if raw and response.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, raw

    def ok(self, method: str, path: str, body: dict | None = None) -> object:
        status, payload = self.call(method, path, body)
        if status >= 400:
            raise Failed(f"{method} {path} -> {status}: {json.dumps(payload)[:600]}")
        return payload


class ApiProcess:
    """The one API instance this harness owns. Only its own PID is ever signalled."""

    def __init__(self, env: dict, port: int, log_path: Path, python: str):
        self.env, self.port, self.log_path, self.python = env, port, log_path, python
        self.proc: subprocess.Popen | None = None
        self.pids: list[int] = []

    def start(self, timeout: float = 60) -> None:
        log = open(self.log_path, "ab")
        self.proc = subprocess.Popen([self.python, "serve.py"], cwd=API_DIR, env=self.env, stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
        self.pids.append(self.proc.pid)
        deadline = now() + timeout
        while now() < deadline:
            if self.proc.poll() is not None:
                raise Blocked(f"API exited during start with code {self.proc.returncode}; see {self.log_path}")
            try:
                if Http(self.port).call("GET", "/healthz", timeout=2)[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.5)
        raise Blocked(f"API did not become healthy within {timeout}s; see {self.log_path}")

    def kill9(self) -> int:
        assert self.proc is not None and self.proc.poll() is None, "no live API process to kill"
        pid = self.proc.pid
        os.kill(pid, signal.SIGKILL)
        self.proc.wait(timeout=10)
        return pid

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


def wait_for(description: str, probe, timeout: float, interval: float = 0.5):
    deadline = now() + timeout
    last = None
    while now() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(interval)
    raise Failed(f"timed out after {timeout:.0f}s waiting for: {description}")


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(requested: int | None) -> int:
    if requested is not None:
        if requested == LIVE_PORT:
            raise SystemExit("refusing port 8800: it belongs to the live MCD/RCD service")
        if not port_free(requested):
            raise SystemExit(f"port {requested} is occupied; choose another (the owner is never evicted)")
        return requested
    for port in range(8801, 8900):
        if port_free(port):
            return port
    raise SystemExit("no free loopback port in 8801-8899")


# ----------------------------------------------------------------------------- plan helpers


def load_plan() -> dict:
    return json.loads(PLAN_FILE.read_text())


def stories(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if n.get("kind", "story") == "story"]


def levels(nodes: list[dict]) -> dict[str, int]:
    by_key = {n["key"]: n for n in stories(nodes)}
    memo: dict[str, int] = {}

    def level(key: str, seen: tuple = ()) -> int:
        if key in seen:
            raise Failed(f"dependency cycle through {key}")
        if key not in memo:
            deps = by_key[key].get("depends_on", [])
            memo[key] = 1 + max((level(d, seen + (key,)) for d in deps), default=0)
        return memo[key]

    return {key: level(key) for key in by_key}


def plan_summary(nodes: list[dict]) -> dict:
    lv = levels(nodes)
    return {"stories": len(lv), "levels": max(lv.values()), "by_level": {str(n): [k for k, v in lv.items() if v == n] for n in sorted(set(lv.values()))},
            "assignees": sorted({n["assignee"] for n in stories(nodes)}),
            "openrouter_stories": sorted(n["key"] for n in stories(nodes) if n.get("model", "").startswith("openrouter/")),
            "human_stories": sorted(n["key"] for n in stories(nodes) if n["assignee"] == "human")}


def assert_plan_shape(ev: Evidence, nodes: list[dict]) -> dict:
    summary = plan_summary(nodes)
    ev.check("at least 6 stories", summary["stories"] >= 6, stories=summary["stories"])
    ev.check("exactly the 3 dependency levels", summary["levels"] == 3, by_level=summary["by_level"])
    ev.check("mixed assignees (claude, codex, openclaw and human)", {"claude", "codex", "openclaw", "human"} <= set(summary["assignees"]), assignees=summary["assignees"])
    ev.check("at least one human decision story", len(summary["human_stories"]) >= 1, stories=summary["human_stories"])
    ev.check("at least two stories assigned OpenRouter models", len(summary["openrouter_stories"]) >= 2, stories=summary["openrouter_stories"])
    for node in stories(nodes):
        if node["assignee"] != "human":
            ev.check(f"{node['key']} has an assigned model", bool(node.get("model")), model=node.get("model"))
    return summary


# ----------------------------------------------------------------------------- validate mode


def validate_fixtures(ev: Evidence) -> None:
    ev.begin("V01", "Fixture plan is well formed")
    plan = load_plan()
    nodes = plan["nodes"]
    keys = [n["key"] for n in nodes]
    ev.check("node keys are unique", len(keys) == len(set(keys)))
    for node in stories(nodes):
        ev.check(f"{node['key']} dependencies exist", all(d in keys for d in node.get("depends_on", [])))
        ev.check(f"{node['key']} has instructions, acceptance and scope", all(node.get(f, "").strip() for f in ("description", "acceptance", "scope")))
    assert_plan_shape(ev, nodes)
    ev.end()

    ev.begin("V02", "Stories stay eligible for automatic handoff; stub markers and fixtures resolve")
    for node in stories(nodes):
        if node["assignee"] == "human":
            continue
        text = "\n".join(str(node.get(k, "")) for k in ("title", "description", "scope", "acceptance"))
        ev.check(f"{node['key']} text has no outward-action or sensitive-review wording", not OUTWARD.search(text) and not SENSITIVE.search(text))
        marker = re.search(r"\[demo\] story=(\S+) scenario=(\S+) run=(\S+) files=(\S*)", node["description"])
        ev.check(f"{node['key']} has a stub marker for its own key", bool(marker) and marker.group(1) == node["key"])
        for rel in [f for f in marker.group(4).split(",") if f]:
            ev.check(f"{node['key']} fixture {rel} exists", (FIXTURES / "site" / rel).is_file())
    scenarios = {re.search(r"scenario=(\S+)", n["description"]).group(1) for n in stories(nodes) if n["assignee"] != "human"}
    ev.check("interrupt, timeout and cancel scenarios are all present", {"slow", "hang-once", "cancel-once"} <= scenarios, scenarios=sorted(scenarios))
    human = next(n for n in stories(nodes) if n["assignee"] == "human")
    ev.check("human story text cannot satisfy the build story's decision pattern", not re.search(r"theme=(light|dark|auto)", human["description"]))
    ev.end()


# ----------------------------------------------------------------------------- environment


def stub_events(state: Path) -> list[dict]:
    path = state / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def story_events(state: Path, story: str, event: str | None = None) -> list[dict]:
    return [e for e in stub_events(state) if e["story"] == story and (event is None or e["event"] == event)]


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stub_processes_gone(state: Path, story: str, timeout: float = 15) -> bool:
    """True once every stub process that started for the story has exited (checked by PID liveness only; never signalled)."""
    pids = {e["pid"] for e in story_events(state, story, "start")}
    try:
        wait_for(f"{story} stub processes exit", lambda: not any(pid_alive(p) for p in pids), timeout)
    except Failed:
        return False
    return True


class Run:
    """Everything one harness run needs: paths, the API process and typed helpers."""

    def __init__(self, args, out_dir: Path):
        self.args, self.out = args, out_dir
        self.port = pick_port(args.port)
        self.scratch = Path(tempfile.mkdtemp(prefix="rcd-demo-")).resolve()
        self.data = self.scratch / "data"
        self.workdir = self.data / "workspaces" / "docs-site"
        self.state = self.scratch / "stub-state"
        self.bin = self.scratch / "bin"
        self.home = self.scratch / "home"
        for d in (self.workdir, self.state, self.bin, self.home):
            d.mkdir(parents=True)
        self.timeout_s = args.timeout_s
        self.execute = args.mode == "execute"
        self.http = Http(self.port)
        self.api: ApiProcess | None = None
        self.project_id: int | None = None
        self.plan = load_plan()

    def write_stubs(self) -> None:
        for agent in AGENTS:
            wrapper = self.bin / agent
            if agent == "hermes":
                # MCD launches Hermes through integrations/hermes/mcd-run.py, which reads this file's shebang for
                # the interpreter and then imports hermes_cli (the fake package in demo/stubs via PYTHONPATH).
                wrapper.write_text(f"#!{self.args.api_python}\nraise SystemExit('hermes stub is launched through the MCD shim')\n")
            else:
                wrapper.write_text(f'#!/bin/sh\nexec "{self.args.api_python}" "{STUB}" {agent} "$@"\n')
            wrapper.chmod(0o755)
        # Planner answers come from the same fixture the harness validates; working_dir is not part of nodes.
        (self.scratch / "plan.json").write_text(json.dumps({"nodes": self.plan["nodes"]}))

    def env(self) -> dict:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "HOME": str(self.home),
               "MAC_CONTROL_DATA_DIR": str(self.data), "MAC_CONTROL_HOST": "127.0.0.1", "MAC_CONTROL_PORT": str(self.port),
               "MAC_CONTROL_COLLECTOR_ENABLED": "false",
               "MAC_CONTROL_DISPATCHER_ENABLED": "true" if self.execute else "false",
               "MAC_CONTROL_MAX_CONCURRENT_RUNS": "1", "MAC_CONTROL_DEFAULT_TIMEOUT_S": str(self.timeout_s),
               "MAC_CONTROL_WORKDIR_ROOTS": json.dumps([str(self.data / "workspaces")]),
               "MAC_CONTROL_CLAUDE_PATH": str(self.bin / "claude"), "MAC_CONTROL_CODEX_PATH": str(self.bin / "codex"),
               "MAC_CONTROL_HERMES_PATH": str(self.bin / "hermes"), "MAC_CONTROL_OPENCLAW_PATH": str(self.bin / "openclaw"),
               "PYTHONPATH": str(STUB.parent),
               "DEMO_STATE_DIR": str(self.state), "DEMO_FIXTURES": str(FIXTURES), "DEMO_PLAN": str(self.scratch / "plan.json")}
        return env

    def preflight(self, ev: Evidence) -> None:
        ev.check("never targets the live service port 8800", self.port != LIVE_PORT, port=self.port)
        ev.check("private port is free", True, port=self.port)
        ev.check("data directory is a fresh scratch directory", not any(self.data.glob("*.db")) and self.data.is_dir(), data_dir=str(self.data))
        env = self.env()
        ev.check("collector disabled", env["MAC_CONTROL_COLLECTOR_ENABLED"] == "false")
        ev.check("dispatcher flag matches the mode", env["MAC_CONTROL_DISPATCHER_ENABLED"] == ("true" if self.execute else "false"), mode=self.args.mode)
        ev.check("no alert or outbound integration settings are passed", not any(k.startswith(("MAC_CONTROL_ALERT", "MAC_CONTROL_GOOGLE", "MAC_CONTROL_AUTH")) for k in env))
        done = subprocess.run([self.args.api_python, "-c", "import fastapi, uvicorn, sqlalchemy, pydantic_settings, alembic"], capture_output=True, text=True)
        if done.returncode != 0:
            raise Blocked(f"{self.args.api_python} cannot import the API dependencies (install apps/api/requirements.lock.txt in a venv and pass --api-python): {done.stderr.strip()[-300:]}")
        ev.check("API dependencies import", True, python=self.args.api_python)
        ev.check("fixtures present", PLAN_FILE.is_file() and STUB.is_file() and (FIXTURES / "site" / "build.py").is_file())

    def start_api(self) -> None:
        self.api = ApiProcess(self.env(), self.port, self.out / "api.log", self.args.api_python)
        self.api.start()

    # ------------------------------------------------------------------ API views

    def detail(self) -> dict:
        return self.http.ok("GET", f"/api/projects/{self.project_id}")  # type: ignore[return-value]

    def task(self, key: str, detail: dict | None = None) -> dict:
        return next(t for t in (detail or self.detail())["tasks"] if t["node_key"] == key and t["role"] == "story")

    def card(self, key: str) -> dict:
        return self.http.ok("GET", f"/api/cards/{self.task(key)['card_id']}")  # type: ignore[return-value]

    def runs(self, key: str) -> list[dict]:
        return list(reversed(self.card(key)["runs"]))  # oldest first

    def revision(self) -> int:
        return self.detail()["revision"]


# ----------------------------------------------------------------------------- checkpoints


def cp02_create_plan(ev: Evidence, run: Run) -> None:
    """Execute mode asks the planner pipeline for the plan; rehearsal saves the fixture plan directly."""
    ev.begin("CP02", "Create the plan")
    doc = {k: v for k, v in run.plan.items() if k != "nodes"}
    doc["working_dir"] = str(run.workdir)
    doc["nodes"] = [] if run.execute else run.plan["nodes"]
    project = run.http.ok("POST", "/api/projects", doc)
    run.project_id = project["id"]  # type: ignore[index]
    ev.check("project created in draft", project["state"] == "draft", id=run.project_id, state=project["state"])  # type: ignore[index]
    if run.execute:
        run.http.ok("POST", f"/api/projects/{run.project_id}/plan", {"revision": project["revision"], "approve_coordination": True})  # type: ignore[index]
        detail = wait_for("planner pipeline reaches review", lambda: (d := run.detail())["state"] in {"review", "planning_failed"} and d, 180)
        ev.check("planner pipeline produced a plan for review", detail["state"] == "review", state=detail["state"], error=detail.get("error"))  # type: ignore[index]
        events = [e["event"] for e in stub_events(run.state)]
        ev.check("coordinator, planner and plan-review steps all ran", {"coordinate", "plan", "plan-review"} <= set(events), events=events)
    ev.note(project_id=run.project_id)
    ev.end()


def cp03_review_assignments(ev: Evidence, run: Run) -> dict:
    ev.begin("CP03", "Review the assignments")
    detail = run.detail()
    nodes = detail["document"]["nodes"]
    summary = assert_plan_shape(ev, nodes)
    expected = {n["key"]: (n["assignee"], n.get("model", "")) for n in stories(run.plan["nodes"])}
    actual = {n["key"]: (n["assignee"], n.get("model", "")) for n in stories(nodes)}
    ev.check("assignments in the reviewed plan equal the intended assignments", actual == expected, expected=expected, actual=actual)
    for key, (assignee, model) in actual.items():
        print(f"      {key:<18} {assignee:<9} {model or '-'}")
    ev.note(plan=summary)
    ev.end()
    return detail


def cp04_submit(ev: Evidence, run: Run) -> None:
    ev.begin("CP04", "Approve and submit; stories are created exactly once")
    run.http.ok("POST", f"/api/projects/{run.project_id}/submit", {"revision": run.revision(), "approve_coordination": True, "approve_api_work": True})
    detail = wait_for("project becomes active", lambda: (d := run.detail())["state"] in {"active", "dispatch_failed"} and d, 120)
    ev.check("dispatch produced an active project", detail["state"] == "active", state=detail["state"], error=detail.get("error"))  # type: ignore[index]
    intended = stories(run.plan["nodes"])
    tasks = [t for t in detail["tasks"] if t["role"] == "story"]  # type: ignore[index]
    ev.check("one card per story, no duplicates", sorted(t["node_key"] for t in tasks) == sorted(n["key"] for n in intended))
    for node in intended:
        task = run.task(node["key"], detail)  # type: ignore[arg-type]
        if node["assignee"] == "human":
            ev.check(f"{node['key']} waits for the operator", task["column"] == "backlog", column=task["column"])
        else:
            ev.check(f"{node['key']} carries its assigned agent and model", (task["agent"], task["model"]) == (node["assignee"], node["model"]), agent=task["agent"], model=task["model"])
    order = next(e for e in reversed(stub_events(run.state)) if e["event"] == "dispatch")["order"]
    ev.check("dispatch order respects every dependency", all(order.index(d) < order.index(n["key"]) for n in intended for d in n.get("depends_on", [])), order=order)
    ev.note(order=order, cards={t["node_key"]: t["card_id"] for t in tasks})
    ev.end()


def cp05_handoffs(ev: Evidence, run: Run) -> None:
    ev.begin("CP05", "Approve automatic agent handoffs for this exact plan")
    detail = run.detail()
    review = detail["handoff_approval"]
    eligible = sorted(r["title"] for r in review["eligible"])
    ev.check("human story is excluded from automatic handoff", any("HUMAN" in r["title"] for r in review["excluded"]), excluded=review["excluded"])
    ev.check("all agent stories are eligible", len(review["eligible"]) == 5, eligible=eligible, excluded=review["excluded"])
    run.http.ok("POST", f"/api/projects/{run.project_id}/handoff-policy",
                {"revision": detail["revision"], "manifest_hash": review["manifest_hash"], "mode": "automatic", "approve": True})
    ev.check("policy recorded as automatic", run.detail()["handoff_approval"]["mode"] == "automatic")
    ev.end()


def wait_story_done(run: Run, key: str, timeout: float = 120) -> dict:
    return wait_for(f"{key} is done", lambda: (t := run.task(key))["column"] == "done" and t, timeout)  # type: ignore[return-value]


def cp06_level_one(ev: Evidence, run: Run) -> None:
    ev.begin("CP06", "Execute level 1: first story completes and hands off automatically")
    wait_story_done(run, "S1_content")
    start = story_events(run.state, "S1_content", "start")
    ev.check("S1_content ran exactly once on its assigned claude model", len(start) == 1 and start[0]["agent"] == "claude" and start[0]["model"] == "claude-sonnet-5-5", starts=start)
    for page in ("index", "install", "usage"):
        ev.check(f"content/{page}.md written to the workspace", (run.workdir / "content" / f"{page}.md").is_file())
    ev.check("handoff accepted by the automatic policy, not a manual click",
             any(m["kind"] == "handoff" and m["text"].startswith("Agent-reported completion passed under operator project-wide handoff approval") for m in run.detail()["memory"]))
    ev.end()


def cp07_interrupt(ev: Evidence, run: Run) -> dict:
    ev.begin("CP07", "Interrupt: kill the API while S1_changelog_data is running")
    wait_for("S1_changelog_data has started", lambda: story_events(run.state, "S1_changelog_data", "start"), 60)
    running = wait_for("its run is recorded as running", lambda: next((r for r in run.runs("S1_changelog_data") if r["stage"] == "running"), None), 30)
    ev.check("the run uses the assigned OpenRouter model", running["model_requested"] == "openrouter/cohere/north-mini-code:free", model=running["model_requested"])  # type: ignore[index]
    ev.check("no completion exists yet", not story_events(run.state, "S1_changelog_data", "finish"))
    pid = run.api.kill9()  # type: ignore[union-attr]
    ev.check("API process is gone (SIGKILL of the harness-owned PID only)", run.api.proc.poll() is not None, pid=pid, returncode=run.api.proc.returncode)  # type: ignore[union-attr]
    refused = False
    try:
        run.http.call("GET", "/healthz", timeout=2)
    except OSError:
        refused = True
    ev.check("health endpoint no longer answers", refused)
    ev.note(killed_pid=pid, interrupted_run_id=running["id"])  # type: ignore[index]
    ev.end()
    return running  # type: ignore[return-value]


def cp08_recover(ev: Evidence, run: Run, interrupted: dict) -> None:
    ev.begin("CP08", "Recover: restart the API; the story finishes once without duplicate work")
    run.start_api()
    ev.check("API healthy again on the same port and data directory", True, new_pid=run.api.pids[-1])  # type: ignore[union-attr]
    wait_story_done(run, "S1_changelog_data", 150)
    runs = run.runs("S1_changelog_data")
    stages = [r["stage"] for r in runs]
    ev.check("no run is left in 'running'", "running" not in stages, stages=stages)
    ev.check("exactly one run succeeded", stages.count("succeeded") == 1, stages=stages)
    ev.check("still one card per story", len([t for t in run.detail()["tasks"] if t["role"] == "story"]) == 6)
    starts = story_events(run.state, "S1_changelog_data", "start")
    keys = {e["key"] for e in starts if e["key"]}
    ev.check("every start of this story used the same idempotency key", len(keys) == 1, keys=sorted(keys))
    ev.check("changelog.json written and valid", len(json.loads((run.workdir / "changelog.json").read_text())) == 3)
    finishes = story_events(run.state, "S1_changelog_data", "finish")
    path = "reattached to the surviving process" if len(runs) == 1 else "requeued as a new attempt"
    ev.note(recovery_path=path, run_stages=stages, stub_starts=len(starts), stub_finishes=len(finishes),
            duplicate_agent_work=len(finishes) > 1)
    ev.end()


def cp09_timeout(ev: Evidence, run: Run) -> None:
    ev.begin("CP09", f"Timeout: S2_generator hangs and is stopped after {run.timeout_s}s; explicit retry succeeds")
    first = wait_for("S2_generator run reaches a terminal stage", lambda: next((r for r in run.runs("S2_generator") if r["stage"] not in {"running", "queued"}), None), run.timeout_s + 90)
    ev.check("run ended as a timeout", first["stage"] == "timeout", stage=first["stage"], error=first.get("error"))  # type: ignore[index]
    ev.check("card moved to Failed", run.task("S2_generator")["column"] == "failed")
    ev.check("the hung process was stopped by MCD", stub_processes_gone(run.state, "S2_generator"), terminated_logged=bool(story_events(run.state, "S2_generator", "terminated")))
    ev.check("downstream stories did not start", not story_events(run.state, "S2_checker") and not story_events(run.state, "S3_build"))
    ev.check("no partial build.py was accepted", not (run.workdir / "build.py").exists())
    detail = run.detail()
    run.http.ok("POST", f"/api/projects/{run.project_id}/stories/{run.task('S2_generator', detail)['card_id']}/retry", {"revision": detail["revision"]})
    wait_story_done(run, "S2_generator", 120)
    stages = [r["stage"] for r in run.runs("S2_generator")]
    ev.check("retry produced exactly one success after the timeout", stages.count("succeeded") == 1 and "timeout" in stages, stages=stages)
    ev.check("build.py now exists", (run.workdir / "build.py").is_file())
    ev.end()


def cp10_cancel(ev: Evidence, run: Run) -> None:
    ev.begin("CP10", "Cancel: stop S2_checker mid-run; retry completes it")
    wait_for("S2_checker is working", lambda: story_events(run.state, "S2_checker", "working-long"), 90)
    current = wait_for("run is running", lambda: next((r for r in run.runs("S2_checker") if r["stage"] == "running"), None), 20)
    ev.check("the run uses the assigned OpenRouter model", current["model_requested"] == "openrouter/thinkingmachines/inkling:free", model=current["model_requested"])  # type: ignore[index]
    status, payload = run.http.call("POST", f"/api/runs/{current['id']}/cancel")  # type: ignore[index]
    ev.check("cancel accepted", status == 200, status=status, payload=payload)
    ended = wait_for("run becomes cancelled", lambda: next((r for r in run.runs("S2_checker") if r["id"] == current["id"] and r["stage"] != "running"), None), 30)  # type: ignore[index]
    ev.check("run ended as cancelled", ended["stage"] == "cancelled", stage=ended["stage"])  # type: ignore[index]
    ev.check("process was stopped and never finished", stub_processes_gone(run.state, "S2_checker") and not story_events(run.state, "S2_checker", "finish"),
             terminated_logged=bool(story_events(run.state, "S2_checker", "terminated")))
    ev.check("no partial check_site.py left behind", not (run.workdir / "check_site.py").exists())
    ev.check("card moved to Failed, not retried automatically", run.task("S2_checker")["column"] == "failed" and len(run.runs("S2_checker")) == 1)
    detail = run.detail()
    run.http.ok("POST", f"/api/projects/{run.project_id}/stories/{run.task('S2_checker', detail)['card_id']}/retry", {"revision": detail["revision"]})
    wait_story_done(run, "S2_checker", 120)
    stages = [r["stage"] for r in run.runs("S2_checker")]
    ev.check("retry produced exactly one success after the cancellation", stages == ["cancelled", "succeeded"], stages=stages)
    ev.end()


def cp11_human_gate(ev: Evidence, run: Run) -> float:
    ev.begin("CP11", "Human decision: downstream work is held until the operator answers")
    wait_for("the decision story is ready for the operator", lambda: (t := run.task("S2_decide_theme"))["column"] == "backlog" and not t["blocked_by"] and t, 60)
    build = run.task("S3_build")
    ev.check("S3_build is blocked on the decision", build["column"] != "running" and bool(build["blocked_reasons"]), column=build["column"], reasons=build["blocked_reasons"])
    detail = run.detail()
    run.http.ok("POST", f"/api/projects/{run.project_id}/pause", {"revision": detail["revision"]})
    ev.check("operator paused dispatch while deciding", run.detail()["state"] == "paused")
    time.sleep(5)
    ev.check("nothing started while the decision was open", not story_events(run.state, "S3_build"))
    decided_at = now()
    run.http.ok("POST", f"/api/projects/{run.project_id}/stories/{run.task('S2_decide_theme')['card_id']}/accept",
                {"summary": "Decision: theme=dark. The operator prefers the dark theme for the docs site."})
    ev.check("decision story is done", run.task("S2_decide_theme")["column"] == "done")
    ev.check("decision recorded in shared project memory", any("theme=dark" in m["text"] and m["kind"] == "handoff" for m in run.detail()["memory"]))
    ev.note(decided_at=iso(decided_at))
    ev.end()
    return decided_at


def cp12_resume(ev: Evidence, run: Run, decided_at: float) -> None:
    ev.begin("CP12", "Resume: the build runs once and uses the recorded decision")
    detail = run.detail()
    run.http.ok("POST", f"/api/projects/{run.project_id}/resume", {"revision": detail["revision"]})
    ev.check("project active again", run.detail()["state"] == "active")
    wait_story_done(run, "S3_build", 120)
    starts = story_events(run.state, "S3_build", "start")
    ev.check("S3_build started only after the decision", len(starts) == 1 and starts[0]["ts"] > decided_at, start_ts=[s["ts"] for s in starts], decided_at=decided_at)
    theme = story_events(run.state, "S3_build", "theme")
    ev.check("it read theme=dark from shared project context", len(theme) == 1 and theme[0]["theme"] == "dark", events=theme)
    ev.check("it ran on its assigned codex model", starts[0]["model"] == "gpt-5.6-terra", model=starts[0]["model"])
    ev.check("exactly one run for S3_build", [r["stage"] for r in run.runs("S3_build")] == ["succeeded"])
    ev.end()


def cp13_finish(ev: Evidence, run: Run) -> dict:
    ev.begin("CP13", "Finish: project complete with usable artifacts and consistent history")
    detail = wait_for("project completes", lambda: (d := run.detail())["state"] == "complete" and d, 60)
    ev.check("project state is complete", detail["state"] == "complete")  # type: ignore[index]
    tasks = [t for t in detail["tasks"] if t["role"] == "story"]  # type: ignore[index]
    ev.check("every story is done", all(t["column"] == "done" for t in tasks), columns={t["node_key"]: t["column"] for t in tasks})

    wanted = ["content/index.md", "content/install.md", "content/usage.md", "changelog.json", "build.py", "check_site.py",
              "site/index.html", "site/install.html", "site/usage.html", "site/changelog.html", "report.json"]
    missing = [rel for rel in wanted if not (run.workdir / rel).is_file()]
    ev.check("all expected artifacts exist", not missing, missing=missing)
    ev.check("site carries the chosen dark theme", all('data-theme="dark"' in (run.workdir / f"site/{p}.html").read_text() for p in ("index", "install", "usage", "changelog")))
    ev.check("changelog page lists every version", all(v in (run.workdir / "site/changelog.html").read_text() for v in ("0.3.0", "0.2.1", "0.2.0")))
    report = json.loads((run.workdir / "report.json").read_text())
    ev.check("structure check passed", report["ok"] and not report["problems"], report=report)

    # History consistency: ordering, one success per story, model fidelity, no duplicate card or run for completed work.
    events = stub_events(run.state)
    plan_nodes = {n["key"]: n for n in stories(run.plan["nodes"])}
    final_finish = {}
    for e in events:
        if e["event"] == "finish":
            final_finish[e["story"]] = max(final_finish.get(e["story"], 0), e["ts"])
    first_start = {}
    for e in events:
        if e["event"] == "start":
            first_start.setdefault(e["story"], e["ts"])
    ordering = [(key, dep) for key, node in plan_nodes.items() if node["assignee"] != "human" for dep in node["depends_on"]
                if plan_nodes[dep]["assignee"] != "human" and first_start[key] < final_finish[dep]]
    ev.check("no story started before its agent prerequisites finished", not ordering, violations=ordering)
    for key, node in plan_nodes.items():
        if node["assignee"] == "human":
            continue
        runs = run.runs(key)
        ev.check(f"{key}: exactly one successful run", sum(r["stage"] == "succeeded" for r in runs) == 1, stages=[r["stage"] for r in runs])
        models = {r["model_requested"] for r in runs}
        ev.check(f"{key}: every run requested its assigned model", models == {node["model"]}, models=sorted(models), assigned=node["model"])
        logged = {e["model"] for e in events if e["story"] == key and e["event"] == "start"}
        ev.check(f"{key}: the agent CLI actually received that model", logged == {node["model"]}, logged=sorted(logged))
    ctx = run.http.ok("GET", f"/api/projects/{run.project_id}/context")
    ev.check("shared context endpoint carries the decision", "theme=dark" in str(ctx))

    artifacts = {}
    dest = run.out / "artifacts"
    for rel in wanted:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run.workdir / rel, target)
        artifacts[rel] = sha256(target)
    (run.out / "project-memory.json").write_text(json.dumps(detail["memory"], indent=2))  # type: ignore[index]
    shutil.copyfile(run.state / "events.jsonl", run.out / "stub-events.jsonl")
    ev.note(artifacts=artifacts, runs_total={k: len(run.runs(k)) for k in plan_nodes if plan_nodes[k]["assignee"] != "human"})
    ev.end()
    return artifacts


# ----------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["validate", "rehearsal", "execute"], default="rehearsal")
    parser.add_argument("--api-python", default=sys.executable, help="Python with the API dependencies installed (default: this one)")
    parser.add_argument("--port", type=int, help="private loopback port (default: first free from 8801); 8800 is refused")
    parser.add_argument("--timeout-s", type=int, default=30, help="per-card timeout for the private instance (minimum 30)")
    parser.add_argument("--out", type=Path, help="evidence directory (default: demo/out/<timestamp>)")
    parser.add_argument("--keep-scratch", action="store_true", help="keep the scratch data directory for inspection")
    args = parser.parse_args()
    if args.timeout_s < 30:
        print("--timeout-s must be at least 30 (the API's own minimum)", file=sys.stderr)
        return 2
    out = (args.out or DEMO / "out" / datetime.now().strftime("%Y%m%d-%H%M%S")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    header = {"schema": 1, "mode": args.mode, "started": iso(), "host": {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version()}}
    ev = Evidence(out / "evidence.json", header)
    run: Run | None = None
    code = 0
    try:
        if args.mode == "validate":
            validate_fixtures(ev)
        else:
            run = Run(args, out)
            header["private_port"], header["scratch"] = run.port, str(run.scratch)
            ev.begin("CP01", "Preflight and isolation")
            run.write_stubs()
            run.preflight(ev)
            run.start_api()
            ev.note(api_pid=run.api.pids[-1])  # type: ignore[union-attr]
            ev.end()
            cp02_create_plan(ev, run)
            cp03_review_assignments(ev, run)
            if not run.execute:
                for cp, name in (("CP04", "Approve and submit"), ("CP05", "Automatic handoffs"), ("CP06", "Level-1 execution"), ("CP07", "Interrupt"),
                                 ("CP08", "Recover"), ("CP09", "Timeout"), ("CP10", "Cancel"), ("CP11", "Human decision"), ("CP12", "Resume"), ("CP13", "Finish")):
                    ev.skip(cp, name, "needs the dispatcher; run with --mode execute")
            else:
                cp04_submit(ev, run)
                cp05_handoffs(ev, run)
                cp06_level_one(ev, run)
                interrupted = cp07_interrupt(ev, run)
                cp08_recover(ev, run, interrupted)
                cp09_timeout(ev, run)
                cp10_cancel(ev, run)
                decided_at = cp11_human_gate(ev, run)
                cp12_resume(ev, run, decided_at)
                cp13_finish(ev, run)
    except Failed as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        code = 1
        if ev.current and ev.current["status"] == "running":
            ev.current["status"] = "failed"
            ev.current["error"] = str(exc)
        for cp in ev.checkpoints:
            if cp["status"] == "failed" and "error" not in cp:
                cp["error"] = str(exc)
        if run and run.project_id and run.api and run.api.proc and run.api.proc.poll() is None:
            try:
                (out / "failure-project.json").write_text(json.dumps(run.detail(), indent=2))
            except Exception:  # diagnostics only
                pass
    except Blocked as exc:
        print(f"\nBLOCKED: {exc}", file=sys.stderr)
        code = 3
    except SystemExit as exc:
        print(f"\nREFUSED: {exc}", file=sys.stderr)
        code = 2
    finally:
        if run and run.api:
            run.api.stop()
        if run and run.state.exists():
            try:
                shutil.copyfile(run.state / "events.jsonl", out / "stub-events.jsonl")
            except OSError:
                pass
        passed = sum(c["status"] == "passed" for c in ev.checkpoints)
        result = {0: "passed", 1: "failed", 2: "refused", 3: "blocked"}[code]
        ev.save(finished=iso(), result=result, summary={"passed": passed, "failed": sum(c["status"] == "failed" for c in ev.checkpoints),
                                                         "skipped": sum(c["status"] == "skipped" for c in ev.checkpoints)},
                api_pids=run.api.pids if run and run.api else [])
        if run and not args.keep_scratch:
            shutil.rmtree(run.scratch, ignore_errors=True)
        print(f"\nresult: {result}; evidence: {out / 'evidence.json'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
