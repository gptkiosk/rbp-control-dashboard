"""MCD-run media generation through fal.ai with the operator's saved key.

The key never leaves this process: it is read from the encrypted profile, sent only to fal hosts, and never written to a response, a log, a ledger or a
file. The project folder is treated as DATA: `media/slots.json` supplies prompts and file names, but no code from the folder is ever run here (agents
can edit that folder, so running its scripts with the key would let a changed script read it). Results land as candidates in
`<folder>/media/candidates/`; choosing one and running the project's own `ingest` needs no key.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import approval
import media_catalog

SLOT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_SLOTS_FILE = 200_000
MAX_REF_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD = 150 * 1024 * 1024
FAL_HOSTS = ("fal.run", "fal.ai", "fal.media", "googleapis.com")
TIERS = ("draft", "standard", "premium")
IMAGE_TIERS = {"draft": ("fal-ai/nano-banana-2", "1K"), "standard": ("fal-ai/nano-banana-2", "2K"), "premium": ("fal-ai/nano-banana-pro", "2K")}
VEO = "fal-ai/veo3.1"
KLING25 = "fal-ai/kling-video/v2.5-turbo/pro"
VIDEO_TIERS = {"draft": KLING25, "standard": VEO + "/fast", "premium": VEO}


class MediaError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- the project folder, as data

def project_root(settings, working_dir):
    root = approval.resolve_workdir(working_dir, settings.workdir_roots)
    if root is None:
        raise MediaError("That folder is not inside an allowed working directory.")
    return root


def inside(root, rel):
    """A file inside the folder, never a path that escapes it (symlinks and .. included)."""
    try:
        path = (root / rel).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return path if path.is_file() and (root in path.parents) else None


def load_slots(root):
    path = inside(root, "media/slots.json")
    if path is None:
        raise MediaError("This folder has no media/slots.json, so there are no media slots to generate.")
    if path.stat().st_size > MAX_SLOTS_FILE:
        raise MediaError("media/slots.json is too large.")
    try:
        raw = json.loads(path.read_text())["slots"]
    except (ValueError, KeyError, TypeError):
        raise MediaError("media/slots.json is not valid.") from None
    if not isinstance(raw, list) or len(raw) > 50:
        raise MediaError("media/slots.json must list at most 50 slots.")
    slots = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not SLOT_RE.fullmatch(item["name"]) or item["name"] in slots:
            raise MediaError("Every slot needs a unique lowercase name.")
        if item.get("kind") not in {"image", "video"} or not isinstance(item.get("prompt"), str) or not 1 <= len(item["prompt"]) <= 4000:
            raise MediaError(f"Slot {item['name']} needs a kind of image or video and a prompt.")
        for key in ("refs",):
            if not isinstance(item.get(key, []), list) or len(item.get(key, [])) > 4 or not all(isinstance(r, str) and len(r) < 200 for r in item.get(key, [])):
                raise MediaError(f"Slot {item['name']} has invalid references.")
        for key in ("from_still", "first_still", "last_still"):
            if key in item and not (isinstance(item[key], str) and SLOT_RE.fullmatch(item[key])):
                raise MediaError(f"Slot {item['name']} has an invalid {key}.")
        slots[item["name"]] = item
    return slots


def data_url(root, rel):
    """A reference or approved still as a JPEG data URL (re-encoded when ffmpeg exists, so any format and size is accepted)."""
    path = inside(root, rel)
    if path is None or path.stat().st_size == 0 or path.stat().st_size > MAX_REF_BYTES:
        raise MediaError(f"Reference image {rel} is missing, empty or over 8 MB.")
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise MediaError(f"Reference {rel} is not an image.")
    if shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ref.jpg"
            run = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf", "scale='min(1536,iw)':-2", "-frames:v", "1", "-q:v", "3", str(out)],
                                 capture_output=True, text=True, timeout=60)
            if run.returncode == 0 and out.exists():
                return "data:image/jpeg;base64," + base64.b64encode(out.read_bytes()).decode()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/webp" if path.suffix.lower() == ".webp" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def still_url(root, name):
    rel = f"assets/img/{name}.jpg"
    if inside(root, rel) is None:
        raise MediaError(f"The approved still '{name}' is not published yet: generate it, pick one, then ingest it first.")
    return data_url(root, rel)


# ---------------------------------------------------------------- what to ask fal for

def video_endpoint(tier, mode):
    if tier == "draft":
        return KLING25 + ("/text-to-video" if mode == "t2v" else "/image-to-video")
    if mode == "flf":
        return VEO + "/first-last-frame-to-video"
    if mode == "i2v":
        return VIDEO_TIERS[tier] + "/image-to-video"
    return VIDEO_TIERS[tier]


def endpoint_for(slot, tier, model=None):
    """The endpoint a slot would use, without reading any file. `model` must be a catalog model."""
    if model:
        if model not in {m["id"] for m in media_catalog.MODELS}:
            raise MediaError("Choose a model from the media catalog.")
        return model
    if slot["kind"] == "image":
        family = IMAGE_TIERS[tier][0]
        return family + ("/edit" if slot.get("refs") else "")
    mode = "flf" if slot.get("first_still") and slot.get("last_still") else "i2v" if slot.get("from_still") else "t2v"
    return video_endpoint(tier, mode)


ASPECTS = {"21:9": 21 / 9, "16:9": 16 / 9, "3:2": 3 / 2, "4:3": 4 / 3, "5:4": 5 / 4, "1:1": 1.0, "4:5": 4 / 5, "3:4": 3 / 4, "2:3": 2 / 3, "9:16": 9 / 16}


def aspect_for(slot):
    """The supported aspect ratio closest to the slot's own width and height, so a square card is made square and a wide hero is made wide."""
    try:
        w, h = float(slot.get("width") or 1920), float(slot.get("height") or 1080)
        ratio = w / h if w > 0 and h > 0 else 16 / 9
    except (TypeError, ValueError):
        ratio = 16 / 9
    return min(ASPECTS, key=lambda name: abs(ASPECTS[name] - ratio) / ratio)


