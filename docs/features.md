# Features and workflows

This describes the local RCD prototype; the public repository is currently docs-only. Agent execution and physical-Pi behavior remain under validation.

| Menu / control | Use and boundary |
|---|---|
| Overview | Fleet/activity/alerts summaries. Missing collector data is shown as not reported; it is not a benchmark result. |
| Pi health | Linux/Pi platform readings. VM results do not establish firmware, GPIO, temperature or throttling behavior on a real Pi. |
| Services | Host service inventory. Linux service behavior requires separate testing; Mac LaunchAgents are not Pi services. |
| Projects | Brief → reviewed plan/map → approved stories → dependency-ordered execution → handoff review. Agent/model recommendations remain editable before review. |
| Tasks | Scope, definition of done, dependencies, run history and explicit human decisions. Distinguish current and historical runs; exit0 alone is not completion. |
| Agents | Detected native CLIs, observed activity and reported usage. Installed adapter code is not proof of a runtime being conformance-eligible. |
| Chat | Agent conversation requires a configured runtime and explicit model/spending policy; a preview need not enable it. |
| MCP | Reviewed tool integrations and bounded capabilities; read/draft grants do not approve dispatch or publication. |
| GitHub | Repository activity through an existing scoped CLI login; no credentials should be committed or exposed. |
| Ops reports | Read Markdown/UTF-8 reports from explicitly configured local folders. See [configuration](configuration.md). |
| Help & how-tos / header Help | Feature guidance and deep links. Verify instructions against this product/revision. |
| Settings / setup wizard | Profile preferences and write-only credentials; host/agent routes remain distinct. |

## Project and task flow

1. Define the goal, workspace, exclusions, bounded stories, measurable acceptance and dependencies.
2. Review agent/model assignments and spending policy. Native defaults never override an explicitly assigned route. A Pi deployment must not assume Claude/Codex subscription apps are available locally.
3. Submit the exact reviewed plan; shared context and accepted handoffs carry relevant evidence into the next story.
4. Routine automatic handoffs, where explicitly authorized, exclude human questions, security/publication decisions and unfinished outputs. A board status alone is not independent artifact verification.
5. A limit/failure should preserve partial-work evidence and stop or use an already reviewed route. Retry must not duplicate active work or introduce paid fallback without approval.
6. UI work includes a reachable isolated preview and factual checks, followed by explicit sign-off. Release/publication is a separate decision.

The prototype has unresolved lifecycle/security validation. These workflow intentions must not be treated as production guarantees. See [readiness](release/readiness.md).
