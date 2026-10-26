"""Project types: templates are sound, a plan is checked against its type, and the planner is told the type's failure points."""
from __future__ import annotations

import json

import pytest

import project_types as pt
from settings import get_settings
from tests.test_projects import app, new, node  # noqa: F401


def story(key, title, deps=(), assignee="claude", description="", **kw):
    return {"key": key, "kind": "story", "title": title, "description": description, "acceptance": "", "depends_on": list(deps), "assignee": assignee, **kw}


GOOD_SITE = [
    story("a", "Design direction writes DESIGN.md"),
    story("b", "Restyle the pages", ["a"]),
    story("m", "Create the media inventory and media/slots.json", ["b"]),
    story("mg", "Generate, select and publish site illustrations in MCD Media Studio", ["m"], assignee="human"),
    story("mi", "Integrate published media into pages and both themes", ["mg"]),
    story("c", "Verification of the files and themes", ["mi"], assignee="openclaw"),
    story("d", "Preview checkpoint on localhost", ["c"], assignee="claude"),
    story("e", "Responsive and polish review in the preview", ["d"], assignee="human"),
    story("e2", "Approve the look from the preview", ["e"], assignee="human"),
    story("f", "Container and pipeline finish", ["e2"]),
    story("f2", "Push the project branch and open the pull request", ["f"]),
    story("f3", "README with the architecture diagram and a how-to for each page", ["f"]),
    story("f4", "Capture the application screenshots with the Playwright script", ["f3"], assignee="human"),
    story("g", "Final local verification on Colima: docker compose up --build, and the pipeline result", ["f2", "f4"], assignee="human"),
]


def ids(findings):
    return {f["id"] for f in findings}


def test_every_shipped_type_is_usable_and_named_for_its_file(tmp_path):
    types = pt.load(type("S", (), {"data_dir": tmp_path})())
    assert set(types) == {"web-app", "packaged-app", "website-property", "local-website", "gcp-hosted-website", "gcp-hosted-app", "other"}
    for t in types.values():
        assert t["failure_points"] and t["human_signoffs"] and t["planner_text"] and t["checks"]
        assert all(c["message"] for c in t["checks"])


def test_a_plan_that_follows_the_website_type_has_no_findings():
    assert pt.check("website-property", GOOD_SITE) == []


def test_the_website_type_catches_the_mistakes_that_failed_before(tmp_path):
    bad = [
        story("x", "Container and pipeline setup with docker compose up --build smoke test", [], assignee="codex"),
        story("p", "Pages restyle", ["x"]),
        story("m", "Generate the video clips and stills", ["p"], assignee="claude"),
        story("h", "Approve the art look", ["m"], assignee="human"),
    ]
    found = ids(pt.check("website-property", bad))
    assert {"design-direction-first", "verification-story", "preview-checkpoint", "preview-before-look-signoff", "container-needs-human", "media-is-human", "container-after-pages", "illustrated-media-inventory", "illustrated-media-generation", "illustrated-media-integration"} <= found
    flagged = {f["id"]: f["stories"] for f in pt.check("website-property", bad)}
    assert flagged["container-needs-human"] == ["x"] and flagged["media-is-human"] == ["m"] and flagged["container-after-pages"] == ["x"]


def test_a_preview_folded_into_the_human_story_is_still_flagged():
    merged = [s for s in GOOD_SITE if s["key"] not in {"d", "e"}] + [story("e", "Preview checkpoint and human approval of the look", ["c"], assignee="human")]
    assert "preview-checkpoint" in ids(pt.check("website-property", merged))


def test_web_app_and_packaged_app_checks():
    web = [story("a", "Build the image with docker build and run compose up", assignee="codex")]
    assert {"container-needs-human", "has-human-signoff", "has-verification"} <= ids(pt.check("web-app", web))
    package = [story("a", "Publish the release and sign the manifest", assignee="claude"), story("b", "Write docs")]
    assert {"release-is-human", "has-install-test", "has-release-approval"} <= ids(pt.check("packaged-app", package))
    ok = [story("a", "Code and tests"), story("b", "Verify the package checksum signature and manifest", ["a"]),
          story("c", "Install and update test on the Pi", ["b"], assignee="human"), story("d", "Approve publishing the release", ["c"], assignee="human"),
          story("e", "Push the branch and open the pull request, then read the pipeline result", ["a"]),
          story("f", "Write the README and how-tos with a data-flow diagram", ["a"]), story("g", "Capture the screenshots with Playwright", ["f"], assignee="human")]
    assert pt.check("packaged-app", ok) == []


