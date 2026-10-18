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
    r = client.post("/api/media/generate", json={"confirm_spend": True, **body})
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
    assert by["hero-still"]["plans"]["standard"]["estimate_usd"] == 0.08
    assert by["hero-clip"]["plans"]["draft"]["estimate_usd"] == 0.35               # 5 s at $0.07
    assert by["hero-clip"]["plans"]["standard"]["estimate_usd"] is None             # Veo is not listed: never invented
    assert by["plate"]["plans"]["standard"]["endpoint"] == "fal-ai/veo3.1/first-last-frame-to-video"
    assert by["hero-clip"]["waiting_for_stills"] == []


def test_a_clip_run_calls_fal_with_the_saved_key_and_saves_a_candidate(env):
    client, folder = env
    r = run_and_wait(client, {"working_dir": str(folder), "slot": "hero-clip", "tier": "draft"})
    posts = [e for e in FakeFal.log if e[0] == "POST"]
    assert posts[0][1] == "/fal-ai/kling-video/v2.5-turbo/pro/image-to-video"
    assert posts[0][2] == "Key " + FAL
    assert posts[0][3]["image_url"].startswith("data:image/")
    downloads = [e for e in FakeFal.log if e[1].startswith("/files/")]
    assert downloads and all(e[2] is None for e in downloads)                       # no key on the download
    assert r.json()["estimate_usd_each"] == 0.35
    assert (folder / "media" / "candidates" / "hero-clip-1.mp4").stat().st_size > 0
    side = json.loads((folder / "media" / "candidates" / "hero-clip-1.json").read_text())
    assert side["model"] == "fal-ai/kling-video/v2.5-turbo/pro/image-to-video" and side["tool"].startswith("fal")
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
    assert ledger["done"] == 2 and ledger["estimated_usd"] == 0.16
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
    run_and_wait(client, {"working_dir": str(folder), "slot": "card-x", "aspect": "4:5"})
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
