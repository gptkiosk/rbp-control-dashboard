# Alerts

The Alerts section (`AlertStatus.vue` on Overview; `docs/ALERTS.md` for the rules file format) covers failure alert rules, delivery history, and acknowledgment. It supports the decision: "Are any failed runs or service crash loops unacknowledged, is delivery paused or enabled, and do I need to review an uncertain event before any manual resend?"

## Purpose

For the operator: confirm whether alert monitoring is active, whether a Discord destination is configured (`alerts.toml`), how many events need delivery review (`attention`), and which events are `uncertain` (delivery result ambiguous) versus `held` (expired queued events) or `expired` (default one hour). It also provides the `Mark reviewed` acknowledgment that records inspection without resending or erasing the original outcome.

For the user: understand that only failed, timed-out, and interrupted runs generate outbox events; cancelled and successful runs do not alert. Crash-loop detection complements the Services page's 24-hour assessment but uses a different window (10 minutes, not 24 hours), so the two can show different results.

## Screenshots

- Pending capture: `overview-alerts-panel.png`. No RCD capture exists yet. A capture would not show an actual delivery or a reviewable event; the controls below appear when applicable.

## Controls

### Alert status card (`AlertStatus.vue`)
- Header: `Alerts` icon plus delivery-state label (derived from `data.enabled` and `data.delivery_enabled`).
- Status line: `Failed runs and service crash loops · Last check: <dateLabel>`; if `pending > 0`, `· {{ pending }} pending`.
- Attention line: `{{ attention }} alert(s) need delivery review. Check the Discord channel before resending.` — shown only when `attention > 0`.
- Expandable `<details>`: `Recent alerts (N)` with `<ul>` of events (`key="event.id"`). Each `<li>` shows:
  - `Status · Reviewed` heading (`strong`). Status mapped by `labels`: `pending`, `delivering`, `sent`, `uncertain`, `held`, `expired`, `reviewed`.
  - Timestamp (`dateLabel(event.sent_at ?? event.created_at)`).
  - Message (`pre-wrap`).
  - Error line (if `event.error` exists).
  - `Mark reviewed` button only for `uncertain` or `held` events when `!event.reviewed_at`. Disabled (`:disabled="reviewing !== null"`) during the `POST /api/alerts/{id}/acknowledge` call; label switches to `Saving…`.
- Refresh: `/api/alerts` polled every 30 000 ms; acknowledgment refreshes the same endpoint.

### Rules reference (`ALERTS.md` and `docs/configuration/alerts-toml.md`)
- The rules file (`~/.mac-control/alerts.toml`, override with `MAC_CONTROL_ALERTS_CONFIG_PATH`) controls:
  - `enabled` and `delivery_enabled` (defaults disabled).
  - `destination` — explicit Discord channel reference (`discord:<CHANNEL_ID>`); required to enable delivery.
  - `poll_seconds`, `max_deliveries_per_tick`, `pending_max_age_seconds`.
  - `[runs]` section: `enabled`, `stages`.
  - `[services]` section: `enabled`, `window_seconds`, `excess_runs`, `calendar_allowance`, `sample_max_age_seconds`, `recovery_samples`.
- File requirements: regular file (not symlink), owned by current user, mode `600` recommended. Symlinks or invalid TOML pause delivery; the monitor reloads the file each check.
- Delivery mechanism: `~/.local/bin/hermes send --to discord:<CHANNEL_ID> --file - --json` with the exact message on stdin. Hermes reads its existing private bot configuration; no MCD tokens are copied, no new permission scope is requested.
- Event model (SQLite migration `0008`): outbox table plus durable `baseline` and `incident` state. Delivery claim committed before Hermes runs; a `sent` event records Discord's message ID. A lost acknowledgement, timeout, or interrupted process becomes `uncertain` and is never retried automatically.
- Limits: at most 3 alerts sent per check (default 30 s); each send bounded to 30 s plus 3 s to terminate its process group; shutdown waits for in-flight send and starts no subsequent sends; installer allows up to 45 s for teardown. Agent dispatch and metrics collection continue independently of notification failures.
- Crash-loop rules (10-minute window): more than 5 launches above the expected schedule; interval jobs receive 20% margin; calendar jobs have a 20-launch allowance. At least two fresh snapshots required (older than 180 s ignored); counter reset starts a new epoch. Incident sends once until two distinct healthy samples confirm recovery.
- Expired events: queued events older than `pending_max_age_seconds` (default one hour) are not sent.

