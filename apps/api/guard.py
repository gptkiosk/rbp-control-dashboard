"""Request guard: blocks cross-site and DNS-rebinding requests before sign-in exists.

The server binds to 127.0.0.1, but any web page open in a browser on this Mac can still send
requests to it. Without this guard a malicious page could create a card and make an agent run
its prompt. Rules:

  every request    Host must be a loopback name on an allowed port (blocks DNS rebinding)
  state changes    Origin, when present, must be one of the allowed origins, AND the custom
                   header X-Mac-Control: 1 must be present. Browsers cannot add a custom header
                   to a cross-origin request without a CORS preflight, which this app never grants.
"""

from __future__ import annotations

from fastapi import Request
from urllib.parse import urlsplit
from fastapi.responses import JSONResponse

GUARD_HEADER = "x-mac-control"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def allowed_hosts(ports: tuple[int, ...]) -> set[str]:
    return {f"{h}:{p}" for h in LOOPBACK_HOSTS for p in ports}


def allowed_origins(ports: tuple[int, ...]) -> set[str]:
    return {f"http://{h}" for h in allowed_hosts(ports)}


def check(request: Request, ports: tuple[int, ...], origins: tuple[str, ...] = ()) -> str | None:
    """Return a refusal reason, or None when the request may proceed."""
    host = request.headers.get("host", "")
    if host not in allowed_hosts(ports) | {urlsplit(o).netloc for o in origins}:
        return "host not allowed"
    if request.method in SAFE_METHODS:
        return None
    origin = request.headers.get("origin")
    if origin is not None and origin not in allowed_origins(ports) | set(origins):
        return "origin not allowed"
    if request.headers.get(GUARD_HEADER) != "1":
        return "missing X-Mac-Control header"
    return None


def refusal(reason: str) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": f"Request refused: {reason}."})
