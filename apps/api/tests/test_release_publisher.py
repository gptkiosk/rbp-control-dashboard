import os,subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
PUBLISH=Path(__file__).resolve().parents[3]/"scripts/release/publish-release.sh"
CHANGELOG=Path(__file__).resolve().parents[3]/"scripts/release/changelog.py"
def git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()

def commit_version(repo, version, lock="a==1\n", changelog=True, tag=None):
    (repo / "apps/api").mkdir(parents=True, exist_ok=True)
    (repo / "apps/web").mkdir(parents=True, exist_ok=True)
    (repo / "apps/web/package-lock.json").write_text("{}\n")
    (repo / "apps/api/version.py").write_text(f'__version__ = "{version}"\n')
    (repo / "apps/api/requirements.lock.txt").write_text(lock)
    (repo / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{version}] - 2026-10-13\n\n### Added\n- thing\n" if changelog else "# Changelog\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", f"chore: {version}")
    if tag:
        git(repo, "tag", tag)

@pytest.fixture
def release_repo(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); git(repo, "init", "-q", "-b", "main")
    (repo / "scripts/release").mkdir(parents=True)
    (repo / "scripts/release/changelog.py").write_text(CHANGELOG.read_text())
    (repo / "scripts/release/publish-release.sh").write_text(PUBLISH.read_text())
    (repo / "packaging").mkdir(); (repo / "packaging/product.json").write_text('{"repository": "owner/product"}')
    commit_version(repo, "1.1.0")
    commit_version(repo, "1.2.0")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [1.2.0] - 2026-10-13\n\n### Added\n- thing two\n\n## [1.1.0] - 2026-10-01\n\n### Added\n- thing one\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "docs: changelog")
    calls = tmp_path / "gh-calls"; state = tmp_path / "gh-state"
    gh = tmp_path / "gh"
    gh.write_text(f'''#!/bin/bash
echo "$@" >> "{calls}"
case "$1 $2" in
  "api repos/owner/product/commits/"*) [ -f "{state}/not-pushed" ] && exit 1; echo "${{3##*/}}"; exit 0;;
  "api repos/owner/product/git/ref/tags/"*) [ -f "{state}/tag-exists" ] && exit 0; exit 1;;
  "secret list") [ -f "{state}/has-secret" ] && printf 'RELEASE_SSH_PRIVATE_KEY\\t2026-10-13\\n'; exit 0;;
  "release view") exit 1;;
  "release create") echo "created"; exit 0;;
esac
exit 0
''')
    gh.chmod(0o755); state.mkdir()
    leaks = tmp_path / "gitleaks"                      # stands in for gitleaks so the test needs no install
    leaks.write_text(f'#!/bin/bash\necho "$@" >> "{tmp_path}/leak-calls"\n[ -f "{state}/leak" ] && exit 1\nexit 0\n'); leaks.chmod(0o755)
    env = {**os.environ, "MCD_GH": str(gh), "MCD_GITLEAKS": str(leaks)}
    def run(*args):
        return subprocess.run(["bash", str(repo / "scripts/release/publish-release.sh"), *args], capture_output=True, text=True, cwd=repo, env=env)
    return SimpleNamespace(repo=repo, run=run, calls=calls, state=state, head=lambda: git(repo, "rev-parse", "HEAD"))

def test_dry_run_shows_the_notes_the_release_will_carry(release_repo):
    r = release_repo.run("--version", "1.2.0", "--target", release_repo.head(), "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "owner/product v1.2.0" in r.stdout and "- thing two" in r.stdout and "- thing one" not in r.stdout
    assert "compare/v1.1.0...v1.2.0" in r.stdout and "nothing published" in r.stdout
    assert "release create" not in (release_repo.calls.read_text() if release_repo.calls.exists() else "")

def calls_of(release_repo):
    return release_repo.calls.read_text().splitlines() if release_repo.calls.exists() else []

def test_package_mode_creates_only_the_tag_so_the_workflow_can_draft_the_release(release_repo):
    (release_repo.state / "has-secret").write_text("")
    sha = release_repo.head()
    r = release_repo.run("--version", "1.2.0", "--target", sha, "--package")
    assert r.returncode == 0, r.stderr
    calls = calls_of(release_repo)
    tag_call = next(c for c in calls if c.startswith("api -X POST repos/owner/product/git/refs"))
    assert "ref=refs/tags/v1.2.0" in tag_call and f"sha={sha}" in tag_call
    assert not any(c.startswith("release create") for c in calls)      # the workflow creates the draft, not this script
    assert "tagged: v1.2.0" in r.stdout and "review it and publish it" in r.stdout

def test_package_mode_refuses_without_the_signing_secret_and_creates_nothing(release_repo):
    r = release_repo.run("--version", "1.2.0", "--target", release_repo.head(), "--package")
    assert r.returncode != 0 and "RELEASE_SSH_PRIVATE_KEY" in r.stderr and "no tag was created" in r.stderr
    calls = calls_of(release_repo)
    assert not any(c.startswith("release create") or "git/refs" in c and "POST" in c for c in calls)

def test_package_dry_run_says_what_it_would_do_and_publishes_nothing(release_repo):
    (release_repo.state / "has-secret").write_text("")
    r = release_repo.run("--version", "1.2.0", "--target", release_repo.head(), "--package", "--dry-run")
    assert r.returncode == 0 and "tag only" in r.stdout and "nothing published" in r.stdout
    assert not any("POST" in c or c.startswith("release create") for c in calls_of(release_repo))
