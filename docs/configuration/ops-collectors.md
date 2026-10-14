# Ops collectors configuration

> **Doc version:** 2026-10-12 · project 3 revision 2 · story `s2-docs` (draft)
> **Status:** unreleased. The application source is held for operator fixes and human sign-off. This
> page describes a local prototype. Tests for the collector, schedule, signal and UI code have not been
> run against this revision, and no test has been run on Raspberry Pi hardware. The collector design is
> awaiting human approval (`h2-design`). Nothing here is published, and no Hermes job has been changed.

The Ops collectors replace routine verbose model runs with deterministic checks. No model is called.
The collectors read only the sources named in the host-owned `ops-collectors.json`. They write a report
only when a result changes or a reminder is due. A healthy, unchanged fleet produces no report, no alert
and no model tokens.

## Turning them on

1. Leave `MAC_CONTROL_OPS_COLLECTORS_ENABLED` unset, or `false`, until the collector design is approved.
   The `ops_collectors_enabled` setting gates the scheduler loop, and it is off by default.
2. Create `ops-collectors.json` in the data directory (`~/.rcd-control` by default, or `MAC_CONTROL_DATA_DIR`).
   A missing file gives built-in safe defaults: a disk check on the data directory and a jobs check.
3. Add schedules. Every schedule starts disabled unless the host file enables it. Schedules that are
   missing from the file are created disabled.

> The settings class reads the `MAC_CONTROL_` environment prefix, not `RCD_`. This is inherited from the
> MCD import. Confirm the intended prefix before release.

Schedules are the only way a collector runs on a timer. A schedule never enables itself.

## Sources

Each source has an `id`, a `kind` and the keys for that kind. Unknown keys are rejected. A file may
name at most 40 sources, and the whole file is limited to 16 KiB.

| Kind | Keys | What it checks |
|---|---|---|
| `disk` | `path`, `warn_pct`, `crit_pct` | Free space on the volume holding `path`. |
| `memory` | `warn_pct`, `crit_pct` | Memory pressure. |
| `load` | `warn_ratio`, `crit_ratio` | Load average against CPU count. |
| `jobs` | `window_s`, `stuck_s`, `warn_failed`, `crit_failed` | Recent failed Tasks and stuck dependencies. |
| `waits` | `warn_s`, `crit_s` | Approval and queue waits. |
| `agents` | `quiet_s`, `warn_dead`, `crit_dead` | Agent runs that have stopped responding. |
| `service` | `name`, `scope` | One named service, by status. See below. |
| `release` | `stuck_s` | An interrupted update that has not finished. |
| `file_age` | `path`, `warn_s`, `crit_s` | How old a file is, for example a report a job should write. |
| `dir_age` | `path`, `warn_s`, `crit_s` | How old the newest file in a folder is, for example a backup folder. |
| `command` | `argv`, `ok_exit`, `warn_exit` | An allowlisted executable. See below. |

**Service checks by platform.** On macOS, `service` asks `launchctl print`, in the `gui/<uid>` domain for
`scope: user` or the `system` domain otherwise. On Linux, it runs `systemctl is-active`, with `--user`
for `scope: user`. The Linux path is unverified on ARM64 hardware.

`command` sources run only when their absolute executable is listed in `MAC_CONTROL_OPS_COLLECTOR_COMMANDS`.
They run with no shell, a scrubbed environment (`PATH=/usr/bin:/bin` and `LANG=C.UTF-8`), bounded
output and a process-group kill on timeout. No operator credential or data path reaches a check.

Evidence text is cut to 500 characters.

## Schedules

Each schedule has an `id` (unique), a `label`, `enabled`, and exactly one timing:

- `every_s`: an interval from 300 seconds to 7 days.
- `at`: a UTC `HH:MM` time, optionally with `weekday` from 0 to 6 (Monday is 0).

A schedule may also name a `sources` subset. The validator rejects unknown keys, bad times, unknown
sources, duplicate ids and more than 12 schedules.

The scheduler checks every 30 seconds. Each enabled schedule that is due runs once per slot, under one
invocation lock. Slots missed while RCD was down collapse into a single run. A fixed-time schedule that
has never run waits for its next slot. It does not run immediately at startup.

The three replacement schedules are shipped disabled:

| id | Label | Time (UTC) |
|---|---|---|
| `morning-health` | Morning fleet health | 07:00 daily |
| `evening-review` | Evening review | 19:00 daily |
| `weekly-maintenance` | Weekly fleet maintenance | 06:00 Monday |

## Limits

| Setting | Default | Allowed |
|---|---|---|
| Source timeout | 5 s | 1–30 s |
| Concurrency | 3 | 1–8 |
| Result cache | 60 s | 0–3600 s |
| Stale after | 3600 s | 60 s–7 days |
| Reminder while unchanged (`renotify_s`) | 21600 s | 300 s–7 days |
| Retained reports | 100 | 1–1000 |
| Report age | 30 days | 1–365 days |
| Total report bytes | 2 MiB | 4 KiB–64 MiB |
| Bytes per report | 32 KiB | 1 KiB–256 KiB |
| Archive bytes | 32 MiB | 0–512 MiB |

Stale checks are labelled "No recent result". Their age is always shown.

## Reports and the dashboard

Reports are written to the `fleet-health` folder under the ops-reports directory. The Reports page
lists them, and the Ops health panel shows:

- The overall severity and the time of the last check, both relative and exact.
- Checks, most severe first, with how long each has held its status.
- Schedules, with the next run and the latest fleet report.
- A link on each check to the dashboard page where you act on it: Tasks, Agents, Mac or Settings.

**Refresh checks** runs the enabled sources now. It sends the operator guard header and needs an
operator sign-in. Refresh is rate-limited by the result cache.

Historic reports are copied to `historic-archive` only by an explicit archive action. The originals
in the Hermes archive are never copied, edited or removed.

## What this does not do

- It does not enable any Hermes job. Morning Fleet Health Check, Evening Log Review and Weekly Fleet
  Maintenance stay paused until the operator enables the reviewed replacement.
- It does not call a model, post a message or send an alert.
- It does not read logs, job bodies or secrets. Only the allowlisted sources run.

## Verification status

No test result is claimed here. The collector, schedule, signal and UI changes were written and read,
but the test and type-check commands were not run for this revision. Acceptance requires an approved
test run on the ARM64 Linux test environment and on macOS, plus the `h2-design` approval. The approved
ARM64 Lima instance `pi4-test` currently reports `Broken`, so the Linux run is blocked.

Related: [Ops panels](../OPS_PANELS.md) · [Settings](settings.md) · [Report storage](report-storage.md)
