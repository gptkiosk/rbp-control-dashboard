"""Catalog of media-generation models (fal.ai): what each one is, how it is billed, and what it is for.

Facts only. Prices are fal's list prices, checked against fal's own usage table on the date shown: Veo 3.1 Fast billed $0.15 a second and Veo 3.1
$0.40 a second, and Nano Banana 2 billed 1.5 image units at $0.08 for a 2K picture. Estimates are an upper bound (fal billed fewer seconds
than were requested on the clips in that run); fal's usage page is the truth. An operator price saved in the billing settings replaces the
listed one for display. `price_usd` is None only where nothing is known, and a run with no price is counted and shown as unpriced, never as zero.
Nothing here limits spending and nothing is enforced.
"""
from __future__ import annotations

import json

from models import BillingConfig

SOURCE = "https://fal.ai/pricing"
VERIFIED = "2026-10-18"

# tier: the quality level that `media.py generate --tier` maps to (draft is the cheapest model, premium the best); None when not a default
MODELS = [
    {"id": "fal-ai/nano-banana-2", "label": "Nano Banana 2", "kind": "image", "mode": "text-to-image", "unit": "image", "price_usd": 0.08, "tier": "standard", "resolution_factor": {"1K": 1, "2K": 1.5, "4K": 2},
     "note": "Standard stills at 2K. Draft tier uses it at 1K for composition checks."},
    {"id": "fal-ai/nano-banana-2/edit", "label": "Nano Banana 2 (edit, reference images)", "kind": "image", "mode": "image-edit", "unit": "image", "price_usd": 0.08, "tier": "standard", "resolution_factor": {"1K": 1, "2K": 1.5, "4K": 2},
     "note": "Takes reference images, so your concept art can steer the style."},
    {"id": "fal-ai/nano-banana-pro", "label": "Nano Banana Pro", "kind": "image", "mode": "text-to-image", "unit": "image", "price_usd": 0.15, "tier": "premium", "resolution_factor": {"1K": 1, "2K": 1, "4K": 2},
     "note": "4K output is charged at double the standard rate."},
    {"id": "fal-ai/nano-banana-pro/edit", "label": "Nano Banana Pro (edit, reference images)", "kind": "image", "mode": "image-edit", "unit": "image", "price_usd": 0.15, "tier": "premium", "resolution_factor": {"1K": 1, "2K": 1, "4K": 2}, "resolution_factor": {"1K": 1, "2K": 1, "4K": 2},
     "note": "4K output is charged at double the standard rate."},
    {"id": "minimax/h3-max-turbo/text-to-video", "label": "MiniMax H3 Max Turbo (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": 0.04, "tier": "draft",
     "resolution_factor": {"480P": 0.625, "768P": 1, "1080P": 2},
     "note": "Cheapest clips. $0.04 a second at 768p after 31 October 2026 (a launch discount runs until then). Takes any length from about 1 to 15 seconds, so MCD asks for the shortest clip a slot can use."},
    {"id": "minimax/h3-max-turbo/image-to-video", "label": "MiniMax H3 Max Turbo (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": 0.04, "tier": "draft",
     "resolution_factor": {"480P": 0.625, "768P": 1, "1080P": 2},
     "note": "Starts from your approved still and can also end on a second still, so it makes the theme transition plates too."},
    {"id": "minimax/h3-max/text-to-video", "label": "MiniMax H3 Max (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": 0.08, "tier": "standard",
     "resolution_factor": {"480P": 0.625, "768P": 1, "1080P": 2},
     "note": "Default clip tier. $0.08 a second at 768p after 31 October 2026, about half of Veo 3.1 Fast and a fifth of Veo 3.1."},
    {"id": "minimax/h3-max/image-to-video", "label": "MiniMax H3 Max (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": 0.08, "tier": "standard",
     "resolution_factor": {"480P": 0.625, "768P": 1, "1080P": 2},
     "note": "Default for clips that start from a still, and for transitions (start and end stills). Prices are the list prices after the launch discount, so an estimate is an upper bound until 31 October."},
    {"id": "fal-ai/kling-video/v2.5-turbo/pro/image-to-video", "label": "Kling 2.5 Turbo Pro (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": 0.07, "tier": None,
     "note": "Cheapest clip tier. 5 or 10 seconds. An end-frame field lets it morph between two stills."},
    {"id": "fal-ai/kling-video/v2.5-turbo/pro/text-to-video", "label": "Kling 2.5 Turbo Pro (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": None, "tier": None,
     "note": "Not priced on fal's pricing page."},
    {"id": "fal-ai/kling-video/v3/standard/image-to-video", "label": "Kling v3 Standard (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": 0.14, "tier": None,
     "note": "3 to 15 seconds, start and end image fields. Name it with --model."},
    {"id": "fal-ai/kling-video/v3/standard/text-to-video", "label": "Kling v3 Standard (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": 0.14, "tier": None, "note": ""},
    {"id": "fal-ai/veo3.1/fast/image-to-video", "label": "Veo 3.1 Fast (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": 0.15, "tier": None,
     "note": "Not a default tier now. 4, 6 or 8 seconds, up to 4K. Billed $0.15 a second in practice, so an 8 second clip is about $1.20 at most."},
    {"id": "fal-ai/veo3.1/fast", "label": "Veo 3.1 Fast (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": 0.15, "tier": None, "note": "Billed $0.15 a second in practice."},
    {"id": "fal-ai/veo3.1/image-to-video", "label": "Veo 3.1 (image to video)", "kind": "video", "mode": "image-to-video", "unit": "second", "price_usd": 0.40, "tier": "premium",
     "note": "Best quality tier. Billed $0.40 a second, so a 6 second clip is about $2.40 at most."},
    {"id": "fal-ai/veo3.1", "label": "Veo 3.1 (text to video)", "kind": "video", "mode": "text-to-video", "unit": "second", "price_usd": 0.40, "tier": "premium", "note": "Billed $0.40 a second."},
    {"id": "fal-ai/veo3.1/first-last-frame-to-video", "label": "Veo 3.1 (first frame to last frame)", "kind": "video", "mode": "first-last-frame", "unit": "second", "price_usd": 0.40, "tier": "premium",
     "note": "Morphs between two stills: used for the theme transition plates. This is the full Veo 3.1 model, billed $0.40 a second: the dearest thing MCD calls, so do not generate it twice."},
]

