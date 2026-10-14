from __future__ import annotations

import json

import subagents

HERMES_TABLE = """Title                        Workspace          Last Active   ID
──────────────────────────────────────────────────────────────────────────────
Remember secret word pelic   scratch            3m ago        20261009_140427_0df228
Confirm ok response          scratch            48m ago       20261009_132828_591885
  … more not shown (use --limit 12 to see more)
"""


def test_classify_agents_without_reading_prompts():
    assert subagents.classify(["/Users/x/Library/Application Support/Claude/claude-code/2.1.237/claude.app/Contents/MacOS/claude",
                               "--model", "claude-opus-5"]) == ("claude", "desktop session")
    assert subagents.classify(["/opt/homebrew/bin/claude", "-p", "secret prompt"]) == ("claude", "cli session")
    assert subagents.classify(["/Users/x/.local/bin/codex", "exec", "--json"]) == ("codex", "exec")
    assert subagents.classify(["/v/bin/python", "-m", "hermes_cli.main", "gateway", "run"]) == ("hermes", "gateway")
    assert subagents.classify(["/Users/x/.local/bin/hermes", "chat", "-q", "secret"]) == ("hermes", "chat turn")
    assert subagents.classify(['/v/bin/python','/repo/integrations/hermes/mcd-run.py','chat','-q','secret']) == ('hermes','chat turn')
    assert subagents.classify(["/opt/homebrew/opt/node@22/bin/node",
                               "/opt/homebrew/lib/node_modules/openclaw/dist/index.js", "gateway"]) == ("openclaw", "gateway")
    assert subagents.classify(["/usr/bin/python3", "server.py"]) is None


def test_flags_extract_model_and_session_only():
    argv = ["claude", "--model", "claude-opus-5", "--resume=abc-123", "-p", "do not leak"]
    assert subagents._flag(argv, "model") == "claude-opus-5"
    assert subagents._flag(argv, "session") == "abc-123"
    assert subagents._flag(["openclaw", "agent", "--session-id", "s9"], "session") == "s9"


def test_openclaw_agents_and_sessions():
    agents = subagents.parse_openclaw_agents(json.dumps([
        {"id": "mm-main", "name": "mm-main", "model": "openrouter/google/gemini-2.5-flash-lite",
         "isDefault": True, "bindings": 2, "workspace": "~/w"}]))
    assert agents == [{"id": "mm-main", "name": "mm-main", "model": "openrouter/google/gemini-2.5-flash-lite",
                       "default": True, "bindings": 2, "workspace": "~/w"}]
    s = subagents.summarize_openclaw_sessions(json.dumps([
        {"updatedAt": 1_000_000, "totalTokens": 100, "model": "a"},
        {"updatedAt": 2_000_000, "totalTokens": 50, "model": "b"}]), now_ms=2_060_000)
    assert s == {"sessions_24h": 2, "last_active_s": 60, "tokens_24h": 150, "models": ["a", "b"]}
    assert subagents.summarize_openclaw_sessions("[]", 0)["last_active_s"] is None


def test_hermes_table():
    rows = subagents.parse_hermes_sessions(HERMES_TABLE)
    assert rows[0] == {"title": "Remember secret word pelic", "workspace": "scratch",
                       "last_active": "3m ago", "id": "20261009_140427_0df228"}
    assert len(rows) == 2
    assert subagents.parse_hermes_sessions("No sessions") == []
