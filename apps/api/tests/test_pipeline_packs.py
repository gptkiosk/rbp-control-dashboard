"""Pipeline packs: data-only add-ons, validated before install, verified against the release key when fetched, loaded by the planner."""
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import pipeline_packs as pp
import project_types
from tests.test_release_fetch import SSH_KEYGEN, Server  # noqa: F401

TYPE = {"id": "course-test", "label": "Test course", "summary": "A short course.", "planner_text": "Plan a short course.",
        "keys": [], "guides": ["course-format.md"], "failure_points": [], "human_signoffs": ["Approve the objectives"], "checks": []}


def pack_files(**manifest):
    m = {"format": "dashboard-pipeline-pack", "version": "0.1", "id": "course-pack", "pack_version": "0.1.0", "label": "Course pack",
         "app_min": "0.0.1", "project_types": ["course-test"], "guides": ["course-format.md"], "general_guides": ["readme-and-docs.md"], **manifest}
    return {"pack.json": json.dumps(m).encode(), "project-types/course-test.json": json.dumps(TYPE).encode(),
            "guides/course-format.md": b"# Course format\n\nOne lesson per file, one heading per section.\n"}


def archive(files, top="course-pack-0.1.0/"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(top + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(buf.getvalue())


def settings(tmp_path):
    return SimpleNamespace(data_dir=tmp_path)


def test_a_valid_pack_passes_and_every_problem_is_listed_together():
    assert pp.validate(pack_files(), "0.6.86")[1] == []
    files = pack_files(checks=["course-package", "future-check"], app_min="9.0.0", service={"id": "x", "label": "X", "credential": "nope"})
    files["tools/run.sh"] = b"echo hi"
    files["guides/security.md"] = b"x"
    problems = " ".join(pp.validate({**files, "pack.json": json.dumps({**json.loads(files["pack.json"]), "guides": ["course-format.md", "security.md"]}).encode()}, "0.6.86")[1])
    for expected in ("tools/run.sh is not a file a pack may contain", "needs dashboard 9.0.0", "nope credential",
                     "does not have yet (future-check)", "security.md would replace a shipped guide"):
        assert expected in problems


def test_install_makes_the_type_and_its_guides_available_and_remove_takes_them_away(tmp_path):
    s = settings(tmp_path)
    pp.install(s, pack_files(), "0.6.86")
    assert "course-test" in project_types.load(s)
    assert project_types.selected_guides("course-test", s) == ["readme-and-docs.md", "course-format.md"]   # pack replaced the software guides
    assert "One lesson per file" in project_types.guidance_packet("course-test", s)["text"]
    assert project_types.selected_guides("local-website", s)[:2] == ["practices.md", "security.md"]       # other types keep the default
    pp.install(s, pack_files(pack_version="0.2.0"), "0.6.86")
    assert (tmp_path / "packs" / "course-pack" / "active").read_text().strip() == "0.2.0"
    assert (tmp_path / "packs" / "course-pack" / "0.1.0").is_dir()                                        # previous version kept
    pp.remove(s, "course-pack")
    assert "course-test" not in project_types.load(s)
    with pytest.raises(pp.PackError):
        pp.install(s, {**pack_files(), "evil.py": b"import os"}, "0.6.86")
    assert not (tmp_path / "packs" / "course-pack").exists()


def test_the_operators_own_type_still_wins_over_a_pack(tmp_path):
    s = settings(tmp_path)
    pp.install(s, pack_files(), "0.6.86")
    (tmp_path / "project-types").mkdir()
    (tmp_path / "project-types" / "course-test.json").write_text(json.dumps({**TYPE, "label": "Mine"}))
    assert project_types.load(s)["course-test"]["label"] == "Mine"


def test_archives_refuse_links_and_paths_outside_the_pack():
    assert set(pp.read_archive(archive(pack_files()))) == set(pack_files())
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        link = tarfile.TarInfo("pack/link"); link.type = tarfile.SYMTYPE; link.linkname = "/etc/passwd"; tar.addfile(link)
    with pytest.raises(pp.PackError, match="not a regular file"):
        pp.read_archive(gzip.compress(buf.getvalue()))
    with pytest.raises(pp.PackError, match="outside the pack"):
        pp.read_archive(archive({"x": b"1"}, top="../"))


@pytest.mark.skipif(SSH_KEYGEN is None, reason="ssh-keygen is not available")
def test_listing_and_install_verify_the_signed_index_and_the_archive_digest(tmp_path):
    keys = tmp_path / "keys"; keys.mkdir(mode=0o700)
    for name in ("good", "evil"):
        subprocess.run([SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-f", str(keys / name)], check=True)
    pub = (keys / "good.pub").read_text().split()
    signer = f'dashboard-release namespaces="dashboard-release" {pub[0]} {pub[1]} test'

    def sign(key, data, where):
        where.write_bytes(data)
        subprocess.run([SSH_KEYGEN, "-Y", "sign", "-q", "-f", str(keys / key), "-n", "dashboard-release", str(where)], check=True)
        return Path(f"{where}.sig").read_bytes()

    data = archive(pack_files())
    entry = {"id": "course-pack", "pack_version": "0.1.0", "label": "Course pack", "archive": "course-pack-0.1.0.tar.gz", "sha256": hashlib.sha256(data).hexdigest()}
    index = json.dumps({"format": "dashboard-pipeline-pack-index", "version": "0.1", "packs": [entry]}).encode()
    server = Server()
    try:
        dl = lambda name: f"{server.base}/dl/{name}"
        server.routes[f"/repos/{pp.PACKS_REPOSITORY}/releases/latest"] = json.dumps({"tag_name": "packs-1", "assets": [
            {"name": n, "browser_download_url": dl(n)} for n in ("pipeline-packs.json", "pipeline-packs.json.sig", "course-pack-0.1.0.tar.gz")]}).encode()
        server.routes["/dl/pipeline-packs.json"] = index
        server.routes["/dl/course-pack-0.1.0.tar.gz"] = data
        net = dict(api_base=server.base, allowed_hosts=frozenset({"127.0.0.1"}), require_https=False)

        server.routes["/dl/pipeline-packs.json.sig"] = sign("evil", index, tmp_path / "i1")
        with pytest.raises(pp.PackError, match="not signed by the dashboard release key"):
            pp.available(signer=signer, **net)

        server.routes["/dl/pipeline-packs.json.sig"] = sign("good", index, tmp_path / "i2")
        listing = pp.available(signer=signer, **net)
        assert [p["id"] for p in listing["packs"]] == ["course-pack"] and listing["release"] == "packs-1"
        s = settings(tmp_path / "data")
        pp.download_and_install(s, listing["packs"][0], "0.6.86", **net)
        assert "course-test" in project_types.load(s)

        server.routes["/dl/course-pack-0.1.0.tar.gz"] = archive({**pack_files(), "guides/course-format.md": b"changed"})
        with pytest.raises(pp.PackError, match="does not match the signed index"):
            pp.download_and_install(s, listing["packs"][0], "0.6.86", **net)
    finally:
        server.close()


def test_the_built_in_release_key_is_the_one_the_app_releases_are_signed_with():
    from settings import REPO_ROOT
    assert (Path(REPO_ROOT) / "packaging" / "allowed_signers").read_text().strip() == pp.RELEASE_SIGNER


def test_routes_offer_packs_and_hold_a_service_pack_until_its_credential_is_saved(make_client, monkeypatch):
    import routes.pipeline_packs as route
    client = make_client()

    @client.app.middleware("http")
    async def operator_session(request, call_next):
        request.state.user = {"email": "operator@example.invalid"}
        return await call_next(request)

    offered = {"release": "packs-1", "packs": [{"id": "upubhub-class", "pack_version": "0.1.0", "label": "upubhub class", "summary": "Textbook and lessons.",
                                                "service": {"id": "upubhub", "label": "upubhub.com", "credential": "upubhub"}, "archive": "x", "sha256": "0" * 64, "url": "u"}]}
    monkeypatch.setattr(route.pp, "available", lambda: offered)
    route._CACHE.update(at=0.0, listing=None, error=None)
    r = client.get("/api/pipeline-packs"); body = r.json(); assert r.status_code == 200, r.text
    assert body["available"][0]["service"]["ready"] is False and body["installed"] == []
    r = client.post("/api/pipeline-packs/install", json={"id": "upubhub-class"})
    assert r.status_code == 409 and "Private credentials" in r.json()["detail"]
    assert client.put("/api/profile/credentials/upubhub", json={"value": "uph_" + "a" * 32}).status_code == 200
    calls = []
    monkeypatch.setattr(route.pp, "download_and_install", lambda settings, entry, version: calls.append(entry["id"]) or {"id": entry["id"], "pack_version": "0.1.0", "project_types": ["upubhub-class"]})
    assert client.post("/api/pipeline-packs/install", json={"id": "upubhub-class"}).status_code == 200 and calls == ["upubhub-class"]
    assert client.delete("/api/pipeline-packs/nothing-here").status_code == 404


def test_the_index_keeps_store_fields_and_tools_in_their_expected_shapes():
    entry = {"id": "course-pack", "pack_version": "0.2.0", "label": "Course pack", "archive": "course-pack-0.2.0.tar.gz", "sha256": "a" * 64,
             "author": "a-teacher", "trust": "community", "settings": ["Lessons", 5], "app_min": "0.6.88",
             "requires": {"system_tools": ["ffmpeg", "Bad Name"], "checks": ["course-package"], "anything": ["x"]}}
    odd = {**entry, "id": "odd-pack", "archive": "odd-pack-0.2.0.tar.gz", "author": "<b>me</b>", "trust": "verified", "requires": "all"}
    tools = {"system_tools": [{"id": "ffmpeg", "name": "FFmpeg", "description": "Converts video.", "app_min": "0.6.0"}, {"id": "../x", "name": "x"}],
             "agents": "nope"}
    data = json.dumps({"format": "dashboard-pipeline-pack-index", "version": "0.1", "packs": [entry, odd], "tools": tools}).encode()
    first, second = pp.parse_index(data)
    assert (first["author"], first["trust"], first["settings"]) == ("a-teacher", "community", ["Lessons"])
    assert first["requires"] == {"system_tools": ["ffmpeg"], "checks": ["course-package"]}
    assert (second["author"], second["trust"], second["requires"]) == (None, None, {})
    listed = pp.parse_tools(data)
    assert listed["system_tools"] == [{"id": "ffmpeg", "name": "FFmpeg", "description": "Converts video.", "app_min": "0.6.0"}]
    assert listed["agents"] == [] and pp.parse_tools(b"not json") == {}


def test_the_store_listing_names_what_this_host_lacks_and_shows_the_tools(make_client, monkeypatch):
    import routes.pipeline_packs as route
    client = make_client()

    @client.app.middleware("http")
    async def operator_session(request, call_next):
        request.state.user = {"email": "operator@example.invalid"}
        return await call_next(request)

    offered = {"release": "packs-2", "packs": [
        {"id": "course-pack", "pack_version": "0.2.0", "label": "Course pack", "summary": "", "service": None, "archive": "x", "sha256": "0" * 64, "url": "u",
         "app_min": "0.6.0", "author": "gptkiosk", "trust": "official", "settings": ["Lessons"], "requires": {"checks": ["course-package", "future-check"], "providers": ["fal"]}},
        {"id": "next-pack", "pack_version": "1.0.0", "label": "Next", "summary": "", "service": None, "archive": "y", "sha256": "0" * 64, "url": "v",
         "app_min": "99.0.0", "author": None, "trust": None, "settings": [], "requires": {}}],
        "tools": {"checks": [{"id": "course-package", "name": "Course package check", "description": "Checks a course.", "app_min": "0.6.87"}],
                  "providers": [{"id": "fal", "name": "fal", "description": "Media.", "app_min": "0.6.13"}]}}
    monkeypatch.setattr(route.pp, "available", lambda: offered)
    route._CACHE.update(at=0.0, listing=None, error=None)
    body = client.get("/api/pipeline-packs").json()
    course, later = body["available"]
    assert (course["trust"], course["author"], course["settings"], course["too_new"]) == ("official", "gptkiosk", ["Lessons"], False)
    assert {(n["kind"], n["id"], n["status"]) for n in course["needs"]} == {("checks", "future-check", "unknown"), ("providers", "fal", "missing")}
    assert later["too_new"] is True and later["needs"][0]["detail"] == "Needs dashboard 99.0.0 or newer."
    assert body["tools"]["checks"][0]["status"] == "ready" and body["tools"]["providers"][0]["status"] == "missing"
    assert body["tools"]["providers"][0]["link"] == "/profile#credentials-profile"


def zip_archive(files, top="my-course/"):
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(top + name, data)
        z.writestr("__MACOSX/._pack.json", b"finder metadata")              # what macOS Compress adds
    return buf.getvalue()


def test_an_earlier_version_stays_and_can_be_made_active_again(tmp_path):
    s = settings(tmp_path)
    pp.install(s, pack_files(), "0.6.86")
    pp.install(s, pack_files(pack_version="0.2.0", changes="Two lessons per week."), "0.6.86")
    pack = pp.installed(s)[0]
    assert (pack["version"], pack["versions"], pack["manifest"]["changes"]) == ("0.2.0", ["0.2.0", "0.1.0"], "Two lessons per week.")
    pp.activate(s, "course-pack", "0.1.0", "0.6.86")
    assert pp.installed(s)[0]["version"] == "0.1.0"
    with pytest.raises(pp.PackError):
        pp.activate(s, "course-pack", "9.9.9", "0.6.86")                       # not on disk
    (tmp_path / "packs" / "course-pack" / "0.2.0" / "tools.sh").write_text("echo hi")
    with pytest.raises(pp.PackError, match="no longer checks out"):
        pp.activate(s, "course-pack", "0.2.0", "0.6.86")                       # a stored version is checked again before use
    assert pp.validate(pack_files(changes="x" * 601), "0.6.86")[1] == ["changes must be text of at most 600 characters."]


def test_an_own_template_imports_from_a_zip_or_tar_unsigned_and_is_marked_local(tmp_path):
    s = settings(tmp_path)
    m = pp.import_local(s, zip_archive(pack_files()), "0.6.86", reserved={"upubhub-class", "local-website"})
    pack = pp.installed(s)[0]
    assert m["id"] == "course-pack" and pack["source"]["kind"] == "local" and len(pack["source"]["sha256"]) == 64
    pp.import_local(s, archive(pack_files(pack_version="0.2.0")), "0.6.86", reserved=set())    # a newer own version replaces it
    assert pp.installed(s)[0]["version"] == "0.2.0" and pp.installed(s)[0]["source"]["kind"] == "local"
    pp.install(s, pack_files(pack_version="0.3.0"), "0.6.86")                                  # a store install clears the local mark
    assert pp.installed(s)[0]["source"] is None


def test_an_own_template_may_not_take_a_store_or_built_in_id_or_anothers_types(tmp_path):
    s = settings(tmp_path)
    with pytest.raises(pp.PackError, match="its own id") as exc:
        pp.import_local(s, archive(pack_files()), "0.6.86", reserved={"course-pack"})
    assert exc.value.status == 409
    with pytest.raises(pp.PackError, match="course-test"):
        pp.import_local(s, archive(pack_files()), "0.6.86", reserved={"course-test"})          # a type id that is built in
    pp.install(s, pack_files(), "0.6.86")                                                       # the store copy is installed
    with pytest.raises(pp.PackError, match="installed from the store"):
        pp.import_local(s, archive(pack_files(pack_version="0.9.0")), "0.6.86", reserved=set())
    with pytest.raises(pp.PackError, match="already used: course-test"):
        pp.import_local(s, archive(pack_files(id="other-pack")), "0.6.86", reserved=set())      # another pack's type
    with pytest.raises(pp.PackError, match="not a file a pack may contain"):
        pp.import_local(s, zip_archive({**pack_files(id="third"), "run.sh": b"echo"}), "0.6.86", reserved=set())   # same data-only rules


def test_routes_import_needs_the_risk_accepted_refuse_store_ids_and_switch_versions(make_client, monkeypatch):
    import routes.pipeline_packs as route
    client = make_client()

    @client.app.middleware("http")
    async def operator_session(request, call_next):
        request.state.user = {"email": "operator@example.invalid"}
        return await call_next(request)

    offered = {"release": "packs-3", "packs": [{"id": "store-pack", "pack_version": "1.0.0", "label": "Store", "summary": "", "service": None,
                                                "archive": "x", "sha256": "0" * 64, "url": "u", "changes": "New checks."}]}
    monkeypatch.setattr(route.pp, "available", lambda: offered)
    route._CACHE.update(at=0.0, listing=None, error=None)
    data = zip_archive(pack_files())
    assert client.post("/api/pipeline-packs/import", content=data).status_code == 422                    # risk not accepted
    r = client.post("/api/pipeline-packs/import?accept_risk=true", content=data)
    assert r.status_code == 201, r.text
    assert r.json() == {"installed": "course-pack", "version": "0.1.0", "project_types": ["course-test"], "local": True}
    r = client.post("/api/pipeline-packs/import?accept_risk=true", content=zip_archive(pack_files(id="store-pack")))
    assert r.status_code == 409 and "store or built-in template id" in r.json()["detail"]
    r = client.post("/api/pipeline-packs/import?accept_risk=true", content=zip_archive(pack_files(id="mine", project_types=["local-website"])))
    assert r.status_code in (409, 422)                                                                    # a shipped type id
    client.post("/api/pipeline-packs/import?accept_risk=true", content=zip_archive(pack_files(pack_version="0.2.0", changes="More.")))
    body = client.get("/api/pipeline-packs").json()
    mine = body["installed"][0]
    assert (mine["local"], mine["version"], mine["versions"], mine["changes"]) == (True, "0.2.0", ["0.2.0", "0.1.0"], "More.")
    assert body["available"][0]["changes"] == "New checks."
    types = {t["id"]: t for t in client.get("/api/project-types").json()["types"]}
    assert types["course-test"]["local"] is True and types["local-website"]["local"] is False   # the picker marks own templates
    r = client.post("/api/pipeline-packs/course-pack/activate", json={"version": "0.1.0"})
    assert r.status_code == 200 and r.json() == {"id": "course-pack", "version": "0.1.0"}
    assert client.post("/api/pipeline-packs/course-pack/activate", json={"version": "bad"}).status_code == 422
