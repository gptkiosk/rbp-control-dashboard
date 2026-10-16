"""Bug reports: preview what would be sent, and either file it through the guarded GitHub action or hand back a prefilled GitHub link."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import bug_reports
from github_actions import ActionError
from routes.agent_tools import operator
from settings import get_settings

router = APIRouter(prefix="/api/bug-reports")


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=400)
    what: str = Field(default="", max_length=12000)
    expected: str = Field(default="", max_length=8000)
    steps: str = Field(default="", max_length=12000)
    impact: str = Field(default="annoying", max_length=20)
    page: str = Field(default="", max_length=80)
    include_environment: bool = True
    confirm: bool = False


def _caps(request: Request) -> dict:
    return bug_reports.capabilities(getattr(request.app.state, "github_actions", None), getattr(request.app.state, "github", None))


def _built(body: ReportIn) -> dict:
    try:
        return bug_reports.build(body.model_dump(exclude={"confirm", "include_environment"}), get_settings(), body.include_environment)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/capabilities")
def capabilities(request: Request):
    operator(request)
    return _caps(request)


@router.get("/intake")
def intake(request: Request):
    """The accepted reports that became tasks, the ones waiting for a maintainer's label, and when GitHub was last read."""
    operator(request)
    return request.app.state.bug_intake.status()


@router.post("/intake/refresh")
def intake_refresh(request: Request):
    operator(request)
    service = request.app.state.bug_intake
    if not service.enabled():
        raise HTTPException(409, "Bug report intake is off on this install.")
    return service.poll()


@router.post("/preview")
def preview(request: Request, body: ReportIn):
    """Exactly what would be sent, with what was scrubbed. Sends nothing."""
    operator(request)
    return {**_built(body), **{k: v for k, v in _caps(request).items() if k in {"mode", "reason"}}}


@router.post("/file", status_code=201)
def file(request: Request, body: ReportIn):
    """File the previewed issue as this install's signed-in GitHub account, through the guarded action (draft, review, approve, execute)."""
    actor = operator(request)
    if not body.confirm:
        raise HTTPException(422, "Confirm the preview before filing.")
    caps = _caps(request)
    if caps["mode"] != "direct":
        raise HTTPException(409, caps["reason"])
    built = _built(body)
    guard = request.app.state.github_actions
    content = {"title": built["title"], "body": built["body"], "labels": bug_reports.filing_labels(built["impact"])}
    try:
        drafted = guard.draft({"kind": "issue", "repo": bug_reports.REPOSITORY, "content": content}, actor)
        reviewed = guard.review(drafted["id"], actor)
        guard.approve(drafted["id"], reviewed["fingerprint"], reviewed["nonce"], actor)
        done = guard.execute(drafted["id"], reviewed["fingerprint"], actor)
    except ActionError as exc:
        raise HTTPException(exc.status, exc.message) from None
    return {"state": done["state"], "url": (done.get("result") or {}).get("html_url") or f"https://github.com/{bug_reports.REPOSITORY}/issues",
            "action_id": drafted["id"]}
