"""Phase 2: metric tables and launchd service snapshots.

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

METRIC_FIELDS = (
    "cpu_pct", "ecpu_pct", "pcpu_pct", "gpu_pct", "mem_used", "mem_total", "swap_used",
    "swap_total", "pressure_level", "disk_used", "disk_total", "net_rx_bps", "net_tx_bps",
    "cpu_temp", "gpu_temp", "sys_power", "cpu_power", "gpu_power", "ane_power", "ram_power",
    "fan_rpm",
)
MAX_FIELDS = ("cpu_pct_max", "cpu_temp_max", "sys_power_max")


def _metric_table(name: str, with_max: bool) -> None:
    cols = [sa.Column("ts", sa.Integer, primary_key=True)]
    cols += [sa.Column(f, sa.Float) for f in METRIC_FIELDS]
    if with_max:
        cols += [sa.Column(f, sa.Float) for f in MAX_FIELDS]
    op.create_table(name, *cols)


def upgrade() -> None:
    _metric_table("metric_sample", with_max=False)
    _metric_table("metric_minute", with_max=True)
    _metric_table("metric_day", with_max=True)
    op.create_table(
        "service_snapshot",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.Integer, nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False),
        sa.Column("state", sa.String(40)),
        sa.Column("pid", sa.Integer),
        sa.Column("runs", sa.Integer),
        sa.Column("last_exit", sa.String(80)),
        sa.Column("path", sa.String(500)),
        sa.Column("program", sa.String(500)),
    )
    op.create_index("ix_service_snapshot_ts", "service_snapshot", ["ts"])
    op.create_index("ix_service_snapshot_label_ts", "service_snapshot", ["label", "ts"])


def downgrade() -> None:
    op.drop_table("service_snapshot")
    for name in ("metric_day", "metric_minute", "metric_sample"):
        op.drop_table(name)
