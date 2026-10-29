"""MCD-run fal generation: the saved key stays inside MCD, the project folder is only data, and every run is explicit and recorded."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import media_catalog
import media_generate as mg
from settings import get_settings
from tests.test_auth import begin, complete, secured  # noqa: F401
from tests.test_profiles import bridge, signed

FAL = "fal-test-" + "k" * 30      # clearly synthetic


def media_bytes(kind):
    if not shutil.which("ffmpeg"):
        return b"not-checked-without-ffprobe" * 10
    with __import__("tempfile").TemporaryDirectory() as tmp:
        out = Path(tmp) / ("o.mp4" if kind == "video" else "o.png")
        src = "testsrc2=size=640x360:rate=24:duration=5" if kind == "video" else "testsrc2=size=640x360:rate=1:duration=1"
        extra = ["-c:v", "libx264", "-pix_fmt", "yuv420p"] if kind == "video" else ["-frames:v", "1"]
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src, *extra, str(out)], check=True)
        return out.read_bytes()


class FakeFal(BaseHTTPRequestHandler):
    log = []
    fail_status = None
    evil = False
    clip = b""
    still = b""
    polls = 0

    def _send(self, obj=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeFal.log.append(("POST", self.path, self.headers.get("Authorization"), body))
        me = f"http://127.0.0.1:{self.server.server_port}"
        if FakeFal.evil:
            return self._send({"request_id": "r", "status_url": "https://evil.example.com/s", "response_url": "https://evil.example.com/r"})
        self._send({"request_id": "req-1", "status_url": me + "/status/1", "response_url": me + "/result/1"})

    def do_GET(self):
        FakeFal.log.append(("GET", self.path, self.headers.get("Authorization"), None))
        me = f"http://127.0.0.1:{self.server.server_port}"
        if self.path.startswith("/status"):
            FakeFal.polls += 1
            if FakeFal.polls % 2:
                return self._send({"status": "IN_PROGRESS"})
            return self._send({"status": "COMPLETED", **({"error": FakeFal.fail_status, "error_type": "x"} if FakeFal.fail_status else {})})
        if self.path.startswith("/result"):
            return self._send({"video": {"url": me + "/files/o.mp4"}, "images": [{"url": me + "/files/o.png"}]})
        if self.path.startswith("/files/o.mp4"):
            return self._send(raw=FakeFal.clip, ctype="video/mp4")
        if self.path.startswith("/files/o.png"):
            return self._send(raw=FakeFal.still, ctype="image/png")
        if self.path.startswith("/v1/models/pricing"):
            return self._send({"prices": [{"endpoint_id": "e", "unit_price": 0.07, "unit": "second", "currency": "USD"}]})
        self.send_error(404)

    def log_message(self, *a):
        pass


SLOTS = {"slots": [
    {"name": "hero-still", "kind": "image", "world": "light", "prompt": "A barber shop interior. No text.", "refs": ["reference/concept.png"]},
    {"name": "hero-clip", "kind": "video", "world": "light", "prompt": "Slow dust motes.", "seconds": [4, 8], "from_still": "hero-still"},
    {"name": "plate", "kind": "video", "world": "dark", "prompt": "A vault door closes.", "seconds": [4, 6], "first_still": "hero-still", "last_still": "hero-still"},
]}


@pytest.fixture
def env(tmp_path, secured, monkeypatch):  # noqa: F811
    FakeFal.log, FakeFal.fail_status, FakeFal.evil, FakeFal.polls = [], None, False, 0
    FakeFal.clip, FakeFal.still = media_bytes("video"), media_bytes("image")
    server = HTTPServer(("127.0.0.1", 0), FakeFal)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    settings = get_settings()
    settings.fal_queue_base, settings.fal_api_base, settings.fal_poll_s = base, base + "/v1", 0.0
    folder = tmp_path / "ws" / "site"
    (folder / "media").mkdir(parents=True)
    (folder / "reference").mkdir()
    (folder / "assets" / "img").mkdir(parents=True)
    (folder / "media" / "slots.json").write_text(json.dumps(SLOTS))
    (folder / "reference" / "concept.png").write_bytes(FakeFal.still)
    (folder / "assets" / "img" / "hero-still.jpg").write_bytes(FakeFal.still)
    signed(secured)
    secured.put("/api/profile/credentials/fal", json={"value": FAL})
    yield secured, folder
    server.shutdown()


def run_and_wait(client, body, expect=202):
    r = client.post("/api/media/generate", json={"confirm_spend": True, "regenerate": True, **body})      # the fixture publishes hero-still, which clips are made from
    assert r.status_code == expect, r.text
    if expect != 202:
        return r
    for job in r.json()["jobs"]:
        for _ in range(200):
            state = client.get(f"/api/media/jobs/{job}").json()
            if state["state"] in {"done", "failed"}:
                break
            time.sleep(0.05)
    return r


def test_a_folder_with_slots_is_listed_with_prices_for_each_tier(env):
    client, folder = env
    assert {"path": str(folder.resolve()), "name": "site"} in client.get("/api/media/folders").json()["folders"]
    data = client.get("/api/media/slots", params={"working_dir": str(folder)}).json()
    by = {s["name"]: s for s in data["slots"]}
    assert by["hero-still"]["plans"]["draft"]["endpoint"] == "fal-ai/nano-banana-2/edit"
    assert by["hero-still"]["plans"]["premium"]["endpoint"] == "fal-ai/nano-banana-pro/edit"
    assert by["hero-still"]["plans"]["standard"]["estimate_usd"] == 0.12        # 2K is 1.5 units of $0.08
    assert by["hero-clip"]["plans"]["draft"]["estimate_usd"] == 0.2                # 5 s of MiniMax Turbo at $0.04: the shortest clip the slot can use
    assert by["hero-clip"]["plans"]["standard"]["estimate_usd"] == 0.4            # 5 s of MiniMax H3 Max at $0.08
    assert by["hero-clip"]["plans"]["premium"]["estimate_usd"] == 3.2             # 8 s of Veo 3.1 (not fast) at $0.40 is the dear tier, shown before anything is spent
    assert by["plate"]["plans"]["standard"]["endpoint"] == "minimax/h3-max/image-to-video"
    assert by["plate"]["plans"]["premium"]["endpoint"] == "fal-ai/veo3.1/first-last-frame-to-video"
    assert by["hero-clip"]["waiting_for_stills"] == []


def test_a_clip_run_calls_fal_with_the_saved_key_and_saves_a_candidate(env):
    client, folder = env
    r = run_and_wait(client, {"working_dir": str(folder), "slot": "hero-clip", "tier": "draft"})
    posts = [e for e in FakeFal.log if e[0] == "POST"]
    assert posts[0][1] == "/minimax/h3-max-turbo/image-to-video"
    assert posts[0][2] == "Key " + FAL
    assert posts[0][3]["image_url"].startswith("data:image/")
    assert posts[0][3]["duration"] == 5.0 and posts[0][3]["resolution"] == "768P" and "end_image_url" not in posts[0][3]
    downloads = [e for e in FakeFal.log if e[1].startswith("/files/")]
    assert downloads and all(e[2] is None for e in downloads)                       # no key on the download
    assert r.json()["estimate_usd_each"] == 0.2
    assert (folder / "media" / "candidates" / "hero-clip-1.mp4").stat().st_size > 0
    side = json.loads((folder / "media" / "candidates" / "hero-clip-1.json").read_text())
    assert side["model"] == "minimax/h3-max-turbo/image-to-video" and side["tool"].startswith("fal")
    job = client.get(f"/api/media/jobs/{r.json()['jobs'][0]}").json()
    assert job["state"] == "done" and job["files"][0]["path"] == "media/candidates/hero-clip-1.mp4"


def test_nothing_the_api_returns_or_the_ledger_stores_contains_the_key(env):
    client, folder = env
    r = run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    texts = [r.text, client.get("/api/media/ledger").text, client.get("/api/media/folders").text, client.get(f"/api/media/jobs/{r.json()['jobs'][0]}").text]
    texts += [p.read_text(errors="ignore") for p in (folder / "media").rglob("*.json")]
    texts += [(Path(get_settings().data_dir) / "media" / "ledger.jsonl").read_text()]
    assert all(FAL not in t for t in texts)


def test_the_ledger_records_each_run_with_an_estimate_and_a_total(env):
    client, folder = env
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still", "count": 2})
    ledger = client.get("/api/media/ledger").json()
    assert ledger["done"] == 2 and ledger["estimated_usd"] == 0.24 and ledger["unpriced"] == 0
    assert ledger["rows"][0]["endpoint"] == "fal-ai/nano-banana-2/edit" and ledger["rows"][0]["request_id"] == "req-1"
    assert "not invoices" in ledger["note"]


def test_a_failed_run_leaves_no_candidate_and_is_recorded(env):
    client, folder = env
    FakeFal.fail_status = "content policy"
    r = run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    job = client.get(f"/api/media/jobs/{r.json()['jobs'][0]}").json()
    assert job["state"] == "failed" and "content policy" in job["error"]
    assert not list((folder / "media" / "candidates").glob("*")) if (folder / "media" / "candidates").exists() else True
    assert client.get("/api/media/ledger").json()["rows"][-1]["status"] == "failed"


def test_a_link_to_another_host_never_receives_the_key(env):
    client, folder = env
    FakeFal.evil = True
    r = run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    assert client.get(f"/api/media/jobs/{r.json()['jobs'][0]}").json()["state"] == "failed"
    assert not [e for e in FakeFal.log if e[0] == "GET"]                            # nothing was ever fetched from the foreign link


def test_it_refuses_without_confirmation_a_saved_key_or_an_unpublished_still(env):
    client, folder = env
    body = {"working_dir": str(folder), "slot": "hero-clip"}
    assert client.post("/api/media/generate", json=body).status_code == 422          # confirm_spend missing
    (folder / "assets" / "img" / "hero-still.jpg").unlink()
    r = client.post("/api/media/generate", json={"confirm_spend": True, **body})
    assert r.status_code == 422 and "not published yet" in r.text
    assert [e for e in FakeFal.log if e[0] == "POST"] == []
    client.delete("/api/profile/credentials/fal")
    assert client.post("/api/media/generate", json={"confirm_spend": True, "working_dir": str(folder), "slot": "hero-still"}).status_code == 422


def test_folders_outside_the_allowed_roots_and_references_that_escape_are_refused(env, tmp_path):
    client, folder = env
    outside = tmp_path / "elsewhere"
    (outside / "media").mkdir(parents=True)
    (outside / "media" / "slots.json").write_text(json.dumps(SLOTS))
    assert client.get("/api/media/slots", params={"working_dir": str(outside)}).status_code == 422
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"x" * 50)
    slots = json.loads((folder / "media" / "slots.json").read_text())
    slots["slots"][0]["refs"] = ["../../secret.png"]
    (folder / "media" / "slots.json").write_text(json.dumps(slots))
    assert client.post("/api/media/generate", json={"confirm_spend": True, "working_dir": str(folder), "slot": "hero-still"}).status_code == 422
    (folder / "reference" / "link.png").symlink_to(secret)
    slots["slots"][0]["refs"] = ["reference/link.png"]
    (folder / "media" / "slots.json").write_text(json.dumps(slots))
    assert client.post("/api/media/generate", json={"confirm_spend": True, "working_dir": str(folder), "slot": "hero-still"}).status_code == 422
    assert [e for e in FakeFal.log if e[0] == "POST"] == []


def test_slot_files_are_validated_as_data(env):
    client, folder = env
    for bad in ({"slots": [{"name": "../x", "kind": "image", "prompt": "p"}]}, {"slots": [{"name": "ok", "kind": "audio", "prompt": "p"}]},
                {"slots": [{"name": "ok", "kind": "image", "prompt": ""}]}, {"slots": "no"}, {"slots": [{"name": "a", "kind": "image", "prompt": "p"}] * 2}):
        (folder / "media" / "slots.json").write_text(json.dumps(bad))
        assert client.get("/api/media/slots", params={"working_dir": str(folder)}).status_code == 422


def test_only_a_catalog_model_can_be_named(env):
    client, folder = env
    r = client.post("/api/media/generate", json={"confirm_spend": True, "working_dir": str(folder), "slot": "hero-still", "model": "fal-ai/sora-2/text-to-video"})
    assert r.status_code == 422
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-clip", "model": "fal-ai/kling-video/v3/standard/image-to-video"})
    posts = [e for e in FakeFal.log if e[0] == "POST"]
    assert posts[-1][1] == "/fal-ai/kling-video/v3/standard/image-to-video" and "start_image_url" in posts[-1][3]


def test_pick_copies_a_candidate_into_the_inbox_without_running_anything(env):
    client, folder = env
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    r = client.post("/api/media/pick", json={"working_dir": str(folder), "slot": "hero-still", "candidate": "hero-still-1.png"})
    assert r.status_code == 200 and r.json()["next"] == "python3 tools/media/media.py ingest hero-still"
    assert (folder / "media" / "inbox" / "hero-still.png").stat().st_size > 0 and (folder / "media" / "inbox" / "hero-still.json").exists()
    assert client.post("/api/media/pick", json={"working_dir": str(folder), "slot": "hero-still", "candidate": "../slots.json"}).status_code == 422
    assert client.post("/api/media/pick", json={"working_dir": str(folder), "slot": "plate", "candidate": "hero-still-1.png"}).status_code == 422


def test_agents_and_the_project_bridge_cannot_use_any_of_it(env):
    client, folder = env
    import profiles
    profiles.bridge_token(get_settings(), True)
    agent = bridge(client)
    for method, path in (("get", "/api/media/folders"), ("get", f"/api/media/slots?working_dir={folder}"), ("get", "/api/media/ledger"), ("get", "/api/media/jobs/x")):
        assert getattr(agent, method)(path).status_code in {401, 403}, path
    assert agent.post("/api/media/generate", json={"confirm_spend": True, "working_dir": str(folder), "slot": "hero-still"}).status_code in {401, 403}


def test_every_endpoint_the_generator_can_choose_is_in_the_catalog():
    ids = {m["id"] for m in media_catalog.MODELS}
    for slot in ({"kind": "image", "refs": ["a"]}, {"kind": "image"}, {"kind": "video", "from_still": "a"}, {"kind": "video", "first_still": "a", "last_still": "b"}, {"kind": "video"}):
        for tier in mg.TIERS:
            assert mg.endpoint_for(slot, tier) in ids, (slot, tier)


def test_each_still_is_made_in_its_own_shape_unless_one_is_asked_for(env):
    client, folder = env
    slots = {"slots": [
        {"name": "hero-still", "kind": "image", "prompt": "Wide scene.", "width": 2560, "height": 1100},
        {"name": "card-x", "kind": "image", "prompt": "Square card.", "width": 1200, "height": 1200},
        {"name": "about-x", "kind": "image", "prompt": "Vignette.", "width": 1600, "height": 900},
        {"name": "tall-x", "kind": "image", "prompt": "Portrait.", "width": 900, "height": 1200},
        {"name": "plain-x", "kind": "image", "prompt": "No size given."},
    ]}
    (folder / "media" / "slots.json").write_text(json.dumps(slots))
    for name, expected in (("hero-still", "21:9"), ("card-x", "1:1"), ("about-x", "16:9"), ("tall-x", "3:4"), ("plain-x", "16:9")):
        FakeFal.log = []
        run_and_wait(client, {"working_dir": str(folder), "slot": name})
        body = [e for e in FakeFal.log if e[0] == "POST"][0][3]
        assert body["aspect_ratio"] == expected, (name, body["aspect_ratio"])
    FakeFal.log = []
    run_and_wait(client, {"working_dir": str(folder), "slot": "card-x", "aspect": "4:5", "another_take": True})
    assert [e for e in FakeFal.log if e[0] == "POST"][0][3]["aspect_ratio"] == "4:5"                 # an explicit choice still wins


def test_a_slot_only_claims_its_own_numbered_candidates_not_a_longer_slot_name(env):
    """`hero-light` is a video slot and `hero-light-still` an image slot: the second's candidates must never show up under the first."""
    client, folder = env
    slots = {"slots": [{"name": "hero-light-still", "kind": "image", "prompt": "Still."}, {"name": "hero-light", "kind": "video", "prompt": "Clip."}]}
    (folder / "media" / "slots.json").write_text(json.dumps(slots))
    cand = folder / "media" / "candidates"
    cand.mkdir(parents=True)
    for name in ("hero-light-still-1.png", "hero-light-still-2.png", "hero-light-1.mp4", "hero-light-1.json", "hero-light-notes.png", "hero-light-x.mp4"):
        (cand / name).write_bytes(b"data")
    by = {s["name"]: s for s in client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["slots"]}
    assert by["hero-light-still"]["candidates"] == ["hero-light-still-1.png", "hero-light-still-2.png"]
    assert by["hero-light"]["candidates"] == ["hero-light-1.mp4"]                       # not the stills, not the sidecar, not oddly named files
    body = {"working_dir": str(folder), "slot": "hero-light", "candidate": "hero-light-still-1.png"}
    assert client.post("/api/media/pick", json=body).status_code == 422                 # a still can never be picked into the video slot
    assert client.post("/api/media/pick", json={**body, "candidate": "hero-light-1.mp4"}).status_code == 200
    assert (folder / "media" / "inbox" / "hero-light.mp4").exists() and not (folder / "media" / "inbox" / "hero-light.png").exists()


