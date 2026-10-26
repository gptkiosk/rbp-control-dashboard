"""Model profiles: what each model can do, how it has actually done here, and what people have noted about it. The three kinds are kept apart.

* **Facts** come from sources: the price catalog (foundation and free models the app knows) and a dated snapshot of OpenRouter's public model
  list, which an operator refreshes on demand. Facts are context size, tool use, structured output, reasoning, modalities and price.
* **Observed** is computed from the telemetry the app already keeps (nothing new is stored). A model with fewer than ``PROVEN_RUNS`` runs on a
  kind of work is *unproven* for that kind, and the coordinator is told so.
* **Notes** are short text by people, each with a source and a date. They are shown as stale after ``STALE_DAYS``.

Dated vendor guidance supplies a routing class and specialty, separately labelled as app heuristics rather than benchmark scores. Refreshing never edits the price catalog or any route; it only shows what changed.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

import billing
import model_selection
import model_evidence
import telemetry

PROVEN_RUNS = 10
STALE_DAYS = 90
LIST_URL = "https://openrouter.ai/api/v1/models"
MAX_BYTES = 6 * 1024 * 1024
MAX_MODELS = 1500
MAX_NOTES = 200
NOTE_TEXT_MAX = 400
SNAPSHOT = "openrouter.json"
NOTES = "notes.json"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,119}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ModelError(ValueError):
    pass


def _norm(model: str | None) -> str:
    return (model or "").strip().removeprefix("openrouter/")


def _folder(data_dir) -> Path:
    return Path(data_dir) / "models"


def _clean(text, limit) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or "")).strip()[:limit]


def _read_json(path: Path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=1, sort_keys=True), "utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


# ------------------------------------------------------------------------------------------------ the OpenRouter snapshot
def _entry(raw: dict) -> dict | None:
    """The few fields kept from one entry of OpenRouter's list. Text from the list is length-capped and stripped of control characters."""
    mid = raw.get("id")
    if not isinstance(mid, str) or not ID_RE.match(mid):
        return None
    pricing = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else {}
    arch = raw.get("architecture") if isinstance(raw.get("architecture"), dict) else {}
    params = raw.get("supported_parameters") if isinstance(raw.get("supported_parameters"), list) else []
    top = raw.get("top_provider") if isinstance(raw.get("top_provider"), dict) else {}

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    prompt, completion = number(pricing.get("prompt")), number(pricing.get("completion"))
    return {"id": mid, "name": _clean(raw.get("name"), 80), "context": raw.get("context_length") if isinstance(raw.get("context_length"), int) else None,
            "max_output": top.get("max_completion_tokens") if isinstance(top.get("max_completion_tokens"), int) else None,
            "tools": "tools" in params, "structured": "structured_outputs" in params or "response_format" in params, "reasoning": "reasoning" in params,
            "inputs": [m for m in arch.get("input_modalities", []) if isinstance(m, str) and len(m) < 20][:6] if isinstance(arch.get("input_modalities"), list) else [],
            "free": prompt == 0 and completion == 0, "prompt_per_m": None if prompt is None else round(prompt * 1e6, 4),
            "completion_per_m": None if completion is None else round(completion * 1e6, 4)}


