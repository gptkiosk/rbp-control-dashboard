# Agent roles and Coordinator starter pack

Hermes is the fixed project Coordinator in RCD. Settings → Agent roles shows Hermes with a Coordinator badge and does not let you assign Coordinator or Delegator to another platform. The other agents can be labelled Worker, Reviewer or Security. Those labels guide assignments; they do not configure native agent access or create automatic review jobs. Hermes must be installed and its starter guidance applied for consultant planning.

## Configure another agent platform (optional)

Coordinator is a project role, not a requirement to use only Hermes. Today, you can ask Hermes through RCD Chat for setup advice or a setup brief, or use Claude Code CLI or Codex CLI directly when that runtime is installed and signed in on the host. The operator still applies and verifies native configuration and credentials.

The Hermes starter guidance includes RCD-specific context for OpenClaw: how the dashboard uses its gateway, named agent targets and workspace instructions.

## Coordinator setup

In Settings → Coordinator setup, the dashboard sets up the agent platforms itself; no model is involved, so every run behaves the same.

1. **Choose a setup mode.** *Stable start* (recommended) creates what is missing from tested templates: the OpenClaw role agents `rcd-oc-developer`, `rcd-oc-security` and, if ticked, `rcd-oc-reviewer` (each with its own workspace, `SOUL.md` and `AGENTS.md` from `packs/agents/`, registered with `openclaw agents add` on OpenClaw's configured default model), plus the shared-memory notes and project folders. *I'll configure the platforms myself* changes nothing and only checks what you set up.
2. **Pick the platforms.** Each selected platform is checked: installed, starts (`--version`), and has a route the dashboard may use (OpenClaw: a default model; Claude Code, Codex and Grok Build: billing saved as Subscription). Anything not ready shows the fix and a link.
3. **Hermes, the Coordinator,** must be installed, assigned, guided and have a default model.
4. **Apply setup.** The list of changes says what will be created and what is already there. Tick the confirmation and apply. An existing agent, file or folder is never changed, a stale preview is refused, and a failed item is reported with its reason while the others still apply. Applying twice creates nothing new.
5. **Start validation project.** Once every check passes and nothing is left to create, this creates a small project: one read-only story per ready platform (OpenClaw runs as `rcd-oc-developer`) and your review. Submit it in Projects; it proves each platform signs in and answers. Then start a real project.

Switching from *configure myself* to *Stable start* later only adds what is missing.


Preview shows exact managed instruction blocks and paths before confirmation. The dashboard retains surrounding operator text, makes a private backup and supports rollback. Rollback refuses if a target was edited after assignment. An interrupted write has a recovery journal; recover only when its contents still match the recorded before/after states. Changed operator files are never silently erased.

Hermes uses its SOUL.md and a dashboard context file; Claude Code uses CLAUDE.md; Codex uses AGENTS.md. Grok and OpenClaw require an explicitly chosen existing agent workspace inside an allowed root. Grok uses AGENTS.md; OpenClaw uses SOUL.md and AGENTS.md. Symlinks, foreign-owned files and oversized/non-UTF-8 files are refused. Native credentials are not part of the pack.

The generic pack and coordinate/plan/review/dispatch templates ship under packs/roles/delegator. The installed-agent catalog is added to guidance. The pack is instruction data, not authority: approvals, price gates, permission boundaries and handoff acceptance remain in code.

New pipeline requests snapshot the Hermes Coordinator route and selected planner/model. Changing role labels requires a fresh operator review and does not reroute an in-progress pipeline. Automatic planning can use available Claude/Codex membership planners, while Hermes coordinates and reviews the plan. Hermes planning can use its configured free route; paid planning still requires separate approval and runtime budget enforcement.

The API and saved role data retain the legacy `delegator` field for compatibility. In the Settings card, that internal value represents Hermes as Coordinator; it is not a user-selectable role for other agents. If an earlier version saved a different Coordinator, preview and apply the role changes to move the saved setting to Hermes. Active pipelines keep their approved agent and model. Verification uses synthetic homes and model responses, not native account files or live paid model calls.
