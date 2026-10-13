from __future__ import annotations

import asyncio

from sqlalchemy import text

from collector import Collector
from platform.macos import MacOSPlatform
from tests.test_facts import SOFTWAREUPDATE, TAILSCALE
from tests.test_sampling import VM_STAT

LIST = "PID\tStatus\tLabel\n10\t0\tai.hermes.gateway\n-\t0\tcom.apple.x\n"
PRINT = "gui/501/ai.hermes.gateway = {\n\tstate = running\n\truns = 3\n\tpid = 10\n\tlast exit code = 0\n}\n"


def _fake_runner(responses):
    async def run(*argv, timeout=30.0):
        key = " ".join(argv[:2])
        for prefix, out in responses.items():
            if key.startswith(prefix) or argv[0].endswith(prefix):
                return 0, out
        return 1, ""
    return run


def _collector(sessions, responses):
    run = _fake_runner(responses)
    return Collector(
        sessions, macmon_path="macmon", tailscale_path="tailscale", disk_path="/",
        service_prefixes=("ai.hermes."), run=run, clock=lambda: 1_800_000_000.0,
        platform=MacOSPlatform(macmon_path="macmon", disk_path="/", run=run, clock=lambda: 1_800_000_000.0),
    )


def test_record_merges_macmon_and_extras(sessions):
    c = _collector(sessions, {"vm_stat": VM_STAT, "sysctl -n": "1\n"})
    row = asyncio.run(c.record({"cpu_pct": 12.0, "sys_power": 4.0}))
    assert row["cpu_pct"] == 12.0
    assert row["pressure_level"] == 1.0
    assert row["mem_used"] > 0 and row["disk_total"] > 0
    with sessions() as s:
        assert s.execute(text("SELECT cpu_pct FROM metric_sample")).scalar() == 12.0
    assert isinstance(c.processes, list)


def test_snapshot_services_inserts_rows(sessions):
    c = _collector(sessions, {"launchctl list": LIST, "launchctl print": PRINT})
    rows = asyncio.run(c.snapshot_services())
    assert [r["label"] for r in rows] == ["ai.hermes.gateway"]
    assert rows[0]["runs"] == 3
    with sessions() as s:
        assert s.execute(text("SELECT COUNT(*) FROM service_snapshot")).scalar() == 1


def test_tailscale_and_updates_refresh(sessions):
    c = _collector(sessions, {"tailscale": TAILSCALE, "softwareupdate": SOFTWAREUPDATE})
    asyncio.run(c.refresh_tailscale())
    asyncio.run(c.refresh_updates())
    assert c.tailscale["backend_state"] == "Running"
    assert c.updates["updates"][0]["requires_restart"] is True


def test_tailscale_failure_is_reported_not_raised(sessions):
    c = _collector(sessions, {})
    asyncio.run(c.refresh_tailscale())
    assert "error" in c.tailscale
