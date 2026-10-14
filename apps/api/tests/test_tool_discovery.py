"""Optional host tools are found on PATH; a missing tool never breaks settings."""
import os
import stat

import settings


def _make_tool(folder, name):
    path = folder / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_find_tool_prefers_path_entry(tmp_path, monkeypatch):
    tool = _make_tool(tmp_path, "gh")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert settings.find_tool("gh") == str(tool)


def test_find_tool_missing_returns_bare_name(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(settings.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert settings.find_tool("definitely-not-installed-xyz") == "definitely-not-installed-xyz"


def test_settings_build_without_optional_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("MAC_CONTROL_DATA_DIR", str(tmp_path / "data"))
    cfg = settings.Settings()
    for name in ("gh_path", "claude_path", "codex_path", "hermes_path", "openclaw_path", "macmon_path"):
        assert not os.path.isabs(getattr(cfg, name)) or os.path.isfile(getattr(cfg, name))


def test_explicit_path_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("MAC_CONTROL_GH_PATH", "/custom/gh")
    monkeypatch.setenv("MAC_CONTROL_DATA_DIR", str(tmp_path))
    assert settings.Settings().gh_path == "/custom/gh"


def test_search_dirs_have_no_duplicates(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/usr/bin", "/usr/local/bin"]))
    dirs = settings.tool_search_dirs()
    assert len(dirs) == len(set(dirs))
