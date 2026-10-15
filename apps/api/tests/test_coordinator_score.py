"""The coordinator scorecard: a deterministic plan scorer, fixed briefs, returned-versus-approved edits and the report. No model is called."""
from __future__ import annotations

import copy
import json

import pytest

import coordinator_score as cs
import scorecard
import standards
from models import Project
from tests.test_auth import secured  # noqa: F401
from tests.test_profiles import signed
from tests.test_projects import app, new, node  # noqa: F401 (the same envelope-complete node builder the project tests use)


def good(key="a", **kw):
    base = dict(kind="story", key=key, title=key, description="Implement a bounded change in one module.", scope="Only the files this story owns.",
                acceptance="The unit tests for this module pass and the page shows the new total.", assignee="codex", model="gpt-6.1-sol", work_kind="implement",
                size="s", risk="medium", estimate_minutes=45, route_reason="Bounded change; a subscription route fits.", area="business-logic")
    return {**base, **kw}


def plan(*extra):
    return [good("a"), good("b", depends_on=["a"], work_kind="test"), *extra]


FOUND = None


def tier(n):
    return scorecard._tier(n)


def starter():
    return standards.starter()


def by(result, cid):
    return next(c for c in result["checks"] if c["id"] == cid)


# ------------------------------------------------------------------------------------------------------ the scorer
def test_a_well_formed_plan_passes_every_applicable_check():
    r = cs.score_plan(plan(), found=starter(), tier_of=tier)
    assert r["score"] == 1.0 and r["failed"] == [] and r["passed"] == r["total"] >= 9


@pytest.mark.parametrize("mutate,cid", [
    (lambda ns: ns[0].update(work_kind=None), "envelope"),
    (lambda ns: ns[0].update(size="xs", estimate_minutes=240), "estimates"),
    (lambda ns: ns[0].update(acceptance="Looks good."), "acceptance"),
    (lambda ns: ns[0].update(scope=""), "scope"),
    (lambda ns: ns[0].update(depends_on=["nowhere"]), "dependencies"),
    (lambda ns: ns[0].update(route_reason=""), "envelope"),
    (lambda ns: ns[0].update(size="xl", estimate_minutes=600), "size"),
])
def test_each_check_fails_for_the_problem_it_names(mutate, cid):
    ns = copy.deepcopy(plan())
    mutate(ns)
    r = cs.score_plan(ns, found=starter(), tier_of=tier)
    assert cid in r["failed"] and by(r, cid)["detail"] != "" and r["score"] < 1.0


def test_a_dependency_loop_is_caught():
    ns = [good("a", depends_on=["b"]), good("b", depends_on=["a"])]
    r = cs.score_plan(ns, found=starter(), tier_of=tier)
    assert "dependencies" in r["failed"] and "loop" in by(r, "dependencies")["detail"]


def test_a_plan_that_does_not_parse_is_scored_on_that_alone():
    r = cs.score_plan([{"kind": "story", "key": "bad key!"}])
    assert r["failed"] == ["schema"] and r["total"] == 1 and r["score"] == 0.0


def test_high_risk_needs_a_human_or_review_story_and_never_a_free_only_route():
    risky = [good("a", risk="high", area="payments-and-billing")]
    r = cs.score_plan(risky, found=starter(), tier_of=tier)
    assert "review" in r["failed"]
    reviewed = risky + [good("c", assignee="human", model="", work_kind="review", risk="low", depends_on=["a"], area="documentation-and-copy")]
    assert "review" not in cs.score_plan(reviewed, found=starter(), tier_of=tier)["failed"]
    free = [good("a", risk="high", area="payments-and-billing", assignee="hermes", model="openrouter/free")] + reviewed[1:]
    assert "standards" in cs.score_plan(free, found=starter(), tier_of=tier)["failed"]


def test_a_brief_adds_its_own_expectations():
    brief = next(b for b in cs.briefs() if b["id"] == "checkout")["expect"]
    r = cs.score_plan(plan(), expect=brief, found=starter(), tier_of=tier)
    assert {"brief_size", "brief_review", "brief_areas"} <= set(r["failed"])           # two stories, no review, wrong area
    assert by(r, "brief_areas")["detail"] == "missing: payments-and-billing"


def test_the_shipped_briefs_are_general_and_complete():
    items = cs.briefs()
    assert len(items) == 8 and len({b["id"] for b in items}) == 8
    import re
    for b in items:
        assert b["brief"] and b["title"] and set(b["expect"]) >= {"min_stories", "needs_human_review", "areas", "kinds", "no_free_for_high"}
        assert not re.search(r"upubhub|wegamehub|bamcio|\bMCD\b|\bRCD\b|/Users/", json.dumps(b), re.I)
    starter_areas = {a["slug"] for a in starter()["areas"]}
    assert {a for b in items for a in b["expect"]["areas"]} <= starter_areas, "every expected area is one the starter standards define"


# -------------------------------------------------------------------------------------------------- comparing plans
def test_edits_count_added_removed_and_changed_nodes():
    returned = cs.signatures(plan())
    approved_nodes = plan(good("c"))
    approved_nodes[1]["acceptance"] = "The integration test passes and the report shows 12 rows."
    assert cs.edits(returned, cs.signatures(approved_nodes)) == {"added": 1, "removed": 0, "changed": 1, "total": 2, "nodes_returned": 2}
    assert cs.edits(returned, cs.signatures(plan()))["total"] == 0
    assert cs.edits(returned, cs.signatures([good("a")]))["removed"] == 1


