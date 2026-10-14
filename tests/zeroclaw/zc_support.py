"""Shared helpers: a local OpenRouter stand-in and run-spec builder. No network, no secrets."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import importlib.util

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# apps/api must NOT go on sys.path: it ships `tests` and `platform` packages that would shadow the
# repository's `tests` and the standard library. Load the contract by file, as the conformance
# harness does, and register it under its production name.
if "adapter_contract" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("adapter_contract", ROOT / "apps" / "api" / "adapter_contract.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["adapter_contract"] = _module
    _spec.loader.exec_module(_module)

from adapter_contract import SCHEMA_VERSION, run_key, work_key  # noqa: E402

FREE = "vendor/free-a:free"
PAID = "vendor/paid-b"
ZERO = {"prompt": "0", "completion": "0", "request": "0"}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok", "value"],
          "properties": {"ok": {"const": True}, "value": {"type": "string"}}}
FINAL = {"role": "assistant", "content": '{"ok":true,"value":"x"}'}


def tool_message(name: str, **arguments):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


class Upstream:
    """OpenAI-compatible stand-in for OpenRouter. Records what the proxy forwarded."""

    def __init__(self) -> None:
        self.script: list[dict] = []
        self.delay = 0.0
        self.served_model: str | None = None
        self.cost: float | None = 0
        self.requests: list[dict] = []
        self.status = 200
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                owner.requests.append({"model": body.get("model"), "stream": body.get("stream"),
                                       "provider": body.get("provider"), "auth": self.headers.get("authorization"),
                                       "max_tokens": body.get("max_tokens")})
                time.sleep(owner.delay)
                message = owner.script.pop(0) if owner.script else FINAL
                usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
                if owner.cost is not None:
                    usage["cost"] = owner.cost
                payload = {"id": f"gen-{len(owner.requests)}", "provider": "StubProvider",
                           "model": owner.served_model or body.get("model"), "usage": usage,
                           "choices": [{"index": 0, "message": message,
                                        "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}]}
                data = json.dumps(payload).encode()
                self.send_response(owner.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def zeroclaw_binary() -> str | None:
    return os.environ.get("RCD_ZEROCLAW_BIN") or shutil.which("zeroclaw")


def make_spec(workspace: Path, *, run_id="zc-1", model=FREE, timeout=20, tools=None, mode="edit",
              billing="free", fallbacks=None, **limits):
    return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "idempotency_key": run_key(run_id),
            "work_key": work_key(1), "attempt": 1, "origin": {"kind": "story"}, "prompt": "Do the work.",
            "context": {"digest": "0" * 64},
            "model_policy": {"assigned": {"agent": "zeroclaw", "model": model},
                             "approved_fallback_routes": fallbacks or [], "allow_runtime_fallback": False,
                             "require_model_report": True},
            "workspace": {"path": str(workspace), "mode": mode, "allowed_tools": tools or []},
            "limits": {"timeout_s": timeout, "kill_grace_s": 0.5, "max_transient_retries": 0, **limits},
            "budget": {"billing": billing, "max_cost_usd": 0.01, "max_output_tokens": 256},
            "session": {"mode": "new"}, "output": {"format": "json", "json_schema": SCHEMA}}
