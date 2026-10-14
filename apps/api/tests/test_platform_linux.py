"""Linux-only behavior is exercised on Linux CI/Pi, not on macOS parity runs."""

from __future__ import annotations

import asyncio
import sys

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux platform collector")

from rcd_platform.linux import LinuxPlatform


async def _run(*argv: str, timeout: float = 30.0) -> tuple[int, str]:
    command = " ".join(argv)
    if "list-units" in command:
        return 0, "ai.hermes.gateway.service loaded active running Hermes\n"
    if " show " in f" {command} ":
        return 0, "ActiveState=failed\nMainPID=0\nNRestarts=51\nExecMainStatus=2\n"
    if "get_throttled" in command:
        return 0, "throttled=0x4\n"
    return 1, ""


def test_systemd_user_snapshot_and_throttle_flags():
    platform = LinuxPlatform(disk_path="/", run=_run, clock=lambda: 1.0)
    rows = asyncio.run(platform.snapshot_services(("ai.hermes.",)))
    assert rows == [{
        "label": "ai.hermes.gateway.service", "domain": "user", "state": "failed", "pid": None,
        "runs": 51, "last_exit": "2", "path": None, "program": None,
        "run_interval_s": None, "calendar": False,
    }]
    health = asyncio.run(platform._throttling())
    assert health == {"throttled": True, "throttle_flags": ["throttled"]}
