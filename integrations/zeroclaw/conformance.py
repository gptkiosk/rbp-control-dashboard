"""Conformance ``Driver`` factory for ZeroClaw (tests/adapter_conformance ``harness.Driver``).

    RCD_CONFORMANCE_FACTORY='integrations.zeroclaw.conformance:create_driver'

Test instrumentation only. It builds the production ``ZeroClawAdapter`` and wires three things the
production contract has no place for: the provider proxy's independent receipts and fault injection,
the harness' synthetic tools (through ``mcp_bridge.py``), and the per-run workload description.
It never fabricates an adapter result and never performs the memory/artifact operations itself.

Fail-closed initialisation (free-only policy): the factory refuses unless

* ``RCD_ZEROCLAW_FREE_MODELS`` names a recent pricing snapshot (see ``admission.py``), and
* both the primary and the fallback route are agent ``zeroclaw`` with a model that the snapshot
  lists at price zero.

The catalog handed to the adapter holds exactly those two models, so any other model is refused
before inference. ``OPENROUTER_API_KEY`` is read by the proxy per request; it is never copied.
Optional: ``RCD_ZEROCLAW_BIN`` (default ``zeroclaw`` on PATH) and ``RCD_ZEROCLAW_UPSTREAM`` (default
OpenRouter; point at a loopback stand-in for offline rehearsals).
"""
from __future__ import annotations

import asyncio
import hmac
import http.server
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import threading
from typing import Any

from adapter_contract import SCHEMA_VERSION, TERMINAL

from .adapter import ZeroClawAdapter, ZeroClawConfig
from .admission import FreeModelCatalog, Refusal
from .proxy import ProviderProxy

SERVER = "rcd"
BRIDGE = Path(__file__).with_name("mcp_bridge.py")
TOOLS = ("echo", "memory_write", "memory_read", "artifact_write")
FAILURES = {"PROVIDER_RATE_LIMITED": "rate_limit", "PROVIDER_QUOTA_EXHAUSTED": "quota", "PROVIDER_AUTH": "auth",
            "PROVIDER_ERROR": "provider_error", "TOOL_DENIED": "tool_denied"}


def workload(scenario: str, run_id: str) -> str:
    """What the model must do for a harness scenario. Tool names carry the MCP server prefix."""
    p = SERVER + "__"
    final = 'Finish with exactly one JSON object {"ok":true,"value":"<string>"} and nothing else.'
    return {
        "structured": f'Do not call any tool. {final} Use the string "x" as value.',
        "tool": f'Call {p}echo exactly once with value "{run_id}". {final} Use the string it returned as value.',
        "memory_write": f'Call {p}memory_write once with key "handoff" and value "{run_id}". {final} Use "{run_id}" as value.',
        "memory_read": f'Call {p}memory_read once with key "handoff". {final} Use the string it returned as value.',
        "artifact": f'Call {p}artifact_write once with path "artifact.txt" and value "one artifact". {final} Use "artifact.txt" as value.',
        "long_running": (f'Call {p}echo with value "1", then "2", then "3" and so on with the next number, forever '
                         f'(never repeat a value). Never give a final answer.'),
        "approval": (f'Call {p}artifact_write with path "before.txt" and value "before". Then stop and wait for a human '
                     f'to approve. Only after approval call {p}artifact_write with path "after.txt" and value "after". '
                     f'{final} Use "continued from checkpoint" as value.'),
    }.get(scenario, "")


class _ToolServer:
    """Loopback endpoint the MCP bridge calls. Bearer token required; binds 127.0.0.1 only."""

    def __init__(self, services: Any) -> None:
        self.token, self.scenarios, self.services = secrets.token_urlsafe(24), {}, services
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a: Any) -> None:
                pass

            def do_POST(self) -> None:
                if not hmac.compare_digest(self.headers.get("authorization", ""), "Bearer " + owner.token):
                    return self._send(401, {"error": "unauthorised"})
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                if self.path == "/scenario":
                    return self._send(200, {"text": workload(owner.scenarios.get(body["run_id"], ""), body["run_id"])})
                try:
                    result = owner.services.tool(body["run_id"], body["call_id"], body["name"], body["arguments"])
                except Exception as exc:  # journal only records successful calls
                    return self._send(400, {"error": type(exc).__name__})
                self._send(200, {"result": result})

            def _send(self, status: int, payload: Any) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True, name="zeroclaw-tools").start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class ZeroClawDriver:
    def __init__(self, adapter: ZeroClawAdapter, proxy: ProviderProxy, tools: _ToolServer, state: Path) -> None:
        self.adapter, self._proxy, self._tools, self._state = adapter, proxy, tools, state

    def configure(self, run_id: str, *, scenario: str = "structured", failure: str | None = None,
                  reported_model: str | None = None) -> None:
        self._tools.scenarios[run_id] = scenario
        self._proxy.inject(run_id, failure=FAILURES[failure] if failure else None, reported_model=reported_model)

    def receipts(self, run_id: str) -> list[dict[str, Any]]:
        return self._proxy.receipts(run_id)

    async def close(self) -> None:
        for run_id, run in list(self.adapter._runs.items()):
            if run["status"] not in {str(s) for s in TERMINAL}:
                await self.adapter.cancel({"schema_version": SCHEMA_VERSION, "run_id": run_id,
                                           "request_id": f"close:{run_id}", "reason": "shutdown", "actor": "driver"})
        await asyncio.to_thread(self._proxy.stop)
        self._tools.stop()
        shutil.rmtree(self._state, ignore_errors=True)


def create_driver(config: Any) -> ZeroClawDriver:
    snapshot = os.environ.get("RCD_ZEROCLAW_FREE_MODELS")
    if not snapshot:
        raise RuntimeError("RCD_ZEROCLAW_FREE_MODELS is required: refusing to run without a free-model price snapshot")
    routes = {"primary": config.primary, "fallback": config.fallback}
    for label, route in routes.items():
        if route.get("agent") != "zeroclaw":
            raise RuntimeError(f"The {label} route is not a zeroclaw route")
    full = FreeModelCatalog.load(Path(snapshot))
    models = {r["model"] for r in routes.values()}
    try:
        for model in models:
            full.admit(model)
    except Refusal as refusal:
        raise RuntimeError(f"Refusing to initialise: {refusal.message}") from refusal
    catalog = FreeModelCatalog({m: full.models[m] for m in models}, full.verified_at, full.source, full.max_age_s)

    proxy = ProviderProxy(catalog, upstream=os.environ.get("RCD_ZEROCLAW_UPSTREAM", "https://openrouter.ai/api/v1"))
    proxy.start()
    tools = _ToolServer(config.services)
    state = Path(tempfile.mkdtemp(prefix="rcd-zeroclaw-"))  # outside the workspace under test
    servers = {SERVER: {"command": sys.executable, "args": [str(BRIDGE)], "tools": list(TOOLS),
                        "env": {"RCD_TOOL_URL": tools.url, "RCD_TOOL_TOKEN": tools.token, "RCD_RUN_ID": "{run_id}"}}}
    adapter = ZeroClawAdapter(ZeroClawConfig(state_dir=state, proxy=proxy, catalog=catalog,
                                             executable=os.environ.get("RCD_ZEROCLAW_BIN") or shutil.which("zeroclaw") or "zeroclaw",
                                             mcp_servers=servers))
    return ZeroClawDriver(adapter, proxy, tools, state)
