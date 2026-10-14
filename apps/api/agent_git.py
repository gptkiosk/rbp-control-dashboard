"""Branch-scoped git grants for project stories.

A grant lets agents commit and push in named clones on one project branch, and nothing
else. Grants are operator configuration: a file in the data folder that the operator edits,
never plan output, never agent output, and never part of the approved manifest. An invalid
file or entry grants nothing.

    ~/.rcd-control/agent-git/grants.json
    {"5": {"clones": [{"dir": "rbp-control-dashboard",
                       "repo": "gptkiosk/rbp-control-dashboard",
                       "branch": "project-5/installable-releases"}],
           "commands": ["Bash(limactl list:*)"]}}

``dir`` is a clone directly under the story's working directory. The branch must be
``project-<id>/<slug>`` for the same project id, so a grant can never name ``main``.

What a grant changes for an Edit-mode story of an approved project:
  * Claude is allowed exact git commands for those clones (including the single push of the
    project branch) plus test commands. Merge and release commands stay denied.
  * Codex runs with a custom permission profile (writable .git, network limited to GitHub and
    the package indexes) instead of the plain workspace-write sandbox.
  * The shared context tells the agent what it may commit and push, in place of "do not push".
Operator-owned hooks and a credential helper (scripts/agent-git) enforce commit size,
message format, the push gate and a push rate limit. They are guidance and a safety net, not a
security boundary: an agent with a full shell can bypass them, and until GitHub rulesets exist
the token itself can write wherever its owner can.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("mac_control.agent_git")

DIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
BRANCH_RE = re.compile(r"^project-(\d+)/[a-z0-9][a-z0-9.-]{0,40}$")
COMMAND_RE = re.compile(r"^Bash\([A-Za-z0-9 ._/:*=@+-]{1,120}\)$")
MAX_CLONES = 4
MAX_COMMANDS = 20
GRANTED_AGENTS = {"claude", "codex", "grok", "openclaw"}

# What the sentence in the shared project context says when no grant exists.
NO_PUSH_SENTENCE = ("Do not commit, push or merge automatically; the operator reviews and "
                    "snapshots worktree changes at acceptance.")

GIT_SUBCOMMANDS = ("status", "diff", "log", "show", "add", "commit", "restore", "rev-parse", "fetch origin")
DEFAULT_COMMANDS = (
    "Bash(cd:*)",
    "Bash(python3 -I -m pytest:*)",
    "Bash(.venv/bin/python -m pytest:*)",
    "Bash(npm run test:*)",
    "Bash(npm run type-check:*)",
    "Bash(npm run build:*)",
    "Bash(npx vitest:*)",
    "Bash(bash -n:*)",
    "Bash(shasum:*)",
)
CODEX_DOMAINS = ("github.com", "api.github.com", "codeload.github.com", "objects.githubusercontent.com",
                 "pypi.org", "files.pythonhosted.org", "registry.npmjs.org")


@dataclass(frozen=True)
class Clone:
    dir: str
    repo: str
    branch: str


@dataclass(frozen=True)
class Grant:
    project_id: int
    clones: tuple[Clone, ...]
    commands: tuple[str, ...] = ()


def _entry(key: str, value: object) -> Grant | None:
    if not key.isdigit() or not isinstance(value, dict):
        return None
    pid = int(key)
    clones = value.get("clones")
    if not isinstance(clones, list) or not 1 <= len(clones) <= MAX_CLONES:
        return None
    parsed: list[Clone] = []
    for item in clones:
        if not isinstance(item, dict):
            return None
        d, repo, branch = item.get("dir"), item.get("repo"), item.get("branch")
        if not (isinstance(d, str) and DIR_RE.fullmatch(d) and d not in {".", ".."}
                and isinstance(repo, str) and REPO_RE.fullmatch(repo)
                and isinstance(branch, str)):
            return None
        match = BRANCH_RE.fullmatch(branch)
        if not match or int(match.group(1)) != pid or ".." in branch or branch.endswith((".", "/", ".lock")):
            return None
        parsed.append(Clone(d, repo, branch))
    if len({c.dir for c in parsed}) != len(parsed):
        return None
    extra = value.get("commands", [])
    if (not isinstance(extra, list) or len(extra) > MAX_COMMANDS
            or not all(isinstance(c, str) and COMMAND_RE.fullmatch(c) for c in extra)):
        return None
    return Grant(pid, tuple(parsed), tuple(extra))


def load(path: Path) -> dict[int, Grant]:
    """All valid grants in the file. A missing or unreadable file, or a bad entry, grants nothing."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    grants: dict[int, Grant] = {}
    for key, value in raw.items():
        grant = _entry(str(key), value)
        if grant is None:
            logger.warning("ignored an invalid agent git grant entry for project %r", str(key)[:20])
            continue
        grants[grant.project_id] = grant
    return grants


