"""Operator-run media generation: MCD calls fal with the saved key; the project folder is only data."""
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import media_generate as mg
import media_state
import profiles
import projects
from deps import get_session
from settings import get_settings

router = APIRouter(prefix="/api/media")


def fail(exc):
    raise HTTPException(exc.status, str(exc)) from None


def project_note(s, root, text, identity):
    """Mirror a media decision into the ledger of the project whose working folder this is (the newest one), so the project remembers it."""
    from models import Project
    best = None
    for p in s.scalars(select(Project)):
        try:
            if Path(projects.document(p)["working_dir"]).expanduser().resolve() == root and (best is None or p.id > best.id):
                best = p
        except (OSError, RuntimeError, KeyError):
            continue
    if best is not None:
        projects.memory(s, best, "decision", text, identity)
        s.commit()


def operator(request):
    return profiles.owner(request)            # agents and project bridges get 403


@router.get("/folders")
def folders(request: Request):
    operator(request)
    settings = get_settings()
    found = []
    for root in settings.workdir_roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for path in [root, *sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))]:
            real = mg.approval.resolve_workdir(str(path), settings.workdir_roots)
            if real is not None and mg.inside(real, "media/slots.json") is not None:
                found.append({"path": str(real), "name": real.name})
    return {"folders": found}


class FolderQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    working_dir: str = Field(max_length=500)


@router.get("/slots")
def slots(working_dir: str, request: Request, s: Session = Depends(get_session)):
    operator(request)
    settings = get_settings()
    try:
        root = mg.project_root(settings, working_dir)
        items = mg.load_slots(root)
    except mg.MediaError as exc:
        fail(exc)
    out = []
    for slot in items.values():
        folder = "video" if slot["kind"] == "video" else "img"
        published = mg.is_published(root, slot)
        candidates = sorted(p.name for p in (root / "media" / "candidates").iterdir() if mg.candidate_of(slot["name"], p.name)) if (root / "media" / "candidates").is_dir() else []
        needs = [n for n in (slot.get("from_still"), slot.get("first_still"), slot.get("last_still")) if n]
        waiting = [n for n in needs if mg.inside(root, f"assets/img/{n}.jpg") is None]
        decision = media_state.entry(root, slot["name"])
        out.append({"name": slot["name"], "kind": slot["kind"], "skipped": decision["skipped"], "history": decision["history"], "world": slot.get("world"), "purpose": slot.get("purpose", ""), "prompt": slot["prompt"],
                    "published": published, "candidates": candidates, "inbox": (lambda f: f.name if f else None)(mg.inbox_file(root, slot)), "waiting_for_stills": waiting,
                    "plans": {tier: mg.quick_plan(s, slot, tier) for tier in mg.TIERS}})
    summary = media_state.summary(out, lambda x: x["published"])
    return {"working_dir": str(root), "slots": out, "summary": summary}


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    working_dir: str = Field(max_length=500)
    slot: str = Field(max_length=60)
    tier: str = Field(default="standard", pattern="^(draft|standard|premium)$")
    model: str | None = Field(default=None, max_length=160)
    count: int = Field(default=1, ge=1, le=4)
    aspect: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{1,2}$")      # None: use the slot's own shape
    confirm_spend: bool = False
    regenerate: bool = False      # a slot that is already published is only regenerated when this is said outright


@router.post("/generate", status_code=202)
def generate(body: GenerateIn, request: Request, s: Session = Depends(get_session)):
    identity = operator(request)
    settings = get_settings()
    if not body.confirm_spend:
        raise HTTPException(422, "Confirm that this spends from your fal account.")
    key = profiles.credential(s, identity, "fal", settings)
    if not key:
        raise HTTPException(422, "Save your fal key first (Profile, Private credentials).")
    try:
        root = mg.project_root(settings, body.working_dir)
        items = mg.load_slots(root)
        slot = items.get(body.slot)
        if slot is None:
            raise mg.MediaError("Unknown slot.")
        endpoint, payload = mg.build_request(root, slot, body.tier, body.model, body.aspect)
    except mg.MediaError as exc:
        fail(exc)
    jobs = mg.runtime(settings)
    if mg.is_published(root, slot) and not body.regenerate:
        raise HTTPException(409, f"{body.slot} is already published. Choose Regenerate if you really want a new one.")
    if jobs.active_for(root, body.slot):
        raise HTTPException(409, f"A generation for {body.slot} is already running. Wait for it to finish.")
    estimate = mg.estimate_for(s, endpoint, payload)
    ids = [jobs.submit(settings, key, root, slot, endpoint, payload, estimate, {"owner": identity, "tier": body.tier, "regenerate": body.regenerate}) for _ in range(body.count)]
    return {"jobs": ids, "endpoint": endpoint, "estimate_usd_each": estimate}


@router.get("/jobs/{job_id}")
def job(job_id: str, request: Request):
    operator(request)
    found = mg.runtime(get_settings()).get(job_id)
    if found is None:
        raise HTTPException(404, "Unknown job. MCD may have restarted; the ledger lists finished and failed runs.")
    return found


@router.get("/ledger")
def ledger(request: Request):
    operator(request)
    rows = mg.runtime(get_settings()).ledger.rows()
    done = [r for r in rows if r.get("status") == "done"]
    return {"rows": rows[-50:], "runs": len(rows), "done": len(done), "estimated_usd": round(sum(r.get("estimate_usd") or 0 for r in done), 4),
            "note": "Estimates come from listed or your own prices and are not invoices; fal's billing page is authoritative."}


