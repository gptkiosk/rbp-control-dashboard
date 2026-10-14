"""Common agent adapter contract (rcd.adapter.v1). Design only: no runtime implementation.

The dispatcher talks to every agent runtime (Claude, Codex, Hermes, OpenClaw today; ZeroClaw
and PicoClaw on the Pi) through `AgentAdapter`. Messages are plain dicts that validate against
adapter_schemas/adapter-contract.schema.json; the TypedDicts below mirror the required fields.
The rationale, mapping table and guarantees are in docs/port/adapter-contract.md.

Authority stays with MCD: an adapter runs exactly the assigned route, never switches models,
never queues work and never accepts its own output. It reports; MCD decides.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, AsyncIterator, Protocol, TypedDict, runtime_checkable

SCHEMA_VERSION = "rcd.adapter.v1"
SCHEMA_PATH = Path(__file__).resolve().parent / "adapter_schemas" / "adapter-contract.schema.json"


# ----------------------------------------------------------------------------- status machine


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT})

# Every allowed edge. Anything else is INVALID_TRANSITION; terminal states have no exits.
# A retry or route fallback is a NEW run (new run_id/idempotency_key, same work_key).
TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset({RunStatus.AWAITING_APPROVAL, *TERMINAL}),
    # -> running: resume(approve|answer). -> cancelled: reject or cancel. -> timed_out: approval_timeout_s.
    # -> failed: checkpoint lost / resume could not relaunch.
    RunStatus.AWAITING_APPROVAL: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.TIMED_OUT, RunStatus.FAILED}),
    **{t: frozenset() for t in TERMINAL},
}


def can_transition(current: RunStatus | None, new: RunStatus) -> bool:
    if current is None:
        return new is RunStatus.QUEUED
    return new in TRANSITIONS[current]


# Today's Run.stage values (dispatcher.py / projects.py) and their contract status.
# "interrupted" becomes failed + INTERRUPTED so the UI keeps its wording.
LEGACY_STAGE: dict[str, tuple[RunStatus, str | None]] = {
    "running": (RunStatus.RUNNING, None),
    "awaiting_approval": (RunStatus.AWAITING_APPROVAL, None),
    "succeeded": (RunStatus.SUCCEEDED, None),
    "failed": (RunStatus.FAILED, None),
    "cancelled": (RunStatus.CANCELLED, "CANCELLED"),
    "timeout": (RunStatus.TIMED_OUT, "TIMEOUT"),
    "interrupted": (RunStatus.FAILED, "INTERRUPTED"),
}


# ----------------------------------------------------------------------------- error taxonomy


class ErrorCategory(StrEnum):
    PREFLIGHT = "preflight"   # refused before any inference; nothing ran, nothing to review
    PROVIDER = "provider"     # model provider / gateway said no
    POLICY = "policy"         # MCD guarantee would be violated (model, budget, tools, sandbox)
    AGENT = "agent"           # the agent ran but its result is unusable
    LIFECYCLE = "lifecycle"   # timeout, cancel, approval outcome, restart
    CONTROL = "control"       # a control call was invalid; the run itself is unchanged
    INTERNAL = "internal"


@dataclass(frozen=True)
class ErrorInfo:
    category: ErrorCategory
    status: RunStatus | None  # terminal status this error implies; None = rejected call only
    retryable: bool           # explicit operator retry on the SAME route may help
    fallback_eligible: bool   # MCD may move to the next APPROVED route automatically
    requires_human: bool


_P, _V, _O, _A, _L, _C, _I = (ErrorCategory.PREFLIGHT, ErrorCategory.PROVIDER, ErrorCategory.POLICY,
                              ErrorCategory.AGENT, ErrorCategory.LIFECYCLE, ErrorCategory.CONTROL,
                              ErrorCategory.INTERNAL)
_F, _X, _T = RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT

ERRORS: dict[str, ErrorInfo] = {
    # preflight: status queued -> failed, no process or no inference
    "INVALID_RUN_SPEC":         ErrorInfo(_P, _F, False, False, True),
    "IDEMPOTENCY_CONFLICT":     ErrorInfo(_C, None, False, False, True),   # same key, different spec digest
    "RUNTIME_UNAVAILABLE":      ErrorInfo(_P, _F, True, False, True),     # binary/gateway missing
    "RUNTIME_INCOMPATIBLE":     ErrorInfo(_P, _F, False, False, True),    # e.g. Hermes guard cannot install
    "MODEL_NOT_ALLOWED":        ErrorInfo(_P, _F, False, False, True),    # route not in approved routes
    "MODEL_NOT_ENFORCEABLE":    ErrorInfo(_P, _F, False, False, True),    # runtime cannot pin/report model
    "WORKSPACE_REJECTED":       ErrorInfo(_P, _F, False, False, True),    # never relocate work elsewhere
    "CONCURRENCY_CONFLICT":     ErrorInfo(_C, None, True, False, False),  # overlapping workspace/target; stays queued
    # provider
    "PROVIDER_RATE_LIMITED":    ErrorInfo(_V, _F, True, True, False),
    "PROVIDER_QUOTA_EXHAUSTED": ErrorInfo(_V, _F, True, True, False),
    "PROVIDER_AUTH":            ErrorInfo(_V, _F, False, False, True),
    "PROVIDER_TIMEOUT":         ErrorInfo(_V, _T, True, False, True),
    "PROVIDER_ERROR":           ErrorInfo(_V, _F, True, False, True),
    # policy
    "MODEL_MISMATCH":           ErrorInfo(_O, _F, False, False, True),
    "BUDGET_EXCEEDED":          ErrorInfo(_O, _F, False, False, True),
    "TOOL_DENIED":              ErrorInfo(_O, _F, False, False, True),
    "SANDBOX_VIOLATION":        ErrorInfo(_O, _F, False, False, True),
    # agent / output
    "AGENT_ERROR":              ErrorInfo(_A, _F, True, False, True),
    "RESULT_MISSING":           ErrorInfo(_A, _F, True, False, True),
    "RESULT_INVALID":           ErrorInfo(_A, _F, True, False, True),
    "RESULT_INCOMPLETE":        ErrorInfo(_A, _F, True, False, True),
    # lifecycle
    "TIMEOUT":                  ErrorInfo(_L, _T, True, False, True),
    "CANCELLED":                ErrorInfo(_L, _X, True, False, False),
    "DECISION_REJECTED":        ErrorInfo(_L, _X, False, False, False),
    "APPROVAL_TIMEOUT":         ErrorInfo(_L, _T, True, False, True),
    "INTERRUPTED":              ErrorInfo(_L, _F, True, False, True),
    "LOST":                     ErrorInfo(_L, _F, True, False, True),
    # control-call rejections: returned to the caller, the run is unchanged
    "UNKNOWN_RUN":              ErrorInfo(_C, None, False, False, False),
    "INVALID_TRANSITION":       ErrorInfo(_C, None, False, False, False),
    "DECISION_CONFLICT":        ErrorInfo(_C, None, False, False, True),
    "ADAPTER_INTERNAL":         ErrorInfo(_I, _F, True, False, True),
}


def error(code: str, message: str, **detail: Any) -> dict[str, Any]:
    """Build a schema-valid Error object. Messages must already be redacted."""
    info = ERRORS[code]
    out = {"code": code, "category": str(info.category), "message": message, "retryable": info.retryable,
           "fallback_eligible": info.fallback_eligible, "requires_human": info.requires_human}
    if detail:
        out["detail"] = detail
    return out


class AdapterError(Exception):
    """Raised by control operations (start/cancel/resume/heartbeat) that are refused outright."""

    def __init__(self, code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.code, self.payload = code, error(code, message, **detail)


# ----------------------------------------------------------------------------- idempotency


def run_key(run_id: int | str) -> str:
    """Per-attempt key. MCD creates the Run row first, so the key exists before any process."""
    return f"mcd:run:{run_id}"


def work_key(card_id: int) -> str:
    """Per-story key, stable across retries, fallbacks and resumes."""
    return f"mcd:story:{card_id}"


def preassigned_session(card_id: int) -> str:
    """Same value dispatcher._claim already derives for OpenClaw story sessions."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mcd:story:{card_id}"))


