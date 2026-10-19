# Agent roles and Coordinator starter pack

Hermes is the fixed project Coordinator in RCD. Settings → Agent roles shows Hermes with a Coordinator badge and does not let you assign Coordinator or Delegator to another platform. The other agents can be labelled Worker, Reviewer or Security. Those labels guide assignments; they do not configure native agent access or create automatic review jobs. Hermes must be installed and its starter guidance applied for consultant planning.

## Configure another agent platform (optional)

Coordinator is a project role, not a requirement to use only Hermes. Today, you can ask Hermes through RCD Chat for setup advice or a setup brief, or use Claude Code CLI or Codex CLI directly when that runtime is installed and signed in on the host. The operator still applies and verifies native configuration and credentials.

The Hermes starter guidance includes RCD-specific context for OpenClaw, including how the dashboard uses its gateway, named agent targets and workspace instructions. That context can make OpenClaw setup easier than starting from a generic prompt. In Profile → Coordinator setup, save the desired platforms and roles, then choose **Start agent setup** when the readiness list shows Hermes installed, assigned as Coordinator, guided and configured with a default model. RCD creates a setup project draft and opens it in Projects. Review the brief and plan there; no model run begins until you explicitly continue through the normal project approval flow. The bootstrap must preserve existing agent configuration and turn sign-in, credentials, model selection and other operator-only work into linked human tasks.

Profile → Coordinator setup stores bootstrap preferences for platforms to consider, starter roles, shared project memory and workspace creation, security-review frequency, and whether to reuse configured model defaults or ask before changing them. All platforms are selected initially. Saving preferences does not change native platform configuration; starting setup snapshots those choices into a project brief for Hermes to plan.

Preview shows exact managed instruction blocks and paths before confirmation. The dashboard retains surrounding operator text, makes a private backup and supports rollback. Rollback refuses if a target was edited after assignment. An interrupted write has a recovery journal; recover only when its contents still match the recorded before/after states. Changed operator files are never silently erased.

Hermes uses its SOUL.md and a dashboard context file; Claude Code uses CLAUDE.md; Codex uses AGENTS.md. Grok and OpenClaw require an explicitly chosen existing agent workspace inside an allowed root. Grok uses AGENTS.md; OpenClaw uses SOUL.md and AGENTS.md. Symlinks, foreign-owned files and oversized/non-UTF-8 files are refused. Native credentials are not part of the pack.

The generic pack and coordinate/plan/review/dispatch templates ship under packs/roles/delegator. The installed-agent catalog is added to guidance. The pack is instruction data, not authority: approvals, price gates, permission boundaries and handoff acceptance remain in code.

New pipeline requests snapshot the Hermes Coordinator route and selected planner/model. Changing role labels requires a fresh operator review and does not reroute an in-progress pipeline. Automatic planning can use available Claude/Codex membership planners, while Hermes coordinates and reviews the plan. Hermes planning can use its configured free route; paid planning still requires separate approval and runtime budget enforcement.

The API and saved role data retain the legacy `delegator` field for compatibility. In the Settings card, that internal value represents Hermes as Coordinator; it is not a user-selectable role for other agents. If an earlier version saved a different Coordinator, preview and apply the role changes to move the saved setting to Hermes. Active pipelines keep their approved agent and model. Verification uses synthetic homes and model responses, not native account files or live paid model calls.
