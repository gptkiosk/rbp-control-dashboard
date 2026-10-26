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
CANDIDATE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm")
CANDIDATE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".mp4": "video/mp4", ".webm": "video/webm"}


def candidate_of(slot_name, filename):
    """True only for `<slot>-<number>.<media extension>`. A prefix match is not enough: `hero-light` must not claim `hero-light-still-1.png`."""
    m = re.fullmatch(re.escape(slot_name) + r"-(\d+)(\.[a-z0-9]+)", filename)
    return bool(m) and m.group(2) in CANDIDATE_SUFFIXES
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_SLOTS_FILE = 200_000
MAX_REF_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD = 150 * 1024 * 1024
FAL_HOSTS = ("fal.run", "fal.ai", "fal.media", "googleapis.com")
TIERS = ("draft", "standard", "premium")
IMAGE_TIERS = {"draft": ("fal-ai/nano-banana-2", "1K"), "standard": ("fal-ai/nano-banana-2", "2K"), "premium": ("fal-ai/nano-banana-pro", "2K")}
VEO = "fal-ai/veo3.1"
KLING25 = "fal-ai/kling-video/v2.5-turbo/pro"
IMAGE_RESOLUTIONS = ("1K", "2K", "4K")                  # a slot may ask for less than its tier (a small picture does not need 2K)
VIDEO_RESOLUTIONS = ("480P", "768P", "1080P")           # MiniMax: 480p costs 0.625 of 768p, and suits a VHS or retro look
MINIMAX = "minimax/h3-max"
MINIMAX_TURBO = "minimax/h3-max-turbo"
# draft and standard are MiniMax (a fifth to a half of what Veo billed on a real run); premium is the full Veo 3.1.
VIDEO_TIERS = {"draft": MINIMAX_TURBO, "standard": MINIMAX, "premium": VEO}


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


def candidate_file(root, name):
    """A candidate as a regular file directly inside media/candidates with a media extension, or None. A link (even one that stays inside the
    project) is refused, so a candidate can never be another file in disguise."""
    folder = root / "media" / "candidates"
    path = folder / name
    try:
        if path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve() or path.suffix not in CANDIDATE_TYPES or path.stat().st_size == 0:
            return None
    except OSError:
        return None
    return path


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
        if "batch" in item and (not isinstance(item["batch"], str) or item["batch"] not in {"reference", "scenes"}):
            raise MediaError(f"Slot {item['name']} has an invalid batch.")
        for key in ("refs",):
            if not isinstance(item.get(key, []), list) or len(item.get(key, [])) > 4 or not all(isinstance(r, str) and len(r) < 200 for r in item.get(key, [])):
                raise MediaError(f"Slot {item['name']} has invalid references.")
        if "resolution" in item and item["resolution"] not in (IMAGE_RESOLUTIONS if item["kind"] == "image" else VIDEO_RESOLUTIONS):
            allowed = " or ".join(IMAGE_RESOLUTIONS if item["kind"] == "image" else VIDEO_RESOLUTIONS)
            raise MediaError(f"Slot {item['name']} has an invalid resolution: use {allowed}.")
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
    if tier in {"draft", "standard"}:      # MiniMax takes a start still and an end still on the same image-to-video endpoint
        return VIDEO_TIERS[tier] + ("/text-to-video" if mode == "t2v" else "/image-to-video")
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


def minimax_seconds(slot):
    """The shortest clip the slot can use: its minimum plus one second for the loop fade, never above its maximum. MiniMax bills by the second, so length is cost."""
    lo, hi = (slot.get("seconds") or [4, 8])[:2]
    return float(min(max(lo + 1, 2), hi))


