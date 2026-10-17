"""Branch-scoped git grants: validation, agent command lines, context text, hooks and helper."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_git
from agents import build_claude, build_codex

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "agent-git"
HOOKS = SCRIPTS / "hooks"
GOOD = {"5": {"clones": [{"dir": "mcd", "repo": "gptkiosk/mac-control-dashboard",
                          "branch": "project-5/installable-releases"}]}}


def write(tmp_path, data):
    f = tmp_path / "grants.json"
    f.write_text(json.dumps(data) if not isinstance(data, str) else data)
    return f


def card(agent="claude", mode="edit", **kw):
    return SimpleNamespace(agent=agent, mode=mode, working_dir="/w", **kw)


# ------------------------------------------------------------------ grant file


def test_valid_grant_loads(tmp_path):
    g = agent_git.load(write(tmp_path, GOOD))[5]
    assert g.project_id == 5 and g.clones[0].dir == "mcd" and g.clones[0].branch == "project-5/installable-releases"


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(branch="main"),                              # never main
    lambda c: c.update(branch="project-6/other"),                   # branch must carry this project's id
    lambda c: c.update(branch="project-5/../main"),
    lambda c: c.update(dir="../escape"),                            # clone must sit directly under the workdir
    lambda c: c.update(dir="a/b"),
    lambda c: c.update(dir=".."),
    lambda c: c.update(repo="not a repo"),
])
def test_invalid_entries_grant_nothing(tmp_path, mutate):
    data = json.loads(json.dumps(GOOD)); mutate(data["5"]["clones"][0])
    assert agent_git.load(write(tmp_path, data)) == {}


def test_bad_files_and_limits_grant_nothing(tmp_path):
    assert agent_git.load(tmp_path / "missing.json") == {}
    assert agent_git.load(write(tmp_path, "{not json")) == {}
    assert agent_git.load(write(tmp_path, "[]")) == {}
    many = json.loads(json.dumps(GOOD)); many["5"]["clones"] = many["5"]["clones"] * 5
    assert agent_git.load(write(tmp_path, many)) == {}
    dup = json.loads(json.dumps(GOOD)); dup["5"]["clones"] = dup["5"]["clones"] * 2
    assert agent_git.load(write(tmp_path, dup)) == {}
    bad_cmd = json.loads(json.dumps(GOOD)); bad_cmd["5"]["commands"] = ["Bash(rm -rf /;)"]
    assert agent_git.load(write(tmp_path, bad_cmd)) == {}
    assert agent_git.load(write(tmp_path, {"x": GOOD["5"]})) == {}


def test_one_bad_entry_does_not_hide_a_good_one(tmp_path):
    data = {**GOOD, "6": {"clones": [{"dir": "x", "repo": "a/b", "branch": "main"}]}}
    assert set(agent_git.load(write(tmp_path, data))) == {5}


def test_grant_for_skips_read_mode_and_managers(tmp_path):
    s = SimpleNamespace(agent_git_grants_file=write(tmp_path, GOOD))
    assert agent_git.grant_for(s, 5, card("claude", "edit")) is not None
    assert agent_git.grant_for(s, 5, card("claude", "read")) is None
    assert agent_git.grant_for(s, 5, card("hermes", "edit")) is None
    assert agent_git.grant_for(s, 6, card("claude", "edit")) is None
    assert agent_git.grant_for(SimpleNamespace(), 5, card()) is None


# ------------------------------------------------------------------ agent command lines


def grant(tmp_path):
    return agent_git.load(write(tmp_path, GOOD))[5]


def test_claude_without_grant_is_unchanged():
    argv = build_claude(card(), "p", "claude-haiku-5-5", 1.0, "claude")
    d = argv[argv.index("--disallowedTools") + 1:argv.index("--disallowedTools") + 4]
    assert d == ["Bash(git push:*)", "Bash(git merge:*)", "Bash(gh pr merge:*)"]
    assert argv[argv.index("--allowedTools") + 1:argv.index("--allowedTools") + 3] == ["WebSearch", "WebFetch"]
    assert not any(a.startswith("Bash(git -C") for a in argv)


def test_claude_with_grant_allows_one_exact_push_and_keeps_merge_denied(tmp_path):
    argv = build_claude(card(agent_git_grant=grant(tmp_path)), "p", "m", 1.0, "claude")
    assert "Bash(git -C mcd push origin project-5/installable-releases)" in argv
    assert "Bash(git -C mcd commit:*)" in argv
    assert "Bash(git push:*)" not in argv                    # a blanket deny would beat the exact allow
    assert "Bash(git merge:*)" in argv and "Bash(gh pr merge:*)" in argv
    assert "Bash(git -C mcd push --force:*)" in argv and "Bash(git -C mcd tag:*)" in argv
    # nothing grants a push of another ref
    assert not any("push origin main" in a for a in argv)
    assert not any(a in {"Bash(git push:*)", "Bash(git:*)", "Bash(gh:*)", "Bash(*)"} for a in argv)


def test_claude_output_only_never_gets_git(tmp_path):
    argv = build_claude(card(agent_git_grant=grant(tmp_path), output_only=True), "p", "m", 1.0, "claude")
    assert not any(a.startswith("Bash(git -C") for a in argv)


def test_codex_without_grant_is_unchanged():
    argv = build_codex(card("codex"), "p", "gpt-6-luna", 1.0, "codex")
    assert argv[:4] == ["codex", "exec", "--json", "--skip-git-repo-check"] and "-s" in argv
    assert "workspace-write" in argv and not any("agentgit" in a for a in argv)


def test_codex_with_grant_uses_the_permission_profile(tmp_path):
    argv = build_codex(card("codex", agent_git_grant=grant(tmp_path)), "p", "gpt-6-luna", 1.0, "codex")
    assert "-s" not in argv and "danger-full-access" not in " ".join(argv)
    assert 'default_permissions="agentgit"' in argv and 'permissions.agentgit.extends=":workspace"' in argv
    net = next(a for a in argv if a.startswith("permissions.agentgit.network="))
    assert '"github.com"="allow"' in net and "example.com" not in net and '"*"' not in net
    fs = next(a for a in argv if a.startswith("permissions.agentgit.filesystem="))
    # .git is writable so a story can cut its branch and commit; hooks and config stay read-only
    assert '".git"="write"' in fs and '".git/hooks"="read"' in fs and '".git/config"="read"' in fs and '"/"' not in fs
    resumed = build_codex(card("codex", agent_git_grant=grant(tmp_path)), "p", "m", 1.0, "codex", session_id="s1")
    assert 'default_permissions="agentgit"' in resumed and not any(a.startswith("sandbox_mode") for a in resumed)


def test_codex_read_mode_has_no_grant_so_stays_read_only():
    argv = build_codex(card("codex", mode="read"), "p", "m", 1.0, "codex")
    assert "read-only" in argv


# ------------------------------------------------------------------ context


def test_context_replaces_the_no_push_sentence(tmp_path):
    g = grant(tmp_path)
    prompt = f"before. {agent_git.NO_PUSH_SENTENCE} after."
    out = agent_git.apply_context(prompt, g, 77, "codex", "gpt-6-luna")
    assert agent_git.NO_PUSH_SENTENCE not in out and out.startswith("before.") and out.endswith("after.")
    for needle in ("MCD-Project: 5", "MCD-Story: #77", "MCD-Agent: codex/gpt-6-luna",
                   "git -C mcd push origin project-5/installable-releases", "small commits", "Never merge"):
        assert needle in out
    assert agent_git.apply_context("no sentence here", g, 1, "claude", None).startswith("no sentence here\n")


# ------------------------------------------------------------------ hooks and helper (real git)


def git(cwd, *args, env=None, check=True):
    e = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
         "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", **(env or {})}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=e, check=check)


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    git(work, "config", "user.name", "t"); git(work, "config", "user.email", "t@example.com")
    (work / "README.md").write_text("hi\n")
    git(work, "add", "README.md"); git(work, "commit", "-q", "-m", "chore: init")
    git(work, "push", "-q", "origin", "HEAD:main")
    git(work, "switch", "-q", "-c", "project-5/x")
    git(work, "config", "core.hooksPath", str(HOOKS))
    git(work, "config", "mcd.branch", "project-5/x")
    git(work, "config", "mcd.remoteRegex", ".*origin\\.git$")
    git(work, "config", "--type=bool", "mcd.requireTrailers", "true")
    return work


ENV = lambda tmp_path: {"MCD_AGENT_GIT_STATE": str(tmp_path / "state")}   # noqa: E731
TRAILERS = "\n\nMCD-Project: 5\nMCD-Story: #7\n"


def commit(repo, subject, body=TRAILERS, check=False):
    return git(repo, "commit", "-q", "-m", subject + body, check=check)


def test_commit_message_rules(repo):
    (repo / "a.txt").write_text("a\n"); git(repo, "add", "a.txt")
    assert commit(repo, "added stuff").returncode != 0                                   # not conventional
    assert commit(repo, "feat: " + "x" * 80).returncode != 0                             # too long
    assert commit(repo, "feat(update): add check", body="").returncode != 0              # trailers missing
    ok = commit(repo, "feat(update): add check")
    assert ok.returncode == 0, ok.stderr


def test_commit_size_cap_and_excluded_files(repo):
    (repo / "big.txt").write_text("line\n" * 500); git(repo, "add", "big.txt")
    r = commit(repo, "feat: big")
    assert r.returncode != 0 and "limit 400" in r.stderr
    git(repo, "reset", "-q")
    (repo / "package-lock.json").write_text("x\n" * 5000)                                  # lock files do not count
    (repo / "small.txt").write_text("ok\n")
    git(repo, "add", "package-lock.json", "small.txt")
    assert commit(repo, "chore: deps").returncode == 0


def test_push_gate(repo, tmp_path):
    env = ENV(tmp_path)
    (repo / "a.md").write_text("doc\n"); git(repo, "add", "a.md"); assert commit(repo, "docs: a").returncode == 0
    assert git(repo, "push", "-q", "origin", "project-5/x", env=env, check=False).returncode == 0     # the branch
    assert git(repo, "push", "-q", "origin", "HEAD:main", env=env, check=False).returncode != 0      # never main
    assert git(repo, "push", "-q", "origin", "HEAD:refs/heads/other", env=env, check=False).returncode != 0
    assert git(repo, "push", "-q", "origin", ":project-5/x", env=env, check=False).returncode != 0   # no delete
    git(repo, "tag", "v1.0.0"); assert git(repo, "push", "-q", "origin", "v1.0.0", env=env, check=False).returncode != 0
    git(repo, "tag", "v1.0.1-rc.1"); assert git(repo, "push", "-q", "origin", "v1.0.1-rc.1", env=env, check=False).returncode != 0
    git(repo, "config", "--type=bool", "mcd.allowRcTags", "true")
    assert git(repo, "push", "-q", "origin", "v1.0.1-rc.1", env=env, check=False).returncode == 0     # rc only when granted


def test_force_push_is_refused(repo, tmp_path):
    env = ENV(tmp_path)
    (repo / "a.md").write_text("1\n"); git(repo, "add", "a.md"); commit(repo, "docs: one")
    assert git(repo, "push", "-q", "origin", "project-5/x", env=env, check=False).returncode == 0
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    (repo / "b.md").write_text("2\n"); git(repo, "add", "b.md"); commit(repo, "docs: two")
    r = git(repo, "push", "-q", "--force", "origin", "project-5/x", env=env, check=False)
    assert r.returncode != 0 and "non-fast-forward" in r.stderr


def test_wrong_remote_and_ungranted_clone(repo, tmp_path):
    env = ENV(tmp_path)
    (repo / "a.md").write_text("doc\n"); git(repo, "add", "a.md"); commit(repo, "docs: a")
    git(repo, "config", "mcd.remoteRegex", "^https://github\\.com/nobody/nothing$")
    assert "not one of the granted" in git(repo, "push", "-q", "origin", "project-5/x", env=env, check=False).stderr
    git(repo, "config", "mcd.remoteRegex", ".*origin\\.git$"); git(repo, "config", "--unset", "mcd.branch")
    assert "not granted" in git(repo, "push", "-q", "origin", "project-5/x", env=env, check=False).stderr


def test_push_rate_limit(repo, tmp_path):
    env = ENV(tmp_path)
    git(repo, "config", "--int", "mcd.maxPushesPerHour", "2")
    for i in range(2):
        (repo / f"d{i}.md").write_text("x\n"); git(repo, "add", "."); commit(repo, f"docs: d{i}")
        assert git(repo, "push", "-q", "origin", "project-5/x", env=env, check=False).returncode == 0
    (repo / "d9.md").write_text("x\n"); git(repo, "add", "."); commit(repo, "docs: d9")
    r = git(repo, "push", "-q", "origin", "project-5/x", env=env, check=False)
    assert r.returncode != 0 and "Batch your commits" in r.stderr


def test_pre_push_runs_the_suite_only_for_code_changes(repo, tmp_path):
    env = ENV(tmp_path)
    git(repo, "config", "mcd.prePushCmd", "false")                                          # a failing suite
    (repo / "notes.md").write_text("doc\n"); git(repo, "add", "."); commit(repo, "docs: notes")
    assert git(repo, "push", "-q", "origin", "project-5/x", env=env, check=False).returncode == 0   # docs skip it
    (repo / "mod.py").write_text("x = 1\n"); git(repo, "add", "."); commit(repo, "feat: mod")
    r = git(repo, "push", "-q", "origin", "project-5/x", env=env, check=False)
    assert r.returncode != 0 and "local test command failed" in r.stderr
    git(repo, "config", "mcd.prePushCmd", "true")
    assert git(repo, "push", "-q", "origin", "project-5/x", env=env, check=False).returncode == 0


def run_helper(stdin, token_file):
    return subprocess.run([str(SCRIPTS / "git-credential-mcd-agent"), "get"], input=stdin, text=True,
                          capture_output=True, env={"PATH": os.environ["PATH"], "MCD_AGENT_GIT_TOKEN_FILE": str(token_file)})


def test_credential_helper_serves_only_the_two_repos(tmp_path):
    tok = tmp_path / "token"; tok.write_text("fake-token-value\n")
    for path in ("gptkiosk/mac-control-dashboard.git", "gptkiosk/rbp-control-dashboard"):
        r = run_helper(f"protocol=https\nhost=github.com\npath={path}\n\n", tok)
        assert "password=fake-token-value" in r.stdout and "username=x-access-token" in r.stdout
    for stdin in ("protocol=https\nhost=github.com\npath=gptkiosk/some-other-repo.git\n\n",
                  "protocol=https\nhost=github.com\npath=other/mac-control-dashboard.git\n\n",
                  "protocol=https\nhost=example.com\npath=gptkiosk/mac-control-dashboard.git\n\n",
                  "protocol=http\nhost=github.com\npath=gptkiosk/mac-control-dashboard.git\n\n",
                  "protocol=https\nhost=github.com\n\n"):
        assert run_helper(stdin, tok).stdout == ""
    assert run_helper("protocol=https\nhost=github.com\npath=gptkiosk/mac-control-dashboard\n\n", tmp_path / "none").stdout == ""
    assert subprocess.run([str(SCRIPTS / "git-credential-mcd-agent"), "store"], input="x", text=True,
                          capture_output=True).stdout == ""


def test_setup_clone_wires_a_clone_without_pushing(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    dest = tmp_path / "work" / "mcd"; dest.parent.mkdir()
    subprocess.run(["git", "clone", "-q", str(origin), str(dest)], check=True, capture_output=True)
    git(dest, "config", "user.name", "t"); git(dest, "config", "user.email", "t@example.com")
    (dest / "README.md").write_text("hi\n"); git(dest, "add", "."); git(dest, "commit", "-q", "-m", "chore: init")
    git(dest, "push", "-q", "origin", "HEAD:main")
    agent_dir = tmp_path / "agent-git"
    r = subprocess.run([str(SCRIPTS / "setup-clone.sh"), "--repo", "gptkiosk/mac-control-dashboard", "--dest", str(dest),
                        "--project", "5", "--slug", "installable-releases", "--allow-rc-tags"],
                       capture_output=True, text=True, env={**os.environ, "MCD_AGENT_GIT_DIR": str(agent_dir)})
    assert r.returncode == 0, r.stderr
    cfg = lambda k: git(dest, "config", "--get", k).stdout.strip()   # noqa: E731
    assert git(dest, "branch", "--show-current").stdout.strip() == "project-5/installable-releases"
    assert cfg("mcd.branch") == "project-5/installable-releases" and cfg("mcd.baseTag") == "project-5-base"
    assert cfg("core.hooksPath") == str(agent_dir / "hooks") and cfg("credential.useHttpPath") == "true"
    assert cfg("mcd.allowRcTags") == "true" and cfg("push.default") == "nothing"
    assert (agent_dir / "hooks" / "pre-push").stat().st_mode & 0o111
    assert "project-5-base" in git(dest, "tag").stdout
    assert git(origin, "branch", "--list", "project-5/*").stdout.strip() == ""          # nothing was pushed
    bad = subprocess.run([str(SCRIPTS / "setup-clone.sh"), "--repo", "someone/else", "--dest", str(dest),
                          "--project", "5", "--slug", "x"], capture_output=True, text=True)
    assert bad.returncode == 2


# ------------------------------------------------------------------ through the dispatcher

from sqlalchemy import select                                    # noqa: E402
from dispatcher import Dispatcher                                # noqa: E402
from models import Card, Run                                     # noqa: E402
from projects import ProjectMemory                               # noqa: E402
from tests.test_projects import app, active, node                # noqa: E402,F401  (fixtures and helpers)


def story_id(p):
    return next(t["card_id"] for t in p["tasks"] if t["role"] == "story")


def claim_edit_story(app, nodes, grants=None, tmp_path=None):
    c, s, wd, settings = app
    p = active(app, nodes)
    if grants is not None:
        data = {str(p["id"]): {"clones": [{"dir": "mcd", "repo": "gptkiosk/mac-control-dashboard",
                                          "branch": f"project-{p['id']}/installable-releases"}]}}
        settings.agent_git_grants_file = write(tmp_path, data)
    cid = story_id(p)
    with s.begin() as db:
        db.get(Card, cid).mode = "edit"
    assert len(Dispatcher(s, settings)._claim(1)) == 1
    with s() as db:
        run = db.scalar(select(Run).where(Run.card_id == cid).order_by(Run.id.desc()))
        ctx = db.scalar(select(ProjectMemory).where(ProjectMemory.card_id == cid, ProjectMemory.kind == "context")).text
        return p["id"], cid, json.loads(run.command), json.loads(run.checkpoint), ctx


def test_dispatcher_grants_a_project_story_git_access_and_records_it(app, tmp_path):
    pid, cid, cmd, checkpoint, ctx = claim_edit_story(app, [node("a")], grants=True, tmp_path=tmp_path)
    assert 'default_permissions="agentgit"' in cmd and "-s" not in cmd           # codex story: profile, not workspace-write
    assert checkpoint["agent_git"] == [{"dir": "mcd", "repo": "gptkiosk/mac-control-dashboard",
                                        "branch": f"project-{pid}/installable-releases"}]
    assert "GIT ACCESS FOR THIS PROJECT" in ctx and f"MCD-Story: #{cid}" in ctx
    assert agent_git.NO_PUSH_SENTENCE not in ctx
    assert "MCD PREVIEW SAFETY" in ctx                                             # the rest of the shared context is kept


def test_dispatcher_claude_story_gets_exact_git_allows(app, tmp_path):
    pid, cid, cmd, checkpoint, ctx = claim_edit_story(
        app, [dict(node("a"), assignee="claude", model="claude-haiku-5-5")], grants=True, tmp_path=tmp_path)
    assert f"Bash(git -C mcd push origin project-{pid}/installable-releases)" in cmd
    assert "Bash(git push:*)" not in cmd and "Bash(git merge:*)" in cmd


def test_dispatcher_without_a_grant_keeps_the_no_push_rule(app):
    pid, cid, cmd, checkpoint, ctx = claim_edit_story(app, [node("a")])
    assert "agent_git" not in checkpoint and not any("agentgit" in a for a in cmd)
    assert 'default_permissions="agentwork"' in cmd and "-s" not in cmd              # the working default: workspace sandbox plus the package indexes and GitHub
    assert not any("filesystem" in a for a in cmd)                                      # no .git rule without a grant
    assert agent_git.NO_PUSH_SENTENCE in ctx and "GIT ACCESS FOR THIS PROJECT" not in ctx


def test_strict_permissions_give_codex_its_plain_sandbox_and_claude_only_the_operators_commands(app, monkeypatch):
    c, s, wd, settings = app
    monkeypatch.setattr(settings, "agent_permissions", "strict")
    pid, cid, cmd, checkpoint, ctx = claim_edit_story(app, [node("a")])
    assert "workspace-write" in cmd and not any("agentwork" in a or "agentgit" in a for a in cmd)


def test_strict_permissions_give_claude_only_the_operators_own_commands(app, monkeypatch):
    c, s, wd, settings = app
    monkeypatch.setattr(settings, "agent_permissions", "strict")
    pid, cid, cmd, checkpoint, ctx = claim_edit_story(app, [dict(node("b"), assignee="claude", model="claude-haiku-5-5")])
    assert not any(a.startswith("Bash(node") or a.startswith("Bash(python3") or a.startswith("Bash(npm") for a in cmd) and "Bash(git push:*)" in cmd


def test_operator_extra_commands_and_domains_are_validated_and_added(app, monkeypatch):
    c, s, wd, settings = app
    monkeypatch.setattr(settings, "agent_extra_commands", ("Bash(make test:*)", "rm -rf /", "Bash(curl $(x))"))
    monkeypatch.setattr(settings, "agent_extra_network_domains", ("cdn.example.org", "bad domain", "localhost"))
    assert "Bash(make test:*)" in agent_git.allowed_commands(settings) and not any("rm -rf" in x or "curl" in x for x in agent_git.allowed_commands(settings))
    assert "cdn.example.org" in agent_git.network_domains(settings) and "bad domain" not in agent_git.network_domains(settings) and "localhost" not in agent_git.network_domains(settings)
    pid, cid, cmd, checkpoint, ctx = claim_edit_story(app, [dict(node("a"), assignee="claude", model="claude-haiku-5-5")])
    assert "Bash(make test:*)" in cmd and "Bash(npm ci:*)" in cmd and "Bash(git push:*)" in cmd      # extras and installs added, push still denied


def test_dispatcher_ignores_a_grant_for_another_project(app, tmp_path):
    c, s, wd, settings = app
    p = active(app, [node("a")])
    data = {str(p["id"] + 1): {"clones": [{"dir": "mcd", "repo": "gptkiosk/mac-control-dashboard",
                                          "branch": f"project-{p['id'] + 1}/x"}]}}
    settings.agent_git_grants_file = write(tmp_path, data)
    cid = story_id(p)
    with s.begin() as db:
        db.get(Card, cid).mode = "edit"
    assert len(Dispatcher(s, settings)._claim(1)) == 1
    with s() as db:
        run = db.scalar(select(Run).where(Run.card_id == cid))
        assert "agent_git" not in json.loads(run.checkpoint)


def test_setup_clone_can_cut_the_project_branch_from_a_baseline(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    dest = tmp_path / "w" / "mcd"; dest.parent.mkdir()
    subprocess.run(["git", "clone", "-q", str(origin), str(dest)], check=True, capture_output=True)
    git(dest, "config", "user.name", "t"); git(dest, "config", "user.email", "t@example.com")
    (dest / "a.txt").write_text("1\n"); git(dest, "add", "."); git(dest, "commit", "-q", "-m", "chore: init"); git(dest, "push", "-q", "origin", "HEAD:main")
    git(dest, "switch", "-q", "-c", "baseline/x"); (dest / "b.txt").write_text("2\n"); git(dest, "add", "."); git(dest, "commit", "-q", "-m", "chore: baseline")
    git(dest, "push", "-q", "origin", "baseline/x"); git(dest, "switch", "-q", "main")
    r = subprocess.run([str(SCRIPTS / "setup-clone.sh"), "--repo", "gptkiosk/rbp-control-dashboard", "--dest", str(dest), "--project", "7",
                        "--slug", "demo", "--from", "origin/baseline/x"], capture_output=True, text=True,
                       env={**os.environ, "MCD_AGENT_GIT_DIR": str(tmp_path / "ag")})
    assert r.returncode == 0, r.stderr
    assert (dest / "b.txt").exists() and git(dest, "branch", "--show-current").stdout.strip() == "project-7/demo"
    assert git(dest, "rev-parse", "project-7-base^{commit}").stdout == git(dest, "rev-parse", "origin/baseline/x").stdout


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("codex"), reason="needs the Codex seatbelt sandbox")
def test_real_codex_sandbox_lets_a_story_cut_its_branch_but_not_touch_hooks(tmp_path):
    """Drift guard: Codex changed what `:workspace` protects once and stories could no longer create their branch."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    probe = ("import os,sys\n"
             "for p in ('.git/refs/heads/x','.git/hooks/x','.git/config'):\n"
             "    try: open(p,'a').close(); print('ok',p)\n"
             "    except OSError: print('denied',p)\n"
             "os.remove('.git/refs/heads/x')\n")
    argv = ["codex", "sandbox", *[a for o in agent_git.codex_overrides() for a in ("-c", o)], "--", sys.executable, "-c", probe]
    out = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=60).stdout
    assert "ok .git/refs/heads/x" in out and "denied .git/hooks/x" in out and "denied .git/config" in out, out


