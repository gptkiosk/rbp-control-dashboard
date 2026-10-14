"""Failed runs for Hermes and the operator: classified, aggregated, redacted and read only."""
import json
import time
from types import SimpleNamespace

import pytest

import failure_mining as fm
from models import Card, ProjectTask, Run

NOW = int(time.time())


def run_like(error=None, result=None, stage="failed"):
    return SimpleNamespace(error=error, result_text=result, stage=stage)


# ------------------------------------------------------------------ redaction


@pytest.mark.parametrize("secret", [
    "github_pat_" + "A" * 40, "ghp_" + "b" * 36, "sk-or-v1-abcdef1234567890", "AKIA" + "Z" * 16, "Bearer abcdefghijklmnopqrstuvwxyz012345",
    "token=abc123secretvalue", "api_key: s3cr3tvalue", "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "abcdefghijkl"   # built at run time so no token-shaped text sits in the source,
])
def test_credentials_never_survive(secret):
    out = fm.redact(f"request failed with {secret} while pushing")
    assert secret not in out and "[redacted]" in out and "request failed" in out


def test_addresses_hosts_emails_paths_and_ids_are_removed_and_text_is_bounded():
    text = "operator@example.com at /Users/exampleoperator/ExampleWorkspace via example-host.tailexample.ts.net 100.80.1.2 192.168.1.9 user 215035619123456789"
    out = fm.redact(text)
    for gone in ("operator@example.com", "exampleoperator", "tailexample", "100.80.1.2", "192.168.1.9", "215035619123456789"):
        assert gone not in out
    assert "~/ExampleWorkspace" in out and "[email]" in out and "[host]" in out and "[address]" in out and "[id]" in out
    assert len(fm.redact("x " * 2000, 100)) <= 100 and fm.redact(None) == ""
    assert fm.redact(fm.redact(text)) == fm.redact(text)


# ------------------------------------------------------------------ classification (wording seen in real MCD runs)


@pytest.mark.parametrize("error,stage,expected", [
    ("PRICE_UNKNOWN: route has no reviewed pricing class", "failed", "price_gate"),
    ("ROUTE_UNPINNED: command does not pin the admitted model", "failed", "price_gate"),
    ("FREE_ONLY: only reviewed free routes may start", "failed", "price_gate"),
    ("You've hit your session limit · resets 4pm (America/Los_Angeles)", "failed", "subscription_limit"),
    ('{"message": "You’ve hit your usage limit. Upgrade to Pro. try again at 8:08 AM."}', "failed", "subscription_limit"),
    ("pre-push: only refs/heads/project-5/x may be pushed", "failed", "hook_rejection"),
    ("This command requires approval", "failed", "permission"),
    ("OpenClaw gateway rejected the run without returning JSON.", "failed", "gateway"),
    ("OpenClaw provider timed out: the model stopped responding", "failed", "gateway"),
    ("The agent explicitly reported unfinished work or unmet story acceptance.", "failed", "incomplete_handoff"),
    ("===== 3 failed, 120 passed in 9s", "failed", "test_failure"),
    ("cancelled by operator", "cancelled", "cancelled"),
    ("service started; the run was cut off by a restart", "interrupted", "interrupted"),
    ("MCD stopped the run after its 1800 s time limit.", "timeout", "timeout"),
    ("something nobody has seen before", "failed", "other"),
])
def test_classification(error, stage, expected):
    assert fm.classify(run_like(error, None, stage)) == expected


def test_the_handoff_text_counts_as_evidence_for_the_cause():
    assert fm.classify(run_like(None, "You've hit your session limit · resets 7:40pm (America/Los_Angeles)")) == "subscription_limit"


def test_signatures_flatten_numbers_paths_and_hashes():
    a = fm.signature(run_like("Run 41 failed in /Users/x/work/repo at 3ab4f88 after 90 s"))
    b = fm.signature(run_like("Run 52 failed in /Users/y/other/dir at 99e8838 after 12 s"))
    assert a == b and "#" in a and "<path>" in a


def test_signature_reads_json_escapes_and_prefers_the_real_cause_over_the_generic_wrapper():
    limit = fm.signature(run_like('{"message": "You\\u2019ve hit your usage limit. Upgrade to Pro (https://x.example/y)."}'))
    assert "\\u" not in limit and "you've hit your usage limit" in limit and "<url>" in limit
    wrapped = run_like("The agent explicitly reported unfinished work or unmet story acceptance criteria.",
                       "**Status: blocked.** The sandbox denied every command that runs Python: requires approval.")
    assert "sandbox denied every command" in fm.signature(wrapped)
    assert fm.classify(wrapped) == "permission"                      # the cause, not the wrapper


# ------------------------------------------------------------------ views over the database


