"""Loopback provider boundary between ZeroClaw and OpenRouter.

ZeroClaw's ``openrouter`` provider type ignores ``uri`` and keeps its API key in config.toml, so it
can neither be metered nor kept off disk. The adapter instead points a ``custom`` provider at this
proxy with a per-run bearer token. The proxy

* holds the real OpenRouter key (read from the environment per request, never persisted or logged),
* admits only the run's assigned model, only while the free-model snapshot says it is zero-priced,
  and asks OpenRouter to enforce ``provider.max_price`` = 0 as a second, upstream guard,
* forces non-streaming requests so every response yields exactly one receipt,
* records independent receipts (response id, SERVED model, provider, usage, cost) per run,
* refuses all further requests once a run is closed (cancel, timeout, mismatch, breach) and aborts
  the connection of any request already in flight.

It stores no prompts or completions. The usage of a request abandoned in flight is not observable
(no response arrives, so no receipt exists); under the free-only policy it is zero-priced by
construction, and a paid policy would have to reconcile such requests against the provider's ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import http.server
import json
import math
import os
import secrets
import socket
import threading
import time
from typing import Any
import urllib.parse

from .admission import FreeModelCatalog, Refusal
from apps.api.openrouter_costs import fetch_key, check_remaining

ZERO_PRICE_CAP = {"prompt": 0, "completion": 0, "request": 0, "image": 0}
_INJECTED_STATUS = {"rate_limit": 429, "quota": 402, "auth": 401, "provider_error": 503, "tool_denied": 403}
_MAX_BODY = 8 * 1024 * 1024


@dataclass
class _Run:
    run_id: str
    model: str
    max_requests: int
    max_tokens: int | None
    closed: bool = False
    requests: int = 0
    receipts: list[dict[str, Any]] = field(default_factory=list)
    refusals: list[tuple[str, str]] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    inject_failure: str | None = None
    inject_model: str | None = None
    active: set = field(default_factory=set)


class ProviderProxy:
    def __init__(self, catalog: FreeModelCatalog, *, upstream: str = "https://openrouter.ai/api/v1",
                 key_env: str = "OPENROUTER_API_KEY", upstream_timeout_s: float = 120.0,
                 host: str = "127.0.0.1", port: int = 0, account_fetch=fetch_key) -> None:
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("The provider proxy only binds to loopback")
        self.catalog, self.upstream, self.key_env = catalog, upstream.rstrip("/"), key_env
        self.account_fetch = account_fetch
        self.upstream_timeout_s = upstream_timeout_s
        self._lock = threading.Lock()
        self._by_token: dict[str, _Run] = {}
        self._by_run: dict[str, _Run] = {}
        self._pending_inject: dict[str, tuple[str | None, str | None]] = {}
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:  # never log request data
                pass

            def _send(self, status: int, payload: Any) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                # Model listing: advertise nothing so the runtime cannot discover paid models.
                self._send(200, {"object": "list", "data": []})

            def do_POST(self) -> None:
                size = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(size) if 0 < size <= _MAX_BODY else b""
                status, payload = proxy._handle(self.path, self.headers.get("authorization", ""), raw)
                self._send(status, payload)

        self._server = http.server.ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ lifecycle
    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="zeroclaw-proxy")
            self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def admit_account(self) -> None:
        key = os.environ.get(self.key_env, "")
        if not key:
            raise Refusal("PROVIDER_AUTH", "No OpenRouter credential is configured")
        try:
            check_remaining(self.account_fetch(key), 0.0)
        except Exception:
            raise Refusal("BUDGET_EXCEEDED", "OpenRouter account budget is unavailable") from None

    # ------------------------------------------------------------------ per-run state
    def register(self, run_id: str, model: str, *, max_requests: int = 400, max_tokens: int | None = None) -> str:
        token = "rcd-" + secrets.token_urlsafe(24)
        run = _Run(run_id, model, max_requests, max_tokens)
        with self._lock:
            run.inject_failure, run.inject_model = self._pending_inject.pop(run_id, (None, None))
            self._by_token[token] = run
            self._by_run[run_id] = run
        return token

    def close_run(self, run_id: str) -> None:
        """Refuse all further traffic for the run and abort any request already in flight upstream."""
        with self._lock:
            run = self._by_run.get(run_id)
            if run is None:
                return
            run.closed = True
            pending = list(run.active)
        for conn in pending:
            sock = getattr(conn, "sock", None)
            try:
                if sock:
                    sock.shutdown(socket.SHUT_RDWR)  # wakes a thread blocked in recv; close() alone does not
            except OSError:
                pass

    def inject(self, run_id: str, *, failure: str | None = None, reported_model: str | None = None) -> None:
        """Test instrumentation: fail the next requests or change the served-model metadata."""
        if failure and failure not in _INJECTED_STATUS:
            raise ValueError(failure)
        with self._lock:
            run = self._by_run.get(run_id)
            if run is None:  # configured before the adapter registers the run
                self._pending_inject[run_id] = (failure, reported_model)
            else:
                run.inject_failure, run.inject_model = failure, reported_model

    def receipts(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            run = self._by_run.get(run_id)
            return [json.loads(json.dumps(r)) for r in run.receipts] if run else []

    def refusals(self, run_id: str) -> list[tuple[str, str]]:
        with self._lock:
            run = self._by_run.get(run_id)
            return list(run.refusals) if run else []

    def statuses(self, run_id: str) -> list[int]:
        with self._lock:
            run = self._by_run.get(run_id)
            return list(run.statuses) if run else []

    def flags(self, run_id: str) -> set[str]:
        with self._lock:
            run = self._by_run.get(run_id)
            return set(run.flags) if run else set()

    # ------------------------------------------------------------------ request handling
    def _refuse(self, run: _Run, code: str, message: str, status: int = 403) -> tuple[int, dict[str, Any]]:
        with self._lock:
            run.refusals.append((code, message))
            if code == "BUDGET_EXCEEDED":
                run.closed = True
                run.flags.add("cost_breach")
        return status, {"error": {"message": message, "type": "rcd_admission", "code": code}}

    def _handle(self, path: str, authorization: str, raw: bytes) -> tuple[int, dict[str, Any]]:
        token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
        with self._lock:
            run = self._by_token.get(token)
        if run is None:
            return 401, {"error": {"message": "Unknown run token", "code": "RCD_UNKNOWN_RUN"}}
        if not path.rstrip("/").endswith("/chat/completions"):
            return self._refuse(run, "MODEL_NOT_ALLOWED", "Only chat completions are permitted", 404)
        with self._lock:
            if run.closed:
                run.refusals.append(("CANCELLED", "Run is closed"))
                return 403, {"error": {"message": "Run is closed", "code": "RCD_RUN_CLOSED"}}
            run.requests += 1
            over = run.requests > run.max_requests
            failure = run.inject_failure
        if over:
            return self._refuse(run, "BUDGET_EXCEEDED", "Per-run request cap reached")
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._refuse(run, "INVALID_RUN_SPEC", "Malformed request body", 400)
        if body.get("model") != run.model:
            return self._refuse(run, "MODEL_NOT_ALLOWED", "Requested model is not the assigned model")
        try:
            self.catalog.admit(run.model)
        except Refusal as refusal:
            return self._refuse(run, refusal.code, refusal.message)
        if failure:  # injected before any metered inference or upstream call
            if failure == "tool_denied":  # a policy refusal rather than a provider status
                return self._refuse(run, "TOOL_DENIED", "Tool use refused by policy")
            with self._lock:
                run.statuses.append(_INJECTED_STATUS[failure])
            return _INJECTED_STATUS[failure], {"error": {"message": f"injected {failure}", "code": failure}}
        key = os.environ.get(self.key_env, "")
        if not key:
            with self._lock:
                run.statuses.append(401)
            return self._refuse(run, "PROVIDER_AUTH", "No OpenRouter credential is configured", 401)

        try:
            self.admit_account()
        except Refusal as refusal:
            return self._refuse(run, refusal.code, refusal.message)

        for banned in ("models", "route", "transforms", "plugins"):
            body.pop(banned, None)
        body["stream"] = False
        body.pop("stream_options", None)
        provider = body.get("provider") if isinstance(body.get("provider"), dict) else {}
        body["provider"] = {**provider, "max_price": dict(ZERO_PRICE_CAP)}
        if run.max_tokens:
            asked = body.get("max_tokens")
            body["max_tokens"] = min(asked, run.max_tokens) if isinstance(asked, int) and asked > 0 else run.max_tokens

        parts = urllib.parse.urlsplit(self.upstream)
        connect = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        conn = connect(parts.hostname, parts.port, timeout=self.upstream_timeout_s)
        with self._lock:
            run.active.add(conn)
            closed = run.closed  # closed between the check above and now: never send
        try:
            if closed:
                raise ConnectionAbortedError
            conn.request("POST", parts.path.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                         {"content-type": "application/json", "authorization": f"Bearer {key}", "x-title": "RCD"})
            response = conn.getresponse()
            status, data = response.status, response.read(_MAX_BODY)
        except (OSError, http.client.HTTPException):
            with self._lock:
                aborted = run.closed
                if not aborted:
                    run.statuses.append(504)
            if aborted:  # cancelled/timed out mid-flight: usage of the abandoned request is unobservable
                return 499, {"error": {"message": "run closed during request", "code": "RCD_RUN_CLOSED"}}
            return 504, {"error": {"message": "upstream unreachable", "code": "upstream_unreachable"}}
        finally:
            with self._lock:
                run.active.discard(conn)
            conn.close()
        with self._lock:
            run.statuses.append(status)
        if status >= 400:
            return status, {"error": {"message": f"upstream status {status}", "code": "upstream_error"}}
        return self._account(run, status, data)

    def _account(self, run: _Run, status: int, data: bytes) -> tuple[int, dict[str, Any]]:
        try:
            payload = json.loads(data)
            usage = payload["usage"]
            tokens_in, tokens_out = int(usage["prompt_tokens"]), int(usage["completion_tokens"])
            response_id = str(payload["id"])
            if not response_id or tokens_in < 0 or tokens_out < 0:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            with self._lock:
                run.flags.add("unaccounted_response")
                run.closed = True
            return self._refuse(run, "RESULT_INVALID", "Provider response lacked id or usage; refused", 502)
        reported_cost = usage.get("cost")
        if isinstance(reported_cost, (int, float)) and not isinstance(reported_cost, bool) and math.isfinite(reported_cost) and reported_cost >= 0:
            cost, cost_source = float(reported_cost), "reported"
        else:
            with self._lock:
                run.flags.add("unaccounted_response")
                run.closed = True
            return self._refuse(run, "RESULT_INVALID", "Provider response lacked authoritative cost; refused", 502)
        served = run.inject_model or payload.get("model")
        receipt = {"source": "provider_response", "response_id": response_id,
                   "provider": str(payload.get("provider") or "openrouter"), "model": served,
                   "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
                   "cost_usd": cost, "cost_source": cost_source, "ts": int(time.time())}
        with self._lock:
            run.receipts.append(receipt)
            breach = cost > 0
            mismatch = served != run.model
            if breach:
                run.flags.add("cost_breach")
            if mismatch:
                run.flags.add("model_mismatch")
            if breach or mismatch:
                run.closed = True  # withhold the response: no artifacts from a wrong/paid model
        if breach:
            return self._refuse(run, "BUDGET_EXCEEDED", "Provider reported a non-zero cost", 502)
        if mismatch:
            return self._refuse(run, "MODEL_MISMATCH", "Served model differs from the assignment", 502)
        return status, payload
