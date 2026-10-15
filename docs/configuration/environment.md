# Environment variables and settings (`MAC_CONTROL_*`, `.env`)

Every configuration field loaded by `apps/api/settings.py` (Pydantic `BaseSettings`, prefix `MAC_CONTROL_`, env file `~/.rcd-control/.env`) is listed below with its default, Python type, purpose, and whether it holds a secret. The `SecretStr` credential field is shown only as a placeholder; never commit `.env` or `~/.rcd-control/.env`.

## Purpose

Controls the MCD server bind, ports, directories, feature toggles (collector, dispatcher, auth, alerts), service prefixes, agent paths, and the private host/auth settings. Changing a value requires a restart (`launchctl` or `serve.py`) unless noted.

## Screenshots

Pending capture: `profile-settings.png`.

The profile UI is separate from the host environment table; it does not expose or edit these host fields.
- LaunchAgent install: `docs/configuration/launchd.md`

## Controls

- `.env` edit: `~/.rcd-control/.env` (mode 600)
- `scripts/configure-google-auth.py --enable` (writes auth keys to `.env`, preserves backups)
- `scripts/install-launchagent.sh` (reloads the service; the application reads dotenv at startup)
- In-app Settings manages profile preferences and credentials separately from these host fields.

## Settings involved

### General / server

| Key | Default | Type | Purpose | Secret? |
|---|---|---|---|---|
| `MAC_CONTROL_HOST` | `127.0.0.1` | `str` | Bind address. Keep the loopback bind for the documented Tailscale proxy deployment, including after sign-in is enabled. | No |
| `MAC_CONTROL_PORT` | `8800` | `int` | Main server port (1–65535). The current installer health check is fixed to loopback port 8800; a custom port needs separate verification. | No |
| `MAC_CONTROL_DEV_PORT` | `5173` | `int` | Vite dev server port; allowed by the request guard during development. | No |
| `MAC_CONTROL_LOG_LEVEL` | `info` | `str` | Logging level. Conventional values are `debug`, `info`, `warning`, `error`; the value is free-form and not validated by the code. | No |
| `MAC_CONTROL_DATA_DIR` | `~/.rcd-control` | `Path` | Runtime directory (database, run logs, alerts, vault). Keep private storage mode `700`; individual helpers enforce their own checks. | No |
| `MAC_CONTROL_ENVIRONMENT` | `local` | `str` | Installation environment; tests use `test`. | No |
| `MAC_CONTROL_WEB_DIST` | `<REPOSITORY_ROOT>/apps/web/dist` | `Path` | Built frontend served by the API. | No |

### Organization / branding

| Key | Default | Type | Purpose | Secret? |
|---|---|---|---|---|
| `MAC_CONTROL_ORGANIZATION_NAME` | `Mac Control` | `str` | Organization label shown in UI headers. | No |
| `MAC_CONTROL_PRODUCT_NAME` | `Mac Control Dashboard` | `str` | Full product name. | No |
| `MAC_CONTROL_PRODUCT_SHORT_NAME` | `MCD` | `str` | Short identifier for reports and notifications. | No |

### Collector (`MAC_CONTROL_COLLECTOR_*`)

| Key | Default | Type | Purpose | Secret? |
|---|---|---|---|---|
| `MAC_CONTROL_COLLECTOR_ENABLED` | `True` | `bool` | Enables the metrics/service collector (`macmon`, `launchd` probes). Disabled in tests. | No |
| `MAC_CONTROL_SAMPLE_INTERVAL_S` | `10` | `int` (`2`–`300`) | Seconds between metric samples. | No |
| `MAC_CONTROL_MACMON_PATH` | first `macmon` on `PATH` (macOS only; unused on Linux) | `str` | Path to `macmon` binary for CPU/GPU/memory metrics. Optional. | No |
| `MAC_CONTROL_TAILSCALE_PATH` | first `tailscale` on `PATH` | `str` | Path to `tailscale` binary for network/peer status. Optional. | No |
| `MAC_CONTROL_DISK_PATH` | `/` on Linux, `/System/Volumes/Data` on macOS | `str` | Root path for disk-space monitoring. | No |
| `MAC_CONTROL_SERVICE_PREFIXES` | `("ai.hermes.", "ai.openclaw.", "com.openclaw.", "com.headroom.", "com.operator.")` | `tuple[str, ...]` | Service-name prefixes included in the Services panel: launchd labels on macOS, systemd user unit names on Linux (e.g. `ai.hermes.`, `rcd-`). On Linux the default also includes `rcd-`. | No |

### Dispatcher / agent execution (`MAC_CONTROL_DISPATCHER_*`)

