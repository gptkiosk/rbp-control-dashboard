"""Linux and Raspberry Pi host collectors."""

from __future__ import annotations

import asyncio
import glob
import time
from pathlib import Path

import psutil

import facts
import sampling
import services_probe
from processes import ProcessSampler
from .base import Record, Runner


class LinuxPlatform:
    name = "linux"

    def __init__(self, *, disk_path: str, run: Runner, clock=time.time, **_ignored: object) -> None:
        self.disk_path, self.run, self.clock = disk_path, run, clock
        self.metrics_status = "starting"
        self._net_prev: tuple[float, int, int] | None = None

    async def stop(self) -> None:
        return None

    def make_process_sampler(self) -> ProcessSampler:
        # psutil handles the different Linux process layouts; the sampler's app
        # grouping deliberately falls back from macOS .app bundles to process name.
        return ProcessSampler()

    def _temperature(self) -> float | None:
        values = []
        for name in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
            try:
                value = float(Path(name).read_text().strip())
                values.append(value / 1000 if value > 1000 else value)
            except (OSError, ValueError):
                continue
        return round(max(values), 2) if values else None

    async def _throttling(self) -> dict[str, object]:
        code, out = await self.run("vcgencmd", "get_throttled")
        flags = sampling.parse_vcgencmd_throttled(out) if code == 0 else []
        return {"throttled": any(not flag.startswith("previously_") for flag in flags),
                "throttle_flags": flags}

    async def system_extras(self) -> dict[str, float | None]:
        memory, swap = psutil.virtual_memory(), psutil.swap_memory()
        try:
            proc_memory = sampling.parse_proc_meminfo(Path("/proc/meminfo").read_text())
            mem_total = float(proc_memory.get("MemTotal", memory.total))
            mem_used = float(mem_total - proc_memory.get("MemAvailable", memory.available))
        except OSError:
            mem_total, mem_used = float(memory.total), float(memory.total - memory.available)
        disk, net = psutil.disk_usage(self.disk_path), psutil.net_io_counters()
        now = (self.clock(), net.bytes_recv, net.bytes_sent)
        rx, tx = sampling.net_rates(self._net_prev, now)
        self._net_prev = now
        # MemAvailable is the kernel's estimate of reclaimable memory; psutil
        # remains the fallback for constrained containers without procfs.
        return {"mem_used": mem_used, "mem_total": mem_total,
                "swap_used": float(swap.used), "swap_total": float(swap.total),
                "disk_used": float(disk.used), "disk_total": float(disk.total),
                "net_rx_bps": rx, "net_tx_bps": tx}

    async def collect_metrics(self, record: Record, interval_s: int) -> None:
        self.metrics_status = "running"
        while True:
            health = await self._throttling()
            await record({"cpu_pct": psutil.cpu_percent(None), "cpu_temp": self._temperature()}, health)
            await asyncio.sleep(interval_s)

    async def snapshot_services(self, prefixes: tuple[str, ...]) -> list[dict[str, object]]:
        code, listing = await self.run("systemctl", "--user", "list-units", "--all", "--no-legend", "--plain")
        if code:
            return []
        rows: list[dict[str, object]] = []
        for label in services_probe.parse_systemctl_list(listing, prefixes):
            code, out = await self.run("systemctl", "--user", "show", label,
                                       "--property=Id,ActiveState,MainPID,NRestarts,ExecMainStatus,FragmentPath,ExecStart")
            if not code:
                rows.append({"label": label, "domain": "user", **services_probe.parse_systemctl_show(out)})
        return rows

    async def refresh_updates(self) -> dict[str, object]:
        code, out = await self.run("apt", "list", "--upgradable", timeout=180)
        return ({"updates": facts.parse_apt_updates(out)} if code == 0
                else {"error": f"apt list --upgradable failed (exit {code})"})
