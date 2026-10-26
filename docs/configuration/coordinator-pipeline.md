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


## Model matching and planning quality (0.6.71)

The story slider is a **classification threshold**, not a provider selector or automatic model pin. Economy prefers low total cost and fast adequate models; Balanced uses focused models for bounded work and general models for integration; Capability favors stronger reasoning on ambiguous/critical work while permitting a justified focused route for simple work. The Coordinator must explain specialty, task complexity/risk, vision/tools/context requirements and the cost/latency tradeoff. An explicit operator route still wins. No recommendation enables a billing class or paid API fallback.

Automatic planning has installed, allowed Haiku5.5/Luna and Sonnet5.5/Sol membership candidates, independent of the story slider. It reviews on the selected automatic planner and can promote a failed focused planning/review step to an already-approved general route. Existing bounded output repair, route history and approvals remain. A manual planner choice remains manual; no silent account or model migration occurs. New-project Choices exposes the planner separately. When membership is unavailable or prohibited, only existing reviewed free/approved recovery routes remain; do not claim a stronger route was available.

Dated provider guidance supplies routing heuristics, not scores: [Anthropic](https://platform.claude.com/docs/en/models/haiku-5-5/overview), [OpenAI](https://developers.openai.com/api/docs/guides/model-selection), [Gemma](https://ai.google.dev/gemma/docs/core/model_card_4) and [North Mini Code provider page](https://openrouter.ai/cohere/north-mini-code:free), reviewed2026-10-25. Unknown/legacy/custom models retain unknown specialty until researched; aliases never imply vision. Model profiles expose source/date/class; configured endpoint/tool support and local quality still need verification. Existing on-demand provider refresh and sourced notes/weekly watch remain the learning path. Artificial Analysis rankings require dated notes or a separately configured licensed connection: this release does not claim that connection exists or scrape rankings during planning.

Guidance remains capped24 rows/3500 characters with round-robin agent coverage; only general + selected type is loaded. API token rates are reference estimates, not membership invoices or guaranteed spend. Median local run time depends on task mix; process success is not artifact acceptance. Full replan source stays private for cancellation; model prompts receive source revision/reason/preserved history and a prior-map summary capped14000 characters. Semantic website defects must be repaired before a returned proposal is marked ready; dispatch remains a separate review/approval.


### Source-independent API evidence

OpenRouter's existing public model snapshot supplies pricing, context, supported parameters and input modalities. Native OpenAI/Anthropic model IDs now match their exact provider-prefixed snapshot entries without conflating versions. The Models panel also has **Refresh reference data · LiteLLM**, using the fixed public JSON model-cost map URL. It imports only known catalog models and supported numeric/boolean fields. These are reference observations as retrieved, not independently verified provider prices, and never overwrite the billing catalog. No model run, native configuration change or provider key is involved.

`GET /api/models/evidence` exposes the normalized schema units and current observations; authenticated operator `POST /api/models/evidence` imports up to300 observations with explicit confirmation. An API adapter outside the app can translate other documented feeds into this contract. Records retain exact model ID, metric, value, canonical unit, source, as_of date, benchmark/version and scale where relevant, environment and method. Future dates, non-finite measurements, mismatched units, missing quality scales and credential-bearing source URLs are rejected. Data is bounded, private and atomically stored; older observations cannot replace newer observations from the same source/method. Source disagreements stay visible. Imported text is untrusted evidence and cannot grant access, activate a route or authorize spending.

Artificial Analysis is an example of quality/speed/cost criteria and an optional data supplier, not a dependency. Its documented authenticated API can feed the same contract when separately configured. Arena publishes task-specific leaderboards/datasets (the old LMSYS name is not an assumption of an available API); an adapter must preserve category, evaluation/harness/version, scale and conditions. This release includes the generic import boundary and LiteLLM/OpenRouter inputs, not authenticated AA/Arena connectors or a claimed universal score. No page scraping or benchmark API call is made during project planning.

Sources: [OpenRouter model API](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties), [LiteLLM cost map](https://docs.litellm.ai/docs/proxy/model_cost_map), [AA data API](https://artificialanalysis.ai/data-api/docs), [Arena dataset](https://arena.ai/blog/arena-leaderboard-dataset). Use provider pricing as authority for billing; community maps and benchmarks remain dated corroborating evidence.

## Planning contract repairs (0.6.73)

Model JSON is parsed with unique keys; duplicate dependencies/routes and non-finite values are rejected before graph construction. A new proposal can fill an unambiguous `media_stage`, `media_batch` or `verification_stage` from already-declared work. This changes labels only, not instructions, dependencies, models or authorization. Ambiguous work remains a finding; approved records are never relabelled in place.

A distinct static file/asset check carries `verification_stage: static`. Script preparation and fixed host actions are separate. For requested character-reference-first media, generation/publication nodes carry `media_batch: reference` or `scenes`, and dependencies enforce reference generation → reference publication → scene generation → scene publication → integration → static checks → dashboard preview. A Generate-all paragraph cannot replace the separate published-reference barrier. Inventory slots carry matching `batch: reference|scenes`; scene `refs` must include the published `assets/img/<reference-slot>.jpg` paths. Batch-specific decisions verify their required assets without waiting for the later batch, while legacy/unbatched approval still verifies all required slots. Scene requests refuse unpublished/missing reference links before any provider call.

With existing output recovery enabled, an invalid classification label can receive one field-only repair on the approved route. The app retains the original map privately and accepts exactly the listed labels, rejecting graph/scope/route edits or a replacement map. Other bounded repairs retain a private response sidecar for inspection. No extra attempt, route or spending is authorized by these formats; plan review and submission still apply. Role pack 26 is available through the existing Agent roles preview/apply flow; updates do not overwrite personal custom copies.

Token impact: selected-type guide and story-context budgets are unchanged. Three optional node role fields and the shared planning/review instruction add bounded schema/text overhead. A label repair sends at most eight invalid-field summaries (120-character title, 360-character description, 120-character value) plus the enum contract; it does not resend the full proposal. The full original response remains private for other repairs. No research fetch or additional normal-path model call was added.
