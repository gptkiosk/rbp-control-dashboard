# systemd user service installation (Linux / Raspberry Pi OS)

## Purpose

Run RCD as a per-user systemd service so it starts at boot and restarts after abnormal exits. This is the Linux counterpart of the macOS LaunchAgent page (`launchd.md`, macOS only). Restarting replaces the running service; do it when active jobs and sends can be safely interrupted.

## Controls

From the repository root, complete `scripts/bootstrap.sh` (it builds the API environment and the web app), then run `scripts/install-systemd-user.sh` as the service user. It checks for Linux, `systemctl`, the Python executable and the web build, renders `ops/systemd/rcd-api.service.template` into `~/.config/systemd/user/rcd-api.service` (mode 0600), reloads systemd, enables and restarts the unit, and waits up to 10 seconds for `/healthz`.

It refuses paths containing `%`, `|`, `&`, a backslash or a line break, because those would change the meaning of the unit.

To start at boot and survive logout, enable lingering once: `sudo loginctl enable-linger "$USER"`. The installer prints a reminder when it is off.

Read-only verification:

```sh
systemctl --user status rcd-api
journalctl --user -u rcd-api -n 50
curl -fsS --max-time 2 http://127.0.0.1:8800/healthz
```

## Settings involved

Installer options are **exported shell environment variables**. The script does not read `<data dir>/.env`; the application reads that file itself at runtime.

| Installer variable | Default |
|---|---|
| `RCD_SYSTEMD_UNIT` | `rcd-api` |
| `MAC_CONTROL_DATA_DIR` | `~/.rcd-control` |
| `MAC_CONTROL_PYTHON_PATH` | `<REPOSITORY_ROOT>/apps/api/.venv/bin/python` |
| `MAC_CONTROL_WORKING_DIRECTORY` | `<REPOSITORY_ROOT>/apps/api` |
| `MAC_CONTROL_SERVE_SCRIPT` | `serve.py` |
| `RCD_SYSTEMD_RESTART_SEC` | `10` |
| `MAC_CONTROL_PORT` | `8800` (only used for the final health check; set the server port in the `.env` file) |

The unit carries only the data folder and `PYTHONUNBUFFERED`. It holds no credentials. `Restart=on-failure` restarts after an abnormal exit only; `systemctl --user stop` stays stopped. Five failed starts within 5 minutes stop the restarts; reset with `systemctl --user reset-failed rcd-api`. Logs go to the journal (`journalctl --user -u rcd-api`), not to files in the data folder.

The Services page lists user units whose names start with one of `MAC_CONTROL_SERVICE_PREFIXES`. On Linux the default includes `rcd-`, so this unit and the update recovery units appear. A unit that restarted more than 50 times in 24 hours is flagged as a crash loop.

## Update recovery units

`ops/systemd/rcd-update-recover.service` and `.timer` are separate templates for the managed-update helper; see `packaging/README.md`. They are installed by hand and are not part of this installer.

## Troubleshooting

- **`Failed to connect to bus` when run over SSH:** the user manager is not running. Enable lingering, log in again, and check `XDG_RUNTIME_DIR`.
- **Missing Python or build:** run `scripts/bootstrap.sh`, or set `MAC_CONTROL_PYTHON_PATH`. The script stops before touching the unit.
- **Loaded but health failed:** read the journal and confirm the port in the `.env` file matches the one you checked.
- **Start limit reached:** fix the startup error shown in the journal, then `systemctl --user reset-failed rcd-api` and restart.
- **Unit name changed:** the installer only replaces the requested name. Stop and disable an older unit separately so two servers do not compete for one port.
- **Uninstall:** `systemctl --user disable --now rcd-api`, remove `~/.config/systemd/user/rcd-api.service`, then `systemctl --user daemon-reload`. The data folder is not touched.
