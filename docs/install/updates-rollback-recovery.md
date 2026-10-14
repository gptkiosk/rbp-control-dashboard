# Updates, rollback and recovery

**Status: written from source, not run.** No update, rollback or recovery has been executed on a Raspberry Pi or on
the Lima guest. The clean first install has no receipt yet (story `s13_clean_rcd`), so none of the paths below has a
verified starting point.

Updates are **never automatic**. Each one needs an operator to fetch it, stage it and apply it, in separate steps.

## What counts as a managed install

Only a packaged install whose `BUILD_INFO.json` is a stable or prerelease build, running from `<root>/current`, gets
managed updates. A source checkout, a dev build or a package run from anywhere else gets the manual steps only.

## Settings updater

The Settings page's update card calls the operator API:

| Route | What it does |
|---|---|
| `GET /api/updates` | Install state, current version, interrupted update, work in flight |
| `GET /api/updates/check?channel=stable\|prerelease` | Reads the public GitHub Releases API for this repository. No token needed |
| `POST /api/updates/fetch` | Downloads the three allowlisted assets of one version into the inbox, verifies them, and stages them |
| `POST /api/updates/stage` | Stages a package already in the inbox |
| `POST /api/updates/apply` | Drains, snapshots, switches atomically, checks health, rolls back on failure |
| `POST /api/updates/recover` | Finishes or undoes an interrupted update |

Routes are for the signed-in operator only. Agent processes are refused. The POST routes only start the pinned
helper and return `202`. Poll `GET /api/updates` for progress.

**Known gaps on a bootstrap install:**

- **The updater is off.** The API reads `MAC_CONTROL_UPDATE_ROOT`, and `rcd-api.service` does not set it. The card
  then shows manual steps. To enable it, add this line to `~/.rcd-control/.env` and restart the service. This has not
  been tested:

  ```sh
  MAC_CONTROL_UPDATE_ROOT=/home/<user>/.local/share/rcd-control
  ```

- **With a pinned digest the one-button fetch requires an independent digest.** The panel displays GitHub's API digest
  for reference, then requires the operator to enter the manifest SHA-256 copied independently from the release page.
  It sends that value as `manifest_sha256`; missing or malformed pins are refused before download.
- **With release-signature trust the update is one confirmation.** Check for updates, then **Update to X.Y.Z**: the
  server downloads the release, verifies the manifest's SSH signature against the release key pinned in
  `<root>/helper/allowed_signers`, stages it, and installs it with the same drain check, data snapshot, health check and
  automatic rollback as the command line. No digest is typed. If work is running the install is refused and the verified
  package stays staged until you install it.

### Switch a host to release-signature trust

A host installed by the current `bootstrap-rcd.sh` is switched automatically when the package ships the release key and
it matches the fingerprint written in the script. For an existing host, run once on it, naming the key you checked in
[the release signing guide](../../packaging/release-signing.md):

```sh
python3 -I <root>/helper/update_helper.py --config <root>/helper/helper.json \
  enable-signed-updates --fingerprint SHA256:<fingerprint of the release key> --allowed-signers <path to allowed_signers>
```

Without `--allowed-signers` it reads `<root>/current/packaging/allowed_signers` (shipped from 0.3.2). The command refuses
unless the file holds exactly one key for the `dashboard-release` signer, limited to that namespace, and that key's
fingerprint is the one you named. It copies the file into the helper folder, where an update cannot replace it, and
rewrites `helper.json`. It refuses while an update is in progress. To go back, set `"trust": {"kind": "pinned-digest"}` in
`helper.json`. A rotated release key needs this command again with the new fingerprint.

## Upgrade with the command line

Run these as the service user. The helper's `--config` is the pinned `helper.json`:

```sh
H=~/.local/share/rcd-control/helper
python3.11 -I $H/update_helper.py --config $H/helper.json check --channel stable
python3.11 -I $H/update_helper.py --config $H/helper.json fetch X.Y.Z --channel stable --manifest-sha256 <64-hex>
python3.11 -I $H/update_helper.py --config $H/helper.json stage rcd-X.Y.Z-linux-arm64 --manifest-sha256 <64-hex>
python3.11 -I $H/update_helper.py --config $H/helper.json apply <version id>
```

