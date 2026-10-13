"""Phase 6 read-only panels. The app's normal sign-in guard protects every route."""
import asyncio
import re
import time
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from deps import get_session
from models import AlertEvent, Card, FindingDraftLink, Run
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api")


class FindingDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    finding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    assignee_type: str = "agent"
    agent: str | None = None
    agent_target: str | None = None
    model: str | None = None
    mode: str = "read"
    working_dir: str | None = None
    priority: str = "normal"
    depends_on: list[int] = Field(default_factory=list, max_length=50)
    timeout_s: int | None = Field(default=None, ge=30, le=6 * 3600)
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    retry_backoff_s: int | None = Field(default=None, ge=0, le=3600)
    budget_usd: float | None = Field(default=None, ge=0.01, le=50.0)


def _finding_status(session, link):
    card = session.get(Card, link.card_id)
    if card is None:
        return None
    run = session.scalar(select(Run).where(Run.card_id == card.id).order_by(Run.id.desc()).limit(1))
    return {"task_id": card.id, "task_status": card.column,
            "run_id": run.id if run else None, "run_status": run.stage if run else None}

def _operator(request):
    from routes.agent_tools import operator
    operator(request)

@router.get("/github/status")
def github_status(request: Request):
    return request.app.state.github.status()

@router.get("/github/account-repos")
def github_account_repos(request: Request, owner: str = Query(default="", max_length=60)):
    """The checklist behind the GitHub settings: one account's repositories, read only, operator only."""
    _operator(request)
    from github_read import GithubDenied, GithubNotFound, GithubUnavailable
    try:
        return request.app.state.github.account_repos(owner.strip())
    except ValueError:
        raise HTTPException(422, "Enter a GitHub account or organisation name.") from None
    except GithubNotFound:
        raise HTTPException(404, f"No GitHub account or organisation named {owner.strip()} is visible to this login.") from None
    except GithubDenied:
        raise HTTPException(502, "GitHub refused the request. Check the gh login or the rate limit.") from None
    except GithubUnavailable:
        raise HTTPException(502, "GitHub could not be reached right now.") from None

@router.put("/github/config")
async def github_config(request: Request):
    _operator(request)
    try:
        body=await request.json()
        if body.get("enabled") is True:
            status = request.app.state.github.auth_status()
            if status["available"] and status["account"] != body.get("account"):
                raise HTTPException(422, "The selected account is not the active scoped gh login.")
            gone = request.app.state.github.missing([r for r in body.get("repos", []) if isinstance(r, str)]) if status["available"] else []
            if gone:
                first = gone[0]
                raise HTTPException(422, f"{first['name']} was not found for this GitHub login. Check the spelling."
                                    + (f" Did you mean {first['hint']}?" if first["hint"] else ""))
        else:
            status = {"available": False, "account": ""}
        result = request.app.state.github_config.save(body)
    except (ValueError, TypeError, OSError):
        raise HTTPException(422, "GitHub configuration must use a valid account, non-empty repository allowlist, and a 5 minute or slower cadence.") from None
    task = request.app.state.github_poll_task
    if result["configured"] and (task is None or task.done()):
        request.app.state.github_poll_stop=asyncio.Event();request.app.state.github_poll_task=asyncio.create_task(request.app.state.github.poll(request.app.state.github_poll_stop))
    return {**result,"login":status}

@router.post("/github/migrate")
async def migrate_github(request: Request):
    _operator(request)
    if request.app.state.github.status()["state"]!="migration_required":raise HTTPException(409,"GitHub configuration was already migrated.")
    return await github_config(request)

@router.post("/github/refresh")
def refresh_github(request: Request):
    _operator(request);return request.app.state.github.refresh(manual=True)

def _github_view(request,session):
    import profiles
    config=request.app.state.github.config()
    if config is None:return None,False
    selected=profiles.prefs(session,profiles.owner(request)).github;allowed=set(config.repos)
    if selected.repos:allowed&=set(selected.repos)
    return allowed,config.public_only or selected.public_only

@router.get("/github/repos")
def repositories(request: Request,session:Session=Depends(get_session)):
    allowed,public_only=_github_view(request,session);value=request.app.state.github.repos()
    if allowed is None:return value
    return {**value,"repos":[repo for repo in value["repos"] if repo["name"] in allowed and not (public_only and repo["private"])]}

@router.get("/github/repos/{owner}/{repo}")
def repository(request: Request, owner: str, repo: str,session:Session=Depends(get_session)):
    allowed,_=_github_view(request,session)
    if allowed is not None and f"{owner}/{repo}" not in allowed:raise HTTPException(404,"Repository is not in the accessible catalog.")
    value = request.app.state.github.details(f"{owner}/{repo}")
    if value is None:
        raise HTTPException(404, "Repository is not in the accessible catalog.")
    return value

@router.get("/reports")
def reports(request: Request):
    return request.app.state.reports.catalog()

@router.get("/report-storage")
def report_storage(request: Request):
    from routes.agent_tools import operator
    operator(request)
    return request.app.state.reports.status()

@router.put("/report-storage")
async def configure_report_storage(request: Request):
    from routes.agent_tools import operator
    operator(request)
    try:
        body = await request.json()
        if (not isinstance(body, dict) or set(body) != {"ops", "hermes", "reset"}
                or not isinstance(body["ops"], str) or not isinstance(body["hermes"], str)
                or type(body["reset"]) is not bool):
            raise ValueError("Invalid report storage request.")
        return request.app.state.reports.configure(body["ops"], body["hermes"], body["reset"])
    except ValueError:
        raise HTTPException(422, "Report storage could not be saved. Use an existing approved local folder without symlinks or private folders.") from None
    except OSError:
        raise HTTPException(409, "Host report storage configuration is unavailable. Check local folder permissions.") from None