def test_a_candidate_can_be_viewed_by_the_operator_only_and_only_if_it_is_a_real_candidate(env):
    client, folder = env
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    r = client.get("/api/media/candidate", params={"working_dir": str(folder), "name": "hero-still-1.png"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and len(r.content) > 0
    assert "inline" in r.headers["content-disposition"]
    for name in ("hero-still-1.json", "../slots.json", "hero-still-1.png/../../slots.json", "slots.json", "hero-still-9.png", "hero-still-.png", "HERO-1.png"):
        assert client.get("/api/media/candidate", params={"working_dir": str(folder), "name": name}).status_code == 404, name
    (folder / "media" / "candidates" / "hero-still-3.png").symlink_to(folder / "media" / "slots.json")
    assert client.get("/api/media/candidate", params={"working_dir": str(folder), "name": "hero-still-3.png"}).status_code == 404     # a link out of the folder
    assert client.get("/api/media/candidate", params={"working_dir": "/etc", "name": "hero-still-1.png"}).status_code == 422
    import profiles
    profiles.bridge_token(get_settings(), True)
    assert bridge(client).get("/api/media/candidate", params={"working_dir": str(folder), "name": "hero-still-1.png"}).status_code in {401, 403}


needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def small_slots(folder):
    slots = json.loads((folder / "media" / "slots.json").read_text())
    for s in slots["slots"]:
        s["min_width"] = 300
    (folder / "media" / "slots.json").write_text(json.dumps(slots))


@needs_ffmpeg
def test_a_picked_still_is_published_by_mcd_with_provenance_and_the_inventory(env):
    client, folder = env
    small_slots(folder)
    (folder / "assets" / "img" / "hero-still.jpg").unlink()
    def slot_row():
        return next(s for s in client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["slots"] if s["name"] == "hero-still")
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    assert slot_row()["inbox"] is None and slot_row()["published"] is False
    assert client.post("/api/media/publish", json={"working_dir": str(folder), "slot": "hero-still"}).status_code == 404          # nothing picked yet
    client.post("/api/media/pick", json={"working_dir": str(folder), "slot": "hero-still", "candidate": "hero-still-1.png"})
    assert slot_row()["inbox"] == "hero-still.png"
    r = client.post("/api/media/publish", json={"working_dir": str(folder), "slot": "hero-still"})
    assert r.status_code == 200, r.text
    assert [f["path"] for f in r.json()["files"]] == ["assets/img/hero-still.jpg"] and r.json()["files"][0]["bytes"] > 0
    assert slot_row()["published"] is True
    provenance = json.loads((folder / "media" / "provenance.json").read_text())["hero-still"]
    assert provenance["tool"] == "fal (run by MCD)" and provenance["ai_generated"] is True and provenance["files"] == "assets/img/hero-still.jpg"
    inventory = (folder / "assets" / "ART-INVENTORY.md").read_text()
    assert "hero-still" in inventory and "fal (run by MCD)" in inventory and "<!-- media:begin -->" in inventory
    assert FAL not in inventory and FAL not in json.dumps(provenance)


@needs_ffmpeg
def test_a_picked_clip_is_published_silent_with_both_formats_and_a_poster(env):
    client, folder = env
    small_slots(folder)
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-clip", "tier": "draft"})
    client.post("/api/media/pick", json={"working_dir": str(folder), "slot": "hero-clip", "candidate": "hero-clip-1.mp4"})
    r = client.post("/api/media/publish", json={"working_dir": str(folder), "slot": "hero-clip"})
    assert r.status_code == 200, r.text
    assert sorted(f["path"] for f in r.json()["files"]) == ["assets/video/hero-clip.jpg", "assets/video/hero-clip.mp4", "assets/video/hero-clip.webm"]
    assert all(f["bytes"] <= 4 * 1024 * 1024 for f in r.json()["files"])


@needs_ffmpeg
def test_publish_refuses_a_draft_that_is_too_small_and_a_pick_with_no_recorded_tool(env):
    client, folder = env
    (folder / "assets" / "img" / "hero-still.jpg").unlink()
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})                    # the mock image is 640 px wide; the slot needs 960
    client.post("/api/media/pick", json={"working_dir": str(folder), "slot": "hero-still", "candidate": "hero-still-1.png"})
    r = client.post("/api/media/publish", json={"working_dir": str(folder), "slot": "hero-still"})
    assert r.status_code == 422 and "too small" in r.text and not (folder / "assets" / "img" / "hero-still.jpg").exists()
    small_slots(folder)
    (folder / "media" / "inbox" / "hero-still.json").write_text(json.dumps({"model": "m"}))
    r = client.post("/api/media/publish", json={"working_dir": str(folder), "slot": "hero-still"})
    assert r.status_code == 422 and "tool" in r.text