def build_request(root, slot, tier, model=None, aspect=None):
    """(endpoint, input body) for a slot. Reads the reference and still images from the folder."""
    if slot.get('batch') == 'scenes':
        slots = load_slots(root)
        references = [s for s in slots.values() if s.get('required',True) and s.get('batch')=='reference']
        if not references or any(s['kind'] != 'image' or not is_published(root,s) for s in references):
            raise MediaError('Publish the required character/style reference before generating scene artwork.',409)
        paths = {f"assets/img/{s['name']}.jpg" for s in references}
        if not paths <= set(slot.get('refs', [])):
            raise MediaError('Each scene must use the published reference paths in refs before generation.',409)
    endpoint = endpoint_for(slot, tier, model)
    if slot["kind"] == "image":
        aspect = aspect or aspect_for(slot)
        refs = [data_url(root, r) for r in slot.get("refs", [])]
        body = {"prompt": slot["prompt"], "aspect_ratio": aspect, "resolution": slot.get("resolution") or IMAGE_TIERS[tier][1], "output_format": "png", "num_images": 1}
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
    if endpoint.startswith("minimax/"):
        body = {"prompt": slot["prompt"], "duration": minimax_seconds(slot), "resolution": slot.get("resolution") or "768P", "prompt_expansion_mode": "balanced"}
        if mode == "t2v":
            body["aspect_ratio"] = "16:9"
        else:
            body["image_url"] = first or single
            if last:
                body["end_image_url"] = last
    elif "/kling-video/v3" in endpoint:
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
        if endpoint.startswith("minimax/"):
            body = {"duration": minimax_seconds(slot), "resolution": slot.get("resolution") or "768P"}
        else:
            body = {"duration": "5" if "/kling-video/" in endpoint else f"{min(max(round(hi), 4), 8) // 2 * 2}s"}
    else:
        body = {"num_images": 1, "resolution": slot.get("resolution") or IMAGE_TIERS[tier][1]}
    return {"endpoint": endpoint, "estimate_usd": estimate_for(s, endpoint, body)}


def estimate_for(s, endpoint, body):
    """A rough cost in USD for one generation, or None when the price is unknown. Display only; fal's invoice is the truth."""
    model = next((m for m in media_catalog.MODELS if m["id"] == endpoint), None)
    if model is None:
        return None
    rates = media_catalog.saved_rates(s)
    seconds = None
    if model["unit"] == "second":
        digits = re.match(r"(\d+(?:\.\d+)?)", str(body.get("duration", "")))
        seconds = float(digits.group(1)) if digits else None
        if seconds is None:
            return None
    return media_catalog.estimate(model, seconds=seconds, images=body.get("num_images", 1), rates=rates, resolution=body.get("resolution"))


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


def journal_path(settings):
    return Path(settings.data_dir) / "media" / "journal.jsonl"


def journal_add(settings, row):
    """An append-only record of every submitted generation, so one that was in flight when MCD restarted can be finished instead of lost."""
    path = journal_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def journal_open(settings):
    """Entries whose latest state is still `submitted`."""
    path = journal_path(settings)
    if not path.exists():
        return []
    latest = {}
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
            latest[row["id"]] = {**latest.get(row["id"], {}), **row}
        except (ValueError, KeyError):
            continue
    return [r for r in latest.values() if r.get("state") == "submitted"]


def submit_job(settings, key, endpoint, body):
    base = settings.fal_queue_base.rstrip("/")
    if not base_ok(base):
        raise MediaError("fal_queue_base must be https.", 500)
    job = call("POST", f"{base}/{endpoint}", key, body)
    for field in ("status_url", "response_url"):
        if not link_ok(str(job.get(field, "")), base):
            raise MediaError("fal returned an unexpected link; the key was not sent to it.", 502)
    return job


def finish_job(settings, key, root, slot, endpoint, job, progress=lambda text: None):
    """Wait for a submitted job, download the result and save it as a candidate. Raises MediaError on any failure, leaving no candidate."""
    base = settings.fal_queue_base.rstrip("/")
    for field in ("status_url", "response_url"):
        if not link_ok(str(job.get(field, "")), base):
            raise MediaError("The saved job has an unexpected link; the key was not sent to it.", 502)
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
    n = len([p for p in out.iterdir() if candidate_of(slot["name"], p.name) and p.suffix == ext]) + 1
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