- `fetch` downloads only the archive, manifest and signature of exactly that version, checks the product, platform,
  version (no downgrade), digests and signature, then runs `stage`. It stops there. Nothing is switched.
- `stage` extracts into a new `versions/<id>/` and builds its `runtime/` venv. A version counts as staged only once
  its receipt is written.
- `apply` is a second, separate confirmation. It refuses while any agent or chat run is live, a run is waiting on a
  human decision, a task is queued or running, or a project is dispatching. **The operator drains these first.**
  Nothing is stopped or cancelled for you.
- Then `apply` stops `rcd-api.service`, runs the drain check again, copies the database, switches `current` with
  `rename(2)`, and starts the service.
- Readiness: `/healthz` on loopback must report the new version and healthy, from a process started after the switch,
  within `readiness_timeout_s` (90 seconds in the bootstrap config). Otherwise it rolls back automatically.

The prerelease channel needs `allow_prerelease` in `helper.json`, which the bootstrap sets only with
`--allow-prerelease`. Downgrades need `allow_downgrade`, which the bootstrap sets to `false`.

## Automatic rollback

If readiness fails after the switch, the helper:

- points `current` back to the previous version, and
- restores the database copy taken before the switch.

Anything written while the failed version was running is **lost**. A first install has no previous version, so this
path cannot run on it. If the first install's health check fails, the service runs that version. See
[troubleshooting](uninstall-troubleshooting.md#troubleshooting).

## Recovery when the app will not start

`update_recovery.py` works with the app down. It never calls the API and needs no sign-in. It reads the journal
and version links, then drives the same engine.

The bootstrap copies it into `<root>/helper/` with the other helper files. Like the rest of the updater, it has not
been run on a Pi. If the copy is ever missing, the timer-driven recovery below or the `update_helper.py` commands are
the fallback.

```sh
R=~/.local/share/rcd-control/helper
python3.11 -I $R/update_recovery.py --config $R/helper.json status      # app up/down, current, previous, interrupted update
python3.11 -I $R/update_recovery.py --config $R/helper.json versions    # every installed version and its role
python3.11 -I $R/update_recovery.py --config $R/helper.json snapshots   # kept data snapshots, with ids for restore
python3.11 -I $R/update_recovery.py --config $R/helper.json rollback    # code back to the previous version
python3.11 -I $R/update_recovery.py --config $R/helper.json restore <snapshot id>  # database back to a snapshot
python3.11 -I $R/update_recovery.py --config $R/helper.json recover     # finish or undo an interrupted update
```

- `rollback` and `restore` show what they will do first. You confirm by typing the version or snapshot id back. With
  no terminal, pass the same id as `--confirm <id>`. Otherwise nothing changes (exit 3).
- `rollback` switches code only and keeps a copy of the database. It is refused if the database is on a schema the
  previous version does not know.
- `restore` discards every change made since the snapshot. It copies the current database first.
- `recover` finishes or undoes whatever an interrupted helper left. A partial version is removed. An unswitched
  update restarts the old version. A switched one is committed if healthy and rolled back if not.
- `--skip-drain` (terminal only, asked a second time, refused while the app answers) ignores the stale-runs check.
  Use it only after you have confirmed no run is actually live.
- `--json` prints one object.

Exit codes: `0` done, `1` refused or failed, `2` bad usage, `3` declined.

## Timer-driven recovery

`rcd-update-recover.timer` runs `update_helper.py recover` at login/boot (30 seconds after start) and every 5 minutes.
With no interrupted update it only reads the journal and exits. Check it with:

```sh
systemctl --user list-timers rcd-update-recover.timer
journalctl --user -u rcd-update-recover -n 50
```

## Manual rollback and restore, step by step

1. Run `update_recovery.py status` and `versions`. Confirm the target version and that no work is in flight.
2. Run `rollback` (or `restore <snapshot id>` for data). The command stops the service itself, then asks you to
   confirm. Type the version or snapshot id back, or pass it with `--confirm` when there is no terminal.
3. Check `curl -fsS http://127.0.0.1:8800/healthz`. If the service did not come back, see
   `journalctl --user -u rcd-api -n 50`.

Nothing in these steps has been run. Treat the first attempt as a test, and keep a copy of `~/.rcd-control` first.
