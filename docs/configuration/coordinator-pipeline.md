# Coordinator pipeline and context contract

MCD and RCD own the durable project: brief, selected type, approved revision, story dependencies, accepted handoffs, artifacts, run evidence and usage. A Hermes conversation is an entry point to that record. A Discord session and a web conversation must continue the same project ID rather than create independent plans.

## Context selection

The consultant and planner load general practices plus the selected type's guides. General means development practice, security, and documentation. `Other` loads general guidance until its plan explicitly names applicable delivery gates. Adding a new template does not increase an existing project's context. Unrelated personal conversations and templates are not project memory.

`GET /api/projects/consultant-context` returns the text plus `context_manifest`: mode, project type, selected guide names, UTF-8 bytes and SHA-256. Guide text shares a 7,000-character budget; it is not 7,000 characters per guide. A story receives a small guide reference with a private file path, hash and bytes. It reads relevant sections on demand. If a sidecar cannot be written, the bounded text is included instead. Accepted prerequisite handoffs and recent project decisions remain available; unrelated story tails stay in the ledger. The full project ledger remains available for drill-down.

The shared planner prompt carries general scope, route, readiness and decision rules. Delivery-specific practices come from one template. Model guidance is limited to configured candidates, with at most 24 rows and 3,500 characters. It includes dated fresh research notes for those candidates, local task results, and provider snapshot freshness. Request-time planning performs no network fetch.

## Channel contract

The shared `coordinator_read` service powers these reads:

| Purpose | Signed-in web API | Native Hermes MCP | Paired Discord |
| --- | --- | --- | --- |
| Discover capabilities and links | `/api/projects/coordinator?operation=capabilities` | `coordinator_read(capabilities)` | `mcd_project` action `capabilities` |
| List project types | operation `types` | `coordinator_read(types)` | action `types` |
| Selected context | operation `context`, project ID or workspace/type | `coordinator_read(context)` | action `context` |
| Configured model evidence | operation `models` | `coordinator_read(models)` | action `models` |
| Bounded project status | operation `status`, project ID | `coordinator_read(status)` | action `status`, diagnostics permission |
| Redacted task result | operation `task`, task ID | not in read/draft grant | action `task`, diagnostics permission |

Project/task reads check the owning profile. Native access remains local, expiring and revocable; Discord identity is injected by the paired gateway. Discord intake accepts `project_type`, so consulting and actual planning use the same template. No model invents an approval or substitutes terminal commands when a capability is missing.

Existing Discord actions also support planning drafts, issue intake, failure drill-down, limit routing and proposals for housekeeping, standards and repositories. The capability response distinguishes those from dashboard-only decisions. **Full execution parity is not implemented by this read contract:** submission, route amendments, replan, acceptance, media actions and preview start/stop still use their existing operator APIs and dashboard controls. A future channel control adapter must reuse those exact operations, revision pins, approved routes, spending rules and human decision receipts. It must not create a parallel dispatcher or broaden the read/draft MCP grant.

## Meaningful decisions

The approved plan owns routine inventory, implementation, integration, static checks, CI and dashboard preview operations. Human input is reserved for a consequential choice: a missing requirement, spend, media selection, visual acceptance or release/security decision. Link to the project's Media tab when candidates are ready; link to the authenticated preview for visual acceptance. Group compatible decisions. A checklist step is not automatically a human task.

## Shipped and personal responsibilities

Shipped: type schemas and gates, scope/approval enforcement, context selection and budgets, deterministic state transitions, provider facts, local telemetry, dated research evidence, capability discovery and portable API adapters.

Personal Hermes profile: preferred installed accounts and model tiers, individual taste and art direction, notification preferences, machine aliases, personal routines, and which external research connections to use. Keep that profile outside the source/release tree. It may guide a proposal but cannot override the app's ownership, revision, spending or approval checks. Load project context only when discussing that project; personal-agent chat does not carry every project's history.

Artificial Analysis is an optional research source: [Model Recommender](https://artificialanalysis.ai/models/recommend), [API/MCP documentation](https://artificialanalysis.ai/data-api/docs). Its documented API requires a key, server-side storage and cached responses. This release does not configure that connection or scrape the recommender. An operator can save sourced, dated model notes through the existing Models panel/API; stale notes are omitted from planner guidance. Benchmarks inform capability matching; they do not establish local quota, credentials, tool access or completion reliability.

## Workspace continuity and import

See [Project workspaces](project-workspaces.md) for host-aware state, compact handoffs, cooperative external-work reservations and static repository intake. Shared reads and paired Discord use the same services; reservation/handoff writes require Discord control plus diagnostics. These additions do not grant native read/draft tokens execution rights or complete every channel control adapter.

## Start with a conversation or a template

Projects → Plan with chat starts a read-only intake conversation; New project opens the guided form. Both use general intake plus only the chosen type. Hermes reads `intake_questions(project_type)` through its paired tool (or Coordinator read API) before asking missing questions. Reuse already-confirmed answers, ask two or three at a time and permit Help me decide. Confirm a compact summary before planning; the planner owns the story graph and readiness checks. Media selection, spending and consequential release choices remain separate app actions.

The form stores up to 6,000 answer characters separately from the goal. The combined rendered goal and answers are capped at 20,000 characters, matching the prior planning brief limit. Those answers are rendered into the existing brief, not another unbounded prompt field; task brief and consultant context caps remain unchanged. Selected intake questions add at most roughly 3 KB to consultant context, within its existing 20,000-character cap. The consultant's fixed instruction was shortened; unrelated templates are not included. Role pack 23 adds intake guidance; use the existing Agent roles preview/apply control for an already configured Coordinator. Native Hermes plugin changes require its supported installer/upgrade flow; publication does not overwrite live native configuration.
