# Screenshot capture inventory

> **Status: no RCD captures yet.** Every image in this folder came from the MCD (macOS) app before the RCD rebrand. They show the "Mac Control Dashboard" title, Mac-only views and LaunchAgent services. None of them is evidence of RCD behaviour, and RCD guides no longer link to them. The MCD files still sit in this folder because their removal was not approved in this run. Move them out of the public repository before publication (see [secret and PII scan](../release/secret-scan.md)).

RCD captures must come from an isolated RCD preview, or from a Pi/ARM64 Linux environment, with synthetic data. Until that happens, each guide shows a `Pending capture:` line instead of an image.

## Capture procedure (RCD)

1. Pick an unused loopback port (not 8800 or any port owned by a live service). Do not stop or reconfigure another process to get a port.
2. Use a fresh, disposable data directory with no database copied from production, plus synthetic reports, projects and agents.
3. Set `MAC_CONTROL_COLLECTOR_ENABLED=false` and `MAC_CONTROL_DISPATCHER_ENABLED=false`. Leave alerts and external delivery unconfigured.
4. Record the preview URL, source revision, start and stop commands and the PID you started. Stop only that PID.
5. Capture at 1280 px width in light mode, plus `appearance-dark.png`. Check every image for personal identifiers, host names and secrets before it is published.

## Pending RCD captures

| Guide | Pending file | What to show |
| --- | --- | --- |
| Overview | `overview-overview.png` | Pi telemetry tiles and summary cards |
| Overview / alerts | `overview-alerts-panel.png` | Alert status card with delivery state |
| Pi health | `pi-health.png` | Pi host page (`/pi`) |
| Services | `services-table.png` | Services table with flags |
| Projects | `projects-brief.png`, `projects-planning-map.png`, `projects-story-assignment.png`, `projects-story-assignment-model.png` | New project, planning map, story instructions and model choices |
| Tasks | `tasks-board.png`, `tasks-story-assignment.png` | Grouped board and new task form |
| Agents | `agents-list.png`, `agents-subagent-select.png`, `agents-billing-rates-dialog.png` | Fleet explorer, sub-agent selector, billing dialog |
| Chat | `chat-thread.png`, `chat-new-dialog.png` | Thread and new-chat form |
| MCP | `mcp-server.png`, `mcp-server-request-dialog.png`, `mcp-grants-dialog.png` | Server table, request form and unsubmitted access review |
| GitHub | `github-repo.png` | Disconnected state |
| Ops reports | `reports-catalog.png` | Report list and preview |
| Help | `help-guide.png`, `help-chat.png` | Guide catalog and help chat |
| Settings | `profile-settings.png`, `profile-settings-account.png`, `profile-discord-planning.png`, `profile-credentials-vault.png`, `appearance-dark.png` | Preferences, account menu, unpaired Discord, empty credential fields and dark mode |

## Not captured in RCD

- Installer or systemd setup illustrations. None exists; do not add a screenshot of another state to imply installation, a permission grant, pairing or delivery.
- Live GitHub, Google sign-in, Discord pairing, provider billing or a real delivery. These cannot be shown in a synthetic preview.

## Verification

- [ ] RCD capture set taken from an isolated preview. Not started.
- [ ] Each capture checked for identifiers and secrets, with reviewer and date recorded.
- [ ] Operator acceptance after review.
- [ ] MCD files removed from this folder (pending approval to move them out).

## Naming and publication review

Use `<section>-<state>.png`. From a section guide, link to `../screenshots/<filename>.png`; from the documentation root, use `screenshots/<filename>.png`.

Before publication, independently inspect every image for personal emails, real channel/account IDs, tailnet/host names, private repository names, personal filesystem paths and secret values. Use synthetic data at capture time. Security review and publication approval are separate, and these images do not authorize either.
