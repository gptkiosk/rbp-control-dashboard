# Profiles and Discord project planning

New profiles default to **Balanced (50/100)**. The slider shows Economy, Balanced and Capability at their respective positions. Existing maps and approved manifests keep their earlier preference until reviewed and edited.

## Operator setup

1. Open **Profile** from the header. Save appearance, default workspace and assignment preference.
2. Set the Discord channel where Hermes replies and a configured HTTPS MCD address for project links. Enable notifications. The installation's existing alert channel is suggested when available, never embedded in source.
3. Enable **Allow my Discord requests to start subscription planning with Hermes coordination** if desired. It permits planning when you ask; Hermes coordination still uses its configured free-first route with capped Google BYOK. It does not authorize paid API planners or story execution.
4. Choose **Get pairing code**, send the displayed instruction to Hermes in that channel within ten minutes, then choose **Check pairing**. The code is stored only as a hash, consumed once and bound to this channel. **Unlink Discord** revokes access.

Ask Hermes: “Plan a project to [goal].” It collects missing name, brief and allowed workspace and can use your saved defaults. Discuss exclusions, risk and assignment preference. Ask it to start planning when ready. An intake is deduplicated by the original Discord message ID; deliberate replanning uses the current project/revision.

Alternatively, **New project → Submit to Hermes** creates the brief and starts the coordinator → subscription planner → Hermes review pipeline after the coordination acknowledgement. **Save draft** runs no models. Progress is based on actual pipeline stages, not a fabricated percentage. Plan failures retain the draft and task evidence for explicit retry.

When the plan is ready, a linked profile receives a Discord notification with a Projects deep link and a question asking whether a diagram is needed. Ask for the image to receive a locally rendered PNG of the saved revision with phases, agents/models and numbered dependencies. Larger maps have multiple pages. Hermes can read and save complete revised maps with revision checks; drafts remain editable in MCD. **Review & submit in MCD** remains required before implementation stories run.

Delivery is distinct from planning: pending, sent, held, expired and uncertain receipts are tracked durably. Uncertain sends never retry blindly. Changing channel or unlinking holds pending messages. Stale revisions are not sent. No external message or paid model turn is needed to verify this feature in tests.

## Private credentials and portability

Profile credentials are write-only, encrypted with Fernet and separated by signed-in operator. API validation errors never echo submitted values. The private encryption key lives in `~/.mac-control/vault.key` with mode 600 inside a mode-700 directory; symlinks, shared permissions and invalid keys fail closed. Restore the **database and vault.key together** from a private backup. Losing the vault key requires re-entering credentials.

- **OpenRouter profile key:** manually checks that key's actual API/BYOK spending. Saving it does not silently change the native agents' routing, shared $20/month cap or provider fallback approval.
- **Discord profile token:** optional own bot for project notifications. Otherwise this installation's privately configured Hermes bot sends notifications. A broken stored token/vault never silently falls back to a different bot.
- **Claude/Codex:** retain their host subscription sign-ins. Subscription credentials are not copied into MCD or exported.
- **Google/OpenRouter BYOK and OpenClaw gateway:** remain private native installation settings. Provider keys must not appear in source, prompts, diagrams, frontend storage or distribution packages. Profile storage supports MCD-specific credentials; it is not a migration of third-party credential stores.

**Export preferences** includes settings only; credentials, pairing and encryption material are excluded. Import loads settings for review; Save validates workspace and origin against the new installation. Review paths/channel/address and pair again on a new installation. Appearance is shared through the profile when explicitly set; browser/device theme remains usable when profile access is unavailable.

For a clean distribution, ship version-controlled source, dependencies and the native plugin, **never** `.env`, OAuth client JSON, runtime database/logs, vault.key, credential backups or agent-tokens. Host bootstrap configuration and allowed operator emails must be set explicitly. `scripts/configure-google-auth.py --allowed-email operator@example.com` imports configured HTTPS callback origins from the downloaded client JSON rather than hardcoding a tailnet hostname. Machine workspaces are allowlisted in private host configuration.

## Native Hermes integration

Run `python3 scripts/install-hermes-projects.py` on an installation with Hermes. This copies only the checked-in plugin and enables it through Hermes' native plugin mechanism. Existing differing plugin files are preserved. Hermes may require a gateway reload depending on its version; check the activation output.

`integrations/hermes/mcd-projects` registers `mcd_project`. The installer preserves existing Discord toolsets and adds `mcd_projects`; new gateway sessions load it after a graceful gateway restart. Identity comes from task-scoped Discord gateway ContextVars, not model arguments or inherited environment. Missing/changed native identity APIs fail closed. The local bridge accepts one exact POST route and a separate private capability token created during pairing. Browser/proxy/remote requests are rejected. The existing MCD MCP task token's permissions are unchanged.

The tool can pair, collect intake, list/get/save owned projects, request approved subscription planning and queue a requested diagram. It has **no execution, dispatch, credential or profile mutation action**. Non-Discord and MCD coordinator CLI turns cannot use it. Custom installations may configure `MCD_PROJECTS_URL` (HTTP loopback only) and `MCD_PROJECTS_TOKEN_FILE` in private Hermes configuration.
