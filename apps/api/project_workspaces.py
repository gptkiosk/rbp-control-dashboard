"""Local Git worktrees for parallel project stories; never push or merge the source."""
import subprocess
from pathlib import Path
from fastapi import HTTPException
import approval

def git(path, *args):
    try:
        r = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(path), *args],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise HTTPException(409, 'Git workspace operation did not complete; inspect the project workspace.')
    if r.returncode:
        # No raw output: repository URLs, filters or hooks can contain secrets.
        raise HTTPException(409, 'Git workspace operation failed; inspect the project workspace and retry explicitly.')
    return r.stdout.strip()

def snapshot(path):
    root = git(path, 'rev-parse', '--show-toplevel')
    if Path(root).resolve() != Path(path).resolve():
        raise HTTPException(422, 'Parallel mode requires the repository root as the project working directory.')
    if git(path, 'status', '--porcelain'):
        raise HTTPException(409, 'Commit or stash source changes before approving parallel work. Each story starts from the reviewed commit.')
    return git(path, 'rev-parse', 'HEAD')

def location(project_id, revision, key, settings):
    # This remains under an existing allowlisted root, not an arbitrary model-supplied path.
    root = settings.workdir_roots[-1].expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / '.mcd-projects' / str(project_id) / str(revision) / key
    if not path.resolve().is_relative_to(root):
        raise HTTPException(422, 'Managed project workspaces must remain within the approved workspace root.')
    return path

def create(project_id, revision, key, source, commit, settings):
    path = location(project_id, revision, key, settings)
    branch = f'codex/mcd-{project_id}-r{revision}-{key}'
    if path.exists():
        if approval.current_branch(path) != branch or git(path, 'rev-parse', 'HEAD') != commit or git(path, 'status', '--porcelain'):
            raise HTTPException(409, 'An existing project workspace differs from the reviewed base. Inspect it before retrying dispatch.')
        return str(path), branch
    path.parent.mkdir(parents=True, exist_ok=True)
    git(source, 'worktree', 'add', '-b', branch, str(path), commit)
    return str(path), branch

def prepare(path, artifacts, existing):
    # Cherry-pick only operator-accepted commits from prerequisite stories. On conflict,
    # restore this story workspace and stop. No conflict resolution or source merge is inferred.
    commits = list(dict.fromkeys(c for a in artifacts for c in a.get('commits', [])))
    pending = [c for c in commits if c not in existing]
    if pending:
        if git(path, 'status', '--porcelain'):
            raise HTTPException(409, 'Story workspace has changes before prerequisite integration; inspect it first.')
        before = git(path, 'rev-parse', 'HEAD')
        try:
            # One commit at a time, dropping any that the story already has: `cherry-pick --empty=drop`
            # needs git 2.45, and Raspberry Pi OS and Ubuntu ship older versions.
            for commit in pending:
                try:
                    git(path, 'cherry-pick', commit)
                except HTTPException:
                    unresolved = git(path, 'diff', '--name-only', '--diff-filter=U')
                    if unresolved or git(path, 'status', '--porcelain'):
                        raise
                    git(path, 'cherry-pick', '--skip')   # the pick became empty: nothing to carry over
        except HTTPException:
            # git cherry-pick --abort restores all picks from this sequence.
            try: git(path, 'cherry-pick', '--abort')
            except HTTPException: pass
            if git(path, 'rev-parse', 'HEAD') != before:
                # Picks made before the conflict are ours and the workspace was clean when we started:
                # return to where it was, as one sequence would have.
                try: git(path, 'reset', '--hard', before)
                except HTTPException: pass
            if git(path, 'rev-parse', 'HEAD') != before:
                raise HTTPException(409, 'Prerequisite integration stopped. Inspect the story branch before retrying.')
            raise HTTPException(409, 'Accepted prerequisite commits conflict. Resolve the story workspace explicitly, then retry. The source branch was not changed.')
    return commits, git(path, 'rev-parse', 'HEAD')

def artifact(path, branch, starting_commit):
    if approval.current_branch(Path(path)) != branch:
        raise HTTPException(409, 'The story branch changed. Restore its approved branch before acceptance.')
    if git(path, 'status', '--porcelain'):
        raise HTTPException(409, 'Commit the reviewed story changes locally before accepting its handoff. Uncommitted files cannot be passed safely to dependent worktrees.')
    commits = git(path, 'rev-list', '--reverse', '--ancestry-path', starting_commit+'..HEAD').splitlines()
    git(path, 'merge-base', '--is-ancestor', starting_commit, 'HEAD')
    if len(commits)>100:
        raise HTTPException(409, 'This story exceeds 100 commits. Review and reduce its handoff before acceptance.')
    # Merge commits need explicit integration review, never guess a mainline for cherry-pick.
    if git(path, 'rev-list', '--merges', starting_commit+'..HEAD'):
        raise HTTPException(409, 'Merge commits require explicit integration; accept a linear story history.')
    return {'workspace':path,'branch':branch,'head':git(path,'rev-parse','HEAD'),'commits':commits,
            'files':git(path,'diff','--name-only',starting_commit,'HEAD').splitlines()}

def inspection(path):
    files=sorted(set(git(path,'diff','--name-only','HEAD').splitlines()+git(path,'ls-files','--others','--exclude-standard').splitlines()))
    if len(files)>500 or any('\n' in f or '\r' in f for f in files):
        raise HTTPException(409,'Too many or unsupported artifact paths; review the workspace outside MCD.')
    return {'files':files,'diff':git(path,'diff','--no-ext-diff','--no-textconv','HEAD')[:60000],
            'head':git(path,'rev-parse','HEAD')}

def snapshot_reviewed(path, files):
    changed=inspection(path)['files']
    if not files or len(files)!=len(set(files)) or set(files)!=set(changed):
        raise HTTPException(409,'Explicitly select every changed file for this handoff, or commit/revert it outside MCD. The snapshot must leave a clean story workspace.')
    if any(Path(f).is_absolute() or '..' in Path(f).parts or not f for f in files):
        raise HTTPException(422,'Artifact paths must stay within the story workspace.')
    git(path,'add','--',*files)
    git(path,'-c','user.name=MCD reviewed handoff','-c','user.email=mcd@localhost','commit','-m','MCD operator-accepted story handoff','--',*files)