def test_publish_is_operator_only_and_stays_inside_the_allowed_folders(env, tmp_path):
    client, folder = env
    import profiles
    profiles.bridge_token(get_settings(), True)
    assert bridge(client).post("/api/media/publish", json={"working_dir": str(folder), "slot": "hero-still"}).status_code in {401, 403}
    assert client.post("/api/media/publish", json={"working_dir": "/etc", "slot": "hero-still"}).status_code == 422
    assert client.post("/api/media/publish", json={"working_dir": str(folder), "slot": "no-such-slot"}).status_code == 422
    inbox = folder / "media" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "hero-still.png").symlink_to(folder / "media" / "slots.json")
    assert client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["slots"][0]["inbox"] is None         # a link is never a pick


def test_a_published_slot_is_not_regenerated_unless_asked_and_a_running_one_is_not_duplicated(env):
    client, folder = env
    body = {"working_dir": str(folder), "slot": "hero-clip"}
    (folder / "assets" / "video").mkdir(parents=True)
    (folder / "assets" / "video" / "hero-clip.mp4").write_bytes(b"published")
    r = client.post("/api/media/generate", json={"confirm_spend": True, **body})
    assert r.status_code == 409 and "already published" in r.text
    assert [e for e in FakeFal.log if e[0] == "POST"] == []                                  # nothing was sent to fal
    r = client.post("/api/media/generate", json={"confirm_spend": True, "regenerate": True, **body})
    assert r.status_code == 202                                                              # an explicit regenerate goes through
    again = client.post("/api/media/generate", json={"confirm_spend": True, "regenerate": True, **body})
    assert again.status_code in {202, 409}                                                   # 409 while the first is still running, 202 once it has finished
    for job in r.json()["jobs"]:
        for _ in range(200):
            if client.get(f"/api/media/jobs/{job}").json()["state"] in {"done", "failed"}:
                break
            time.sleep(0.05)