def default_fetch(url: str = LIST_URL, timeout: int = 20) -> bytes:
    """One public HTTPS URL, no credentials, no redirects followed, size capped."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "dashboard-model-profiles"}), timeout=timeout) as response:
        return response.read(MAX_BYTES + 1)


def snapshot(data_dir) -> dict | None:
    got = _read_json(_folder(data_dir) / SNAPSHOT)
    return got if isinstance(got, dict) and isinstance(got.get("models"), list) else None


def refresh(data_dir, now: int | None = None, fetch=None, enabled: bool = True) -> dict:
    """Read the public list, store a dated snapshot, and report what changed against the previous snapshot and the price catalog. Edits nothing else."""
    if not enabled:
        raise ModelError("Refreshing the model list is switched off in this installation.")
    now = int(now if now is not None else time.time())
    try:
        raw = (fetch or default_fetch)()
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        raise ModelError(f"The model list could not be read ({type(error).__name__}). Nothing was changed.") from None
    if len(raw) > MAX_BYTES:
        raise ModelError("The model list is larger than expected. Nothing was changed.")
    try:
        data = json.loads(raw).get("data")
    except (ValueError, AttributeError):
        raise ModelError("The model list was not understood. Nothing was changed.") from None
    if not isinstance(data, list) or not data:
        raise ModelError("The model list was empty or not understood. Nothing was changed.")
    models = [e for e in (_entry(m) for m in data[:MAX_MODELS] if isinstance(m, dict)) if e]
    if not models:
        raise ModelError("No usable models were found in the list. Nothing was changed.")
    previous = snapshot(data_dir)
    current = {"fetched_at": now, "source": LIST_URL, "models": sorted(models, key=lambda m: m["id"])}
    _write_json(_folder(data_dir) / SNAPSHOT, current)
    return {"fetched_at": now, "count": len(models), "free": sum(1 for m in models if m["free"]), "diff": diff(previous, current)}


def diff(previous: dict | None, current: dict) -> dict:
    """New and gone free models against the price catalog's free list, and changes since the previous snapshot."""
    known_free = set(billing.CATALOG.get("free_models", {}))
    live = {m["id"]: m for m in current["models"]}
    live_free = {i for i, m in live.items() if m["free"]}
    out = {"new_free": sorted(live_free - known_free)[:60], "no_longer_free": sorted(i for i in known_free if i not in live_free)[:60], "changed": []}
    if previous:
        before = {m["id"]: m for m in previous["models"]}
        for mid, m in sorted(live.items()):
            old = before.get(mid)
            if old:
                changes = [k for k in ("context", "tools", "structured", "reasoning", "free") if old.get(k) != m.get(k)]
                if changes:
                    out["changed"].append({"id": mid, "fields": changes})
        out["changed"] = out["changed"][:60]
        out["added_since_last"] = len(set(live) - set(before))
        out["removed_since_last"] = len(set(before) - set(live))
    return out


# --------------------------------------------------------------------------------------------------------------- notes
def notes(data_dir, now: int | None = None) -> list[dict]:
    now = int(now if now is not None else time.time())
    raw = _read_json(_folder(data_dir) / NOTES)
    out = []
    for n in (raw if isinstance(raw, list) else [])[:MAX_NOTES]:
        if not isinstance(n, dict) or not ID_RE.match(str(n.get("model", ""))) or not DATE_RE.match(str(n.get("date", ""))):
            continue
        try:
            age_days = (now - int(time.mktime(time.strptime(n["date"], "%Y-%m-%d")))) // 86400
        except (ValueError, OverflowError):
            continue
        out.append({"id": str(n.get("id", "")), "model": _norm(n["model"]), "text": _clean(n.get("text"), NOTE_TEXT_MAX), "source": _clean(n.get("source"), 200),
                    "date": n["date"], "stale": age_days > STALE_DAYS})
    return out


def add_note(data_dir, model: str, text: str, source: str, date: str, now: int | None = None) -> dict:
    """A note needs a model id, text, a source and a date: a claim nobody can trace is not kept."""
    model, text, source = _norm(model), _clean(text, NOTE_TEXT_MAX), _clean(source, 200)
    if not ID_RE.match(model) or not text or not source or not DATE_RE.match(date or ""):
        raise ModelError("A note needs a model id, text, a source and a date (YYYY-MM-DD).")
    existing = _read_json(_folder(data_dir) / NOTES)
    existing = existing if isinstance(existing, list) else []
    if len(existing) >= MAX_NOTES:
        raise ModelError(f"At most {MAX_NOTES} notes are kept; delete some first.")
    note = {"id": f"n{int(now if now is not None else time.time())}x{len(existing)}", "model": model, "text": text, "source": source, "date": date}
    _write_json(_folder(data_dir) / NOTES, [*existing, note])
    return note


