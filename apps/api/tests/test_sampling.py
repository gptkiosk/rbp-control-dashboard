from __future__ import annotations

import json

import sampling

# Captured from `macmon pipe` on the Mac mini M4 (trimmed).
MACMON_LINE = json.dumps({
    "all_power": 0.39, "ane_power": 0.0, "cpu_active_ratio": 0.1005, "cpu_power": 0.116,
    "ecpu_active_ratio": 0.1579, "pcpu_active_ratio": 0.0144, "gpu_active_ratio": 0.2747,
    "gpu_power": 0.278, "ram_power": 0.249, "sys_power": 11.32,
    "fans": [{"max_rpm": 4900, "name": "fan0", "rpm": 999}],
    "memory": {"ram_total": 17179869184, "ram_usage": 13552828416,
               "swap_total": 4294967296, "swap_usage": 3688366080},
    "temp": {"cpu_temp_avg": 38.62, "gpu_temp_avg": 34.52},
})

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               10000.
Pages purgeable:                           1000.
Pages wired down:                         150000.
Anonymous pages:                          400000.
Pages occupied by compressor:              50000.
"""


def test_parse_macmon_maps_ratios_to_percent():
    m = sampling.parse_macmon(MACMON_LINE)
    assert m["cpu_pct"] == 10.05
    assert m["gpu_pct"] == 27.47
    assert m["swap_used"] == 3688366080
    assert m["cpu_temp"] == 38.62
    assert m["sys_power"] == 11.32
    assert m["fan_rpm"] == 999.0


def test_parse_macmon_zero_temperature_means_no_reading():
    line = json.dumps({"temp": {"cpu_temp_avg": 0, "gpu_temp_avg": 0.0}})
    m = sampling.parse_macmon(line)
    assert m["cpu_temp"] is None and m["gpu_temp"] is None
    assert m["fan_rpm"] is None


def test_vm_stat_memory_used_matches_formula():
    vm = sampling.parse_vm_stat(VM_STAT)
    assert vm["page_size"] == 16384
    # (anonymous - purgeable) + wired + compressor
    expected = (400000 - 1000 + 150000 + 50000) * 16384
    assert sampling.memory_used_bytes(vm) == expected


def test_memory_used_none_when_fields_missing():
    assert sampling.memory_used_bytes({"page_size": 16384}) is None


def test_pressure_level_parse():
    assert sampling.parse_pressure_level("1\n") == 1.0
    assert sampling.parse_pressure_level("") is None


def test_proc_meminfo_uses_bytes():
    info = sampling.parse_proc_meminfo("MemTotal:       1024 kB\nMemAvailable:    256 kB\nHugePages: 3\n")
    assert info == {"MemTotal": 1024 * 1024, "MemAvailable": 256 * 1024, "HugePages": 3}


def test_net_rates():
    assert sampling.net_rates(None, (10.0, 100, 100)) == (None, None)
    assert sampling.net_rates((0.0, 0, 0), (10.0, 1000, 500)) == (100.0, 50.0)
    # counter reset after an interface change: no negative rates
    assert sampling.net_rates((0.0, 5000, 5000), (10.0, 100, 100)) == (None, None)


def test_parse_pi_throttling_flags():
    assert sampling.parse_vcgencmd_throttled("throttled=0x0\n") == []
    assert sampling.parse_vcgencmd_throttled("throttled=0x50005\n") == [
        "under_voltage", "throttled", "previously_under_voltage", "previously_throttled",
    ]
    assert sampling.parse_vcgencmd_throttled("not installed") == []
