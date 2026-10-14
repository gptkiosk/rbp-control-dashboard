"""Reject incompatible source before publishing an installable package."""
import importlib.util
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('release_syntax_test', ROOT/'scripts/release/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_builder_compiles_sources_without_executing_them(tmp_path):
    path = tmp_path/'good.py'
    path.write_text("raise RuntimeError('must never execute')\n")
    release.validate_python_sources({'good.py': path}, f'{sys.version_info.major}.{sys.version_info.minor}')


def test_builder_reports_source_file_and_syntax_error(tmp_path):
    path = tmp_path/'bad.py'; path.write_text('def broken(:\n')
    with pytest.raises(release.ReleaseError, match="bad.py:1"):
        release.validate_python_sources({'bad.py': path}, f'{sys.version_info.major}.{sys.version_info.minor}')


@pytest.mark.skipif(sys.version_info[:2] != (3,11), reason='Regression must run on the pinned Pi runtime')
def test_builder_rejects_python312_only_fstring_on_pi_runtime(tmp_path):
    path = tmp_path/'projects.py'
    path.write_text("f'{delegate['agent']}'\n")
    with pytest.raises(release.ReleaseError, match="projects.py:1"):
        release.validate_python_sources({'apps/api/projects.py': path}, '3.11')
