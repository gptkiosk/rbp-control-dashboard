"""Process-tree and cgroup measurement from /proc and /sys/fs/cgroup (Linux only).

On non-Linux hosts (developer Macs) the sampler yields no samples and values are reported
as null; the harness never substitutes estimates.
"""
from __future__ import annotations

import os
from pathlib import Path
import resource
import threading
import time

from .stats import median

PROC = Path("/proc")
CGROUP_ROOT = Path("/sys/fs/cgroup")


def _read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def have_proc():
    return (PROC / "self/status").exists()


def _children_map():
    tree = {}
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        stat = _read(entry / "stat")
        if not stat:
            continue
        # comm may contain spaces/parens: split after the last ')'.
        rest = stat[stat.rfind(")") + 2:].split()
        tree.setdefault(int(rest[1]), []).append(int(entry.name))
    return tree


def descendants(pid):
    tree, out, stack = _children_map(), [], [pid]
    while stack:
        for child in tree.get(stack.pop(), []):
            out.append(child)
            stack.append(child)
    return out


def rss_kb(pid):
    """(VmRSS, VmHWM) in kB, or None if the process is gone."""
    status = _read(PROC / str(pid) / "status")
    if not status:
        return None
    values = {}
    for line in status.splitlines():
        if line.startswith(("VmRSS:", "VmHWM:")):
            values[line.split(":")[0]] = int(line.split()[1])
    return values.get("VmRSS", 0), values.get("VmHWM", 0)


def tree_rss_kb(pids):
    total = hwm = 0
    for pid in pids:
        value = rss_kb(pid)
        if value:
            total += value[0]
            hwm += value[1]
    return total, hwm


def cgroup_dir(pid="self"):
    text = _read(PROC / str(pid) / "cgroup")
    if not text:
        return None
    for line in text.splitlines():
        if line.startswith("0::"):
            path = CGROUP_ROOT / line[3:].lstrip("/")
            return path if path.is_dir() else None
    return None


def cgroup_stat(cg):
    """memory.peak / memory.current in bytes and cpu usage in usec; missing files -> None."""
    out = {"memory_peak_bytes": None, "memory_current_bytes": None, "cpu_usage_usec": None}
    if cg is None:
        return out
    for key, name in (("memory_peak_bytes", "memory.peak"), ("memory_current_bytes", "memory.current")):
        text = _read(cg / name)
        if text and text.strip().isdigit():
            out[key] = int(text)
    for line in (_read(cg / "cpu.stat") or "").splitlines():
        if line.startswith("usage_usec"):
            out["cpu_usage_usec"] = int(line.split()[1])
    return out


def reset_cgroup_peak(cg):
    """Kernel >= 6.12 lets you reset memory.peak by writing to it. Returns True if it worked."""
    try:
        (cg / "memory.peak").write_text("0")
        return True
    except OSError:
        return False


def cpu_seconds():
    """(self, reaped children) CPU seconds; children covers adapter-spawned runtimes once waited."""
    me, kids = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return me.ru_utime + me.ru_stime, kids.ru_utime + kids.ru_stime


class TreeSampler:
    """Samples summed RSS of all descendants of `root_pid` (the runtime processes) every `interval` s."""

    def __init__(self, root_pid=None, interval=0.1):
        self.root, self.interval = root_pid or os.getpid(), interval
        self.samples = []  # (monotonic t, rss_kb, hwm_kb, n_procs)
        self._stop = threading.Event()
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            pids = descendants(self.root)
            rss, hwm = tree_rss_kb(pids)
            self.samples.append((time.monotonic(), rss, hwm, len(pids)))
            self._stop.wait(self.interval)

    def start(self):
        if have_proc():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    def window(self, t0=0, t1=float("inf")):
        return [s for s in self.samples if t0 <= s[0] <= t1]

    def peak_kb(self, t0=0, t1=float("inf")):
        """Highest sampled tree RSS; VmHWM of live processes can exceed any sampled instant."""
        window = [s for s in self.window(t0, t1) if s[3] > 0]
        return max((max(s[1], s[2]) for s in window), default=None)

    def steady_kb(self, t0=0, t1=float("inf")):
        """Median tree RSS over samples in which at least one runtime process existed."""
        return median([s[1] for s in self.window(t0, t1) if s[3] > 0])
