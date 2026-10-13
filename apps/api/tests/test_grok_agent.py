"""Grok Build as an agent: its output, its command line, its place behind the dispatch gate.

The output samples follow the line shapes in xai-grok-pager's headless Messages reducer (system/init,
assistant, result) and the error line `grok -p` prints when nobody is signed in. They are not recordings
of a signed-in run: no account was used.
"""
import json
import sys
from types import SimpleNamespace

import pytest

import agent_git
import agents
from agents import REGISTRY, GrokParser, build_grok
from dispatch_gate import DispatchDenied, admit

INIT = {"type": "system", "subtype": "init", "session_id": "0f6c1c1e-aaaa-4bbb-8ccc-1234567890ab", "apiKeySource": "oauth",
        "model": "grok-4.6", "cwd": "/w", "permissionMode": "acceptEdits", "tools": ["Bash", "Read"], "uuid": "u1"}
ASSISTANT = {"type": "assistant", "message": {"id": "m1", "type": "message", "role": "assistant", "model": "grok-4.6",
             "content": [{"type": "text", "text": "Changed one file."}, {"type": "tool_use", "id": "t1", "name": "Edit", "input": {}}],
             "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5}}, "session_id": "s", "uuid": "u2"}
RESULT = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 1200, "duration_api_ms": 900, "num_turns": 2,
          "result": "Done: edited a.txt and ran the checks.", "stop_reason": "end_turn", "total_cost_usd": 0.0123,
          "usage": {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 500},
          "modelUsage": {}, "session_id": "0f6c1c1e-aaaa-4bbb-8ccc-1234567890ab", "uuid": "u3"}


def feed(*events):
    parser = GrokParser()
    lines = [out for ev in events for out in parser.feed(json.dumps(ev))]
    return parser.meta, lines


def test_a_successful_run_reports_model_session_tokens_cost_and_the_handoff():
    meta, lines = feed(INIT, ASSISTANT, RESULT)
    assert (meta.model_reported, meta.provider, meta.session_id) == ("grok-4.6", "xai", INIT["session_id"])
    assert meta.input_tokens == 5500 and meta.cached_input_tokens == 4000 and meta.cache_write_tokens == 500
    assert meta.output_tokens == 200 and meta.cost_usd == 0.0123
    assert meta.result_text == "Done: edited a.txt and ran the checks." and meta.error is None
    assert "Changed one file." in lines and "tool: Edit" in lines and any(l.startswith("finished") for l in lines)


def test_an_error_result_and_the_signed_out_error_line_are_failures():
    meta, _ = feed(INIT, {**RESULT, "subtype": "error_during_execution", "is_error": True, "result": None,
                          "errors": ["cancelled"], "total_cost_usd": 0})
    assert meta.error
    meta, lines = feed({"type": "error", "message": "Not signed in. To authenticate without a browser, run:\n  grok login --device-code"})
    assert "Not signed in" in meta.error and lines[0].startswith("error:")
    # anything that is not JSON is kept as a log line, not dropped
    parser = GrokParser()
    assert parser.feed("plain text") == ["plain text"] and parser.feed("") == []


def card(mode="edit", **kw):
    return SimpleNamespace(mode=mode, **kw)


def test_the_command_line_pins_the_model_and_confines_the_run():
    argv = build_grok(card("read"), "do it", "grok-4.6", 0.0, "/bin/grok", session_id="sess-1")
    assert argv[:4] == ["/bin/grok", "--no-auto-update", "-p", "do it"]
    assert argv[argv.index("--output-format") + 1] == "streaming-messages-json"
    assert argv[argv.index("--permission-mode") + 1] == "plan" and argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv.count("--model") == 1 and argv[argv.index("--model") + 1] == "grok-4.6"
    assert argv[argv.index("--resume") + 1] == "sess-1"
    denied = [argv[i + 1] for i, a in enumerate(argv) if a == "--deny"]
    assert denied == ["Bash(git push:*)", "Bash(git merge:*)", "Bash(gh pr merge:*)"]
    edit = build_grok(card("edit"), "do it", None, 0.0, "/bin/grok")
    assert edit[edit.index("--permission-mode") + 1] == "acceptEdits" and edit[edit.index("--sandbox") + 1] == "workspace"
    assert "--model" not in edit and "--resume" not in edit and "--max-budget-usd" not in edit
    assert "--always-approve" not in edit and "bypassPermissions" not in edit


def test_a_project_grant_allows_one_exact_push_and_no_blanket_deny(monkeypatch):
    grant = SimpleNamespace(clones=[SimpleNamespace(dir="repo", repo="o/r", branch="project-5/x")])
    monkeypatch.setattr(agent_git, "claude_denied", lambda g: ["Bash(git merge:*)"])
    monkeypatch.setattr(agent_git, "claude_allowed", lambda g: ["--allowedTools", "Bash(git -C repo push origin project-5/x)"])
    argv = build_grok(card("edit", agent_git_grant=grant), "p", "grok-4.6", 0.0, "/bin/grok")
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--allow"] == ["Bash(git -C repo push origin project-5/x)"]
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--deny"] == ["Bash(git merge:*)"]


def row(agent, cap, price_class):
    return SimpleNamespace(agent=agent, model_requested="grok-4.6",
                           checkpoint=json.dumps({"dispatch_policy": {"target": "", "budget_usd": cap, "price_class": price_class}}))


def gate_settings(price_class):
    return SimpleNamespace(dispatch_free_only=False, dispatch_max_budget_usd=5.0,
                           dispatch_route_classes={"grok||grok-4.6": price_class}, environment="test")


def test_grok_runs_on_a_subscription_and_is_refused_on_api_billing():
    argv = ["grok", "--model", "grok-4.6"]
    assert admit(gate_settings("subscription"), row("grok", 1, "subscription"), argv)["price_class"] == "subscription"
    # The CLI has no dollar cap, so a paid route has no enforced boundary and does not start.
    with pytest.raises(DispatchDenied, match="BUDGET_UNENFORCED"):
        admit(gate_settings("paid"), row("grok", 1, "paid"), argv)
    with pytest.raises(DispatchDenied, match="ROUTE_UNPINNED"):
        admit(gate_settings("subscription"), row("grok", 1, "subscription"), ["grok"])


def test_grok_is_registered_with_a_safe_default():
    spec = REGISTRY["grok"]
    assert spec.name == "Grok Build" and spec.role == "worker" and spec.binary_setting == "grok_path"
    assert "grok" in agents.SUBSCRIPTION_AGENTS and "grok" in agents.BILLED_AGENTS
    import billing
    assert billing.DEFAULT_ACCOUNTS["grok"] == {"mode": "api", "monthly_usd": 0.0}   # refused until the operator saves a subscription
    assert agents.GROK_PRIVACY_ENV["GROK_TELEMETRY_TRACE_UPLOAD"] == "false"


def test_a_grok_run_always_starts_with_telemetry_and_trace_upload_off(monkeypatch):
    from dispatcher import Dispatcher
    monkeypatch.setenv("GROK_TELEMETRY_TRACE_UPLOAD", "true")   # whatever the host had, the run does not
    env = Dispatcher._env("grok")
    assert env["GROK_TELEMETRY_TRACE_UPLOAD"] == "false" and env["GROK_TELEMETRY_ENABLED"] == "false"
    other = Dispatcher._env("claude")
    assert "GROK_TELEMETRY_ENABLED" not in other and not any(k.startswith("MAC_CONTROL_") for k in env)


def test_a_dispatched_grok_task_runs_through_the_real_adapter(sessions, tmp_path):
    """The whole path with a stand-in `grok` executable: gate, command line, privacy environment, parser, run record."""
    import asyncio
    from dispatcher import Dispatcher
    from models import Card, Run
    from sqlalchemy import select
    import time
    from tests.test_dispatcher import _drain

    seen = tmp_path / "seen.json"
    stand_in = tmp_path / "grok"
    stand_in.write_text("#!" + sys.executable + "\n" + "\n".join([
        "import json, os, sys",
        f"open({str(seen)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], 'env': {{k: v for k, v in os.environ.items() if k.startswith('GROK_')}}}}))",
        f"print({json.dumps(INIT)!r})",
        f"print({json.dumps(ASSISTANT)!r})",
        f"print({json.dumps(RESULT)!r})",
    ]) + "\n")
    stand_in.chmod(0o755)
    settings = SimpleNamespace(runs_dir=tmp_path / "runs", max_concurrent_runs=2, default_budget_usd=0.0, grok_path=str(stand_in),
                               run_retention_days=90, dispatch_free_only=False, dispatch_max_budget_usd=1.0,
                               dispatch_route_classes={"grok||grok-4.6": "subscription"})
    now = int(time.time())
    with sessions.begin() as s:
        card = Card(title="t", body="Summarise the repo.", agent="grok", model="grok-4.6", mode="read", working_dir=str(tmp_path),
                    column="queued", position=1.0, timeout_s=30, needs_approval=False, created_by="operator",
                    created_at=now, updated_at=now)
        s.add(card)
        s.flush()
        cid = card.id
    d = Dispatcher(sessions, settings)
    asyncio.run(_drain(d))
    with sessions() as s:
        run = s.scalar(select(Run).where(Run.card_id == cid))
        assert run.stage == "succeeded" and s.get(Card, cid).column == "done"
        assert (run.model_reported, run.provider, run.input_tokens, run.output_tokens, run.cost_usd) == ("grok-4.6", "xai", 5500, 200, 0.0123)
        assert run.result_text.startswith("Done: edited a.txt")
        assert "Summarise the repo." not in run.command and "<prompt>" in run.command   # the prompt is never stored in the command
    got = json.loads(seen.read_text())
    assert got["argv"][:2] == ["--no-auto-update", "-p"] and "--sandbox" in got["argv"] and "read-only" in got["argv"]
    assert got["env"]["GROK_TELEMETRY_TRACE_UPLOAD"] == "false"
