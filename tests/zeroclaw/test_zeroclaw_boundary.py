"""Admission, config rendering, provider proxy and adapter preflight. No runtime binary needed."""
from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request

import pytest

from zc_support import FINAL, FREE, PAID, ZERO, make_spec
from integrations.zeroclaw import FreeModelCatalog, Refusal, snapshot_from_openrouter_models
from integrations.zeroclaw.runtime_config import render, resolve_tools


# ----------------------------------------------------------------------------- admission
def test_free_model_admitted_and_priced_or_unknown_refused(catalog):
    catalog.admit(FREE)
    for model in (PAID, "vendor/unknown", ""):
        with pytest.raises(Refusal):
            catalog.admit(model)


@pytest.mark.parametrize("pricing", [{"prompt": "0"}, {"prompt": "0", "completion": "0", "request": "0.01"},
                                     {"prompt": "x", "completion": "0"}, {"prompt": None, "completion": "0"},
                                     {"prompt": "-1", "completion": "0"}, {"prompt": "NaN", "completion": "0"}])
def test_unknown_malformed_or_partly_priced_models_are_refused(pricing):
    with pytest.raises(Refusal) as refusal:
        FreeModelCatalog({FREE: pricing}, verified_at=int(time.time())).admit(FREE)
    assert refusal.value.code == "BUDGET_EXCEEDED"


def test_stale_or_undated_snapshot_refuses_everything():
    for stamp in (0, int(time.time()) - 3 * 86400, int(time.time()) + 86400):
        with pytest.raises(Refusal):
            FreeModelCatalog({FREE: ZERO}, verified_at=stamp).admit(FREE)


def test_snapshot_builder_keeps_only_exactly_zero_priced_models(tmp_path):
    payload = {"data": [{"id": "a:free", "pricing": {"prompt": "0", "completion": "0", "image": "0"}},
                        {"id": "b", "pricing": {"prompt": "0", "completion": "0.000001"}},
                        {"id": "c", "pricing": {"prompt": "0"}}, {"id": "d"}]}
    snapshot = snapshot_from_openrouter_models(payload, now=1_900_000_000)
    assert list(snapshot["models"]) == ["a:free"]
    path = tmp_path / "free.json"
    path.write_text(json.dumps(snapshot))
    FreeModelCatalog.load(path).admit("a:free", now=1_900_000_100)
    with pytest.raises(Refusal):
        FreeModelCatalog.load(tmp_path / "missing.json")


# ----------------------------------------------------------------------------- config rendering
def _render(**over):
    args = dict(proxy_url="http://127.0.0.1:1/v1", token="rcd-tok", model=FREE, workspace="/ws", mode="edit",
                allowed=[], timeout_s=30, max_tokens=64, max_turns=None, transient_retries=0)
    return render(**{**args, **over})


def test_rendered_config_has_one_loopback_provider_and_no_fallback_or_real_key():
    text = _render()
    assert "providers.models.custom.rcd" in text and "127.0.0.1" in text
    assert "openrouter" not in text.lower() and "sk-or" not in text
    for forbidden in ("fallback", "model_routes", "fallback_models", "[channels"):
        assert forbidden not in text
    assert 'level = "supervised"' in text and "workspace_only = true" in text
    assert "native_tools = true" in text  # text-fallback mode drops the tool exchange on 0.8.5


def test_read_mode_is_readonly_and_tools_map_explicitly():
    assert 'level = "readonly"' in _render(mode="read")
    assert resolve_tools(["Read", "Write"], {}) == ["file_read", "file_write"]
    assert resolve_tools(["echo"], {"rcd": {"tools": ["echo"]}}) == ["rcd__echo"]
    with pytest.raises(KeyError):
        resolve_tools(["Teleport"], {})


def test_mcp_servers_are_rendered_for_driver_tools_only():
    text = _render(mcp_servers={"rcd": {"command": "/bin/true", "args": ["a b"], "tools": ["echo"]}})
    assert "[[mcp.servers]]" in text and 'name = "rcd"' in text and "[mcp_bundles.rcd]" in text


