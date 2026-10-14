"""Content-addressed tool call ids shared by the adapter and the conformance MCP bridge.

ZeroClaw's trace has no call id that a tool server can see, so both sides derive one from what both
observe: the run, the bare tool name and the canonical arguments, plus an occurrence index for
repeats. Standard library only: ``mcp_bridge.py`` loads this file by path.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def call_id(run_id: str, name: str, arguments: Any, seen: dict[str, int]) -> str:
    try:
        canonical = json.dumps(json.loads(arguments) if isinstance(arguments, str) else arguments,
                               sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except ValueError:
        canonical = str(arguments)
    key = hashlib.sha256(f"{name}\0{canonical}".encode()).hexdigest()[:12]
    seen[key] = seen.get(key, 0) + 1
    return f"{run_id}:{key}:{seen[key]}"