def generate_once(settings, key, root, slot, endpoint, body, progress=lambda text: None, meta=None):
    """One submit, wait, download. Returns the candidate path, fal's request id and size. The submission is journaled first, so a restart can finish it."""
    job = submit_job(settings, key, endpoint, body)
    journal_add(settings, {"id": (meta or {}).get("id") or job.get("request_id"), "state": "submitted", "ts": int(time.time()), "folder": str(root), "slot": slot["name"], "endpoint": endpoint,
                           "request_id": job.get("request_id"), "status_url": job.get("status_url"), "response_url": job.get("response_url"),
                           "owner": (meta or {}).get("owner"), "tier": (meta or {}).get("tier"), "estimate_usd": (meta or {}).get("estimate_usd")})
    return finish_job(settings, key, root, slot, endpoint, job, progress)


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
        record = {"id": job_id, "state": "queued", "progress": "", "slot": slot["name"], "folder": str(root), "endpoint": endpoint, "estimate_usd": estimate, "files": [], "error": None}
        with self.lock:
            self.items[job_id] = record
            if len(self.items) > 100:
                for old in sorted(self.items, key=lambda k: self.items[k].get("t", 0))[:20]:
                    self.items.pop(old, None)
        record["t"] = time.time()

        def run():
            record["state"] = "running"
            ledger = {"ts": int(time.time()), "slot": slot["name"], "folder": str(root), "endpoint": endpoint, "estimate_usd": estimate, "owner": meta.get("owner"), "tier": meta.get("tier")}
            import media_state
            try:
                target, request_id, size = generate_once(settings, key, root, slot, endpoint, body, lambda text: record.__setitem__("progress", text),
                                                         {"id": job_id, "owner": meta.get("owner"), "tier": meta.get("tier"), "estimate_usd": estimate})
                record.update(state="done", files=[{"path": str(target.relative_to(root)), "bytes": size}], progress="done")
                self.ledger.add({**ledger, "status": "done", "request_id": request_id, "file": str(target.relative_to(root))})
                journal_add(settings, {"id": job_id, "state": "done", "ts": int(time.time())})
                media_state.record(root, slot["name"], "regenerated" if meta.get("regenerate") else "generated", f"{target.name} ({endpoint}, {meta.get('tier')} tier)", meta.get("owner") or "")
            except MediaError as exc:
                record.update(state="failed", error=str(exc).replace(key, "[key]"))
                self.ledger.add({**ledger, "status": "failed", "error": record["error"][:200]})
                journal_add(settings, {"id": job_id, "state": "failed", "ts": int(time.time()), "error": record["error"][:200]})
                media_state.record(root, slot["name"], "generate_failed", record["error"][:300], meta.get("owner") or "")
            except Exception:       # never let a worker die silently or echo internals
                record.update(state="failed", error="Generation failed unexpectedly.")
                self.ledger.add({**ledger, "status": "failed", "error": "unexpected"})
                journal_add(settings, {"id": job_id, "state": "failed", "ts": int(time.time()), "error": "unexpected"})

        self.pool.submit(run)
        return job_id

    def active_for(self, folder, slot_name):
        """True while a generation for this slot in this folder is queued or running."""
        with self.lock:
            return any(r.get("folder") == str(folder) and r["slot"] == slot_name and r["state"] in {"queued", "running"} for r in self.items.values())

    def get(self, job_id):
        with self.lock:
            record = self.items.get(job_id)
        return {k: v for k, v in record.items() if k not in {"t", "folder"}} if record else None


_state = {}


def runtime(settings):
    """The jobs and ledger for this installation's data directory."""
    key = str(settings.data_dir)
    if key not in _state:
        ledger = Ledger(Path(settings.data_dir) / "media" / "ledger.jsonl")
        _state[key] = Jobs(ledger)
    return _state[key]


# ---------------------------------------------------------------- publishing a picked candidate (MCD's own code; the folder's scripts are never run)

CLIP_MAX_BYTES = 4 * 1024 * 1024
ATTEMPTS = [(30, 1920), (34, 1920), (36, 1600), (38, 1280), (42, 1280)]      # (crf, max width), tried until the clip fits the size limit
INVENTORY_BEGIN, INVENTORY_END = "<!-- media:begin -->", "<!-- media:end -->"
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_SUFFIXES_IN = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".heic"}


def is_published(root, slot):
    folder = "video" if slot["kind"] == "video" else "img"
    path = inside(root, f"assets/{folder}/{slot['name']}." + ("mp4" if slot["kind"] == "video" else "jpg"))
    return path is not None and path.stat().st_size > 0


def inbox_file(root, slot):
    """The one file waiting in media/inbox for a slot (a regular file named `<slot>.<ext>`), or None."""
    folder = root / "media" / "inbox"
    allowed = VIDEO_SUFFIXES if slot["kind"] == "video" else IMAGE_SUFFIXES_IN
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob(slot["name"] + ".*")):
        try:
            if path.suffix.lower() in allowed and not path.is_symlink() and path.is_file() and path.stat().st_size > 0 and path.resolve().parent == folder.resolve():
                return path
        except OSError:
            continue
    return None


