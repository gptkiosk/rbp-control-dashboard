import importlib.util
import json
from pathlib import Path
import stat

import pytest
from dotenv import dotenv_values

spec = importlib.util.spec_from_file_location("auth_import", Path(__file__).resolve().parents[3] / "scripts/configure-google-auth.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_import_preserves_settings_and_privately_backs_up(tmp_path):
    source = tmp_path / "client.json"
    secret = "quote'and$literal"
    source.write_text(json.dumps({"web": {"client_id": "test.apps.googleusercontent.com", "client_secret": secret,
        "redirect_uris": [origin + "/auth/callback" for origin in (module.LOCAL, "https://example-device.example.ts.net:9443")]}}))
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text("KEEP_ME='previous-secret'\nMAC_CONTROL_AUTH_ENABLED='false'\n")
    assert module.configure(source, data, True, ["operator@example.com"]) == [module.LOCAL, "https://example-device.example.ts.net:9443"]
    values = dotenv_values(data / ".env")
    assert values["KEEP_ME"] == "previous-secret"
    assert values["MAC_CONTROL_GOOGLE_CLIENT_SECRET"] == secret
    assert values["MAC_CONTROL_AUTH_ENABLED"] == "true"
    assert "operator@example.com" in json.loads(values["MAC_CONTROL_AUTH_ALLOWED_EMAILS"])
    backup = next(data.glob(".env.before-google-auth-*"))
    assert "previous-secret" in backup.read_text()
    for path in (source, data / ".env", backup):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("kind", ["installed", "missing-callback", "symlink"])
def test_invalid_import_leaves_existing_configuration(tmp_path, kind):
    source = tmp_path / "client.json"
    web = {"client_id": "test.apps.googleusercontent.com", "client_secret": "private", "redirect_uris": []}
    source.write_text(json.dumps({"installed" if kind == "installed" else "web": web}))
    if kind == "symlink":
        original = source.rename(tmp_path / "original.json")
        source.symlink_to(original)
    data = tmp_path / "data"
    data.mkdir()
    env = data / ".env"
    env.write_text("KEEP_ME=unchanged\n")
    with pytest.raises(Exception):
        module.configure(source, data, True)
    assert env.read_text() == "KEEP_ME=unchanged\n"
