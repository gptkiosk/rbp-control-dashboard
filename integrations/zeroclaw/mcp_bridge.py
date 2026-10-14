#!/usr/bin/env python3
"""Conformance-test instrumentation, not part of the production adapter.

A minimal stdio MCP server (newline-delimited JSON-RPC) that exposes the harness' synthetic tools
(echo, memory_write, memory_read, artifact_write) to ZeroClaw and forwards every call to the
conformance driver's loopback ToolServer, where the harness' ``Services`` journals it. It also asks
the driver which workload this run is meant to perform and states it in the tool descriptions.
Environment: RCD_TOOL_URL, RCD_TOOL_TOKEN, RCD_RUN_ID. Standard library only.
"""
import importlib.util
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("zc_callid", os.path.join(HERE, "callid.py"))
callid = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(callid)

URL, TOKEN, RUN_ID = os.environ["RCD_TOOL_URL"], os.environ["RCD_TOOL_TOKEN"], os.environ["RCD_RUN_ID"]
SEEN = {}


def post(path, payload):
    request = urllib.request.Request(URL + path, data=json.dumps(payload).encode(), method="POST",
                                     headers={"authorization": "Bearer " + TOKEN, "content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - loopback driver only
        return json.loads(response.read())


def _schema(**properties):
    return {"type": "object", "properties": {k: {"type": "string"} for k in properties},
            "required": list(properties), "additionalProperties": False}


TOOLS = {
    "echo": ("Return the given value unchanged.", _schema(value=0)),
    "memory_write": ("Store a value under a key in shared project memory.", _schema(key=0, value=0)),
    "memory_read": ("Read the value stored under a key in shared project memory.", _schema(key=0)),
    "artifact_write": ("Write a text file inside the workspace.", _schema(path=0, value=0)),
}
INSTRUCTIONS = post("/scenario", {"run_id": RUN_ID}).get("text", "")


def reply(ident, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": ident}
    message.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def handle(message):
    method, ident, params = message.get("method"), message.get("id"), message.get("params") or {}
    if ident is None:  # notifications need no reply
        return
    if method == "initialize":
        reply(ident, {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "rcd-conformance", "version": "1"},
                      "instructions": INSTRUCTIONS})
    elif method == "tools/list":
        reply(ident, {"tools": [{"name": name, "description": (text + " " + INSTRUCTIONS).strip(), "inputSchema": schema}
                                for name, (text, schema) in TOOLS.items()]})
    elif method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return reply(ident, error={"code": -32602, "message": "unknown tool"})
        cid = callid.call_id(RUN_ID, name, arguments, SEEN)
        try:
            result = post("/tool", {"run_id": RUN_ID, "call_id": cid, "name": name, "arguments": arguments})
            reply(ident, {"content": [{"type": "text", "text": str(result["result"])}], "isError": False})
        except Exception as exc:  # report to the model; the journal is the source of truth
            reply(ident, {"content": [{"type": "text", "text": f"error: {type(exc).__name__}"}], "isError": True})
    elif method == "ping":
        reply(ident, {})
    else:
        reply(ident, error={"code": -32601, "message": "method not found"})


for line in sys.stdin:
    if line.strip():
        handle(json.loads(line))
