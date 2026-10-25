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