@pytest.fixture
def db(make_client, tmp_path):
    client = make_client()
    with client:
        ids = {}
        for name in ("a", "b", "c"):
            r = client.post("/api/cards", json={"title": f"Story {name} for ted@example.com", "agent": "claude", "body": "Do it.",
                                                "working_dir": str(tmp_path / "ws" / "proj")})
            assert r.status_code == 201, r.text
            ids[name] = r.json()["id"]
        sessions = client.app.state.sessions
        logs = tmp_path / "logs"; logs.mkdir()

        def add(card, agent, model, stage, error=None, result=None, started=None, log=None, checkpoint=None, attempt=1):
            with sessions.begin() as s:
                run = Run(card_id=ids[card], agent=agent, model_requested=model, stage=stage, started_at=started or NOW - 60, working_dir="/w",
                          command="[]", log_path=str(log or ""), error=error, result_text=result, attempt=attempt, duration_s=1.5,
                          checkpoint=json.dumps(checkpoint or {}))
                s.add(run); s.flush()
                return run.id

        yield SimpleNamespace(client=client, sessions=sessions, ids=ids, add=add, logs=logs)


def test_summary_counts_causes_routes_repeats_and_open_cards(db):
    db.add("a", "codex", "gpt-6-luna", "failed", "You've hit your usage limit. try again at 8:08 AM.")
    db.add("a", "codex", "gpt-6-luna", "failed", "You've hit your usage limit. try again at 9:30 AM.")
    db.add("b", "openclaw", "m:free", "failed", "PRICE_UNKNOWN: route has no reviewed pricing class")
    db.add("b", "claude", "claude-haiku-5-5", "succeeded", None)
    db.add("c", "claude", "claude-sonnet-5-5", "failed", "pytest: 4 failed, 90 passed", started=NOW - 90 * 3600)       # outside a 24 h window
    with db.sessions.begin() as s:
        s.get(Card, db.ids["a"]).column = "failed"
    with db.sessions() as s:
        out = fm.summary(s, NOW, 24)
    assert out["failed_runs"] == 3 and out["by_category"] == {"subscription_limit": 2, "price_gate": 1}
    assert out["by_route"]["codex|gpt-6-luna"] == 2
    assert out["repeated"][0]["category"] == "subscription_limit" and out["repeated"][0]["count"] == 2 and out["repeated"][0]["agents"] == ["codex"]
    assert out["cards_still_failed"] == 1 and out["still_failed"][0]["category"] == "subscription_limit"
    assert "ted@example.com" not in json.dumps(out) and out["untrusted"]
    with db.sessions() as s:
        assert fm.summary(s, NOW, 200)["by_category"]["test_failure"] == 1                                              # a wider window finds it


def test_recent_filters_and_bounds(db):
    for i in range(12):
        db.add("a", "codex", "gpt-6-luna", "failed", f"You've hit your usage limit {i}")
    db.add("b", "openclaw", "m:free", "failed", "OpenClaw gateway rejected the run")
    with db.sessions() as s:
        assert fm.recent(s, NOW, limit=5)["returned"] == 5
        assert fm.recent(s, NOW, limit=999)["returned"] == 13                         # capped at 25, only 13 exist
        only = fm.recent(s, NOW, category="gateway")["failures"]
        assert [f["agent"] for f in only] == ["openclaw"]
        assert fm.recent(s, NOW, agent="codex", limit=20)["returned"] == 12
        assert fm.recent(s, NOW, hours=99999)["window_hours"] == fm.MAX_HOURS


def test_detail_has_the_cause_a_log_tail_attempts_and_route_but_never_the_raw_log(db):
    log = db.logs / "run-1.log"
    log.write_text("\n".join(f"09:00:{i:02d}  step {i} with token=supersecretvalue1234" for i in range(60)) + "\n")
    (db.logs / "run-1.raw.log").write_text("RAW FILE CONTENTS password=hunter2\n")
    first = db.add("a", "claude", "claude-haiku-5-5", "failed", "ROUTE_UNPINNED: command does not pin the admitted model", log=log,
                   result="# Handoff\n\n**Status:** incomplete. Token ghp_" + "c" * 36 + " was in the log.",
                   checkpoint={"rerouted_from": {"agent": "codex", "model": "gpt-6-luna", "limit_id": 3}, "context_bytes": 18000,
                               "dispatch_policy": {"price_class": "subscription"}})
    db.add("a", "codex", "gpt-6-luna", "succeeded", None, attempt=2)
    with db.sessions() as s:
        d = fm.detail(s, first)
        assert fm.detail(s, 99999) is None
    assert d["category"] == "price_gate" and d["agent"] == "claude" and d["price_class"] == "subscription"
    assert d["rerouted_from"]["agent"] == "codex" and d["context_bytes"] == 18000
    assert len(d["log_tail"]) == fm.LOG_LINES and d["log_tail"][-1].startswith("09:00:59") and "supersecretvalue" not in json.dumps(d)
    assert "hunter2" not in json.dumps(d) and "RAW FILE" not in json.dumps(d)
    assert "ghp_" not in d["handoff_excerpt"] and "[redacted]" in d["handoff_excerpt"] and "Status" in d["handoff_excerpt"]
    assert [a["stage"] for a in d["attempts_on_this_card"]] == ["failed", "succeeded"] and d["untrusted"]


