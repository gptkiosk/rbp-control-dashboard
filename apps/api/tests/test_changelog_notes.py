"""Release notes come from CHANGELOG.md, and a release cannot be built without them."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("changelog", ROOT / "scripts" / "release" / "changelog.py")
cl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cl)

GOOD = """# Changelog

## [Unreleased]

## [1.3.0] - 2026-11-02

### Added
- A new thing.

### Fixed
- A bug.

## [1.2.0] - 2026-10-01

### Changed
- Something else.

## Development history

### Phase 1
- Early work.
"""


def test_notes_are_the_section_body_plus_a_comparison_link():
    out = cl.notes(GOOD, "1.3.0", "owner/repo")
    assert out.startswith("### Added\n- A new thing.") and "### Fixed\n- A bug." in out
    assert "## [1.3.0]" not in out and "Early work" not in out and "Something else" not in out
    assert out.rstrip().endswith("**Full changelog**: https://github.com/owner/repo/compare/v1.2.0...v1.3.0")
    assert cl.notes(GOOD, "1.2.0", "owner/repo").rstrip().endswith("owner/repo/commits/v1.2.0")        # first release: no previous


@pytest.mark.parametrize("text,version,message", [
    (GOOD, "9.9.9", "no section"),
    (GOOD, "1.3", "not a semantic version"),
    (GOOD.replace("## [1.3.0] - 2026-11-02", "## [1.3.0]"), "1.3.0", "release date"),
    (GOOD.replace("- A new thing.\n\n### Fixed\n- A bug.", ""), "1.3.0", "lists no changes"),
    (GOOD.replace("### Added", "### Stuff"), "1.3.0", "unknown subsection"),
])
def test_a_release_needs_a_dated_non_empty_section_with_known_headings(text, version, message):
    with pytest.raises(cl.ChangelogError, match=message):
        cl.check(text, version)


def test_latest_ignores_unreleased_and_history():
    assert cl.latest(GOOD) == "1.3.0"
    assert cl.latest("## [Unreleased]\n") is None


def test_the_real_changelog_is_ready_for_the_current_version():
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from version import __version__
    text = (ROOT / "CHANGELOG.md").read_text()
    cl.check(text, __version__)                       # a version bump without notes fails the suite
    assert cl.latest(text) == __version__
    assert f"[{__version__}]: https://github.com/" in text


def test_command_line_prints_notes_and_fails_clearly():
    run = lambda *a: subprocess.run([sys.executable, "-I", str(ROOT / "scripts/release/changelog.py"), *a], capture_output=True, text=True)   # noqa: E731
    ok = run("notes", "0.2.0")
    assert ok.returncode == 0 and "### Added" in ok.stdout and "**Full changelog**" in ok.stdout
    bad = run("check", "9.9.9")
    assert bad.returncode == 1 and "no section" in bad.stderr