# ---------------------------------------------------------------- decisions, the project connection and restart recovery

def make_project(client, folder):
    r = client.post("/api/projects", json={"title": "Site", "brief": "A site.", "working_dir": str(folder), "nodes": []})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def memory_texts(client, pid):
    return [m["text"] for m in client.get(f"/api/projects/{pid}").json()["memory"] if m["kind"] == "decision"]


def test_skip_restore_and_reject_are_recorded_with_the_slot_and_the_project_remembers_them(env):
    client, folder = env
    pid = make_project(client, folder)
    body = {"working_dir": str(folder), "slot": "hero-clip"}
    assert client.post("/api/media/decision", json={**body, "event": "skip", "note": "Not needed for launch"}).json() == {"slot": "hero-clip", "skipped": True}
    row = next(s for s in client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["slots"] if s["name"] == "hero-clip")
    assert row["skipped"] is True and row["history"][-1]["event"] == "skipped" and "Not needed" in row["history"][-1]["detail"]
    state = json.loads((folder / "media" / "decisions.json").read_text())["slots"]["hero-clip"]
    assert state["skipped"] is True
    assert any("Skipped media slot hero-clip: Not needed for launch" in t and "fallback" in t for t in memory_texts(client, pid))
    assert client.post("/api/media/decision", json={**body, "event": "unskip"}).json()["skipped"] is False
    assert client.post("/api/media/decision", json={**body, "event": "reject"}).status_code == 200
    events = [h["event"] for h in next(s for s in client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["slots"] if s["name"] == "hero-clip")["history"]]
    assert events == ["skipped", "restored", "rejected"]
    assert client.post("/api/media/decision", json={**body, "event": "bogus"}).status_code == 422


