# Mac

The Mac health page (`MacView.vue`) shows time-series charts for CPU (total, E-cores, P-cores), GPU, memory (used and swap), temperature (CPU and GPU), power (system, CPU, GPU), and network (down, up). It also shows the top 15 processes, Tailscale status, and pending updates that require a restart. It supports the decision: "Is the hardware healthy over 1 h / 24 h / 7 d / 30 d / 1 y, and which process or temperature spike is the cause of a service or run failure?"

## Purpose

For the operator: detect thermal throttling, memory pressure escalation, network interruption, or a restart-required update. For troubleshooting services (`docs/sections/services.md`) and tasks (`docs/sections/tasks.md`), the charts show whether the host had headroom when a job failed or timed out. It is read-only; no settings change from this screen.

## Screenshots

- Pending capture: RCD's host page is `/pi` (Pi health), not this macOS page. No RCD capture exists yet. The charts described below are the MCD page and are not verified for RCD.
- Services: see [Services](services.md).

## Controls

### Range selector (`ref<SeriesRange>`)
- Default `1h`. Changing to `24h`, `7d`, `30d` or `1y` updates `/api/metrics/series?range=...&fields=...` (poll interval switches from 30 000 ms to 300 000 ms for longer ranges).
- Fields requested: `cpu_pct`, `ecpu_pct`, `pcpu_pct`, `gpu_pct`, `mem_used`, `swap_used`, `cpu_temp`, `gpu_temp`, `sys_power`, `cpu_power`, `gpu_power`, `net_rx_bps`, `net_tx_bps`.

### Charts (`TimeSeriesChart.vue`)
- Each chart has a title, icon, one or more `ChartLine` definitions, format function (`formatPct`, `formatGB`, `formatTemp`, `formatWatts`, `formatKBps`), and a `zeroBased` flag.
- CPU chart shows three lines (`CPU`, `E-cores`, `P-cores`). Memory shows `Memory used` (GB) and `Swap used` (GB). Temperature shows `CPU` and `GPU` (°C, non-zero based). Power shows `System`, `CPU`, `GPU` (W). Network shows `Down` and `Up` (KB/s).

### Top processes (`/api/processes/top?limit=15`)
- Poll interval 10 s. Lists the top processes by CPU usage; no interactive actions (read-only list).

### Tailscale (`/api/tailscale`)
- Shows connection state; no interactive pairing from this screen. Pairing is done via profile settings (`docs/sections/profile-settings.md`).

### Updates (`/api/updates`)
- Shows updates with `requires_restart` count. Restart is not triggered from this screen; it requires an operator decision or a planned maintenance window.

## Settings involved

- `.env` / `MAC_CONTROL_*` keys:
  - `MAC_CONTROL_COLLECTOR_ENABLED` (must be `True` for charts to populate).
  - `MAC_CONTROL_SAMPLE_INTERVAL_S` (default `10`; affects how often new points appear).
  - `MAC_CONTROL_MACMON_PATH` (default: the first `macmon` found on `PATH`; macOS only).
  - `MAC_CONTROL_TAILSCALE_PATH` (`/usr/local/bin/tailscale` by default).
  - `MAC_CONTROL_DISK_PATH` (`/System/Volumes/Data` by default).
- Profile / environment: no direct profile fields edit from this page; Tailscale pairing is handled separately.

Never include secret values in docs or screenshots.

## Troubleshooting

- **No chart data** — confirm `MAC_CONTROL_COLLECTOR_ENABLED` is `True`, that `macmon` is installed at the configured path, and that the `.env` file is readable (`chmod 600` recommended). Check `macmon_status` on Overview.
- **Temperature stays high** — compare with Power chart (system/CPU/GPU W). Investigate top processes. If thermal throttling is suspected, allow the machine to cool or move workload off this host.
- **Swap growing** — Memory chart shows swap alongside used memory. If swap increases over time, investigate memory-heavy processes and consider service restart or workload reduction.
- **Network drop** — Network chart lines fall to zero. Check Tailscale status card; if disconnected, verify pairing (`profile-discord-planning.md` or `docs/sections/profile-settings.md`) and the tailnet connection independently of MCD.
- **Updates require restart** — the count is shown but not acted on automatically. Coordinate restart with the task and agent schedule to avoid interrupting active runs.

## Related pages

- [Overview](overview.md) — summary metrics and alert status.
- [Services](services.md) — launchd health that correlates with resource charts.
- [Profile settings](profile-settings.md) — Tailscale pairing.
- [Configuration: settings](../configuration/settings.md)
- [Configuration: alerts](../configuration/alerts-toml.md)
- [Tested environments](../tested-environments.md)