| Key | Default | Type | Purpose | Secret? |
|---|---|---|---|---|
| `MAC_CONTROL_DISPATCHER_ENABLED` | `True` | `bool` | Enables agent/task dispatch. Disabled in tests. | No |
| `MAC_CONTROL_MAX_CONCURRENT_RUNS` | `2` | `int` (`1`–`8`) | Maximum concurrent agent/task executions. | No |
| `MAC_CONTROL_DEFAULT_TIMEOUT_S` | `1800` | `int` (`30`–`21600`) | Default execution timeout (30 min). | No |
| `MAC_CONTROL_DEFAULT_BUDGET_USD` | `1.0` | `float` (`0.01`–`50.0`) | API-dollar budget used by the Claude adapter when applicable. Not a universal provider hard cap; subscription project runs omit this API-equivalent budget. | No |
| `MAC_CONTROL_RUN_RETENTION_DAYS` | `90` | `int` (`≥1`) | Days to retain completed run records. | No |
| `MAC_CONTROL_MODEL_REFRESH_ENABLED` | `true` | `bool` | Lets the operator read OpenRouter's public model list from the Models section. `false` refuses the refresh and fetches nothing. | No |
| `MAC_CONTROL_MODEL_WATCH_ENABLED` | `false` | `bool` | Runs the weekly model watch: reads OpenRouter's public model list and leaves one Backlog card when a model needs a decision. | No |
| `MAC_CONTROL_MODEL_WATCH_INTERVAL_DAYS` | `7` | `int` (`1`-`30`) | Days between model watch runs. | No |
| `MAC_CONTROL_HOUSEKEEPING_AUTO` | empty | `str` | Comma-separated housekeeping kinds cleaned up automatically after hours (`stale_approval_wait`, `old_update_backup`). Empty: nothing is automatic. | No |
| `MAC_CONTROL_HOUSEKEEPING_WINDOW_START_HOUR` | `1` | `int` (`0`-`23`) | Local hour the after-hours window opens. | No |
| `MAC_CONTROL_HOUSEKEEPING_WINDOW_END_HOUR` | `5` | `int` (`0`-`23`) | Local hour the after-hours window closes (a window may cross midnight). | No |
| `MAC_CONTROL_WORKDIR_ROOTS` | `(~/Projects, ~/.rcd-control/workspaces)` | `tuple[Path, ...]` | Allowed working directories for agent runs (e.g. `~/Projects`, `~/.rcd-control/workspaces`). A card’s working directory must be inside one of these. | No |
| `MAC_CONTROL_CLAUDE_PATH` | first `claude` found (see below) | `str` | Path to Claude CLI binary. Optional. | No |
| `MAC_CONTROL_CODEX_PATH` | first `codex` found (see below) | `str` | Path to Codex CLI binary. Optional. | No |
| `MAC_CONTROL_HERMES_PATH` | first `hermes` found (see below) | `str` | Path to Hermes CLI binary. Optional. | No |
| `MAC_CONTROL_OPENCLAW_PATH` | first `openclaw` found (see below) | `str` | Path to OpenClaw CLI binary. Optional. | No |
| `MAC_CONTROL_AGENT_EXECUTABLES` | `("claude", "codex", "hermes", "openclaw")` | `tuple[str, ...]` | Executable names treated as agents outside dispatched runs (gateways, interactive CLIs). Their processes and children are refused by operator APIs, as every dispatched runner already is. `[]` limits the check to dispatched runs. See [Hermes access](../HERMES_ACCESS.md#operator-authority-boundary). | No |

Optional tools (`gh`, `macmon`, `tailscale` and the agent CLIs) are looked up in the service's `PATH`, then `~/.local/bin` and `/usr/local/bin` (plus Homebrew's prefix on macOS). When a tool is not found the matching feature shows as unavailable; setup and startup never fail because of it. A service manager often starts with a short `PATH`, so set the matching `MAC_CONTROL_*_PATH` key to an absolute path to pin a location.
| `MAC_CONTROL_HERMES_CONFIG_PATH` | `None` | `Path \| None` | Optional private Hermes config file. | No |
| `MAC_CONTROL_OPENCLAW_CONFIG_PATH` | `None` | `Path \| None` | Optional private OpenClaw config file. | No |
| `MAC_CONTROL_ALLOWED_HOSTS_EXTRA` | `()` | `tuple[str, ...]` | Extra `Host` header values accepted by the request guard. Tests use this; it is not an authentication bypass. | No |

### Auth (`MAC_CONTROL_AUTH_*`) — only when `MAC_CONTROL_AUTH_ENABLED=true`

| Key | Default | Type | Purpose | Secret? |
|---|---|---|---|---|
| `MAC_CONTROL_AUTH_ENABLED` | `False` | `bool` | Enables Google OIDC sign-in. Requires complete configuration; failure raises `ValueError`. | No |
| `MAC_CONTROL_GOOGLE_CLIENT_ID` | `""` | `str` | Google OAuth `client_id`. Usually ends with `.apps.googleusercontent.com`, but the code only requires it to be non-empty when auth is enabled. | No; publish placeholder identifiers only |
| `MAC_CONTROL_GOOGLE_CLIENT_SECRET` | `SecretStr("")` | `SecretStr` | Google OAuth `client_secret`. Masked by `SecretStr` and hidden in Settings validation errors. | **Yes** — placeholder only (`<SECRET>`); never commit |
| `MAC_CONTROL_AUTH_ALLOWED_EMAILS` | `()` | `tuple[str, ...]` | Allowlisted operator emails (operator email allowlist). Required when auth is enabled. | No |
| `MAC_CONTROL_AUTH_ORIGINS` | `("http://127.0.0.1:8800",)` | `tuple[str, ...]` | Allowed OAuth origins. Must be canonical HTTPS or loopback HTTP (`http://127.0.0.1:8800`). No query/fragment/user/pass. | No |