def delete_note(data_dir, note_id: str) -> bool:
    existing = _read_json(_folder(data_dir) / NOTES)
    existing = existing if isinstance(existing, list) else []
    kept = [n for n in existing if n.get("id") != note_id]
    if len(kept) == len(existing):
        return False
    _write_json(_folder(data_dir) / NOTES, kept)
    return True


# ------------------------------------------------------------------------------------------------------------ profiles
def _observed(s, now: int, days: int) -> dict[str, dict]:
    """Per served model: totals and per kind of work, from the same records the Telemetry page uses."""
    cfg = billing.config(s)
    rows: dict[str, dict] = {}
    for rec in telemetry.collect(s, now, days, cfg):
        for run in rec["runs"]:
            if run.started_at < now - days * 86400:
                continue
            model = _norm(run.model_reported or run.model_requested) or "unknown"
            row = rows.setdefault(model, {"runs": 0, "succeeded": 0, "seconds": [], "tokens": 0, "cost_usd": 0.0, "fallbacks": 0, "kinds": defaultdict(lambda: {"runs": 0, "succeeded": 0, "first_pass": 0, "cards": 0})})
            kind = rec["card"].kind or "untagged"
            k = row["kinds"][kind]
            row["runs"] += 1
            k["runs"] += 1
            if run.stage == "succeeded":
                row["succeeded"] += 1
                k["succeeded"] += 1
                if rec["attempts"] == 1:
                    k["first_pass"] += 1
            if run.duration_s:
                row["seconds"].append(run.duration_s)
            row["tokens"] += (run.input_tokens or 0) + (run.output_tokens or 0)
            row["cost_usd"] += run.cost_usd or 0.0
            if run.model_requested and run.model_reported and _norm(run.model_requested) != _norm(run.model_reported):
                row["fallbacks"] += 1
    return rows


def profiles(s, data_dir, now: int | None = None, days: int = 90) -> dict:
    now = int(now if now is not None else time.time())
    days = max(1, min(int(days), telemetry.MAX_DAYS))
    live = snapshot(data_dir)
    live_by_id = {m["id"]: m for m in live["models"]} if live else {}
    observed = _observed(s, now, days)
    all_notes = notes(data_dir, now)
    research = model_evidence.records(data_dir)
    ids = set(billing.CATALOG.get("models", {})) | set(billing.CATALOG.get("free_models", {})) | set(observed) | {n["model"] for n in all_notes}
    ids |= {i for i, m in live_by_id.items() if m["free"] or i in observed}
    ids |= {r["model"] for r in research}
    rows = []
    for mid in sorted(ids):
        cat = billing.CATALOG.get("models", {}).get(mid) or billing.CATALOG.get("free_models", {}).get(mid) or {}
        fact = live_by_id.get(mid) or next((live_by_id[prefix+mid] for prefix in ("openai/","anthropic/","google/") if prefix+mid in live_by_id),None)
        obs = observed.get(mid)
        free = bool(fact["free"]) if fact else (mid in billing.CATALOG.get("free_models", {}) or mid.endswith(":free") or mid == "openrouter/free")
        if mid == "unknown":
            free = None        # runs that recorded no model: we cannot say whether they were free
        kinds = []
        if obs:
            for kind, k in sorted(obs["kinds"].items(), key=lambda kv: -kv[1]["runs"]):
                kinds.append({"kind": kind, "runs": k["runs"], "success_rate": round(k["succeeded"] / k["runs"], 2), "first_pass": k["first_pass"], "proven": k["runs"] >= PROVEN_RUNS})
        rows.append({
            "evidence": model_evidence.for_model(research,mid,now), "selection": model_selection.classification(mid, now), "id": mid, "name": "model not recorded" if mid == "unknown" else (fact or {}).get("name") or mid, "free": free, "platform": cat.get("platform"), "agents": cat.get("agents", []), "status": cat.get("status"),
            "in_catalog": bool(cat), "in_snapshot": bool(fact), "context": (fact or {}).get("context") or cat.get("max_input"), "tools": (fact or {}).get("tools"),
            "structured": (fact or {}).get("structured"), "reasoning": (fact or {}).get("reasoning"), "inputs": (fact or {}).get("inputs", []),
            "price_in": cat.get("input", (fact or {}).get("prompt_per_m")), "price_out": cat.get("output", (fact or {}).get("completion_per_m")),
            "observed": None if not obs else {"runs": obs["runs"], "success_rate": round(obs["succeeded"] / obs["runs"], 2), "median_seconds": telemetry._median(obs["seconds"]),
                                              "tokens": obs["tokens"], "cost_usd": round(obs["cost_usd"], 4), "served_instead_of_requested": obs["fallbacks"], "proven": obs["runs"] >= PROVEN_RUNS},
            "kinds": kinds, "notes": [n for n in all_notes if n["model"] == mid]})
    rows.sort(key=lambda r: (-(r["observed"] or {}).get("runs", 0), not r["free"], r["id"]))
    return {"generated_at": now, "days": days, "proven_runs": PROVEN_RUNS, "stale_days": STALE_DAYS,
            "snapshot": {"fetched_at": live["fetched_at"], "count": len(live["models"]), "free": sum(1 for m in live["models"] if m["free"])} if live else None,
            "models": rows, "stale_notes": sum(1 for n in all_notes if n["stale"])}


