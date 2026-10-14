# Help and how-tos

The Help page (`HelpView.vue`) provides a searchable catalog of reviewed guides (`helpGuides` from `apps/web/src/lib/help.ts`) and a token-free chat (`help chat`) that uses local guides and opens MCD links. It does not run agents, grant permissions, send alerts, change settings, or send questions or dashboard data to a model.

## Purpose

For the operator: find clear steps for any MCD feature and open the relevant page directly from a guide link. For new users: use search (`Find a how-to`) or choose a topic from the catalog (`guide-catalog`), then open the selected feature or ask a follow-up through the header chat button. This page supports feature discovery without exposing dashboard data to an external model.

## Screenshots

- Pending capture: `help-guide.png` (guide catalog). No RCD capture exists yet.
- Pending capture: `help-chat.png` (header `Ask help chat` button and chat). No RCD capture exists yet.

## Controls

### Start here

1. Open Help and search for the feature you want, or select its topic.
2. Follow the numbered guide and use its links to open the relevant page or control.
3. Select **Ask help chat** for a local guide match. Use agent Chat when you need a real model conversation.

- **Search** (`label for="help-search"` with `input id="help-search"`): filters guides (`filtered`) by matching words against titles, areas, summaries, keywords and steps. Empty result (`!filtered.length`) shows `No matching guides. Try fewer words or ask help chat.`.
- **Guide catalog** (`nav aria-label="How-to topics"`): selectable `button class="topic"` elements per guide with `small` area label and `strong` title. Selection updates the URL (`route.query.topic`) and the reading pane (`guide-reading`). `aria-current="true"` marks the active topic.
- **Guide reading pane** (`div class="guide-reading"`): displays the selected `HelpGuide` (`HelpGuideArticle` component) with steps (`steps`), links (`links` with `label` and `to`), optional note (`note`), and area label (`area`).
- **Ask help chat** (`btn primary` in `header` with `AppIcon name="chat"`): opens the chat interface (`useHelpStore.show`). The chat uses built-in guides (`helpGuides`) and opens local MCD links (`to` references). It does not invoke an agent model, does not access the dashboard's live data beyond the guide text, and does not change settings.
- **Tip links** (`p class="muted small"`): copy the page URL to keep a link to the selected guide; open links navigate within MCD (e.g., `/mac#mac-title`, `/tasks#board-controls`).
- **Header chat access**: the `Ask help chat` button is available from any feature through the header; the selected guide is preserved by URL query (`?topic=<id>`).

## Settings involved

- `.env`: no `.env` keys specifically configure help content; `MAC_CONTROL_HOST` and `MAC_CONTROL_PORT` affect whether links open correctly in the browser.
- Guide source: `apps/web/src/lib/help.ts` (`helpGuides` array with `id`, `title`, `area`, `summary`, `keywords`, `steps`, `links`, `note`). Changes to guides require editing that file and re-exporting (`scripts/export-howtos.mjs`) for `docs/HOW_TO.md` if the export target is updated.
- No profile fields (`discord_channel_id`, `planning_bias`, `default_workdir`) are edited from the Help page. No `token_file`, `env_names`, or secret values are shown.
- Token-free behavior: the help chat never sends questions or dashboard data to a model. It matches keywords locally (`normalize`, `findGuides`) and opens MCD links (`router.replace`). No external model call is made.
- No LaunchAgent or service configuration is changed by visiting this page.

## Token-free Help chat

- The chat uses only the built-in guide catalog (`helpGuides`). It does not invoke the agent's model, does not send prompts to an external API, and does not return live dashboard state beyond the guide references (`to` links).
- Search (`findGuides`) computes a score from title/keyword matches (`score` calculation) and token overlap (`words.has(token)`). It returns up to 3 guides (`slice(0, 3)`). Short follow-ups that reuse a previous topic (`contextId`) return the same guide when the query includes `that`, `it`, or `this` and starts with `how`, `where`, `what`, `and`, or `can`.
- No `agentTurn` payload, `message`, `model`, or `timeoutSeconds` is used. The chat does not access `chat` threads or `dispatch` routes.
- The header `Ask help chat` button (`help.show(selected.id)`) opens the chat from any feature; it does not change the active feature or save settings.
- The chat does not generate new reports, enable schedules (`MAC_CONTROL_HERMES_REPORTS_DIR`), grant access (`AgentAccessPanel.vue`), or change `.env` settings.

### Guide reference notes

