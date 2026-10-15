"""The standard job envelope: controlled fields on every planned story, derived tier and job, standard tags, and a plan refused without them."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

import job_envelope as je
from models import Card, ProjectTask
from project_schemas import Node
from tests.test_projects import active, app, new, node  # noqa: F401  (fixtures and helpers)
from tests.test_tasks_v2 import _human  # noqa: F401


def test_the_route_tier_comes_from_what_will_run_never_from_a_model():
    assert je.tier_for("human", None, None) == "human"
    assert je.tier_for("agent", "codex", "gpt-6.1-sol") == "subscription"
    assert je.tier_for("agent", "claude", None) == "subscription"
    assert je.tier_for("agent", "hermes", "openrouter/free") == "free"
    assert je.tier_for("agent", "openclaw", "google/gemma-4-31b-it:free") == "free"
    assert je.tier_for("agent", "hermes", "google/gemini-2.5-flash") == "api"           # a paid OpenRouter model is an API route


def test_values_outside_the_vocabulary_are_named_and_absent_values_are_fine():
    assert je.problems({}) == []
    assert je.problems({"kind": "implement", "size": "m", "risk": "low", "area": "web-ui", "route_reason": "fits"}) == []
    text = " ".join(je.problems({"kind": "bake", "size": "huge", "risk": "meh", "area": "Not Valid!", "route_reason": "x" * 301}))
    for expected in ("kind must be", "size must be", "risk must be", "area must be", "route_reason must be"):
        assert expected in text


def test_a_plan_story_is_missing_exactly_what_it_leaves_out():
    nodes = [{"key": "phase1", "kind": "phase"},
             {"key": "a", "kind": "story", "work_kind": "implement", "size": "s", "risk": "low", "estimate_minutes": 45, "route_reason": "ok"},
             {"key": "b", "kind": "story", "work_kind": "review"},
             {"key": "c", "kind": "story"}]
    assert je.story_problems(nodes) == ["b: size, risk, estimate_minutes, route_reason", "c: work_kind, size, risk, estimate_minutes, route_reason"]


def test_the_planner_is_shown_the_envelope_in_the_node_schema_and_in_its_instructions():
    props = Node.model_json_schema()["properties"]
    assert {"work_kind", "size", "risk", "area", "estimate_minutes", "route_reason"} <= set(props)
    from pathlib import Path
    plan = (Path(__file__).resolve().parents[3] / "packs" / "roles" / "delegator" / "plan.txt").read_text()
    for word in ("work_kind", "estimate_minutes", "route_reason", "free route", "never choose a paid API route"):
        assert word.lower() in plan.lower()


# --------------------------------------------------------------------------------- cards

def test_cards_carry_the_envelope_and_the_tier_is_derived(app):  # noqa: F811
    c = app[0]
    made = c.post("/api/cards", json={"title": "Check the release notes", "body": "read only", "assignee_type": "agent", "agent": "codex", "working_dir": str(app[2]),
                                      "kind": "review", "size": "s", "risk": "low", "area": "docs", "estimate_minutes": 30, "route_reason": "Read-only review fits."})
    assert made.status_code == 201, made.text
    card = made.json()
    assert (card["kind"], card["size"], card["risk"], card["area"], card["route_tier"]) == ("review", "s", "low", "docs", "subscription")
    assert c.post("/api/cards", json={"title": "bad", "assignee_type": "human", "kind": "bake"}).status_code == 422
    plain = c.post("/api/cards", json={"title": "Old style", "assignee_type": "human"}).json()
    assert plain["kind"] is None and plain["route_tier"] == "human"                        # no envelope needed for hand-made tasks
    patched = c.patch(f"/api/cards/{card['id']}", json={"risk": "high"})
    assert patched.status_code == 200 and patched.json()["risk"] == "high"


def test_namespaced_tags_are_allowed(app):  # noqa: F811
    r = app[0].post("/api/cards", json={"title": "t", "assignee_type": "human", "tags": ["kind:implement", "job:p1r1", "Tier:Free"]})
    assert r.status_code == 201 and r.json()["tags"] == ["kind:implement", "job:p1r1", "tier:free"]


# --------------------------------------------------------------------------------- plans

def test_a_plan_without_the_envelope_is_refused_at_approval_and_names_the_gaps(app):  # noqa: F811
    c = app[0]
    bare = dict(key="a", title="a", description="Implement a bounded local change.", scope="Only this file.", acceptance="Checks pass.", assignee="codex", model="gpt-6.1-sol")
    p = new(app, [bare])
    r = c.post(f"/api/projects/{p['id']}/submit", json={"revision": 1, "approve_coordination": True, "approve_api_work": True})
    assert r.status_code == 422 and "a: work_kind, size, risk, estimate_minutes, route_reason" in r.text


def test_approved_stories_become_cards_with_the_envelope_job_and_standard_tags(app):  # noqa: F811
    p = active(app, [node("a", work_kind="research", size="xs", risk="low", estimate_minutes=15, area="docs", route_reason="Read-only; a subscription model is fine."),
                     node("b", assignee="hermes", model="openrouter/free", work_kind="triage", size="s", risk="low", estimate_minutes=40, area="ops", route_reason="Reversible and low risk: free is enough.")])
    with app[1]() as s:
        rows = {t.node_key: s.get(Card, t.card_id) for t in s.scalars(select(ProjectTask).where(ProjectTask.project_id == p["id"], ProjectTask.role == "story"))}
    a, b = rows["a"], rows["b"]
    assert (a.kind, a.size, a.risk, a.area, a.estimate_minutes, a.route_tier) == ("research", "xs", "low", "docs", 15, "subscription")
    assert (b.kind, b.route_tier) == ("triage", "free") and "free is enough" in b.route_reason
    tags = json.loads(a.tags)
    assert f"job:p{p['id']}r1" in tags and "kind:research" in tags and "tier:subscription" in tags and "risk:low" in tags and f"project {p['id']}" in tags


# --------------------------------------------------------------------------------- who it is assigned to

def test_a_task_is_assigned_to_a_human_user_or_an_agent_never_both(app):  # noqa: F811
    c = app[0]
    person = c.post("/api/cards", json={"title": "Decide the rollout", "assignee_type": "human", "assignee_user": "jamie@example.com"})
    assert person.status_code == 201 and person.json()["assignee_user"] == "jamie@example.com" and person.json()["route_tier"] == "human"
    unassigned = c.post("/api/cards", json={"title": "Nobody yet", "assignee_type": "human"}).json()
    assert unassigned["assignee_user"] is None                                              # shows up as Unassigned in telemetry
    agent = c.post("/api/cards", json={"title": "Agent work", "assignee_type": "agent", "agent": "codex", "working_dir": str(app[2]), "assignee_user": "jamie@example.com"})
    assert agent.status_code == 422 and "Only a human task" in agent.text
    assert c.post("/api/cards", json={"title": "bad", "assignee_type": "human", "assignee_user": "not valid!"}).status_code == 422
    moved = c.patch(f"/api/cards/{unassigned['id']}", json={"assignee_user": "kevin"})
    assert moved.status_code == 200 and moved.json()["assignee_user"] == "kevin"
    cleared = c.patch(f"/api/cards/{unassigned['id']}", json={"assignee_user": ""})
    assert cleared.status_code == 200 and cleared.json()["assignee_user"] is None


def test_a_human_story_in_a_plan_carries_who_it_is_for(app):  # noqa: F811
    p = active(app, [node("a"), node("h", assignee="human", model="", work_kind="review", size="xs", risk="low", estimate_minutes=15,
                                      route_reason="A person must decide.", assignee_user="jamie@example.com", depends_on=["a"])])
    with app[1]() as s:
        rows = {t.node_key: s.get(Card, t.card_id) for t in s.scalars(select(ProjectTask).where(ProjectTask.project_id == p["id"], ProjectTask.role == "story"))}
    assert rows["h"].assignee_user == "jamie@example.com" and rows["h"].route_tier == "human" and rows["a"].assignee_user is None
