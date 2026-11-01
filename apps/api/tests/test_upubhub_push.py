"""The upubhub-push connector: sends a checked course package to upubhub's publish API in order, as private drafts, and only from the push
story after the final sign-off. The token goes only to upubhub as a header, and never into a receipt, a note or an error."""
import io
import json
import urllib.error
from pathlib import Path

import pytest

import pipeline_packs as pp
import upubhub_push
from tests.test_course_package import write
from tests.test_projects import active, app, node  # noqa: F401  (app is a fixture)

TOKEN = "uph_" + "f" * 32


class FakeUpubhub:
    """Answers the publish API like upubhub 1.41 does, and records what it was sent."""

    def __init__(self, fail: dict | None = None):
        self.calls, self.fail, self.next_id = [], fail or {}, 40

    def __call__(self, request, timeout=None):
        path = request.full_url.split("upubhub.test", 1)[1]
        body = request.data
        self.calls.append({"method": request.get_method(), "path": path, "auth": request.get_header("Authorization"),
                           "json": json.loads(body) if body and request.get_header("Content-type") == "application/json" else None,
                           "bytes": body})
        if path in self.fail:
            raise urllib.error.HTTPError(request.full_url, self.fail[path], "Refused", {}, io.BytesIO(b'{"detail": "Not today."}'))
        if path == "/api/v1/publish/assets":
            answer = {"url": "https://cdn.upubhub.test/img/cart.jpg", "mime": "image/jpeg"}
        elif path == "/api/v1/publish/works":
            sent = self.calls[-1]["json"]
            self.next_id += 1
            answer = {"work_id": self.next_id, "visibility": "private", "kind": sent["kind"], "created": True,
                      "chapters": [{"id": 300 + i, "external_id": ch["external_id"], "moderation_status": "clean"} for i, ch in enumerate(sent["chapters"])]}
        elif path.endswith("/chat-topics"):
            answer = {"ok": True}
        else:
            sent = self.calls[-1]["json"]
            answer = {"class_id": 12, "external_id": path.rsplit("/", 1)[1], "created": True, "name": sent["name"], "visibility": "invite_only",
                      "access_type": "free", "url_path": "/classes/12",
                      "assignments": [{"external_id": a["external_id"], "assignment_id": 7, "created": True, "assessment": "set"} for a in sent["assignments"]]}
        return io.BytesIO(json.dumps(answer).encode())


def push(root, opener, **kw):
    return upubhub_push.push(root, TOKEN, base="https://upubhub.test", opener=opener, **kw)


def test_a_class_goes_up_in_upubhubs_order_as_private_drafts(tmp_path):
    write(tmp_path)
    up = FakeUpubhub()
    receipt = push(tmp_path, up)
    assert [(c["method"], c["path"]) for c in up.calls] == [
        ("POST", "/api/v1/publish/assets"), ("POST", "/api/v1/publish/works"), ("POST", "/api/v1/publish/works"),
        ("PUT", "/api/v1/publish/works/41/chat-topics"), ("PUT", "/api/v1/publish/classes/forces-for-beginners")]
    assert {c["auth"] for c in up.calls} == {f"Bearer {TOKEN}"}
    textbook, plan, _topics, klass = (c["json"] for c in up.calls[1:])
    assert textbook["kind"] == "textbook" and textbook["external_source"] == "dashboard-template" and "visibility" not in textbook
    assert textbook["ai_provenance"] == "ai_assisted"                       # upubhub has no "AI generated"; it is AI assisted there
    assert textbook["chapters"][0]["external_id"] == "forces-for-beginners-textbook:01-forces"
    assert "https://cdn.upubhub.test/img/cart.jpg" in textbook["chapters"][0]["body_markdown"]     # the image now points at upubhub
    assert plan["kind"] == "lesson_plan" and plan["title"] == "Lesson plan"
    assert klass["textbook_work_ids"] == [41] and klass["assignments"][0]["chapter_ids"] == [300]
    assert klass["assignments"][0]["assessment"]["topics"] == ["Pushes and pulls"]
    assert receipt["class"]["visibility"] == "invite_only" and receipt["textbook"]["visibility"] == "private"
    assert TOKEN not in json.dumps(receipt)
    again = FakeUpubhub()
    push(tmp_path, again, previous=receipt)
    assert "/api/v1/publish/assets" not in [c["path"] for c in again.calls]   # the same image is not uploaded twice


def test_nothing_is_sent_when_the_package_does_not_pass(tmp_path):
    write(tmp_path)
    (tmp_path / "course" / "lesson-plans" / "01-forces.md").unlink()
    up = FakeUpubhub()
    with pytest.raises(upubhub_push.PushError, match="lesson-plans/01-forces.md is missing") as exc:
        push(tmp_path, up)
    assert exc.value.status == 422 and up.calls == []


def test_the_teachers_own_text_is_labelled_hand_crafted_and_only_then(tmp_path):
    write(tmp_path, ai_provenance="hand_crafted")
    with pytest.raises(upubhub_push.PushError, match="pipeline-written text is never declared human-written"):
        push(tmp_path, FakeUpubhub())
    up = FakeUpubhub()
    push(tmp_path, up, provided=True)
    assert {c["json"]["ai_provenance"] for c in up.calls if c["path"] == "/api/v1/publish/works"} == {"hand_crafted"}