### Alerts / reports

| Key | Default | Type | Purpose | Secret? |
|---|---|---|---|---|
| `MAC_CONTROL_ALERTS_CONFIG_PATH` | `None` (falls back to `~/.rcd-control/alerts.toml`) | `Path \| None` | Path to `alerts.toml`. Overrides default. Must be a regular file (not symlink), owned by current user, mode 600 recommended. | No |
| `MAC_CONTROL_GH_PATH` | first `gh` found (see above) | `str` | Path to GitHub CLI (`gh`) for read-only repo reports. Optional. | No |
| `MAC_CONTROL_OPS_REPORTS_DIR` | `~/.rcd-control/reports` | `Path` | Local read-only reports directory. | No |
| `MAC_CONTROL_HERMES_REPORTS_DIR` | `None` | `Path \| None` | Optional Hermes reports directory for cross-install reports. | No |

### Provider-cost overrides and installer variables

The OpenRouter cost reader separately reads these optional keys from the fixed private `~/.rcd-control/.env` file. They are not fields of `Settings` or process-environment overrides. Leave them unset to use the respective agent's local provider configuration. Keep literal credentials private; unresolved secret references are not sent as keys.

| Key | Default | Type | Purpose | Secret? |
|---|---|---|---|---|
| `MAC_CONTROL_OPENROUTER_HERMES_KEY` | unset | string | Optional provider key used to query Hermes' actual key-level OpenRouter spending. | **Yes** |
| `MAC_CONTROL_OPENROUTER_OPENCLAW_KEY` | unset | string | Optional provider key used to query OpenClaw's actual key-level OpenRouter spending. | **Yes** |

These overrides select the accounting key; they do not change the agent's execution route or enforce a spending cap. If agents share a key, its spend is shared and cannot be attributed separately by key alone.

[LaunchAgent installation](launchd.md) lists the installer's ten exported shell options, including its label, Python path and log directory. They are installer inputs rather than additional application Settings fields.

### Loading and precedence

The `Settings` class (`apps/api/settings.py`) gives explicit constructor values precedence over environment variables, which override the configured dotenv file, then defaults. `model_config` sets `env_prefix="MAC_CONTROL_"`, `env_file` pointing to the expanded home path `~/.rcd-control/.env`, and `extra="ignore"`. `SecretStr` fields (`google_client_secret`) never display the value in errors (`hide_input_in_errors=True`).

## Secret placeholders

Every secret value below is shown as a placeholder (`<VALUE>`, `<SECRET>`, `<CLIENT_ID>`). Actual values live only in `~/.rcd-control/.env` (mode 600), `~/.rcd-control/vault.key` (mode 600), `~/.rcd-control/google-oauth-client.json` (mode 600), or private backups. Never include real credentials in source, prompts, screenshots, diagrams, or distribution packages.

- `MAC_CONTROL_GOOGLE_CLIENT_ID`: `<CLIENT_ID>` (e.g. `...apps.googleusercontent.com`)
- `MAC_CONTROL_GOOGLE_CLIENT_SECRET`: `<SECRET>`
- `MAC_CONTROL_AUTH_ALLOWED_EMAILS`: `operator@example.com` (example only; use real allowed operator emails when enabling)

## Troubleshooting

- **Bind failure (`MAC_CONTROL_HOST`)**: If `0.0.0.0` is set before auth is enforced, the server is exposed. Revert to `127.0.0.1`, restart LaunchAgent (`launchctl bootout/bootstrap`), verify with `curl -fsS --max-time 2 http://127.0.0.1:8800/healthz`.
- **Auth validation error (`ValueError`)**: `MAC_CONTROL_AUTH_ENABLED=true` requires `google_client_id`, `google_client_secret`, `auth_allowed_emails`, and `auth_origins`. Check `.env` syntax (list values use JSON arrays, not Python tuples) and that origins contain only loopback HTTP or canonical HTTPS.
- **Environment not picked up**: Environment variables override dotenv values. Restart the application after host setting changes. `MAC_CONTROL_DATA_DIR` changes runtime output paths but does not move the fixed default dotenv lookup from `~/.rcd-control/.env`. Use an explicit settings `env_file` override in controlled test code when needed.
- **Directory permissions**: Keep private runtime storage owned by the operator and mode `700`. Credential helpers enforce their own file/directory checks; `Settings.validate_auth` validates auth configuration/origins, not general directory ownership.

## Related pages

- [Settings overview](settings.md)
- [Google sign-in](google-sign-in.md)
- [Remote access](remote-access.md)
- [LaunchAgent](launchd.md)
- [Alerts config](alerts-config.md)
- [Profile / Discord](profiles-discord.md)
- [Runtime data](runtime-data.md)
