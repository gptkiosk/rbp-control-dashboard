# Overview

The Overview page (`OverviewView.vue`) is the landing dashboard. It shows live hardware telemetry (CPU, GPU, memory, disk, temperature, power, network, fan), a service-attention summary, agent availability, available updates that require a restart, and the alert-delivery status card. The monitoring panels are read-only. The alert panel can record that an uncertain or held delivery was reviewed; that does not resend it. It supports the decision: "Is the host healthy right now, and do I need to open Mac health, Services or Alerts for detail?"

## Purpose

For the operator running a local Mac mini M4: confirm the collector is running (`macmon`), see whether services or agents need attention, and check whether any delivery-delayed alerts need review. For a new user: understand what the dashboard reports and where to go for deeper health, service, task or agent details.

## Screenshots

- Pending capture: `overview-overview.png` (main dashboard). No RCD capture exists yet.
- Pending capture: `overview-alerts-panel.png` (alert panel). Live delivery states, event history and review buttons appear only when configured and applicable.

## Controls

### Metrics grid (`StatTile` components)
- **CPU** — value (`formatPct`), sub-label (`E-cores · P-cores` with separate percentages), meter bar.
- **GPU** — value and meter; no sub-label.
- **Memory used** — value (`formatPct`), sub-label (`used of total` bytes, e.g. `4.2 GB of 16.0 GB`) and a `ChipTag` pressure chip (`normal`, `warning`, `critical`) when `pressure_label` is set.
- **Swap** — value in bytes, meter, sub-label (`of total` bytes).
- **Disk used** — value (`formatPct`), sub-label (`about N days to full` when `disk_days_to_full` is available, otherwise `not filling`), meter.
- **Temperature, Power, Network, Fan** — additional stat tiles visible in the full view; values refresh via `/api/metrics/current` every 10 s.

### Alert status card (`AlertStatus.vue`)
- Header label `Alerts` with an icon; right-side delivery status string.
- `Failed runs and service crash loops · Last check: <timestamp>` line. If `pending > 0`, it shows `· {{ pending }} pending`.
- If `attention > 0`: `{{ attention }} alert(s) need delivery review. Check the Discord channel before resending.`
- `<details>` expandable `Recent alerts (N)` with an unordered list of events. Each event shows:
  - Status label (`Pending`, `Delivering`, `Sent`, `Uncertain`, `Held`, `Expired`, `Reviewed`) plus `· Reviewed` when `reviewed_at` is set.
  - Timestamp (`dateLabel(sent_at ?? created_at)`).
  - Message text (`white-space: pre-wrap`).
  - Error string (if `event.error` exists).
  - `Mark reviewed` button for `uncertain` or `held` events when not yet reviewed. Disabled while `reviewing` is non-null; label changes to `Saving…` during the request.
- Clicking `Mark reviewed` calls `POST /api/alerts/{id}/acknowledge` and refreshes the card.

### Service summary
- Number of services needing attention in the Services summary tile. Choose **View services** to open the Services page.

### Agent summary and updates
- Agent availability cards (OpenClaw, Hermes, Claude Code, Codex) with status (`Available`).
- `Updates` payload shows `requires_restart` count.

## Settings involved

- `.env` / `MAC_CONTROL_*` keys (loaded from `~/.mac-control/.env` or environment):
  - `MAC_CONTROL_HOST` (default `127.0.0.1`; set to `0.0.0.0` only after auth is enforced).
  - `MAC_CONTROL_PORT` (default `8800`).
  - `MAC_CONTROL_LOG_LEVEL`.
  - `MAC_CONTROL_COLLECTOR_ENABLED` (default `True`; must be enabled for metrics to appear).
  - `MAC_CONTROL_SERVICE_PREFIXES` (affects which services appear in the summary).
- `alerts.toml` (see `docs/configuration/alerts-toml.md` and `ALERTS.md`): defaults disabled; controls whether the alert panel shows `Monitoring · delivery paused` or `Discord delivery enabled`. The file lives at `~/.mac-control/alerts.toml` (override with `MAC_CONTROL_ALERTS_CONFIG_PATH`).
- Profile fields: `discord_channel_id` is the delivery destination referenced by `alerts.toml`; it is not edited on this screen.

Never include secret values (Discord IDs, tokens, hostnames) in docs or screenshots.

## Troubleshooting

- **Could not load metrics** — `macmon` may not be running (`macmon_status !== 'running'` shows a muted line). Check `MAC_CONTROL_COLLECTOR_ENABLED`, `MAC_CONTROL_MACMON_PATH` (default: the first `macmon` found on `PATH`; macOS only), and that the process has permissions for system metrics. Restart the API (`serve.py`) after fixing `.env`.
- **No services shown** — check `MAC_CONTROL_SERVICE_PREFIXES` includes the label prefix (`ai.hermes.`, `ai.openclaw.`, `com.openclaw.`, etc.). See `docs/sections/services.md`.
- **Delivery paused / Monitoring · delivery paused** — `alerts.toml` either has `enabled = false` or `delivery_enabled = false`, or the `destination` is missing. See `docs/configuration/alerts-toml.md`.
- **Pending events never resolve** — verify the `alerts.toml` `poll_seconds` value, that the outbox SQLite table exists (`migration 0008`), and that `verify-alert-delivery.py` has been authorized by the operator. Uncertain events are never retried automatically; inspect the Discord channel before any manual resend.
- **Memory pressure stays critical** — the chip reflects `macmon`'s `pressure_label`. If it does not recover, investigate memory-consuming processes via Mac health (`docs/sections/mac.md`) and top processes.

## Related pages

- [Mac health](mac.md) — time-series charts for the same hardware metrics.
- [Services](services.md) — full service table and crash-loop details.
- [Profile settings](profile-settings.md) — Discord pairing and delivery destination setup.
- [Configuration: settings](../configuration/settings.md)
- [Configuration: alerts](../configuration/alerts-toml.md)
- [Alerts reference](../ALERTS.md)
- [Tested environments](../tested-environments.md)
