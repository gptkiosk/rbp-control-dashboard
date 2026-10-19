"""Host readiness: what this machine still needs before projects can be built and delivered from it (operator only)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import host_readiness as hr
import profiles
from settings import get_settings

router = APIRouter(prefix="/api/host/readiness", tags=["host"])


class FixIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern="^(create_workspace|set_git_identity|make_github_key|test_github_ssh|add_tools_to_path|brew_install|brew_update|colima_start|brew_install_all|brew_upgrade_all)$")
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    path: str | None = Field(default=None, max_length=500)
    tool: str | None = Field(default=None, pattern="^(ffmpeg|python3|docker|colima)$")


@router.get("")
def readiness(request: Request, network: bool = False):
    profiles.owner(request)
    return hr.report(get_settings(), network=network)


@router.post("/fix")
def fix(body: FixIn, request: Request):
    profiles.owner(request)
    settings = get_settings()
    try:
        message = hr.apply(settings, body.action, body.name, body.email, body.path, body.tool)
    except hr.ReadinessError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    return {"message": message, "report": hr.report(settings), "job": hr.current_job()}


@router.get("/job")
def job(request: Request):
    profiles.owner(request)
    return {"job": hr.current_job()}


@router.get("/tools")
def tools(request: Request, check_updates: bool = False):
    """The optional system tools with versions; `check_updates` also asks Homebrew what is outdated (slower, local index only)."""
    profiles.owner(request)
    return hr.system_tools(get_settings(), check_updates=check_updates)


@router.get("/tools/health")
def tools_health(request: Request):
    profiles.owner(request)
    return hr.system_tools_health(get_settings())
