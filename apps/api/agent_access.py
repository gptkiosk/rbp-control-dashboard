"""Local-only agent capabilities: task reads and operator-reviewed planning drafts."""
import os
import re
import secrets
import stat
import time
import uuid
from fastapi import HTTPException
from sqlalchemy import select, text
from auth import digest, loopback
from models import AgentAccess

TOKEN_FILE = "hermes.token"

def local_request(request):
    return (request.client is not None and loopback(request.client.host)
        and request.url.hostname in {"127.0.0.1", "localhost", "::1"}
        and not any(k.lower() in {"forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"} for k in request.headers)
        and "origin" not in request.headers)

def permitted(method, path, scope):
    if method == "GET":
        return path in {"/api/agent-tools/tasks", "/api/agent-tools/agents", "/api/agent-tools/coordinator"} or bool(re.fullmatch(r"/api/agent-tools/tasks/[1-9][0-9]*", path))
    if scope != "draft": return False
    return (method == "POST" and (path == "/api/agent-tools/tasks" or bool(re.fullmatch(r"/api/agent-tools/tasks/[1-9][0-9]*/dependencies", path)))) or (method == "PATCH" and bool(re.fullmatch(r"/api/agent-tools/tasks/[1-9][0-9]*", path))) or (method == "DELETE" and bool(re.fullmatch(r"/api/agent-tools/tasks/[1-9][0-9]*/dependencies/[1-9][0-9]*", path)))

class AgentAccessService:
    def __init__(self, settings, sessions, clock=time.time):
        self.settings, self.sessions, self.clock = settings, sessions, clock

    @property
    def token_path(self): return self.settings.data_dir / "agent-tokens" / TOKEN_FILE

    def metadata(self, row):
        state = "revoked" if row.revoked_at else "expired" if row.expires_at <= self.clock() else "active"
        return {k: getattr(row, k) for k in ("id", "agent", "scope", "created_by", "created_at", "expires_at", "revoked_at", "last_used_at")} | {"state": state, "token_file": str(self.token_path)}

    def list(self):
        with self.sessions() as s:
            return {"grants": [self.metadata(r) for r in s.scalars(select(AgentAccess).order_by(AgentAccess.created_at.desc()).limit(50))], "token_file": str(self.token_path), "auth_enabled": self.settings.auth_enabled}

    def issue(self, scope, days, operator):
        if not self.settings.auth_enabled: raise HTTPException(409, "Enable Google sign-in before granting agent access.")
        if scope not in {"read", "draft"} or days not in {1, 7, 30}: raise HTTPException(422, "Unsupported access scope or duration.")
        token, now, grant_id = secrets.token_urlsafe(48), int(self.clock()), uuid.uuid4().hex
        folder = self.token_path.parent
        folder.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = grant_id + ".tmp"
        try:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise HTTPException(409, "Agent credential folder must be owned by this Mac user, mode 700.")
            with self.sessions.begin() as s:
                s.execute(text("BEGIN IMMEDIATE"))
                for old in s.scalars(select(AgentAccess).where(AgentAccess.revoked_at.is_(None), AgentAccess.agent == "hermes")): old.revoked_at = now
                row = AgentAccess(id=grant_id, token_hash=digest(token), agent="hermes", scope=scope,
                    created_by=operator, created_at=now, expires_at=now+days*86400)
                s.add(row)
                secret_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                with os.fdopen(secret_fd, "w") as output:
                    output.write(token + "\n"); output.flush(); os.fsync(output.fileno())
                os.replace(temporary, TOKEN_FILE, src_dir_fd=fd, dst_dir_fd=fd)
                result = self.metadata(row)
            return result
        finally:
            try: os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError: pass
            os.close(fd)

    def authorize(self, request):
        if not self.settings.auth_enabled or not local_request(request):
            raise HTTPException(403, "Agent access requires a direct local connection without browser or proxy headers.")
        value = request.headers.get("authorization", "")
        if not re.fullmatch(r"Bearer [A-Za-z0-9_-]{64}", value): raise HTTPException(401, "Agent credential refused.")
        with self.sessions.begin() as s:
            row = s.scalar(select(AgentAccess).where(AgentAccess.token_hash == digest(value[7:])))
            if not row or row.revoked_at or row.expires_at <= self.clock(): raise HTTPException(401, "Agent credential expired, revoked or refused.")
            if not permitted(request.method, request.url.path, row.scope): raise HTTPException(403, "This route is outside the approved agent access.")
            row.last_used_at = int(self.clock())
            return {"id": row.id, "agent": row.agent, "scope": row.scope}

    def revoke(self, grant_id):
        with self.sessions.begin() as s:
            row = s.get(AgentAccess, grant_id)
            if not row: raise HTTPException(404, "Agent access not found.")
            row.revoked_at = row.revoked_at or int(self.clock())
            return self.metadata(row)
