"""Template rehearsal: plan a template's example the way the dashboard does, and judge the plan with the dashboard's own checks.

The template store runs this from a dashboard checkout when a maintainer asks for a rehearsal. `prompt` prints the planner prompt
for one example (the same role prompt, brief payload, methods, saved-intent contract and type section a real plan gets, with a
fixed route catalog instead of this host's agents and no project database). A model answers it outside the dashboard; `judge`
then reads that answer with the dashboard's parser and plan validation, runs the template's plan checks and the example's own
expectations, and prints the verdict as JSON. Nothing here runs a model, reads credentials or writes outside a temporary folder.

Run it with MAC_CONTROL_DATA_DIR set to an empty temporary folder; --pack installs the pack under rehearsal there first.

Example file: {"type": "<template id>", "title": "...", "brief": "...", "answers": {setting id: value},
               "expect": {"stories_min": n, "stories_max": n, "titles": [regex, ...]}}
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

REHEARSAL_AGENTS = ("claude", "codex")


def _settings():
    from settings import get_settings
    return get_settings()


def document(example, settings):
    """The draft project an example describes, with its answers checked against the template's settings."""
    import project_intake
    if not isinstance(example, dict) or not isinstance(example.get("type"), str):
        raise ValueError("An example needs a template id in `type`.")
    answers = project_intake.validate(example.get("answers") or {}, example["type"], settings)
    missing = project_intake.assessment(example["type"], answers, settings)["missing"]
    if missing:
        raise ValueError("The example leaves required settings unanswered: " + ", ".join(missing))
    return {"title": str(example.get("title") or "Rehearsal")[:200], "brief": str(example.get("brief") or ""), "constraints": "",
            "working_dir": "/rehearsal", "project_type": example["type"], "intake_answers": answers,
            "planning_bias": 50, "dispatch_mode": "sequential", "nodes": []}


def catalog(type_id, settings):
    """A fixed route catalog: the template's own agents where the planner may route stories, never this host's install state."""
    import project_types
    from agents import REGISTRY
    wanted = (project_types.load(settings).get(type_id) or {}).get("requires", {}).get("agents") or list(REHEARSAL_AGENTS)
    return [{"agent": a, "models": list(REGISTRY[a].suggested_models), "targets": []} for a in wanted if a in REHEARSAL_AGENTS and a in REGISTRY] or \
           [{"agent": a, "models": list(REGISTRY[a].suggested_models), "targets": []} for a in REHEARSAL_AGENTS]


def prompt(example, settings=None) -> str:
    import project_contract
    import project_intake
    import project_types
    import projects
    import standards
    from project_schemas import Node
    settings = settings or _settings()
    doc = document(example, settings)
    with tempfile.TemporaryDirectory() as empty:
        found = standards.resolve(empty, settings.data_dir)
    text = projects.role_prompt("plan", schema=json.dumps(Node.model_json_schema()), catalog=json.dumps(catalog(doc["project_type"], settings)),
                                project=projects.brief_payload(doc), standards=standards.prompt_section(found))
    text += "\n\nGeneral and selected-type methods:\n" + project_types.guidance_packet(doc["project_type"], settings)["text"]
    text += "\n\nSaved-intent contract:\n" + project_contract.prompt(doc)
    typed = project_types.planner_section(doc["project_type"], settings, project_intake.values(doc, settings))
    return text + ("\n\n" + typed if typed else "") + "\n\nThis installation:\nTemplate rehearsal. Route stories only to the catalog above; no host tools are checked."


def judge(example, answer: str, settings=None) -> dict:
    """{'ok', 'problems', 'stories', 'findings'} for one planner answer to an example."""
    import project_types
    import projects
    from fastapi import HTTPException
    from pydantic import ValidationError
    settings = settings or _settings()
    doc = document(example, settings)
    try:
        data = projects._json_result(answer)
        if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
            raise ValueError("the answer is not a {\"nodes\": [...]} object")
        # Plan validation wants an allowlisted, existing workspace: an empty temporary folder only this check allows.
        with tempfile.TemporaryDirectory() as workspace:
            planned = projects.proposal({**doc, "working_dir": workspace}, data["nodes"],
                                        settings.model_copy(update={"workdir_roots": (Path(workspace),)}))
    except HTTPException as exc:
        return {"ok": False, "problems": [f"The dashboard would refuse this plan: {exc.detail}"], "stories": 0, "findings": []}
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        return {"ok": False, "problems": [f"The dashboard would refuse this plan: {str(exc)[:400]}"], "stories": 0, "findings": []}
    nodes = planned["nodes"] if isinstance(planned, dict) else data["nodes"]
    stories = [n for n in nodes if n.get("kind", "story") == "story"]
    findings = project_types.check(doc["project_type"], nodes, settings)
    problems = [f"plan check {f['id']}: {f['message']}" for f in findings if f.get("severity") == "block"]
    expect = example.get("expect") or {}
    if len(stories) < expect.get("stories_min", 1):
        problems.append(f"{len(stories)} stories, fewer than the expected {expect.get('stories_min', 1)}")
    if "stories_max" in expect and len(stories) > expect["stories_max"]:
        problems.append(f"{len(stories)} stories, more than the expected {expect['stories_max']}")
    titles = [n.get("title", "") for n in stories]
    for pattern in expect.get("titles", []):
        if not any(re.search(pattern, t, re.I) for t in titles):
            problems.append(f"no story title matches {pattern!r}")
    return {"ok": not problems, "problems": problems, "stories": len(stories),
            "findings": [{"id": f["id"], "severity": f.get("severity", "warn")} for f in findings]}


def install_pack(folder: Path, settings) -> None:
    """Install the pack under rehearsal into this run's data folder, through the same validation an install from the store gets."""
    import pipeline_packs
    from version import __version__
    files = {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file() and not p.is_symlink()}
    try:
        pipeline_packs.install(settings, files, __version__)
    except pipeline_packs.PackError as exc:
        raise ValueError(f"The pack does not install: {exc}") from None


USAGE = "usage: rehearsal.py [--pack <pack folder>] prompt <example.json> | judge <example.json> <answer.txt>"


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    pack = None
    if args[:1] == ["--pack"] and len(args) > 1:
        pack, args = Path(args[1]), args[2:]
    if len(args) < 2 or args[0] not in ("prompt", "judge") or (args[0] == "judge") != (len(args) == 3):
        print(USAGE, file=sys.stderr)
        return 2
    example = json.loads(Path(args[1]).read_text("utf-8"))
    try:
        if pack is not None:
            install_pack(pack, _settings())
        if args[0] == "prompt":
            print(prompt(example))
            return 0
        verdict = judge(example, Path(args[2]).read_text("utf-8"))
    except ValueError as exc:
        print(json.dumps({"ok": False, "problems": [str(exc)], "stories": 0, "findings": []}))
        return 1
    print(json.dumps(verdict))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
