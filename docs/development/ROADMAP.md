# Historical roadmap and ideas for forks

This page separates implemented behavior from ideas that fork owners may choose to pursue. Upstream development is not planned and no future delivery or support is promised. Deployment-specific identifiers and private operational notes are excluded.

## Implemented

- **Monitoring:** Mac resource samples and charts, service status, crash-loop detection and configurable alerts.
- **Task management:** A grouped vertical board with filters, hideable lanes, human tasks, definitions of done, dependencies, execution approvals and operator handoff review.
- **Agents and chat:** Claude Code, Codex, Hermes and OpenClaw adapters, named OpenClaw targets, session resume and activity drill-down.
- **Project planning:** Editable phases and stories, a shared planning map, assignment preference, shared project context and dependency-ordered dispatch with operator acceptance.
- **Usage and billing:** Captured token usage, configurable subscription comparison, model rates and OpenRouter spending when a readable key is configured. Coverage and missing data remain visible.
- **Appearance and help:** Blue glass light/dark themes, header appearance toggle, local how-to guides and help chat with feature links.
- **Access and profiles:** Google sign-in, an operator allowlist, private Tailscale access, profile preferences, encrypted write-only provider credentials and optional Discord planning connection.
- **Integrations:** Read-only GitHub and operational report views; approval-based MCP configuration and limited expiring Hermes access.

## Verification and release work

- Independent screenshot privacy review and documentation accuracy checks.
- Release snapshot and repository decisions (MIT is selected).
- Private vulnerability reporting is enabled in the release repository; independent forks must establish their own policy.
- Additional platform and macOS version testing; untested environments must remain identified as untested.
- Independent resource-usage comparison and per-integration verification where coverage is incomplete.

## Ideas for independent forks

- Bounded Mac service controls with explicit authorization and tested recovery.
- Broader automation across independent stories and isolated Git workspaces, with conflict prevention and clear ownership.
- Improved telemetry coverage and cost reconciliation as providers expose reliable data.

These proposals do not grant execution permission or claim delivery dates. Publication, credential rotation and substantive security decisions require operator review.