@router.get("/ops-collectors")
def ops_collectors(request: Request):
    return request.app.state.ops_collectors.status()

@router.post("/ops-collectors/refresh")
async def refresh_ops_collectors(request: Request):
    """On-demand run of the configured collectors; the request can only name configured sources."""
    from ops_collectors import Busy, ConfigError
    _operator(request)
    try:
        body = await request.json() if await request.body() else {}
        if not isinstance(body, dict) or set(body) - {"sources", "force"} or type(body.get("force", False)) is not bool:
            raise ConfigError("Invalid refresh request.")
        return await asyncio.to_thread(request.app.state.ops_collectors.run, body.get("sources"), body.get("force", False))
    except Busy:
        raise HTTPException(409, "A collector run is already in progress.") from None
    except (ConfigError, ValueError):
        raise HTTPException(422, "Refresh must name configured sources and the collector configuration must be valid.") from None
    except OSError:
        raise HTTPException(409, "Collector report storage is unavailable. Check the Ops report folder.") from None

@router.post("/ops-collectors/archive")
async def archive_ops_reports(request: Request):
    """Copy earlier reports into the labelled historic archive. Takes no input; originals are never changed."""
    _operator(request)
    if await request.body():
        raise HTTPException(422, "Archive takes no request body.")
    try:
        return await asyncio.to_thread(request.app.state.ops_collectors.archive_historic)
    except OSError:
        raise HTTPException(409, "Collector report storage is unavailable. Check the Ops report folder.") from None

@router.get("/reports/{report_id}")
def report(request: Request, report_id: str, session: Session = Depends(get_session)):
    if not re.fullmatch(r"[a-f0-9]{64}", report_id):
        raise HTTPException(404, "Report not found.")
    try:
        result = request.app.state.reports.read(report_id)
        finding_ids = set(re.findall(r"^## ([a-z0-9][a-z0-9_-]{0,39}) - (?:ok|warn|crit) ", result["content"], re.M))
        links = session.scalars(select(FindingDraftLink).where(FindingDraftLink.finding_id.in_(finding_ids))).all() if finding_ids else []
        result["finding_tasks"] = {link.finding_id: _finding_status(session, link) for link in links}
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except OSError:
        raise HTTPException(404, "Report is unavailable. Refresh the report list.") from None


@router.post("/reports/{report_id}/findings/{finding_id}/draft", status_code=201)
def draft_from_finding(request: Request, report_id: str, finding_id: str, body: FindingDraftIn,
                       session: Session = Depends(get_session)):
    """Create one Backlog draft per report finding. Draft creation never queues work."""
    from routes.tasks import _card_dict, _dependency_maps
    import cards
    from settings import get_settings
    _operator(request)
    if report_id != body.report_id or finding_id != body.finding_id:
        raise HTTPException(422, "Finding identity must match the request path.")
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        report_data = request.app.state.reports.read(report_id)
    except (ValueError, OSError):
        raise HTTPException(404, "Report is unavailable. Refresh the report list.") from None
    match = re.search(rf"^## {re.escape(finding_id)} - (warn|crit) \([^\n]*\)\n(.*?)(?=^## |\Z)",
                      report_data["content"], re.M | re.S)
    if not match:
        raise HTTPException(404, "Actionable finding not found in this report.")
    existing = session.scalar(select(FindingDraftLink).where(FindingDraftLink.finding_id == finding_id))
    if existing:
        card = session.get(Card, existing.card_id)
        return {"created": False, "task": _card_dict(card, deps=_dependency_maps(session, [card.id])),
                **(_finding_status(session, existing) or {})}
    data = body.model_dump(exclude={"report_id", "finding_id"})
    data.update({"title": f"Investigate Ops finding: {finding_id}"[:200],
                 "body": f"Source report: {report_id}\nFinding: {finding_id}\n\n{match.group(2).strip()}"[:100_000],
                 "tags": ["ops-finding"],
                 "acceptance": "Review the evidence, resolve or explain the finding, and record the result."})
    card = cards.create(session, data, get_settings(), created_by="operator")
    link = FindingDraftLink(report_id=report_id, finding_id=finding_id, card_id=card.id, created_at=int(time.time()))
    session.add(link)
    session.commit()
    session.refresh(card)
    return {"created": True, "task": _card_dict(card, deps=_dependency_maps(session, [card.id])),
            **(_finding_status(session, link) or {})}


@router.get("/alerts")
def alerts(request: Request):
    return request.app.state.alerts.status()


@router.post("/alerts/{event_id}/acknowledge")
def acknowledge_alert(event_id: str, session: Session = Depends(get_session)):
    if not re.fullmatch(r"[a-f0-9]{32}", event_id):
        raise HTTPException(404, "Alert not found.")
    event = session.get(AlertEvent, event_id)
    if event is None:
        raise HTTPException(404, "Alert not found.")
    if event.status not in {"uncertain", "held"}:
        raise HTTPException(409, "Only alerts awaiting delivery review can be acknowledged.")
    event.reviewed_at = event.reviewed_at or int(time.time())
    session.commit()
    return {"ok": True, "reviewed_at": event.reviewed_at}