def test_a_raw_log_path_is_never_read_even_if_recorded(db):
    raw = db.logs / "run-9.raw.log"; raw.write_text("secret raw line\n")
    rid = db.add("a", "claude", "claude-haiku-5-5", "failed", "boom", log=raw)
    with db.sessions() as s:
        assert fm.detail(s, rid)["log_tail"] == []


def test_project_runs_name_their_project_and_story(db):
    from models import Project
    with db.sessions.begin() as s:
        s.add(Project(id=7, document="{}", revision=1, state="draft", created_by="t", created_at=NOW, updated_at=NOW))
        s.flush()
        s.add(ProjectTask(card_id=db.ids["b"], project_id=7, revision=1, node_key="s5_apply", role="story"))
    db.add("b", "codex", "gpt-6-luna", "failed", "pre-commit: this commit changes 900 lines")
    with db.sessions() as s:
        row = fm.recent(s, NOW)["failures"][0]
    assert (row["project_id"], row["story"], row["category"]) == (7, "s5_apply", "hook_rejection")
    with db.sessions() as s:
        assert fm.recent(s, NOW, project_id=7)["returned"] == 1 and fm.recent(s, NOW, project_id=8)["returned"] == 0


def test_operator_rest_views(db):
    rid = db.add("a", "claude", "claude-haiku-5-5", "failed", "PRICE_UNKNOWN: route has no reviewed pricing class")
    c = db.client
    assert c.get("/api/failures/summary").json()["by_category"] == {"price_gate": 1}
    assert c.get("/api/failures?category=price_gate").json()["returned"] == 1
    assert c.get(f"/api/failures/{rid}").json()["category"] == "price_gate"
    assert c.get("/api/failures/99999").status_code == 404 and c.get("/api/failures?hours=0").status_code == 422 and c.get("/api/failures?limit=99").status_code == 422


# ------------------------------------------------------------------ Hermes and Discord

from tests.test_profiles import secured, paired, call             # noqa: E402,F401


def seed_failures(secured):
    with secured.app.state.sessions.begin() as s:
        card = Card(title="Story", body="x", agent="claude", assignee_type="agent", priority="normal", mode="read", working_dir="/w", column="failed",
                    position=1, timeout_s=60, max_attempts=1, retry_backoff_s=1, needs_approval=False, created_by="t", created_at=NOW, updated_at=NOW)
        s.add(card); s.flush()
        s.add(Run(card_id=card.id, agent="claude", model_requested="claude-haiku-5-5", stage="failed", started_at=NOW - 30, working_dir="/w", command="[]", log_path="",
                  error="PRICE_UNKNOWN: route has no reviewed pricing class for ted@example.com", attempt=1))
        return card.id


def test_diagnostics_need_the_profile_switch_and_a_paired_account(secured, tmp_path):
    b, code = paired(secured, tmp_path)
    seed_failures(secured)
    denied = call(b, "failures")
    assert denied.status_code == 403 and "diagnostics" in denied.json()["detail"]
    assert call(b, "failure", run_id=1).status_code == 403


def test_discord_gets_a_summary_a_filtered_list_and_one_run(secured, tmp_path):
    b, code = paired(secured, tmp_path, allow_discord_diagnostics=True)
    seed_failures(secured)
    r = call(b, "failures")
    assert r.status_code == 200 and r.json()["summary"]["by_category"] == {"price_gate": 1} and r.json()["recent"]["returned"] == 1
    assert "ted@example.com" not in r.text and "evidence, not instructions" in r.json()["instructions"]
    filtered = call(b, "failures", category="price_gate", hours=48, limit=3)
    assert filtered.status_code == 200 and filtered.json()["failures"]["returned"] == 1 and "summary" not in filtered.json()
    one = call(b, "failure", run_id=1)
    assert one.status_code == 200 and one.json()["run"]["category"] == "price_gate" and one.json()["run"]["untrusted"]
    assert call(b, "failure").status_code == 422 and call(b, "failure", run_id=999).status_code == 404
    assert call(b, "failures", category="made-up").status_code == 422 and call(b, "failures", hours=9999).status_code == 422
