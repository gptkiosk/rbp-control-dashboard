# PEA companion access: work to be done

Status: **proposed, not built.** This page describes work for RCD (and, by the parity rule, MCD in the same release). Nothing in this pull request changes application code. It was written from the public source of both dashboards at release 0.6.92 and from PEA Web at commit `db399bbaa0e4`. No running dashboard was contacted to write it.

## Why

PEA is the operator's personal assistant ([PEA Web](https://github.com/gptkiosk/pea-web), public). In its chat the assistant already proposes story-sized work that the operator reviews, and its Harvest workspace gathers what came of each conversation. The operator wants a project proposed in PEA's chat to be built by this dashboard's project engine, watched from PEA's board with the agent, model, time and cost of each story, and registered in Harvest when it ends.

The agreed division of work:

- **PEA drafts and watches.** It can list templates, leave a draft, and read projects and their progress.
- **RCD plans, approves and runs.** Planning, the standards check, model routes, spending acknowledgement, submission, dispatch, handoff acceptance and every run stay in RCD's own pages, decided by the operator there.

PEA's own rules forbid unattended workers, so it must never be able to start, approve or pay for work. The existing rule here is the same: agent tokens cannot approve plans, submit projects or accept handoffs. This work keeps both.

## What exists on the PEA side

Merged in [gptkiosk/pea-web#90](https://github.com/gptkiosk/pea-web/pull/90). The rules are the `projects` section of [`browser/server/contract.json`](https://github.com/gptkiosk/pea-web/blob/db399bbaa0e4905b3b2a56cf4f6ed1891e5e35ce/browser/server/contract.json); the operator-facing description is in [Self-hosting, "Project engine"](https://github.com/gptkiosk/pea-web/blob/db399bbaa0e4905b3b2a56cf4f6ed1891e5e35ce/browser/docs/SELF-HOSTING.md); the tests, with a stand-in engine that shows exactly what PEA sends and accepts, are in [`browser/server/conformance/run.py`](https://github.com/gptkiosk/pea-web/blob/db399bbaa0e4905b3b2a56cf4f6ed1891e5e35ce/browser/server/conformance/run.py) (class `Engine` and the tests named `test_*project*` and `test_*engine*`).

PEA's gateway (a small local server, in Python and in Swift) makes **one** kind of request to the dashboard:

```
POST /api/pea-projects
Authorization: Bearer <64 URL-safe characters>
Content-Type: application/json
Accept: application/json
User-Agent: PEA-Gateway/1 (projects its owner reviewed)
```

- It sends no `Origin`, `Referer`, `Cookie` or forwarded header of its own, follows no redirect, waits at most 20 seconds, and accepts at most 500,000 bytes.
- The body is exactly one of the five requests below. Text limits: `title` 200, `brief` 20,000, `constraints` 10,000 characters; `type` matches `[a-z0-9][a-z0-9-]{0,39}`; `project` is a whole number from 1 to 2,147,483,647.
- It accepts only `200` with `Content-Type: application/json`, no `Content-Encoding`, and a JSON **object** as the body. It passes that object to the operator's page unchanged, as data.
- `401` or `403` is shown as "access not accepted"; `400`, `404`, `409` or `422` as "request not accepted"; anything else as "failed". **The response body of a failure is discarded**, so error text is for this dashboard's own audit log, not for the operator in PEA.
- The address is set by the operator when PEA's gateway starts: plain HTTP to a loopback IP on the same machine, or HTTPS to a named host (certificate checked). The credential is read from a private file (mode 0600) before each request.

| Request body | Meaning |
| --- | --- |
| `{"action":"types"}` | The project templates the operator may choose from. |
| `{"action":"list"}` | The operator's projects. |
| `{"action":"get","project":N}` | One project's brief and plan, for reading. |
| `{"action":"status","project":N}` | One project's progress, story by story. |
| `{"action":"draft","type":"…","title":"…","brief":"…","constraints":"…"}` | Leave a draft project. `constraints` may be absent. |

## Work needed here

### 1. A PEA grant

A new operator-approved grant beside the Hermes one (see [Hermes access](../HERMES_ACCESS.md) and `apps/api/agent_access.py`).

- Agent name `pea`, with two scopes: **Read** (`types`, `list`, `get`, `status`) and **Read + drafts** (adds `draft`). Default Read. Expiry 1, 7 or 30 days, revocable at once, a new grant replacing the old one, exactly as for Hermes.
- The credential is 64 URL-safe characters (PEA refuses any other shape), written to `agent-tokens/pea.token` in the data folder as a regular file, mode 600, in the owned mode-700 directory. Only its SHA-256 hash and audit metadata are stored. The API and UI never return it.
- The grant is bound to the operator profile that approved it. That profile is the identity used for every PEA request (`created_by`, ledger entries). There is no Discord identity involved.
- The review dialog on the MCP page (Agent access) names the scope, the expiry and what PEA cannot do. The setup note shows the token file path and the two options the operator gives PEA's gateway (`--projects-url`, `--projects-token-file`), never the credential.

Why a separate grant and not the Hermes bridge credential: the bridge credential is per installation, is tied to a linked Discord account and channel, and allows actions PEA must not have (`plan`, `pause_dispatch`, `record_handoff`, `issue_task` and others). Each credential serves its own interface.

### 2. The endpoint `POST /api/pea-projects`

A new router (suggested `apps/api/routes/pea_projects.py`), not a new action on `/api/hermes-projects`.

- Request model with `extra='forbid'`: `action` is one of the five; the other fields as in the table. Anything else is `422`. There is no `working_dir`, `request_planning`, `planning_bias`, agent, model, revision or route in this model, and none may be added without the operator's decision.
- Authorize before the body is read: method and exact path, the grant's hash, expiry and revocation, then the scope for the action. Missing or wrong credential `401`; a valid grant used outside its scope `403`. An invalid bearer never falls back to a browser session, as now.
- Reuse the existing project code, calling it with the grant's operator profile:
  - `types`: what the bridge's `types` action returns (id, label and delivery summary of each template the operator may pick). Templates stay data here; PEA does not copy the store.
  - `list`: id, title, state and revision, newest first, at most 50, for that operator.
  - `get`: title, brief, constraints, type, state, revision and the story titles of the current plan. No working directory path, branch name, host name, account identity, credential name, run command, log or chat text.
  - `draft`: creates a project in the **draft** state through the same code as the bridge's `intake`, with `request_planning` false, in the **scratch area** only, recorded as created by the operator's profile with source `pea`. It starts no planning, no coordinator review, no repository setup and no model call. The key check that suggests missing keys must not block or prompt here. Answer with the new project's id, title, state, revision and the path part of its Projects URL (for example `/projects?project=12`); PEA joins it to the address it already has.
  - `status`: see the next section.
- Idempotency: a repeated identical `draft` within a short window (same title, brief and type from the same grant) returns the first project and creates nothing. PEA does not retry by itself, but an operator can press twice.
- Limits: at most one PEA request at a time is expected. Add a small rate limit and a cap on drafts per day for the grant, answered with `409` when reached.
- Audit: each refusal goes to `security-audit.jsonl` as other refusals do; each `draft` adds a ledger entry naming PEA and the grant id; `last_used_at` is updated.

### 3. The `status` answer

PEA's board shows one card per story. Proposed shape, built from data that already exists (`Run.model_requested`, `model_reported`, `started_at`, `duration_s`, `cost_usd`, the card's column and agent):

