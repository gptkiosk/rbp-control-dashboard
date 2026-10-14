"""Phase 3: task board cards, agent runs and run events.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("agent_target", sa.String(80)),
        sa.Column("model", sa.String(120)),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("working_dir", sa.String(500), nullable=False),
        sa.Column("column", sa.String(20), nullable=False),
        sa.Column("position", sa.Float, nullable=False),
        sa.Column("timeout_s", sa.Integer, nullable=False),
        sa.Column("budget_usd", sa.Float),
        sa.Column("needs_approval", sa.Boolean, nullable=False),
        sa.Column("approval_reasons", sa.Text),
        sa.Column("approved_at", sa.Integer),
        sa.Column("created_by", sa.String(20), nullable=False),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )
    op.create_index("ix_card_column", "card", ["column"])
    op.create_table(
        "run",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("card_id", sa.Integer, sa.ForeignKey("card.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("model_requested", sa.String(120)),
        sa.Column("model_reported", sa.String(120)),
        sa.Column("provider", sa.String(80)),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("started_at", sa.Integer, nullable=False),
        sa.Column("ended_at", sa.Integer),
        sa.Column("duration_s", sa.Float),
        sa.Column("exit_code", sa.Integer),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("cost_usd", sa.Float),
        sa.Column("session_id", sa.String(120)),
        sa.Column("working_dir", sa.String(500), nullable=False),
        sa.Column("command", sa.Text, nullable=False),
        sa.Column("log_path", sa.String(500), nullable=False),
        sa.Column("result_text", sa.Text),
        sa.Column("error", sa.Text),
    )
    for col in ("card_id", "agent", "stage", "started_at"):
        op.create_index(f"ix_run_{col}", "run", [col])
    op.create_table(
        "run_event",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
    )
    op.create_index("ix_run_event_run_id", "run_event", ["run_id"])


def downgrade() -> None:
    op.drop_table("run_event")
    op.drop_table("run")
    op.drop_table("card")
