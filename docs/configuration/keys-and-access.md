# Keys and access

**Profile, Private credentials** starts with a guide that says which keys exist, what each is for and which are needed. Basic use needs one thing: an agent signed in on this Mac (Claude Code, Codex, or a configured Hermes or OpenClaw). Nothing else is required.

| Key | Level | What it is for |
| --- | --- | --- |
| An agent signed in | Required for basic use | Runs tasks, chats and projects. Managed in the agent, not stored by MCD. |
| OpenRouter key | Recommended | Reads actual spending, can be shared with Hermes and OpenClaw (off by default), and is the automated route for still images through your Google AI Studio key set up as bring-your-own-key at OpenRouter. |
| fal.ai key | Optional | Video generation (the only automated route) and image generation as a fallback. |
| Discord bot token | Optional | Project notifications from your own bot. |
| GitHub access | Optional | Branch grants for private repositories, set per project. |

Saved keys are encrypted, write-only and never given to agents. Set a credit limit with each provider; MCD does not cap provider spending.

## The key check before a project is created

When you create a project, MCD reads its name and brief and asks whether it seems to need a key you have not saved. This is a keyword check, so it suggests and never decides:

- a brief that mentions generated video suggests the fal key;
- a brief that mentions generating images or art suggests an OpenRouter or fal key (the Gemini app and Flow also work by hand, with no key);
- only "no agent is installed or available at all" blocks, because nothing could run.

A dialog lists what is missing, why, where to get it and how to scope it, and lets you paste the key there. You can also continue without it; the project then uses its fallbacks. If the check itself cannot run, creation goes ahead. The same check is available as `POST /api/keys/check` and the guide as `GET /api/keys`.

To add a rule, edit `RULES` in `apps/api/key_registry.py`.