def build_request(root, slot, tier, model=None, aspect=None):
    """(endpoint, input body) for a slot. Reads the reference and still images from the folder."""
    endpoint = endpoint_for(slot, tier, model)
    if slot["kind"] == "image":
        aspect = aspect or aspect_for(slot)
        refs = [data_url(root, r) for r in slot.get("refs", [])]
        body = {"prompt": slot["prompt"], "aspect_ratio": aspect, "resolution": IMAGE_TIERS[tier][1], "output_format": "png", "num_images": 1}
        if refs:
            body["image_urls"] = refs
        return endpoint, body
    first = last = single = None
    if slot.get("first_still") and slot.get("last_still"):
        first, last = still_url(root, slot["first_still"]), still_url(root, slot["last_still"])
    elif slot.get("from_still"):
        single = still_url(root, slot["from_still"])
    mode = "flf" if first else "i2v" if single else "t2v"
    hi = (slot.get("seconds") or [4, 8])[-1]
    if "/kling-video/v3" in endpoint:
        body = {"prompt": slot["prompt"], "duration": "5", "generate_audio": False}
        if mode == "t2v":
            body["aspect_ratio"] = "16:9"
        else:
            body["start_image_url"] = first or single
            if last:
                body["end_image_url"] = last
    elif "/kling-video/" in endpoint:
        body = {"prompt": slot["prompt"], "duration": "5"}
        if mode == "t2v":
            body["aspect_ratio"] = "16:9"
        else:
            body["image_url"] = first or single
            if last:
                body["tail_image_url"] = last
    else:
        body = {"prompt": slot["prompt"], "aspect_ratio": "16:9", "duration": f"{min(max(round(hi), 4), 8) // 2 * 2}s", "resolution": "1080p", "generate_audio": False}
        if mode == "flf":
            body["first_frame_url"], body["last_frame_url"] = first, last
        elif mode == "i2v":
            body["image_url"] = single
            body["auto_fix"] = False
    return endpoint, body


