"""Regression checks for high/medium s15 release pipeline findings."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (ROOT / ".github/workflows/release-on-tag.yml").read_text()


def test_release_build_has_read_only_token_and_separate_privileged_jobs():
    assert "permissions:\n  contents: read" in WORKFLOW
    assert WORKFLOW.count("contents: write") == 1
    assert WORKFLOW.count("GH_TOKEN: ${{ github.token }}") == 1
    build = WORKFLOW.index("build:\n")
    attest = WORKFLOW.index("sign-and-attest:\n")
    publish = WORKFLOW.index("publish-draft:\n")
    assert build < attest < publish
    assert "GH_TOKEN" not in WORKFLOW[build:attest]
    assert "permissions:\n      contents: read\n      attestations: write\n      id-token: write" in WORKFLOW[attest:publish]
    assert "permissions:\n      contents: write" in WORKFLOW[publish:]


def test_external_actions_are_full_commit_pins():
    refs = re.findall(r"uses:\s+([^\s]+)", WORKFLOW)
    assert refs
    assert all(re.search(r"@[0-9a-f]{40}$", ref) for ref in refs), refs


def test_bootstrap_requires_manifest_pin_and_never_executes_archive_verifier():
    bootstrap = (ROOT / "scripts/install/bootstrap-rcd.sh").read_text()
    assert "--manifest-sha256" in bootstrap
    assert "not the pinned" in bootstrap
    assert 'CHECK_PY=' in bootstrap
    assert bootstrap.index('CHECK_PY=') < bootstrap.index('tar -xzf "$ARCHIVE"')


def test_bootstrap_checks_redirect_destination_before_fetching_next_hop():
    bootstrap = (ROOT / "scripts/install/bootstrap-rcd.sh").read_text()
    fetch = bootstrap[bootstrap.index("fetch() {"):bootstrap.index("\n}\n", bootstrap.index("fetch() {"))]
    assert "--max-redirs 0" in fetch
    assert fetch.index("case \"$url\" in") < fetch.index("curl ")
    assert "case \"$location\" in https://*" in fetch
