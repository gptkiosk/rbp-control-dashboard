"""The dashboard must work with any mix of agents installed, including none.

Five agents exist (Claude Code, Codex, Grok Build, Hermes, OpenClaw). Every one of the 32 combinations is
exercised: each read-only page answers, only installed agents are offered to run work, a task for an agent that
is not installed fails clearly, and nothing assumes a particular agent is present.
"""
import itertools
import json
import time

import pytest
from sqlalchemy import select

import projects
import provider_limits
from agents import REGISTRY, AgentSpec
from models import Card, Run

ALL = tuple(REGISTRY)
MIXES = [subset for n in range(len(ALL) + 1) for subset in itertools.combinations(ALL, n)]
PAGES = ["/api/agents", "/api/agents/usage?period=month", "/api/billing", "/api/limits", "/api/failures/summary",
         "/api/cards", "/api/projects", "/api/chat/threads", "/api/release", "/api/healthz"]


def mix_id(subset):
    return "+".join(subset) or "none"


@pytest.fixture
def installed(monkeypatch):
    def use(subset):
        monkeypatch.setattr(AgentSpec, "available", lambda self, settings: self.id in subset)
    return use


@pytest.mark.parametrize("mix", MIXES, ids=mix_id)
def test_every_page_answers_and_reports_exactly_the_installed_agents(make_client, installed, mix):
    installed(mix)
    with make_client() as client:
        for page in PAGES:
            if page == "/api/healthz":
                continue   # health lives outside /api
            assert client.get(page).status_code == 200, (mix_id(mix), page)
        agents = client.get("/api/agents").json()["agents"]
        assert [a["id"] for a in agents] == list(ALL)
        assert {a["id"] for a in agents if a["available"]} == set(mix), mix_id(mix)
        for agent in ALL:
            assert client.get(f"/api/agents/usage?agent={agent}").status_code == 200, (mix_id(mix), agent)


@pytest.mark.parametrize("mix", MIXES, ids=mix_id)
def test_only_installed_agents_are_offered_for_project_stories(make_client, installed, mix):
    installed(mix)
    with make_client():
        from settings import get_settings
        offered = {row["agent"] for row in projects.execution_catalog(get_settings())}
        assert offered == set(mix), mix_id(mix)


@pytest.mark.parametrize("mix", MIXES, ids=mix_id)
def test_a_task_for_an_agent_that_is_not_installed_fails_with_a_reason_instead_of_crashing(sessions, tmp_path, installed, mix):
    import asyncio
    from types import SimpleNamespace
    from dispatcher import Dispatcher
    from tests.test_dispatcher import _drain

    installed(mix)
    missing = [a for a in ALL if a not in mix]
    if not missing:
        pytest.skip("every agent is installed in this mix")
    now = int(time.time())
    with sessions.begin() as s:
        ids = []
        for agent in missing:
            card = Card(title=agent, body="x", agent=agent, model="m", mode="read", working_dir=str(tmp_path), column="queued",
                        position=1.0, timeout_s=30, needs_approval=False, created_by="operator", created_at=now, updated_at=now)
            s.add(card)
            s.flush()
            ids.append(card.id)
    settings = SimpleNamespace(runs_dir=tmp_path / "runs", max_concurrent_runs=8, default_budget_usd=0.0, run_retention_days=90,
                               dispatch_free_only=False, dispatch_max_budget_usd=1.0,
                               dispatch_route_classes={f"{a}||m": "subscription" for a in ALL},
                               **{spec.binary_setting: str(tmp_path / "not-installed") for spec in REGISTRY.values()})
    asyncio.run(_drain(Dispatcher(sessions, settings)))
    with sessions() as s:
        for cid in ids:
            card = s.get(Card, cid)
            run = s.scalar(select(Run).where(Run.card_id == cid))
            assert card.column == "failed" and run is not None and run.error, (mix_id(mix), card.agent)


@pytest.mark.parametrize("mix", MIXES, ids=mix_id)
def test_a_limit_reroute_only_ever_picks_an_installed_agent_or_none(mix):
    routes = [{"agent": a, "model": "m"} for a in ALL]
    usable = [r for r in routes if r["agent"] in mix]
    for limited in provider_limits.PROVIDERS:
        for agent in provider_limits.PROVIDERS:
            alt = provider_limits.alternate(usable, agent, "m", {limited})
            assert alt is None or (alt["agent"] in mix and alt["agent"] != agent and alt["agent"] != limited)