def test_a_textbook_package_sends_the_textbook_and_topics_only(tmp_path):
    c = write(tmp_path, kind="textbook")
    for folder in ("lesson-plans", "assessments"):
        for f in (c / folder).iterdir():
            f.unlink()
        (c / folder).rmdir()
    up = FakeUpubhub()
    receipt = push(tmp_path, up)
    assert [c["path"] for c in up.calls] == ["/api/v1/publish/assets", "/api/v1/publish/works", "/api/v1/publish/works/41/chat-topics"]
    assert receipt["class"] is None and receipt["lesson_plans"] == []


def test_a_lesson_plan_package_sends_one_lesson_plan(tmp_path):
    c = tmp_path / "course" / "lesson-plans"
    c.mkdir(parents=True)
    (c / "01-bridges.md").write_text("# Bridges in 40 minutes\n\n## Objectives\n\nName three kinds of bridge.\n")
    (tmp_path / "course" / "course.json").write_text(json.dumps({
        "kind": "lesson_plan", "title": "Bridges", "audience": "Grade 4", "level": "Grade 4", "tool": "RCD", "ai_provenance": "hand_crafted",
        "objectives": ["Name three kinds of bridge and say how each carries weight."], "credits": [],
        "lessons": [{"id": "01-bridges", "title": "Bridges", "objectives": ["Name three kinds of bridge."]}]}))
    (tmp_path / "UPLOAD.md").write_text("# Upload\n")
    up = FakeUpubhub()
    receipt = push(tmp_path, up, provided=True)
    assert [c["path"] for c in up.calls] == ["/api/v1/publish/works"]
    assert up.calls[0]["json"]["kind"] == "lesson_plan" and up.calls[0]["json"]["title"] == "Bridges in 40 minutes"
    assert receipt["lesson_plans"][0]["external_id"] == "bridges-plan-01-bridges"


def test_a_refusal_names_the_call_and_upubhubs_reason_but_never_the_token(tmp_path):
    write(tmp_path)
    with pytest.raises(upubhub_push.PushError) as exc:
        push(tmp_path, FakeUpubhub(fail={"/api/v1/publish/classes/forces-for-beginners": 403}))
    assert "PUT /api/v1/publish/classes/forces-for-beginners (403): Not today." in str(exc.value) and TOKEN not in str(exc.value)


def test_push_waits_for_the_sign_off_needs_a_token_and_records_ids_not_the_token(app, monkeypatch):  # noqa: F811
    from tests.test_pipeline_packs import pack_files
    c, s, wd, settings = app
    pp.install(settings, pack_files(connectors=["upubhub-push"]), "0.6.90")
    write(Path(wd))
    p = active(app, [dict(node("signoff", title="Approve the course for the upubhub push"), assignee="human", model="", mode="read"),
                     dict(node("push", title="Push the course to upubhub", depends_on=["signoff"]), assignee="human", model="", mode="read")],
               project_type="course-test")
    ids = {t["node_key"]: t["card_id"] for t in p["tasks"] if t["role"] == "story"}
    url = f"/api/projects/1/stories/{ids['push']}/upubhub-push"
    assert c.get(f"/api/projects/1/stories/{ids['signoff']}/upubhub-push").status_code == 404     # never on the sign-off story
    body = c.get(url).json()
    assert body["plan"]["kind"] == "class" and len(body["blocked_by"]) == 1 and body["token_saved"] is False and body["problems"] == []
    calls = []
    monkeypatch.setattr(upubhub_push, "push", lambda *a, **kw: calls.append(1) or {})
    r = c.post(url)
    assert r.status_code == 409 and "final sign-off" in r.json()["detail"] and calls == []         # the sign-off is not done
    assert c.post(f"/api/projects/1/stories/{ids['signoff']}/accept", json={"summary": "Read every lesson; approved."}).status_code == 200
    r = c.post(url)
    assert r.status_code == 409 and "Private credentials" in r.json()["detail"] and calls == []    # signed off, but no token saved
    assert c.put("/api/profile/credentials/upubhub", json={"value": TOKEN}).status_code == 200
    seen = {}

    def fake_push(root, token, **kw):
        seen.update(token=token, base=kw["base"], provided=kw["provided"])
        return {"kind": "class", "textbook": {"external_id": "forces-for-beginners-textbook", "url_path": "/dashboard/works/41"},
                "lesson_plans": [], "class": {"external_id": "forces-for-beginners", "url_path": "/classes/12"}}
    monkeypatch.setattr(upubhub_push, "push", fake_push)
    r = c.post(url)
    assert r.status_code == 200 and seen == {"token": TOKEN, "base": "https://upubhub.com", "provided": False}
    assert c.get(url).json()["last"]["class"]["url_path"] == "/classes/12"
    saved = upubhub_push.receipt_path(settings, 1).read_text()
    notes = json.dumps(c.get("/api/projects/1").json()["memory"])
    assert TOKEN not in saved and TOKEN not in notes and "/classes/12" in notes
