"""Record each launchd job's schedule so scheduled runs are not mistaken for crash loops.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("service_snapshot") as batch:
        batch.add_column(sa.Column("run_interval_s", sa.Integer))
        batch.add_column(sa.Column("calendar", sa.Boolean))


def downgrade() -> None:
    with op.batch_alter_table("service_snapshot") as batch:
        batch.drop_column("calendar")
        batch.drop_column("run_interval_s")
