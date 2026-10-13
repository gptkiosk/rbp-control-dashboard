from __future__ import annotations

import json
from types import SimpleNamespace

import agents
import pytest

CARD = SimpleNamespace(mode="read", working_dir="/tmp/w", agent_target=None, timeout_s=600)


def test_claude_parser_success_and_tokens():
    p = agents.ClaudeParser()
    p.feed(json.dumps({"type": "system", "subtype": "init", "model": "claude-haiku-5-5",
                       "session_id": "s1", "permissionMode": "plan"}))
    out = p.feed(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "OK"}, {"type": "tool_use", "name": "Read"}]}}))
    assert out == ["OK", "tool: Read"]
    p.feed(json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 1,
                       "result": "OK", "total_cost_usd": 0.0012,
                       "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5,
                                 "cache_read_input_tokens": 100, "output_tokens": 3}}))
    m = p.meta
    assert (m.model_reported, m.session_id, m.input_tokens, m.output_tokens, m.cost_usd) == \
        ("claude-haiku-5-5", "s1", 115, 3, 0.0012)
    assert m.error is None


def test_claude_parser_auth_error_is_reported():
    # Shape captured from the real probe on 2026-10-09 (expired OAuth token).
    p = agents.ClaudeParser()
    p.feed(json.dumps({"type": "result", "is_error": True, "total_cost_usd": 0,
                       "result": "Failed to authenticate. API Error: 401 OAuth access token has expired.",
                       "usage": {"input_tokens": 0, "output_tokens": 0}}))
    assert "401" in p.meta.error


def test_codex_parser():
    p = agents.CodexParser()
    p.feed(json.dumps({"type": "thread.started", "thread_id": "t1"}))
    assert p.feed(json.dumps({"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": "OK"}})) == ["OK"]
    p.feed(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 14957, "output_tokens": 5}}))
    assert (p.meta.session_id, p.meta.input_tokens, p.meta.output_tokens, p.meta.result_text) == ("t1", 14957, 5, "OK")
    assert p.meta.model_reported is None  # Codex does not report the model


def test_hermes_parser():
    p = agents.HermesParser()
    p.feed(json.dumps({"type": "system", "subtype": "init", "model": "thinkingmachines/inkling:free", "session_id": "h1"}))
    p.feed(json.dumps({"type": "text", "text": "OK"}))
    p.feed(json.dumps({"type": "result", "exit_code": 0, "text": "OK", "tokens": {"input": 13994, "output": 35}}))
    assert (p.meta.model_reported, p.meta.provider, p.meta.input_tokens) == ("thinkingmachines/inkling:free", "thinkingmachines", 13994)


def test_openclaw_parser_reads_document_at_exit():
    doc = {"runId": "r", "status": "ok", "result": {"payloads": [{"text": "OK"}], "meta": {"agentMeta": {
        "provider": "openrouter", "model": "google/gemini-2.5-flash-lite", "sessionId": "o1",
        "usage": {"input": 16525, "output": 33}}}}}
    p = agents.OpenClawParser()
    for line in json.dumps(doc, indent=2).splitlines():
        assert p.feed(line) == []
    assert p.finish() == ["OK"]
    assert (p.meta.provider, p.meta.model_reported, p.meta.output_tokens) == ("openrouter", "google/gemini-2.5-flash-lite", 33)


def test_openclaw_parser_garbage_is_error():
    p = agents.OpenClawParser()
    p.feed("not json")
    p.finish()
    assert p.meta.error


def test_openclaw_gateway_timeout_without_json_preserves_cause_not_secret():
    p = agents.OpenClawParser()
    p.feed_stderr('[state-migrations] Legacy config warning')
    p.feed_stderr('GatewayClientRequestError: FailoverError: LLM request timed out. secret-key-value')
    assert p.finish() == [f'error: {p.meta.error}']
    assert p.meta.timed_out and 'provider timed out' in p.meta.error
    assert 'No JSON result was returned' in p.meta.error and 'secret-key-value' not in p.meta.error
    assert p.meta.model_reported is None and p.meta.input_tokens is None


def test_openclaw_other_gateway_error_stays_failed_without_copying_stderr():
    p = agents.OpenClawParser()
    p.feed_stderr('GatewayClientRequestError: unavailable credential=secret')
    p.finish()
    assert not p.meta.timed_out and 'gateway rejected the run' in p.meta.error
    assert 'secret' not in p.meta.error


def test_openclaw_warning_alone_does_not_imply_timeout():
    p = agents.OpenClawParser()
    p.feed_stderr('Warning: model idle timeout may be configured')
    p.finish()
    assert p.meta.error == 'no JSON result from openclaw' and not p.meta.timed_out


def test_openclaw_valid_result_takes_precedence_over_stderr():
    p = agents.OpenClawParser()
    p.feed_stderr('GatewayClientRequestError: FailoverError: LLM request timed out.')
    p.feed(json.dumps({'status': 'ok', 'result': {'payloads': [{'text': 'Recovered'}]}}))
    assert p.finish() == ['Recovered'] and p.meta.error is None and not p.meta.timed_out


