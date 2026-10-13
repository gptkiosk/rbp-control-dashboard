# LaunchAgent installation

## Purpose

Install MCD as a per-user macOS LaunchAgent so it starts at login and restarts after abnormal exits. Reloading replaces the running service; arrange it when active jobs and sends can be safely interrupted/reviewed.

## Screenshots

There is no installer screenshot. Verify installation with the health response and launchd status; profile screenshots are not proof of a successful install.

## Controls

From the repository root, complete bootstrap and the web build, then run `scripts/install-launchagent.sh` in the logged-in operator’s session. It checks the Python executable and frontend build, creates the default private data/log directory, renders and lints the plist, then writes the installed copy. It does not validate the dotenv file or check every server dependency before reload.

The script uses `launchctl bootout` then `bootstrap` to reread the definition. It waits up to 45 seconds for teardown and retries bootstrap once after two seconds. Existing model work is not blindly restarted. The final health probe is hardcoded to `http://127.0.0.1:8800/healthz`; a customized server port needs independent verification even if installation loaded successfully.

Read-only verification:

```sh
launchctl print "gui/$(id -u)/com.operator.mac-control"
curl -fsS --max-time 2 http://127.0.0.1:8800/healthz
```

Use your chosen label/port if different. Health returns JSON; check `status`, build state and writable data state.

## Settings involved

Installer options are **exported shell environment variables**. The shell script does not read `~/.mac-control/.env`; the Python application reads that file separately at runtime.

| Installer variable | Default |
|---|---|
| `MAC_CONTROL_LAUNCHD_LABEL` | `com.operator.mac-control` |
| `MAC_CONTROL_PYTHON_PATH` | `<REPOSITORY_ROOT>/apps/api/.venv/bin/python` |
| `MAC_CONTROL_WORKING_DIRECTORY` | `<REPOSITORY_ROOT>/apps/api` |
| `MAC_CONTROL_SERVE_SCRIPT` | `serve.py` |
| `MAC_CONTROL_PYTHONUNBUFFERED` | `1` |
| `MAC_CONTROL_RUN_AT_LOAD` | `true` |
| `MAC_CONTROL_KEEP_ALIVE_SUCCESSFUL_EXIT` | `false` |
| `MAC_CONTROL_THROTTLE_INTERVAL` | `60` |
| `MAC_CONTROL_STDOUT_PATH` | `~/.mac-control/logs/api.out.log` |
| `MAC_CONTROL_STDERR_PATH` | `~/.mac-control/logs/api.err.log` |

The installed plist is `~/Library/LaunchAgents/<LABEL>.plist`. The template’s environment entries are PATH and PYTHONUNBUFFERED, not a copy of OAuth credentials or every `MAC_CONTROL_*` field. KeepAlive is a dictionary with SuccessfulExit false by default: abnormal exits restart; normal exits do not. RunAtLoad starts the job when loaded, and ThrottleInterval limits restart frequency.

The installer’s log/data setup remains under `~/.mac-control` even when the Python application’s `MAC_CONTROL_DATA_DIR` differs. Configure custom log destinations explicitly; directories must exist. The script uses literal sed replacements, so review/lint customized paths containing unusual replacement characters before deployment.

## Secret placeholders

Use `<REPOSITORY_ROOT>` and `<LABEL>` in distribution examples. Do not paste dotenv credentials or private log contents into a plist example or support report.

## Troubleshooting

- **Missing Python/build:** complete bootstrap and build, or correct the exported executable path. The script stops before loading.
- **Plist lint failure:** inspect template substitutions; the lint check occurs before replacing the installed plist.
- **Loaded but health failed:** inspect the stderr log and actual configured host/port. The fixed health URL may differ from a customized deployment.
- **Crash loop:** inspect the startup error and dependency/configuration state. Changing restart settings does not resolve a failing application.
- **Label changed:** the installer only replaces the requested label. Review any previously installed job separately to avoid two servers competing for one port.

## Related pages

- [Environment](environment.md), [Google sign-in](google-sign-in.md).
- [Runtime data](runtime-data.md), [remote access](remote-access.md).
