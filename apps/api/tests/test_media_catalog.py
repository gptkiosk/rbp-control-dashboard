"""The media-model catalog (fal.ai): listed facts, the operator's own prices, and the saved fal key (write-only)."""
from __future__ import annotations

import media_catalog
from tests.test_auth import begin, complete, secured  # noqa: F401
from tests.test_profiles import signed

FAL_KEY = "fal-test-" + "k" * 30    # clearly synthetic


def test_the_catalog_lists_every_model_with_its_unit_and_source(make_client):
    c = make_client()
    with c:
        data = c.get("/api/media/models").json()
    assert data["provider"] == "fal" and data["fal_key_saved"] is False
    by_id = {m["id"]: m for m in data["models"]}
    assert by_id["fal-ai/nano-banana-2"]["unit"] == "image" and by_id["fal-ai/nano-banana-2"]["price_usd"] == 0.08
    assert by_id["fal-ai/kling-video/v2.5-turbo/pro/image-to-video"]["unit"] == "second"
    assert by_id["minimax/h3-max-turbo/image-to-video"]["tier"] == "draft" and by_id["minimax/h3-max/image-to-video"]["tier"] == "standard"
    assert by_id["minimax/h3-max/image-to-video"]["price_usd"] == 0.08 and by_id["minimax/h3-max-turbo/text-to-video"]["price_usd"] == 0.04
    assert by_id["fal-ai/veo3.1/fast/image-to-video"]["price_usd"] == 0.15        # what fal billed, so a clip never counts as free
    assert by_id["fal-ai/veo3.1/first-last-frame-to-video"]["price_usd"] == 0.40
    assert by_id["fal-ai/kling-video/v2.5-turbo/pro/text-to-video"]["price_usd"] is None   # still unknown: never invented
    assert all(m["price_source"] == media_catalog.SOURCE for m in data["models"])
    assert {m["tier"] for m in data["models"]} >= {"draft", "standard", "premium"}
    assert data["key_rules"]["preset"] == "API" and "fal-ai/veo3.1*" in data["key_rules"]["allowed_models"]


def test_your_own_price_replaces_the_listed_one_and_can_be_cleared(make_client):
    c = make_client()
    with c:
        assert c.get("/api/billing").json()["media_rates"] == {}
        r = c.patch("/api/billing", json={"media_rates": {"fal-ai/kling-video/v2.5-turbo/pro/text-to-video": 0.15}})
        assert r.status_code == 200 and r.json()["media_rates"] == {"fal-ai/kling-video/v2.5-turbo/pro/text-to-video": 0.15}
        row = next(m for m in c.get("/api/media/models").json()["models"] if m["id"] == "fal-ai/kling-video/v2.5-turbo/pro/text-to-video")
        assert row["price_usd"] == 0.15 and row["listed_price_usd"] is None and row["price_source"] == "operator"
        c.patch("/api/billing", json={"media_rates": {"fal-ai/nano-banana-2": 0.09}})
        assert set(c.get("/api/billing").json()["media_rates"]) == {"fal-ai/kling-video/v2.5-turbo/pro/text-to-video", "fal-ai/nano-banana-2"}
        c.patch("/api/billing", json={"media_rates": {"fal-ai/kling-video/v2.5-turbo/pro/text-to-video": None}})
        row = next(m for m in c.get("/api/media/models").json()["models"] if m["id"] == "fal-ai/kling-video/v2.5-turbo/pro/text-to-video")
        assert row["price_usd"] is None and row["price_source"] == media_catalog.SOURCE


def test_unknown_models_and_bad_prices_are_refused(make_client):
    c = make_client()
    with c:
        assert c.patch("/api/billing", json={"media_rates": {"fal-ai/not-a-model": 1}}).status_code == 422
        assert c.patch("/api/billing", json={"media_rates": {"fal-ai/nano-banana-2": -1}}).status_code == 422
        assert c.patch("/api/billing", json={"media_rates": {"fal-ai/nano-banana-2": 99999}}).status_code == 422
        assert c.get("/api/billing").json()["media_rates"] == {}


def test_a_saved_fal_key_is_write_only_and_can_be_removed(secured):  # noqa: F811
    signed(secured)
    assert secured.get("/api/media/models").json()["fal_key_saved"] is False
    r = secured.put("/api/profile/credentials/fal", json={"value": FAL_KEY})
    assert r.status_code == 200 and FAL_KEY not in r.text
    assert {"provider": "fal", "hint": FAL_KEY[-4:]} in r.json()["credentials"]
    listing = secured.get("/api/media/models")
    assert listing.json()["fal_key_saved"] is True and FAL_KEY not in listing.text
    assert FAL_KEY not in secured.get("/api/profile").text
    secured.delete("/api/profile/credentials/fal")
    assert secured.get("/api/media/models").json()["fal_key_saved"] is False


def test_estimates_use_the_unit_and_say_nothing_when_the_price_is_unknown():
    video = next(m for m in media_catalog.MODELS if m["id"] == "fal-ai/kling-video/v2.5-turbo/pro/image-to-video")
    image = next(m for m in media_catalog.MODELS if m["id"] == "fal-ai/nano-banana-2")
    veo = next(m for m in media_catalog.MODELS if m["id"] == "fal-ai/veo3.1/fast/image-to-video")
    flf = next(m for m in media_catalog.MODELS if m["id"] == "fal-ai/veo3.1/first-last-frame-to-video")
    unknown = next(m for m in media_catalog.MODELS if m["id"] == "fal-ai/kling-video/v2.5-turbo/pro/text-to-video")
    assert media_catalog.estimate(video, seconds=5) == 0.35
    assert media_catalog.estimate(image, images=3) == 0.24                                    # 1K, the base price
    assert media_catalog.estimate(image, images=1, resolution="2K") == 0.12                   # fal billed 1.5 units for a 2K picture
    assert media_catalog.estimate(image, images=1, resolution="4K") == 0.16
    assert media_catalog.estimate(veo, seconds=8) == 1.2                                      # Veo 3.1 Fast, $0.15 a second
    assert media_catalog.estimate(flf, seconds=6) == 2.4                                      # the full Veo 3.1 model, $0.40 a second
    assert media_catalog.estimate(next(m for m in media_catalog.MODELS if m["id"] == "minimax/h3-max/image-to-video"), seconds=5, resolution="768P") == 0.4
    assert media_catalog.estimate(next(m for m in media_catalog.MODELS if m["id"] == "minimax/h3-max/image-to-video"), seconds=5, resolution="1080P") == 0.8
    assert media_catalog.estimate(unknown, seconds=5) is None
    assert media_catalog.estimate(unknown, seconds=5, rates={unknown["id"]: 0.1}) == 0.5