def test_a_published_slot_cannot_be_skipped_and_accept_and_publish_are_remembered(env):
    client, folder = env
    pid = make_project(client, folder)
    small_slots(folder)
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    client.post("/api/media/pick", json={"working_dir": str(folder), "slot": "hero-still", "candidate": "hero-still-1.png"})
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        assert client.post("/api/media/publish", json={"working_dir": str(folder), "slot": "hero-still"}).status_code == 200
        assert client.post("/api/media/decision", json={"working_dir": str(folder), "slot": "hero-still", "event": "skip"}).status_code == 409
        assert any("Published media slot hero-still" in t for t in memory_texts(client, pid))
    texts = memory_texts(client, pid)
    assert any("Accepted candidate hero-still-1.png for media slot hero-still" in t for t in texts)
    history = [h["event"] for h in json.loads((folder / "media" / "decisions.json").read_text())["slots"]["hero-still"]["history"]]
    assert history[0] == "regenerated" or history[0] == "generated"
    assert "accepted" in history


def test_the_slots_format_given_to_stories_describes_what_the_loader_accepts(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "ref.png").write_bytes(b"x")
    good = {"slots": [{"name": "heroine-reference", "kind": "image", "prompt": "a heroine", "batch": "reference", "refs": ["media/ref.png"] * 4,
                       "resolution": "2K", "purpose": "kept but ignored"},
                      {"name": "hero-clip", "kind": "video", "prompt": "a clip", "batch": "scenes", "from_still": "heroine-reference", "resolution": "480P"}]}
    (tmp_path / "media" / "slots.json").write_text(json.dumps(good))
    assert list(mg.load_slots(tmp_path)) == ["heroine-reference", "hero-clip"]
    for key in ('"name"', '"kind"', '"prompt"', '"refs"', 'at most 4', '"id" or "type" are not read', '1K, 2K or 4K', '480P, 768P or 1080P'):
        assert key in mg.SLOTS_FORMAT
    for bad in ({"id": "x", "type": "image", "prompt": "p"}, {"name": "x", "kind": "image", "prompt": "p", "refs": ["media/ref.png"] * 5}):
        (tmp_path / "media" / "slots.json").write_text(json.dumps({"slots": [bad]}))
        with pytest.raises(mg.MediaError):
            mg.load_slots(tmp_path)


