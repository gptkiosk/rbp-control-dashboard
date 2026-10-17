"""Keys and access: what each key is for, and the check that runs before a project is created."""
from __future__ import annotations

import pytest

from tests.test_auth import begin, complete, secured  # noqa: F401
from tests.test_profiles import signed

FAL = "fal-test-" + "k" * 30      # clearly synthetic
BRIEF_VIDEO = "A site with an AI-generated video background for each theme."
BRIEF_IMAGES = "Generate custom art for both themes and embed it."


@pytest.fixture
def with_agent(monkeypatch):
    monkeypatch.setattr("routes.keys.available_agents", lambda: ["claude"])


def test_the_registry_says_what_is_required_for_basic_use_and_what_is_saved(secured, with_agent):  # noqa: F811
    signed(secured)
    data = secured.get("/api/keys").json()
    levels = {k["id"]: k["level"] for k in data["keys"]}
    assert levels == {"agent": "required", "openrouter": "recommended", "fal": "optional", "discord": "optional", "github": "optional"}
    assert data["basic_use"] == ["agent"] and data["basic_use_ready"] is True
    assert all(k["purpose"] and k["obtain"] for k in data["keys"])
    fal = next(k for k in data["keys"] if k["id"] == "fal")
    assert fal["in_place"] is False and fal["detail"] == "not saved"
    secured.put("/api/profile/credentials/fal", json={"value": FAL})
    again = secured.get("/api/keys")
    assert FAL not in again.text
    fal = next(k for k in again.json()["keys"] if k["id"] == "fal")
    assert fal["in_place"] is True and fal["detail"] == f"saved ····{FAL[-4:]}"


def test_basic_use_is_not_ready_without_an_agent(secured, monkeypatch):  # noqa: F811
    monkeypatch.setattr("routes.keys.available_agents", lambda: [])
    signed(secured)
    assert secured.get("/api/keys").json()["basic_use_ready"] is False
    result = secured.post("/api/keys/check", json={"text": "anything"}).json()
    assert result["ready"] is False and result["missing"][0]["id"] == "agent" and result["missing"][0]["blocking"] is True


def test_a_project_that_mentions_video_is_asked_for_a_fal_key_but_not_blocked(secured, with_agent):  # noqa: F811
    signed(secured)
    result = secured.post("/api/keys/check", json={"text": BRIEF_VIDEO}).json()
    assert result["ready"] is False
    item = result["missing"][0]
    assert (item["id"], item["provider"], item["blocking"]) == ("video", "fal", False)
    assert "fallbacks" in item["why"] and item["obtain"].startswith("https://fal.ai")
    secured.put("/api/profile/credentials/fal", json={"value": FAL})
    assert secured.post("/api/keys/check", json={"text": BRIEF_VIDEO}).json() == {"ready": True, "missing": []}


def test_image_generation_is_satisfied_by_either_the_openrouter_or_the_fal_key(secured, with_agent):  # noqa: F811
    signed(secured)
    item = secured.post("/api/keys/check", json={"text": BRIEF_IMAGES}).json()["missing"][0]
    assert item["id"] == "images" and item["providers"] == ["openrouter", "fal"]
    secured.put("/api/profile/credentials/openrouter", json={"value": "sk-or-test-" + "x" * 30})
    assert secured.post("/api/keys/check", json={"text": BRIEF_IMAGES}).json()["ready"] is True


def test_ordinary_text_needs_nothing_and_a_video_player_mention_does_not_trigger(secured, with_agent):  # noqa: F811
    signed(secured)
    assert secured.post("/api/keys/check", json={"text": "Fix the login form and add unit tests."}).json()["ready"] is True
    assert secured.post("/api/keys/check", json={"text": "Embed the existing company video player on the About page."}).json()["ready"] is True
