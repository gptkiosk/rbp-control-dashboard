from __future__ import annotations

import services_probe as sp

LIST = "PID\tStatus\tLabel\n96121\t0\tai.hermes.gateway\n-\t0\tcom.apple.something\n-\t2\tcom.openclaw.backup\n"

PRINT = """gui/501/ai.hermes.gateway = {
\tactive count = 1
\tpath = /Users/x/Library/LaunchAgents/ai.hermes.gateway.plist
\tstate = running
\tprogram = /usr/bin/python3
\tenvironment = {
\t\tstate = nested-should-be-ignored
\t}
\truns = 238293
\tpid = 96121
\tlast exit code = 2
}
"""


def test_list_filters_by_prefix_and_skips_header():
    assert sp.parse_launchctl_list(LIST, sp.DEFAULT_PREFIXES) == ["ai.hermes.gateway", "com.openclaw.backup"]


def test_print_reads_top_level_only():
    f = sp.parse_launchctl_print(PRINT)
    assert f["state"] == "running"
    assert f["runs"] == 238293
    assert f["pid"] == 96121
    assert f["last_exit"] == "2"


def test_exit_code_variants():
    assert sp.exit_code("0") == 0
    assert sp.exit_code("-15") == -15
    assert sp.exit_code("78: EX_CONFIG") == 78
    assert sp.exit_code("(never exited)") is None
    assert sp.exit_code(None) is None


def test_runs_in_window_handles_counter_reset():
    assert sp.runs_in_window(120, 20) == 100
    assert sp.runs_in_window(3, 900) == 3  # reloaded, counter restarted
    assert sp.runs_in_window(5, None) == 5
    assert sp.runs_in_window(None, 1) is None


def test_crash_loop_threshold_is_strictly_above_50():
    assert sp.assess("0", 50) == []
    assert sp.assess("0", 51) == ["crash_loop"]


def test_nonzero_and_signal_exits_are_warnings():
    assert sp.assess("2", 1) == ["last_exit_nonzero"]
    assert sp.assess("-15", 1) == ["last_exit_nonzero"]
    assert sp.assess("(never exited)", 1) == []


INTERVAL_PRINT = "gui/501/com.openclaw.health-check = {\n\tstate = not running\n\truns = 7099\n\tlast exit code = 0\n\trun interval = 300 seconds\n}\n"
CALENDAR_PRINT = ("gui/501/com.openclaw.backup = {\n\tstate = not running\n\truns = 25\n\tlast exit code = 0\n"
                  "\tevent triggers = {\n\t\t\"com.apple.launchd.calendarinterval\" = {\n\t\t}\n\t}\n}\n")


def test_print_reads_schedule():
    f = sp.parse_launchctl_print(INTERVAL_PRINT)
    assert f["run_interval_s"] == 300 and f["calendar"] is False
    g = sp.parse_launchctl_print(CALENDAR_PRINT)
    assert g["run_interval_s"] is None and g["calendar"] is True


def test_five_minute_job_is_not_a_crash_loop():
    # health-check on this Mac: every 300 s, 288 runs a day.
    assert sp.assess("0", 288, run_interval_s=300) == []
    assert sp.allowed_runs_24h(300, False) == 395


def test_interval_job_far_beyond_schedule_is_a_crash_loop():
    assert sp.assess("0", 1000, run_interval_s=300) == ["crash_loop"]


def test_calendar_job_allowance():
    assert sp.assess("0", 24, calendar=True) == []
    assert sp.assess("0", 201, calendar=True) == ["crash_loop"]


def test_schedule_labels():
    assert sp.schedule_label(300, False) == "every 5 min"
    assert sp.schedule_label(45, False) == "every 45 s"
    assert sp.schedule_label(None, True) == "calendar"
    assert sp.schedule_label(None, False) == "on demand / keep alive"


SYSTEMD_LIST = "ai.hermes.gateway.service loaded active running Hermes\nssh.service loaded active running SSH\n"
SYSTEMD_SHOW = """Id=ai.hermes.gateway.service
ActiveState=failed
MainPID=0
NRestarts=58
ExecMainStatus=2
FragmentPath=/home/pi/.config/systemd/user/ai.hermes.gateway.service
ExecStart={ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /opt/rcd/worker.py ; }
"""


def test_systemctl_parsers_map_user_services_to_existing_snapshot_shape():
    assert sp.parse_systemctl_list(SYSTEMD_LIST, ("ai.hermes.",)) == ["ai.hermes.gateway.service"]
    row = sp.parse_systemctl_show(SYSTEMD_SHOW)
    assert row["state"] == "failed"
    assert row["pid"] is None
    assert row["runs"] == 58
    assert row["last_exit"] == "2"
    assert row["path"].endswith(".service")