@router.get("/candidate")
def candidate(working_dir: str, name: str, request: Request):
    """One candidate file, so the panel can show it for a visual decision. Operator-only; only `<slot>-<number>.<media>` files inside media/candidates."""
    operator(request)
    try:
        root = mg.project_root(get_settings(), working_dir)
    except mg.MediaError as exc:
        fail(exc)
    slot = re.sub(r"-\d+\.[a-z0-9]+$", "", name)
    if Path(name).name != name or not mg.SLOT_RE.fullmatch(slot) or not mg.candidate_of(slot, name):
        raise HTTPException(404, "No such candidate.")
    path = mg.candidate_file(root, name)
    if path is None:
        raise HTTPException(404, "No such candidate.")
    return FileResponse(path, media_type=mg.CANDIDATE_TYPES[path.suffix], headers={"Cache-Control": "private, max-age=300", "Content-Disposition": "inline"})


class PublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    working_dir: str = Field(max_length=500)
    slot: str = Field(max_length=60)


@router.post("/publish")
def publish(body: PublishIn, request: Request, s: Session = Depends(get_session)):
    """Publish the picked file for a slot: validate, convert, and record provenance, with MCD's own code (nothing from the folder is run)."""
    identity = operator(request)
    settings = get_settings()
    try:
        root = mg.project_root(settings, body.working_dir)
        slot = mg.load_slots(root).get(body.slot)
        if slot is None:
            raise mg.MediaError("Unknown slot.")
        files = mg.publish(root, slot)
    except mg.MediaError as exc:
        fail(exc)
    names = ", ".join(f["path"] for f in files)
    media_state.record(root, body.slot, "published", names, identity)
    project_note(s, root, f"Published media slot {body.slot}: {names}.", identity)
    return {"published": body.slot, "files": files}


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    working_dir: str = Field(max_length=500)
    slot: str = Field(max_length=60)
    event: str = Field(pattern="^(skip|unskip|reject)$")
    note: str = Field(default="", max_length=300)


@router.post("/decision")
def decision(body: DecisionIn, request: Request, s: Session = Depends(get_session)):
    """Record a decision about a slot that is not a generation: skip it (the site ships on its fallback), restore it, or reject the candidates it has."""
    identity = operator(request)
    try:
        root = mg.project_root(get_settings(), body.working_dir)
        slot = mg.load_slots(root).get(body.slot)
        if slot is None:
            raise mg.MediaError("Unknown slot.")
    except mg.MediaError as exc:
        fail(exc)
    event = {"skip": "skipped", "unskip": "restored", "reject": "rejected"}[body.event]
    if event == "skipped" and mg.is_published(root, slot):
        raise HTTPException(409, f"{body.slot} is already published; there is nothing to skip.")
    entry = media_state.record(root, body.slot, event, body.note, identity)
    words = {"skipped": "Skipped media slot", "restored": "Restored media slot", "rejected": "Rejected the candidates for media slot"}[event]
    project_note(s, root, f"{words} {body.slot}" + (f": {body.note}" if body.note else ".") + (" The site ships on its fallback." if event == "skipped" else ""), identity)
    return {"slot": body.slot, "skipped": entry["skipped"]}


@router.get("/project/{project_id}")
def project_media(project_id: int, request: Request, s: Session = Depends(get_session)):
    """Whether a project's working folder has media slots, and where its media decisions stand. Never fails for a project without media."""
    operator(request)
    from models import Project
    p = s.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "Unknown project.")
    try:
        root = mg.project_root(get_settings(), projects.document(p)["working_dir"])
        slots_ = mg.load_slots(root)
    except (mg.MediaError, KeyError):
        return {"available": False}
    rows = [{"name": n, "skipped": media_state.entry(root, n)["skipped"]} for n in slots_]
    summary = media_state.summary(rows, lambda x: mg.is_published(root, slots_[x["name"]]))
    return {"available": True, "working_dir": str(root), "summary": summary}


class PickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    working_dir: str = Field(max_length=500)
    slot: str = Field(max_length=60)
    candidate: str = Field(max_length=120)


@router.post("/pick")
def pick(body: PickIn, request: Request, s: Session = Depends(get_session)):
    """Copy a candidate into media/inbox so the project's own ingest step can publish it. Copies files only; no project code runs."""
    operator(request)
    settings = get_settings()
    try:
        root = mg.project_root(settings, body.working_dir)
        slot = mg.load_slots(root).get(body.slot)
    except mg.MediaError as exc:
        fail(exc)
    if slot is None or Path(body.candidate).name != body.candidate or not mg.candidate_of(body.slot, body.candidate):
        raise HTTPException(422, "Choose one of this slot's candidates.")
    source = mg.candidate_file(root, body.candidate)
    if source is None:
        raise HTTPException(404, "That candidate no longer exists.")
    inbox = root / "media" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for old in inbox.glob(body.slot + ".*"):
        old.unlink()
    shutil.copy(source, inbox / (body.slot + source.suffix))
    side = source.with_suffix(".json")
    if side.is_file():
        shutil.copy(side, inbox / (body.slot + ".json"))
    identity = profiles.owner(request)
    media_state.record(root, body.slot, "accepted", body.candidate, identity)
    project_note(s, root, f"Accepted candidate {body.candidate} for media slot {body.slot}.", identity)
    return {"copied": f"media/inbox/{body.slot}{source.suffix}", "next": f"python3 tools/media/media.py ingest {body.slot}"}
