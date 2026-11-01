"""The `upubhub-push` connector: send a project's course package to upubhub.com through its publish API, as private drafts.

A pipeline pack names this connector (upubhub-class, upubhub-textbook, upubhub-lesson-plan). The operator presses Push to upubhub on the
project's push story once every earlier story, including the final human sign-off, is done. Nothing here runs from an agent, and the
upubhub token (Private credentials, provider `upubhub`) is read only at push time, sent only as a bearer header to the upubhub host,
and never logged, stored elsewhere or put in an error.

What goes up, in upubhub's order (docs/PUBLISH_API.md, upubhub 1.41):
  1. images the lessons use       POST /api/v1/publish/assets   (kind image; the Markdown is rewritten to the returned URLs)
  2. the textbook                 POST /api/v1/publish/works    (kind textbook, one chapter per lesson)
  3. each lesson plan             POST /api/v1/publish/works    (kind lesson_plan, one chapter)
  4. the textbook's chat-outs     PUT  /api/v1/publish/works/<id>/chat-topics   (topics.json)
  5. the class                    PUT  /api/v1/publish/classes/<external id>     (textbook shared, one assignment per lesson)
A textbook package stops after 4, a lesson-plan package after 3. Every call is idempotent on upubhub's side (external ids below), so
pushing again updates the same textbook, plans and class. New works are private and a new class is invite-only and free; a re-push
never changes visibility, entry or anything else set on upubhub.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

import course_package

CONNECTOR = "upubhub-push"
SOURCE = "dashboard-template"          # the same course pushed from the Mac or the Pi updates the same items
DEFAULT_BASE = "https://upubhub.com"
TIMEOUT = 60
MAX_IMAGE_BYTES = 8 * 1024 * 1024
KINDS = ("class", "textbook", "lesson_plan")
# upubhub's labels are hand_crafted, ai_assisted, mixed and undeclared; it has no "AI generated", so that maps to ai_assisted.
PROVENANCE = {"hand_crafted": "hand_crafted", "ai_assisted": "ai_assisted", "ai_generated": "ai_assisted", "mixed": "mixed"}


class PushError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "course"


def read_course(root: Path) -> dict:
    try:
        course = json.loads((Path(root) / "course" / "course.json").read_text("utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise PushError("course/course.json is missing or not valid JSON.", 422) from None
    if not isinstance(course, dict):
        raise PushError("course/course.json must be an object.", 422)
    return course


def kind_of(course: dict) -> str:
    kind = course.get("kind") or "class"
    if kind not in KINDS:
        raise PushError(f"course.json kind must be one of {', '.join(KINDS)}.", 422)
    return kind


def base_id(course: dict) -> str:
    """The stable name the course has on upubhub: from its class code when it has one, otherwise its title."""
    code = course.get("code")
    return course_package.slug(code) if isinstance(code, str) and code else _slug(str(course.get("title") or "course"))


def plan(root: Path, course: dict | None = None) -> dict:
    """What a push would send, without sending anything: kind, external ids, lesson and image counts."""
    root = Path(root)
    course = course or read_course(root)
    kind, base = kind_of(course), base_id(course)
    lessons = [l for l in course.get("lessons", []) if isinstance(l, dict) and isinstance(l.get("id"), str)]
    images = sorted({rel for l in lessons for rel in _images(root, l["id"])})
    return {"kind": kind, "external_source": SOURCE, "base": base, "title": course.get("title"),
            "textbook": f"{base}-textbook" if kind in ("class", "textbook") else None,
            "lesson_plans": [f"{base}-plan-{l['id']}" for l in lessons] if kind in ("class", "lesson_plan") else [],
            "class": base if kind == "class" else None, "lessons": len(lessons), "images": len(images)}


def _textbook(root: Path, lid: str) -> str:
    return (root / "course" / "textbook" / f"{lid}.md").read_text("utf-8")


def _lesson_plan(root: Path, lid: str) -> str:
    return (root / "course" / "lesson-plans" / f"{lid}.md").read_text("utf-8")


def _images(root: Path, lid: str) -> list[str]:
    try:
        markdown = _textbook(root, lid)
    except OSError:
        return []
    out = []
    for _alt, target in course_package.IMAGE_RE.findall(markdown):
        rel = target.split("#")[0].split("?")[0]
        while rel.startswith("../"):
            rel = rel[3:]
        out.append(rel.lstrip("./"))
    return out


class Client:
    """A minimal JSON client for the upubhub publish API. The token stays inside the request header."""

    def __init__(self, base: str, token: str, opener=None):
        self.base = base.rstrip("/")
        self._auth = {"Authorization": f"Bearer {token}"}
        self._open = opener or urllib.request.urlopen

    def send(self, method: str, path: str, body=None, raw: bytes | None = None, content_type: str = "application/json") -> dict:
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {**self._auth, "Accept": "application/json", "User-Agent": "dashboard-upubhub-push"}
        if data is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self._open(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise PushError(f"upubhub refused {method} {path.split('?')[0]} ({exc.code}): {_detail(exc)}", 502 if exc.code >= 500 else 409) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PushError(f"Could not reach upubhub: {getattr(exc, 'reason', exc)}", 502) from None
        except ValueError:
            raise PushError(f"upubhub answered {method} {path.split('?')[0]} with something that is not JSON.", 502) from None

    def upload_image(self, path: Path) -> str:
        data = path.read_bytes()
        if len(data) > MAX_IMAGE_BYTES:
            raise PushError(f"{path.name} is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.", 422)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        boundary = "----dashboard" + secrets.token_hex(12)
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\nimage\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n").encode() \
            + data + f"\r\n--{boundary}--\r\n".encode()
        return str(self.send("POST", "/api/v1/publish/assets", raw=body, content_type=f"multipart/form-data; boundary={boundary}")["url"])


def _detail(exc: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(exc.read().decode("utf-8")).get("detail")
    except (ValueError, UnicodeError, AttributeError, OSError):
        return exc.reason or "no detail"
    if isinstance(detail, list):                       # FastAPI validation errors
        return "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)[:600]
    return str(detail)[:600]


def push(root: Path, token: str, *, base: str = DEFAULT_BASE, expected_code: str | None = None, provided: bool = False,
         tool: str = "Mac Control Dashboard", previous: dict | None = None, opener=None, progress=None) -> dict:
    """Check the package, then push it. Returns the receipt (ids, URLs, what was created); raises PushError before sending anything
    when the package does not pass, so a broken package never reaches upubhub half-sent."""
    root = Path(root)
    course = read_course(root)
    kind = kind_of(course)
    result = course_package.check(root, expected_code, provided=provided)
    if not result["ok"]:
        shown = result["problems"][:15]
        raise PushError(f"The course package has {len(result['problems'])} problem(s); fix them first:\n- " + "\n- ".join(shown), 422)
    say = progress or (lambda _m: None)
    client = Client(base, token, opener)
    info = plan(root, course)
    provenance = PROVENANCE.get(str(course.get("ai_provenance")), "undeclared")
    lessons = [l for l in course["lessons"]]
    receipt = {"kind": kind, "external_source": SOURCE, "base": info["base"], "pushed_at": None, "upubhub": base,
               "images": dict((previous or {}).get("images") or {}), "textbook": None, "lesson_plans": [], "class": None}

    # 1. Images, uploaded once per file content and reused on later pushes.
    urls: dict[str, str] = {}
    for rel in sorted({r for l in lessons for r in _images(root, l["id"])}):
        path = root / rel
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        cached = receipt["images"].get(digest)
        if not cached:
            say(f"Uploading image {rel}")
            cached = client.upload_image(path)
            receipt["images"][digest] = cached
        urls[rel] = cached

    def rewrite(markdown: str) -> str:
        def swap(m):
            target = m.group(2).split("#")[0].split("?")[0]
            rel = target
            while rel.startswith("../"):
                rel = rel[3:]
            rel = rel.lstrip("./")
            return f"![{m.group(1)}]({urls[rel]})" if rel in urls else m.group(0)
        return course_package.IMAGE_RE.sub(swap, markdown)

    work_common = {"external_source": SOURCE, "ai_provenance": provenance, "ai_provenance_tool": tool, "language": "en"}
    summary = str(course.get("summary") or course.get("audience") or "")[:2000] or None

    # 2. The textbook: one chapter per lesson, ids "<textbook>:<lesson>" so the class routes find the lessons.
    chapters_by_lesson: dict[str, int] = {}
    textbook_id = None
    if kind in ("class", "textbook"):
        ext = info["textbook"]
        say("Sending the textbook")
        body = {**work_common, "external_id": ext, "kind": "textbook", "title": str(course["title"])[:255], "summary": summary,
                "chapters": [{"order_index": i, "external_id": f"{ext}:{l['id']}", "title": str(l["title"])[:255],
                              "body_markdown": rewrite(_textbook(root, l["id"]))} for i, l in enumerate(lessons, 1)]}
        work = client.send("POST", "/api/v1/publish/works", body)
        textbook_id = work["work_id"]
        for ch in work.get("chapters", []):
            if isinstance(ch.get("external_id"), str) and ":" in ch["external_id"]:
                chapters_by_lesson[ch["external_id"].split(":", 1)[1]] = ch["id"]
        receipt["textbook"] = {"external_id": ext, "work_id": textbook_id, "created": work.get("created"), "visibility": work.get("visibility"),
                               "url_path": f"/dashboard/works/{textbook_id}",
                               "chapters": [{"lesson": k, "chapter_id": v} for k, v in chapters_by_lesson.items()],
                               "moderation": sorted({str(ch.get("moderation_status")) for ch in work.get("chapters", [])})}

    # 3. Lesson plans, one private work each.
    if kind in ("class", "lesson_plan"):
        for l in lessons:
            ext = f"{info['base']}-plan-{l['id']}"
            say(f"Sending lesson plan {l['id']}")
            markdown = _lesson_plan(root, l["id"])
            heading = next((line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")), "")
            work = client.send("POST", "/api/v1/publish/works", {
                **work_common, "external_id": ext, "kind": "lesson_plan", "title": (heading or f"Lesson plan: {l['title']}")[:255],
                "summary": summary, "chapters": [{"order_index": 1, "external_id": f"{ext}:{l['id']}", "title": str(l["title"])[:255],
                                                   "body_markdown": markdown}]})
            receipt["lesson_plans"].append({"lesson": l["id"], "external_id": ext, "work_id": work["work_id"], "created": work.get("created"),
                                            "visibility": work.get("visibility"), "url_path": f"/dashboard/works/{work['work_id']}"})

    # 4. The textbook's chat-outs.
    topics_path = root / "course" / "topics.json"
    if textbook_id is not None and topics_path.is_file():
        topics = json.loads(topics_path.read_text("utf-8"))
        if topics:
            say("Sending discussion topics")
            client.send("PUT", f"/api/v1/publish/works/{textbook_id}/chat-topics", topics)
            receipt["textbook"]["topics"] = sum(len(v) for v in topics.values() if isinstance(v, list))

    # 5. The class: invite-only and free when new; one assignment per lesson, assessed when the package has its settings.
    if kind == "class":
        say("Sending the class")
        assignments = []
        for i, l in enumerate(lessons, 1):
            item = {"external_id": l["id"], "title": f"Lesson {i}: {l['title']}"[:200],
                    "instructions": _instructions(l), "chapter_ids": [chapters_by_lesson[l["id"]]] if l["id"] in chapters_by_lesson else []}
            if isinstance(l.get("learning_method"), str):
                item["learning_method"] = l["learning_method"]
            assessment = root / "course" / "assessments" / f"{l['id']}.json"
            if assessment.is_file():
                item["assessment"] = json.loads(assessment.read_text("utf-8"))
            assignments.append(item)
        body = {"external_source": SOURCE, "name": str(course.get("code") or course["title"])[:120],
                "description": _description(course), "textbook_work_ids": [textbook_id], "assignments": assignments}
        if isinstance(course.get("rules_markdown"), str) and course["rules_markdown"].strip():
            body["rules_markdown"] = course["rules_markdown"]
        klass = client.send("PUT", f"/api/v1/publish/classes/{info['base']}", body)
        receipt["class"] = {k: klass.get(k) for k in ("class_id", "external_id", "created", "name", "visibility", "access_type", "url_path")}
        receipt["class"]["assignments"] = [{k: a.get(k) for k in ("external_id", "assignment_id", "created", "assessment", "assessment_detail")}
                                           for a in klass.get("assignments", [])]
    receipt["pushed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return receipt


def _instructions(lesson: dict) -> str:
    objectives = [o for o in lesson.get("objectives", []) if isinstance(o, str)]
    text = f"Read {lesson['title']}, then talk it through with the tutor."
    if objectives:
        text += " By the end you should be able to:\n" + "\n".join(f"- {o}" for o in objectives)
    return text[:5000]


def _description(course: dict) -> str:
    parts = [str(course.get("title") or "")]
    if course.get("audience"):
        parts.append(f"For {course['audience']}.")
    objectives = [o for o in course.get("objectives", []) if isinstance(o, str)]
    if objectives:
        parts.append("You will: " + "; ".join(objectives[:6]) + ".")
    return " ".join(p for p in parts if p)[:2000]


# ------------------------------------------------------------------------------------------------ receipts (dashboard data, not the workspace)


def receipt_path(settings, project_id: int) -> Path:
    return Path(settings.data_dir) / "upubhub-push" / f"project-{int(project_id)}.json"


def last_receipt(settings, project_id: int) -> dict | None:
    try:
        value = json.loads(receipt_path(settings, project_id).read_text("utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def save_receipt(settings, project_id: int, receipt: dict) -> None:
    path = receipt_path(settings, project_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(receipt, indent=1) + "\n", "utf-8")
    tmp.replace(path)
