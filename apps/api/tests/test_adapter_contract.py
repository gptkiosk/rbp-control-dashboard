"""The adapter contract is self-consistent and its sample payloads validate (docs/port/adapter-contract.md)."""

from __future__ import annotations

import inspect
import json

import pytest

import adapter_contract as ac

EXAMPLES = json.loads((ac.SCHEMA_PATH.parent / "examples.json").read_text())


def _validator(definition):
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft202012Validator(ac.schema_for(definition))


def test_schema_is_valid_draft_2020_12():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(ac.schema())


@pytest.mark.parametrize("sample", EXAMPLES["valid"], ids=lambda s: f'{s["def"]}: {s["name"]}')
def test_valid_samples(sample):
    errors = sorted(_validator(sample["def"]).iter_errors(sample["payload"]), key=str)
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize("sample", EXAMPLES["invalid"], ids=lambda s: f'{s["def"]}: {s["name"]}')
def test_invalid_samples(sample):
    assert not _validator(sample["def"]).is_valid(sample["payload"]), sample["why"]


def test_every_message_type_has_a_valid_sample():
    covered = {s["def"] for s in EXAMPLES["valid"]}
    assert {"RunSpec", "Event", "RunResult", "Decision", "CancelRequest", "Heartbeat",
            "RecoveredRun", "Capabilities"} <= covered
    event_types = {s["payload"]["type"] for s in EXAMPLES["valid"] if s["def"] == "Event"}
    assert set(ac.schema()["$defs"]["Event"]["properties"]["type"]["enum"]) - event_types <= {"heartbeat"}


def test_python_and_schema_enums_match():
    defs = ac.schema()["$defs"]
    assert set(defs["RunStatus"]["enum"]) == {s.value for s in ac.RunStatus}
    assert set(defs["TerminalStatus"]["enum"]) == {s.value for s in ac.TERMINAL}
    assert set(defs["ErrorCode"]["enum"]) == set(ac.ERRORS)
    assert set(defs["ErrorCategory"]["enum"]) == {c.value for c in ac.ErrorCategory}
    assert defs["SchemaVersion"]["const"] == ac.SCHEMA_VERSION


def test_state_machine():
    S = ac.RunStatus
    assert set(ac.TRANSITIONS) == set(S)
    assert ac.can_transition(None, S.QUEUED) and not ac.can_transition(None, S.RUNNING)
    for path in ([S.QUEUED, S.RUNNING, S.SUCCEEDED],
                 [S.QUEUED, S.RUNNING, S.AWAITING_APPROVAL, S.RUNNING, S.SUCCEEDED],
                 [S.QUEUED, S.RUNNING, S.AWAITING_APPROVAL, S.CANCELLED],
                 [S.QUEUED, S.CANCELLED], [S.QUEUED, S.FAILED], [S.QUEUED, S.RUNNING, S.TIMED_OUT]):
        assert all(ac.can_transition(a, b) for a, b in zip(path, path[1:])), path
    for terminal in ac.TERMINAL:
        assert not ac.TRANSITIONS[terminal]
    assert not ac.can_transition(S.QUEUED, S.AWAITING_APPROVAL)
    assert not ac.can_transition(S.AWAITING_APPROVAL, S.SUCCEEDED)  # approval never completes work by itself
    assert not ac.can_transition(S.RUNNING, S.QUEUED)                 # retries are new runs


def test_error_taxonomy_is_coherent():
    for code, info in ac.ERRORS.items():
        assert info.status is None or info.status in ac.TERMINAL - {ac.RunStatus.SUCCEEDED}, code
        assert not (info.fallback_eligible and info.category is not ac.ErrorCategory.PROVIDER), code
        if info.category is ac.ErrorCategory.CONTROL:
            assert info.status is None, code
    # Only quota/rate limits may trigger an automatic switch to an approved route (projects.on_finish).
    assert {c for c, i in ac.ERRORS.items() if i.fallback_eligible} == {"PROVIDER_RATE_LIMITED", "PROVIDER_QUOTA_EXHAUSTED"}
    assert ac.error("TIMEOUT", "x")["category"] == "lifecycle"
    with pytest.raises(ac.AdapterError) as exc:
        raise ac.AdapterError("UNKNOWN_RUN", "no such run", run_id="9")
    assert exc.value.payload["detail"] == {"run_id": "9"}


def test_sample_errors_follow_the_taxonomy():
    for sample in EXAMPLES["valid"]:
        p = sample["payload"]
        err = p.get("error") if sample["def"] == "RunResult" else p["data"] if p.get("type") == "error" else None
        if not err:
            continue
        info = ac.ERRORS[err["code"]]
        assert (err["category"], err["retryable"], err["fallback_eligible"], err["requires_human"]) == (
            info.category.value, info.retryable, info.fallback_eligible, info.requires_human), sample["name"]
        if sample["def"] == "RunResult":
            assert p["status"] == info.status.value, sample["name"]


def test_legacy_stages_map_into_the_contract():
    for stage, (status, code) in ac.LEGACY_STAGE.items():
        assert status in ac.RunStatus
        assert code is None or ac.ERRORS[code].status is status, stage


def test_idempotency_helpers_match_dispatcher():
    assert ac.run_key(37) == "mcd:run:37" and ac.work_key(37) == "mcd:story:37"
    import uuid
    assert ac.preassigned_session(36) == str(uuid.uuid5(uuid.NAMESPACE_URL, "mcd:story:36"))
    spec = next(s["payload"] for s in EXAMPLES["valid"] if s["def"] == "RunSpec")
    assert ac.spec_digest(spec) == ac.spec_digest(json.loads(json.dumps(spec)))
    assert ac.spec_digest(spec) != ac.spec_digest({**spec, "prompt": spec["prompt"] + " "})
    assert ac.spec_digest(spec) == ac.spec_digest({**spec, "origin": {**spec["origin"], "story_title": "renamed"}})


def test_protocol_surface():
    ops = {"capabilities", "start", "events", "result", "cancel", "resume", "heartbeat", "recover"}
    members = {n for n, _ in inspect.getmembers(ac.AgentAdapter, inspect.isfunction)}
    assert ops <= members
    for name in ops - {"capabilities", "events"}:
        assert inspect.iscoroutinefunction(getattr(ac.AgentAdapter, name)), name