def test_impossible_agent_runtime_checks_block_dispatch_and_require_a_human_verification():
    media = [
        story("m", "Create the media inventory and media/slots.json"),
        story("mg", "Generate, select and publish site illustrations in MCD Media Studio", ["m"], assignee="human"),
        story("mi", "Integrate published media into pages and both themes", ["mg"]),
    ]
    bad = [story("a", "Container configuration", assignee="codex", description="Run docker compose build and start the stack."), *media]
    findings = pt.blocking_findings("website-property", bad)
    assert {f["id"] for f in findings} == {"container-needs-human", "container-runtime-verification"}
    fixed = bad + [story("b", "Local Docker container verification", ["a"], assignee="human")]
    assert {f["id"] for f in pt.blocking_findings("website-property", fixed)} == {"container-needs-human"}


def test_no_type_or_an_unknown_type_checks_nothing():
    assert pt.check(None, GOOD_SITE) == [] and pt.check("nonsense", []) == []
    assert pt.planner_section(None) == "" and pt.planner_section("nonsense") == ""


def test_the_planner_is_told_the_type_its_failure_points_and_where_people_look_and_sign_off():
    text = pt.planner_section("website-property")
    assert "Project type: Website property" in text and "Known failure points" in text
    assert "A Dockerfile that copies only html, css and js ships a site with no assets" in text
    assert "Visual checks:" in text and "Human sign-offs belong here:" in text


def test_a_type_is_suggested_only_when_the_brief_clearly_fits():
    assert pt.suggest("A static local website with dark mode, theme toggle, custom art and animation transitions") == "local-website"
    assert pt.suggest("A subscription service on GCP Cloud Run with Stripe payments") == "gcp-hosted-app"
    assert pt.suggest("An installable packaged app from a GitHub release for Raspberry Pi") == "packaged-app"
    assert pt.suggest("An illustrated website hosted on GCP Cloud Run") == "gcp-hosted-website"
    assert pt.suggest("A GCP Cloud Run application service") == "gcp-hosted-app"
    assert {row["id"] for row in pt.listing()} == {"packaged-app", "local-website", "gcp-hosted-website", "gcp-hosted-app", "other"}
    assert pt.suggest("Fix the login bug") is None


def test_the_operators_own_copy_wins_and_a_broken_one_is_ignored(tmp_path):
    settings = type("S", (), {"data_dir": tmp_path})()
    mine = tmp_path / "project-types"
    mine.mkdir()
    custom = dict(pt.load(settings)["web-app"], label="My web app", failure_points=["My own lesson."])
    (mine / "web-app.json").write_text(json.dumps(custom))
    assert pt.load(settings)["web-app"]["label"] == "My web app"
    (mine / "packaged-app.json").write_text(json.dumps(dict(custom, id="packaged-app", checks=[{"id": "x", "kind": "run_code", "message": "m"}])))
    assert pt.load(settings)["packaged-app"]["label"].startswith("Packaged app")                  # the broken copy never replaces the shipped one
    (mine / "website-property.json").write_text("not json")
    assert "website-property" in pt.load(settings)


def test_types_and_checks_are_available_through_the_api(app):  # noqa: F811
    c, s, wd, settings = app
    listing = c.get("/api/project-types").json()["types"]
    assert {t["id"] for t in listing} == {"packaged-app", "local-website", "gcp-hosted-website", "gcp-hosted-app", "other"}
    assert c.post("/api/project-types/suggest", json={"text": "A static local website with dark mode, art and animation"}).json() == {"suggested": "local-website"}
    plain = new(app, [node("a")])
    assert c.get(f"/api/projects/{plain['id']}/checks").json() == {"project_type": None, "findings": []}
    typed = new(app, [node("a", title="Container and pipeline docker compose up", assignee="codex")], project_type="website-property")
    result = c.get(f"/api/projects/{typed['id']}/checks").json()
    assert result["project_type"] == "website-property" and "container-needs-human" in {f["id"] for f in result["findings"]}
    assert c.post("/api/projects", json={"title": "Bad", "brief": "x", "working_dir": str(wd), "nodes": [], "project_type": "Bad Type!"}).status_code == 422


