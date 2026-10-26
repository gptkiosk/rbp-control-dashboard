# Project types

Choose a type in New project or the project consultant. The selected template supplies planner rules, guides, known failures, media defaults and plan checks.

| Type | Delivery | Meaningful decisions |
| --- | --- | --- |
| Packaged app | Installed package, signed release, install/update evidence | Release/security choice and target verification |
| GCP hosted app | Containerized application on a named GCP service | Infrastructure/billing changes and production release |
| Local website | Illustrated themed pages, media integration and dashboard preview | Media spend/selection and visual acceptance |
| GCP hosted website | Website pipeline plus named GCP delivery and post-deploy evidence | Media, visual acceptance and production release |
| Other | General guidance with explicitly chosen delivery gates | Only choices warranted by the brief |

Legacy `web-app` and `website-property` IDs remain readable for existing projects; they are not offered for new plans. A type is data in `packs/project-types/<id>.json`. A valid operator copy in the private data directory's `project-types/` replaces the shipped copy. It never grants credentials, dispatch permission or a paid route.

Consultation and planning use **general plus the chosen type only**. `Other` does not import every delivery guide. Read the [Coordinator context contract](coordinator-pipeline.md) for budgets and channel behavior.

Checks can warn or block submission. When final generation is requested, required stages are media inventory/slots, dashboard fal.ai generation after spend acknowledgement, candidate selection/publication, then agent integration. Selection/publication alone cannot satisfy generation. Existing-assets-only briefs skip paid generation. Reference art and placeholders do not satisfy delivery of final illustrations. Routine setup, file changes, tests, evidence capture and cleanup belong in programmatic stories. Human stories contain meaningful decisions and direct in-app links.

Media generation uses the dashboard's saved provider key and spend acknowledgement. Existing candidates and published slots are reused before another paid take. Final preview evidence must show the planned media on the actual pages and theme states. A reachable base layout alone does not prove the illustrated brief complete.

Guide files are read from the template allowlist. Checks inspect plan data; they never execute a model-supplied command. Kinds include `has_story`, `order`, `not_agent_for` and `requires_story`. Record lessons from repeated failures in the relevant type so the next plan includes the missing tool, access prerequisite or delivery gate.

## Guided intake

New project asks for a goal and the selected template's build details. Website intake covers pages/interactions, visual direction/theme states, and final media. Packaged app intake covers workflows/platforms/data; GCP variants add hosting facts. Other accepts a custom deliverable. Optional audience/boundaries apply generally. “Help me decide” records an undecided choice; it does not invent a confirmed requirement. A complete brief can bypass the questionnaire. Reference images attach before planning; upload errors leave a draft for repair.

Templates may define up to eight `intake_questions`, each with a unique `id` (lowercase letters, digits and underscores), `label`, `prompt`, and optional boolean `required`. Two general questions are appended. Answers are capped at 1,200 characters each and 6,000 total, stored separately from the goal in `intake_answers`, and rendered into the planning/task brief once. Switching templates retains common answers and keeps the form's per-template answers while that dialog remains open. Approved project facts remain immutable.

Coordinator `intake_questions` reads use the same source in web, scoped MCP and paired Discord. Chat asks only for facts not already supplied and returns a compact summary before planning. Paired Hermes passes confirmed answers by question ID with `intake` or the document on `save`; a structured intake with missing required answers returns `needs_information` without creating a project. Existing freeform/legacy projects remain compatible. Custom templates without questions use the two general prompts.

Spending preferences and typed budget amounts never grant provider or cloud authorization. Generation, deployment, execution and route approvals still use existing controls. Never enter secret values. No extra model call is used to render the form.

## Saved-intent and setup contract (0.6.70)

Confirmed exclusions and story-model preferences outrank template examples and assignment bias. Website templates no longer introduce forms, accounts, visitor storage, containers or CI by default. The app checks recognized explicit no-forms/accounts/tracking constraints; broader semantic scope still needs Coordinator and operator review. Explicit primary choices saved by Use one route persist in `story_route` across replans. A conservative reader also recognizes unambiguous named Haiku/Sonnet/Luna/Terra story preferences in saved input. It does not infer permission from a bare model mention. Configured membership routes replace free/API defaults only on an unsubmitted proposal; unavailable routes are setup findings. Other subscription/capability exceptions are visible for review, and existing route/spend/risk gates remain enforced.

New generated-media plans label separate stories with `media_stage`: `inventory`, `generate`, `publish`, `integrate`. Inventory/integration are agent file work; generation/publication are meaningful dashboard Media Studio decisions. Checks require ordered ancestry through all four stages and integration before final file/preview verification. Explicit generation/publication decision acceptance checks the required candidate/published files; skipping every required asset cannot complete an illustrated workflow. No new media provider call occurs during planning, checking, repair or editing.

Web and paired Hermes expose `readiness` and `plan_checks`. Setup inspects the allowlisted writable folder, tool discovery on the actual dispatcher path, saved membership configuration, fal credential presence (never its value), repository branch grant/clone and preview script/preparation. It never executes project code, installs a tool, reads provider accounts, creates a credential or grants access. Missing website/media setup blocks initial dispatch; an approved app-owned repository setup or declared preview preparation is recorded as pending, not done. Use linked existing setup controls for host fixes. `repair_plan` repairs saved-route/write-mode defaults only as a new editable revision; scope and dependency changes use existing save/replan review. Approved/running work is never hot-edited.

The Coordinator receives compact contract findings in its existing review call. No new model round trip is added. Core contract text is capped at 2,400 characters and setup at 1,600; the selected website wording was reduced instead of loading other templates. Private template/role overrides remain supported, but app-owned saved-intent checks still apply. New native tool action names require upgrading the installed Hermes integration through the supported flow; web planning uses the shipped engine immediately.

## Refine an asset before generation

Media Studio → Not made yet → Edit asset plan edits prompt, purpose, world/theme, display dimensions, resolution and video duration. Resolution controls provider cost; dimensions choose the closest supported aspect. Names/types/references/count/placements are an integration contract: adding, removing or renaming assets needs a reviewed inventory amendment/replan. Edits are limited to slots without running, generated or published work, compare a current inventory hash and preserve other slots/metadata. Estimates refresh and spend acknowledgement resets. Generation from the new UI carries that inventory hash and refuses a stale plan before submitting to fal. Existing candidates are reviewed before paying for another take.
