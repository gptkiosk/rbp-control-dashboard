"""Record subscription limit events, their lift time and the operator's reroute choice."""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "provider_limit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("detected_at", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.Integer(), nullable=False),
        sa.Column("lift_at", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("rerouting", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("handoffs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rerouted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_at", sa.Integer(), nullable=True),
    )
    op.create_index("ix_provider_limit_provider", "provider_limit", ["provider"])


def downgrade():
    op.drop_index("ix_provider_limit_provider", table_name="provider_limit")
    op.drop_table("provider_limit")
