# Uninstall and troubleshooting

**Status: written from source, not run.** The uninstall steps and the troubleshooting messages come from
`scripts/install/bootstrap-rcd.sh`, `packaging/README.md` and the update helper. None has been executed on a
Raspberry Pi.

## Uninstall

Uninstalling removes the program and its units. **It keeps your data** in `~/.rcd-control` unless you delete it in
the last step.

```sh
systemctl --user disable --now rcd-api.service rcd-update-recover.timer
rm -f ~/.config/systemd/user/rcd-api.service \
      ~/.config/systemd/user/rcd-update-recover.service \
      ~/.config/systemd/user/rcd-update-recover.timer
systemctl --user daemon-reload
rm -rf ~/.local/share/rcd-control
```

This removes the install root: every version, the helper, the inbox, the state, the journal and the backups. If
you installed with `--root`, use that path instead.

To remove your data as well, after the steps above:

```sh
rm -rf ~/.rcd-control
```

**This deletes the database, logs, reports and settings file.** Copy `~/.rcd-control` somewhere first if you want to
keep it. Nothing else removes it, so a reinstall keeps your data until you do this.

If you ran `loginctl enable-linger` for the service user, undo it with `sudo loginctl disable-linger <user>`. That
setting is for the whole account, so change it only if nothing else needs it.

The uninstall steps above have not been run. Check each path with `ls` before you delete it.

## Where data lives

| Path | What | Removed by uninstall |
|---|---|---|
| `~/.local/share/rcd-control/` | Install root: versions, helper, inbox, state, backups | Yes |
| `~/.rcd-control/` | Runtime data: `data.db`, `.env`, logs, reports | Only if you run the last step |
| `~/.config/systemd/user/rcd-*` | Units installed by the bootstrap | Yes |

## Troubleshooting

### Check first

```sh
systemctl --user status rcd-api.service
journalctl --user -u rcd-api -n 50
journalctl --user -u rcd-update-recover -n 50
curl -fsS http://127.0.0.1:8800/healthz
```

### Messages the installer prints

| Message | Meaning and action |
|---|---|
| `Python 3.11 is required. On Raspberry Pi OS: sudo apt install python3.11 python3.11-venv (or pass --python PATH)` | No Python 3.11 found. Install it, or pass `--python /absolute/path`. A bad `--python` path is never replaced by another interpreter |
| `<python> lacks venv/ensurepip` | Install `python3.11-venv` |
| `--manifest-sha256 must be the 64-hex digest from the release page` | The digest is missing or malformed. Copy it again from the release page |
| `download failed: <url>` | Network or GitHub error. Retry. Check the URL and the release tag |
| `download was redirected to a host that is not GitHub: <host>` | Refused on purpose. Nothing was installed |
| `manifest sha256 is X, not the pinned Y; refusing this package` | The manifest is not the one the release page lists. Stop, and recheck the digest and the release |
| `package refused; nothing was installed`, followed by one or more `error:` lines | One of the package checks failed. The lines name it, for example a product or platform mismatch, a prerelease without `--allow-prerelease`, an archive size or digest mismatch, or a refused archive member |
| `the host must be arm64 (uname -m reports ...)` | Wrong architecture. Use 64-bit Raspberry Pi OS |
| `this installer is for Linux (Raspberry Pi OS)` | Wrong operating system |
| `no systemd user session; log in as the service user (or run loginctl enable-linger) and retry` | Log in as the service user, then retry |
| `<root>/current already exists; RCD is installed. Upgrade with the in-app updater.` | This is not a first install. Use [updates](updates-rollback-recovery.md) |
| `<unit> already exists; refusing to replace it` | An earlier install left the unit behind. Check it, then remove it by hand |
| `something already answers on 127.0.0.1:8800; stop it before installing` | Another service owns the port. Find it with `ss -ltnp` on Linux and stop it. Do not kill a process you have not identified |
| `staging refused the package; nothing was switched` | Read the `error:` lines in `<root>/state/helper.log`. Nothing was switched, so fix the cause or re-download the package |
| `installed X but healthz did not answer within 10 s` | The service is installed and running the new version. There is no previous version to roll back to. Read the journal, fix the cause, or uninstall |
| `note: run 'sudo loginctl enable-linger <user>' ...` | The service will not start at boot until lingering is on. This is a note, not an error |
| `note: systemd-analyze reported warnings for rcd-api.service` | Usually harmless. Read the journal if the service fails |

### Symptoms after an install

| Symptom | Cause | Action |
|---|---|---|
| `staging` fails with `No module named 'release_fetch'` (in the helper traceback or `helper.log`) | An older bootstrap copied only three helper files. The current bootstrap copies all five | Do not copy files by hand. Re-install from a tagged source that includes the fix, after the first install is verified |
| The recover timer fails every 5 minutes | Often a missing helper module, or an interrupted update the helper cannot finish | Check `journalctl --user -u rcd-update-recover`. Do not hand-copy files; use `update_recovery.py status` first |
| The Settings update card says the helper is not set up, or shows manual steps | `MAC_CONTROL_UPDATE_ROOT` is not set in the app environment | Add `MAC_CONTROL_UPDATE_ROOT=<root>` to `~/.rcd-control/.env` and restart. This has not been tested |
| The one-button fetch is refused | The panel needs a well-formed manifest SHA-256 copied from the release page. Without one, nothing is downloaded | Enter the digest, or use the command line. See [updates](updates-rollback-recovery.md#upgrade-with-the-command-line) |
| `apply` refuses with live work or queued tasks | The drain check is doing its job | Let the work finish or stop it through the app, then retry. Nothing is stopped for you |
| `rcd-api` restarts in a loop | The app exits abnormally. `Restart=on-failure` with a 10-second delay and a start limit | Check the journal. A `StartLimitBurst` hit stays down until you reset it: `systemctl --user reset-failed rcd-api` |
| Port 8800 is taken | Another dashboard (for example MCD, which uses the same default port) is on the same host | Run only one of them on this host. The installer has no port option: it is fixed at 8800, and the health check and unit both assume it |
| `curl` on `/healthz` works, but the browser shows nothing | The API binds loopback only | Use the Pi's own browser, or set up [remote access](../configuration/remote-access.md) |

## Getting help

Include the output of `systemctl --user status rcd-api`, the `journalctl` lines above, and the version from
`~/.local/share/rcd-control/current/BUILD_INFO.json`. Never include the contents of `~/.rcd-control/.env`.