## Settings involved

- `.env` / `MAC_CONTROL_*` keys:
  - `MAC_CONTROL_ALERTS_CONFIG_PATH` — optional override for the rules file path (`~/.mac-control/alerts.toml` default).
  - `MAC_CONTROL_DATA_DIR` — SQLite outbox and durable baseline/incident tables.
  - `MAC_CONTROL_LOG_LEVEL`.
- Profile fields: `discord_channel_id` (not shown directly on this screen; set through profile settings; referenced by `alerts.toml` `destination` as `discord:<CHANNEL_ID>`).
- LaunchAgent (`docs/configuration/launchd.md`): the `.plist` label and `KeepAlive` settings are independent of alert monitoring; alerts observe service state but do not restart or stop services.

Never include real Discord IDs, personal emails, hostnames, absolute file paths (`~/private-workspace`), or secret tokens in docs, screenshots, or rules examples. Use placeholder values (`<CHANNEL_ID>`, `<TRUE_OR_FALSE>`) in all examples.

## Troubleshooting

- **Delivery paused** — check `enabled` and `delivery_enabled` in `alerts.toml`. Confirm `destination` contains an explicit `discord:<CHANNEL_ID>` reference; a missing or empty destination prevents delivery. Confirm file mode (`600`) and that it is a regular file (not symlink).
- **Monitoring · delivery paused** — `enabled = true` but `delivery_enabled = false`. This is the safe default; delivery requires explicit operator authorization.
- **Pending events never deliver** — verify `poll_seconds` and `max_deliveries_per_tick`. Confirm the Hermes binary (`~/.local/bin/hermes`) is executable and its private configuration includes the destination channel. Check the outbox SQLite table (`migration 0008`) and that `MAC_CONTROL_DATA_DIR` is writable.
- **Uncertain event** — delivery attempt produced an ambiguous result (lost acknowledgement, timeout, interrupted process). Do not run `verify-alert-delivery.py --send` repeatedly; inspect the Discord channel first. Acknowledging (`Mark reviewed`) records inspection without resending and does not erase the original outcome.
- **Held / Expired events** — queued events that exceeded `pending_max_age_seconds` become `expired`; older queued events remain `held` until acknowledged or removed by expiration. These are not resent automatically.
- **Crash loop shown on Services but no alert** — alert rules use a 10-minute window with different thresholds; Services uses 24 hours. A brief burst may trigger the service flag without reaching the alert window. Check `alerts.toml` `[services]` `window_seconds` and `excess_runs` values.
- **Local simulation** — use the disposable-run script (`apps/api/.venv/bin/python scripts/verify-alert-delivery.py --destination discord:<CHANNEL_ID>`). Add `--send` only after the operator has authorized the destination and purpose. This test uses temporary database/workspace, forces exit `23`, and checks duplicate suppression; it does not create or fail production cards.

## Related pages

- [Overview](overview.md) — alert status card (`AlertStatus.vue`) embedded on the main dashboard.
- [Services](services.md) — crash-loop detection and 24-hour assessment that complements the shorter alert windows.
- [Configuration: settings](../configuration/settings.md)
- [Configuration: alerts format](../configuration/alerts-toml.md)
- [Alerts rules reference](../ALERTS.md)
- [Profile settings](profile-settings.md) — Discord pairing and delivery destination setup.
- [Security reference](../development/SECURITY.md)
