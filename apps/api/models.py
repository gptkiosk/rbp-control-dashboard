"""ORM models for Phase 2: Mac metrics and launchd service snapshots.

Three metric tables share one column set:
  metric_sample  raw 10 s samples, kept 24 h
  metric_minute  1-minute averages, kept 30 days
  metric_day     daily averages, kept 365 days
Rollup tables also keep maxima for CPU, CPU temperature and system power.
Timestamps are UTC epoch seconds (int) for cheap range queries.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base

# Numeric metric columns shared by all three metric tables, in display order.
METRIC_FIELDS: tuple[str, ...] = (
    "cpu_pct",
    "ecpu_pct",
    "pcpu_pct",
    "gpu_pct",
    "mem_used",
    "mem_total",
    "swap_used",
    "swap_total",
    "pressure_level",
    "disk_used",
    "disk_total",
    "net_rx_bps",
    "net_tx_bps",
    "cpu_temp",
    "gpu_temp",
    "sys_power",
    "cpu_power",
    "gpu_power",
    "ane_power",
    "ram_power",
    "fan_rpm",
)

MAX_FIELDS: tuple[str, ...] = ("cpu_pct", "cpu_temp", "sys_power")


class _MetricColumns:
    ts: Mapped[int] = mapped_column(Integer, primary_key=True)
    cpu_pct: Mapped[float | None] = mapped_column(Float)
    ecpu_pct: Mapped[float | None] = mapped_column(Float)
    pcpu_pct: Mapped[float | None] = mapped_column(Float)
    gpu_pct: Mapped[float | None] = mapped_column(Float)
    mem_used: Mapped[float | None] = mapped_column(Float)
    mem_total: Mapped[float | None] = mapped_column(Float)
    swap_used: Mapped[float | None] = mapped_column(Float)
    swap_total: Mapped[float | None] = mapped_column(Float)
    pressure_level: Mapped[float | None] = mapped_column(Float)
    disk_used: Mapped[float | None] = mapped_column(Float)
    disk_total: Mapped[float | None] = mapped_column(Float)
    net_rx_bps: Mapped[float | None] = mapped_column(Float)
    net_tx_bps: Mapped[float | None] = mapped_column(Float)
    cpu_temp: Mapped[float | None] = mapped_column(Float)
    gpu_temp: Mapped[float | None] = mapped_column(Float)
    sys_power: Mapped[float | None] = mapped_column(Float)
    cpu_power: Mapped[float | None] = mapped_column(Float)
    gpu_power: Mapped[float | None] = mapped_column(Float)
    ane_power: Mapped[float | None] = mapped_column(Float)
    ram_power: Mapped[float | None] = mapped_column(Float)
    fan_rpm: Mapped[float | None] = mapped_column(Float)


class _MaxColumns:
    cpu_pct_max: Mapped[float | None] = mapped_column(Float)
    cpu_temp_max: Mapped[float | None] = mapped_column(Float)
    sys_power_max: Mapped[float | None] = mapped_column(Float)


class MetricSample(_MetricColumns, Base):
    __tablename__ = "metric_sample"


class MetricMinute(_MetricColumns, _MaxColumns, Base):
    __tablename__ = "metric_minute"


class MetricDay(_MetricColumns, _MaxColumns, Base):
    __tablename__ = "metric_day"


class ServiceSnapshot(Base):
    """One launchd job observed at one moment. Kept 7 days."""

    __tablename__ = "service_snapshot"
    __table_args__ = (Index("ix_service_snapshot_label_ts", "label", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(20))  # "gui" or "system"
    state: Mapped[str | None] = mapped_column(String(40))
    pid: Mapped[int | None] = mapped_column(Integer)
    runs: Mapped[int | None] = mapped_column(Integer)
    last_exit: Mapped[str | None] = mapped_column(String(80))
    path: Mapped[str | None] = mapped_column(String(500))
    program: Mapped[str | None] = mapped_column(String(500))
    run_interval_s: Mapped[int | None] = mapped_column(Integer)
    calendar: Mapped[bool | None] = mapped_column(Boolean)


# ---------------------------------------------------------------------------- Phase 3

COLUMNS: tuple[str, ...] = ("backlog", "queued", "running", "review", "done", "failed")
RUN_STAGES: tuple[str, ...] = (
    "running", "succeeded", "failed", "timeout", "cancelled", "interrupted", "awaiting_approval",
)


class Card(Base):
    """A task on the board. The body is the prompt sent to the agent."""

    __tablename__ = "card"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    # assignee_type "agent" runs through the dispatcher; "human" is the operator's own task and is
    # never dispatched (agent and working_dir are then None).
    assignee_type: Mapped[str] = mapped_column(String(10), default="agent")
    agent: Mapped[str | None] = mapped_column(String(40))
    agent_target: Mapped[str | None] = mapped_column(String(80))  # OpenClaw agent id
    model: Mapped[str | None] = mapped_column(String(120))  # None = the agent's default
    mode: Mapped[str] = mapped_column(String(10), default="read")  # read | edit
    working_dir: Mapped[str | None] = mapped_column(String(500))
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # urgent|high|normal|low
    due_date: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    estimate_minutes: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[str | None] = mapped_column(Text)  # JSON list of lowercase tags
    acceptance: Mapped[str | None] = mapped_column(Text)  # definition of done
    # Standard job envelope (see job_envelope.py): filterable, aggregatable columns, all optional so older cards stay valid.
    # Who a human task is assigned to (an approved user: an email or short name). None = unassigned. Agent tasks use `agent`/`model`.
    assignee_user: Mapped[str | None] = mapped_column(String(255), index=True)
    kind: Mapped[str | None] = mapped_column(String(16), index=True)  # research|plan|implement|review|test|docs|ops|triage
    size: Mapped[str | None] = mapped_column(String(4))  # xs|s|m|l|xl
    risk: Mapped[str | None] = mapped_column(String(8))  # low|medium|high
    area: Mapped[str | None] = mapped_column(String(40))
    route_tier: Mapped[str | None] = mapped_column(String(16))  # free|subscription|api|human, derived from the route
    route_reason: Mapped[str | None] = mapped_column(String(300))
    column: Mapped[str] = mapped_column(String(20), default="backlog", index=True)
    position: Mapped[float] = mapped_column(Float, default=0.0)
    timeout_s: Mapped[int] = mapped_column(Integer)
    # A story has both an absolute wall-clock budget and a shorter no-progress budget.
    # NULL idle_timeout_s means only the wall clock is enforced.
    idle_timeout_s: Mapped[int | None] = mapped_column(Integer)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    retry_backoff_s: Mapped[int] = mapped_column(Integer, default=0)
    retry_after: Mapped[int | None] = mapped_column(Integer, index=True)
    budget_usd: Mapped[float | None] = mapped_column(Float)
    needs_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_reasons: Mapped[str | None] = mapped_column(Text)  # JSON list
    approved_at: Mapped[int | None] = mapped_column(Integer)
    approval_grant: Mapped[str | None] = mapped_column(Text)  # JSON single-use grant; see approval.py
    created_by: Mapped[str] = mapped_column(String(20), default="operator")  # operator | hermes
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    # Execution key reused by an interruption requeue; cleared when the execution ends.
    idempotency_key: Mapped[str | None] = mapped_column(String(120))


class CardDependency(Base):
    """card_id cannot start until depends_on_id is Done."""

    __tablename__ = "card_dependency"

    card_id: Mapped[int] = mapped_column(ForeignKey("card.id", ondelete="CASCADE"), primary_key=True)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey("card.id", ondelete="CASCADE"), primary_key=True, index=True)


class FindingDraftLink(Base):
    """Durable, unique provenance from one Ops report finding to its draft task."""

    __tablename__ = "finding_draft_link"
    __table_args__ = (UniqueConstraint("finding_id", name="uq_finding_draft_finding"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(String(64), index=True)
    finding_id: Mapped[str] = mapped_column(String(40))
    card_id: Mapped[int] = mapped_column(ForeignKey("card.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[int] = mapped_column(Integer)


class Run(Base):
    """One execution of a card. Fields an agent does not report stay NULL."""

    __tablename__ = "run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # A run belongs to a card (task board) or to a chat thread (Phase 3b), never both.
    card_id: Mapped[int | None] = mapped_column(ForeignKey("card.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("chat_thread.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(40), index=True)
    model_requested: Mapped[str | None] = mapped_column(String(120))
    model_reported: Mapped[str | None] = mapped_column(String(120))
    provider: Mapped[str | None] = mapped_column(String(80))
    stage: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[int] = mapped_column(Integer, index=True)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    session_id: Mapped[str | None] = mapped_column(String(120))
    working_dir: Mapped[str] = mapped_column(String(500))
    command: Mapped[str] = mapped_column(Text)  # JSON argv with the prompt replaced
    log_path: Mapped[str] = mapped_column(String(500))
    result_text: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    # Durable lifecycle (migration 0012). Attempts of one execution share idempotency_key;
    # at most one is running and at most one succeeds (partial unique indexes).
    idempotency_key: Mapped[str | None] = mapped_column(String(120), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    requeued_from: Mapped[int | None] = mapped_column(Integer)
    pid: Mapped[int | None] = mapped_column(Integer)  # detached supervisor = process group id
    checkpoint: Mapped[str | None] = mapped_column(Text)  # JSON: phase, context digest, exit


class ProviderReceipt(Base):
    """Provider identity survives attempts and run pruning; never bill a replay twice."""

    __tablename__ = "provider_receipt"
    provider: Mapped[str] = mapped_column(String(80), primary_key=True)
    response_id: Mapped[str] = mapped_column(String(300), primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"))
    payload: Mapped[str] = mapped_column(Text)


class RunEvent(Base):
    """Stage changes and notes for a run (the log file holds agent output)."""

    __tablename__ = "run_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    ts: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # stage | note
    text: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------------------- Phase 3b

MESSAGE_STATUSES: tuple[str, ...] = (
    "pending_approval", "running", "done", "failed", "cancelled",
)


class ChatThread(Base):
    """One conversation with one agent. session_id is the agent's own session, resumed each turn."""

    __tablename__ = "chat_thread"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(40))
    agent_target: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(String(10), default="read")
    working_dir: Mapped[str] = mapped_column(String(500))
    session_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[int] = mapped_column(Integer)
    last_activity_at: Mapped[int] = mapped_column(Integer, index=True)