# ----------------------------------------------------------------------------- provider proxy
def _post(proxy, token, body):
    request = urllib.request.Request(proxy.base_url + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                     headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_proxy_admits_assigned_free_model_forces_zero_price_and_records_served_model(proxy, upstream):
    token = proxy.register("r1", FREE, max_tokens=50)
    status, _ = _post(proxy, token, {"model": FREE, "stream": True, "max_tokens": 9999, "models": ["x/y"],
                                     "messages": []})
    assert status == 200
    sent = upstream.requests[0]
    assert sent["stream"] is False and sent["max_tokens"] == 50
    assert sent["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0, "image": 0}
    assert sent["auth"] == "Bearer test-key-not-a-secret"
    receipt, = proxy.receipts("r1")
    assert (receipt["model"], receipt["provider"], receipt["cost_usd"]) == (FREE, "StubProvider", 0.0)
    assert receipt["usage"] == {"input_tokens": 11, "output_tokens": 7}
    assert receipt["source"] == "provider_response" and receipt["response_id"]


@pytest.mark.parametrize("model", [PAID, "vendor/unknown", "other/model:free"])
def test_proxy_refuses_unassigned_paid_or_unknown_models_before_upstream(proxy, upstream, model):
    token = proxy.register("r2", FREE)
    status, body = _post(proxy, token, {"model": model, "messages": []})
    assert status == 403 and upstream.requests == []
    assert proxy.refusals("r2")[0][0] in {"MODEL_NOT_ALLOWED", "BUDGET_EXCEEDED"}


def test_proxy_refuses_paid_assignment_even_if_requested_as_assigned(proxy, upstream):
    token = proxy.register("r3", PAID)
    status, _ = _post(proxy, token, {"model": PAID, "messages": []})
    assert status == 403 and upstream.requests == [] and proxy.refusals("r3")[0][0] == "BUDGET_EXCEEDED"


def test_proxy_needs_a_known_token_and_a_credential(proxy, upstream, monkeypatch):
    assert _post(proxy, "rcd-unknown", {"model": FREE})[0] == 401
    token = proxy.register("r4", FREE)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert _post(proxy, token, {"model": FREE})[0] == 401 and upstream.requests == []


def test_served_model_mismatch_is_withheld_and_flagged(proxy, upstream):
    upstream.served_model = "someone/else"
    token = proxy.register("r5", FREE)
    status, _ = _post(proxy, token, {"model": FREE})
    assert status == 502 and proxy.flags("r5") == {"model_mismatch"}
    assert proxy.receipts("r5")[0]["model"] == "someone/else"
    assert _post(proxy, token, {"model": FREE})[0] == 403  # run is closed: no further inference


def test_nonzero_reported_cost_is_a_breach_and_closes_the_run(proxy, upstream):
    upstream.cost = 0.000001
    token = proxy.register("r6", FREE)
    assert _post(proxy, token, {"model": FREE})[0] == 502
    assert proxy.flags("r6") == {"cost_breach"} and _post(proxy, token, {"model": FREE})[0] == 403


def test_missing_cost_fails_closed_without_fabricating_a_receipt(proxy, upstream):
    upstream.cost = None
    token = proxy.register("r7", FREE)
    assert _post(proxy, token, {"model": FREE})[0] == 502
    assert proxy.receipts("r7") == []
    assert "unaccounted_response" in proxy.flags("r7")


def test_closed_run_and_request_cap_stop_traffic(proxy, upstream):
    token = proxy.register("r8", FREE, max_requests=1)
    assert _post(proxy, token, {"model": FREE})[0] == 200
    assert _post(proxy, token, {"model": FREE})[0] == 403
    other = proxy.register("r9", FREE)
    proxy.close_run("r9")
    assert _post(proxy, other, {"model": FREE})[0] == 403 and len(upstream.requests) == 1


def test_injected_provider_failure_is_returned_before_any_upstream_call(proxy, upstream):
    token = proxy.register("r10", FREE)
    proxy.inject("r10", failure="rate_limit")
    assert _post(proxy, token, {"model": FREE})[0] == 429 and upstream.requests == []


def test_proxy_refuses_non_loopback_binding(catalog):
    from integrations.zeroclaw import ProviderProxy
    with pytest.raises(ValueError):
        ProviderProxy(catalog, host="0.0.0.0")


# ----------------------------------------------------------------------------- adapter preflight
def _run(adapter, spec):
    async def go():
        await adapter.start(spec)
        async for _ in adapter.events(spec["run_id"]):
            pass
        return await adapter.result(spec["run_id"])
    return asyncio.run(go())


@pytest.mark.parametrize("kwargs,code", [
    (dict(model=PAID), "BUDGET_EXCEEDED"), (dict(model="vendor/unknown"), "MODEL_NOT_ALLOWED"),
    (dict(billing="byok"), "BUDGET_EXCEEDED"), (dict(billing="subscription"), "BUDGET_EXCEEDED"),
    (dict(tools=["Teleport"]), "TOOL_DENIED")])
def test_refusals_fail_the_run_before_any_process_or_inference(make_adapter, workspace, upstream, kwargs, code):
    result = _run(make_adapter(executable="/nonexistent/zeroclaw"), make_spec(workspace, **kwargs))
    assert (result["status"], result["error"]["code"]) == ("failed", code)
    assert result["exit_code"] is None and upstream.requests == []
    assert result["cost"]["usd"] == 0


def test_run_for_another_agent_or_missing_workspace_is_refused(make_adapter, tmp_path):
    spec = make_spec(tmp_path / "missing")
    assert _run(make_adapter(), spec)["error"]["code"] == "WORKSPACE_REJECTED"
    other = make_spec(tmp_path, run_id="zc-2")
    other["model_policy"]["assigned"]["agent"] = "picoclaw"
    assert _run(make_adapter(), other)["error"]["code"] == "MODEL_NOT_ALLOWED"


def test_oversized_prompt_and_resume_session_are_refused(make_adapter, workspace):
    big = make_spec(workspace)
    big["prompt"] = "x" * 100_001
    assert _run(make_adapter(), big)["error"]["code"] == "INVALID_RUN_SPEC"
    resume = make_spec(workspace, run_id="zc-3")
    resume["session"] = {"mode": "resume", "session_id": "abc"}
    assert _run(make_adapter(), resume)["error"]["code"] == "RUNTIME_INCOMPATIBLE"


def test_missing_runtime_is_a_recorded_failure(make_adapter, workspace):
    result = _run(make_adapter(executable="/nonexistent/zeroclaw"), make_spec(workspace))
    assert result["error"]["code"] == "RUNTIME_UNAVAILABLE"


def test_capabilities_state_what_this_adapter_can_actually_do(make_adapter):
    caps = make_adapter(executable="/nonexistent/zeroclaw").capabilities()
    assert caps["pins_model"] and caps["disables_native_fallback"] and caps["enforces_budget"] == "adapter"
    assert caps["reports_model"] == "at_end" and caps["suspend_modes"] == ["live"] and caps["session"] == "none"
