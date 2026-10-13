# MCP servers and agent access

The MCP page (`McpView.vue`) manages server registrations and Hermes planning grants separately. MCP server changes are requests that must be approved; agent access grants are expiring permissions reviewed on the same page. The MCD stdio tool server (`apps/mcp/mcd_server.py`) provides bounded task-board access to Hermes without exposing logs, chat, billing, credentials or integration settings.

## Purpose

For the operator: register an agent's MCP server, approve or reject pending changes, and review the Hermes access grant. For developers: understand the stdio server's loopback-only security model (`MCD_URL`, `MCD_TOKEN_FILE`, mode-600 token file) and the difference between Read and Read + planning drafts grants. This page supports decisions about tool integrations and agent planning access.

## Screenshots

- Pending capture: `mcp-server.png` (server table). No RCD capture exists yet.
- Pending capture: `mcp-server-request-dialog.png` (request form). No RCD capture exists yet.
- Pending capture: `mcp-grants-dialog.png` (access review). No RCD capture exists yet.

## Controls

### Start here

1. Open MCP and use **Request a server** to prepare the command/URL and named environment variables.
2. Review the pending request under **Changes**, then approve or reject it. Confirm the final change status; a normal CLI exit alone is not proof of a successful registration.
3. Review Hermes access separately. Choose the smallest needed Read/Draft scope and expiry, approve the grant, and revoke it when no longer needed.

### Servers list (`/mcp`)
- **Refresh** (`btn` with `AppIcon name="refresh"`) — reloads the server catalog and runs a health-check probe on every server. Slow.
- **Request a server** (`btn primary`) — opens `RequestServerDialog` (`showRequest`). Select agent, server name, stdio command/arguments or HTTP URL (`spec.transport`), and named environment variables (`env_names` only — no secret values).
- Per-agent server table (`table class="data-table servers"`): Name, Transport (`mono`), Target (`mono` with optional `env` details), Status (`ChipTag` with tone from `mcpAgentLabel`), Source, Action (`Remove` for removable servers; managed connectors show "Managed in claude.ai").
- Notice banner (`notice` with tones `ok` / `warn` / `danger`) shows the result of requests or approval actions.
- **Changes** (`section aria-labelledby="changes-title"`): pending change rows with `Add` / `Remove` badges, spec (`mono`), environment variable names (`env-names`), created/decided times, `Approve` and `Reject` buttons (`btn primary` / `btn danger`), and expandable `Output` (`pre class="mono out"`) for failed changes.

### Agent access (`AgentAccessPanel.vue`)
- **Agent access** header with "Review Hermes access" button (`btn`). Disabled when `!auth_enabled` or `busy`.
- Grant list (`ul`): Hermes scope (`Read only` or `Read + planning drafts`), state (`badge`), expiry (`dateLabel`), last used, and `Revoke access` button (`btn`).
- **Review Hermes access** (`ModalShell`): select scope (`AppSelect`: `read` or `draft` with descriptions) and expiry (`AppSelect`: `1`, `7`, `30` days). Notes explain that draft access cannot queue/start runs, approve/complete/delete tasks, or change integrations; chat, logs, billing and credentials stay outside this access. `Approve Hermes access` applies a new grant; `Cancel` closes without writing.
- **Local MCP setup** (`details` / `summary`): shows the private token file path (`code`) and notes that its contents are never shown in the UI.
- Notice messages confirm approval (`Hermes access approved. ...`) or revocation (`Access revoked. Hermes requests ... refused immediately.`).

### MCD stdio server (`apps/mcp`)
- Normal invocation: `.venv/bin/python mcd_server.py` (stdio). The server runs over stdio, not a public port.
- Registration uses a separate pending MCP change (`RequestServerDialog`). After approval, refresh the server list and verify the result.
- Tools: `list_tasks`, `get_task`, `create_task`, `update_task`, `add_dependency`, `remove_dependency`, `list_agents`. Read access exposes task descriptions, definitions of done, dependencies, agent metadata (`/api/agent-tools`). Draft access creates Backlog tasks and edits/links dependencies only on Hermes-created Backlog drafts.
- Queue/status requests through the server are refused before changing anything; they never create a partial queued task. The operator queues work, approves tasks and marks completion.

