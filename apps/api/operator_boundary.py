"""Operator authority boundary: agent processes cannot call operator APIs.

Agents run as the same OS user as this service and reach it over loopback, so a loopback
address, a file in the data folder or an inherited variable cannot tell them apart from the
operator. Three layers keep operator authority out of their reach:

1. Runner environment scrub. Every agent runner starts without this app's settings
   (MAC_CONTROL_*, MCD_*, RCD_*: sign-in client secret, cost keys, data paths), so no
   operator credential or location is inherited. Run-specific values are added afterwards.
2. Peer-process check. For a request from this machine, the process that owns the client
   socket is identified. If it is an agent process, only the agent capability routes (each
   with its own scoped bearer credential) and /healthz are served. Everything else is refused,
   including sign-in recovery, approvals, dispatch and settings, whatever the request carries.
   Agent processes are the session and process tree of every live runner recorded on an
   unfinished run, plus the trees of the configured agent executables (gateways and
   interactive CLIs that run tools outside a dispatched run).
   If agent processes exist and the owner cannot be determined, state changes are refused.
3. Audit. Every refusal adds a note to the matched run and a line to
   <data_dir>/security-audit.jsonl (owner-only, rotated at 1 MB). Query strings are not logged.

The operator's own credentials (the session cookie when sign-in is on, the recovery token)
are never put into a runner's environment, and are refused from agent processes even if read
from disk. Limits: a process that fully detaches from both the runner session and every
configured agent tree (double fork plus setsid) is not recognised, and scripting the
operator's browser is not blocked here. A separate OS account for agents is the stronger
boundary.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass

import psutil
from fastapi.responses import JSONResponse
from sqlalchemy import select

from models import Run, RunEvent

logger = logging.getLogger("mac_control.operator_boundary")

SCRUB_PREFIXES = ("MAC_CONTROL_", "MCD_", "RCD_")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
AUDIT_FILE = "security-audit.jsonl"
AUDIT_MAX_BYTES = 1024 * 1024
ROOTS_TTL_S = 2.0
INTERPRETER = re.compile(r"^(?:node|bun|deno|[Pp]ython[0-9.]*)$")
REFUSED = "Operator APIs are not available to agent processes."
UNVERIFIED = ("Operator APIs refused: agent processes are running and the caller could not be "
              "verified as the operator. Try again, or stop the agent run.")


def runner_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for an agent runner: the service's own, minus this app's settings."""
    source = os.environ if base is None else base
    return {k: v for k, v in source.items() if not k.upper().startswith(SCRUB_PREFIXES)}


def agent_route(method: str, path: str, has_bearer: bool) -> bool:
    """Routes an agent process may use. Each has its own scoped credential check."""
    if path == "/healthz":
        return method in SAFE_METHODS
    if path.startswith("/api/agent-tools/"):
        return has_bearer
    return path == "/api/hermes-projects" and method == "POST" and has_bearer


@dataclass(frozen=True)
class Peer:
    pid: int | None
    name: str
    run_id: int | None
    verified: bool = True


def _ip(value):
    try:
        ip = ipaddress.ip_address(value)
    except (TypeError, ValueError):
        return None
    return (ip.ipv4_mapped or ip) if ip.version == 6 else ip


