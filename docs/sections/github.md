# GitHub repositories, PRs and issues

The GitHub page (`GithubView.vue`) reads accessible repositories from the existing `gh` CLI login and displays open pull requests and issues for a selected repository. It is read-only: no PR merges, issue edits, token scope changes, or repository modifications occur through this panel.

## Purpose

For the operator: inspect open work across repositories using the existing GitHub account without leaving the dashboard. For new users: understand the search, selection and refresh flow, and what the capped results and stale-state warnings mean. This page supports review decisions before opening an item on `github.com`.

## Screenshots

- Pending capture: `github-repo.png` (repository view). No RCD capture exists yet. Repository search and PR/issue detail controls appear only after a catalog is available.

## Choosing which repositories to show

Open **Settings > GitHub** (also in the setup wizard). Enter the GitHub account that is already signed
in with `gh` on the host and its repositories appear as a checklist, newest first, with private and
archived ones marked. Tick the ones to show, use **Select all** or **Clear**, and search when the list is
long. Repositories already saved are ticked for you. A saved name that is not in the account's list (another
owner, or a name GitHub no longer shows) stays visible and marked so it can be removed. To add a repository
from another owner, use **Add a repository by name**.

Saving checks that each name exists for the signed-in login and suggests the closest match for a
misspelling. On the GitHub page, a repository that cannot be read is named with the reason (not found, access
refused, or temporarily unreadable) while the others keep loading.

## Controls

### Start here

1. Open GitHub, select an accessible repository, then inspect its open PRs and issues.
2. Use search to narrow the catalog and **Refresh** to check again. Read any stale/capped-result notice.
3. Open the canonical GitHub link for actions outside this read-only panel.

- **Refresh** (`btn` near `h1 id="github-title"`) — reloads the repository catalog (`/api/github/repos`, 60-second poll interval) and, if a repository is selected, its open PRs and issues (`/api/github/repos/{name}`). Concurrent requests are coalesced.
- **Search** (`input type="search"` in `.repository-controls`) — filters repositories by name or description (case-insensitive). Empty result shows a muted message.
- **Repository selector** (`AppSelect` with `v-model="selected"`) — selects a repository from the catalog. When the selection changes, the detail endpoint (`/api/github/repos/{selected}`) loads open PRs (`pulls`) and issues (`issues`).
- **Repository cards** (`button class="card repo-card"`) — selectable cards showing `r.name`, `r.description`, visibility (`Private` / `Public`), branch (`r.branch`), and archived status. Clicking selects the repository.
- **Details section** (`section class="repository-detail"`) — shows the repository name (`h2`), a direct `github.com` link (`a` with `target="_blank"` and `referrerpolicy="no-referrer"`), PR/issue grids (`work-grid` with `GithubWorkList` components for PRs and issues), and any detail-level warnings.
- **Link behavior**: repository links and individual PR/issue links open canonical `github.com` URLs; no referrer is sent by MCD links (`referrerpolicy="no-referrer"`). MCD displays summaries without bodies, diff contents, secrets or workflow logs.

## Settings involved

- `.env` / environment:
  - `MAC_CONTROL_GH_PATH` — path to the `gh` executable (default: the first `gh` found on the service `PATH`; optional). Used by the backend to list repositories and open work; not part of the web UI settings.
- Profile / account: uses the existing `gh` CLI authentication. MCD does not request, save or display a GitHub token. No `token_file`, `secret` or `env_names` value is shown in the UI.
- General host, port and sign-in settings also govern access to the panel; `MAC_CONTROL_GH_PATH` specifically selects its CLI executable.
- LaunchAgent (`com.operator.mac-control`) must keep the service running so `/api/github/repos` responds.

## Troubleshooting

- **Not signed in / no repositories available** (`div class="card empty"` with message "No repositories available") — verify the `gh` CLI login (`gh auth status`). The page relies on that existing login; MCD does not manage it.
- **Limited catalog** — the “First 100 repositories” notice marks the capped catalog. Selected repositories show up to 50 open PRs and 50 issues. This is a bounded read-only result, not the entire account history.
- **Stale results** (`dateLabel(data?.checked_at ?? null)` shows an older time) — click **Refresh** to check again. The 60-second cache applies to both success and failure responses; concurrent requests are coalesced.
- **PR/issue refresh failure** (`p class="notice-warn"` with `detailError`) — the last successful result is retained with a warning and the time of that result shown. Refresh checks the cached source again; it does not bypass the 60-second protection.
- **Empty open-work grids** — the selected repository may have no open PRs or issues at the time of query. This is a state, not an error.
- **No PR/issue links open** — links point to `github.com` with `target="_blank"`; verify browser permissions and the external link is not blocked.
- **Partial results warning** (`p class="notice-warn"` with `repos.length` shown) — indicates capped results or an error state. Inspect the message text for whether it refers to a connection problem or a cap.

## Related pages

- [Overview](overview.md) — live fleet status; does not include repository work.
- [Tasks](tasks.md) — work that may reference repositories; approval flows are separate from GitHub viewing.
- [Projects](projects.md) — planning and dependencies independent of repository work.
- [MCP servers](mcp.md) — tool integrations separate from GitHub read-only access.
- [Ops reports](reports.md) — Hermes reports; independent of repository state.
- Source references: `docs/OPS_PANELS.md` (GitHub read-only behavior, `gh api --method GET`, no token scope broadening, cached query limits), `docs/HERMES_ACCESS.md` (independent of repository work), `apps/web/src/views/GithubView.vue` (UI structure and data sources).

## External-action backend

The current page remains read-only. The separate [external-action guard](../configuration/github-actions.md) requires an exact operator preview and individual authorization, stores an audit and suppresses duplicates. Host writes default to disabled; task/project approvals do not authorize GitHub sends. No send UI or live-provider verification is claimed.
