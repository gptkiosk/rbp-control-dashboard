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

Checks can warn or block submission. Required illustrated-site gates are media inventory/slots, a Media Studio publish decision, and agent integration ordered after publication. Reference art and placeholders do not satisfy delivery of final illustrations. Routine setup, file changes, tests, evidence capture and cleanup belong in programmatic stories. Human stories contain meaningful decisions and direct in-app links.

Media generation uses the dashboard's saved provider key and spend acknowledgement. Existing candidates and published slots are reused before another paid take. Final preview evidence must show the planned media on the actual pages and theme states. A reachable base layout alone does not prove the illustrated brief complete.

Guide files are read from the template allowlist. Checks inspect plan data; they never execute a model-supplied command. Kinds include `has_story`, `order`, `not_agent_for` and `requires_story`. Record lessons from repeated failures in the relevant type so the next plan includes the missing tool, access prerequisite or delivery gate.

## Guided intake

New project asks for a goal and the selected template's build details. Website intake covers pages/interactions, visual direction/theme states, and final media. Packaged app intake covers workflows/platforms/data; GCP variants add hosting facts. Other accepts a custom deliverable. Optional audience/boundaries apply generally. “Help me decide” records an undecided choice; it does not invent a confirmed requirement. A complete brief can bypass the questionnaire. Reference images attach before planning; upload errors leave a draft for repair.

Templates may define up to eight `intake_questions`, each with a unique `id` (lowercase letters, digits and underscores), `label`, `prompt`, and optional boolean `required`. Two general questions are appended. Answers are capped at 1,200 characters each and 6,000 total, stored separately from the goal in `intake_answers`, and rendered into the planning/task brief once. Switching templates retains common answers and keeps the form's per-template answers while that dialog remains open. Approved project facts remain immutable.

Coordinator `intake_questions` reads use the same source in web, scoped MCP and paired Discord. Chat asks only for facts not already supplied and returns a compact summary before planning. Paired Hermes passes confirmed answers by question ID with `intake` or the document on `save`; a structured intake with missing required answers returns `needs_information` without creating a project. Existing freeform/legacy projects remain compatible. Custom templates without questions use the two general prompts.

Spending preferences and typed budget amounts never grant provider or cloud authorization. Generation, deployment, execution and route approvals still use existing controls. Never enter secret values. No extra model call is used to render the form.
