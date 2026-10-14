"""Opt-in: Hermes and OpenClaw run with the operator's saved OpenRouter key. Off by default; never any other agent; never in output."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

import profiles
from agents import REGISTRY
from legacy_adapters import LegacyAgentAdapter, ProcessHandle, scrub
from models import Run, UserProfile
from settings import get_settings
from tests.test_auth import begin, complete, secured  # noqa: F401
from tests.test_durable_runs import _settings
from tests.test_profiles import pref, signed

KEY = "sk-or-test-" + "x" * 40   # clearly synthetic, and built so secret scanners do not mistake it for a real key


def save_key(client, key=KEY):
    assert client.put("/api/profile/credentials/openrouter", json={"value": key}).status_code == 200


def lookup(client):
    with client.app.state.sessions() as s:
        return profiles.saved_openrouter_key(s, get_settings())


def test_it_is_off_by_default_even_with_a_saved_key(secured):  # noqa: F811
    signed(secured); save_key(secured)
    assert lookup(secured) is None
    assert secured.get("/api/profile").json()["preferences"]["use_saved_openrouter_key"] is False


def test_enabling_needs_a_saved_key_then_supplies_it_and_the_api_never_returns_it(secured):  # noqa: F811
    signed(secured)
    data = secured.get("/api/profile").json()["preferences"]
    assert secured.put("/api/profile", json={**data, "use_saved_openrouter_key": True}).status_code == 422
    save_key(secured)
    response = secured.put("/api/profile", json={**data, "use_saved_openrouter_key": True})
    assert response.status_code == 200 and KEY not in response.text
    assert lookup(secured) == KEY
    assert KEY not in secured.get("/api/profile").text


def test_removing_the_key_or_switching_off_stops_it_at_once(secured):  # noqa: F811
    signed(secured); save_key(secured); pref(secured, use_saved_openrouter_key=True)
    assert lookup(secured) == KEY
    pref(secured, use_saved_openrouter_key=False)
    assert lookup(secured) is None
    pref(secured, use_saved_openrouter_key=True)
    assert secured.delete("/api/profile/credentials/openrouter").status_code == 200
    assert lookup(secured) is None
    assert secured.get("/api/profile").json()["preferences"]["use_saved_openrouter_key"] is False   # the switch went off with the key


def test_only_one_operator_can_share_a_key_and_two_owners_means_no_key(secured):  # noqa: F811
    signed(secured); save_key(secured); pref(secured, use_saved_openrouter_key=True)
    secured.post("/auth/logout")
    assert complete(secured, begin(secured), email="reviewer@example.com", sub="subject2").status_code == 303
    save_key(secured, KEY[:-4] + "ffff")
    data = secured.get("/api/profile").json()["preferences"]
    assert secured.put("/api/profile", json={**data, "use_saved_openrouter_key": True}).status_code == 409
    with secured.app.state.sessions() as s:                       # even if the database were edited by hand, ambiguity supplies nothing
        row = s.get(UserProfile, "reviewer@example.com")
        row.preferences = profiles.Preferences(**{**data, "use_saved_openrouter_key": True}).model_dump_json(); s.commit()
    assert lookup(secured) is None


def test_a_broken_vault_supplies_nothing_instead_of_failing_a_run(secured):  # noqa: F811
    signed(secured); save_key(secured); pref(secured, use_saved_openrouter_key=True)
    vault = get_settings().data_dir / "vault.key"
    vault.write_bytes(profiles.Fernet.generate_key()); vault.chmod(0o600)
    assert lookup(secured) is None


def test_scrub_removes_the_exact_key_and_anything_shaped_like_one():
    assert KEY not in scrub(f"token={KEY} done", KEY)
    assert "sk-or-" not in scrub("echo sk-or-v1-aaaaaaaaaaaaaaaaaaaa and more")
    assert scrub("nothing secret here") == "nothing secret here"
    assert "redacted" in scrub("x " + "sk-or-" + "b" * 20)


# ----------------------------------------------------------------------------- the process environment (real subprocess, real lookup)

SCRIPT = 'if [ -n "$OPENROUTER_API_KEY" ]; then echo "has-key"; echo "leak:$OPENROUTER_API_KEY"; else echo "no-key"; fi\n'


def seed(sessions, settings, *, share: bool):
    """An operator profile with a saved key, written the way the app writes it, in the database the adapter reads."""
    with sessions.begin() as db:
        profiles.get(db, "operator@example.com")
        profiles.put_credential(db, "operator@example.com", "openrouter", KEY, settings)
        if share:
            row = db.get(UserProfile, "operator@example.com")
            row.preferences = profiles.Preferences(use_saved_openrouter_key=True).model_dump_json()


def run_agent(sessions, tmp_path, agent, share):
    settings = _settings(tmp_path, data_dir=tmp_path / "data")
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    seed(sessions, settings, share=share)
    script = tmp_path / "agent.sh"
    script.write_text("#!/bin/sh\n" + SCRIPT)
    script.chmod(0o755)
    with sessions.begin() as db:
        row = Run(agent=agent, stage="running", started_at=1, working_dir=str(tmp_path), command="[]", log_path="", idempotency_key="k-" + agent)
        db.add(row); db.flush(); run_id = row.id
    adapter = LegacyAgentAdapter(REGISTRY[agent], sessions, settings, {run_id: ProcessHandle()})
    asyncio.run(adapter._run_process(run_id, agent, [str(script)], str(tmp_path), 30))
    return (settings.runs_dir / f"run-{run_id}.raw.log").read_text(), (settings.runs_dir / f"run-{run_id}.log").read_text()


def test_openclaw_gets_the_key_in_its_process_and_it_never_reaches_stored_output(sessions, tmp_path):
    raw, log = run_agent(sessions, tmp_path, "openclaw", share=True)
    assert "has-key" in raw                                       # the process really had OPENROUTER_API_KEY
    assert KEY not in raw and KEY not in log                      # and nothing stored contains it
    assert "redacted OpenRouter key" in raw
    assert "saved OpenRouter key was supplied" in log


def test_claude_never_gets_it_even_when_shared(sessions, tmp_path):
    raw, log = run_agent(sessions, tmp_path, "claude", share=True)
    assert "no-key" in raw and "has-key" not in raw and "supplied" not in log


def test_nothing_is_supplied_without_the_opt_in(sessions, tmp_path):
    raw, log = run_agent(sessions, tmp_path, "openclaw", share=False)
    assert "no-key" in raw and "supplied" not in log


def test_the_spending_check_uses_the_shared_key_for_both_agents_and_a_native_key_otherwise(tmp_path):
    from openrouter_costs import configured_keys
    native = "sk-or-v1-native" + "n" * 30
    (tmp_path / ".hermes").mkdir(); (tmp_path / ".hermes" / ".env").write_text(f"OPENROUTER_API_KEY={native}\n")
    assert configured_keys(tmp_path)["hermes"] == native
    shared = configured_keys(tmp_path, KEY)
    assert shared == {"hermes": KEY, "openclaw": KEY}              # the saved key wins, and fills OpenClaw too
