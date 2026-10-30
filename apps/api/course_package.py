"""The `course-package` check: is a project's course/ folder a complete package upubhub will accept?

Deterministic and read-only; no model. A pipeline pack names it, and the dashboard runs it when the operator accepts the course's static
verification story, listing every problem at once. The limits mirror upubhub's own (chat-out fields and anchors as in
routes/textbook_imports.py, assessment settings as in routes/class_learning.py, 12 topics and 60,000 characters per assessed lesson).

Layout (relative to the project folder):
  course/course.json                 code?, title, audience, level, objectives, lessons[{id, title, objectives, sections}], credits, ai_provenance, tool
  course/textbook/<lesson>.md        one "## " heading per section, in course.json order
  course/topics.json                 {lesson: [{section, label, kind, prompt, objective, anchor, source_url?}]}
  course/lesson-plans/<lesson>.md
  course/assessments/<lesson>.json   upubhub class activity settings
  UPLOAD.md                          the upload and class-setup checklist
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LESSON_RE = re.compile(r"^\d{2}-[a-z0-9][a-z0-9-]{0,60}$")
LICENCES = {"CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "public-domain"}
PROVENANCE = {"ai_assisted", "ai_generated"}
KINDS = {"person", "historic_figure", "place", "subject"}
STRICTNESS = {"lenient", "balanced", "strict"}
MAX_LESSON_CHARS = 60_000
MAX_TOPICS = 12
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
TOP_FILES = {"course.json", "topics.json"}
FOLDERS = {"textbook": ".md", "lesson-plans": ".md", "assessments": ".json"}
# Class code SUBJ:LL-name: a 3 to 5 letter subject code, a two-digit level (00 kindergarten, 01 to 12 grades, 13 to 16 college years)
# and the teacher's class name. The colon form is for display; files and links use slug().
CODE_RE = re.compile(r"^([A-Z]{3,5}):(\d{2})-(\S(?:.{0,78}\S)?)$")


def class_code(subject: str, level, name: str) -> str:
    return f"{subject}:{int(level):02d}-{' '.join(str(name).split())}"


def slug(code: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-")[:100]


def expected_code(answers: dict) -> str | None:
    """The class code a project's template settings call for, when it has all three parts."""
    try:
        return class_code(answers["subject_code"], answers["level"], answers["class_name"]) if all(answers.get(k) for k in ("subject_code", "level", "class_name")) else None
    except (TypeError, ValueError):
        return None


def _text(value, low=1, high=10_000):
    return isinstance(value, str) and low <= len(value.strip()) <= high