KEY_RULES = {
    "preset": "API",
    "note": "Create the key with the API preset (model execution and storage). Restrict allowed models so a mistake or a leaked key cannot call other models. fal fixes a key's model list when the key is created and cannot change it afterwards, so a key made before a model was added has to be replaced by a new key. If a wildcard is refused, add the exact endpoint ids instead.",
    "exact_models": ["minimax/h3-max/text-to-video", "minimax/h3-max/image-to-video", "minimax/h3-max-turbo/text-to-video", "minimax/h3-max-turbo/image-to-video",
                     "fal-ai/nano-banana-2", "fal-ai/nano-banana-2/edit", "fal-ai/nano-banana-pro", "fal-ai/nano-banana-pro/edit",
                     "fal-ai/veo3.1", "fal-ai/veo3.1/image-to-video", "fal-ai/veo3.1/first-last-frame-to-video", "fal-ai/veo3.1/fast", "fal-ai/veo3.1/fast/image-to-video"],
    "allowed_models": ["fal-ai/nano-banana-2*", "fal-ai/nano-banana-pro*", "fal-ai/veo3.1*", "minimax/h3-max*", "fal-ai/kling-video/v2.5-turbo/pro/*", "fal-ai/kling-video/v3/standard/*"],
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


def estimate(model, seconds=None, images=None, rates=None, resolution=None):
    """A rough upper-bound cost for one generation, or None when the price is unknown. Display only."""
    price = (rates or {}).get(model["id"], model["price_usd"])
    if price is None:
        return None
    factor = (model.get("resolution_factor") or {}).get(resolution, 1)
    if model["unit"] == "second":
        return round(price * factor * seconds, 4)
    return round(price * factor * (images or 1), 4)
