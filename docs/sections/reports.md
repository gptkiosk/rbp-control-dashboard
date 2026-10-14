# Ops reports

The Ops reports page (`ReportsView.vue`) lists Hermes reports from a configured local directory (`MAC_CONTROL_OPS_REPORTS_DIR`) and optionally from a separate Hermes archive (`MAC_CONTROL_HERMES_REPORTS_DIR`). It is read-only: viewing does not generate new reports, enable schedules, invoke a model, or post a message.

## Purpose

For the operator: inspect recent operational reports with their source, timestamp and preview limits, and distinguish current findings from historical archives. For new users: understand the capped catalog (200 previews, 2,000 entries), the 512 KiB preview limit, and the historical warning for reports over 24 hours old. This page supports review decisions before interpreting findings as current service status.

## Screenshots

- Pending capture: `reports-catalog.png` (report list and preview). No RCD capture exists yet. Any example findings in a future capture would not be current live health.

## Controls

### Start here

1. Open Ops reports and choose a report from the selector or list.
2. Check its source and captured time before interpreting its findings. An old report is not current health.
3. Use **Refresh** for new files. Viewing does not generate a report or enable a Hermes schedule.

- **Refresh** (`btn` near `h1 id="reports-title"`) — rescans the configured directories (`/api/reports`, 60-second poll interval) and reloads content for the selected report if a selection exists (`refreshContent`).
- **Report selector** (`AppSelect` with `v-model="selected"`) — selects from the list of reports sorted by modification time (`latest first`). Each option shows `title || name`, `source`, `dateLabel(modified_at)`, and `bytesLabel(size)`. A selected report triggers the content endpoint (`/api/reports/{id}`).
- **Report list** (`nav aria-label="Reports"`) — selectable cards (`button class="card report-row"`) with report name, source, timestamp, size, and a `Too large to preview` label for unreadable files (`!r.readable`). Selecting a card updates the preview.
- **Fleet health** (`OpsHealthPanel`, `section class="card ops-health"`) — reads `/api/ops-collectors` every 60 seconds. It shows the worst severity (`Critical`, `Missing`, `Warning` or `OK`, always as text), the last check time, a seven-day count of fleet health reports, and a search and severity filter. Checks are listed most severe first. Each row shows how long its status has been unchanged, when it was last checked, and a link to the page for its kind (for example `/tasks` or `/mac`). A check with no recent result is labelled `No recent result`.
- **Refresh checks** (in the Fleet health panel) — runs the configured checks on demand through `POST /api/ops-collectors/refresh`. This needs operator sign-in. The checks are deterministic and never call a model. Automatic checks show their schedules and next run, and are off unless the host enables them.
- **Report search and kind filter** — search matches title, file name and source. The kind filter offers all reports, fleet health, archived copies, the Hermes archive or other Ops reports.
- **Archived copies** are labelled `Archived copy · original unchanged`. Archiving copies a report into a labelled folder and does not change the original.
- **Deep links** — **Link to this report** on a selected report and **Open the latest fleet health report** in the panel both open `/reports?report=<id>` and select that exact report.
- **Content preview** (`article class="card report-content"`):
  - Header (`header`) with `h2` (title/name), source (`p class="muted"`), captured time, and size.
  - Historical warning (`p role="status" class="notice-warn"`) when `current.modified_at` is more than 24 hours old (`historical` computed property).
  - Response-only note (`p class="muted small"`) when `content.response_only` is true (original prompt omitted).
  - Markdown preview (`div class="markdown-report"` with `v-html="html"` from `renderReport`) with HTML disabled, nesting limits, HTTP(S) links only (`a` tags only), remote images replaced by text, and no referrers (`referrerpolicy="no-referrer"`).
  - Plain text preview (`pre class="text-report"`) escaped by Vue (`{{ content.content }}`).
- **Empty state** (`div class="card empty"`) — shown when `reports.length === 0`. Displays message (`No reports yet`), the configured root path (`code` with `data?.root`), and availability status (`The report folder is not available yet` when `!data?.available`).

## Settings involved

- `.env` / environment:
  - `MAC_CONTROL_OPS_REPORTS_DIR` — the primary read-only report source directory (`.md`, `.markdown`, `.txt` files, UTF-8). Scanned up to two levels of subdirectories; hidden entries and symlinks excluded. Scan stops after 2,000 entries; up to 200 reports listed (`limited` flag set when capped). Reports over 512 KiB appear in the list (`readable: false`) but cannot be previewed.
  - `MAC_CONTROL_HERMES_REPORTS_DIR` — optional independent archive source (e.g., `~/.hermes/cron/output`). Uses the same descriptor traversal (`O_NOFOLLOW`), depth, UTF-8, byte limit, and symlink refusal. Separate ID namespace; shared cap (`2,000` / `200`). Sources receive readable selector labels. Historical files over 24 hours old display a historical warning; findings are not treated as current service status.