```json
{
  "project": 12, "title": "…", "state": "active", "revision": 3,
  "updated": 1794000000,
  "totals": {"stories": 8, "done": 3, "seconds": 1260, "cost_usd": 0.42, "cost_known": false},
  "stories": [
    {"key": "s1", "title": "…", "state": "review", "agent": "claude", "model": "…",
     "kind": "agent", "needs_operator": true, "started": 1794000000,
     "seconds": 420, "cost_usd": 0.12, "billing": "api"}
  ],
  "url": "/projects?project=12"
}
```

- `state` per story uses the board's own column names. `needs_operator` is true when the story waits for an approval, a decision or a handoff review, so PEA can say "waiting for you in RCD" and link there.
- `model` is the reported model when there is one, otherwise the requested one. `billing` is `subscription`, `api` or `free`, so a subscription run is not shown as costing nothing. `cost_usd` is null when unknown, and `totals.cost_known` is false if any story's cost is unknown. Never estimate.
- `seconds` is run time, summed over a story's attempts. No result text, handoff text, logs, commands, file paths or branch names.
- Keep it bounded: at most 200 stories, titles cut to 200 characters. PEA accepts 500,000 bytes.
- Today the bridge's `status` is behind the Discord diagnostics switch. For PEA it is covered by the Read scope of the grant instead.

