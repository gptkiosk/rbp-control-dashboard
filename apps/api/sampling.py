"""Pure parsers for host metrics. No I/O here, so every function is unit-testable.

Sources:
  macmon pipe   CPU/GPU load, power, temperature, fans, swap (sudoless, Apple Silicon)
  vm_stat       page counts for an Activity Monitor-style "Memory Used"
  sysctl        kern.memorystatus_vm_pressure_level (1 normal, 2 warning, 4 critical)
  /proc/meminfo Linux memory values and vcgencmd Raspberry Pi throttle flags
"""

from __future__ import annotations

import json
import re

PRESSURE_LABELS = {1: "normal", 2: "warning", 4: "critical"}


def _pct(ratio: object) -> float | None:
    if isinstance(ratio, (int, float)):
        return round(float(ratio) * 100.0, 2)
    return None


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _temp(value: object) -> float | None:
    # macmon reports 0 when a sensor is unavailable; that is "no reading", not 0 degrees.
    v = _num(value)
    return round(v, 2) if v is not None and v > 0 else None


def parse_macmon(line: str) -> dict[str, float | None]:
    """Map one `macmon pipe` JSON line to metric columns.

    CPU percentages use the active ratio (share of time cores were busy), which tracks
    Activity Monitor's CPU load. macmon's cpu_usage_pct is frequency-weighted and reads lower.
    """
    data = json.loads(line)
    memory = data.get("memory") or {}
    temp = data.get("temp") or {}
    fans = data.get("fans") or []
    rpms = [f.get("rpm") for f in fans if isinstance(f.get("rpm"), (int, float))]
    return {
        "cpu_pct": _pct(data.get("cpu_active_ratio")),
        "ecpu_pct": _pct(data.get("ecpu_active_ratio")),
        "pcpu_pct": _pct(data.get("pcpu_active_ratio")),
        "gpu_pct": _pct(data.get("gpu_active_ratio")),
        "mem_total": _num(memory.get("ram_total")),
        "swap_used": _num(memory.get("swap_usage")),
        "swap_total": _num(memory.get("swap_total")),
        "cpu_temp": _temp(temp.get("cpu_temp_avg")),
        "gpu_temp": _temp(temp.get("gpu_temp_avg")),
        "sys_power": _num(data.get("sys_power")),
        "cpu_power": _num(data.get("cpu_power")),
        "gpu_power": _num(data.get("gpu_power")),
        "ane_power": _num(data.get("ane_power")),
        "ram_power": _num(data.get("ram_power")),
        "fan_rpm": float(max(rpms)) if rpms else None,
    }


_PAGE_SIZE_RE = re.compile(r"page size of (\d+) bytes")
_LINE_RE = re.compile(r'^"?([^":]+)"?:\s+(\d+)\.?\s*$')


def parse_vm_stat(text: str) -> dict[str, int]:
    """Parse `vm_stat` into {"page_size": n, "<field>": pages}."""
    out: dict[str, int] = {}
    m = _PAGE_SIZE_RE.search(text)
    if m:
        out["page_size"] = int(m.group(1))
    for line in text.splitlines():
        lm = _LINE_RE.match(line.strip())
        if lm:
            out[lm.group(1).strip()] = int(lm.group(2))
    return out


def memory_used_bytes(vm: dict[str, int]) -> float | None:
    """Activity Monitor's "Memory Used": app memory + wired + compressed.

    App memory is approximated as anonymous pages minus purgeable pages, the same
    approximation used by common macOS monitors.
    """
    needed = ("page_size", "Anonymous pages", "Pages wired down", "Pages occupied by compressor")
    if not all(k in vm for k in needed):
        return None
    app = max(vm["Anonymous pages"] - vm.get("Pages purgeable", 0), 0)
    pages = app + vm["Pages wired down"] + vm["Pages occupied by compressor"]
    return float(pages * vm["page_size"])


def parse_pressure_level(text: str) -> float | None:
    text = text.strip()
    return float(text) if text.isdigit() else None


def parse_proc_meminfo(text: str) -> dict[str, int]:
    """Read Linux ``/proc/meminfo`` values as bytes (unknown lines are ignored)."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        name, sep, value = line.partition(":")
        parts = value.split()
        if sep and parts and parts[0].isdigit():
            values[name] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return values


def net_rates(
    prev: tuple[float, int, int] | None, now: tuple[float, int, int]
) -> tuple[float | None, float | None]:
    """Bytes/s received and sent between two (time, rx_bytes, tx_bytes) readings."""
    if prev is None:
        return None, None
    dt = now[0] - prev[0]
    if dt <= 0:
        return None, None
    rx = (now[1] - prev[1]) / dt
    tx = (now[2] - prev[2]) / dt
    # Counters reset on interface changes; a negative delta is not a real rate.
    return (round(rx, 1) if rx >= 0 else None, round(tx, 1) if tx >= 0 else None)


_THROTTLE_BITS = (
    "under_voltage", "frequency_capped", "throttled", "soft_temp_limit",
    "previously_under_voltage", "previously_frequency_capped", "previously_throttled",
    "previously_soft_temp_limit",
)


def parse_vcgencmd_throttled(text: str) -> list[str]:
    """Decode Raspberry Pi's ``vcgencmd get_throttled`` bit field.

    Bits 0--3 describe an active condition and bits 16--19 record a condition
    since boot.  Unknown/new bits are deliberately ignored.
    """
    m = re.search(r"throttled=0x([0-9a-fA-F]+)", text)
    if not m:
        return []
    value = int(m.group(1), 16)
    return [name for bit, name in enumerate(_THROTTLE_BITS)
            if value & (1 << (bit if bit < 4 else bit + 12))]
