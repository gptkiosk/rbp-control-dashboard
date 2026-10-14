"""Phase 3b: chat threads and messages, MCP change requests; runs can belong to a thread.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_thread",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("agent_target", sa.String(80)),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("model", sa.String(120)),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("working_dir", sa.String(500), nullable=False),
        sa.Column("session_id", sa.String(120)),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("last_activity_at", sa.Integer, nullable=False),
    )
    op.create_index("ix_chat_thread_last_activity_at", "chat_thread", ["last_activity_at"])
    with op.batch_alter_table("run") as batch:
        batch.alter_column("card_id", existing_type=sa.Integer, nullable=True)
        batch.add_column(sa.Column("thread_id", sa.Integer, sa.ForeignKey(
            "chat_thread.id", name="fk_run_thread_id", ondelete="CASCADE")))
        batch.create_index("ix_run_thread_id", ["thread_id"])
    op.create_table(
        "chat_message",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.Integer, sa.ForeignKey("chat_thread.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approval_reasons", sa.Text),
        sa.Column("approved_at", sa.Integer),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("run.id", ondelete="SET NULL")),
        sa.Column("model", sa.String(120)),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("cost_usd", sa.Float),
        sa.Column("duration_s", sa.Float),
        sa.Column("created_at", sa.Integer, nullable=False),
    )
    op.create_index("ix_chat_message_thread_id", "chat_message", ["thread_id"])
    op.create_table(
        "mcp_change",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("spec", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("output", sa.Text),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("decided_at", sa.Integer),
    )
    op.create_index("ix_mcp_change_status", "mcp_change", ["status"])


def downgrade() -> None:
    op.drop_table("mcp_change")
    op.drop_table("chat_message")
    with op.batch_alter_table("run") as batch:
        batch.drop_index("ix_run_thread_id")
        batch.drop_column("thread_id")
        batch.alter_column("card_id", existing_type=sa.Integer, nullable=False)
    op.drop_table("chat_thread")