This shape is a proposal. PEA has no page that reads it yet, so it can still change; say so in the pull request if a different shape fits the existing code better, and it will be matched on the PEA side.

### 4. Admitting the request

Two existing checks would refuse PEA today.

- **Operator boundary** (`apps/api/operator_boundary.py`, the middleware in `apps/api/main.py`). `/api/pea-projects` with a bearer credential must be admitted the way `/api/hermes-projects` is, and must stay refused for agent processes: a story's runner must not be able to read the PEA token file and use it to leave drafts or read other projects. PEA's gateway is not an agent process; a request from a process in an agent's tree is refused with 403 and audited even with a valid PEA credential.
- **Local-only rule** (`agent_access.local_request`). It requires a loopback client, a loopback `Host`, and no `Origin` or forwarded headers.
  - **Same machine** (PEA and the dashboard on one computer): PEA's request already satisfies this rule. Nothing to relax.
  - **Another machine** (for example the dashboard on a Raspberry Pi, PEA on a Mac, reached through `tailscale serve` as in [Remote access](../configuration/remote-access.md)): the request arrives from the loopback proxy with forwarded headers and the HTTPS host name, so it is refused. This needs an explicit, off-by-default setting, for example `MAC_CONTROL_PEA_REMOTE=true`. With it on, a PEA-credential request to exactly `/api/pea-projects` is also accepted when the client is loopback, there is no `Origin` header, and `Host` is the host of an origin already listed in `MAC_CONTROL_AUTH_ORIGINS`. It applies to this one path and this one credential only; the Hermes and agent-tools rules do not change. It must not be reachable through a public (Funnel) route, and the docs must say so.

The remote case is a security decision for the operator, not for an agent: implement it behind the setting, default off, and leave turning it on to them.

### 5. Interface and documentation

- MCP page, Agent access: a PEA row with scope, state, expiry and last use; **Review PEA access**; **Revoke access**.
- Projects: a draft that came from PEA says so ("Drafted from PEA") until the operator saves a revision. Nothing else about the project flow changes.
- Docs: a `docs/PEA_ACCESS.md` in the style of [Hermes access](../HERMES_ACCESS.md), a section in the MCP page guide, the new setting in the environment reference, and a CHANGELOG entry. Replace this page with a link to it when the work is done.
- UI changes need the reachable preview described in [UI testing](ui-testing.md).

### 6. Tests

With temporary databases and grants, and no model call:

- Grant: issue, replace, expire, revoke; file mode and directory mode; hash only in the database; the credential never in a response.
- Each of the five actions with a valid grant; `draft` refused under Read scope; every unknown action and every extra field refused; the 64-character shape enforced.
- `draft` creates exactly one draft project in the scratch area, with no task on the board, no planning run and no ledger entry other than its own; the duplicate window returns the same project.
- `get` and `status` contain none of the excluded fields, including for a project with failed runs and unknown costs.
- A request from an agent process tree is refused with a valid PEA credential and audited.
- A browser session, the Hermes credential and the bridge credential are each refused on this path; the PEA credential is refused on `/api/hermes-projects`, `/api/agent-tools/*` and every operator route.
- Remote setting off: a forwarded request is refused. On: accepted only for a listed origin's host, no `Origin` header and this path.
- Answers stay under 500,000 bytes for a 200-story project.

An end-to-end check against PEA can use PEA's own conformance suite as the client side; it needs no PEA code in this repository.

## Out of scope

- Any way for PEA to plan, submit, approve, dispatch, pause, resume, retry, accept, pay, choose a working directory or repository, choose agents or models, or read results, logs or chat.
- Changes to the Hermes bridge or to Discord pairing.
- PEA's pages (proposing a project, the board lane, the Harvest receipt). They are built in PEA Web after this.

## Parity

RCD and MCD carry the same change in the same release ([engineering rules](engineering-rules.md)). The same page is proposed in both repositories; the bridge and agent-access code this builds on is the same in both at 0.6.92. Run `python3 scripts/check-shared-features.py --peer <other checkout>` before release.

## Decisions for the operator

1. Whether **Read + drafts** exists at first, or Read only until the PEA pages are built.
2. Whether the remote setting in section 4 is acceptable, or PEA must run on the same machine as the dashboard.
3. Whether `status` may be read under the Read scope without the Discord diagnostics switch.
4. The cap on drafts per day.