class OperatorBoundary:
    def __init__(self, settings, sessions, clock=time.time):
        self.settings, self.sessions, self.clock = settings, sessions, clock
        self.executables = frozenset(getattr(settings, "agent_executables", ()) or ())
        self._roots: tuple[float, frozenset[int]] = (0.0, frozenset())
        self._audit_lock = threading.Lock()

    # ------------------------------------------------------------------ discovery

    def _runner_roots(self) -> dict[int, int]:
        """pid -> run id for runners on unfinished runs.

        A pid now held by a process older than the run is a reused pid and is skipped. A runner
        that already exited is kept: its id still names the session its descendants are in.
        """
        with self.sessions() as s:
            rows = s.execute(select(Run.id, Run.pid, Run.started_at)
                             .where(Run.pid.is_not(None), Run.ended_at.is_(None))).all()
        roots = {}
        for run_id, pid, started_at in rows:
            try:
                if psutil.Process(pid).create_time() < (started_at or 0) - 2:
                    continue
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                pass  # cannot be inspected: treat as the runner (fail toward refusal)
            roots[pid] = run_id
        return roots

    def _executable_roots(self) -> frozenset[int]:
        """Processes running a configured agent executable, cached briefly (they are long-lived)."""
        if not self.executables:
            return frozenset()
        stamp, cached = self._roots
        if time.monotonic() - stamp < ROOTS_TTL_S:
            return cached
        found = set()
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name") or ""
            if name in self.executables:
                found.add(proc.pid)
                continue
            try:
                argv = proc.cmdline()
            except psutil.Error:
                continue
            # A version-named binary is still invoked as `claude`; scripts run under an interpreter.
            names = [os.path.basename(a) for a in argv[:3 if INTERPRETER.match(name) else 1]]
            if any(n in self.executables for n in names):
                found.add(proc.pid)
        result = frozenset(found)
        self._roots = (time.monotonic(), result)
        return result

    def _agent_processes(self) -> dict[int, int | None]:
        """pid -> run id (None for configured executables) for every agent process."""
        runners = self._runner_roots()
        roots = {pid: None for pid in self._executable_roots()} | runners
        if not roots:
            return {}
        children: dict[int, list[int]] = {}
        pids = []
        for proc in psutil.process_iter(["ppid"]):
            pids.append(proc.pid)
            children.setdefault(proc.info.get("ppid") or 0, []).append(proc.pid)
        agents = dict(roots)
        queue = list(roots)
        while queue:
            parent = queue.pop()
            for child in children.get(parent, ()):
                if child not in agents:
                    agents[child] = agents[parent]
                    queue.append(child)
        # Runners lead their own session; a re-parented background process keeps it.
        if runners:
            for pid in pids:
                if pid in agents:
                    continue
                try:
                    sid = os.getsid(pid)
                except OSError:
                    continue
                if sid in runners:
                    agents[pid] = runners[sid]
        agents.pop(os.getpid(), None)
        return agents

    def peer(self, client, server) -> Peer | None:
        """The agent process owning this connection's client socket, or None for anyone else.

        Only connections from this machine are examined. A Peer with verified=False means
        agent processes exist but at least one could not be inspected.
        """
        if not client or not server:
            return None
        client_ip, server_ip = _ip(client[0]), _ip(server[0])
        if client_ip is None or not (client_ip.is_loopback or client_ip == server_ip):
            return None
        client_port, server_port = int(client[1]), int(server[1])
        unverified = False
        for pid, run_id in self._agent_processes().items():
            try:
                proc = psutil.Process(pid)
                connections = proc.net_connections(kind="inet")
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except psutil.AccessDenied:
                # On Linux a zombie (a runner that exited and is not yet reaped) reports AccessDenied
                # instead of ZombieProcess. It holds no sockets, so it is not an uninspectable process.
                try:
                    if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                        continue
                except psutil.Error:
                    pass
                unverified = True
                continue
            for c in connections:
                if not c.laddr or not c.raddr or c.laddr.port != client_port or c.raddr.port != server_port:
                    continue
                local, remote = _ip(c.laddr.ip), _ip(c.raddr.ip)
                if (local is None or local == client_ip) and (remote is None or server_ip is None or remote == server_ip):
                    try:
                        name = proc.name()
                    except psutil.Error:
                        name = ""
                    return Peer(pid, name, run_id)
        return Peer(None, "", None, verified=False) if unverified else None

    # ------------------------------------------------------------------ enforcement

    def refusal(self, request) -> JSONResponse | None:
        """Called by the request middleware (in a worker thread). None lets the request through."""
        path, method = request.url.path, request.method
        if agent_route(method, path, bool(request.headers.get("authorization"))):
            return None
        if path.startswith("/assets/"):
            return None
        server = request.scope.get("server")
        client = (request.client.host, request.client.port) if request.client else None
        try:
            peer = self.peer(client, server)
        except Exception:
            logger.exception("operator boundary check failed")
            peer = Peer(None, "", None, verified=False)
        if peer is None or (not peer.verified and method in SAFE_METHODS):
            return None
        self.audit(peer, method, path)
        return JSONResponse({"detail": REFUSED if peer.verified else UNVERIFIED}, status_code=403)

    def audit(self, peer: Peer, method: str, path: str) -> None:
        now = int(self.clock())
        what = f"{method} {path[:200]}"
        record = {"ts": now, "event": "operator_api_refused" if peer.verified else "operator_api_unverified",
                  "request": what, "pid": peer.pid, "process": peer.name[:80], "run_id": peer.run_id}
        logger.warning("refused operator API call %s from agent pid=%s run=%s", what, peer.pid, peer.run_id)
        try:
            with self._audit_lock:
                path_ = self.settings.data_dir / AUDIT_FILE
                try:
                    if path_.stat().st_size > AUDIT_MAX_BYTES:
                        os.replace(path_, path_.with_suffix(".jsonl.1"))
                except FileNotFoundError:
                    pass
                fd = os.open(path_, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as out:
                    out.write(json.dumps(record) + "\n")
        except OSError:
            logger.exception("could not write the security audit file")
        if peer.run_id is not None:
            try:
                with self.sessions.begin() as s:
                    if s.get(Run, peer.run_id) is not None:
                        s.add(RunEvent(run_id=peer.run_id, ts=now, kind="note",
                                       text=f"refused operator API call from an agent process (pid {peer.pid}): {what}"))
            except Exception:
                logger.exception("could not record the refusal on run %s", peer.run_id)
