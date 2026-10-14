# Share the saved OpenRouter key with Hermes and OpenClaw

## Purpose

Explains the opt-in switch in Profile that lets Hermes and OpenClaw run with the OpenRouter key you saved in the app, so you
do not type the same key into each agent. Read it before turning the switch on, or when an agent says it has no key.

## Screenshots

Pending capture: `profile-share-openrouter-key.png`.

## Controls

On **Profile → Private credentials**, once an OpenRouter key is saved, the checkbox **Let Hermes and OpenClaw use this saved key**
appears. It is off by default and saves on its own, without saving other unsaved edits on the page.

When it is on:

- Every Hermes and OpenClaw run (board stories and chat turns) starts with the key in that one process's environment as
  `OPENROUTER_API_KEY`, even if the agent has its own key configured. Nothing is written to disk.
- Anything the agent prints is scrubbed of the key before it is stored or shown: the exact value and anything shaped like an
  OpenRouter key become `[redacted OpenRouter key]`. The run log notes that the saved key was supplied, never its value.
- The agents' spending meters use the same key.
- Claude Code, Codex and Grok never receive it. Paid models still follow your dispatch policy: the key does not authorize
  paid usage.
- Only one operator can share a key per installation. Turning the switch off, or removing the saved key, stops it at once.
  A saved key that cannot be read supplies nothing, and runs carry on without it.
- The switch is not part of exported or imported preferences.

An agent can read its own environment, just as it can read its own configuration file. Use a dedicated OpenRouter key with a
credit limit set at OpenRouter, and keep Google AI Studio BYOK under "Always use this key" in your OpenRouter integrations so a
Gemini fallback bills your Google account.

## Settings involved

- Profile preference `use_saved_openrouter_key` (default off), and the encrypted credential `openrouter`.
- Hermes reads the key through `key_env: OPENROUTER_API_KEY`. OpenClaw needs its provider key to be an environment reference,
  set once and containing no secret: `OPENROUTER_API_KEY=x openclaw config set models.providers.openrouter.apiKey
  --ref-provider default --ref-source env --ref-id OPENROUTER_API_KEY` (the placeholder value only lets the command resolve the
  reference; nothing is stored).
- Setup of the provider chain itself (model, fallbacks) stays in the agents' own configuration.

## Troubleshooting

- "No key" from an agent: check the switch is on and that an OpenRouter key is saved (Profile shows the last four characters).
  If another operator shares a key, turn that off first.
- OpenClaw still reports a missing key: its provider key is probably a literal or unset instead of the environment reference
  above.
- Rotating the key: save the new key in Profile. Agents pick it up on their next run.

## Related pages

- [Recommended agent mix](recommended-agent-mix.md)
- [Setup wizard](../SETUP_WIZARD.md)
- [Profiles and Discord](../PROFILES_AND_DISCORD.md)
