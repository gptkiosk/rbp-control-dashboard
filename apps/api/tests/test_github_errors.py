"""One misspelled or unreadable repository must not blank the GitHub page, and the reason is stated."""
import json
from types import SimpleNamespace

import pytest

import github_read
from github_config import GithubConfigStore
from github_read import GithubReader
from tests.test_auth import secured, begin, complete          # noqa: F401  (operator sign-in fixtures)


def reader_for(tmp_path, monkeypatch, repos, behaviour, visible=("owner/rbp-control-dashboard", "owner/good")):
    store = GithubConfigStore(tmp_path / "data")
    store.save({"version": 1, "enabled": True, "account": "owner", "repos": repos, "public_only": False, "poll_seconds": 900})
    seen = []

    def run(argv, **kwargs):
        endpoint = argv[4]
        seen.append(endpoint)
        if endpoint.startswith("user/repos"):
            return SimpleNamespace(returncode=0, stdout=json.dumps(list(visible)).encode(), stderr=b"")
        name = endpoint.removeprefix("repos/")
        how = behaviour.get(name, "ok")
        if how == "ok":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"name": name, "private": False, "archived": False}).encode(), stderr=b"")
        text = {"404": b"gh: Not Found (HTTP 404)", "403": b"gh: Forbidden (HTTP 403)", "rate": b"API rate limit exceeded",
                "boom": b"something odd"}[how]
        return SimpleNamespace(returncode=1, stdout=b"", stderr=text)

    monkeypatch.setattr(github_read.subprocess, "run", run)
    return GithubReader("fake-gh", store), seen


def test_a_misspelled_repository_is_reported_with_a_hint_and_the_good_one_still_loads(tmp_path, monkeypatch):
    r, seen = reader_for(tmp_path, monkeypatch, ["owner/good", "owner/rpd-control-dashboard"], {"owner/rpd-control-dashboard": "404"})
    out = r.repos(force=True)
    assert [x["name"] for x in out["repos"]] == ["owner/good"] and out["error"] is None and out["stale"] is False
    assert out["problems"] == [{"name": "owner/rpd-control-dashboard", "reason": "not_found", "hint": "owner/rbp-control-dashboard"}]


def test_only_misspelled_names_say_so_instead_of_blaming_the_login(tmp_path, monkeypatch):
    r, _ = reader_for(tmp_path, monkeypatch, ["owner/rpd-control-dashboard"], {"owner/rpd-control-dashboard": "404"})
    out = r.repos(force=True)
    assert out["repos"] == [] and out["error"] is None
    assert out["problems"][0]["reason"] == "not_found"


def test_a_name_with_no_close_match_has_no_hint(tmp_path, monkeypatch):
    r, _ = reader_for(tmp_path, monkeypatch, ["owner/zzz-unrelated"], {"owner/zzz-unrelated": "404"})
    assert r.repos(force=True)["problems"][0]["hint"] is None


@pytest.mark.parametrize("how,reason", [("403", "denied"), ("rate", "denied"), ("boom", "unavailable")])
def test_access_problems_are_named_per_repository_but_do_not_hide_the_rest(tmp_path, monkeypatch, how, reason):
    r, _ = reader_for(tmp_path, monkeypatch, ["owner/good", "owner/other"], {"owner/other": how})
    out = r.repos(force=True)
    assert [x["name"] for x in out["repos"]] == ["owner/good"] and out["error"] is None
    assert out["problems"] == [{"name": "owner/other", "reason": reason, "hint": None}]


def test_when_nothing_can_be_read_because_of_access_the_page_reports_github_unavailable(tmp_path, monkeypatch):
    r, _ = reader_for(tmp_path, monkeypatch, ["owner/a", "owner/b"], {"owner/a": "403", "owner/b": "403"})
    out = r.repos(force=True)
    assert out["repos"] == [] and "GitHub is unavailable" in out["error"]


def test_gh_output_is_never_kept(tmp_path, monkeypatch):
    r, _ = reader_for(tmp_path, monkeypatch, ["owner/other"], {"owner/other": "403"})
    assert "Forbidden" not in json.dumps(r.repos(force=True))


def test_missing_lists_only_names_github_says_do_not_exist(tmp_path, monkeypatch):
    r, _ = reader_for(tmp_path, monkeypatch, ["owner/good", "owner/rpd-control-dashboard", "owner/denied"],
                      {"owner/rpd-control-dashboard": "404", "owner/denied": "403"})
    assert r.missing(["owner/good", "owner/rpd-control-dashboard", "owner/denied"]) == [
        {"name": "owner/rpd-control-dashboard", "hint": "owner/rbp-control-dashboard"}]


