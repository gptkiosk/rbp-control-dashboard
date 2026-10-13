"""Human tasks, priority, due date, estimate, tags, definition of done, and dependencies.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("card") as batch:
        batch.add_column(sa.Column("assignee_type", sa.String(10), nullable=False, server_default="agent"))
        batch.alter_column("agent", existing_type=sa.String(40), nullable=True)
        batch.alter_column("working_dir", existing_type=sa.String(500), nullable=True)
        batch.add_column(sa.Column("priority", sa.String(10), nullable=False, server_default="normal"))
        batch.add_column(sa.Column("due_date", sa.String(10)))
        batch.add_column(sa.Column("estimate_minutes", sa.Integer))
        batch.add_column(sa.Column("tags", sa.Text))
        batch.add_column(sa.Column("acceptance", sa.Text))
    op.create_table(
        "card_dependency",
        sa.Column("card_id", sa.Integer, sa.ForeignKey("card.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("depends_on_id", sa.Integer, sa.ForeignKey("card.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_card_dependency_depends_on_id", "card_dependency", ["depends_on_id"])


def downgrade() -> None:
    op.drop_table("card_dependency")
    with op.batch_alter_table("card") as batch:
        for col in ("acceptance", "tags", "estimate_minutes", "due_date", "priority", "assignee_type"):
            batch.drop_column(col)
