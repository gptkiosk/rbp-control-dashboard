"""Which accepted bug-report issues already became tasks."""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "bug_intake",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo", sa.String(length=140), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("urgency", sa.String(length=12), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint("repo", "number", name="uq_bug_intake_issue"),
    )


def downgrade():
    op.drop_table("bug_intake")
