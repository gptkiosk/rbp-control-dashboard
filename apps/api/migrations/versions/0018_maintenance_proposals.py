"""Housekeeping proposals: findings the coordinator proposed to resolve, waiting for the operator's decision."""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "maintenance_proposal",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("finding_ids", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
    )
    op.create_index("ix_maintenance_proposal_status", "maintenance_proposal", ["status"])


def downgrade():
    op.drop_index("ix_maintenance_proposal_status", table_name="maintenance_proposal")
    op.drop_table("maintenance_proposal")
