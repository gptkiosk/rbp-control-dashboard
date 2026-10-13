# MCD failure alerts

Alert rules live in one file: `~/.mac-control/alerts.toml`. See `ops/alerts.example.toml`.
The file location can be overridden with MAC_CONTROL_ALERTS_CONFIG_PATH. It must be a regular
file owned by the current user, not writable by other users; symlinks and invalid TOML pause
delivery. Mode 600 is recommended. Defaults are disabled. The monitor reloads the file each
check; an explicit Discord channel ID is required to enable delivery.

Delivery uses `~/.local/bin/hermes send --to discord:<CHANNEL_ID> --file - --json`, with the exact
message on stdin. It reuses Hermes's private bot configuration. No tokens are copied into MCD,
no model or tool-calling agent is invoked, and no new permission scope is requested. Destinations
are pinned into queued events; changing the config holds old events instead of rerouting them.

Failed, timed-out and interrupted runs generate one outbox event each. Cancelled and successful
runs do not alert. Monitoring starts from an activation baseline: old failures are excluded,
while runs already active can still alert if they fail. Prompts, titles, output, error strings,
working directories, keys, costs, and model arguments are omitted. Only the generated run ID,
agent identifier, state and numeric exit code are sent. Identifier text cannot contain mentions,
links or Hermes media directives.

Crash-loop alerts count excess launches over a 10-minute window. Defaults: more than 5 launches
above the expected schedule; interval jobs receive a 20% margin, calendar jobs have a 20-launch
allowance. At least two fresh snapshots are required, snapshots older than 180 seconds are
ignored, and a counter reset starts a new epoch. An incident sends once until two distinct
healthy samples confirm recovery. These burst rules complement the Services page's longer
24-hour assessment; their different windows can show different results. No service is restarted
or stopped by the alert monitor.

SQLite migration 0008 adds the outbox and durable baseline/incident state. A delivery claim is
committed before Hermes runs. A sent event records Discord's message ID; a lost acknowledgement,
timeout or interrupted process becomes `uncertain` and is never retried automatically. This
avoids duplicate automatic sends after an ambiguous result; network delivery cannot promise
exactly once in every failure scenario. Check the channel before any manual resend. Overview
shows alert status and recent history. Mark reviewed acknowledges inspection without resending
or erasing the original outcome. Expired queued events (default one hour) are not sent.

At most 3 alerts are sent per check (default every 30 seconds). Each send is bounded to 30 seconds
plus 3 seconds to terminate its process group. Shutdown waits for the in-flight send and starts
no subsequent sends. The installer allows up to 45 seconds for teardown. Agent dispatch and
metrics collection continue independently of notification failures.

For a local simulation with a disposable Python run and no network sends:

```
apps/api/.venv/bin/python scripts/verify-alert-delivery.py --destination discord:<CHANNEL_ID>
```

Adding `--send` sends exactly the prepared test message through Hermes after the operator has
authorized the destination and purpose. This test uses a temporary database/workspace, forces
exit 23, and checks duplicate suppression across repeated polls and a new monitor. It does not
create or fail production cards. A successful real-send result contains Discord's acknowledgement.
Do not run it repeatedly to check an uncertain delivery; inspect the channel first.
