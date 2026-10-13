# Alert rules and delivery

## Purpose

MCD records run failures and service crash loops durably, then optionally delivers concise notifications through the existing Hermes Discord sender. Detection and delivery are separate switches. Both are off at the top level by default.

## Screenshots

Pending capture: `overview-alerts-panel.png`. No RCD capture exists yet. Profile plan notifications are a separate feature from these operational alerts.

## Controls

Edit `<DATA_DIR>/alerts.toml`, or use `MAC_CONTROL_ALERTS_CONFIG_PATH` to select another file. The monitor reloads rules during checks. The file must be a regular file owned by the operator, not a symlink, and not writable by group or others. Mode `600` is recommended. Invalid configuration pauses the monitor with an error.

On Overview, **Mark reviewed** records that you inspected an alert; it does not resend it or change its delivery outcome. Inspect Discord before deciding what to do with an uncertain delivery.

## Settings involved

TOML booleans and numbers must be native values: `true`, `false`, `30`, not quoted strings. The distribution template in `ops/alerts.example.toml` contains placeholders that must be replaced with correctly typed values before use.

| Root key | Default | Type / allowed range | Effect |
|---|---|---|---|
| `enabled` | `false` | boolean | Enables detection. |
| `delivery_enabled` | `false` | boolean | Enables delivery; requires detection enabled and a valid destination. |
| `destination` | empty | string, `discord:` followed by 16–22 digits | Pins the channel for new events. Keep the real ID private. |
| `poll_seconds` | `30` | integer, 10–300 | Check interval. |
| `max_deliveries_per_tick` | `3` | integer, 1–10 | Limits sends per check. |
| `pending_max_age_seconds` | `3600` | integer, 60–86400 | Expires stale queued alerts before delivery. |

| `[runs]` key | Default | Type | Effect |
|---|---|---|---|
| `enabled` | `true` | boolean | Run detection, subject to the root switch. |
| `stages` | `["failed", "timeout", "interrupted"]` | array of 1–3 strings from this set | Run stages to notify. The stage name is `timeout`, not `timed_out`. |

| `[services]` key | Default | Type / allowed range | Effect |
|---|---|---|---|
| `enabled` | `true` | boolean | Service detection, subject to the root switch. |
| `window_seconds` | `600` | integer, 120–86400 | Window of service snapshots. |
| `excess_runs` | `5` | integer, 2–1000 | Excess launches allowed. |
| `calendar_allowance` | `20` | integer, 2–2000 | Minimum launch allowance for calendar jobs. |
| `sample_max_age_seconds` | `180` | integer, 60–600 | Ignores stale snapshots. |
| `recovery_samples` | `2` | integer, 2–10 | Distinct healthy samples needed to clear an incident. |

Interval jobs add their expected launches with a 20% margin to `excess_runs`. Calendar jobs use the larger of `excess_runs` and `calendar_allowance`. A counter reset starts a new observation epoch. Services' 24-hour assessment can differ from this shorter alert window.

### Delivery lifecycle

An event begins `pending`, is claimed as `delivering`, then becomes `sent` if Hermes returns a valid acknowledgement. MCD records the Discord ID in `message_id` and the timestamp in `sent_at`. Unconfirmed sends, or a restart during delivery, become `uncertain` and are not retried automatically. Old pending events become `expired`; a changed destination makes them `held` rather than rerouting them. Review acknowledgement is a separate `reviewed_at` field, not a `reviewed` delivery status.

Hermes sends the exact message from stdin; no model run is involved. Run notifications include only run ID, sanitized agent identifier, stage and exit code. Service notifications include a sanitized label, launch count, observation interval and allowance. Prompts, task titles, result text, error strings, working directories and keys are excluded from these messages.

### Disposable verification

From the repository, use the API virtual environment and an explicitly chosen destination:

```sh
apps/api/.venv/bin/python scripts/verify-alert-delivery.py \
  --destination 'discord:<CHANNEL_ID>'
```

Replace the placeholder with the intended channel ID. Without `--send`, this uses a temporary database and a simulated sender, not production cards or Discord delivery. It forces one disposable run to exit 23 and checks that repeated polls and a restarted monitor do not duplicate its alert. Only add `--send` when an actual test message has been authorized. A simulation's `sent` result is not evidence of a real Discord message.

## Secret placeholders

Use `discord:<CHANNEL_ID>` and `<PATH>` in public examples. Keep the actual rules and Hermes bot credentials private. MCD operational alert delivery uses Hermes' existing configuration; it does not copy its bot token into this rules file.

## Troubleshooting

- **Paused:** check file ownership, native TOML types, unknown keys and validation ranges. Delivery needs both root switches and a valid channel destination.
- **Uncertain:** inspect the channel first. Do not repeatedly run real-send tests or assume no acknowledgement means no message arrived.
- **Held:** the destination changed after the event was queued. Old messages will not silently move to the new channel.
- **Expired:** the pending event exceeded its maximum age when delivery resumed. Investigate the original run separately.

## Related pages

- [Overview and alert inspection](../sections/overview.md)
- [Service health](../sections/services.md)
- [Environment reference](environment.md)
- [Profile plan notifications](profiles-discord.md)
