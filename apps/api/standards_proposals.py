"""Additions to a repository's standards that the coordinator proposes and the operator approves.

Same shape as housekeeping: a model reads and explains, fixed code decides and acts. Hermes proposes an ADDITION (a table row, a check, a
security bullet or a tightening rule). The server composes the new file text itself, proves it only adds (no removed or reworded line, no area
lowered or rerouted, no check dropped, no rule loosened), freezes the diff and the hash of the file it was made against, and waits. On the
operator's approval the app re-checks both, then commits the change on a NEW branch in a temporary worktree. It never writes to the current
branch or the working tree, and it never pushes: the branch is reviewed and merged like any other change to the repository.
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import time
from pathlib import Path

from sqlalchemy import select

import standards
from failure_mining import redact
from models import StandardsProposal

MAX_PATCH = 20000


class ProposalError(ValueError):
    pass


def proposal_dict(p: StandardsProposal) -> dict:
    return {"id": p.id, "created_at": p.created_at, "created_by": p.created_by, "project_id": p.project_id, "summary": p.summary, "section": p.section,
            "patch": p.patch, "status": p.status, "decided_at": p.decided_at, "decided_by": p.decided_by,
            "result": json.loads(p.result) if p.result else None}


def for_project(s, project_id: int) -> list[StandardsProposal]:
    return list(s.scalars(select(StandardsProposal).where(StandardsProposal.project_id == project_id).order_by(StandardsProposal.id.desc()).limit(20)))


def _current(workdir):
    try:
        got = standards._read(workdir)
    except (ValueError, OSError) as error:
        raise ProposalError(str(error)) from None
    if got is None:
        raise ProposalError(f"This repository has no {standards.FILE}. Standards are created by a normal change in the repository; additions can be proposed once it exists.")
    return got


def propose(s, owner: str, project_id: int, workdir, section: str, items: list[dict], summary: str, now: int | None = None) -> StandardsProposal:
    now = int(now if now is not None else time.time())
    text, digest = _current(workdir)
    try:
        new = standards.compose_addition(text, section, items)
    except standards.AdditionError as error:
        raise ProposalError(str(error)) from None
    problems = standards.additive_problems(text, new)
    if problems or new == text:
        raise ProposalError('Not a pure addition: ' + ('; '.join(problems[:3]) or 'nothing would change'))
    patch = ''.join(difflib.unified_diff(text.splitlines(True), new.splitlines(True), fromfile=standards.FILE, tofile=standards.FILE + ' (proposed)', n=2))[:MAX_PATCH]
    existing = s.scalar(select(StandardsProposal).where(StandardsProposal.project_id == project_id, StandardsProposal.status == "pending",
                                                        StandardsProposal.new_text == new))
    if existing:
        return existing
    row = StandardsProposal(created_at=now, created_by=owner, project_id=project_id, summary=redact(summary, 500) or 'Addition to the standards', section=section,
                            base_sha256=digest, patch=patch, new_text=new, status="pending")
    s.add(row)
    s.commit()
    return row


def _git(path, *args):
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(path), *args], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ProposalError('git could not do that: ' + (result.stderr.strip().splitlines() or ['unknown'])[-1][:160])
    return result.stdout.strip()


def _commit_on_new_branch(data_dir: Path, workdir, row: StandardsProposal, actor: str) -> dict:
    root = Path(_git(workdir, 'rev-parse', '--show-toplevel')).resolve()
    if root != Path(workdir).resolve():
        raise ProposalError("The project's working directory must be the repository root.")
    branch = f"standards/{row.id}-{re.sub(r'[^a-z0-9]+', '-', row.section)}"
    if subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', '-q', f'refs/heads/{branch}'], capture_output=True).returncode == 0:
        raise ProposalError(f'The branch {branch} already exists.')
    work = Path(data_dir) / 'standards-proposals' / str(row.id)
    work.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if work.exists():
        raise ProposalError('A previous attempt left a working folder; remove it and approve again.')
    _git(root, 'worktree', 'add', '-q', '-b', branch, str(work), 'HEAD')
    try:
        (work / standards.FILE).write_text(row.new_text, encoding='utf-8')
        _git(work, 'add', '--', standards.FILE)
        _git(work, 'commit', '-q', '-m', f'Standards: {row.summary[:60]}\n\nProposed by the coordinator, approved by {actor}. Addition only.')
        commit = _git(work, 'rev-parse', 'HEAD')
    except ProposalError:
        subprocess.run(['git', '-C', str(root), 'worktree', 'remove', '--force', str(work)], capture_output=True)
        subprocess.run(['git', '-C', str(root), 'branch', '-D', branch], capture_output=True)
        raise
    subprocess.run(['git', '-C', str(root), 'worktree', 'remove', '--force', str(work)], capture_output=True)
    return {"branch": branch, "commit": commit, "file": standards.FILE,
            "note": "Committed on a new branch. Nothing was pushed and your current branch and files are unchanged. Review it and open a pull request like any other change."}


def decide(s, data_dir: Path, proposal_id: int, approve: bool, actor: str, workdir, now: int | None = None) -> StandardsProposal:
    now = int(now if now is not None else time.time())
    row = s.get(StandardsProposal, proposal_id)
    if row is None or row.status != "pending":
        raise ProposalError("That proposal is not waiting for a decision.")
    row.decided_at, row.decided_by = now, actor
    if not approve:
        row.status = "rejected"
        s.commit()
        return row
    try:
        text, digest = _current(workdir)
        if digest != row.base_sha256:
            raise ProposalError("The standards file changed after this was proposed. Ask for a new proposal against the current file.")
        problems = standards.additive_problems(text, row.new_text)
        if problems:
            raise ProposalError('No longer a pure addition: ' + '; '.join(problems[:3]))
        result = _commit_on_new_branch(Path(data_dir), workdir, row, actor)
        row.status, row.result = "applied", json.dumps(result)
    except (ProposalError, OSError, subprocess.SubprocessError) as error:
        row.status, row.result = "failed", json.dumps({"reason": str(error)[:300]})
    s.commit()
    return row