class ChatMessage(Base):
    """A user turn (with status and approval) or the agent's reply (with model and tokens)."""

    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("chat_thread.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    approval_reasons: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[int | None] = mapped_column(Integer)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"))
    model: Mapped[str | None] = mapped_column(String(120))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[int] = mapped_column(Integer)


class McpChange(Base):
    """A requested MCP add or remove. Nothing is written to an agent's config until approved."""

    __tablename__ = "mcp_change"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(10))  # add | remove
    name: Mapped[str] = mapped_column(String(64))
    spec: Mapped[str] = mapped_column(Text)  # JSON: transport, command, args, url, env_names
    status: Mapped[str] = mapped_column(String(20), index=True)  # pending | applied | failed | rejected
    output: Mapped[str | None] = mapped_column(Text)  # redacted CLI output
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer)
    decided_at: Mapped[int | None] = mapped_column(Integer)


class UsageRecord(Base):
    """One deduplicated model response; payload contains usage metadata only."""
    __tablename__ = 'usage_record'
    __table_args__ = (Index('ix_usage_record_agent_ts', 'agent', 'ts'),)
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    agent: Mapped[str] = mapped_column(String(40))
    ts: Mapped[float] = mapped_column(Float)
    session_id: Mapped[str] = mapped_column(String(160))
    payload: Mapped[str] = mapped_column(Text)


