"""Additions to a repository's standards that the coordinator proposed, waiting for the operator's decision."""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "standards_proposal",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=False),
        sa.Column("base_sha256", sa.String(length=64), nullable=False),
        sa.Column("patch", sa.Text(), nullable=False),
        sa.Column("new_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
    )
    op.create_index("ix_standards_proposal_project_id", "standards_proposal", ["project_id"])
    op.create_index("ix_standards_proposal_status", "standards_proposal", ["status"])


def downgrade():
    op.drop_index("ix_standards_proposal_status", table_name="standards_proposal")
    op.drop_index("ix_standards_proposal_project_id", table_name="standards_proposal")
    op.drop_table("standards_proposal")