def test_saving_a_misspelled_repository_is_refused_with_the_hint(secured, monkeypatch):
    assert complete(secured, begin(secured)).status_code == 303
    reader = secured.app.state.github
    async def quiet(stop):                                   # a successful save starts the background poll; keep the test quiet
        return
    monkeypatch.setattr(reader, "poll", quiet)
    monkeypatch.setattr(reader, "auth_status", lambda: {"available": True, "account": "owner"})
    monkeypatch.setattr(reader, "missing", lambda repos: [{"name": "owner/rpd-control-dashboard", "hint": "owner/rbp-control-dashboard"}]
                        if "owner/rpd-control-dashboard" in repos else [])
    body = {"version": 1, "enabled": True, "account": "owner", "repos": ["owner/good", "owner/rpd-control-dashboard"], "public_only": True, "poll_seconds": 900}
    r = secured.put("/api/github/config", json=body)
    assert r.status_code == 422 and "owner/rpd-control-dashboard was not found" in r.json()["detail"] and "Did you mean owner/rbp-control-dashboard?" in r.json()["detail"]
    body["repos"] = ["owner/good", "owner/rbp-control-dashboard"]
    assert secured.put("/api/github/config", json=body).status_code == 200


# ------------------------------------------------------------------ the repository checklist (settings)


def lister(monkeypatch, mine="owner", fail=None):
    """A fake gh that answers `auth status` and the two repository-listing endpoints."""
    seen = []

    def run(argv, **kwargs):
        if argv[1:3] == ["auth", "status"]:
            return SimpleNamespace(returncode=0, stdout=f"github.com\n  Logged in to github.com account {mine} (keyring)\n", stderr="")
        endpoint = argv[4]
        seen.append(endpoint)
        if fail:
            return SimpleNamespace(returncode=1, stdout=b"", stderr={"404": b"HTTP 404", "403": b"HTTP 403", "boom": b"x"}[fail])
        who = "owner" if endpoint.startswith("user/repos") else endpoint.split("/")[1]
        rows = [{"name": f"{who}/b-private", "private": True, "archived": False, "description": "p", "updated_at": "2026-10-13T00:00:00Z", "branch": "main"},
                {"name": f"{who}/a-public", "private": False, "archived": False, "description": None, "updated_at": "2026-10-12T00:00:00Z", "branch": "main"},
                {"name": "someone-else/forked", "private": False, "archived": False, "description": None, "updated_at": None, "branch": "main"}]
        return SimpleNamespace(returncode=0, stdout=json.dumps(rows).encode(), stderr=b"")

    monkeypatch.setattr(github_read.subprocess, "run", run)
    return seen


def test_account_repos_include_private_ones_only_for_the_signed_in_account(tmp_path, monkeypatch):
    seen = lister(monkeypatch, mine="owner")
    r = GithubReader("fake-gh", GithubConfigStore(tmp_path / "d"))
    own = r.account_repos("owner")
    assert seen[-1].startswith("user/repos") and own["private_included"] is True
    assert [x["name"] for x in own["repos"]] == ["owner/b-private", "owner/a-public"]          # newest first, nothing from other owners
    other = r.account_repos("some-org")
    assert seen[-1].startswith("users/some-org/repos") and other["private_included"] is False
    assert all(x["name"].startswith("some-org/") for x in other["repos"])


@pytest.mark.parametrize("bad", ["", "a/b", "x" * 40, "has space", "../x"])
def test_account_repos_rejects_a_bad_owner_before_calling_gh(tmp_path, monkeypatch, bad):
    seen = lister(monkeypatch)
    with pytest.raises(ValueError):
        GithubReader("fake-gh", GithubConfigStore(tmp_path / "d")).account_repos(bad)
    assert seen == []


def test_the_checklist_route_is_operator_only_and_reports_clear_errors(secured, monkeypatch):
    assert secured.get("/api/github/account-repos?owner=owner").status_code == 401
    assert complete(secured, begin(secured)).status_code == 303
    lister(monkeypatch)
    ok = secured.get("/api/github/account-repos?owner=owner")
    assert ok.status_code == 200 and [x["name"] for x in ok.json()["repos"]] == ["owner/b-private", "owner/a-public"]
    assert secured.get("/api/github/account-repos").status_code == 422
    for how, code, text in (("404", 404, "No GitHub account or organisation named owner"), ("403", 502, "refused"), ("boom", 502, "could not be reached")):
        lister(monkeypatch, fail=how)
        r = secured.get("/api/github/account-repos?owner=owner")
        assert r.status_code == code and text in r.json()["detail"]