class UsageCursor(Base):
    __tablename__ = 'usage_cursor'
    path: Mapped[str] = mapped_column(Text, primary_key=True)
    offset: Mapped[int] = mapped_column(Integer)
    identity: Mapped[str] = mapped_column(String(80))
    context: Mapped[str] = mapped_column(Text)


class BillingConfig(Base):
    __tablename__ = 'billing_config'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class AuthSession(Base):
    """Opaque browser tokens are hashed at rest; no Google access/refresh/ID tokens stored."""
    __tablename__ = "auth_session"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    origin: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    method: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[int] = mapped_column(Integer, index=True)


# Phase 7: durable alerts; independent of run retention and deletion.
class AlertEvent(Base):
    __tablename__ = "alert_event"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(200), unique=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(String(1000))
    destination: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[str | None] = mapped_column(String(40))
    reviewed_at: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(300))


class AlertState(Base):
    __tablename__ = "alert_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class AgentAccess(Base):
    """Revocable, expiring Hermes capability; the secret is never returned by the API."""
    __tablename__ = "agent_access"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    agent: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(20))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)
    revoked_at: Mapped[int | None] = mapped_column(Integer)
    last_used_at: Mapped[int | None] = mapped_column(Integer)


class Project(Base):
    """Versioned project plan; execution always references an immutable approved snapshot."""
    __tablename__ = "project"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(30), default="draft")
    approved_manifest: Mapped[str | None] = mapped_column(Text)
    pipeline: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    intake_key: Mapped[str | None] = mapped_column(String(100), unique=True)


