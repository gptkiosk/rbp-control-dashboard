"""MCD tool server: lets an agent (Hermes first) plan work on the Mac Control Dashboard board.

Runs over stdio, registered in an agent's MCP config through the dashboard's MCP approval flow.
It calls the dashboard API on loopback with the request-guard header and X-MCD-Actor: hermes,
so tasks it creates are attributed to Hermes. The server enforces every rule (working directory
roots, approvals, dependency cycles); this file only shapes requests and answers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlencode
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

BASE_URL = os.environ.get("MCD_URL", "http://127.0.0.1:8800").rstrip("/")
TOKEN_PATH = Path(os.environ.get("MCD_TOKEN_FILE", str(Path.home() / ".mac-control/agent-tokens/hermes.token")))
COLUMNS = ("backlog", "queued", "running", "review", "done", "failed")

Assignee = Literal["human", "claude", "codex", "hermes", "openclaw"]
Priority = Literal["urgent", "high", "normal", "low"]
Status = Literal["backlog", "queued", "running", "review", "done", "failed"]


class McdError(ToolError):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None

def credential():
    try:
        fd = os.open(TOKEN_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError()
            value = source.read(129).strip()
            if len(value) != 64 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in value): raise ValueError()
            return value
    except (OSError, ValueError, UnicodeError):
        raise McdError("Operator-approved MCD access is missing or invalid. Check the MCP Agent access panel; never use the recovery token.") from None


def request(method: str, path: str, body: Any = None) -> Any:
    try:
        url = urlsplit(BASE_URL)
        port = url.port
    except ValueError:
        raise McdError("MCD_URL must be an explicit HTTP loopback address and port.") from None
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"} or not port or url.username or url.password or url.path or url.query or url.fragment:
        raise McdError("MCD_URL must be an explicit HTTP loopback address and port.")
    if not (path == "/api/agents" or path == "/api/cards" or path.startswith("/api/cards/") or path.startswith("/api/coordinator?")):
        raise McdError("Route is outside MCD planning access.")
    target = (path.replace('/api/coordinator', '/api/agent-tools/coordinator', 1) if path.startswith('/api/coordinator?') else
        path.replace('/api/cards', '/api/agent-tools/tasks', 1) if path.startswith('/api/cards') else '/api/agent-tools/agents')
    headers = {"X-Mac-Control": "1", "Authorization": "Bearer " + credential()}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_URL + target, data=data, method=method, headers=headers)
    try:
        # Ignore inherited proxy settings and never forward credentials through redirects.
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read(4096) or b"{}").get("detail", "Request refused")
        except ValueError:
            detail = "Request refused"
        if exc.code == 401: detail = "MCD access expired or was revoked; ask the operator to review it."
        raise McdError(f"{exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise McdError("MCD is unreachable at its configured loopback address.") from None


def summary(card: dict) -> dict:
    """The fields an agent needs to reason about a task, without run logs."""
    return {
        "id": card["id"], "title": card["title"], "status": card["column"],
        "assignee": "human" if card.get("assignee_type") == "human" else card.get("agent"),
        "priority": card.get("priority"), "due_date": card.get("due_date"),
        "estimate_minutes": card.get("estimate_minutes"), "tags": card.get("tags", []),
        "depends_on": card.get("depends_on", []), "blocked_by": card.get("blocked_by", []),
        "needs_approval": card.get("needs_approval"), "approved": bool(card.get("approved_at")),
        "created_by": card.get("created_by"),
        "last_run_stage": (card.get("last_run") or {}).get("stage"),
    }


server = MCPServer(
    name="mcd",
    title="Mac Control Dashboard",
    instructions=(
        "Task board for the operator and the local agents (Claude Code, Codex, Hermes, OpenClaw). "
        "Use assignee 'human' for work only the operator can do (decisions, approvals, accounts, "
        "anything outside this Mac), and give it a clear definition of done in `acceptance`. "
        "Link work with depends_on. Draft access creates Backlog tasks and edits only Hermes's own "
        "Backlog drafts. The operator queues work, approves tasks and marks completion. Read access "
        "cannot change tasks. No run logs, chats, credentials or integration settings are accessible."
    ),
)


@server.tool(description="List tasks on the board, optionally filtered by status, assignee or tag.")
def list_tasks(status: Status | None = None, assignee: Assignee | None = None,
               tag: str | None = None, limit: int = 50) -> list[dict]:
    cards = request("GET", "/api/cards")["cards"]
    out = []
    for c in cards:
        s = summary(c)
        if status and s["status"] != status:
            continue
        if assignee and s["assignee"] != assignee:
            continue
        if tag and tag.lower() not in s["tags"]:
            continue
        out.append(s)
    return out[: max(1, min(limit, 200))]


@server.tool(description="Get one task with its description, definition of done and dependencies.")
def get_task(task_id: int) -> dict:
    card = request("GET", f"/api/cards/{task_id}")
    return {**summary(card), "description": card.get("body"), "acceptance": card.get("acceptance"),
            "dependents": card.get("dependents", []), "working_dir": card.get("working_dir"),
            "approval_reasons": card.get("approval_reasons", [])}


@server.tool(description=(
    "Create a task for the operator (assignee 'human') or an agent. Set queue=true to make an agent "
    "draft in Backlog. The operator reviews and queues work; queue=true is refused."))
def create_task(title: str, assignee: Assignee, description: str = "",
                acceptance: str | None = None, priority: Priority = "normal",
                due_date: str | None = None, estimate_minutes: int | None = None,
                tags: list[str] | None = None, depends_on: list[int] | None = None,
                working_dir: str | None = None, mode: Literal["read", "edit"] = "read",
                queue: bool = False) -> dict:
    if queue:
        raise McdError("MCD agent access creates Backlog drafts only. The operator must review and queue work.")
    body: dict[str, Any] = {
        "title": title, "body": description, "acceptance": acceptance, "priority": priority,
        "due_date": due_date, "estimate_minutes": estimate_minutes, "tags": tags or [],
        "depends_on": depends_on or [],
    }
    if assignee == "human":
        body["assignee_type"] = "human"
    else:
        if not working_dir:
            raise McdError("Agent tasks need working_dir (inside an installation-allowlisted workspace).")
        body.update({"assignee_type": "agent", "agent": assignee, "working_dir": working_dir, "mode": mode})
    card = request("POST", "/api/cards", body)
    result = summary(card)
    return result


@server.tool(description="Update Hermes's own Backlog draft title, priority, dates, tags, description or definition of done. Status changes require the operator.")
def update_task(task_id: int, status: Status | None = None, title: str | None = None,
                priority: Priority | None = None, due_date: str | None = None,
                estimate_minutes: int | None = None, tags: list[str] | None = None,
                description: str | None = None, acceptance: str | None = None) -> dict:
    if status is not None:
        raise McdError("Task status changes require the operator. Hermes can edit only its own Backlog drafts.")
    patch: dict[str, Any] = {k: v for k, v in {
        "title": title, "priority": priority, "due_date": due_date,
        "estimate_minutes": estimate_minutes, "tags": tags, "body": description,
        "acceptance": acceptance,
    }.items() if v is not None}
    if not patch:
        raise McdError("Nothing to update.")
    return summary(request("PATCH", f"/api/cards/{task_id}", patch))


@server.tool(description="Make task_id wait until depends_on_id is done. Cycles are refused.")
def add_dependency(task_id: int, depends_on_id: int) -> dict:
    return summary(request("POST", f"/api/cards/{task_id}/dependencies", {"depends_on_id": depends_on_id}))


@server.tool(description="Remove a dependency between two tasks.")
def remove_dependency(task_id: int, depends_on_id: int) -> dict:
    return summary(request("DELETE", f"/api/cards/{task_id}/dependencies/{depends_on_id}"))


@server.tool(description="List the agents, whether they are installed, what they are running, and OpenClaw's sub-agents.")
def list_agents() -> list[dict]:
    out = []
    for a in request("GET", "/api/agents")["agents"]:
        sub = a.get("subagents") or {}
        out.append({
            "id": a["id"], "name": a["name"], "role": a["role"], "available": a["available"],
            "default_model": a.get("default_model"),
            "running_now": [c.get("title") for c in a.get("current", [])],
            "runs_24h": a.get("runs_24h"),
            "sub_agents": [s["id"] for s in sub.get("agents", [])] if a["id"] == "openclaw" else [],
        })
    return out


@server.tool(description="Read shared Coordinator capabilities, project types, selected-type context, model evidence or a project status. Scoped reads only; use returned links for unsupported actions.")
def coordinator_read(operation:Literal['capabilities','types','context','models','status','workspace','repository_intake','intake_questions'],
        project_id:int|None=None,working_dir:str='',project_type:str|None=None) -> dict:
    query={'operation':operation}
    if project_id is not None: query['project_id']=project_id
    if working_dir: query['working_dir']=working_dir
    if project_type: query['project_type']=project_type
    return request('GET','/api/coordinator?'+urlencode(query))


if __name__ == "__main__":
    server.run("stdio")
