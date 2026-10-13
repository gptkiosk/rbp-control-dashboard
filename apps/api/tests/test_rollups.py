from __future__ import annotations

from sqlalchemy import insert, select, text

import rollups
from models import MetricMinute, MetricSample


def _samples(session, start, n, cpu):
    rows = [{"ts": start + i * 10, "cpu_pct": cpu + i, "cpu_temp": 40.0 + i, "sys_power": 5.0}
            for i in range(n)]
    session.execute(insert(MetricSample), rows)


def test_minute_rollup_averages_and_maxes(sessions):
    t0 = 1_800_000_000 - (1_800_000_000 % 60)  # minute-aligned
    with sessions.begin() as s:
        _samples(s, t0, 6, cpu=10.0)  # one full minute: cpu 10..15
        _samples(s, t0 + 60, 3, cpu=50.0)  # next minute, still open at `now`
        written = rollups.roll_minutes(s, now=t0 + 90)
    assert written == 1
    with sessions() as s:
        row = s.execute(select(MetricMinute)).scalar_one()
    assert row.ts == t0
    assert row.cpu_pct == 12.5
    assert row.cpu_pct_max == 15.0
    assert row.cpu_temp_max == 45.0


def test_minute_rollup_is_idempotent(sessions):
    t0 = 1_800_000_000 - (1_800_000_000 % 60)
    with sessions.begin() as s:
        _samples(s, t0, 6, cpu=10.0)
        rollups.roll_minutes(s, now=t0 + 120)
        rollups.roll_minutes(s, now=t0 + 120)
    with sessions() as s:
        assert s.execute(text("SELECT COUNT(*) FROM metric_minute")).scalar() == 1


def test_day_rollup_from_minutes(sessions):
    day = 1_800_000_000 - (1_800_000_000 % 86400)
    with sessions.begin() as s:
        s.execute(insert(MetricMinute), [
            {"ts": day + 60, "cpu_pct": 10.0, "cpu_pct_max": 30.0},
            {"ts": day + 120, "cpu_pct": 20.0, "cpu_pct_max": 90.0},
        ])
        assert rollups.roll_days(s, now=day + 86400 + 5) == 1
        row = s.execute(text("SELECT cpu_pct, cpu_pct_max FROM metric_day")).one()
    assert row == (15.0, 90.0)


def test_retention_deletes_only_expired(sessions):
    now = 1_800_000_000
    with sessions.begin() as s:
        s.execute(insert(MetricSample), [
            {"ts": now - rollups.RAW_RETENTION_S - 1, "cpu_pct": 1.0},
            {"ts": now - rollups.RAW_RETENTION_S + 1, "cpu_pct": 2.0},
        ])
        deleted = rollups.apply_retention(s, now)
    assert deleted["metric_sample"] == 1
    with sessions() as s:
        assert s.execute(text("SELECT cpu_pct FROM metric_sample")).scalars().all() == [2.0]