def _run(cmd):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MediaError(f"{cmd[0]} could not run: {exc}", 500) from None
    if done.returncode:
        lines = done.stderr.strip().splitlines()
        raise MediaError(f"{cmd[0]} failed: {lines[-1] if lines else done.returncode}", 422)
    return done.stdout


def _probe(path):
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        raise MediaError("ffmpeg and ffprobe must be installed on this machine to publish media (brew install ffmpeg).", 500)
    try:
        data = json.loads(_run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]))
    except ValueError:
        raise MediaError(f"{path.name} is not a readable media file.", 422) from None
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video or not video.get("width"):
        raise MediaError(f"{path.name} has no picture.", 422)
    return {"w": int(video["width"]), "seconds": float(data.get("format", {}).get("duration") or video.get("duration") or 0)}


def _fit_image(src, slot, out_dir):
    target = out_dir / f"{slot['name']}{'.png' if slot.get('transparent') else '.jpg'}"
    width = int(slot.get("width", 1920))
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"scale='min({width},iw)':-2:flags=lanczos", "-frames:v", "1"]
         + ([] if slot.get("transparent") else ["-q:v", "3"]) + [str(target)])
    return [target]


def _fit_video(src, slot, info, out_dir, fade=0.6):
    lo, hi = slot.get("seconds", [4, 8])
    fade = min(fade, info["seconds"] / 4) if fade else 0
    if info["seconds"] < lo + fade:
        raise MediaError(f"{src.name} is {info['seconds']:.1f}s, too short for a {lo} to {hi}s clip.", 422)
    looped = fade and slot.get("loop", True)
    if looped:
        d, f = info["seconds"], fade
        graph = (f"[0:v]fps=24,split=3[v1][v2][v3];[v1]trim=start={f}:end={d - f},setpts=PTS-STARTPTS[body];[v2]trim=start={d - f}:end={d},setpts=PTS-STARTPTS[tail];"
                 f"[v3]trim=start=0:end={f},setpts=PTS-STARTPTS[head];[tail][head]xfade=transition=fade:duration={f}:offset=0[x];[body][x]concat=n=2:v=1:a=0[o]")
    produced = []
    for fmt, codec in (("webm", ["-c:v", "libvpx-vp9", "-b:v", "0", "-row-mt", "1"]), ("mp4", ["-c:v", "libx264", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart"])):
        target = out_dir / f"{slot['name']}.{fmt}"
        for crf, width in ATTEMPTS:
            scale = f"scale='min({width},iw)':-2:flags=lanczos"
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
            cmd += ["-filter_complex", graph + f";[o]{scale}[out]", "-map", "[out]"] if looped else ["-vf", f"fps=24,{scale}"]
            _run(cmd + codec + ["-crf", str(crf), "-an", str(target)])
            if target.stat().st_size <= CLIP_MAX_BYTES:
                break
        else:
            raise MediaError(f"{slot['name']}.{fmt} is still over 4 MB at the lowest quality; make a shorter or simpler clip.", 422)
        produced.append(target)
    poster = out_dir / f"{slot['name']}.jpg"
    _run(["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(produced[1]), "-frames:v", "1", "-q:v", "3", str(poster)])
    return produced + [poster]


def _write_inventory(root, provenance):
    rows = ["| Slot | Kind | File | Tool | Model | Terms | AI-generated | Date | Prompt |", "|---|---|---|---|---|---|---|---|---|"]
    for _, p in sorted(provenance.items()):
        rows.append("| " + " | ".join(str(p.get(k, "")).replace("|", "/").replace("\n", " ") for k in ("slot", "kind", "files", "tool", "model", "terms", "ai_generated", "date", "prompt")) + " |")
    block = f"{INVENTORY_BEGIN}\nGenerated media (written by MCD or tools/media/media.py; edit media/provenance.json, not this table).\n\n" + "\n".join(rows) + f"\n{INVENTORY_END}\n"
    path = root / "assets" / "ART-INVENTORY.md"
    text = path.read_text() if path.exists() else "# Art and media inventory\n\nEvery asset, its source and its license.\n\n"
    if INVENTORY_BEGIN in text and INVENTORY_END in text:
        text = text[:text.index(INVENTORY_BEGIN)] + block + text[text.index(INVENTORY_END) + len(INVENTORY_END) + 1:]
    else:
        text = text.rstrip("\n") + "\n\n" + block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def publish(root, slot, loop_fade=0.6):
    """Validate, convert and record the file waiting in media/inbox for a slot, exactly as `tools/media/media.py ingest` does. Returns the files made."""
    import datetime
    import hashlib
    src = inbox_file(root, slot)
    if src is None:
        raise MediaError("Nothing is waiting in the inbox for this slot. Use one of its candidates first.", 404)
    side = src.with_suffix(".json")
    try:
        meta = json.loads(side.read_text()) if side.is_file() and not side.is_symlink() else {}
    except (OSError, ValueError):
        meta = {}
    meta = meta if isinstance(meta, dict) else {}
    tool = str(meta.get("tool") or "").strip()
    if not tool:
        raise MediaError("The picked file has no record of the tool that made it; the inventory records every generated asset. Generate it again or ingest it by hand with --tool.", 422)
    info = _probe(src)
    min_w = int(slot.get("min_width", 960))
    if info["w"] < min_w:
        raise MediaError(f"{src.name} is {info['w']}px wide and this slot needs at least {min_w}px (a draft is too small to publish; generate it at standard or premium).", 422)
    out_dir = root / "assets" / ("video" if slot["kind"] == "video" else "img")
    out_dir.mkdir(parents=True, exist_ok=True)
    files = _fit_video(src, slot, info, out_dir, loop_fade) if slot["kind"] == "video" else _fit_image(src, slot, out_dir)
    pfile = root / "media" / "provenance.json"
    try:
        provenance = json.loads(pfile.read_text()) if pfile.is_file() else {}
    except (OSError, ValueError):
        provenance = {}
    provenance[slot["name"]] = {"slot": slot["name"], "kind": slot["kind"], "files": ", ".join(str(f.relative_to(root)) for f in files), "tool": tool,
                                "model": str(meta.get("model") or ""), "terms": str(meta.get("terms") or "see tool terms"), "ai_generated": True,
                                "date": datetime.date.today().isoformat(), "prompt": str(meta.get("prompt") or slot["prompt"]),
                                "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest()}
    pfile.parent.mkdir(parents=True, exist_ok=True)
    pfile.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    _write_inventory(root, provenance)
    return [{"path": str(f.relative_to(root)), "bytes": f.stat().st_size} for f in files]


def recover(settings, sessions):
    """Finish generations that were submitted to fal but not finished when MCD last stopped. Runs in the background at start-up; a job it cannot
    resume (no key, folder gone, fal no longer knows it) is marked failed in the journal and the ledger, never retried or resubmitted."""
    import media_state
    import profiles
    runtime_ = runtime(settings)
    for entry in journal_open(settings):
        def resume(entry=entry):
            ledger = {"ts": int(time.time()), "slot": entry.get("slot"), "folder": entry.get("folder"), "endpoint": entry.get("endpoint"), "estimate_usd": entry.get("estimate_usd"),
                      "owner": entry.get("owner"), "tier": entry.get("tier"), "recovered": True}
            try:
                with sessions() as s:
                    key = profiles.credential(s, entry.get("owner") or "operator", "fal", settings)
                if not key:
                    raise MediaError("No saved fal key to resume this generation with.", 422)
                root = project_root(settings, entry["folder"])
                slot = load_slots(root)[entry["slot"]]
                target, request_id, size = finish_job(settings, key, root, slot, entry["endpoint"], entry)
                runtime_.ledger.add({**ledger, "status": "done", "request_id": request_id, "file": str(target.relative_to(root))})
                journal_add(settings, {"id": entry["id"], "state": "done", "ts": int(time.time())})
                media_state.record(root, slot["name"], "generated", f"{target.name} (finished after a restart)", entry.get("owner") or "")
            except Exception as exc:
                message = str(exc)[:200] if isinstance(exc, MediaError) else "could not be resumed"
                runtime_.ledger.add({**ledger, "status": "failed", "error": message})
                journal_add(settings, {"id": entry["id"], "state": "failed", "ts": int(time.time()), "error": message})
        runtime_.pool.submit(resume)


_PLAN_LOCKS = {}
_PLAN_LOCKS_GUARD = threading.Lock()

def plan_lock(root):
    """Serialize operator slot edits and generation admission on this dashboard process."""
    with _PLAN_LOCKS_GUARD:
        return _PLAN_LOCKS.setdefault(str(root), threading.RLock())
