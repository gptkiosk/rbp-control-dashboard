#!/usr/bin/env python3
"""Probe what each installed agent can really do in an Edit-mode scratch folder, using MCD's own launch arguments.

    python3 scripts/probe-agent-capabilities.py claude codex hermes openclaw

For each agent it creates a throwaway folder under the managed workspaces root, asks the agent to write a file, run a syntax check and a unit test, and try git,
then prints what ran and what was denied, and removes the folder. It calls the real CLIs (it uses a few model requests), so run it after upgrading an agent runtime
or after an update of MCD, not in CI. A CLI change that quietly takes away a permission shows up here, not in the middle of a project.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

API = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API))
import agents  # noqa: E402

TASK = ("Work only in the task folder. 1) Create check.js containing console.log('ok') and run: node --check check.js "
        "2) Create test_probe.py with a unittest.TestCase that has one passing test, and run: python3 -I -m unittest "
        "3) Run: git status. Do not try to work around any refusal. Then reply with exactly three lines: "
        "NODE=ran or NODE=denied, UNITTEST=ran or UNITTEST=denied, GIT=ran or GIT=denied.")
MODELS = {"claude": "claude-haiku-5-5", "codex": "gpt-6-luna", "hermes": "thinkingmachines/inkling:free",
          "openclaw": "openrouter/thinkingmachines/inkling:free"}


def card(agent: str, folder: Path) -> SimpleNamespace:
    return SimpleNamespace(agent=agent, model=MODELS[agent], mode="edit", agent_git_grant=None, output_only=False, subscription_billing=True,
                           timeout_s=240, working_dir=str(folder), agent_target="mm-developer" if agent == "openclaw" else None, id=0)


def argv_for(agent: str, folder: Path) -> list[str]:
    c, task = card(agent, folder), f"The task folder is {folder}. Use absolute paths under it. {TASK}"
    if agent == "claude":
        return agents.build_claude(c, task, c.model, 1.0, "claude")
    if agent == "codex":
        argv = agents.build_codex(c, task, c.model, 1.0, "codex")
        argv[argv.index("-C") + 1] = str(folder)
        return argv
    if agent == "hermes":
        argv = agents.build_hermes(c, task, c.model, 1.0, "hermes")
        argv[argv.index("--in") + 1] = str(folder)
        return argv
    return agents.build_openclaw(c, task, c.model, 1.0, "openclaw")


def remove(folder: Path) -> None:
    for root, dirs, files in os.walk(folder, topdown=False):
        for name in files:
            os.remove(os.path.join(root, name))
        for name in dirs:
            os.rmdir(os.path.join(root, name))
    folder.rmdir()


def main(names: list[str]) -> int:
    data = Path(os.environ.get("MAC_CONTROL_DATA_DIR", Path.home() / ".mac-control"))
    base = data / "workspaces"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    failed = 0
    for name in names:
        if name not in MODELS:
            print(f"{name}: not probed (known: {', '.join(MODELS)})")
            continue
        folder = base / f"probe-{name}-{os.getpid()}"
        folder.mkdir(mode=0o700)
        try:
            run = subprocess.run(argv_for(name, folder), cwd=folder, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
            text = (run.stdout or "") + (run.stderr or "")
        except subprocess.TimeoutExpired:
            text = ""
        got = dict(re.findall(r"(NODE|UNITTEST|GIT)=(ran|denied)", text))
        written = sorted(p.name for p in folder.iterdir() if p.name != "__pycache__")
        wrote = {"check.js", "test_probe.py"} <= set(written)
        ok = got.get("NODE") == "ran" and got.get("UNITTEST") == "ran" and wrote
        failed += 0 if ok else 1
        print(f"{name:<9}{'OK ' if ok else 'FAIL'} node={got.get('NODE', '?'):<7} unittest={got.get('UNITTEST', '?'):<7} git={got.get('GIT', '?'):<7} files in the task folder: {written}")
        remove(folder)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["claude", "codex", "hermes", "openclaw"]))
