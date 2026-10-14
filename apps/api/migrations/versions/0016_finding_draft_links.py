"""Link Ops report findings to deduplicated task drafts."""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "finding_draft_link",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("finding_id", sa.String(length=40), nullable=False),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("card.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint("finding_id", name="uq_finding_draft_finding"),
        sa.UniqueConstraint("card_id"),
    )
    op.create_index("ix_finding_draft_link_report_id", "finding_draft_link", ["report_id"])


def downgrade():
    op.drop_index("ix_finding_draft_link_report_id", table_name="finding_draft_link")
    op.drop_table("finding_draft_link")