def test_claude_argv_modes_and_guards():
    read = agents.build_claude(CARD, "do it", None, 1.0, "claude")
    assert read[read.index("--permission-mode") + 1] == "plan"
    assert "Bash(git push:*)" in read and read[read.index("--max-budget-usd") + 1] == "1.00"
    edit = agents.build_claude(SimpleNamespace(**{**vars(CARD), "mode": "edit"}), "do it", "claude-opus-5-5", 2.5, "claude")
    assert edit[edit.index("--permission-mode") + 1] == "acceptEdits"
    assert edit[edit.index("--model") + 1] == "claude-opus-5-5"


def test_codex_argv_sandbox():
    read = agents.build_codex(CARD, "x", None, 1.0, "codex")
    assert read[read.index("-s") + 1] == "read-only" and read[read.index("-C") + 1] == "/tmp/w"
    edit = agents.build_codex(SimpleNamespace(**{**vars(CARD), "mode": "edit"}), "x", None, 1.0, "codex")
    assert edit[edit.index("-s") + 1] == "workspace-write"
    assert "--dangerously-bypass-approvals-and-sandbox" not in edit


def test_openclaw_never_delivers():
    argv = agents.build_openclaw(CARD, "x", None, 1.0, "openclaw")
    assert "--deliver" not in argv and argv[argv.index("--agent") + 1] == "mm-main"
    assert argv[argv.index("--timeout") + 1] == "600"


def test_openclaw_passes_task_timeout_with_explicit_model_and_session():
    card = SimpleNamespace(**{**vars(CARD), 'timeout_s': 1800, 'agent_target': 'mm-developer'})
    argv = agents.build_openclaw(card, 'work', 'openrouter/model:free', 1, 'openclaw', 'session-1')
    assert argv[argv.index('--timeout') + 1] == '1800'
    assert argv[argv.index('--model') + 1] == 'openrouter/model:free'
    assert argv[argv.index('--session-id') + 1] == 'session-1'
    assert argv[argv.index('--agent') + 1] == 'mm-developer'


@pytest.mark.parametrize('phase,idle,expected', [
    ('provider', True, 'model stopped responding before its idle limit'),
    ('provider', False, 'model request did not finish in time'),
    ('queue', False, 'while waiting to start'),
    ('preflight', False, 'before the model request started'),
    ('post_turn', False, 'while finalizing the response'),
    ('gateway_draining', False, 'while the gateway was shutting down'),
    (None, False, 'before the run completed'),
])
def test_openclaw_structured_timeout_keeps_usage_and_partial_result(phase, idle, expected):
    p = agents.OpenClawParser()
    p.feed(json.dumps({'status': 'timeout', 'result': {
        'payloads': [{'text': 'Partial result'}, {'text': 'model idle timeout' if idle else 'request timed out'}],
        'meta': {'timeoutPhase': phase, 'agentMeta': {'model': 'model:free', 'provider': 'openrouter',
                                                    'usage': {'input': 12, 'output': 3}}},
    }}))
    out = p.finish()
    assert p.meta.timed_out and expected in p.meta.error
    assert out == [f'error: {p.meta.error}']
    assert (p.meta.input_tokens, p.meta.output_tokens) == (12, 3)
    assert 'Partial result' in p.meta.result_text


def test_redact_hides_prompt():
    argv = agents.build_hermes(CARD, "secret plan", None, 1.0, "hermes")
    assert "secret plan" not in agents.redact(argv, "secret plan")

def test_project_subscription_budget_is_not_an_api_equivalent_stop():
    subscription=SimpleNamespace(**vars(CARD),subscription_billing=True)
    argv=agents.build_claude(subscription,'Plan the approved project','claude-opus-5-5',1,'claude')
    assert '--max-budget-usd' not in argv and 'Bash(git push:*)' in argv
    assert argv[argv.index('--permission-mode')+1]=='plan'
    api=agents.build_claude(CARD,'Plan',None,1,'claude')
    assert '--max-budget-usd' in api


def test_output_continuation_resumes_with_only_read_tools_and_subscription():
    card = SimpleNamespace(mode='read',output_only=True,subscription_billing=True)
    argv = agents.build_claude(card,'Return Markdown JSON','claude-haiku-5-5',1,'claude',session_id='prior-session')
    assert argv[argv.index('--permission-mode')+1]=='plan'
    assert argv[argv.index('--tools')+1]=='Read,Glob,Grep'
    assert argv[argv.index('--resume')+1]=='prior-session'
    assert argv[argv.index('--mcp-config')+1]=='{"mcpServers":{}}'
    assert '--strict-mcp-config' in argv and '--disable-slash-commands' in argv
    assert '--max-budget-usd' not in argv