def _int(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _read_json(path: Path, problems: list[str], rel: str):
    try:
        return json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        problems.append(f"{rel} is missing.")
    except (OSError, ValueError, UnicodeError):
        problems.append(f"{rel} is not valid JSON.")
    return None


def sections(markdown: str) -> list[tuple[str, str]]:
    """(heading, body) for each "## " section; text before the first one is the lesson's introduction and belongs to no section."""
    out, title, body, fence = [], None, [], False
    for line in markdown.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        if not fence and line.startswith("## "):
            if title is not None:
                out.append((title, "\n".join(body)))
            title, body = line[3:].strip(), []
        elif title is not None:
            body.append(line)
    if title is not None:
        out.append((title, "\n".join(body)))
    return out


def _published_images(root: Path) -> set[str]:
    try:
        provenance = json.loads((root / "media" / "provenance.json").read_text("utf-8"))
    except (OSError, ValueError, UnicodeError):
        return set()
    names = provenance.keys() if isinstance(provenance, dict) else ()
    return {f"assets/img/{n}.jpg" for n in names if (root / "assets" / "img" / f"{n}.jpg").is_file()}


def _topic(t, lesson: str, titles: dict[str, str], used: set, problems: list[str]) -> None:
    where = f"topics.json {lesson}: {t.get('label', '?') if isinstance(t, dict) else '?'!s}"
    if not isinstance(t, dict):
        problems.append(f"topics.json {lesson}: every topic must be an object.")
        return
    if not _text(t.get("label"), 1, 200):
        problems.append(f"{where}: label must be 1 to 200 characters.")
    if t.get("kind", "subject") not in KINDS:
        problems.append(f"{where}: kind must be one of {', '.join(sorted(KINDS))}.")
    if not _text(t.get("prompt"), 10, 2000):
        problems.append(f"{where}: prompt must be 10 to 2,000 characters.")
    if not _text(t.get("objective"), 10, 1000):
        problems.append(f"{where}: objective must be 10 to 1,000 characters.")
    if t.get("source_url") and not str(t["source_url"]).startswith("https://"):
        problems.append(f"{where}: source_url must be an https link.")
    section = t.get("section")
    if section not in titles:
        problems.append(f"{where}: section {section!r} is not a \"## \" heading in textbook/{lesson}.md.")
        return
    anchor = t.get("anchor", "")
    if not isinstance(anchor, str) or len(anchor) > 200:
        problems.append(f"{where}: anchor must be text of at most 200 characters (empty for an end-of-section callout).")
    elif anchor:
        body = titles[section]
        line = next((l for l in body.splitlines() if anchor in l), "")
        if "\n" in anchor or "\r" in anchor:
            problems.append(f"{where}: the anchor must be plain text on one line.")
        elif (section, anchor) in used or body.count(anchor) != 1:
            problems.append(f"{where}: the anchor {anchor!r} must occur exactly once in its section and not be used twice.")
        elif any(c in line for c in "[]<>`!$") or any(c in anchor for c in "*_{}\\#|"):
            problems.append(f"{where}: the anchor must sit in plain prose (no links, images, code or markup on its line); or leave it empty.")
        used.add((section, anchor))


def _assessment(a, lesson: str, labels: set[str], problems: list[str]) -> None:
    where = f"assessments/{lesson}.json"
    if not isinstance(a, dict):
        problems.append(f"{where} must be an object.")
        return
    if not _text(a.get("objectives"), 10, 3000):
        problems.append(f"{where}: objectives must say what students should learn (10 to 3,000 characters).")
    topics = a.get("topics", [])
    if not isinstance(topics, list) or len(topics) > MAX_TOPICS or any(x not in labels for x in topics):
        problems.append(f"{where}: topics must list at most {MAX_TOPICS} of this lesson's topic labels from topics.json.")
    for key, low, high in (("question_target", 1, 10), ("assessment_length", 1, 10), ("max_attempts", 1, 3),
                           ("accuracy_weight", 1, 5), ("reasoning_weight", 1, 5), ("application_weight", 1, 5)):
        if key in a and not _int(a[key], low, high):
            problems.append(f"{where}: {key} must be a whole number from {low} to {high}.")
    if a.get("grading_strictness", "balanced") not in STRICTNESS:
        problems.append(f"{where}: grading_strictness must be lenient, balanced or strict.")
    if not isinstance(a.get("rubric_notes", ""), str) or len(a.get("rubric_notes", "")) > 2000:
        problems.append(f"{where}: rubric_notes must be text of at most 2,000 characters.")


def check(root: Path, code: str | None = None) -> dict:
    """{'ok', 'problems', 'counts'} for the course package in a project folder. `code` is the class code the project's settings call for."""
    root = Path(root)
    course_dir = root / "course"
    problems: list[str] = []
    counts = {"lessons": 0, "sections": 0, "topics": 0, "images": 0}
    if not course_dir.is_dir():
        return {"ok": False, "problems": ["There is no course/ folder."], "counts": counts}
    course = _read_json(course_dir / "course.json", problems, "course/course.json")
    if not isinstance(course, dict):
        return {"ok": False, "problems": problems or ["course/course.json must be an object."], "counts": counts}

    for key in ("title", "audience", "level", "tool"):
        if not _text(course.get(key), 1, 300):
            problems.append(f"course.json: {key} is required.")
    if code and course.get("code") != code:
        problems.append(f"course.json: code must be {code!r}, from the project's settings.")
    elif "code" in course and not (isinstance(course["code"], str) and CODE_RE.match(course["code"]) and int(CODE_RE.match(course["code"]).group(2)) <= 16):
        problems.append("course.json: code must look like MATH:07-Forces and Motion (3 to 5 capital letters, a colon, a level from 00 to 16, a dash, the class name).")
    if not isinstance(course.get("objectives"), list) or not course["objectives"] or not all(_text(o, 10, 1000) for o in course["objectives"]):
        problems.append("course.json: objectives must be a non-empty list of measurable objectives (10 to 1,000 characters each).")
    if course.get("ai_provenance") not in PROVENANCE:
        problems.append("course.json: ai_provenance must be ai_assisted or ai_generated; pipeline-written text is never declared human-written.")
    credits = course.get("credits", [])
    credited: set[str] = set()
    if not isinstance(credits, list):
        problems.append("course.json: credits must be a list.")
        credits = []
    for i, c in enumerate(credits, 1):
        if not isinstance(c, dict) or not _text(c.get("what"), 1, 500) or not _text(c.get("author"), 1, 300):
            problems.append(f"course.json credit {i}: say what was borrowed and credit its author.")
            continue
        if c.get("licence") not in LICENCES:
            problems.append(f"course.json credit {i}: licence must be one of {', '.join(sorted(LICENCES))}.")
        if not str(c.get("source_url", "")).startswith("https://"):
            problems.append(f"course.json credit {i}: source_url must be an https link to the source.")
        if isinstance(c.get("file"), str):
            credited.add(c["file"].lstrip("./"))

    lessons = course.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        problems.append("course.json: lessons must list at least one lesson.")
        lessons = []
    topics_all = _read_json(course_dir / "topics.json", problems, "course/topics.json") if lessons else {}
    if topics_all is not None and not isinstance(topics_all, dict):
        problems.append("course/topics.json must be an object keyed by lesson id.")
        topics_all = {}
    topics_all = topics_all or {}
    published = _published_images(root)
    ids: list[str] = []
    for lesson in lessons:
        if not isinstance(lesson, dict) or not LESSON_RE.fullmatch(str(lesson.get("id", ""))):
            problems.append("course.json: every lesson needs an id like 01-forces (two digits, a dash, lowercase words).")
            continue
        lid = lesson["id"]
        if lid in ids:
            problems.append(f"course.json: lesson {lid} is listed twice.")
            continue
        ids.append(lid)
        counts["lessons"] += 1
        if not _text(lesson.get("title"), 1, 300):
            problems.append(f"course.json {lid}: title is required.")
        if not isinstance(lesson.get("objectives"), list) or not lesson["objectives"] or not all(_text(o, 10, 1000) for o in lesson["objectives"]):
            problems.append(f"course.json {lid}: objectives must be a non-empty list (10 to 1,000 characters each).")
        wanted = lesson.get("sections")
        if not isinstance(wanted, list) or not wanted or not all(_text(x, 1, 200) for x in wanted):
            problems.append(f"course.json {lid}: sections must list the lesson's \"## \" section headings.")
            wanted = []
        try:
            markdown = (course_dir / "textbook" / f"{lid}.md").read_text("utf-8")
        except (OSError, UnicodeError):
            problems.append(f"course/textbook/{lid}.md is missing.")
            markdown = None
        titles: dict[str, str] = {}
        if markdown is not None:
            found = sections(markdown)
            titles = dict(found)
            counts["sections"] += len(found)
            if len(markdown) > MAX_LESSON_CHARS:
                problems.append(f"textbook/{lid}.md is {len(markdown):,} characters; an assessed upubhub lesson holds at most {MAX_LESSON_CHARS:,}.")
            if [t for t, _ in found] != [w.strip() for w in wanted]:
                problems.append(f"textbook/{lid}.md: its \"## \" headings {[t for t, _ in found]} must match course.json sections {wanted} in order.")
            for title, body in found:
                if not body.strip():
                    problems.append(f"textbook/{lid}.md: section {title!r} is empty.")
            for alt, target in IMAGE_RE.findall(markdown):
                counts["images"] += 1
                rel = target.split("#")[0].split("?")[0]
                while rel.startswith("../"):
                    rel = rel[3:]
                rel = rel.lstrip("./")
                if re.match(r"^[a-z]+:", target):
                    problems.append(f"textbook/{lid}.md: image {target} is remote; images must be files in this project so they can be uploaded.")
                elif not (root / rel).is_file():
                    problems.append(f"textbook/{lid}.md: image {target} does not exist.")
                elif rel not in published and rel not in credited:
                    problems.append(f"textbook/{lid}.md: image {rel} is neither published in Media studio nor credited in course.json.")
                if not alt.strip():
                    problems.append(f"textbook/{lid}.md: image {target} needs alt text.")
        lesson_topics = topics_all.get(lid, [])
        if not isinstance(lesson_topics, list):
            problems.append(f"topics.json {lid}: must be a list of topics.")
            lesson_topics = []
        if len(lesson_topics) > MAX_TOPICS:
            problems.append(f"topics.json {lid}: {len(lesson_topics)} topics; an assessed upubhub activity takes at most {MAX_TOPICS}.")
        used: set = set()
        for t in lesson_topics:
            counts["topics"] += 1
            _topic(t, lid, titles, used, problems)
        try:
            if not (course_dir / "lesson-plans" / f"{lid}.md").read_text("utf-8").strip():
                problems.append(f"course/lesson-plans/{lid}.md is empty.")
        except (OSError, UnicodeError):
            problems.append(f"course/lesson-plans/{lid}.md is missing.")
        labels = {t.get("label") for t in lesson_topics if isinstance(t, dict)}
        assessment = _read_json(course_dir / "assessments" / f"{lid}.json", problems, f"course/assessments/{lid}.json")
        if assessment is not None:
            _assessment(assessment, lid, labels, problems)

    for stray in sorted(set(topics_all) - set(ids)):
        problems.append(f"topics.json has topics for {stray}, which is not a lesson in course.json.")
    for path in sorted(course_dir.iterdir()):
        if path.is_file() and path.name not in TOP_FILES:
            problems.append(f"course/{path.name} is not part of the package layout.")
        elif path.is_dir() and path.name not in FOLDERS:
            problems.append(f"course/{path.name}/ is not part of the package layout.")
    for folder, suffix in FOLDERS.items():
        if (course_dir / folder).is_dir():
            for path in sorted((course_dir / folder).iterdir()):
                if path.suffix != suffix or path.stem not in ids:
                    problems.append(f"course/{folder}/{path.name} does not belong to a lesson in course.json.")
    try:
        if not (root / "UPLOAD.md").read_text("utf-8").strip():
            problems.append("UPLOAD.md is empty.")
    except (OSError, UnicodeError):
        problems.append("UPLOAD.md (the upload and class-setup checklist) is missing.")
    return {"ok": not problems, "problems": problems, "counts": counts}


if __name__ == "__main__":
    result = check(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
    print("course-package: " + ("passed" if result["ok"] else f"{len(result['problems'])} problem(s)"), result["counts"])
    for problem in result["problems"]:
        print(" -", problem)
    sys.exit(0 if result["ok"] else 1)
