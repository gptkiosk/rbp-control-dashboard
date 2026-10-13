"""The systemd unit template and installer stay consistent with the update helper and probe."""

from __future__ import annotations

import re
from pathlib import Path

import services_probe

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = (ROOT / "ops/systemd/rcd-api.service.template").read_text()
INSTALLER = (ROOT / "scripts/install-systemd-user.sh").read_text()


def test_template_placeholders_are_all_rendered_by_the_installer():
    placeholders = set(re.findall(r"__[A-Z_]+__", TEMPLATE))
    assert placeholders
    for name in placeholders:
        assert f"s|{name}|" in INSTALLER, name


def test_template_restarts_only_after_failure_and_holds_no_secret():
    assert "Restart=on-failure" in TEMPLATE
    assert "WantedBy=default.target" in TEMPLATE
    assert not re.search(r"SECRET|TOKEN|PASSWORD|KEY=", TEMPLATE, re.I)


def test_unit_name_is_the_one_the_update_helper_and_probe_use():
    assert 'RCD_SYSTEMD_UNIT:-rcd-api' in INSTALLER
    assert services_probe.parse_systemctl_list(
        "rcd-api.service loaded active running RCD\n", ("rcd-",)) == ["rcd-api.service"]


def test_installer_refuses_values_that_would_alter_the_unit():
    for fragment in ("*%*", r"*$'\n'*", "*'|'*", "uname -s"):
        assert fragment in INSTALLER