- `MAC_CONTROL_HOST`, `MAC_CONTROL_PORT`: affect the base URL for `to` links (`/profile`, `/projects?action=new`, `/mac#mac-title`, etc.).
- `MAC_CONTROL_LOG_LEVEL`: does not affect help behavior.
- `MAC_CONTROL_COLLECTOR_ENABLED`: independent; the help page does not show metrics.
- `MAC_CONTROL_ALERTS_CONFIG_PATH`: independent; the help page does not manage alerts.
- Guide IDs (`id`) are fixed strings in `help.ts` (`profile-discord`, `projects`, `project-models`, `getting-started`, `overview`, `hardware`, `services`, `updates`, `agent-tasks`, `human-tasks`, `dependencies`, `task-filters`, `approvals`, `runs`, `agent-explorer`, `openclaw-chat`, `agent-chat`, `subscriptions`, `model-rates`, `openrouter`, `mcp`, `hermes-access`, `github`, `reports`, `alerts`, `sign-in`, `remote`). Changing an `id` requires updating all references (`pageGuide`, links in other docs, and any external links).

## Troubleshooting

- **No matching guides** (`p role="status"` with `No matching guides. Try fewer words or ask help chat.`) — the search uses word-level matching (`normalize` removes non-alphanumeric characters). Try fewer words or use the topic button (`button.topic`) instead.
- **Empty guide list** (`!filtered.length` after filtering all `helpGuides`) — the initial list is never empty (the UI displays the actual guide count). If the source file (`help.ts`) is missing or empty, restore it from the repository.
- **Broken feature links** (`to` references like `/profile#discord-profile`) — verify the target feature exists (`ProfileView.vue`, `ProjectsView.vue`, etc.) and the route is registered (`router/routes`). The help page does not create new routes.
- **Chat does not open** (`useHelpStore.show` not working) — verify the `HelpStore` is registered in the app and the `help-show` state is accessible. The button calls `help.show(selected.id)` with the current selected guide's `id`.
- **No agent response in chat** — the chat does not invoke agents (`agentTurn`, `model`, `message`, `timeoutSeconds` are never set). It uses guide text only. If the user expects an agent reply, direct them to `/chat` or `/agents` instead.
- **Historical or stale guide references** — guides reference features that may change (`Projects`, `Tasks`, `Agents`). The guide text (`steps`, `links`) should be updated in `help.ts` when features change; `docs/HOW_TO.md` is regenerated by `scripts/export-howtos.mjs`.
- **Search returns unrelated guides** — `findGuides` uses a scoring system (`score`) combining phrase matches (`p.includes(' ') ? 10 : 4`) and word overlaps (`token` match: `2`). Very broad queries return top-scored guides that may not match the user's intent. Use the catalog (`topic`) for precise selection.

## Related pages

- [Overview](overview.md) — landing dashboard; guide `overview` points to `/`.
- [Mac](mac.md) — hardware charts; guide `hardware` points to `/mac#mac-title`.
- [Services](services.md) — service health; guide `services` points to `/services#services-title`.
- [Tasks](tasks.md) — board, approvals, dependencies; guides `agent-tasks`, `human-tasks`, `dependencies`, `task-filters`, `approvals`, `runs` point to `/tasks` and sub-anchors.
- [Agents](agents.md) — fleet, sub-agents, billing; guides `agent-explorer`, `subscriptions`, `model-rates`, `openrouter` point to `/agents` and billing anchors.
- [Chat](chat.md) — threads, model routing; guides `agent-chat`, `openclaw-chat` point to `/chat?action=new`.
- [Projects](projects.md) — planning, shared memory; guides `projects`, `project-models` point to `/projects` and `?action=new`.
- [MCP](mcp.md) — server registrations and grants; guides `mcp`, `hermes-access` point to `/mcp`.
- [GitHub](github.md) — repository work; guide `github` points to `/github#github-title`.
- [Reports](reports.md) — Hermes reports; guide `reports` points to `/reports#reports-title`.
- [Profile settings](profile-settings.md) — Discord pairing, credentials; guide `profile-discord` points to `/profile#discord-profile`.
- [Getting started](../getting-started.md) — guide `getting-started` points to `/`.
- [Configuration](../configuration/settings.md) — `.env` keys and settings reference.
- Source references: `docs/HERMES_ACCESS.md` (independent of help; access grants are separate from guide content), `docs/OPS_PANELS.md` (independent; reports are separate from help), `docs/ALERTS.md` (guide `alerts` points to `/` and `/services`), `apps/web/src/lib/help.ts` (guide definitions), `apps/web/src/views/HelpView.vue` (UI structure and data sources), `docs/_template.md` (six-part template followed by this page).
