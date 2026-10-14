#!/usr/bin/env python3
"""Offline stand-in for the claude, codex, hermes and openclaw CLIs.

The demo harness points MAC_CONTROL_{CLAUDE,CODEX,HERMES,OPENCLAW}_PATH at tiny wrappers that run
`agent_stub.py <agent> <argv...>`. The stub speaks each CLI's output format (see apps/api/agents.py),
makes no network calls and reads no credentials. It does real file work in the story workspace so the
finished project has real artifacts.

Behaviour comes from a marker line in the story text:

    [demo] story=<key> scenario=<normal|slow|hang-once|cancel-once> run=<none|build> files=<a,b>

Environment (set by the harness): DEMO_STATE_DIR, DEMO_FIXTURES, DEMO_PLAN.
Every start, finish and termination is appended to $DEMO_STATE_DIR/events.jsonl for the harness to assert.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("DEMO_STATE_DIR", "."))
FIXTURES = Path(os.environ.get("DEMO_FIXTURES", "."))
PLAN = Path(os.environ.get("DEMO_PLAN", "plan.json"))
MAX_LIFETIME_S = 120  # orphans left by a killed API still exit on their own
STARTED = time.time()

AGENT = sys.argv[1]
ARGS = sys.argv[2:]
STORY = "pipeline"
MODEL = ""


def log(event: str, **extra) -> None:
    row = {"ts": time.time(), "event": event, "agent": AGENT, "story": STORY, "model": MODEL,
           "pid": os.getpid(), "run_id": os.environ.get("RCD_RUN_ID"),
           "key": os.environ.get("RCD_IDEMPOTENCY_KEY"), **extra}
    with open(STATE / "events.jsonl", "a") as handle:
        handle.write(json.dumps(row) + "\n")


def option(name: str) -> str:
    return ARGS[ARGS.index(name) + 1] if name in ARGS and ARGS.index(name) + 1 < len(ARGS) else ""


def prompt_and_model() -> tuple[str, str]:
    if AGENT == "claude":
        return option("-p"), option("--model")
    if AGENT == "codex":
        return ARGS[-1], option("-m")
    if AGENT == "hermes":
        return option("-q"), option("-m")
    return option("-m"), option("--model")  # openclaw: -m is the message


def invocation_number(story: str) -> int:
    path = STATE / f"count-{story}.txt"
    count = int(path.read_text()) + 1 if path.exists() else 1
    path.write_text(str(count))
    return count


def on_term(_signum, _frame) -> None:
    log("terminated")
    os._exit(143)


def wait(seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if time.time() - STARTED > MAX_LIFETIME_S:
            log("expired")
            os._exit(3)
        time.sleep(0.5)


def emit(text: str, tokens: tuple[int, int] = (120, 60), session: str = "demo-session") -> None:
    """Print the agent's result in the dialect its parser in agents.py expects."""
    if AGENT == "claude":
        print(json.dumps({"type": "system", "subtype": "init", "model": MODEL, "session_id": session, "permissionMode": "acceptEdits"}))
        print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Working."}]}}), flush=True)
        print(json.dumps({"type": "result", "result": text, "num_turns": 1, "total_cost_usd": 0.0,
                          "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]}}))
    elif AGENT == "codex":
        print(json.dumps({"type": "thread.started", "thread_id": session}))
        print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text}}))
        print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]}}))
    elif AGENT == "hermes":
        print(json.dumps({"type": "system", "subtype": "init", "model": MODEL or "demo-hermes", "session_id": session}))
        print(json.dumps({"type": "result", "text": text, "tokens": {"input": tokens[0], "output": tokens[1]}, "exit_code": 0}))
    else:  # openclaw prints one JSON document when the turn ends
        provider = MODEL.split("/")[0] if "/" in MODEL else "openrouter"
        print(json.dumps({"status": "ok", "result": {
            "meta": {"agentMeta": {"model": MODEL.removeprefix("openrouter/"), "provider": provider, "sessionId": session,
                                   "usage": {"input": tokens[0], "output": tokens[1]}}},
            "payloads": [{"text": text}]}}))
    sys.stdout.flush()


