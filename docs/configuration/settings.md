# Settings and your profile

## Purpose

Use Settings to manage your appearance, planning defaults, Discord connection and private OpenRouter/Discord credentials. Host installation settings are separate; the profile does not edit the server’s dotenv configuration or native subscription logins.

## Screenshots

Pending capture: `profile-settings.png` (preferences), `profile-settings-account.png` (account menu), `profile-discord-planning.png` (unpaired Discord form), `profile-credentials-vault.png` (empty credential fields), `appearance-dark.png` (dark appearance). No RCD capture exists yet; see [screenshot inventory](../screenshots/README.md).

## Controls

1. Open **Settings** at the bottom of the sidebar or in the discrete header account menu. The account menu also contains Sign out when available; Help chat is a separate control.
2. Select **Appearance** (Follow device, Light or Dark), the default working directory and Model matching preference, then **Save preferences**. The header theme toggle changes appearance for the whole app.
3. Under **Hermes on Discord**, set your channel and dashboard address, select notification/planning permissions and **Save connection**. Choose **Get pairing code**, send that private instruction to Hermes within ten minutes, then **Check pairing**. Use **Unlink Discord** to revoke the pairing.
4. Permit Discord planning only when you want your requests there to start subscription planning with Hermes coordination. Paid API planners and implementation stories still require separate review. Hermes asks whether you need a diagram before sending one.
5. Under **Private credentials**, enter an OpenRouter key or optional Discord bot token and **Save credential**. The UI shows a short saved hint, not the secret. Remove a saved credential when appropriate. **Check key spending** reads the saved OpenRouter key’s reported usage.
6. Use **Export preferences** to download settings without credentials, pairing hashes, encryption keys or agent tokens. **Import preferences** loads them for review; adjust workspace/address/channel values for the destination and Save. Pair Discord again on a new installation.

Exports can still contain private paths, a dashboard hostname and a Discord channel ID. Treat the preferences file as private; absence of credentials does not make it a public distribution artifact.

## Settings involved

Profile preferences are stored per operator in SQLite:

| Preference | Default | Meaning |
|---|---|---|
| `theme` | `system` | Follow device, light or dark. |
| `planning_bias` | `50` | Initial Balanced story assignment preference, range 0–100. |
| `working_dir` | empty | Use first allowed workspace, or an explicitly selected one. |
| `dashboard_origin` | empty | Installation default for project links, or an approved origin. |
| `discord_channel_id` | empty | Private destination channel, configured locally. |
| `notify_plans` | `true` | Notify when planning is ready or stops. |
| `allow_discord_planning` | `false` | Allow paired Discord requests to initiate the described planning. |

OpenRouter and Discord are the only profile credential providers. Claude/Codex remain signed into their native subscriptions. Saving a profile OpenRouter key does not change agent routing or the shared capped fallback key. An optional Discord token selects your notification bot; an invalid stored token does not silently fall back to another bot.

Credentials are Fernet-encrypted using the private `vault.key` in the data directory. Back up the database and that key together. Profile grants do not replace the separate MCP Read/Draft grants.

## Secret placeholders

Profile exports may include private workspace paths, hostnames and channel IDs. Replace them with `<PATH>`, `<HOSTNAME>` and `<CHANNEL_ID>` before sharing examples; never include saved keys or pairing codes.

## Troubleshooting

- **Preference not applied:** Save after editing or import. New defaults do not rewrite approved project assignments.
- **Pairing expired:** request a fresh code and send it in the configured channel within the deadline. Keep the code private.
- **Credentials cannot decrypt:** restore the original matching vault key from private backup. Do not generate a replacement and expect it to decrypt old records.
- **Imported paths invalid:** select an allowed directory and valid dashboard origin for this Mac, then save.
- **Profile unavailable:** when authentication is enabled, sign in with Google; a local recovery session is not a Google profile identity.

## Related pages

- [Environment](environment.md): host settings.
- [Google sign-in](google-sign-in.md) and [remote access](remote-access.md).
- [Projects](../sections/projects.md): planning/acceptance.
- [Runtime data](runtime-data.md): private storage and backup.

Host report folders: see [report storage configuration](report-storage.md).