def test_the_project_route_reports_where_media_stands_and_is_quiet_without_media(env, tmp_path):
    client, folder = env
    pid = make_project(client, folder)
    r = client.get(f"/api/media/project/{pid}").json()
    assert r["available"] is True and (r["summary"]["total"], r["summary"]["published"], r["summary"]["pending"]) == (3, 1, 2)      # hero-still is published by the fixture
    for name in ("hero-clip", "plate"):
        client.post("/api/media/decision", json={"working_dir": str(folder), "slot": name, "event": "skip"})
    r = client.get(f"/api/media/project/{pid}").json()["summary"]
    assert r["published"] == 1 and r["skipped"] == 2 and r["pending"] == 0 and r["complete"] is True      # hero-still is published by the fixture
    assert "slots published" in r["text"] and "Skipped: hero-clip, plate." in r["text"]
    other = tmp_path / "ws" / "plain"
    other.mkdir()
    pid2 = make_project(client, other)
    assert client.get(f"/api/media/project/{pid2}").json() == {"available": False}
    (other / "media").mkdir()                       # pilot story 17 wrote id/type: the studio must say why, not "no slots"
    (other / "media" / "slots.json").write_text(json.dumps({"slots": [{"id": "hero", "type": "image", "prompt": "p"}]}))
    rejected = client.get(f"/api/media/project/{pid2}").json()
    assert rejected["available"] is False and "unique lowercase name" in rejected["error"]
    assert client.get("/api/media/project/9999").status_code == 404
    import profiles
    profiles.bridge_token(get_settings(), True)
    assert bridge(client).get(f"/api/media/project/{pid}").status_code in {401, 403}


def test_a_submission_is_journaled_and_one_left_unfinished_by_a_restart_is_finished_later(env):
    client, folder = env
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    journal = [json.loads(line) for line in mg.journal_path(get_settings()).read_text().splitlines()]
    assert [j["state"] for j in journal][-2:] == ["submitted", "done"] and mg.journal_open(get_settings()) == []
    # simulate MCD stopping after fal accepted a job: a journal entry that never reached done
    me = get_settings().fal_queue_base
    owner = client.get("/api/profile").json()["owner"]
    mg.journal_add(get_settings(), {"id": "lost-1", "state": "submitted", "ts": int(time.time()), "folder": str(folder), "slot": "hero-still", "endpoint": "fal-ai/nano-banana-2/edit",
                                    "request_id": "req-lost", "status_url": me + "/status/1", "response_url": me + "/result/1", "owner": owner, "tier": "standard", "estimate_usd": 0.08})
    assert [e["id"] for e in mg.journal_open(get_settings())] == ["lost-1"]
    before = len(list((folder / "media" / "candidates").glob("hero-still-*.png")))
    mg.recover(get_settings(), client.app.state.sessions)
    for _ in range(300):
        if not mg.journal_open(get_settings()):
            break
        time.sleep(0.05)
    assert mg.journal_open(get_settings()) == []
    assert len(list((folder / "media" / "candidates").glob("hero-still-*.png"))) == before + 1          # the result was fetched and saved
    ledger = client.get("/api/media/ledger").json()["rows"]
    assert any(r.get("recovered") and r["status"] == "done" for r in ledger)
    assert any("finished after a restart" in h["detail"] for h in json.loads((folder / "media" / "decisions.json").read_text())["slots"]["hero-still"]["history"])


def test_a_journaled_job_that_cannot_be_resumed_is_marked_failed_not_retried(env):
    client, folder = env
    client.delete("/api/profile/credentials/fal")
    mg.journal_add(get_settings(), {"id": "lost-2", "state": "submitted", "ts": int(time.time()), "folder": str(folder), "slot": "hero-still", "endpoint": "e", "request_id": "r",
                                    "status_url": "https://evil.example.com/s", "response_url": "https://evil.example.com/r", "owner": "gptkiosk@gmail.com"})
    mg.recover(get_settings(), client.app.state.sessions)
    for _ in range(200):
        if not mg.journal_open(get_settings()):
            break
        time.sleep(0.05)
    assert mg.journal_open(get_settings()) == []
    assert [e for e in FakeFal.log if e[0] == "POST"] == []                                               # never resubmitted
    assert any(r.get("recovered") and r["status"] == "failed" for r in client.get("/api/media/ledger").json()["rows"])


def test_a_slot_with_generations_waiting_for_review_is_not_paid_for_again_unless_asked(env):
    client, folder = env
    first = run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    assert first.status_code == 202
    posts = len([e for e in FakeFal.log if e[0] == "POST"])
    again = client.post("/api/media/generate", json={"confirm_spend": True, "regenerate": True, "working_dir": str(folder), "slot": "hero-still"})
    assert again.status_code == 409 and "already been paid for" in again.text and "Another take" in again.text
    assert len([e for e in FakeFal.log if e[0] == "POST"]) == posts                            # nothing more was sent to fal
    take = run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still", "another_take": True})
    assert take.status_code == 202
    assert len([e for e in FakeFal.log if e[0] == "POST"]) == posts + 1
    client.post("/api/media/decision", json={"working_dir": str(folder), "slot": "hero-still", "event": "reject"})
    assert run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"}).status_code == 202      # a decision clears the wait


def test_the_ledger_counts_repeats_and_unpriced_runs_separately(env):
    client, folder = env
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still", "another_take": True})
    ledger = client.get("/api/media/ledger").json()
    assert ledger["done"] == 2 and ledger["repeats"] == 1 and ledger["repeat_usd"] == 0.12 and ledger["unpriced"] == 0


def test_a_transition_plate_uses_one_minimax_endpoint_with_a_start_and_an_end_still_and_asks_for_the_shortest_clip(env):
    client, folder = env
    run_and_wait(client, {"working_dir": str(folder), "slot": "plate", "tier": "standard"})
    post = [e for e in FakeFal.log if e[0] == "POST"][0]
    assert post[1] == "/minimax/h3-max/image-to-video"
    assert post[3]["image_url"].startswith("data:image/") and post[3]["end_image_url"].startswith("data:image/")
    assert post[3]["duration"] == 5.0                                  # the slot allows 4 to 6; one second over the minimum covers the loop fade
    ledger = client.get("/api/media/ledger").json()
    assert ledger["estimated_usd"] == 0.4 and ledger["unpriced"] == 0


