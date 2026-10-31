"""The template store in Installs & updates: list the signed packs release (templates and approved tools), install, update and remove.
Operator only; packs are data, never code."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import pipeline_packs as pp
import project_types
from deps import get_session
from models import UserCredential
from routes.agent_tools import operator
from settings import get_settings
from version import __version__

router = APIRouter(prefix="/api/pipeline-packs")
_CACHE: dict = {"at": 0.0, "listing": None, "error": None}
CACHE_SECONDS = 900   # GitHub allows 60 unauthenticated requests an hour; a listing is three


class InstallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=pp.ID_RE.pattern)


def _listing(refresh: bool):
    if refresh or _CACHE["listing"] is None and _CACHE["error"] is None or time.time() - _CACHE["at"] > CACHE_SECONDS:
        try:
            _CACHE.update(listing=pp.available(), error=None)
        except pp.PackError as exc:
            _CACHE.update(listing=None, error=str(exc))
        _CACHE["at"] = time.time()
    return _CACHE["listing"], _CACHE["error"]


def _saved(s: Session, identity: str) -> set[str]:
    return set(s.scalars(select(UserCredential.provider).where(UserCredential.owner == identity)))


def _service(manifest_or_entry: dict, saved: set[str]) -> dict | None:
    service = manifest_or_entry.get("service")
    if not isinstance(service, dict):
        return None
    credential = service.get("credential")
    return {"id": service.get("id"), "label": service.get("label"), "credential": credential, "ready": not credential or credential in saved}


@router.get("")
def packs(request: Request, refresh: bool = False, s: Session = Depends(get_session)):
    identity = operator(request)
    saved = _saved(s, identity)
    listing, error = _listing(refresh)
    installed = {p["manifest"]["id"]: p for p in pp.installed(get_settings())}
    offered = []
    settings = get_settings()
    for entry in (listing or {}).get("packs", []):
        current = installed.get(entry["id"])
        needs = [r for r in project_types.requirements({"requires": {**(entry.get("requires") or {}), "app_min": entry.get("app_min") or "0.0.0"}}, settings, saved)
                 if r["status"] in ("missing", "unknown")]
        offered.append({"id": entry["id"], "label": entry.get("label") or entry["id"], "summary": entry.get("summary") or "", "version": entry["pack_version"],
                        "service": _service(entry, saved), "installed": current["version"] if current else None,
                        "update": bool(current and pp._version_tuple(entry["pack_version"]) > pp._version_tuple(current["version"])),
                        "author": entry.get("author"), "trust": entry.get("trust"), "settings": entry.get("settings") or [], "needs": needs,
                        "too_new": any(r["kind"] == "app" for r in needs)})
    tools = {kind: [{**t, "status": status, "detail": detail, "link": project_types.LINKS[kind]}
                    for t in rows for status, detail in [project_types.tool_status(kind, t["id"], settings, saved)]]
             for kind, rows in ((listing or {}).get("tools") or {}).items()}
    return {"repository": pp.PACKS_REPOSITORY, "release": (listing or {}).get("release"), "error": error, "available": offered, "tools": tools,
            "installed": [{"id": m["id"], "label": m.get("label") or m["id"], "version": p["version"], "project_types": m.get("project_types", []),
                           "service": _service(m, saved)} for p in installed.values() for m in [p["manifest"]]]}


@router.post("/install")
def install(body: InstallIn, request: Request, s: Session = Depends(get_session)):
    identity = operator(request)
    listing, error = _listing(False)
    entry = next((p for p in (listing or {}).get("packs", []) if p["id"] == body.id), None)
    if entry is None:
        raise HTTPException(409 if error else 404, error or "That pack is not in the latest packs release.")
    service = _service(entry, _saved(s, identity))
    if service and not service["ready"]:
        raise HTTPException(409, f"Save your {service['label']} credential in General → Private credentials first; this pack works with that service.")
    try:
        manifest = pp.download_and_install(get_settings(), entry, __version__)
    except pp.PackError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    return {"installed": manifest["id"], "version": manifest["pack_version"], "project_types": manifest.get("project_types", [])}


@router.delete("/{pack_id}")
def remove(pack_id: str, request: Request):
    operator(request)
    try:
        pp.remove(get_settings(), pack_id)
    except pp.PackError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    return {"removed": pack_id}
