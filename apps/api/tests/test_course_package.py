"""The course-package check: a upubhub class package is complete and within upubhub's own limits before its verification story is accepted."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import course_package

LESSON = """# Forces

Forces push and pull.

## What a force is

A force is a push or a pull that can change how something moves.

![A cart being pushed](../../assets/img/cart.jpg)

## Balanced forces

When two equal forces act in opposite directions, nothing speeds up.
"""


def write(root: Path, **course_changes) -> Path:
    c = root / "course"
    for folder in ("textbook", "lesson-plans", "assessments"):
        (c / folder).mkdir(parents=True, exist_ok=True)
    course = {"title": "Forces for beginners", "audience": "Ages 11 to 13", "level": "Grade 6", "tool": "MCD upubhub-class pack",
              "objectives": ["Explain what a force is and give an example."], "ai_provenance": "ai_generated", "credits": [],
              "lessons": [{"id": "01-forces", "title": "Forces", "objectives": ["Describe balanced and unbalanced forces."],
                           "sections": ["What a force is", "Balanced forces"]}], **course_changes}
    (c / "course.json").write_text(json.dumps(course))
    (c / "textbook" / "01-forces.md").write_text(LESSON)
    (c / "topics.json").write_text(json.dumps({"01-forces": [
        {"section": "What a force is", "label": "Pushes and pulls", "kind": "subject", "prompt": "Ask the student for everyday pushes and pulls.",
         "objective": "Name three forces seen at home.", "anchor": "a push or a pull"}]}))
    (c / "lesson-plans" / "01-forces.md").write_text("# Lesson plan\n\nWarm up, read, discuss, test.\n")
    (c / "assessments" / "01-forces.json").write_text(json.dumps(
        {"objectives": "Students explain balanced forces in their own words.", "topics": ["Pushes and pulls"], "max_attempts": 2,
         "accuracy_weight": 3, "reasoning_weight": 2, "application_weight": 1, "grading_strictness": "balanced"}))
    (root / "assets" / "img").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "img" / "cart.jpg").write_bytes(b"\xff\xd8jpeg")
    (root / "media").mkdir(exist_ok=True)
    (root / "media" / "provenance.json").write_text(json.dumps({"cart": {"model": "test"}}))
    (root / "UPLOAD.md").write_text("# Upload\n\n1. Import the textbook.\n")
    return c


def problems(root):
    return "\n".join(course_package.check(root)["problems"])


def test_a_complete_package_passes(tmp_path):
    write(tmp_path)
    result = course_package.check(tmp_path)
    assert result["problems"] == []
    assert result["counts"] == {"lessons": 1, "sections": 2, "topics": 1, "images": 1}


def test_anchors_follow_upubhubs_rules(tmp_path):
    c = write(tmp_path)
    topics = json.loads((c / "topics.json").read_text())
    base = topics["01-forces"][0]
    topics["01-forces"] = [{**base, "anchor": "a p"}, {**base, "label": "Twice", "anchor": "a push or a pull"},
                           {**base, "label": "Again", "anchor": "a push or a pull"}, {**base, "label": "Bad", "kind": "planet", "prompt": "short"},
                           {**base, "label": "Elsewhere", "section": "Gravity"}]
    (c / "topics.json").write_text(json.dumps(topics))
    found = problems(tmp_path)
    assert "'a p' must occur exactly once" in found            # "a push", "a pull"
    assert "'a push or a pull' must occur exactly once in its section and not be used twice" in found
    assert "kind must be one of" in found and "prompt must be 10 to 2,000" in found
    assert "section 'Gravity' is not a \"## \" heading" in found


def test_headings_files_and_images_must_match_the_course(tmp_path):
    c = write(tmp_path, lessons=[{"id": "01-forces", "title": "Forces", "objectives": ["Describe balanced and unbalanced forces."],
                                  "sections": ["What a force is", "Unbalanced forces"]},
                                 {"id": "02-motion", "title": "Motion", "objectives": ["Describe speed."], "sections": ["Speed"]}])
    (tmp_path / "media" / "provenance.json").write_text("{}")
    (c / "textbook" / "99-extra.md").write_text("x")
    (c / "notes.txt").write_text("x")
    found = problems(tmp_path)
    assert "must match course.json sections" in found
    assert "course/textbook/02-motion.md is missing" in found and "course/lesson-plans/02-motion.md is missing" in found
    assert "image assets/img/cart.jpg is neither published in Media studio nor credited" in found
    assert "course/textbook/99-extra.md does not belong" in found and "course/notes.txt is not part" in found


def test_credits_licences_provenance_and_assessment_limits(tmp_path):
    c = write(tmp_path, ai_provenance="human", credits=[{"what": "Diagram", "author": "A. Author", "licence": "all-rights-reserved",
                                                          "source_url": "http://example.org"}])
    (c / "assessments" / "01-forces.json").write_text(json.dumps({"objectives": "short", "topics": ["Unknown"], "max_attempts": 4,
                                                                   "accuracy_weight": 0, "grading_strictness": "harsh"}))
    (tmp_path / "UPLOAD.md").unlink()
    found = problems(tmp_path)
    for expected in ("ai_provenance must be ai_assisted or ai_generated", "licence must be one of", "source_url must be an https link",
                     "objectives must say what students should learn", "topics must list at most 12 of this lesson's topic labels",
                     "max_attempts must be a whole number from 1 to 3", "accuracy_weight must be a whole number from 1 to 5",
                     "grading_strictness must be lenient", "UPLOAD.md (the upload and class-setup checklist) is missing"):
        assert expected in found


def test_a_long_lesson_and_too_many_topics_are_refused(tmp_path):
    c = write(tmp_path)
    (c / "textbook" / "01-forces.md").write_text(LESSON + "\nMore text. " * 6000)
    base = json.loads((c / "topics.json").read_text())["01-forces"][0]
    (c / "topics.json").write_text(json.dumps({"01-forces": [{**base, "label": f"T{i}", "anchor": ""} for i in range(13)]}))
    found = problems(tmp_path)
    assert "an assessed upubhub lesson holds at most 60,000" in found
    assert "13 topics; an assessed upubhub activity takes at most 12" in found


def test_no_course_folder_is_one_clear_problem(tmp_path):
    assert course_package.check(tmp_path) == {"ok": False, "problems": ["There is no course/ folder."],
                                              "counts": {"lessons": 0, "sections": 0, "topics": 0, "images": 0}}


def test_acceptance_runs_the_check_only_for_a_packs_verification_story(tmp_path, monkeypatch):
    import pipeline_packs
    import projects
    write(tmp_path)
    (tmp_path / "UPLOAD.md").unlink()
    nodes = [{"key": "verify", "kind": "story", "title": "Verify course files", "verification_stage": "static"},
             {"key": "write", "kind": "story", "title": "Write lesson 1"}]
    p = SimpleNamespace(approved_manifest=json.dumps({"document": {"nodes": nodes}}))
    c = SimpleNamespace(working_dir=str(tmp_path))
    monkeypatch.setattr(projects, "document", lambda p: {"project_type": "upubhub-class", "working_dir": str(tmp_path)})
    monkeypatch.setattr(projects, "get_settings", lambda: None)
    monkeypatch.setattr(pipeline_packs, "checks_for", lambda type_id, settings: ["course-package"] if type_id == "upubhub-class" else [])
    projects.course_package_gate(p, c, SimpleNamespace(node_key="write"))            # not the verification story
    with pytest.raises(Exception) as refused:
        projects.course_package_gate(p, c, SimpleNamespace(node_key="verify"))
    assert "course package check found 1 problem" in str(getattr(refused.value, "detail", refused.value))
    assert "UPLOAD.md" in str(getattr(refused.value, "detail", refused.value))
    monkeypatch.setattr(pipeline_packs, "checks_for", lambda type_id, settings: [])
    projects.course_package_gate(p, c, SimpleNamespace(node_key="verify"))           # no pack asks for it
