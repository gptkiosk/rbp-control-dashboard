import json
import time

from ops_collectors import OpsCollectors, load_config
from settings import Settings

DAY = 86400
MONDAY_0600 = 144 * DAY + 6 * 3600  # 1970-01-01 was a Thursday, so day 144 is a Monday
MEMORY = {"id": "mem", "kind": "memory", "warn_pct": 100, "crit_pct": 100}


def build(tmp_path, sessions, sources, clock=None, **extra):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "ops-collectors.json").write_text(json.dumps({"sources": sources, **extra}))
    settings = Settings(_env_file=None, data_dir=data)
    return OpsCollectors(settings, sessions, lambda: data / "reports", clock or time.time), data


def reports(data):
    folder = data / "reports" / "fleet-health"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_replacement_schedules_are_created_disabled(tmp_path, sessions):
    runner, data = build(tmp_path, sessions, [MEMORY])
    status = runner.status()
    assert [s["id"] for s in status["schedules"]] == ["morning-health", "evening-review", "weekly-maintenance"]
    assert not any(s["enabled"] for s in status["schedules"]) and all(s["next_due"] is None for s in status["schedules"])
    assert runner.run_due() == [] and reports(data) == []
    config, _ = load_config(tmp_path / "nowhere")
    assert not any(s["enabled"] for s in config["schedules"])
    (data / "ops-collectors.json").write_text(json.dumps({"sources": [MEMORY], "schedules": [{"id": "x", "every_s": 600}]}))
    assert load_config(data)[0]["schedules"][0]["enabled"] is False  # omitted means disabled


def test_schedule_validation(tmp_path):
    data = tmp_path / "data"
    data.mkdir()

    def attempt(*schedules, **extra):
        (data / "ops-collectors.json").write_text(json.dumps({"sources": [MEMORY], "schedules": list(schedules), **extra}))
        return load_config(data)[1]

    assert attempt({"id": "a", "at": "07:00", "every_s": 600})
    assert attempt({"id": "a"})
    assert attempt({"id": "a", "at": "24:00"})
    assert attempt({"id": "a", "at": "07:00", "weekday": 7})
    assert attempt({"id": "a", "every_s": 10})
    assert attempt({"id": "a", "every_s": 600, "weekday": 1})
    assert attempt({"id": "a", "at": "07:00", "enabled": "yes"})
    assert attempt({"id": "a", "at": "07:00", "sources": ["nope"]})
    assert attempt({"id": "a", "at": "07:00", "shell": "ls"})
    assert attempt({"id": "a", "at": "07:00"}, {"id": "a", "at": "08:00"})
    assert attempt(*[{"id": f"s{n}", "at": "07:00"} for n in range(13)])
    assert attempt({"id": "a", "at": "07:00"}, retention={"max_archive_bytes": -1})
    assert attempt({"id": "a", "at": "07:00", "weekday": 0, "sources": ["mem"], "enabled": True}) is None


def test_fixed_time_schedule_waits_for_its_slot_and_runs_once(tmp_path, sessions):
    now = [3 * DAY + 5 * 3600]  # 05:00 UTC, before the 07:00 slot
    runner, _ = build(tmp_path, sessions, [MEMORY], clock=lambda: now[0],
                      schedules=[{"id": "am", "enabled": True, "at": "07:00"}, {"id": "off", "at": "07:00"}])
    assert runner.run_due() == []  # armed; yesterday's slot is not caught up
    now[0] = 3 * DAY + 7 * 3600 + 5
    assert runner.run_due() == ["am"]
    assert runner.status()["last_run"]["schedule"] == "am"
    now[0] += 3600
    assert runner.run_due() == []  # already ran for this slot
    now[0] = 6 * DAY + 9 * 3600  # three slots were missed: one run, not three
    assert runner.run_due() == ["am"]
    assert runner.status()["schedules"][0]["next_due"] == 7 * DAY + 7 * 3600


def test_weekly_and_interval_schedules(tmp_path, sessions):
    now = [MONDAY_0600 - 60]
    runner, _ = build(tmp_path, sessions, [MEMORY], clock=lambda: now[0], cache_ttl_s=0,
                      schedules=[{"id": "wk", "enabled": True, "at": "06:00", "weekday": 0},
                                 {"id": "tick", "enabled": True, "every_s": 600}])
    assert runner.run_due() == ["tick"]  # an interval schedule starts at once, the weekly one waits
    now[0] = MONDAY_0600 + 700
    assert runner.run_due() == ["wk", "tick"]
    now[0] += 3 * DAY
    assert runner.run_due() == ["tick"]
    now[0] += 4 * DAY
    assert "wk" in runner.run_due()


def test_scheduled_report_carries_its_label(tmp_path, sessions):
    runner, data = build(tmp_path, sessions, [{"id": "gone", "kind": "file_age", "path": str(tmp_path / "none")}],
                         clock=lambda: DAY,
                         schedules=[{"id": "am", "label": "Morning check", "enabled": True, "every_s": 600}])
    assert runner.run_due() == ["am"]
    assert "(Morning check)" in (data / "reports" / "fleet-health" / reports(data)[0]).read_text()


def test_archive_labels_copies_and_never_touches_originals(tmp_path, sessions):
    ops, hermes = tmp_path / "data" / "reports", tmp_path / "hermes"
    (ops / "fleet-health").mkdir(parents=True)
    (hermes / "job").mkdir(parents=True)
    (ops / "old.md").write_text("old ops report")
    (ops / "fleet-health" / "20260101-000000.md").write_text("new collector report")
    (hermes / "job" / "run1.md").write_text("# Cron Job: Morning Fleet Health Check\n")
    (hermes / "link.md").symlink_to(ops / "old.md")
    (ops / "big.md").write_bytes(b"x" * (512 * 1024 + 1))
    runner, _ = build(tmp_path, sessions, [MEMORY])
    runner.hermes_root_provider = lambda: hermes
    originals = [ops / "old.md", hermes / "job" / "run1.md"]
    before = [p.read_bytes() for p in originals]
    first = runner.archive_historic()
    folder = ops / "historic-archive"
    assert first["archived"] == 2 and first["left_in_place"] == ["ops:big.md"]
    assert (folder / "ops--old.md").read_text() == "old ops report"
    assert (folder / "hermes--job__run1.md").exists()
    assert not (folder / "ops--fleet-health__20260101-000000.md").exists()
    assert not (folder / "hermes--link.md").exists()
    label = json.loads((folder / "LABEL.json").read_text())
    assert label["files"]["ops:old.md"]["label"] == "historic" and "Historic" in (folder / "ARCHIVE-LABEL.md").read_text()
    assert [p.read_bytes() for p in originals] == before
    assert sorted(p.name for p in hermes.iterdir()) == ["job", "link.md"]
    again = runner.archive_historic()
    assert again["archived"] == 0 and again["already"] == 2  # idempotent
    assert runner.status()["archive"]["already"] == 2


def test_archive_size_limit(tmp_path, sessions):
    runner, data = build(tmp_path, sessions, [MEMORY], retention={"max_archive_bytes": 10})
    (data / "reports").mkdir()
    (data / "reports" / "a.md").write_text("x" * 8)
    (data / "reports" / "b.md").write_text("y" * 8)
    result = runner.archive_historic()
    assert result["archived"] == 1 and result["left_in_place"] == ["ops:b.md"]
