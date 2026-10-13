"""Minute and day rollups plus retention, as plain SQL over the shared metric columns."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import MAX_FIELDS, METRIC_FIELDS

RAW_RETENTION_S = 24 * 3600
MINUTE_RETENTION_S = 30 * 86400
DAY_RETENTION_S = 365 * 86400
SERVICE_RETENTION_S = 7 * 86400

_COLS = ", ".join(METRIC_FIELDS)
_AVGS = ", ".join(f"AVG({f})" for f in METRIC_FIELDS)
_MAX_COLS = ", ".join(f"{f}_max" for f in MAX_FIELDS)


def _rollup(session: Session, src: str, dst: str, bucket_s: int, now: int, src_max: bool) -> int:
    """Roll complete buckets from src into dst. Returns the number of buckets written.

    Only buckets that have fully ended are rolled; a bucket already in dst is replaced, so a
    rerun after a crash is safe.
    """
    current_bucket = (now // bucket_s) * bucket_s
    last = session.execute(text(f"SELECT MAX(ts) FROM {dst}")).scalar()
    start = (last + bucket_s) if last is not None else 0
    maxes = (
        ", ".join(f"MAX({f}_max)" for f in MAX_FIELDS)
        if src_max
        else ", ".join(f"MAX({f})" for f in MAX_FIELDS)
    )
    result = session.execute(
        text(
            f"INSERT OR REPLACE INTO {dst} (ts, {_COLS}, {_MAX_COLS}) "
            f"SELECT (ts / :b) * :b AS bucket, {_AVGS}, {maxes} FROM {src} "
            f"WHERE ts >= :start AND ts < :end GROUP BY bucket"
        ),
        {"b": bucket_s, "start": start, "end": current_bucket},
    )
    return result.rowcount or 0


def roll_minutes(session: Session, now: int) -> int:
    return _rollup(session, "metric_sample", "metric_minute", 60, now, src_max=False)


def roll_days(session: Session, now: int) -> int:
    return _rollup(session, "metric_minute", "metric_day", 86400, now, src_max=True)


def apply_retention(session: Session, now: int) -> dict[str, int]:
    deleted: dict[str, int] = {}
    for table, keep in (
        ("metric_sample", RAW_RETENTION_S),
        ("metric_minute", MINUTE_RETENTION_S),
        ("metric_day", DAY_RETENTION_S),
        ("service_snapshot", SERVICE_RETENTION_S),
    ):
        res = session.execute(text(f"DELETE FROM {table} WHERE ts < :cut"), {"cut": now - keep})
        deleted[table] = res.rowcount or 0
    return deleted