def grant_for(settings, project_id: int, card) -> Grant | None:
    """The grant for this story, or None. Read-only stories and managers never get one."""
    if getattr(card, "mode", "read") == "read" or getattr(card, "agent", "") not in GRANTED_AGENTS:
        return None
    path = getattr(settings, "agent_git_grants_file", None)
    if path is None:
        return None
    return load(path).get(int(project_id))


def claude_allowed(grant: Grant) -> list[str]:
    rules: list[str] = []
    for c in grant.clones:
        for sub in GIT_SUBCOMMANDS:
            rules.append(f"Bash(git -C {c.dir} {sub}:*)")
        rules.append(f"Bash(git -C {c.dir} branch --show-current)")
        rules.append(f"Bash(git -C {c.dir} pull --ff-only origin {c.branch})")
        rules.append(f"Bash(git -C {c.dir} push origin {c.branch})")
    rules.extend(DEFAULT_COMMANDS)
    rules.extend(grant.commands)
    return rules


def claude_denied(grant: Grant) -> list[str]:
    """Denies that remain with a grant. A deny always beats an allow, so ``git push`` as a whole
    cannot be denied; only the exact push of the project branch is allowed instead."""
    rules = ["Bash(git merge:*)", "Bash(gh pr merge:*)", "Bash(gh release:*)"]
    for c in grant.clones:
        for flag in ("--force", "-f", "--force-with-lease", "--delete", "--tags", "--mirror"):
            rules.append(f"Bash(git -C {c.dir} push {flag}:*)")
        rules.append(f"Bash(git -C {c.dir} tag:*)")
        rules.append(f"Bash(git -C {c.dir} config:*)")
    return rules


def codex_overrides() -> list[str]:
    """`-c` overrides that replace the plain workspace-write sandbox: .git is writable and the
    network is limited to GitHub and the package indexes. Verified with `codex sandbox`."""
    domains = ",".join(f'"{d}"="allow"' for d in CODEX_DOMAINS)
    return [
        'default_permissions="agentgit"',
        'permissions.agentgit.extends=":workspace"',
        "features.network_proxy={enabled=true}",
        f'permissions.agentgit.network={{enabled=true,mode="full",domains={{{domains}}}}}',
    ]


def context_text(grant: Grant, card_id: int, agent: str, model: str | None) -> str:
    clones = "; ".join(f"{c.dir} (repo {c.repo}, branch {c.branch})" for c in grant.clones)
    first = grant.clones[0]
    return (
        "GIT ACCESS FOR THIS PROJECT (granted by the operator, branch-scoped). You may commit and push "
        f"only in these clones under your working directory, only on the named branch: {clones}. "
        "Work in small commits that each do one thing, with a conventional subject "
        "(type(scope): summary, 72 characters or fewer; types feat fix docs test refactor perf build ci chore revert) "
        f"and these trailers: MCD-Project: {grant.project_id}, MCD-Story: #{card_id}, "
        f"MCD-Agent: {agent}/{model or 'default'}. "
        "Run the tests that cover the code you changed before you commit; the hooks run them too. "
        "Push only when a test needs CI, not after each commit and never for documentation-only changes; pushes are rate limited. "
        f"Use `git -C <dir> ...` and push with exactly `git -C {first.dir} push origin {first.branch}`. "
        "Never merge, rebase onto main, force push, delete branches, create tags, change git config or hooks, or touch main. "
        "If a hook rejects a commit or push, fix the cause; do not work around the hook. "
        "Do not commit secrets, runtime data or large generated files. "
        "A story is finished only when its checks pass and its work is committed on the branch; say plainly what is not done."
    )


def apply_context(prompt: str, grant: Grant, card_id: int, agent: str, model: str | None) -> str:
    text = context_text(grant, card_id, agent, model)
    if NO_PUSH_SENTENCE in prompt:
        return prompt.replace(NO_PUSH_SENTENCE, text, 1)
    return f"{prompt}\n{text}"
