# Setup wizard

Open `/setup`, or choose **Setup wizard** in the header account icon. Settings and Help also link to it. New profiles see a welcome prompt; **Later** hides the prompt without removing access to the wizard.

The six steps cover:

1. **Your Mac:** local macOS prerequisites, dependency/build commands and an allowed default workspace. The browser can be on another device; agents execute on the host Mac.
2. **Google sign-in:** exact configured callback URLs, OAuth Web application setup, approved accounts and the private importer. OAuth secrets remain host configuration. The browser sign-in gate remains enforced.
3. **Hermes & OpenClaw:** executable detection, official installation guides, native provider/model routing and fallback-cap confirmation. Detection does not verify gateway readiness or provider authentication.
4. **OpenRouter:** encrypted write-only profile key entry and an explicit key-spending check. Native inference keys/routing remain separately configured unless you opt in to [sharing this key with Hermes and OpenClaw](configuration/saved-openrouter-key.md); this key does not authorize paid model usage.
5. **Subscriptions:** ChatGPT/Codex and Claude apps, the corresponding CLIs, host subscription login and usage-limit confirmation. MCD executes the CLIs; desktop sign-in alone is not a CLI entitlement check.
6. **Find your way:** all menu destinations, header Help chat, how-tos and a checklist of detected settings and operator confirmations.

**Save & continue** and step selections save progress to the operator's profile. **Refresh checks** rechecks executable paths, allowed workspaces and Google session status. **Finish walkthrough** records that the guide was reviewed; missing items remain visible. It does not install software, run tasks, accept project artifacts, change routing or enable remote access.

Setup progress is per profile and is excluded from portable preference exports. Importing preferences preserves the destination profile's setup state. Credentials are never stored in wizard progress or browser storage. Agent, Google and subscription configuration stays on the private host.

Implementation uses `PATCH /api/profile/setup` with bounded step/status/confirmation fields and operator profile authorization. Old profiles receive safe defaults without a schema migration. Setup writes preserve appearance, planning defaults, permissions and Discord settings.
