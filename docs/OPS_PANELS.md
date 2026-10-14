# GitHub and ops reports

`/github` reads the repositories available to the current `gh` account and each selected
repository's open pull requests and issues. It uses `gh api --method GET` only and never
changes GitHub authentication or token scopes. The executable is configurable with
`MAC_CONTROL_GH_PATH` (default: the first `gh` found on the service `PATH`; the integration is optional). Sign in through the existing CLI
if necessary; MCD does not request, save, or display a GitHub token.

The catalog includes up to 100 repositories ordered by GitHub's updated timestamp.
Each selected repository shows up to 50 open PRs and 50 issues; issue queries inspect
up to 100 entries because GitHub's issues endpoint also contains PRs. PR entries are
excluded from the issue list. Visible notices mark capped results. Repository, PR and
issue links open their canonical github.com URLs. MCD displays summaries, without bodies,
diff contents, secrets, or workflow logs. CI status is outside this phase's scope.

Queries are cached for 60 seconds, including failures, and concurrent requests are
coalesced. Each CLI query has a 12-second timeout and accepts up to 4 MiB of output.
PR and issue refresh failures independently retain their last successful result and
show the time of that result with a warning. Refresh checks the cached source again;
it does not bypass the 60-second protection against bursts. No background GitHub calls
are made until a signed-in operator visits the panel.

`/reports` lists Hermes reports from the directory set by
`MAC_CONTROL_OPS_REPORTS_DIR`. Write `.md`, `.markdown`, or UTF-8 `.txt` files there.
The root and two levels of subdirectories are scanned, excluding hidden entries and
symlinks. The scan stops after 2,000 entries and lists up to 200 reports sorted by
modification time, latest first. Capped results are marked. Reports over 512 KiB appear
in the list but cannot be previewed. Missing, unreadable, binary, or removed reports
produce clear empty states or errors rather than falling back to unrelated files.

Report IDs are hashes of indexed relative paths; the API accepts no arbitrary file path.
File and directory descriptors use `O_NOFOLLOW`, including when a file changes between
listing and reading. Nonregular files cannot be read. Markdown uses markdown-it with
HTML disabled, a nesting limit, HTTP(S) links only, and remote images replaced by text.
Links omit referrers; opening one is an explicit operator action. Plain text is escaped
by Vue. Report content is never executed. Both APIs and pages require the same Google
session as the rest of MCD when sign-in is enabled.

A missing report folder is safe. Hermes should write its next actual report into this
folder; MCD refreshes it once per minute. Verification fixtures belong in the isolated
preview data directory, never in the live ops report folder.

## Hermes cron reports

`MAC_CONTROL_HERMES_REPORTS_DIR` optionally adds an independent read-only report source.
On this Mac it is set to `~/.hermes/cron/output`, beside the existing ops-reports folder.
Sources receive separate ID namespaces, with one shared 2,000-entry / 200-preview limit.
Each source uses the same descriptor traversal, depth, UTF-8, byte-limit and symlink refusal.
Hermes job headers provide readable selector labels. Recognized cron wrappers show the original
run header and recorded Response, omitting the Prompt section. No report instructions are run.
The original files are never copied, edited or removed. Files over 24 hours old display a
historical warning; their findings are not treated as current service status.

The latest actual archived fleet report is September 14, 2026. Morning Fleet Health Check,
Evening Log Review and Weekly Fleet Maintenance jobs are currently disabled in Hermes.
Connecting their output archive does not enable them, schedule a new job, invoke a model or
post a message. New files will appear on the next catalog poll whenever the report producer
writes them. Restoring scheduled report production remains a separate operator decision.

## Deterministic Ops collectors (prototype)

The Ops health panel on `/reports` shows results from the deterministic collectors. These run
allowlisted checks with no model and report only changes. Configuration, sources, schedules and
limits are in [Ops collectors configuration](configuration/ops-collectors.md). That page is a draft
for story `s2-docs`. The application is unreleased, the collector design awaits human approval, its
tests have not been run, and the Pi hardware test is blocked. The replacement schedules ship disabled.
