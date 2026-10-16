"""Closing a project without finishing it: honest state, reason kept, nothing more dispatched, failed cards removable."""
from sqlalchemy import select

from dispatcher import Dispatcher
from models import Card, Project, ProjectMemory, ProjectTask
from tests.test_projects import app, active, node          # noqa: F401  (fixtures and helpers)


def stories(p):
    return [t["card_id"] for t in p["tasks"] if t["role"] == "story"]


def state(app, pid):
    with app[1]() as d:
        return d.get(Project, pid).state


def set_column(app, cid, column):
    with app[1].begin() as d:
        d.get(Card, cid).column = column


def test_closing_records_the_reason_stops_dispatch_and_is_not_complete(app):
    c, s, wd, settings = app
    p = active(app, [node("a"), node("b", depends_on=["a"])])
    pid = p["id"]
    r = c.post(f"/api/projects/{pid}/close", json={"revision": 2 if p["revision"] == 2 else p["revision"], "reason": "Superseded by the RCD project"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "closed" and state(app, pid) == "closed" and state(app, pid) != "complete"
    with s() as d:
        note = d.scalar(select(ProjectMemory).where(ProjectMemory.kind == "decision", ProjectMemory.text.like("Project closed without finishing%")))
        assert note and "Superseded by the RCD project" in note.text
    assert Dispatcher(s, settings)._claim(2) == []                                         # nothing starts on a closed project
    again = c.post(f"/api/projects/{pid}/close", json={"revision": p["revision"], "reason": "again"})
    assert again.status_code == 200 and again.json()["state"] == "closed"                    # closing twice is harmless


def test_a_failed_story_of_a_closed_project_can_be_removed_but_other_cards_cannot(app):
    c, s, wd, settings = app
    p = active(app, [node("a"), node("b", depends_on=["a"])])
    a, b = stories(p)
    set_column(app, a, "failed")
    assert c.delete(f"/api/cards/{a}").status_code == 409                                    # open project: protected
    assert c.post(f"/api/projects/{p['id']}/close", json={"revision": p["revision"], "reason": "abandoned"}).status_code == 200
    assert c.get(f"/api/cards/{a}").json()["closed_project"] is True
    assert c.delete(f"/api/cards/{a}").status_code == 204 and c.get(f"/api/cards/{a}").status_code == 404
    assert c.get(f"/api/cards/{b}").json()["closed_project"] is True                        # queued behind it: nothing will ever start it, so it can go too
    assert c.delete(f"/api/cards/{b}").status_code == 204
    with s() as d:
        assert d.get(ProjectTask, a) is None and d.get(ProjectTask, b) is None
        assert d.scalar(select(ProjectMemory).where(ProjectMemory.text.like("Deleted failed card%")))


def test_refuses_while_a_story_is_running_a_short_reason_a_stale_revision_and_a_completed_project(app):
    c, s, wd, settings = app
    p = active(app, [node("a")])
    pid, a = p["id"], stories(p)[0]
    set_column(app, a, "running")
    r = c.post(f"/api/projects/{pid}/close", json={"revision": p["revision"], "reason": "stop"})
    assert r.status_code == 409 and "running" in r.json()["detail"] and state(app, pid) == "active"
    set_column(app, a, "failed")
    assert c.post(f"/api/projects/{pid}/close", json={"revision": p["revision"], "reason": "x"}).status_code == 422
    assert c.post(f"/api/projects/{pid}/close", json={"revision": p["revision"] + 5, "reason": "stale revision"}).status_code in (409, 422)
    assert c.post(f"/api/projects/{pid}/close", json={"revision": p["revision"], "reason": "ok", "extra": 1}).status_code == 422
    with s.begin() as d:
        d.get(Project, pid).state = "complete"
    done = c.post(f"/api/projects/{pid}/close", json={"revision": p["revision"], "reason": "already finished"})
    assert done.status_code == 409 and state(app, pid) == "complete"                         # a finished project is never relabelled


def test_closing_with_remove_tasks_takes_every_task_off_the_board_and_keeps_the_ledger(app):
    c, s, wd, settings = app
    p = active(app, [node("a"), node("b", depends_on=["a"]), node("c")])
    a, b, cc = stories(p)
    set_column(app, a, "done"); set_column(app, b, "failed")
    r = c.post(f"/api/projects/{p['id']}/close", json={"revision": p["revision"], "reason": "replanned as a new project", "remove_tasks": True})
    assert r.status_code == 200 and r.json()["state"] == "closed"
    for card_id in (a, b, cc):
        assert c.get(f"/api/cards/{card_id}").status_code == 404
    with s() as d:
        assert not d.scalars(select(ProjectTask).where(ProjectTask.project_id == p["id"])).all()
        assert d.scalar(select(ProjectMemory).where(ProjectMemory.text.like("Project closed without finishing%")))
        assert d.scalar(select(ProjectMemory).where(ProjectMemory.text.like("Removed % task(s) of this closed project%")))


def test_a_closed_projects_tasks_can_be_removed_later_but_not_while_a_story_runs_or_while_the_project_is_open(app):
    c, s, wd, settings = app
    p = active(app, [node("a"), node("b")])
    a, b = stories(p)
    assert c.post(f"/api/projects/{p['id']}/remove-tasks", json={"revision": p["revision"]}).status_code == 409      # still open
    set_column(app, a, "running")
    assert c.post(f"/api/projects/{p['id']}/close", json={"revision": p["revision"], "reason": "stop", "remove_tasks": True}).status_code == 409
    set_column(app, a, "queued")
    closed = c.post(f"/api/projects/{p['id']}/close", json={"revision": p["revision"], "reason": "abandoned"}).json()
    assert c.get(f"/api/cards/{b}").status_code == 200                                                                 # closing alone leaves them
    set_column(app, a, "running")
    assert c.post(f"/api/projects/{p['id']}/remove-tasks", json={"revision": closed["revision"]}).status_code == 409
    set_column(app, a, "queued")
    assert c.post(f"/api/projects/{p['id']}/remove-tasks", json={"revision": closed["revision"]}).status_code == 200
    assert c.get(f"/api/cards/{a}").status_code == 404 and c.get(f"/api/cards/{b}").status_code == 404