class ProjectTask(Base):
    __tablename__ = "project_task"
    card_id: Mapped[int] = mapped_column(ForeignKey("card.id", ondelete="RESTRICT"), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="RESTRICT"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    node_key: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(30))


class ProjectMemory(Base):
    """Append-only evidence/decisions; successful agent output is proposed until accepted."""
    __tablename__ = "project_memory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(255))
    card_id: Mapped[int | None] = mapped_column(Integer)
    run_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)

class UserProfile(Base):
    __tablename__ = 'user_profile'
    owner: Mapped[str] = mapped_column(String(255), primary_key=True)
    preferences: Mapped[str] = mapped_column(Text)
    discord_user_id: Mapped[str | None] = mapped_column(String(22), unique=True)
    pair_hash: Mapped[str | None] = mapped_column(String(64))
    pair_expires: Mapped[int | None] = mapped_column(Integer)

class UserCredential(Base):
    __tablename__ = 'user_credential'
    owner: Mapped[str] = mapped_column(ForeignKey('user_profile.owner'), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    hint: Mapped[str] = mapped_column(String(4))

class ProjectDelivery(Base):
    __tablename__ = 'project_delivery'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(120), unique=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('project.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    owner: Mapped[str] = mapped_column(String(255))
    destination: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    images: Mapped[str] = mapped_column(Text, default='[]')
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(String(300))


class ProviderLimit(Base):
    """One subscription limit event (Claude or Codex) and what MCD did about it.

    ``lift_at`` is parsed from the CLI's own message and is None when it was not reported. The
    event is active until it lifts, a later run on the same provider succeeds, or (when no lift
    time was reported) a few hours pass. ``rerouting`` is the operator's choice to send stories
    that have not started to an approved alternate route while the limit lasts.
    """
    __tablename__ = "provider_limit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    detected_at: Mapped[int] = mapped_column(Integer)
    last_seen_at: Mapped[int] = mapped_column(Integer)
    lift_at: Mapped[int | None] = mapped_column(Integer)
    run_id: Mapped[int | None] = mapped_column(Integer)
    rerouting: Mapped[bool] = mapped_column(Boolean, default=False)
    handoffs: Mapped[int] = mapped_column(Integer, default=0)
    rerouted: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[int | None] = mapped_column(Integer)


class MaintenanceProposal(Base):
    """A housekeeping action the coordinator proposed. It carries only finding ids frozen at proposal time; the operator's approval
    makes the app (never a model) re-verify and apply them. ``status``: pending, applied, rejected, failed."""
    __tablename__ = "maintenance_proposal"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(String(500))
    finding_ids: Mapped[str] = mapped_column(Text)  # JSON list
    status: Mapped[str] = mapped_column(String(16), index=True, default="pending")
    decided_at: Mapped[int | None] = mapped_column(Integer)
    decided_by: Mapped[str | None] = mapped_column(String(255))
    result: Mapped[str | None] = mapped_column(Text)  # JSON per-finding outcome
