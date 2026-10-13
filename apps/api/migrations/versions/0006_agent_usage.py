"""Durable, privacy-minimized usage telemetry and billing preferences."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "usage_record",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("ts", sa.Float, nullable=False),
        sa.Column("session_id", sa.String(160), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
    )
    op.create_index("ix_usage_record_agent_ts", "usage_record", ["agent", "ts"])
    op.create_table(
        "usage_cursor",
        sa.Column("path", sa.Text, primary_key=True),
        sa.Column("offset", sa.Integer, nullable=False),
        sa.Column("identity", sa.String(80), nullable=False),
        sa.Column("context", sa.Text, nullable=False),
    )
    op.create_table(
        "billing_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("payload", sa.Text, nullable=False),
    )
    with op.batch_alter_table("run") as b:
        b.add_column(sa.Column("cached_input_tokens", sa.Integer))
        b.add_column(sa.Column("cache_write_tokens", sa.Integer))


def downgrade():
    with op.batch_alter_table("run") as b:
        b.drop_column("cache_write_tokens")
        b.drop_column("cached_input_tokens")
    for t in ["billing_config", "usage_cursor", "usage_record"]:
        op.drop_table(t)