- `alerts.toml`: delivery settings independent of reports; see `docs/sections/alerts.md`.
- LaunchAgent (`com.operator.mac-control`): keeps the service available for `/api/reports` and `/api/reports/{id}`.
- No profile fields (`discord_channel_id`, planning settings) are edited from this page. Report content is never executed; Markdown HTML is disabled and links are restricted to HTTP(S).

## Preview limits and historical state

- Catalog cap: 200 listed reports (`limited` when capped).
- Entry cap: 2,000 scanned entries (`O_NOFOLLOW` descriptor traversal; hidden and symlink entries excluded).
- Preview cap: 512 KiB (`readable` false for oversized files; they appear in the list but show `Too large to preview`).
- Historical warning: reports older than 24 hours show a `notice-warn` banner (`Historical report, more than 24 hours old. These findings describe its captured run, not current health.`). Their findings are not treated as current service status.
- Source namespace: `MAC_CONTROL_OPS_REPORTS_DIR` and `MAC_CONTROL_HERMES_REPORTS_DIR` have separate namespaces (`report.id` is a hash of relative paths). Each uses the same traversal rules.
- Report formats: `.md` / `.markdown` rendered with `markdown-it` (HTML disabled, nesting limit, HTTP(S) links only, remote images replaced by text); `.txt` escaped by Vue (`pre class="text-report"`). Binary or unreadable files produce empty states or errors rather than falling back to unrelated files.
- Hermes cron archive: recognized cron wrappers show the original `Response` (prompt omitted). No instructions are run; original files are never copied, edited or removed.

### Preview configuration notes

- `.env`: `MAC_CONTROL_HOST`, `MAC_CONTROL_PORT`, `MAC_CONTROL_LOG_LEVEL`, `MAC_CONTROL_OPS_REPORTS_DIR`, `MAC_CONTROL_HERMES_REPORTS_DIR`.
- `reports-catalog.png` is the synthetic preview used for documentation; the live directory (`MAC_CONTROL_OPS_REPORTS_DIR`) contains actual `.md`/`.txt` files when reports exist.
- Report previews display the producer’s text; MCD does not automatically detect or redact secrets embedded in that text. Review reports before sharing them or capturing screenshots. Report IDs are hashes; file descriptors use `O_NOFOLLOW`, including when a file changes between listing and reading. Nonregular files cannot be read.
- The catalog and selected content poll once per minute. Refresh requests a new read; the GitHub panel’s separate 60-second cache rule must not be assumed to apply to report files.

## Troubleshooting

- **No reports yet** (`div class="card empty"`) — the configured `MAC_CONTROL_OPS_REPORTS_DIR` is empty, missing, or unreadable. Verify the directory exists and contains `.md`/`.markdown`/`.txt` files. Hermes should write its next actual report into this folder; MCD refreshes once per minute (`poll` interval).
- **Too large to preview** (`small class="muted"` with `Too large to preview`) — the file exceeds 512 KiB (`contentError` or `readable: false`). Open the file directly; MCD does not expand the preview.
- **Historical warning** (`notice-warn`) — the selected report is over 24 hours old (`historical` computed). Its findings describe the captured run, not current health. Do not interpret as current service status.
- **Binary or unreadable file** — produces an empty state or error rather than falling back to unrelated files. Check that the file is UTF-8 text (`.txt`) or Markdown (`.md`/`.markdown`).
- **Content error** (`p class="notice-warn"` with `contentError`) — shows the error text with an optional retention of the last successfully read version. Inspect the file permissions and directory access (`O_NOFOLLOW` descriptor traversal; nonregular files refused).
- **Missing folder safe** — a missing `MAC_CONTROL_OPS_REPORTS_DIR` is safe; no reports are listed and the empty-state card indicates the folder is unavailable (`!data?.available`). The service continues; no crash or fallback occurs.
- **Refresh does not show new reports** — verify Hermes wrote files to the configured directory. The scan stops at 2,000 entries; very large directories may cap results. New files appear on the next catalog read, including the one-minute poll or Refresh.
- **Response-only reports** (`content?.response_only`) — Hermes archive reports omit the original prompt (`Prompt` section omitted). Only the `Response` and recognized cron wrapper details are shown.

## Related pages

- [Overview](overview.md) — alert-delivery status and service/crash-loop attention (independent of reports).
- [Services](services.md) — live service health and crash-loop flags (current state, not historical).
- [Tasks](tasks.md) — work approvals and definitions of done; not the same as operational reports.
- [MCP servers](mcp.md) — agent integrations separate from Hermes reports.
- [Help](help.md) — guide chat does not generate reports or enable schedules.
- Source references: `docs/OPS_PANELS.md` (read-only behavior, `MAC_CONTROL_OPS_REPORTS_DIR`, `MAC_CONTROL_HERMES_REPORTS_DIR`, preview limits, historical warnings, `verify-alert-delivery.py` is independent), `docs/HERMES_ACCESS.md` (independent of reports), `apps/web/src/views/ReportsView.vue` (UI structure and data sources).