def test_an_edit_claude_story_without_a_grant_can_run_checks_but_never_git_and_a_read_story_gets_no_shell():
    plain = SimpleNamespace(mode="edit", agent="claude", agent_git_grant=None, output_only=False, subscription_billing=True, timeout_s=60)
    argv = build_claude(plain, "p", "claude-haiku-5-5", 1.0, "claude")
    allowed = argv[argv.index("--allowedTools") + 1:]
    assert "Bash(node --check:*)" in allowed and "Bash(python3 -I -m pytest:*)" in allowed and "Bash(python3 -I -m unittest:*)" in allowed
    assert not any(a.startswith("Bash(git") or "curl" in a or a in ("Bash", "Bash(*)") for a in allowed) and "Bash(git push:*)" in argv   # git stays denied
    read = SimpleNamespace(mode="read", agent="claude", agent_git_grant=None, output_only=False, subscription_billing=True, timeout_s=60)
    assert not any(a.startswith("Bash(") for a in build_claude(read, "p", "m", 1.0, "claude")[build_claude(read, "p", "m", 1.0, "claude").index("--allowedTools"):])
    out = SimpleNamespace(mode="read", agent="claude", agent_git_grant=None, output_only=True, subscription_billing=True, timeout_s=60)
    assert "--allowedTools" not in build_claude(out, "p", "m", 1.0, "claude")


def test_hermes_edit_stories_are_told_the_task_folder_because_its_terminal_starts_elsewhere():
    from agents import build_hermes
    edit = SimpleNamespace(agent="hermes", mode="edit", working_dir="/work/scratch-demo", timeout_s=60)
    prompt = build_hermes(edit, "do the story", "m", 1.0, "hermes")[3]
    assert prompt.startswith("Task folder: /work/scratch-demo") and "cd /work/scratch-demo &&" in prompt and prompt.endswith("do the story")
    read = SimpleNamespace(agent="hermes", mode="read", working_dir="/work/scratch-demo", timeout_s=60)
    assert build_hermes(read, "plan it", "m", 1.0, "hermes")[3] == "plan it"
    assert "echo" in " ".join(agent_git.CHECK_COMMANDS)
