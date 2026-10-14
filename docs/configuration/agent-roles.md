# Agent roles and Delegator starter pack

Settings → Agent roles assigns one installed Delegator, plus Worker, Reviewer or Security labels for the other agents. Hermes is the default when installed and is the recommended coordinator. With no assigned/installed Delegator, planning stops with a setup explanation. Reviewer and Security labels do not create automatic review jobs.

Preview shows exact managed instruction blocks and paths before confirmation. The dashboard retains surrounding operator text, makes a private backup and supports rollback. Rollback refuses if a target was edited after assignment. An interrupted write has a recovery journal; recover only when its contents still match the recorded before/after states. Changed operator files are never silently erased.

Hermes uses its SOUL.md and a dashboard context file; Claude Code uses CLAUDE.md; Codex uses AGENTS.md. Grok and OpenClaw require an explicitly chosen existing agent workspace inside an allowed root. Grok uses AGENTS.md; OpenClaw uses SOUL.md and AGENTS.md. Symlinks, foreign-owned files and oversized/non-UTF-8 files are refused. Native credentials are not part of the pack.

The generic pack and coordinate/plan/review/dispatch templates ship under packs/roles/delegator. The installed-agent catalog is added to guidance. The pack is instruction data, not authority: approvals, price gates, permission boundaries and handoff acceptance remain in code.

New pipeline requests snapshot the assigned Delegator and model. Assignment changes require a fresh operator coordination review and do not reroute an in-progress pipeline. Automatic planning prefers available Claude/Codex membership planners; without those it can use a reviewed free Delegator route, including an explicitly configured Hermes openrouter/free route. Paid planning still requires separate approval and runtime budget enforcement.

Verification uses synthetic homes and model responses, not native account files or live paid model calls. Every supported agent is tested as Delegator, including assignment changes during planning. This establishes routing and managed-block behavior, not model quality or account entitlement.