## Settings involved

- `.env` / environment:
  - `MAC_CONTROL_HOST` (default `127.0.0.1`; `0.0.0.0` only after auth enforced).
  - `MAC_CONTROL_PORT` (default `8800`).
  - `MAC_CONTROL_LOG_LEVEL`.
- MCP server (`mcd_server.py`):
  - `MCD_URL` — must be an explicit HTTP loopback address and port (`http://127.0.0.1:8800` by default). No username, password, path, query or fragment allowed; proxy and redirect are refused.
  - `MCD_TOKEN_FILE` — private credential file for isolated testing. Default: `~/.mac-control/agent-tokens/hermes.token`.
  - Token file rules: regular file (`S_ISREG`), owned by the same user (`st_uid == os.getuid()`), mode exactly `0o600`, content 64 characters from the allowed set (`A-Z`, `a-z`, `0-9`, `_`, `-`). Read with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` (`credential()` in `mcd_server.py`).
- Agent access (`AgentAccessPanel.vue`):
  - Scope (`read` / `draft`) and expiry (`1` / `7` / `30` days) selected in the review dialog.
  - Grant writes the private file at the configured `token_file`. SQLite migration `0009` stores only the SHA-256 hash and permission/audit metadata; the API and UI never return the secret.
- MCD server security:
  - Reads the private file before every request.
  - Bearer requests accepted only on a direct local connection (`127.0.0.1` or `::1`) without `Origin` or forwarded headers.
  - Invalid bearer never falls back to the operator browser session.
  - Tokens do not access the normal operator API, approval routes, tailnet requests or browser pages.

## Hermes access subsection: grants and the stdio server

### Grant behavior (merged from `docs/HERMES_ACCESS.md`)

- Read access exposes task descriptions, definitions of done, dependencies, task configuration and limited agent metadata through `/api/agent-tools`. It does not expose run commands, logs, result text, chat content, billing, Google sessions, credentials or integration settings.
- Draft access additionally creates Backlog tasks and edits or links dependencies only on Hermes-created Backlog drafts. Working-directory allowlists, field validation, approval flags, self/cycle checks and human-task rules still apply.
- Only the operator queues work, changes status, approves tasks, deletes tasks or starts/cancels runs. Queue/status requests through MCP fail before changing anything; they never create a partial queued task.
- A grant writes the token file (`mode 600`) inside an owned directory (`mode 700`). Only its SHA-256 hash and permission/audit metadata are stored in SQLite (`migration 0009`). The API and UI never return the secret value.
- Creating a new grant revokes all previous Hermes grants. Revoke is immediate on the next request; expiration is enforced server-side. Revoked file contents do not confer access.
- Agents cannot renew or broaden grants. The local admin recovery token and browser session cookie must never be supplied to Hermes.

### MCD stdio server (merged from `apps/mcp`)

Register Hermes's MCD server only through the separately approved pending MCP change (`RequestServerDialog` / `/mcp#changes-title`):

- Command: `<REPOSITORY_ROOT>/apps/mcp/.venv/bin/python`
- Argument: `<REPOSITORY_ROOT>/apps/mcp/mcd_server.py`
- No credential arguments or environment secret values are needed in the request.

Hermes asks to enable discovered tools during registration (e.g., version `0.21.5`). After operator approval, MCD supplies one default answer, requires the CLI's saved-config receipt, and checks the persisted server listing. Cancellation, failed discovery, or a missing registration is a failed change even if the CLI exits zero. Existing-server overwrite and failed-probe save prompts default to No; MCD does not repeatedly answer confirmation prompts.

The server's environment is isolated:

- `BASE_URL` derived from `MCD_URL`; only explicit loopback IPs (`127.0.0.1`, `::1`) with a port.
- Inherited proxy settings are ignored (`ProxyHandler({})`).
- `NoRedirect` handler refuses redirects.
- Route guard: only `/api/agents` and `/api/cards` (with `/api/cards/{id}`) are allowed; everything else raises a `McdError`.
- Internal task/agent paths are remapped to `/api/agent-tools/tasks` and `/api/agent-tools/agents`. The request header includes `X-Mac-Control: 1` and the private bearer credential; responses are parsed as JSON. Credentials must never be copied into docs, screenshots or agent prompts.