def test_every_type_flags_an_agent_story_that_needs_a_browser_and_leaves_static_checks_alone():
    needs_browser = [story("v", "Verification: both themes render without console errors", assignee="codex")]
    static = [story("v", "Verification of the files: every referenced asset exists and no external requests", assignee="codex")]
    for kind in ("website-property", "web-app", "packaged-app"):
        flagged = {f["id"]: f["stories"] for f in pt.check(kind, needs_browser)}
        assert flagged.get("browser-checks-need-a-person") == ["v"], kind
        assert "browser-checks-need-a-person" not in ids(pt.check(kind, static)), kind
        assert ("Never ask an agent story to render pages" in pt.planner_section(kind) or "static file validity" in pt.planner_section(kind))
    human = [story("v", "Preview checkpoint: check both themes render without console errors", assignee="human")]
    assert "browser-checks-need-a-person" not in ids(pt.check("website-property", human))             # a person can


def test_media_default_tiers_are_validated_and_default_to_standard(tmp_path):
    assert pt.media_default_tiers("website-property") == {"image": "standard", "video": "draft"}
    assert pt.media_default_tiers("web-app") == {"image": "standard", "video": "standard"}
    assert pt.media_default_tiers(None) == {"image": "standard", "video": "standard"}
    base = {"id": "x", "label": "X", "summary": "s", "planner_text": "p"}
    assert pt._valid({**base, "media_default_tiers": {"video": "draft"}})
    assert not pt._valid({**base, "media_default_tiers": {"video": "cheapest"}})
    assert not pt._valid({**base, "media_default_tiers": {"audio": "draft"}})


def test_untyped_consultant_has_only_a_selector_and_selected_type_gets_its_rules():
    text = pt.consultant_text()
    assert all(name in text for name in ('Local website', 'GCP hosted website', 'GCP hosted app', 'Packaged app', 'Other'))
    assert 'fal key' not in text and 'Known failure:' not in text and len(text) <= 1300
    typed = pt.consultant_text(type_id='local-website')
    assert 'fal key' in typed and 'another take' in typed
    package = pt.consultant_text(type_id='packaged-app')
    assert 'fal key' not in package and 'cheapest video tier' not in package


def test_a_chosen_type_focuses_the_consultant_and_other_is_a_real_type():
    other = pt.load()["other"]
    assert other["label"].startswith("Other") and other["suggest"] == [] and {c["id"] for c in other["checks"]} == {"container-needs-human", "container-runtime-verification", "browser-checks-need-a-person", "delivery-to-remote", "readme-story", "screenshots-by-a-person-or-ci"}     # never suggested; only the limits and the delivery and documentation gates every project has
    assert "most resembles" in other["planner_text"]
    text = pt.consultant_text(type_id="website-property")
    assert "The operator chose the project type Website property" in text and "Meaningful decisions:" in text and "Known failure:" in text
    assert "does not fit this type" in text and "never by an agent" in text and len(text) <= 1700
    assert "The operator chose" not in pt.consultant_text(type_id="nonsense")                      # an unknown id falls back to the general list
    assert pt.media_default_tiers("other") == {"image": "standard", "video": "standard"}


def test_every_type_asks_for_delivery_to_the_remote_repository_and_says_why():
    for type_id in ("web-app", "packaged-app", "website-property", "other"):
        t = pt.load()[type_id]
        assert ("ends in the remote repository" in t["planner_text"] and "scratch folder" in t["planner_text"]) or ("selected project branch" in t["planner_text"] and "when repository delivery was requested" in t["planner_text"])
        assert any("scratch folder with no git remote" in fp for fp in t["failure_points"])
        none = [story("a", "Code and tests")]
        assert "delivery-to-remote" in ids(pt.check(type_id, none))
        done = [story("a", "Code and tests"), story("b", "Push the project branch and open a pull request", ["a"])]
        assert "delivery-to-remote" not in ids(pt.check(type_id, done))


def test_each_type_says_whether_its_repository_is_public_or_private():
    load = pt.load()
    assert "The repository is public" in load["packaged-app"]["planner_text"] and "MIT" in load["packaged-app"]["planner_text"]
    for type_id in ("web-app", "website-property"):
        assert ("The repository is private" in load[type_id]["planner_text"] and "proprietary" in load[type_id]["planner_text"]) or "private repositories" in load[type_id]["planner_text"]
    assert "public for an MIT-licensed project" in load["other"]["planner_text"] and "private for anything proprietary" in load["other"]["planner_text"]


