"""Catalog of media-generation models (fal.ai): what each one is, how it is billed, and what it is for.

Facts only. Prices are fal's published list prices on the date shown and are approximate: resolution, duration and audio can change the
final cost. `price_usd` is None where fal's pricing page did not list the model; look it up with `tools/media/media.py price` (which asks
fal for the live figure) or set your own in Agents, Billing & rates. An operator price saved in the billing settings replaces the listed one
for display. Nothing here limits spending and nothing is enforced.
"""
from __future__ import annotations

import json

from models import BillingConfig

SOURCE = "https://fal.ai/pricing"
VERIFIED = "2026-10-17"

# tier: the quality level that `media.py generate --tier` maps to (draft is the cheapest model, premium the best); None when not a default
MODELS = [
    {"id": "fal-ai/nano-banana-2", "label": "Nano Banana 2", "kind": "image", "mode": "text-to-image", "unit": "image", "price_usd": 0.08, "tier": "standard",
     "note": "Standard stills at 2K. Draft tier uses it at 1K for composition checks."},
    {"id": "fal-ai/nano-banana-2/edit", "label": "Nano Banana 2 (edit, reference images)", "kind": "image", "mode": "image-edit", "unit": "image", "price_usd": 0.08, "tier": "standard",
     "note": "Takes reference images, so your concept art can steer the style."},
    {"id": "fal-ai/nano-banana-pro", "label": "Nano Banana Pro", "kind": "image", "mode": "text-to-image", "unit": "image", "price_usd": 0.15, "tier": "premium",
     "note": "4K output is charged at double the standard rate."},
    {"id": "fal-ai/nano-banana-pro/edit", "label": "Nano Banana Pro (edit, reference images)", "kind": "image", "mode": "image-edit", "unit": "image", "price_usd": 0.15, "tier": "premium",
     "note": "4K output is charged at double the standard rate."},
    {"id": "fal-ai/kling-video/v2.5-turbo/pro/image-to-video", "label": "Kling 2.5 Turbo Pro (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": 0.07, "tier": "draft",
     "note": "Cheapest clip tier. 5 or 10 seconds. An end-frame field lets it morph between two stills."},
    {"id": "fal-ai/kling-video/v2.5-turbo/pro/text-to-video", "label": "Kling 2.5 Turbo Pro (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": None, "tier": "draft",
     "note": "Not priced on fal's pricing page."},
    {"id": "fal-ai/kling-video/v3/standard/image-to-video", "label": "Kling v3 Standard (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": 0.14, "tier": None,
     "note": "3 to 15 seconds, start and end image fields. Name it with --model."},
    {"id": "fal-ai/kling-video/v3/standard/text-to-video", "label": "Kling v3 Standard (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": 0.14, "tier": None, "note": ""},
    {"id": "fal-ai/veo3.1/fast/image-to-video", "label": "Veo 3.1 Fast (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": None, "tier": "standard",
     "note": "Default clip tier. 4, 6 or 8 seconds, up to 4K. Price not on fal's pricing page: check with media.py price."},
    {"id": "fal-ai/veo3.1/fast", "label": "Veo 3.1 Fast (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": None, "tier": "standard", "note": ""},
    {"id": "fal-ai/veo3.1/image-to-video", "label": "Veo 3.1 (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": None, "tier": "premium",
     "note": "Best quality tier. Price not on fal's pricing page: check with media.py price."},
    {"id": "fal-ai/veo3.1", "label": "Veo 3.1 (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": None, "tier": "premium", "note": ""},
    {"id": "fal-ai/veo3.1/first-last-frame-to-video", "label": "Veo 3.1 (first frame to last frame)", "kind": "video", "mode": "first-last-frame", "unit": "second", "price_usd": None, "tier": "standard",
     "note": "Morphs between two stills: used for the theme transition plates in the standard and premium tiers."},
]

KEY_RULES = {
    "preset": "API",
    "note": "Create the key with the API preset (model execution and storage). Restrict allowed models to the patterns below so a mistake or a leaked key cannot call other models.",
    "allowed_models": ["fal-ai/nano-banana-2*", "fal-ai/nano-banana-pro*", "fal-ai/veo3.1*", "fal-ai/kling-video/v2.5-turbo/pro/*", "fal-ai/kling-video/v3/standard/*"],
}


def saved_rates(s):
    row = s.get(BillingConfig, 1)
    out = (json.loads(row.payload) if row else {}).get("media_rates") or {}
    return {k: float(v) for k, v in out.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0}


def catalog(s):
    """Every model with its listed price and the operator's own price when one is saved. `price_usd` is what applies."""
    mine = saved_rates(s)
    models = []
    for m in MODELS:
        row = dict(m, listed_price_usd=m["price_usd"], price_source=SOURCE, price_verified=VERIFIED)
        if m["id"] in mine:
            row["price_usd"], row["price_source"] = mine[m["id"]], "operator"
        models.append(row)
    return {"provider": "fal", "models": models, "key_rules": KEY_RULES}


def estimate(model, seconds=None, images=None, rates=None):
    """A rough cost for one generation, or None when the price is unknown. Display only."""
    price = (rates or {}).get(model["id"], model["price_usd"])
    if price is None:
        return None
    return round(price * (seconds if model["unit"] == "second" else (images or 1)), 4)
