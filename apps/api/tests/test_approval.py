from __future__ import annotations

import os
import subprocess

import approval


def test_outward_prompts_need_approval():
    assert approval.reasons_for("please git push the branch", "read", None) == ["prompt pushes or merges code"]
    assert approval.reasons_for("Deploy to prod", "read", None) == ["prompt deploys or releases"]
    assert approval.reasons_for("send an email to the customer", "read", None) == ["prompt contacts a person"]
    assert approval.reasons_for("post to discord about it", "read", None) == ["prompt contacts a person"]


def test_ordinary_prompts_do_not():
    assert approval.reasons_for("Summarize the README and list open TODOs", "read", None) == []
    assert approval.reasons_for("Fix the failing unit test in tests/test_x.py", "edit", "feature/x") == []


def test_editing_main_branch_needs_approval():
    assert approval.reasons_for("refactor", "edit", "main") == ["edits a repo on its main branch"]
    assert approval.reasons_for("refactor", "read", "main") == []


def test_workdir_must_be_inside_roots(tmp_path):
    root = tmp_path / "root"
    inside = root / "proj"
    inside.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert approval.resolve_workdir(str(inside), (root,)) == inside.resolve()
    assert approval.resolve_workdir(str(outside), (root,)) is None
    assert approval.resolve_workdir(str(root / "missing"), (root,)) is None
    assert approval.resolve_workdir(str(inside / ".." / ".." / "elsewhere"), (root,)) is None


def test_symlink_cannot_escape_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    os.symlink(outside, root / "link")
    assert approval.resolve_workdir(str(root / "link"), (root,)) is None


def test_current_branch(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    assert approval.current_branch(tmp_path) == "main"
    assert approval.current_branch(tmp_path / "nope") is None
