"""Operator-only model profiles: facts, observed numbers and people's notes (see model_profiles). Agents are refused as for every operator route."""
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

import model_profiles as mp
import model_evidence
import model_watch
import projects
import telemetry
from deps import get_session
from routes.agent_tools import operator
from settings import get_settings

router = APIRouter(prefix="/api/models")


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(max_length=120)
    text: str = Field(max_length=mp.NOTE_TEXT_MAX)
    source: str = Field(max_length=200)
    date: str = Field(max_length=10)


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool


@router.get("/profiles")
def profiles(request: Request, days: int = Query(90, ge=1, le=telemetry.MAX_DAYS), s: Session = Depends(get_session)):
    operator(request)
    out = mp.profiles(s, get_settings().data_dir, int(time.time()), days)
    out["watch"] = model_watch.status(get_settings())
    return out


@router.get("/advice")
def advice(project_id: int, request: Request, s: Session = Depends(get_session)):
    """Non-blocking advice on the saved plan's routes. Refuses nothing: the dispatch gates, risk floors and approvals do that."""
    operator(request)
    nodes = projects.document(projects.get(s, project_id)).get("nodes", [])
    return {"advice": mp.route_advice(s, get_settings().data_dir, nodes, int(time.time()))}


@router.post("/refresh")
def refresh(request: Request, body: RefreshIn):
    operator(request)
    if not body.confirm:
        raise HTTPException(422, "Explicit confirmation is required.")
    settings = get_settings()
    try:
        return mp.refresh(settings.data_dir, enabled=settings.model_refresh_enabled)
    except mp.ModelError as error:
        raise HTTPException(409, str(error)) from None


@router.post("/watch/run")
def watch_run(request: Request, body: RefreshIn, s: Session = Depends(get_session)):
    """Run the model watch now (the same job the schedule runs); it leaves at most one Backlog card and changes nothing else."""
    operator(request)
    if not body.confirm:
        raise HTTPException(422, "Explicit confirmation is required.")
    settings = get_settings()
    if not settings.model_refresh_enabled:
        raise HTTPException(409, "Refreshing the model list is switched off in this installation.")
    return model_watch.run(s, settings, int(time.time()))


@router.post("/notes")
def add_note(request: Request, body: NoteIn):
    operator(request)
    try:
        return mp.add_note(get_settings().data_dir, body.model, body.text, body.source, body.date)
    except mp.ModelError as error:
        raise HTTPException(422, str(error)) from None


@router.delete("/notes/{note_id}")
def delete_note(note_id: str, request: Request):
    operator(request)
    if not mp.delete_note(get_settings().data_dir, note_id):
        raise HTTPException(404, "No such note.")
    return {"deleted": note_id}


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    observations: list[model_evidence.Observation] = Field(min_length=1,max_length=300)
    confirm: bool = False


@router.get('/evidence')
def evidence(request: Request):
    operator(request)
    return {'schema':1,'units':model_evidence.UNITS,'observations':model_evidence.records(get_settings().data_dir)}


@router.post('/evidence')
def import_evidence(request: Request, body: EvidenceIn):
    operator(request)
    if not body.confirm:raise HTTPException(422,'Confirm the sourced model-data import. It cannot change billing or routes.')
    try:return model_evidence.ingest(get_settings().data_dir,body.observations)
    except (ValueError,OSError):raise HTTPException(409,'Model data could not be stored. Check the private data directory and record limit.') from None


@router.post('/evidence/refresh')
def refresh_evidence(request: Request, body: RefreshIn):
    operator(request)
    if not body.confirm:raise HTTPException(422,'Confirm the public reference-data refresh.')
    if not get_settings().model_refresh_enabled:raise HTTPException(409,'Model refresh is switched off.')
    try:return model_evidence.refresh_litellm(get_settings().data_dir)
    except (ValueError,OSError):raise HTTPException(409,'The public LiteLLM reference map could not be read or stored; no routes or billing were changed.') from None