def quick_plan(s, slot, tier, model=None):
    """Endpoint and a price estimate for a slot at a tier without reading any file (for showing choices before anything is spent)."""
    endpoint = endpoint_for(slot, tier, model)
    if slot["kind"] == "video":
        hi = (slot.get("seconds") or [4, 8])[-1]
        body = {"duration": "5" if "/kling-video/" in endpoint else f"{min(max(round(hi), 4), 8) // 2 * 2}s"}
    else:
        body = {"num_images": 1}
    return {"endpoint": endpoint, "estimate_usd": estimate_for(s, endpoint, body)}


def estimate_for(s, endpoint, body):
    """A rough cost in USD for one generation, or None when the price is unknown. Display only; fal's invoice is the truth."""
    model = next((m for m in media_catalog.MODELS if m["id"] == endpoint), None)
    if model is None:
        return None
    rates = media_catalog.saved_rates(s)
    seconds = None
    if model["unit"] == "second":
        digits = re.match(r"(\d+)", str(body.get("duration", "")))
        seconds = int(digits.group(1)) if digits else None
        if seconds is None:
            return None
    return media_catalog.estimate(model, seconds=seconds, images=body.get("num_images", 1), rates=rates)


# ---------------------------------------------------------------- talking to fal

def base_ok(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" or parsed.hostname in {"127.0.0.1", "localhost"}


def link_ok(url, base):
    u, b = urllib.parse.urlparse(url), urllib.parse.urlparse(base)
    if u.scheme not in {"https", "http"} or not u.hostname:
        return False
    return u.netloc == b.netloc or (u.scheme == "https" and any(u.hostname == h or u.hostname.endswith("." + h) for h in FAL_HOSTS))


def call(method, url, key, body=None, scrub=()):
    headers = {"Content-Type": "application/json", "Authorization": "Key " + key}
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise MediaError(f"fal answered {exc.code}: " + exc.read().decode(errors="replace")[:300].replace(key, "[key]"), 502) from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise MediaError("Could not reach fal: " + str(exc).replace(key, "[key]"), 502) from None


def price_of(settings, key, endpoint):
    try:
        reply = call("GET", f"{settings.fal_api_base.rstrip('/')}/models/pricing?endpoint_id={urllib.parse.quote(endpoint, safe='/')}", key)
        row = (reply.get("prices") or [{}])[0]
        return {"unit_price": row["unit_price"], "unit": row["unit"], "currency": row.get("currency", "USD")} if "unit_price" in row else None
    except (MediaError, KeyError, IndexError):
        return None


def generate_once(settings, key, root, slot, endpoint, body, progress=lambda text: None):
    """One submit, wait, download. Returns the candidate path and fal's request id. Raises MediaError on any failure, leaving no candidate."""
    base = settings.fal_queue_base.rstrip("/")
    if not base_ok(base):
        raise MediaError("fal_queue_base must be https.", 500)
    job = call("POST", f"{base}/{endpoint}", key, body)
    for field in ("status_url", "response_url"):
        if not link_ok(str(job.get(field, "")), base):
            raise MediaError("fal returned an unexpected link; the key was not sent to it.", 502)
    request_id = job.get("request_id")
    progress("queued at fal")
    waited = 0.0
    while True:
        status = call("GET", job["status_url"], key)
        if status.get("status") == "COMPLETED":
            break
        progress(str(status.get("status", "working")).lower().replace("_", " "))
        waited += max(settings.fal_poll_s, 0.0)
        if waited > 1500:
            raise MediaError(f"Gave up after 25 minutes; request {request_id} may still finish in your fal dashboard.", 504)
        time.sleep(settings.fal_poll_s)
    if status.get("error"):
        raise MediaError(f"fal reported an error: {status.get('error')} ({status.get('error_type', '')})".replace(key, "[key]"), 502)
    result = call("GET", job["response_url"], key)
    if slot["kind"] == "video":
        url, ext = (result.get("video") or {}).get("url"), ".mp4"
    else:
        url, ext = ((result.get("images") or [{}])[0]).get("url"), ".png"
    if not url or not link_ok(str(url), base):
        raise MediaError("The result had no usable file link.", 502)
    progress("downloading")
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=300) as response:     # no key on the download
            data = response.read(MAX_DOWNLOAD + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MediaError(f"Could not download the result: {exc}", 502) from None
    if not data or len(data) > MAX_DOWNLOAD:
        raise MediaError("The downloaded file was empty or too large.", 502)
    out = root / "media" / "candidates"
    out.mkdir(parents=True, exist_ok=True)
    n = len(list(out.glob(slot["name"] + "-*" + ext))) + 1
    target = out / f"{slot['name']}-{n}{ext}"
    target.write_bytes(data)
    if shutil.which("ffprobe"):
        check = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(target)], capture_output=True, text=True, timeout=60)
        if check.returncode != 0:
            target.unlink()
            raise MediaError("The downloaded file is not a readable image or video, so it was discarded.", 502)
    target.with_suffix(".json").write_text(json.dumps({"tool": "fal (run by MCD)", "model": endpoint, "terms": "Generated with the operator's own fal account; see fal and model-provider terms",
                                                       "prompt": slot["prompt"]}, indent=2))
    return target, request_id, len(data)