def test_every_type_asks_for_a_readme_with_diagrams_and_screenshots_made_by_a_person_or_the_pipeline():
    for type_id in ("web-app", "packaged-app", "website-property", "other"):
        t = pt.load()[type_id]
        assert ("Mermaid architecture diagram" in t["planner_text"] and "Playwright" in t["planner_text"] and "no browser" in t["planner_text"]) or ("concise README" in t["planner_text"] and "declared browser evidence" in t["planner_text"])
        assert "readme-and-docs.md" in t["guides"]
        assert any("Mermaid" in fp and "Playwright" in fp for fp in t["failure_points"])
        none = [story("a", "Code and tests")]
        assert {"readme-story", "screenshots-by-a-person-or-ci"} <= ids(pt.check(type_id, none))
        docs = [story("a", "Write the README with a Mermaid diagram and how-tos")]
        assert "readme-story" not in ids(pt.check(type_id, docs)) and "screenshots-by-a-person-or-ci" in ids(pt.check(type_id, docs))
        agent_shots = [story("a", "Capture the screenshots with Playwright", assignee="claude")]
        assert "screenshots-by-a-person-or-ci" in ids(pt.check(type_id, agent_shots))             # an agent cannot make them: it still needs the human or CI story
        assert "browser-checks-need-a-person" in ids(pt.check(type_id, agent_shots))
        writes = [story("a", "Write the Playwright screenshot script and the README that uses its images", assignee="claude")]
        assert "browser-checks-need-a-person" not in ids(pt.check(type_id, writes))                # writing the script is fine; running it is not


def test_a_website_preview_leaves_a_script_with_urls_a_health_file_and_a_check():
    t = pt.load()["website-property"]
    assert "tools/preview.sh" in t["planner_text"] and "tools/verify-preview.sh" in t["planner_text"] and "/health.txt" in t["planner_text"] and "host_action to \"preview-verify\"" in t["planner_text"] and "host_action \"preview-review\"" in t["planner_text"] and "trap" in t["planner_text"]
    assert any("authenticated remote link" in fp for fp in t["failure_points"])
    assert "authenticated dashboard proxy" in t["planner_text"] and "never SSH" in t["planner_text"]


def test_guides_are_general_plus_one_type_and_never_all_types(tmp_path):
    settings = type('S', (), {'data_dir': tmp_path})()
    local = pt.guidance_packet('local-website', settings)
    package = pt.guidance_packet('packaged-app', settings)
    other = pt.guidance_packet('other', settings)
    assert 'website-design-delivery.md' in local['guides']
    assert 'packaged-app-delivery.md' not in local['guides']
    assert 'web-app-delivery.md' not in local['guides']
    assert 'packaged-app-delivery.md' in package['guides']
    assert 'website-design-delivery.md' not in package['guides']
    assert other['guides'] == list(pt.GENERAL_GUIDES)
    assert all(len(p['text']) <= pt.GUIDANCE_BUDGET and p['bytes'] == len(p['text'].encode()) for p in (local,package,other))
    assert pt.guidance_packet('local-website',settings)['sha256'] == local['sha256']
    # Adding an unrelated override does not grow the selected context.
    folder = tmp_path/'project-types'; folder.mkdir()
    custom = dict(pt.load(settings)['packaged-app'], id='unrelated-product', label='Unrelated product')
    (folder/'unrelated-product.json').write_text(json.dumps(custom))
    assert pt.guidance_packet('local-website',settings) == local


def test_worker_guidance_is_private_stable_and_loaded_on_demand(tmp_path):
    settings=type('S',(),{'data_dir':tmp_path})()
    ref=pt.worker_reference(7,'local-website',settings)
    path=__import__('pathlib').Path(ref['path'])
    assert 'text' not in ref and path.is_file() and path.stat().st_mode & 0o777==0o600
    text=path.read_text()
    assert 'Website design [' in text and 'Delivering a packaged app' not in text
    before=path.stat().st_mtime_ns
    assert pt.worker_reference(7,'local-website',settings)==ref
    assert path.stat().st_mtime_ns==before
