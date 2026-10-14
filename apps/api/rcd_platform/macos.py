"""macOS collection implementation; behavior intentionally matches MCD."""

from __future__ import annotations

import asyncio
import logging
import os
import time

import psutil

import facts
import sampling
import services_probe
from processes import ProcessSampler
from .base import Record, Runner

logger = logging.getLogger("mac_control.platform.macos")


class MacOSPlatform:
    name = "macos"

    def __init__(self, *, macmon_path: str, disk_path: str, run: Runner, clock=time.time) -> None:
        self.macmon_path, self.disk_path, self.run, self.clock = macmon_path, disk_path, run, clock
        self.metrics_status = "starting"
        self._net_prev: tuple[float, int, int] | None = None
        self._macmon: asyncio.subprocess.Process | None = None

    async def stop(self) -> None:
        if self._macmon and self._macmon.returncode is None:
            self._macmon.terminate()
            try:
                await asyncio.wait_for(self._macmon.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._macmon.kill()

    def make_process_sampler(self) -> ProcessSampler:
        return ProcessSampler()

    async def system_extras(self) -> dict[str, float | None]:
        _, vm_text = await self.run("vm_stat")
        _, pressure_text = await self.run("sysctl", "-n", "kern.memorystatus_vm_pressure_level")
        disk, net = psutil.disk_usage(self.disk_path), psutil.net_io_counters()
        now = (self.clock(), net.bytes_recv, net.bytes_sent)
        rx, tx = sampling.net_rates(self._net_prev, now)
        self._net_prev = now
        return {"mem_used": sampling.memory_used_bytes(sampling.parse_vm_stat(vm_text)),
                "pressure_level": sampling.parse_pressure_level(pressure_text),
                "disk_used": float(disk.used), "disk_total": float(disk.total),
                "net_rx_bps": rx, "net_tx_bps": tx}

    async def collect_metrics(self, record: Record, interval_s: int) -> None:
        backoff = 5
        while True:
            try:
                self._macmon = await asyncio.create_subprocess_exec(
                    self.macmon_path, "pipe", "-i", str(interval_s * 1000),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            except FileNotFoundError:
                self.metrics_status = "missing"
                logger.warning("macmon not found at %s; collecting without power/temperature", self.macmon_path)
                while True:
                    await record({"cpu_pct": psutil.cpu_percent(None)}, None)
                    await asyncio.sleep(interval_s)
            self.metrics_status = "running"
            assert self._macmon.stdout is not None
            async for raw in self._macmon.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    try:
                        await record(sampling.parse_macmon(line), None)
                        backoff = 5
                    except Exception:  # one bad line or DB hiccup must not stop collection
                        logger.exception("failed to record sample")
            code = await self._macmon.wait()
            self.metrics_status = "restarting"
            logger.warning("macmon exited with %s; restarting in %ss", code, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

    async def snapshot_services(self, prefixes: tuple[str, ...]) -> list[dict[str, object]]:
        code, listing = await self.run("launchctl", "list")
        if code:
            return []
        uid, rows = os.getuid(), []
        for label in services_probe.parse_launchctl_list(listing, prefixes):
            code, printed = await self.run("launchctl", "print", f"gui/{uid}/{label}")
            if not code:
                rows.append({"label": label, "domain": "gui", **services_probe.parse_launchctl_print(printed)})
        return rows

    async def refresh_updates(self) -> dict[str, object]:
        code, out = await self.run("softwareupdate", "-l", timeout=180)
        return ({"updates": facts.parse_softwareupdate(out)} if code == 0
                else {"error": f"softwareupdate failed (exit {code})"})
