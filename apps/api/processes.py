"""Top processes grouped by app, the way Activity Monitor users think about them."""

from __future__ import annotations

import psutil


def app_name(exe: str | None, name: str | None) -> str:
    """"/Applications/Google Chrome.app/.../Helper" -> "Google Chrome"; otherwise the process name."""
    if exe and ".app/" in exe:
        head = exe.split(".app/", 1)[0]
        return head.rsplit("/", 1)[-1]
    return name or "unknown"


def group(rows: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    """Sum CPU and memory per app. Rows need app, cpu_pct, rss."""
    groups: dict[str, dict[str, object]] = {}
    for row in rows:
        g = groups.setdefault(str(row["app"]), {"app": row["app"], "cpu_pct": 0.0, "rss": 0, "count": 0})
        g["cpu_pct"] = float(g["cpu_pct"]) + float(row.get("cpu_pct") or 0.0)
        g["rss"] = int(g["rss"]) + int(row.get("rss") or 0)
        g["count"] = int(g["count"]) + 1
    ranked = sorted(groups.values(), key=lambda g: int(g["rss"]), reverse=True)
    for g in ranked:
        g["cpu_pct"] = round(float(g["cpu_pct"]), 1)
    return ranked[:limit]


class ProcessSampler:
    """psutil needs two readings per process for CPU %; keep Process objects between calls."""

    def __init__(self) -> None:
        self._procs: dict[int, psutil.Process] = {}

    def sample(self, limit: int = 15) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        seen: set[int] = set()
        for proc in psutil.process_iter(["pid", "name", "exe", "memory_info"]):
            pid = proc.info["pid"]
            seen.add(pid)
            tracked = self._procs.setdefault(pid, proc)
            try:
                cpu = tracked.cpu_percent(None)
            except (psutil.Error, OSError):
                cpu = 0.0
            mem = proc.info.get("memory_info")
            rows.append(
                {
                    "app": app_name(proc.info.get("exe"), proc.info.get("name")),
                    "cpu_pct": cpu,
                    "rss": mem.rss if mem else 0,
                }
            )
        for gone in set(self._procs) - seen:
            del self._procs[gone]
        return group(rows, limit)