Tests (`tests/test_mcd_server.py`) use temporary grants and temporary databases. The stdio proof invokes the tool server directly (`.venv/bin/python mcd_server.py`), without invoking Hermes's model or changing its configuration.

### Additional configuration notes

- `.env`: `MAC_CONTROL_HOST`, `MAC_CONTROL_PORT`, `MAC_CONTROL_LOG_LEVEL`, `MAC_CONTROL_COLLECTOR_ENABLED`.
- `alerts.toml`: delivery and outbox settings (independent of MCP; see `docs/sections/alerts.md`).
- Profile fields: `discord_channel_id` (delivery destination, not edited on this screen), planning preferences.
- LaunchAgent (`com.operator.mac-control`): keeps the service running so the loopback server is available for MCP access.
- MCP-specific environment:
  - `MCD_URL` (loopback only, explicit port).
  - `MCD_TOKEN_FILE` (optional isolated test file).
  - `MAC_CONTROL_GH_PATH` (GitHub CLI path, referenced in other integrations, not used by the stdio server directly).
- Agent access settings (not stored in `.env`): scope and expiry choices in the review dialog; grant state tracked in `agent-access` endpoint and SQLite (`migration 0009`).

## Troubleshooting

- **No change requests yet** (`p class="muted small" data-testid="no-changes"`) — create one with `Request a server`. If nothing changes after approval, verify `serve.py` is running on the configured loopback port.
- **Failed change** (`ChipTag tone="danger"` + `Output` expanded) — inspect the output in `pre class="mono out"`. Common causes: incorrect transport, missing command/URL (`specTarget`), unreachable server, or failed probe after save. The CLI may exit zero while MCD reports failure; rely on the change status.
- **Access expired or revoked** (`McdError` message: "MCD access expired or was revoked ...") — open the Agent access panel (`AgentAccessPanel.vue`), review any active grants (`grant.state`), and approve a new one if needed. A revoked grant is refused immediately; an expired grant requires operator review.
- **Could not load servers** (`p class="error-text"`) — check that `serve.py` is running and `MAC_CONTROL_HOST`/`MAC_CONTROL_PORT` match `MCD_URL`. Verify no proxy or redirect intercepts the loopback connection.
- **Token file invalid** (`credential()` raises `ValueError`) — verify file exists, is a regular file (`S_ISREG`), owned by the current user (`os.getuid()`), mode exactly `0o600`, content exactly 64 allowed characters. Do not use the admin recovery token or a browser cookie as `MCD_TOKEN_FILE`.
- **Draft access creates Backlog drafts but queue/status requests fail** — this is the intended behavior. Only the operator can queue work, approve tasks, or mark completion. The server refuses `queue=true` in `create_task`.
- **No environment variables shown for a server** — the request form names variables (`env_names`) without values. Supply their values privately in the Mac's MCD configuration, not in the request.
- **Server status shows `failed`** — refresh (`loadServers(true)`) to rerun the health check. If the server command or URL changed, submit a new change request rather than editing the existing server directly.

## Related pages

- [Agent access reference](../configuration/auth-google.md) — authorization and session context.
- [Agent usage and billing](agents.md) — agent availability, model usage, subscription settings (not exposed through MCP).
- [Tasks](tasks.md) — task board, approvals, dependencies, and the `Backlog` / `queued` / `running` / `review` / `done` / `failed` columns the server interacts with.
- [Projects](projects.md) — planning work and shared memory outside the server's scope.
- [Ops reports](reports.md) — Hermes reports and archive sources, independent of the MCP server.
- [Help](help.md) — token-free guide chat; does not run agents or grant permissions.
- Source references: `docs/HERMES_ACCESS.md` (grant rules), `docs/OPS_PANELS.md` (reports and previews), `apps/mcp/README.md` (server overview), `apps/mcp/mcd_server.py` (loopback security and tool definitions).
