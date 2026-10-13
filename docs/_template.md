# Page template (`docs/_template.md`)

Every page under `docs/sections/`, `docs/configuration/`, `docs/getting-started.md`, `docs/tested-environments.md`, and `docs/development/` uses these six headings in this order.

---

## Purpose

One paragraph: what this page explains, who reads it (operator, new user, developer), and what decision it supports (install, configure, troubleshoot, extend).

## Screenshots

List screenshot filenames relative to `docs/screenshots/`. While an image is pending, write a line such as `Pending capture: <file>.png` instead of an image link, so no link points at a missing file. The capture checklist (screenshots/README.md) tracks which ones are done.

Naming convention: `<feature>-<view>-<detail>.png` (e.g. `overview-alerts-panel.png`, `profile-settings-discord.png`). See `docs/screenshots/README.md`.

## Controls

Buttons, links, form fields, dropdown options, keyboard actions (Tab, Enter, Escape), and any state change this feature triggers. Include the route or component name when relevant (`/tasks`, `AppSelect.vue`, `ProfileView.vue`).

## Settings involved

Explicit references:

- `.env` keys: `MAC_CONTROL_HOST`, `MAC_CONTROL_PORT`, etc.
- `alerts.toml` sections: `[runs]`, `[services]`, delivery keys.
- Profile fields: `discord_channel_id`, `planning_bias`, `default_workdir`.
- LaunchAgent: `.plist` label `com.operator.mac-control`, `RunAtLoad`, `KeepAlive`.
- MCP: `mcd_server.py` env (`MCD_URL`, `MCD_TOKEN_FILE`).

Never include secret values; reference file paths and setting names only.

## Troubleshooting

Common failures, what to check first (logs, `.env`, pairing TTL), how to recover (re-plan, unlink/re-pair, rotate key, restart service), and when to escalate to the operator.

## Related pages

Links within `docs/` (relative `.md` links) and references to `/help` guides (`helpGuides` IDs from `apps/web/src/lib/help.ts`). Include cross-references to other sections and the development files.