def test_the_expensive_models_are_only_used_when_chosen():
    for slot in ({"kind": "video", "from_still": "a"}, {"kind": "video", "first_still": "a", "last_still": "b"}, {"kind": "video"}):
        for tier in ("draft", "standard"):
            assert mg.endpoint_for(slot, tier).startswith("minimax/"), (slot, tier)
        assert mg.endpoint_for(slot, "premium").startswith("fal-ai/veo3.1"), slot


def test_background_clips_start_on_the_cheapest_tier_for_a_website_and_standard_for_other_projects(env, tmp_path):
    client, folder = env
    assert client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["default_tiers"] == {"image": "standard", "video": "standard"}
    r = client.post("/api/projects", json={"title": "Site", "brief": "A site.", "working_dir": str(folder), "nodes": [], "project_type": "website-property"})
    assert r.status_code == 201, r.text
    assert client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["default_tiers"] == {"image": "standard", "video": "draft"}
    other = tmp_path / "ws" / "app"
    other.mkdir(parents=True)
    (other / "media").mkdir()
    (other / "media" / "slots.json").write_text((folder / "media" / "slots.json").read_text())
    r = client.post("/api/projects", json={"title": "App", "brief": "An app.", "working_dir": str(other), "nodes": [], "project_type": "web-app"})
    assert r.status_code == 201, r.text
    assert client.get("/api/media/slots", params={"working_dir": str(other)}).json()["default_tiers"]["video"] == "standard"


def test_a_slot_can_ask_for_less_resolution_than_its_tier_and_the_price_follows(env):
    client, folder = env
    slots = {"slots": [
        {"name": "small-still", "kind": "image", "prompt": "A marquee.", "width": 1024, "height": 576, "min_width": 900, "resolution": "1K"},
        {"name": "big-still", "kind": "image", "prompt": "A hero.", "width": 2560, "height": 1100},
        {"name": "vhs-clip", "kind": "video", "prompt": "VHS footage.", "seconds": [4, 6], "resolution": "480P", "from_still": "hero-still"},
        {"name": "full-clip", "kind": "video", "prompt": "Clean footage.", "seconds": [4, 6], "from_still": "hero-still"},
    ]}
    (folder / "media" / "slots.json").write_text(json.dumps(slots))
    data = client.get("/api/media/slots", params={"working_dir": str(folder)}).json()
    by = {s["name"]: s for s in data["slots"]}
    assert by["small-still"]["plans"]["standard"]["estimate_usd"] == 0.08            # 1K is the base price, not 2K's 0.12
    assert by["big-still"]["plans"]["standard"]["estimate_usd"] == 0.12
    assert by["vhs-clip"]["plans"]["standard"]["estimate_usd"] == 0.25               # 5 s of MiniMax H3 Max at 480p: 5 x 0.08 x 0.625
    assert by["full-clip"]["plans"]["standard"]["estimate_usd"] == 0.4
    assert by["vhs-clip"]["plans"]["draft"]["estimate_usd"] == 0.125                 # and Turbo at 480p is cheaper still
    FakeFal.log = []
    run_and_wait(client, {"working_dir": str(folder), "slot": "small-still"})
    assert [e for e in FakeFal.log if e[0] == "POST"][0][3]["resolution"] == "1K"    # what is sent is what was priced
    FakeFal.log = []
    run_and_wait(client, {"working_dir": str(folder), "slot": "vhs-clip"})
    assert [e for e in FakeFal.log if e[0] == "POST"][0][3]["resolution"] == "480P"


@pytest.mark.parametrize("kind,resolution", [("image", "480P"), ("video", "2K"), ("image", "8K"), ("video", "ultra")])
def test_a_resolution_that_does_not_fit_the_kind_of_slot_is_refused(env, kind, resolution):
    client, folder = env
    (folder / "media" / "slots.json").write_text(json.dumps({"slots": [{"name": "x", "kind": kind, "prompt": "p", "resolution": resolution}]}))
    r = client.get("/api/media/slots", params={"working_dir": str(folder)})
    assert r.status_code == 422 and "invalid resolution" in r.text


def test_the_project_route_says_what_media_has_cost_and_what_is_left_to_make(env):
    client, folder = env
    pid = make_project(client, folder)
    cost = client.get(f"/api/media/project/{pid}").json()["cost"]
    assert cost["remaining_items"] == 2 and cost["spent_usd"] == 0 and cost["spent_runs"] == 0      # hero-clip and plate are not made; hero-still is published
    assert cost["remaining_usd"] >= 0 and cost["unpriced"] in (0, 1, 2)
    for name in ("hero-clip", "plate"):
        client.post("/api/media/decision", json={"working_dir": str(folder), "slot": name, "event": "skip"})
    after = client.get(f"/api/media/project/{pid}").json()["cost"]
    assert after["remaining_items"] == 0 and after["remaining_usd"] == 0                              # skipped slots cost nothing
    slots_cost = client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["cost"]
    assert slots_cost == after


def test_a_published_slot_can_be_viewed_and_nothing_else_can(env):
    client, folder = env
    ok = client.get("/api/media/published", params={"working_dir": str(folder), "name": "hero-still"})
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg" and ok.content == (folder / "assets" / "img" / "hero-still.jpg").read_bytes()
    assert client.get("/api/media/published", params={"working_dir": str(folder), "name": "plate"}).status_code == 404            # not published
    for bad in ("../slots", "hero-still/../../x", "nope"):
        assert client.get("/api/media/published", params={"working_dir": str(folder), "name": bad}).status_code == 404
    assert client.get("/api/media/published", params={"working_dir": "/etc", "name": "hero-still"}).status_code == 422             # outside the allowed folders