def digest(value: str | dict[str, Any]) -> str:
    """sha256 of a prompt (context digest) or of a canonical RunSpec (idempotency check)."""
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def spec_digest(spec: RunSpec) -> str:
    """Fields that define the work. A start() replay must match exactly or get IDEMPOTENCY_CONFLICT."""
    return digest({k: spec[k] for k in ("run_id", "work_key", "attempt", "model_policy", "workspace",
                                        "limits", "budget", "session", "output")} | {"prompt": digest(spec["prompt"])})


# ----------------------------------------------------------------------------- messages (required fields)


class Route(TypedDict, total=False):
    agent: str
    model: str
    agent_target: str | None


class RunSpec(TypedDict, total=False):
    schema_version: str
    run_id: str
    idempotency_key: str
    work_key: str
    attempt: int
    origin: dict[str, Any]
    prompt: str
    context: dict[str, Any]
    model_policy: dict[str, Any]
    workspace: dict[str, Any]
    limits: dict[str, Any]
    budget: dict[str, Any]
    session: dict[str, Any]
    output: dict[str, Any]


class Event(TypedDict, total=False):
    schema_version: str
    run_id: str
    seq: int
    segment: int
    ts: int
    type: str
    data: dict[str, Any]


class RunResult(TypedDict, total=False):
    schema_version: str
    run_id: str
    idempotency_key: str
    status: str
    started_at: int | None
    ended_at: int | None
    duration_s: float | None
    exit_code: int | None
    model: dict[str, Any]
    session: dict[str, Any]
    usage: dict[str, Any]
    cost: dict[str, Any]
    resources: dict[str, Any]
    artifacts: list[dict[str, Any]]
    result_text: str | None
    structured_output: Any
    approval: dict[str, Any]
    error: dict[str, Any] | None
    context_digest: str | None
    last_seq: int


