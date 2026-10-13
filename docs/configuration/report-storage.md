# Host report storage

Ops reports are local, read-only Markdown or UTF-8 text previews. Configure this
installation from **Settings → Host report storage**, **Setup → Host report
storage**, or **Ops reports → Host report storage**. An authenticated operator
can save folders; agent grants and unsigned local users cannot change them.
The folder is on the dashboard host, even when your browser is on another device.

## Install and configure

1. Give each installation a separate `MAC_CONTROL_DATA_DIR`. With no report
   override, Ops reports use `<data_dir>/reports`, including custom runtime paths.
   MCD's current-user default is `~/.mac-control`; RCD's is `~/.rcd-control`.
   Existing RCD installations using the older default should explicitly keep
   `MAC_CONTROL_DATA_DIR` pointed at their existing runtime to preserve their DB.
   Do not copy or modify a running installation's DB for previews.
2. Create dedicated report folders with permissions allowing the dashboard's
   service account to read them. Avoid home roots, private configuration,
   credential folders, hidden folders and symlinks (including ancestor symlinks).
   Use a physical path: for example `/private/tmp` rather than a symlinked `/tmp`
   on hosts where that distinction exists.
3. In the service environment, set `MAC_CONTROL_REPORTS_ALLOWED_ROOTS` to a JSON
   array of dedicated absolute local folders. The default `<data_dir>/reports`
   and explicitly set `MAC_CONTROL_OPS_REPORTS_DIR` and
   `MAC_CONTROL_HERMES_REPORTS_DIR` are also approved roots, subject to the same
   safety checks. Do not allowlist a whole home directory or a whole runtime.
   The optional macOS LaunchAgent installer persists `MAC_CONTROL_DATA_DIR`
   and the three report variables from its invocation environment in the plist.
   Run that installer only during an operator-approved maintenance window: it
   reloads the service. On Linux, supply these variables through the service
   manager’s environment configuration.
4. After installing the service environment, sign in and open Host report
   storage. Select an existing folder within an approved root and save.
   Changes apply immediately to report reads. New environment/allowlist values
   take effect on the next operator-scheduled service start; this workflow does
   not restart active jobs. Leave Hermes blank to disable its source.
5. Restore installation defaults to remove UI overrides and use the service's
   report environment values, falling back to `<data_dir>/reports` for Ops.

The `MAC_CONTROL_` prefix is retained on both products for compatibility. Each
product reads its default dotenv from its own default runtime directory, not
from a custom `data_dir`. For custom installs, supply the service environment
explicitly; changing `data_dir` does not relocate the dotenv automatically.

Portable synthetic service-environment example (adapt paths to the host):

```sh
# Separate host installations; use ONE data directory per service.
MAC_CONTROL_DATA_DIR=/srv/dashboard/mcd-runtime
# For RCD instead: /srv/dashboard/rcd-runtime
MAC_CONTROL_REPORTS_ALLOWED_ROOTS='["/srv/dashboard/report-output","/srv/dashboard/hermes-archive"]'
MAC_CONTROL_OPS_REPORTS_DIR=/srv/dashboard/report-output
MAC_CONTROL_HERMES_REPORTS_DIR=/srv/dashboard/hermes-archive
```

No username, developer checkout, credentials, Lima mount or VM is required.
Lima can be used as disposable test infrastructure; it is not a production
component. Existing environment-only report configuration continues to work.
A dedicated Hermes archive may be selected; for an existing `.hermes` runtime,
only its `cron/output` subtree is permitted, never the whole Hermes runtime.

## States and precedence

| Label | Meaning |
|---|---|
| Default | Ops derives its folder from this installation's `data_dir`. |
| Configured | A host environment value or saved operator folder is selected. |
| Disabled | No Hermes archive is selected. |
| Unavailable | Selected folder is absent, unreadable, unsafe or not approved. |

Mode and availability are shown independently, including when the report list
is empty. An empty readable folder is available and simply has no reports yet.
Saved UI overrides take precedence over environment defaults. They are stored
in `<data_dir>/report-storage.json` with mode 600, separate from profile exports
and the database. An invalid saved file fails closed until an operator repairs
or resets it. Error messages never include OS exception details or submitted
path values. Selected source paths are visible to dashboard users, as before;
use folder names suitable for that audience.

## Filesystem boundary

The operator endpoint cannot expand the host-installed allowlist. Report roots
and every ancestor are opened with directory descriptors and `O_NOFOLLOW`.
Nested directory and file reads also reject symlinks. Hidden entries and common
private/credential folder and file names are excluded. This protects the
filesystem boundary; the installer must still approve dedicated report output
folders rather than arbitrary trees. Reports remain capped at 200 listed
files and 512 KiB per preview, with UTF-8 validation, escaped Markdown, no remote
images, and Hermes job prompts omitted from displayed archive responses.
Saving configuration writes only the host settings file; it never creates,
modifies, moves or deletes reports. Producers must be configured separately to
write to the chosen folders. Subscriptions, native agent routes, spending caps
and messaging settings are unaffected.

## Isolated preview

With API dependencies installed and the web app built, this optional synthetic
preview uses only report routes, a synthetic operator, and its own local files:

```sh
# From this repository; choose an unused loopback port and a fresh runtime.
apps/api/.venv/bin/python scripts/preview-report-storage.py \
  --data-dir /srv/dashboard/isolated-report-preview --port 8893
# Open http://127.0.0.1:8893/reports on the host.
```

Use a different runtime and port for each product. It does not read host dotenv,
create a database, load agent workers, read credentials, or send messages. It is
for local UI QA only; never install it as the production service. Stop only its
own preview process after review. Some managed environments prohibit binding
ports; that requires running the preview in an authorized local environment.
