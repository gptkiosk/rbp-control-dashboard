"""One place that says which keys exist, what each is for, and which a given piece of work needs.

Facts and a keyword check only: nothing here stores a key or limits anything. Saved keys live in the operator's encrypted profile
(`profiles.py`); agent sign-ins live on the host and are only reported. `needs()` is a heuristic over the text of a project (its name and
brief): it suggests keys, the operator decides, and only "no agent is available at all" ever blocks.
"""
from __future__ import annotations

import re

from sqlalchemy import select

from models import UserCredential

# level: required (basic use), recommended, optional. storage: saved (encrypted in your profile) or host (managed outside MCD).
KEYS = [
    {"id": "agent", "label": "An agent signed in on this Mac", "storage": "host", "provider": None, "level": "required",
     "purpose": "Runs tasks, chats and projects. Claude Code and Codex use your membership sign-in; Hermes and OpenClaw use their own configured routes. MCD keeps no copy.",
     "obtain": "Agents, then Agent tools, shows what is installed and lets you refresh it.", "scope": "Sign in to at least one agent. Nothing to enter here."},
    {"id": "openrouter", "label": "OpenRouter key", "storage": "saved", "provider": "openrouter", "level": "recommended",
     "purpose": "Reads actual spending, can be shared with Hermes and OpenClaw (off by default), and is the automated route for generating still images through your Google AI Studio key when bring-your-own-key is set up at OpenRouter.",
     "obtain": "https://openrouter.ai/keys", "scope": "Set a credit limit on the key at OpenRouter."},
    {"id": "fal", "label": "fal.ai key", "storage": "saved", "provider": "fal", "level": "optional",
     "purpose": "Video generation (the only automated route) and image generation as a fallback, for site art and motion backgrounds. MCD uses the saved key itself when you press Generate (Settings → AI & models → Accounts, Media models); agents never see it. Projects without generated media never need it.",
     "obtain": "https://fal.ai/dashboard/keys", "scope": "Create it with the API preset, restrict its allowed models (listed in Settings → AI & models → Accounts, Media models) and set a credit limit at fal."},
    {"id": "discord", "label": "Discord bot token", "storage": "saved", "provider": "discord", "level": "optional",
     "purpose": "Project notifications from your own bot. Leave empty to use this installation's Hermes bot.",
     "obtain": "https://discord.com/developers/applications", "scope": "Give the bot only the channel permissions it needs."},
    {"id": "github", "label": "GitHub access", "storage": "host", "provider": None, "level": "optional",
     "purpose": "Lets agents work on a branch of a private repository you grant. MCD never gives agents your login; you grant each repository and branch to a project.",
     "obtain": "Sign in with the gh tool on this Mac, then grant a branch in the project.", "scope": "Grant one branch per project."},
]

# What a project's own text suggests it will need. Each rule: a pattern over the text, keys of which any one satisfies it, and why.
RULES = [
    {"id": "video", "pattern": r"\b(ai[- ]generated video|video (generation|clips?|loops?|backgrounds?)|motion (video|background)s?|animated video|veo|kling|footage)\b",
     "any_of": ["fal"], "why": "This project mentions generated video. fal is the only automated route for video, so without a fal key the site ships on its fallbacks."},
    {"id": "images", "pattern": r"\b(generat\w*|ai[- ]generated|custom|create)\b.{0,60}\b(art|images?|illustrations?|graphics|artwork|stills?)\b|\bimage generation\b|\bart generation\b",
     "any_of": ["openrouter", "fal"], "why": "This project mentions generating images. Saved keys for OpenRouter (Google route) or fal allow the automated routes; the Gemini app and Flow also work by hand with no key."},
]


def saved_providers(s, identity):
    return {row.provider: row.hint for row in s.scalars(select(UserCredential).where(UserCredential.owner == identity))}


def registry(s, identity, agents_available):
    """Every key with its level, purpose and whether it is in place. Never any key material, only the last four characters of a saved one."""
    saved = saved_providers(s, identity)
    out = []
    for key in KEYS:
        row = dict(key)
        if key["id"] == "agent":
            row["in_place"] = bool(agents_available)
            row["detail"] = ", ".join(sorted(agents_available)) if agents_available else "No agent is installed or available yet."
        elif key["storage"] == "saved":
            row["in_place"] = key["provider"] in saved
            row["detail"] = f"saved ····{saved[key['provider']]}" if key["provider"] in saved else "not saved"
        else:
            row["in_place"] = None      # managed outside MCD: reported, not verified
            row["detail"] = "managed outside MCD"
        out.append(row)
    return {"keys": out, "basic_use": [k["id"] for k in KEYS if k["level"] == "required"],
            "basic_use_ready": bool(agents_available)}


def needs(s, identity, text, agents_available):
    """Keys this piece of work seems to need and does not have. `blocking` only when nothing could run at all."""
    saved = saved_providers(s, identity)
    missing = []
    if not agents_available:
        agent = next(k for k in KEYS if k["id"] == "agent")
        missing.append({"id": "agent", "label": agent["label"], "provider": None, "blocking": True, "why": "No agent is installed or available, so nothing in this project could run.",
                        "obtain": agent["obtain"], "scope": agent["scope"]})
    lowered = (text or "").lower()
    for rule in RULES:
        if not re.search(rule["pattern"], lowered):
            continue
        if any(p in saved for p in rule["any_of"]):
            continue
        first = next(k for k in KEYS if k["id"] == rule["any_of"][0])
        missing.append({"id": rule["id"], "label": " or ".join(next(k["label"] for k in KEYS if k["id"] == i) for i in rule["any_of"]), "provider": first["provider"],
                        "providers": [next(k["provider"] for k in KEYS if k["id"] == i) for i in rule["any_of"]], "blocking": False, "why": rule["why"],
                        "obtain": first["obtain"], "scope": first["scope"]})
    return {"ready": not missing, "missing": missing}