def test_signatures_ignore_layout_fields_a_person_drags_on_the_map():
    a = good("a")
    moved = {**a, "x": 400, "y": 9}
    assert cs.signatures([a]) == cs.signatures([moved])


# --------------------------------------------------------------------------------- recorded at return and approval
def test_the_approved_plan_records_its_score_the_persons_edits_and_the_wording_in_effect(app):  # noqa: F811
    c, s, wd, settings = app
    p = new(app, [node("a"), node("b", depends_on=["a"])])
    with s.begin() as db:
        project = db.get(Project, p["id"])
        returned = [dict(n, kind="story") for n in json.loads(project.document)["nodes"]]
        scorecard.record_returned(db, project, returned, settings, {"agent": "claude", "model": "claude-opus-5-5"}, {"agent": "hermes", "model": "openrouter/free"})
    doc = c.get(f"/api/projects/{p['id']}").json()["document"]
    doc["nodes"][1]["acceptance"] = "A person tightened this: the checks pass and the reviewer verifies the artifact."
    assert c.patch(f"/api/projects/{p['id']}", json={"revision": 1, "document": doc}).status_code == 200
    r = c.post(f"/api/projects/{p['id']}/submit", json={"revision": 2, "approve_coordination": True, "approve_api_work": True})
    assert r.status_code == 200, r.text
    with s() as db:
        m = json.loads(db.get(Project, p["id"]).approved_manifest)["scorecard"]
    assert m["planner"] == "claude · claude-opus-5-5" and m["delegator"] == "hermes · openrouter/free"
    assert m["edits"]["changed"] == 1 and m["edits"]["added"] == 0 and m["edits"]["total"] == 1
    assert m["wording"]["label"] == "v2" and len(m["wording"]["sha"]) == 12
    assert 0 <= m["approved"]["score"] <= 1 and m["returned"]["total"] == m["approved"]["total"]


def test_a_scorecard_note_never_shows_in_the_projects_memory_list(app):  # noqa: F811
    c, s, wd, settings = app
    p = new(app, [node("a")])
    with s.begin() as db:
        project = db.get(Project, p["id"])
        scorecard.record_returned(db, project, [dict(n, kind="story") for n in json.loads(project.document)["nodes"]], settings, None, None)
    assert all(m["kind"] != "scorecard" for m in c.get(f"/api/projects/{p['id']}").json()["memory"])


def test_a_scorecard_failure_never_blocks_planning_or_approval(app, monkeypatch):  # noqa: F811
    c, s, wd, settings = app
    monkeypatch.setattr(scorecard, "at_approval", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    p = new(app, [node("a")])
    r = c.post(f"/api/projects/{p['id']}/submit", json={"revision": 1, "approve_coordination": True, "approve_api_work": True})
    assert r.status_code == 200
    with s() as db:
        assert json.loads(db.get(Project, p["id"]).approved_manifest)["scorecard"] is None


# ----------------------------------------------------------------------------------------------------- the report
def test_the_report_groups_by_planner_and_by_wording_with_outcomes(app):  # noqa: F811
    from tests.test_projects import active, finish
    c, s, wd, settings = app
    p = active(app, [node("a")])
    with s.begin() as db:
        project = db.get(Project, p["id"])
        m = json.loads(project.approved_manifest)
        m["scorecard"] = {"approved": {"score": 0.9, "passed": 9, "total": 10, "failed": ["acceptance"]}, "returned": {"score": 0.8, "passed": 8, "total": 10, "failed": []},
                          "edits": {"added": 1, "removed": 0, "changed": 2, "total": 3, "nodes_returned": 4}, "planner": "claude · claude-opus-5-5", "delegator": "hermes · free",
                          "wording": {"label": "v2", "sha": "abcdef123456"}}
        project.approved_manifest = json.dumps(m)
    with s() as db:
        out = scorecard.report(db, int(__import__("time").time()), 90)
    assert len(out["plans"]) == 1 and out["plans"][0]["edits"]["total"] == 3 and out["plans"][0]["score"] == 0.9
    assert out["by_planner"][0]["label"] == "claude · claude-opus-5-5" and out["by_planner"][0]["edits_per_plan"] == 3.0
    assert out["by_wording"][0]["label"] == "v2" and out["briefs"] == 8


# ------------------------------------------------------------------------------------------------------- routes
def test_the_routes_score_any_plan_against_a_brief_and_list_the_scorecard(secured):  # noqa: F811
    signed(secured)
    listing = secured.get("/api/coordinator/briefs").json()["briefs"]
    assert len(listing) == 8 and {"id", "title", "brief", "expect"} == set(listing[0])
    r = secured.post("/api/coordinator/score", json={"nodes": plan(), "brief_id": "docs"})
    assert r.status_code == 200 and "checks" in r.json() and r.json()["total"] >= 9
    assert secured.post("/api/coordinator/score", json={"nodes": plan(), "brief_id": "nope"}).status_code == 404
    assert secured.get("/api/coordinator/scorecard").json()["plans"] == []
