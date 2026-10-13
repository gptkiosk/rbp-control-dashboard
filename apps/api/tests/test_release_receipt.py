"""Evidence receipts (s1-release-evidence): labels, digests and refusals.

Commands are real short-lived synthetic child processes (``sys.executable -c ...``) run in tmp_path.
Source state is faked where a live label needs a clean commit, because the test tree is not a release.
Nothing touches the network, the live service or port 8800.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("receipt", REPO_ROOT / "scripts" / "release" / "receipt.py")
receipt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(receipt)

PASS = [sys.executable, "-c", "print('ok')"]
FAIL = [sys.executable, "-c", "import sys; print('no'); sys.exit(3)"]
CLEAN = {"commit": "a" * 40, "dirty": False, "release_eligible": True}
DIRTY = {"commit": "a" * 40, "dirty": True, "release_eligible": False}


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "evidence"


def make(out: Path, *, env: str, argv: list[str], name: str = "unit", timeout: int = 60, **kw):
    return receipt.build_receipt(name=name, env_class=env, argv=argv, out_dir=out, timeout=timeout, **kw)


def test_mock_run_is_never_live_proof_even_on_clean_source(out, monkeypatch):
    monkeypatch.setattr(receipt, "source_info", lambda: CLEAN)
    path, body = make(out, env="mock", argv=PASS)
    assert body["overall"] == "pass"
    assert body["live_proof"] is False
    assert receipt.verify_receipt(path) == ([], ["environment class is mock: a mock or synthetic result, not live proof"])


def test_live_class_with_mock_marker_is_downgraded(out, monkeypatch):
    monkeypatch.setattr(receipt, "source_info", lambda: CLEAN)
    _, body = make(out, env="live", argv=PASS + ["fake-gh-auth"])
    assert body["environment"]["mock_markers"] == ["fake"]
    assert body["live_proof"] is False


def test_live_proof_needs_clean_commit_and_pass(out, monkeypatch):
    monkeypatch.setattr(receipt, "source_info", lambda: CLEAN)
    path, body = make(out, env="live", argv=PASS)
    assert body["live_proof"] is True
    assert receipt.verify_receipt(path, expect_live=True)[0] == []


def test_dirty_or_uncommitted_source_is_never_live_proof(out, monkeypatch):
    monkeypatch.setattr(receipt, "source_info", lambda: DIRTY)
    _, body = make(out, env="live", argv=PASS)
    assert body["live_proof"] is False


def test_failed_command_is_recorded_not_hidden(out, monkeypatch):
    monkeypatch.setattr(receipt, "source_info", lambda: CLEAN)
    path, body = make(out, env="live", argv=FAIL)
    assert body["step"]["exit_code"] == 3
    assert body["overall"] == "fail"
    assert body["live_proof"] is False
    assert receipt.verify_receipt(path)[0] == []


def test_timeout_is_a_failure(out):
    slow = [sys.executable, "-c", "import time; time.sleep(30)"]
    _, body = make(out, env="mock", argv=slow, timeout=1)
    assert body["step"]["timed_out"] is True
    assert body["overall"] == "fail"


def test_log_is_written_beside_receipt_and_digested(out):
    path, body = make(out, env="mock", argv=PASS)
    log = path.with_suffix(".log")
    assert log.read_bytes().strip() == b"ok"
    assert body["step"]["output_sha256"] == receipt.sha256_bytes(log.read_bytes())
    assert "output" not in json.loads(path.read_text())["step"]


def test_tampered_label_fails_verification(out, monkeypatch):
    monkeypatch.setattr(receipt, "source_info", lambda: CLEAN)
    path, _ = make(out, env="mock", argv=PASS)
    data = json.loads(path.read_text())
    data["live_proof"] = True
    path.write_text(json.dumps(data))
    errors, _ = receipt.verify_receipt(path)
    assert "receipt_sha256 does not match the receipt contents" in errors


def test_relabelled_mock_as_live_fails_even_with_resealed_digest(out, monkeypatch):
    monkeypatch.setattr(receipt, "source_info", lambda: CLEAN)
    path, _ = make(out, env="mock", argv=PASS)
    data = json.loads(path.read_text())
    data["live_proof"] = True
    data.pop("receipt_sha256")
    data["receipt_sha256"] = receipt.sha256_bytes(receipt.canonical_json(data))
    path.write_text(json.dumps(data))
    errors, _ = receipt.verify_receipt(path)
    assert "live_proof must be False for class 'mock'" in errors
    assert "mock run labelled as live proof" in errors


def test_expect_live_rejects_mock_receipt(out):
    path, _ = make(out, env="mock", argv=PASS)
    errors, _ = receipt.verify_receipt(path, expect_live=True)
    assert errors == ["not live proof"]


def test_stale_source_is_detected_when_checked(out, monkeypatch):
    monkeypatch.setattr(receipt, "source_info", lambda: CLEAN)
    path, _ = make(out, env="live", argv=PASS)
    monkeypatch.setattr(receipt, "source_info", lambda: {**CLEAN, "commit": "b" * 40})
    errors, _ = receipt.verify_receipt(path, check_source=True)
    assert errors == [f"stale receipt: recorded {'a' * 40} but source is {'b' * 40}"]


def test_out_inside_repository_is_refused():
    with pytest.raises(receipt.ReceiptError, match="outside the repository"):
        make(REPO_ROOT / "scripts" / "release" / "__receipts__", env="mock", argv=PASS)


def test_credential_looking_argument_is_refused(out):
    with pytest.raises(receipt.ReceiptError, match="credential"):
        make(out, env="mock", argv=PASS + ["--api_key=abc"])


def test_bad_name_and_env_class_are_refused(out):
    with pytest.raises(receipt.ReceiptError, match="bad receipt name"):
        make(out, env="mock", argv=PASS, name="../escape")
    with pytest.raises(receipt.ReceiptError, match="--env must be one of"):
        make(out, env="production", argv=PASS)


def test_existing_receipt_is_never_overwritten(out, monkeypatch):
    class FixedClock(receipt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 12, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(receipt, "datetime", FixedClock)
    make(out, env="mock", argv=PASS)
    with pytest.raises(receipt.ReceiptError, match="already exists"):
        make(out, env="mock", argv=PASS)


def test_unknown_schema_is_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other"}))
    assert receipt.verify_receipt(bad)[0] == [f"schema must be {receipt.SCHEMA}"]
