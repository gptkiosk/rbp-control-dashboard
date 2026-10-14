# Runtime data and backups

## Purpose

MCD keeps its database, run logs and private credentials outside the source repository. Treat the whole runtime directory as private: task prompts, results, paths, account identities and shared project memory can be sensitive even when credential fields are encrypted.

## Screenshots

Pending capture: `profile-credentials-vault.png`. A capture would show only the credential controls, not the contents of the runtime files.

## Controls

Choose the runtime root with `MAC_CONTROL_DATA_DIR`. The default is `~/.mac-control`. Keep storage owned by the operator with directory mode `700` and private-file mode `600`. Individual credential helpers enforce additional ownership, regular-file and symlink checks; the general Settings validator does not validate every runtime path.

`bootstrap.sh` installs API dependencies and builds the frontend. It does not create every runtime file. The server and feature-specific helpers create files as needed. The LaunchAgent installer creates its configured log directory.

## Settings involved

| Setting | Default | Effect |
|---|---|---|
| `MAC_CONTROL_DATA_DIR` | `~/.mac-control` | Database, run logs, vault and other private runtime storage. |
| `MAC_CONTROL_RUN_RETENTION_DAYS` | `90` | Prunes old non-running runs and idle chat threads with their run logs; cards remain. |
| `MAC_CONTROL_WORKDIR_ROOTS` | `~/Projects`, `~/.mac-control/workspaces` | Bounds selectable agent working directories. |
| `MAC_CONTROL_OPS_REPORTS_DIR` | `~/.mac-control/reports` | Local reports root. Independently configured; does not automatically follow a custom data directory. |
| `MAC_CONTROL_ALERTS_CONFIG_PATH` | unset | Uses `<DATA_DIR>/alerts.toml` unless overridden. |

Typical files and directories, present only when the corresponding feature has been configured:

```text
~/.mac-control/
  .env                      Host settings; fixed default dotenv location
  data.db                   SQLite database
  data.db-wal, data.db-shm   SQLite WAL files while in use
  vault.key                 Encryption key for profile credentials
  alerts.toml               Operator alert rules
  google-oauth-client.json  Optional privately retained downloaded OAuth JSON
  admin-recovery-token      Local recovery secret when sign-in is enabled
  agent-tokens/             Scoped agent and Hermes project-bridge tokens
  runs/                     Run logs and raw output logs
  project-outputs/          Project/story output artifacts
  workspaces/               Optional agent working directories
  reports/                  Optional local reports
  logs/                     Default LaunchAgent stdout/stderr
```

Changing `DATA_DIR` does not move the dotenv lookup: by default the application still reads `~/.mac-control/.env`. Exported environment variables take precedence over that file. Logs and report roots have their own configuration; inspect those when relocating an installation.

### Database and migrations

The database uses SQLite WAL mode, `synchronous=NORMAL` and foreign keys. Application startup calls `upgrade_to_head` in `apps/api/migrate.py`, using the checked-in Alembic revisions. Migration status is based on Alembic revision tracking. There is no standalone `python -m migrate --verbose` command provided by that module.

Tables include `metric_sample`, `metric_minute`, `metric_day`, `service_snapshot`; `card`, `card_dependency`, `run`, `run_event`; `chat_thread`, `chat_message`, `mcp_change`; `usage_record`, `usage_cursor`, `billing_config`; `auth_session`, `alert_event`, `alert_state`, `agent_access`; and `project`, `project_task`, `project_memory`, `project_delivery`, `user_profile`, `user_credential`.

Tracked revisions currently run from `0001_metrics_and_services.py` through `0011_profiles.py`. Consult `apps/api/migrations/versions/` for the exact schema history. Do not manually alter production rows or downgrade a live database to solve an execution error.

### Backup and restore

Use SQLite's online backup facility for a running database, or stop the application and quiesce database writers before taking a consistent file backup. Copying only a live `data.db` can omit committed data still in its WAL. Keep backups private and outside the repository.

Back up the database with the matching `vault.key`, host settings, alert rules, necessary agent tokens and project/run artifacts. Also record separately configured report and working-directory roots. The Google import helper creates a private dotenv backup when replacing an existing file; this is not a complete application backup.

Restore with the application stopped, preserve ownership and private permissions, then start the application and let startup apply missing migrations. Check health and credential access before resuming dispatch. Do not overwrite a live database.

`vault.key` is generated lazily when saving a profile credential. Losing it prevents decryption of existing saved OpenRouter/Discord credentials; restore the matching key or re-enter those credentials. Claude/Codex subscription sign-in remains in their native tools, outside this profile vault.

## Secret placeholders

Never publish runtime files, database rows, prompts, logs or tokens. Encryption protects saved credential values; it does not make the rest of the database public-safe. Use `<DATA_DIR>`, `<PATH>` and `<SECRET>` in examples. Private backups require the same protection as the original files.

## Troubleshooting

- **Wrong or empty installation:** check the effective `DATA_DIR` and the fixed dotenv lookup before starting another server. A different directory creates a different database.
- **Migration failure:** preserve a backup, inspect the startup error and installed dependencies, and check database writability. Do not guess a schema repair or downgrade.
- **Credential read failure:** verify the matching `vault.key` and the helper's ownership/permission checks. Replacing the key with a new key will not decrypt old credentials.
- **Missing logs or reports:** check their independently configured roots. Run retention removes old run logs; report catalog access does not redact private report contents.

## Related pages

- [Environment reference](environment.md)
- [LaunchAgent installation](launchd.md)
- [Private profile and Discord planning](profiles-discord.md)
- [Alert rules](alerts-config.md)