# ---------------------------------------------------------------- jobs and the spend ledger

class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def add(self, row):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    def rows(self, limit=200):
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines()[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


class Jobs:
    """Generation runs in the background; a restart of MCD loses a job in flight, but its fal request id is in the ledger."""

    def __init__(self, ledger):
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.items = {}
        self.lock = threading.Lock()
        self.ledger = ledger

    def submit(self, settings, key, root, slot, endpoint, body, estimate, meta):
        job_id = uuid.uuid4().hex[:12]
        record = {"id": job_id, "state": "queued", "progress": "", "slot": slot["name"], "endpoint": endpoint, "estimate_usd": estimate, "files": [], "error": None}
        with self.lock:
            self.items[job_id] = record
            if len(self.items) > 100:
                for old in sorted(self.items, key=lambda k: self.items[k].get("t", 0))[:20]:
                    self.items.pop(old, None)
        record["t"] = time.time()

        def run():
            record["state"] = "running"
            ledger = {"ts": int(time.time()), "slot": slot["name"], "folder": str(root), "endpoint": endpoint, "estimate_usd": estimate, "owner": meta.get("owner"), "tier": meta.get("tier")}
            try:
                target, request_id, size = generate_once(settings, key, root, slot, endpoint, body, lambda text: record.__setitem__("progress", text))
                record.update(state="done", files=[{"path": str(target.relative_to(root)), "bytes": size}], progress="done")
                self.ledger.add({**ledger, "status": "done", "request_id": request_id, "file": str(target.relative_to(root))})
            except MediaError as exc:
                record.update(state="failed", error=str(exc).replace(key, "[key]"))
                self.ledger.add({**ledger, "status": "failed", "error": record["error"][:200]})
            except Exception:       # never let a worker die silently or echo internals
                record.update(state="failed", error="Generation failed unexpectedly.")
                self.ledger.add({**ledger, "status": "failed", "error": "unexpected"})

        self.pool.submit(run)
        return job_id

    def get(self, job_id):
        with self.lock:
            record = self.items.get(job_id)
        return {k: v for k, v in record.items() if k != "t"} if record else None


_state = {}


def runtime(settings):
    """The jobs and ledger for this installation's data directory."""
    key = str(settings.data_dir)
    if key not in _state:
        ledger = Ledger(Path(settings.data_dir) / "media" / "ledger.jsonl")
        _state[key] = Jobs(ledger)
    return _state[key]
