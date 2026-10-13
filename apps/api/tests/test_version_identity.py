"""A release package has no .git; it names its source commit in BUILD_INFO.json, and the footer must show it."""
import json
import shutil
import subprocess

import pytest

import version


def _fresh(monkeypatch, root):
    version.git_sha.cache_clear()
    version.git_dirty.cache_clear()
    # Make the module believe it lives in `root`, and make git unusable there like on a packaged install.
    monkeypatch.setattr(version.Path, "resolve", lambda self, *a, **k: root / "apps" / "api" / "version.py")
    real_run = subprocess.run
    monkeypatch.setattr(version.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    return real_run


def test_an_installed_package_reports_its_recorded_source_commit(tmp_path, monkeypatch):
    (tmp_path / "BUILD_INFO.json").write_text(json.dumps({"source_commit": "e3353ea75f02fff2fd50a33c9fbd0e3b09d348b7",
                                                          "source_dirty": False}))
    _fresh(monkeypatch, tmp_path)
    try:
        assert version.git_sha() == "e3353ea" and version.git_dirty() is False
    finally:
        version.git_sha.cache_clear(); version.git_dirty.cache_clear()


def test_without_git_or_build_info_the_commit_is_unknown(tmp_path, monkeypatch):
    _fresh(monkeypatch, tmp_path)
    try:
        assert version.git_sha() == "unknown" and version.git_dirty() is False
    finally:
        version.git_sha.cache_clear(); version.git_dirty.cache_clear()