def plan_nodes() -> list[dict]:
    return json.loads(PLAN.read_text())["nodes"]


def pipeline_step(prompt: str) -> bool:
    """Answer MCD's own coordinator, planner and dispatch prompts. Returns True when handled."""
    if prompt.startswith("You are the project coordinator."):
        choices = json.loads(re.search(r"^Candidates: (\[.*\])$", prompt, re.M).group(1))
        log("coordinate", choice=choices[0])
        emit(json.dumps({**choices[0], "rationale": "Demo: the first operator-approved candidate."}))
    elif prompt.startswith("Read-only project planning."):
        log("plan", nodes=len(plan_nodes()))
        emit(json.dumps({"nodes": plan_nodes()}))
    elif prompt.startswith("Read-only plan review."):
        log("plan-review", nodes=len(plan_nodes()))
        emit(json.dumps({"nodes": plan_nodes()}))
    elif prompt.startswith("Read-only orchestration only."):
        manifest = json.loads(prompt.split("Approved plan: ", 1)[1])
        log("dispatch", order=manifest["order"])
        emit(json.dumps({"order": manifest["order"], "summary": "Demo: dependency order from the approved manifest."}))
    else:
        return False
    return True


def run_script(name: str, *extra: str) -> str:
    done = subprocess.run([sys.executable, name, *extra], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        log("script-failed", script=name, stderr=done.stderr[-400:], stdout=done.stdout[-400:])
        emit(f"The story is not complete: {name} failed.\n\n{done.stdout[-300:]}{done.stderr[-300:]}")
        sys.exit(0)
    return done.stdout.strip()


def story_work(prompt: str) -> None:
    global STORY
    marker = re.search(r"\[demo\] story=(\S+) scenario=(\S+) run=(\S+) files=(\S*)", prompt)
    if not marker:
        log("no-marker")
        emit("The story is not complete: no demo marker found.")
        return
    STORY, scenario, run, files = marker.group(1), marker.group(2), marker.group(3), marker.group(4)
    number = invocation_number(STORY)
    log("start", scenario=scenario, invocation=number, cwd=os.getcwd())

    if scenario == "slow":
        wait(12)
    elif scenario == "hang-once" and number == 1:
        log("hanging")
        wait(MAX_LIFETIME_S)
    elif scenario == "cancel-once" and number == 1:
        log("working-long")
        wait(25)
    else:
        wait(1)

    written = []
    for rel in [f for f in files.split(",") if f]:
        target = Path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / "site" / rel, target)
        written.append(rel)

    summary = f"Wrote {', '.join(written)}." if written else "No files written."
    if run == "build":
        # The decision is read from the shared project context MCD appended to this prompt.
        context = prompt.split("MCD SHARED PROJECT CONTEXT", 1)[-1]
        theme = re.search(r"Decision: theme=(light|dark|auto)", context)
        if not theme:
            log("missing-decision")
            emit("The story is not complete: no theme decision was found in the project context, so nothing was built.")
            return
        summary = f"Built the site with theme {theme.group(1)}. " + run_script("build.py", "--theme", theme.group(1))
        summary += " Checked the built site: " + run_script("check_site.py")
        log("theme", theme=theme.group(1))

    log("finish", scenario=scenario, invocation=number)
    emit(f"Handoff for {STORY}: {summary}\n\nChecks: ran in the story workspace. Remaining risks: none (demo stub).")


def main() -> None:
    global MODEL
    signal.signal(signal.SIGTERM, on_term)
    prompt, MODEL = prompt_and_model()
    log("invoked", argv_head=ARGS[:4])
    if not pipeline_step(prompt):
        story_work(prompt)


if __name__ == "__main__":
    main()