def research_status(data_dir, now=None):
    """Freshness is explicit; request-time planning never fetches the network."""
    now = int(now if now is not None else time.time())
    live = snapshot(data_dir)
    return {'provider_snapshot': {'source': live.get('source', LIST_URL), 'fetched_at': live['fetched_at'],
                'stale': now - live['fetched_at'] > 7 * 86400} if live else None,
            'benchmark_source': 'https://artificialanalysis.ai/models/recommend',
            'benchmark_api_docs': 'https://artificialanalysis.ai/data-api/docs',
            'benchmark_state': 'not_connected',
            'note': 'External benchmarks require dated source notes or a separately configured research connection. They do not prove this installation has quota, tools or reliable task completion.'}


# ------------------------------------------------------------------------------------------------------- routing guidance
WRITE_KINDS = ("implement", "test", "docs", "ops")
GUIDANCE_MAX_CHARS = 3500
GUIDANCE_MAX_MODELS = 24


def guidance_text(s, data_dir, catalog: list[dict], now: int | None = None) -> str:
    """A compact paragraph for the planner: for the models it may choose, free or paid, context, tool support and what has actually happened
    here by kind of work, with unproven stated plainly. Advice for the coordinator; the server still enforces every gate."""
    now = int(now if now is not None else time.time())
    by_id = {m["id"]: m for m in profiles(s, data_dir, now)["models"]}
    accounts = billing.config(s).get('accounts', {})
    lines, seen = [], set()
    # Round-robin prevents one wrapper's long list crowding out other installed agents.
    entries = [dict(entry, models=[model]) for i in range(max((len(e.get('models', [])) for e in catalog or []), default=0))
               for entry in catalog or [] for model in entry.get('models', [])[i:i+1]]
    for entry in entries:
        for model in entry.get("models", []):
            key = (entry.get("agent"), _norm(model))
            if key in seen or len(lines) >= GUIDANCE_MAX_MODELS or not _norm(model):
                continue
            seen.add(key)
            p = by_id.get(_norm(model))
            if not p:
                continue
            membership = accounts.get(entry.get('agent'), {}).get('mode') == 'subscription'
            bits = ['membership quota (API price is reference only)' if membership else 'free' if p['free'] else 'paid']
            if p["context"]:
                bits.append(f"context {p['context']:,}")
            if p["tools"] is not None:
                bits.append("tools" if p["tools"] else "no tool use listed")
            seen_kinds = [f"{k['kind']} {round(k['success_rate'] * 100)}% of {k['runs']}" + ("" if k["proven"] else " (unproven)") for k in p["kinds"][:4]]
            bits.append("here: " + ", ".join(seen_kinds) if seen_kinds else "never run here (unproven)")
            fresh_notes = [n for n in p['notes'] if not n['stale']]
            if fresh_notes:
                n = fresh_notes[-1]
                bits.append(f"research note (untrusted, {n['date']}, {n['source'][:100]}): {n['text'][:180]}")
            signals=sorted(p.get('evidence',[]),key=lambda e:({'quality':0,'latency_p50':1,'output_speed':2}.get(e['metric'],3),e['stale']))
            for sample in signals[:2]:
                bits.append('external observation (untrusted): '+str(sample['metric'])+'='+str(sample['value'])+' '+sample['unit']+' '+sample['as_of']+(' stale' if sample['stale'] else '')+(' conflicting sources' if sample['conflicting'] else '')+'; '+sample['source'][:100]+('; benchmark '+sample['benchmark'][:60]+' / '+str(sample['scale_max']) if sample['benchmark'] else '')+'; '+sample['environment'][:60]+'; '+sample['method'][:80])
            fit = model_selection.classification(_norm(model), now)
            bits.append('class '+fit['class']+' (routing heuristic); '+fit['use'])
            if fit['verified']: bits.append('vendor guidance '+fit['verified']+(' (stale; recheck)' if fit['stale'] else ''))
            if fit['vision'] is True: bits.append('vision listed by vendor; verify harness support')
            if p['inputs']: bits.append('input '+','.join(p['inputs']))
            if p['structured'] is not None: bits.append('structured output '+str(p['structured']))
            if p['price_in'] is not None: bits.append(f"API $/M in={p['price_in']} out={p['price_out']} (catalog/snapshot rates; check freshness)")
            if p['observed'] and p['observed'].get('median_seconds') is not None: bits.append(f"local median {p['observed']['median_seconds']}s/run, task mix dependent")
            lines.append(f"- {entry.get('agent')}/{_norm(model)}: " + "; ".join(bits))
    if not lines:
        return ""
    head = ("Model facts and track record from this installation (advice, not authorization; a model with under "
            f"{PROVEN_RUNS} runs of a kind is unproven for it, so prefer a proven route for medium or high risk work):")
    facts = research_status(data_dir, now)
    freshness = facts['provider_snapshot']
    head += ' Process success is not artifact acceptance. Match task specialty/tools/vision/context first, then compare latency, quota and expected cost including retries. Dated benchmark notes are advice, never permission; unknown facts stay unknown.'
    head += ' Provider snapshot: ' + ('missing; verify current availability.' if not freshness else
        str(freshness['fetched_at']) + (' (stale; verify before changing routes).' if freshness['stale'] else ' (cached).'))
    return (head + "\n" + "\n".join(lines))[:GUIDANCE_MAX_CHARS]


