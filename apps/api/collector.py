"""Background collector for platform metrics, services, VPN, and pending updates.

Runs inside the API process (started from the FastAPI lifespan). Each loop is independent
so a failure in one source never stops the others. All subprocess calls go through
`self.run`, which tests replace, so tests never spawn host commands.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import psutil
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

import facts
import rollups
import subagents
from models import METRIC_FIELDS, MetricSample, ServiceSnapshot
from platform import Platform, current_platform

logger = logging.getLogger("mac_control.collector")

Runner = Callable[..., Awaitable[tuple[int, str]]]


async def run_command(*argv: str, timeout: float = 30.0, input_data: bytes | None = None) -> tuple[int, str]:
    """Run a command and return (returncode, stdout). Never raises for a missing binary."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return 127, ""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(input_data), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, ""
    return proc.returncode or 0, out.decode("utf-8", "replace")


class Collector:
    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        macmon_path: str,
        tailscale_path: str,
        disk_path: str,
        service_prefixes: tuple[str, ...],
        sample_interval_s: int = 10,
        run: Runner = run_command,
        clock: Callable[[], float] = time.time,
        platform: Platform | None = None,
    ) -> None:
        self.sessions = session_factory
        self.tailscale_path = tailscale_path
        self.prefixes = service_prefixes
        self.interval = sample_interval_s
        self.run = run
        self.clock = clock

        self.latest: dict[str, Any] | None = None
        self.processes: list[dict[str, object]] = []
        self.tailscale: dict[str, Any] | None = None
        self.updates: dict[str, Any] | None = None
        self.subagents: dict[str, Any] | None = None
        self.agent_binaries: dict[str, str] = {}
        from usage import UsageScanner
        self.usage_scanner = UsageScanner(self.sessions)
        from openrouter_costs import OpenRouterCosts
        self.openrouter_costs = OpenRouterCosts()
        self.platform = platform or current_platform(
            macmon_path=macmon_path, disk_path=disk_path, run=run, clock=clock
        )
        # Kept for the existing macOS API/UI contract. Linux reports its collector
        # state here too, while `platform` identifies which collector supplied it.
        self.macmon_status = self.platform.metrics_status

        self._proc_sampler = self.platform.make_process_sampler()
        self._tasks: list[asyncio.Task] = []
        self.platform_health: dict[str, object] = {}

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        loops = (self._metrics_loop, self._services_loop, self._tailscale_loop,
                 self._updates_loop, self._maintenance_loop, self._subagents_loop, self._usage_loop, self._openrouter_loop)
        self._tasks = [asyncio.create_task(loop(), name=loop.__name__) for loop in loops]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.platform.stop()

    # ------------------------------------------------------------------ metrics

    async def system_extras(self) -> dict[str, float | None]:
        """Memory, disk, and network fields supplied by the active platform."""
        return await self.platform.system_extras()

    async def record(self, values: dict[str, float | None], health: dict[str, object] | None = None) -> dict[str, Any]:
        """Store one platform reading and refresh the portable process sampler."""
        row: dict[str, Any] = {field: None for field in METRIC_FIELDS}
        row.update(values)
        row.update(await self.system_extras())
        if row.get("mem_total") is None:
            row["mem_total"] = float(psutil.virtual_memory().total)
        row["ts"] = int(self.clock())
        await asyncio.to_thread(self._insert_sample, row)
        self.processes = await asyncio.to_thread(self._proc_sampler.sample, 15)
        self.latest = row
        self.platform_health = health or {}
        self.macmon_status = self.platform.metrics_status
        return row

    def _insert_sample(self, row: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.execute(insert(MetricSample).prefix_with("OR REPLACE"), [row])

    async def _metrics_loop(self) -> None:
        try:
            await self.platform.collect_metrics(self.record, self.interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("platform metrics collector failed")

    # ------------------------------------------------------------------ services

    async def snapshot_services(self) -> list[dict[str, Any]]:
        snapshots = await self.platform.snapshot_services(self.prefixes)
        ts = int(self.clock())
        rows: list[dict[str, Any]] = [{"ts": ts, **row} for row in snapshots]
        if rows:
            await asyncio.to_thread(self._insert_services, rows)
        return rows

    def _insert_services(self, rows: list[dict[str, Any]]) -> None:
        with self.sessions.begin() as session:
            session.execute(insert(ServiceSnapshot), rows)

    async def _services_loop(self) -> None:
        while True:
            try:
                await self.snapshot_services()
            except Exception:
                logger.exception("service snapshot failed")
            await asyncio.sleep(60)

    # ------------------------------------------------------------------ facts

    async def refresh_tailscale(self) -> None:
        code, out = await self.run(self.tailscale_path, "status", "--json")
        if code == 0 and out.strip():
            self.tailscale = {**facts.parse_tailscale(out), "checked_at": int(self.clock())}
        else:
            self.tailscale = {"error": f"tailscale status failed (exit {code})",
                              "checked_at": int(self.clock())}

    async def refresh_updates(self) -> None:
        self.updates = {**await self.platform.refresh_updates(), "checked_at": int(self.clock())}

    async def _tailscale_loop(self) -> None:
        while True:
            try:
                await self.refresh_tailscale()
            except Exception:
                logger.exception("tailscale refresh failed")
            await asyncio.sleep(60)

    async def _updates_loop(self) -> None:
        while True:
            try:
                await self.refresh_updates()
            except Exception:
                logger.exception("update check failed")
            await asyncio.sleep(6 * 3600)

    # ------------------------------------------------------------------ sub-agents

    async def refresh_subagents(self) -> None:
        if self.agent_binaries:
            self.subagents = await subagents.snapshot(self.run, self.agent_binaries)

    async def _subagents_loop(self) -> None:
        while True:
            try:
                await self.refresh_subagents()
            except Exception:
                logger.exception("sub-agent refresh failed")
            await asyncio.sleep(60)

    async def _usage_loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.usage_scanner.scan)
            except Exception:
                logger.exception("usage indexing failed")
            await asyncio.sleep(15)

    async def _openrouter_loop(self) -> None:
        while True:
            await asyncio.to_thread(self.openrouter_costs.refresh)
            await asyncio.sleep(60)

    # ------------------------------------------------------------------ maintenance

    def maintain(self, now: int, full: bool) -> None:
        """Roll minutes every call; roll days and apply retention when `full`."""
        with self.sessions.begin() as session:
            rollups.roll_minutes(session, now)
            if full:
                rollups.roll_days(session, now)
                rollups.apply_retention(session, now)

    async def _maintenance_loop(self) -> None:
        ticks = 0
        while True:
            await asyncio.sleep(60)
            ticks += 1
            try:
                await asyncio.to_thread(self.maintain, int(self.clock()), ticks % 60 == 0)
            except Exception:
                logger.exception("maintenance failed")