class Decision(TypedDict, total=False):
    schema_version: str
    run_id: str
    decision_id: str
    approval_id: str
    verdict: str
    option_id: str | None
    answer_text: str | None
    approved_output_sha256: str | None
    actor: str
    decided_at: int


class CancelRequest(TypedDict):
    schema_version: str
    run_id: str
    request_id: str
    reason: str
    actor: str


class Heartbeat(TypedDict, total=False):
    schema_version: str
    run_id: str
    status: str
    alive: bool
    pid: int | None
    last_seq: int
    last_activity_at: int | None
    deadline_at: int | None
    ts: int
    resources: dict[str, Any]


class RecoveredRun(TypedDict):
    run_id: str
    idempotency_key: str
    outcome: str  # reattached | awaiting_approval | finished_while_down | interrupted
    status: str
    last_seq: int


class Capabilities(TypedDict, total=False):
    schema_version: str
    adapter: str
    runtime_version: str | None
    pins_model: bool
    reports_model: str
    disables_native_fallback: bool
    enforces_mode: bool
    structured_output: str
    streams_events: bool
    tool_events: bool
    session: str
    suspend_modes: list[str]
    reports_cost: bool
    enforces_budget: str
    resource_measurement: str
    default_model: str | None


class Ack(TypedDict):
    run_id: str
    status: str
    replayed: bool  # True when this exact request was already applied


# ----------------------------------------------------------------------------- the interface


@runtime_checkable
class AgentAdapter(Protocol):
    """What the dispatcher calls. One instance per runtime; all methods are safe to call concurrently
    for different run_ids. Every method that changes state is idempotent (see docs, "Idempotency")."""

    name: str

    def capabilities(self) -> Capabilities:
        """Static facts the dispatcher checks before start (model pinning, sandbox, suspend modes...)."""
        ...

    async def start(self, spec: RunSpec) -> Ack:
        """Accept a run. Returns once the run is durably recorded as queued or running.

        Same idempotency_key + same spec_digest -> same Ack with replayed=True, no second process.
        Same key + different digest -> AdapterError(IDEMPOTENCY_CONFLICT).
        Preflight refusals are reported as a terminal `failed` result (not raised), so they are
        recorded on the run; only malformed specs raise INVALID_RUN_SPEC.
        """
        ...

    def events(self, run_id: str, after_seq: int = 0) -> AsyncIterator[Event]:
        """Replay events with seq > after_seq, then follow live until the run is terminal or
        awaiting_approval. At-least-once: consumers dedupe on (run_id, seq)."""
        ...

    async def result(self, run_id: str) -> RunResult:
        """Structured result. Only valid in awaiting_approval or a terminal state; otherwise
        AdapterError(INVALID_TRANSITION). Stable once terminal (same value on every call)."""
        ...

    async def cancel(self, request: CancelRequest) -> Ack:
        """Stop the run (process group SIGTERM, kill_grace_s, then SIGKILL). Idempotent by request_id.
        Cancel wins any race with completion that it observes first. A terminal run returns its
        status with replayed=True and is not changed."""
        ...

    async def resume(self, decision: Decision) -> Ack:
        """Apply a human decision to a run in awaiting_approval. approve/answer -> running (same
        run_id, segment + 1, timeout clock resumes); reject -> cancelled (DECISION_REJECTED).
        decision_id is applied at most once. A different decision for an already-decided
        approval_id -> AdapterError(DECISION_CONFLICT). A decision can never change the route,
        workspace, mode, budget or tools of the run."""
        ...

    async def heartbeat(self, run_id: str) -> Heartbeat:
        """Liveness and resource snapshot. Unknown run -> AdapterError(UNKNOWN_RUN)."""
        ...

    async def recover(self) -> list[RecoveredRun]:
        """Called once at dispatcher start, before any start(). Reconciles every non-terminal run in
        the adapter's state dir. Never relaunches work: a run that cannot be reattached becomes
        failed/INTERRUPTED (its process group is killed first) and MCD decides on any retry."""
        ...


# ----------------------------------------------------------------------------- schema access


def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


def schema_for(definition: str) -> dict[str, Any]:
    """A validator-ready schema for one message type, e.g. schema_for("RunSpec")."""
    root = schema()
    if definition not in root["$defs"]:
        raise KeyError(definition)
    return {**root, "$ref": f"#/$defs/{definition}"}
