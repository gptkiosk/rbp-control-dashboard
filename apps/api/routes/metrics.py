"""Mac metrics: the latest reading and time series for charts."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from deps import get_collector, get_session
from models import MAX_FIELDS, METRIC_FIELDS, MetricSample
from sampling import PRESSURE_LABELS

router = APIRouter(prefix="/api/metrics")

RangeName = Literal["1h", "24h", "7d", "30d", "1y"]

# range -> (table, window seconds, bucket seconds)
RANGES: dict[str, tuple[str, int, int]] = {
    "1h": ("metric_sample", 3600, 10),
    "24h": ("metric_minute", 86400, 60),
    "7d": ("metric_minute", 7 * 86400, 600),
    "30d": ("metric_minute", 30 * 86400, 3600),
    "1y": ("metric_day", 365 * 86400, 86400),
}


def _pct(used: float | None, total: float | None) -> float | None:
    if used is None or not total:
        return None
    return round(100.0 * used / total, 1)


def disk_days_to_full(session: Session, now: int) -> float | None:
    """Days until the data volume fills, from the last 7 days of hourly disk usage.

    Least-squares slope over hourly averages; None when usage is flat or shrinking or there
    is less than a day of history.
    """
    rows = session.execute(
        text(
            "SELECT (ts / 3600) * 3600 AS h, AVG(disk_used), AVG(disk_total) FROM metric_minute "
            "WHERE ts >= :since AND disk_used IS NOT NULL GROUP BY h ORDER BY h"
        ),
        {"since": now - 7 * 86400},
    ).all()
    if len(rows) < 24:
        return None
    xs = [float(r[0]) for r in rows]
    ys = [float(r[1]) for r in rows]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom  # bytes per second
    if slope <= 0:
        return None
    free = float(rows[-1][2]) - ys[-1]
    return round(free / slope / 86400, 1)


@router.get("/current")
def current(session: Session = Depends(get_session), collector=Depends(get_collector)):
    row = collector.latest if collector else None
    if row is None:
        sample = session.execute(
            select(MetricSample).order_by(MetricSample.ts.desc()).limit(1)
        ).scalar_one_or_none()
        if sample is None:
            raise HTTPException(status_code=503, detail="No samples yet; the collector starts within 10 s.")
        row = {f: getattr(sample, f) for f in ("ts", *METRIC_FIELDS)}
    now = int(time.time())
    level = row.get("pressure_level")
    return {
        **row,
        "platform": collector.platform.name if collector else None,
        **(collector.platform_health if collector else {}),
        "sample_age_s": now - int(row["ts"]),
        "mem_used_pct": _pct(row.get("mem_used"), row.get("mem_total")),
        "swap_used_pct": _pct(row.get("swap_used"), row.get("swap_total")),
        "disk_used_pct": _pct(row.get("disk_used"), row.get("disk_total")),
        "pressure_label": PRESSURE_LABELS.get(int(level)) if level is not None else None,
        "disk_days_to_full": disk_days_to_full(session, now),
        "macmon_status": collector.macmon_status if collector else "disabled",
    }


@router.get("/series")
def series(
    range: RangeName = Query("1h"),  # noqa: A002 - public query parameter name
    fields: str = Query("cpu_pct,gpu_pct"),
    session: Session = Depends(get_session),
):
    requested = [f.strip() for f in fields.split(",") if f.strip()]
    allowed = set(METRIC_FIELDS) | {f"{f}_max" for f in MAX_FIELDS}
    bad = [f for f in requested if f not in allowed]
    if bad or not requested:
        raise HTTPException(status_code=422, detail=f"unknown fields: {bad or 'none given'}")
    table, window, bucket = RANGES[range]
    if table == "metric_sample" and any(f.endswith("_max") for f in requested):
        raise HTTPException(status_code=422, detail="_max fields exist only for 24h and longer")

    now = int(time.time())
    agg = ", ".join(
        (f"MAX({f})" if f.endswith("_max") else f"AVG({f})") for f in requested
    )
    rows = session.execute(
        text(
            f"SELECT (ts / :b) * :b AS bucket, {agg} FROM {table} "
            f"WHERE ts >= :since GROUP BY bucket ORDER BY bucket"
        ),
        {"b": bucket, "since": now - window},
    ).all()
    out: dict[str, list] = {"ts": [r[0] for r in rows]}
    for i, f in enumerate(requested, start=1):
        out[f] = [None if r[i] is None else round(float(r[i]), 3) for r in rows]
    return {"range": range, "step_s": bucket, "series": out}
