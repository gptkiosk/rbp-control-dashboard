"""enable-signed-updates: an explicit, fingerprint-confirmed switch from a pasted digest to the release signature,
and the trust the status route reports so the panel can drop the digest box."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import update_engine as ue
import update_helper
from tests.test_release_verify import SSH_KEYGEN
from tests.test_update_engine import cfg, config_file, this_host  # noqa: F401

pytestmark = pytest.mark.skipif(SSH_KEYGEN is None, reason="system ssh-keygen is not installed")


def make_key(tmp_path: Path, name="rel") -> tuple[Path, str, str]:
    key = tmp_path / name
    subprocess.run([SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", "x", "-f", str(key)], check=True, capture_output=True)
    kind, data = (tmp_path / f"{name}.pub").read_text().split()[:2]
    fingerprint = subprocess.run([SSH_KEYGEN, "-lf", str(tmp_path / f"{name}.pub")], capture_output=True, text=True, check=True).stdout.split()[1]
    return key, f"{kind} {data}", fingerprint


def signers(tmp_path: Path, public: str, *, options='namespaces="dashboard-release"', name="allowed_signers") -> Path:
    path = tmp_path / name
    path.write_text(f"dashboard-release {options} {public}\n".replace("  ", " "))
    return path


@pytest.fixture
def helper(tmp_path, cfg):  # noqa: F811
    path = config_file(tmp_path, cfg)
    (cfg.root / "helper").mkdir(exist_ok=True, mode=0o700)
    target = cfg.root / "helper" / "helper.json"
    target.write_text(path.read_text()); target.chmod(0o600)
    return target


def test_the_fingerprint_names_the_key_and_the_switch_rewrites_trust_atomically(tmp_path, cfg, helper):  # noqa: F811
    _, public, fingerprint = make_key(tmp_path)
    source = signers(tmp_path, public)
    result = ue.enable_signed_updates(helper, cfg, source, fingerprint)
    assert result["trust"] == "ssh-signature" and result["fingerprint"] == fingerprint
    reloaded = ue.load_config(helper)
    assert reloaded.trust == {"kind": "ssh-signature", "allowed_signers": str(helper.parent / "allowed_signers"), "identity": "dashboard-release"}
    copy = helper.parent / "allowed_signers"
    assert copy.read_text() == source.read_text() and oct(copy.stat().st_mode & 0o777) == "0o600" and oct(helper.stat().st_mode & 0o777) == "0o600"


def test_a_wrong_fingerprint_or_a_different_key_changes_nothing(tmp_path, cfg, helper):  # noqa: F811
    _, public, fingerprint = make_key(tmp_path)
    _, _, other = make_key(tmp_path, "other")
    before = helper.read_text()
    with pytest.raises(ue.UpdateError, match="not " + other.replace("+", r"\+").replace("/", "/")):
        ue.enable_signed_updates(helper, cfg, signers(tmp_path, public), other)
    with pytest.raises(ue.UpdateError, match="SHA256:<43 characters>"):
        ue.enable_signed_updates(helper, cfg, signers(tmp_path, public), "SHA256:short")
    assert helper.read_text() == before and not (helper.parent / "allowed_signers").exists()


@pytest.mark.parametrize("body", [
    "", "# only a comment\n",
    "dashboard-release ssh-ed25519 AAAA\n",                                       # no namespace limit
    'dashboard-release namespaces="file" ssh-ed25519 AAAA\n',                      # the wrong namespace
    'dashboard-release namespaces="dashboard-release"\n',                          # no key
])
def test_an_allowed_signers_file_that_is_not_one_release_signer_is_refused(tmp_path, cfg, helper, body):  # noqa: F811
    _, _, fingerprint = make_key(tmp_path)
    path = tmp_path / "bad"; path.write_text(body)
    with pytest.raises(ue.UpdateError):
        ue.enable_signed_updates(helper, cfg, path, fingerprint)
    assert json.loads(helper.read_text())["trust"] == {"kind": "pinned-digest"}


def test_two_keys_are_refused_so_a_second_signer_cannot_ride_along(tmp_path, cfg, helper):  # noqa: F811
    _, public, fingerprint = make_key(tmp_path)
    _, second, _ = make_key(tmp_path, "second")
    path = tmp_path / "two"
    path.write_text(f'dashboard-release namespaces="dashboard-release" {public}\ndashboard-release namespaces="dashboard-release" {second}\n')
    with pytest.raises(ue.UpdateError, match="not " ):
        ue.enable_signed_updates(helper, cfg, path, fingerprint)


def test_nothing_is_switched_while_an_update_is_in_progress(tmp_path, cfg, helper, monkeypatch):  # noqa: F811
    _, public, fingerprint = make_key(tmp_path)
    monkeypatch.setattr(ue, "load_state", lambda c: {"tx": {"id": "x"}, "last": None})
    with pytest.raises(ue.UpdateError, match="interrupted"):
        ue.enable_signed_updates(helper, cfg, signers(tmp_path, public), fingerprint)
    assert json.loads(helper.read_text())["trust"] == {"kind": "pinned-digest"}


def test_the_helper_cli_prints_one_json_result_and_defaults_to_the_current_versions_key(tmp_path, cfg, helper, capsys):  # noqa: F811
    _, public, fingerprint = make_key(tmp_path)
    source = signers(tmp_path, public)
    assert update_helper.main(["--config", str(helper), "enable-signed-updates", "--fingerprint", fingerprint, "--allowed-signers", str(source)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["trust"] == "ssh-signature"
    assert update_helper.main(["--config", str(helper), "enable-signed-updates", "--fingerprint", "SHA256:" + "A" * 43]) == 1   # no current version to read a key from
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_the_status_route_reports_which_trust_the_host_uses(tmp_path, monkeypatch, make_client, cfg):  # noqa: F811
    import shutil
    from routes import updates as routes
    helper_dir = cfg.root / "helper"; helper_dir.mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(config_file(tmp_path, cfg), helper_dir / "helper.json"); (helper_dir / "helper.json").chmod(0o600)
    monkeypatch.setenv("MAC_CONTROL_UPDATE_ROOT", str(cfg.root))
    monkeypatch.setattr(ue, "install_kind", lambda app_root, root: ("release", "packaged"))
    client = make_client()

    @client.app.middleware("http")
    async def session(request, call_next):
        request.state.user = {"email": "operator@example.invalid"}
        return await call_next(request)

    assert client.get("/api/app-updates").json()["trust"] == "pinned-digest"
    _, public, fingerprint = make_key(tmp_path)
    ue.enable_signed_updates(helper_dir / "helper.json", cfg, signers(tmp_path, public), fingerprint)
    assert client.get("/api/app-updates").json()["trust"] == "ssh-signature"


# ---------------------------------------------------------------------------- what ships

REPO = Path(__file__).resolve().parents[3]


def test_the_bootstrap_names_the_fingerprint_of_the_key_the_package_ships():
    text = (REPO / "scripts" / "install" / "bootstrap-rcd.sh").read_text()
    pinned = next(line.split('"')[1] for line in text.splitlines() if line.startswith("RELEASE_KEY_FINGERPRINT="))
    shipped = (REPO / "packaging" / "allowed_signers").read_bytes()
    assert ue.signer_fingerprints(shipped) == [pinned]


def test_the_release_key_is_packaged_and_the_package_content_scan_accepts_it():
    import importlib.util
    patterns = json.loads((REPO / "packaging" / "product.json").read_text())["include"]
    assert "packaging/allowed_signers" in patterns
    spec = importlib.util.spec_from_file_location("release_scan_under_test", REPO / "scripts" / "release" / "release.py")
    release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)
    files = {}
    for pattern in patterns:
        for path in sorted(REPO.glob(pattern)):
            if path.is_file():
                files[str(path.relative_to(REPO))] = path.read_bytes()
    assert release.scan_contents(files, []) == []
