"""Remember GitHub issue tasks so Discord and dashboard submissions are idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "issue_task",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo", sa.String(length=140), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint("repo", "number", name="uq_issue_task_issue"),
    )


def downgrade():
    op.drop_table("issue_task")