def test_storage_is_reported_and_clearing_only_removes_takes_of_slots_you_have_decided(env):
    client, folder = env
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})        # a regenerated take for a slot that is already published
    run_and_wait(client, {"working_dir": str(folder), "slot": "plate"})             # a take still waiting for your decision
    data = client.get("/api/media/slots", params={"working_dir": str(folder)}).json()
    assert data["storage"]["unused_count"] == 0                                     # a regenerated published slot's take waits for review too
    assert next(s for s in data["slots"] if s["name"] == "hero-still")["unreviewed"] == 1
    client.post("/api/media/decision", json={"working_dir": str(folder), "slot": "hero-still", "event": "reject"})     # keep the published one
    data = client.get("/api/media/slots", params={"working_dir": str(folder)}).json()
    assert data["storage"]["published_bytes"] > 0 and data["storage"]["unused_count"] == 1 and data["storage"]["unused_bytes"] > 0
    assert next(s for s in data["slots"] if s["name"] == "hero-still")["published_bytes"] > 0
    body = {"working_dir": str(folder)}
    assert client.post("/api/media/clear-unused", json=body).status_code == 422                       # no confirmation, no deletion
    assert (folder / "media" / "candidates").exists() and any((folder / "media" / "candidates").glob("hero-still-*"))
    done = client.post("/api/media/clear-unused", json={**body, "confirm": True})
    assert done.status_code == 200 and done.json()["deleted"] == 1 and done.json()["freed_bytes"] > 0
    left = sorted(p.name for p in (folder / "media" / "candidates").iterdir())
    assert not any(n.startswith("hero-still-") for n in left)                                            # the decided slot's take and its note are gone
    assert any(n.startswith("plate-") for n in left)                                                     # the undecided slot's take is kept
    assert (folder / "assets" / "img" / "hero-still.jpg").is_file()                                      # published media is never touched
    assert client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["storage"]["unused_count"] == 0
    for name in ("hero-clip", "plate"):                                                                  # skipping decides a slot, so its take is then unused
        client.post("/api/media/decision", json={"working_dir": str(folder), "slot": name, "event": "skip"})
    assert client.get("/api/media/slots", params={"working_dir": str(folder)}).json()["storage"]["unused_count"] == 1


def test_a_published_slot_can_be_revised_and_regenerated_only_when_asked_and_keeps_its_file_until_a_take_is_accepted(env):
    """Pilot 2026-10-29: a published fantasy scene needed a stronger prompt, and the studio offered no way to change it or publish a new take."""
    client, folder = env
    def row():
        data = client.get("/api/media/slots", params={"working_dir": str(folder)}).json()
        return next(s for s in data["slots"] if s["name"] == "hero-still")
    edit = {"working_dir": str(folder), "slot": "hero-still", "prompt": "A barber shop interior, half turned to fantasy. No text."}
    assert client.patch("/api/media/slots", json={**edit, "expected_sha256": row()["plan_sha256"]}).status_code == 409          # published: not without saying so
    r = client.patch("/api/media/slots", json={**edit, "expected_sha256": row()["plan_sha256"], "revise_published": True})
    assert r.status_code == 200, r.text
    assert row()["prompt"].startswith("A barber shop interior, half turned") and row()["published"] is True
    before = (folder / "assets" / "img" / "hero-still.jpg").read_bytes()
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still", "expected_sha256": row()["plan_sha256"]})
    assert row()["unreviewed"] == 1 and (folder / "assets" / "img" / "hero-still.jpg").read_bytes() == before
    again = client.patch("/api/media/slots", json={**edit, "prompt": "x", "expected_sha256": row()["plan_sha256"], "revise_published": True})
    assert again.status_code == 409                                                    # a paid take is waiting: review it before changing the plan
    assert any(e[0] == "POST" and "half turned" in json.dumps(e[3]) for e in FakeFal.log)                     # the new take used the revised prompt


@needs_ffmpeg
def test_republishing_a_still_remakes_the_sites_width_named_copies(env):
    client, folder = env
    small_slots(folder)
    copies = folder / "assets" / "img" / "responsive"
    copies.mkdir()
    old = media_bytes("image")
    from PIL import Image
    for name in ("hero-still-480.webp", "hero-still-960.jpg"):
        Image.new("RGB", (640, 360)).save(copies / name)
    (copies / "hero-still-extra.webp").write_bytes(b"not a width copy")
    stamps = {p.name: p.read_bytes() for p in copies.iterdir()}
    run_and_wait(client, {"working_dir": str(folder), "slot": "hero-still"})
    client.post("/api/media/pick", json={"working_dir": str(folder), "slot": "hero-still", "candidate": "hero-still-1.png"})
    r = client.post("/api/media/publish", json={"working_dir": str(folder), "slot": "hero-still"})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["refreshed"]) == ["assets/img/responsive/hero-still-480.webp", "assets/img/responsive/hero-still-960.jpg"] and r.json()["stale"] == []
    assert (copies / "hero-still-480.webp").read_bytes() != stamps["hero-still-480.webp"] and (copies / "hero-still-960.jpg").read_bytes() != stamps["hero-still-960.jpg"]
    assert (copies / "hero-still-extra.webp").read_bytes() == stamps["hero-still-extra.webp"]          # only <name>-<width> copies are touched
    assert not list(copies.glob("*.refresh.*")) and old
    with Image.open(copies / "hero-still-480.webp") as made:
        assert made.width == 480
