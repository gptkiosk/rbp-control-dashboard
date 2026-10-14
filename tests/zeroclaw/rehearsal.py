"""Offline rehearsal of the live conformance driver: real zeroclaw + real driver + SCRIPTED provider.

    export RCD_CONFORMANCE_LIVE=1 RCD_CONFORMANCE_FACTORY=rehearsal:create_driver \\
           RCD_CONFORMANCE_AGENT=zeroclaw RCD_CONFORMANCE_MODEL=vendor/free-a:free \\
           RCD_CONFORMANCE_FALLBACK_AGENT=zeroclaw RCD_CONFORMANCE_FALLBACK_MODEL=vendor/free-b:free \\
           RCD_CONFORMANCE_COST_CAP_USD=0.01 OPENROUTER_API_KEY=rehearsal-not-a-secret \\
           PYTHONPATH=tests/zeroclaw:. RCD_ZEROCLAW_BIN=/path/to/zeroclaw
    python -m pytest -q tests/adapter_conformance

The "provider" below is a deterministic script, not an LLM, and nothing leaves loopback. It proves the
adapter, proxy, MCP bridge and driver plumbing under the unchanged suite. It says NOTHING about how
well any real free model follows these workloads; that needs the live run.
"""
from __future__ import annotations

import json
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

from integrations.zeroclaw.conformance import create_driver as real_create_driver

RUN = re.compile(r"probe-[\w-]+-\d+")
SCENARIO = re.compile(r"Conformance workload (\w+)")


def _text(message) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else json.dumps(content)


class ScriptedModel:
    def __init__(self) -> None:
        self.steps: dict[str, int] = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                payload = owner.respond(body)
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.counter = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def respond(self, body):
        messages = body.get("messages", [])
        # With native tools the workload text (and run id) travels in the tool descriptions.
        everything = " ".join(_text(m) for m in messages) + json.dumps(body.get("tools") or [])
        user = next((_text(m) for m in messages if m.get("role") == "user"), "")
        scenario = (SCENARIO.search(user) or SCENARIO.search(everything) or [None, "structured"])[1]
        run_id = (RUN.search(everything) or [None])[0]
        key = run_id or user
        step = self.steps.get(key, 0)
        self.steps[key] = step + 1
        self.counter += 1
        last = _text(messages[-1]) if messages else ""
        seen = RUN.search(last)
        if os.environ.get("RCD_REHEARSAL_DEBUG"):
            with open(os.environ["RCD_REHEARSAL_DEBUG"], "a") as out:
                out.write(json.dumps({"scenario": scenario, "step": step, "roles": [m.get("role") for m in messages],
                                      "last": last[-700:], "full": body}) + "\n")
        p = "rcd__"

        def call(name, **args):
            return {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call_{self.counter}", "type": "function", "function": {"name": p + name, "arguments": json.dumps(args)}}]}

        def final(value):
            return {"role": "assistant", "content": json.dumps({"ok": True, "value": value})}

        if scenario == "tool":
            message = call("echo", value=run_id) if step == 0 else final(seen[0] if seen else run_id)
        elif scenario == "memory_write":
            message = call("memory_write", key="handoff", value=run_id) if step == 0 else final(run_id)
        elif scenario == "memory_read":
            message = call("memory_read", key="handoff") if step == 0 else final(seen[0] if seen else "")
        elif scenario == "artifact":
            message = call("artifact_write", path="artifact.txt", value="one artifact") if step == 0 else final("artifact.txt")
        elif scenario == "long_running":
            time.sleep(0.05)
            message = call("echo", value=str(step))  # distinct arguments: ZeroClaw stops identical repeated calls
        else:
            message = final("x")
        return {"id": f"gen-{self.counter}", "provider": "ScriptedProvider", "model": body["model"],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25, "cost": 0},
                "choices": [{"index": 0, "message": message,
                             "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}]}

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class _Rehearsal:
    def __init__(self, driver, model, snapshot):
        self._driver, self._model, self._snapshot = driver, model, snapshot
        self.adapter, self.configure, self.receipts = driver.adapter, driver.configure, driver.receipts

    async def close(self):
        try:
            await self._driver.close()
        finally:
            self._model.stop()
            Path(self._snapshot).unlink(missing_ok=True)


def create_driver(config):
    model = ScriptedModel()
    models = {config.primary["model"]: {"prompt": "0", "completion": "0"},
              config.fallback["model"]: {"prompt": "0", "completion": "0"}}
    handle, snapshot = tempfile.mkstemp(prefix="rcd-rehearsal-", suffix=".json")
    with os.fdopen(handle, "w") as out:
        json.dump({"verified_at": int(time.time()), "source": "rehearsal", "models": models}, out)
    os.environ["RCD_ZEROCLAW_FREE_MODELS"] = snapshot
    os.environ["RCD_ZEROCLAW_UPSTREAM"] = model.url
    return _Rehearsal(real_create_driver(config), model, snapshot)