def route_advice(s, data_dir, nodes: list[dict], now: int | None = None) -> list[dict]:
    """Non-blocking advice on a plan's routes, from observed numbers and listed facts. Never refuses anything; the gates do that."""
    now = int(now if now is not None else time.time())
    by_id = {m["id"]: m for m in profiles(s, data_dir, now)["models"]}
    out = []
    for node in nodes:
        if node.get("kind") != "story" or node.get("assignee") in (None, "", "human") or not node.get("model"):
            continue
        model, kind, risk, key = _norm(node["model"]), node.get("work_kind"), node.get("risk"), node.get("key")
        p = by_id.get(model)
        if not p:
            continue
        stat = next((k for k in p["kinds"] if k["kind"] == kind), None)
        if kind in WRITE_KINDS and p["tools"] is False:
            out.append({"key": key, "level": "warn", "text": f"{model} does not list tool use; an agent that edits files normally needs it."})
        if stat and stat["proven"] and stat["success_rate"] < 0.5:
            out.append({"key": key, "level": "warn", "text": f"{model} has succeeded on only {round(stat['success_rate'] * 100)}% of {stat['runs']} {kind} runs here; consider another route."})
        elif (not stat or not stat["proven"]) and risk in ("medium", "high"):
            out.append({"key": key, "level": "info", "text": f"{model} is unproven for {kind or 'this kind of'} work here ({stat['runs'] if stat else 0} runs) and this story is {risk} risk; consider a route with a track record or a review step."})
    return out
