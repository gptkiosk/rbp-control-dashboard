# Housekeeping: findings the coordinator can propose and only you can approve

## Purpose

Explains the Housekeeping panel in Profile: leftovers the server finds by fixed rules, how Hermes can read them and propose a fix
on a free model, and why nothing changes until you approve it. Read it when an update says "waiting on a human decision" for
runs that are long finished, or when update backups pile up.

## Screenshots

Pending capture: `profile-housekeeping.png`.

## Controls

**Profile → Housekeeping**:

- **Scan now** re-reads the database and the backup folder. No model is involved: the findings come from fixed rules.
- **Findings** are listed with the reason, the evidence and what the fix would do. Tick the ones to resolve, tick the
  confirmation, then **Resolve selected**. Each finding is checked again at that moment; one that changed is skipped, never forced.
- **Proposed by Hermes, waiting for you** shows a proposal Hermes made. **Approve and apply** runs the fixed action on exactly the
  findings frozen when it was proposed. **Reject** changes nothing.

What is found today:

| Finding | When | What the fix does |
|---|---|---|
| Stale approval wait | A run sits in `awaiting_approval` on a story that is already done or failed, and a later run on that story succeeded. | Marks the run cancelled (superseded) with an audit note. Its result, logs, model, usage and session are not changed. |

Before any database row changes, the server takes a consistent copy of the database (`~/.rcd-control/upgrades/pre-maintenance-…/data.db`).
Every action is also appended to `~/.rcd-control/maintenance/audit.jsonl` (mode 600).

**Hermes and free models.** With **Allow Hermes to read Housekeeping findings in Discord and propose fixes** on (Profile, off by
default) and a paired Discord account, Hermes can list the findings, explain them in plain words, and create a proposal. It reads
redacted evidence marked as untrusted text. It has no way to apply anything: the apply route is operator-only and agent
processes are refused. The explanation and proposal run on whatever route you give Hermes, including the free router.

**After hours.** Set `MAC_CONTROL_HOUSEKEEPING_AUTO` to the kinds you want cleaned up overnight, for example
`stale_approval_wait,old_update_backup`, and the server applies exactly those fixed actions once a day between
`MAC_CONTROL_HOUSEKEEPING_WINDOW_START_HOUR` and `..._END_HOUR` (default 1 to 5, local time). It is off by default. Each finding is checked
again at that moment, nothing runs while an update is running, a database backup is taken before any row changes, and every action goes
to the audit file as `after-hours`. The panel shows the last run and what it did. Hermes can read the same status and explain it, but
the schedule and the actions are fixed code, not a model.

The Updates panel points here when a blocker is an approval wait.

## Settings involved

- Profile preference `allow_discord_maintenance` (default off).
- Update backups on this product are managed by the updater itself (`<update root>/state/backups`, kept per `keep_versions`), so Housekeeping lists only stale approval waits here.
- `MAC_CONTROL_HOUSEKEEPING_AUTO` (default empty), `MAC_CONTROL_HOUSEKEEPING_WINDOW_START_HOUR` (1) and `MAC_CONTROL_HOUSEKEEPING_WINDOW_END_HOUR` (5).
- Operator API: `GET /api/maintenance`, `POST /api/maintenance/apply {finding_ids, confirm}`,
  `POST /api/maintenance/proposals/<id>/approve|reject`. Hermes bridge actions: `maintenance`, `maintenance_propose`.

## Troubleshooting

- A finding disappears when you resolve it: it changed since the list was drawn (resolved elsewhere, or a backup was removed).
- Nothing listed but an update is blocked: the wait is real (a story still open) or it is not a kind Housekeeping handles; decide it
  in the task board.

## Related pages

- [Updates, rollback and recovery](../install/updates-rollback-recovery.md)
- [Failure mining](failure-mining.md)
- [Profiles and Discord](../PROFILES_AND_DISCORD.md)
