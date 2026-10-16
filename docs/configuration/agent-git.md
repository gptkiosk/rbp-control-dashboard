# Branch-scoped git access for project agents

By default RCD agents cannot commit or push: the shared project context says "do not
commit, push or merge", Claude has `git push` denied (and no shell), and Codex runs in a
`workspace-write` sandbox where `.git` is read-only and there is no network. That is right
for most work. A project that must deliver code to GitHub needs a deliberate exception,
and this is it.

A **grant** lets Edit-mode stories of one approved project commit and push in named clones,
on one project branch, and nothing else.

## What a grant changes

| Agent | With a grant |
|---|---|
| Claude | Allowed exact commands: `git -C <clone> status/diff/log/show/add/commit/restore/rev-parse/fetch origin`, `pull --ff-only origin <branch>`, and `push origin <branch>`; plus test commands. `git merge`, `gh pr merge`, `gh release`, force or delete pushes, tags and `git config` stay denied. |
| Codex | A permission profile replaces the plain sandbox: `.git` is writable and the network is limited to GitHub and the package indexes (`pypi.org`, `registry.npmjs.org`). Verified with `codex sandbox`. |
| OpenClaw | Already has a full shell (`tools.exec.security: full`). The grant adds the instructions and the commit trailers; the hooks and GitHub rules are the limit. |
| Hermes | Never. Managers do not write code. |

Read-only stories and output-only continuations never get a grant. The shared context
sentence "Do not commit, push or merge automatically" is replaced by the grant's rules
(small commits, conventional subjects, `RCD-Project` and `RCD-Story` trailers, push only
when a test needs CI, never merge or tag). The run's checkpoint records the granted
clones and branches.

## Configure

Grants are operator configuration, never plan output. Edit
`~/.rcd-control/agent-git/grants.json` (path: `MAC_CONTROL_AGENT_GIT_GRANTS_FILE`); it is
read at each claim, so no restart is needed.

```json
{"5": {"clones": [{"dir": "rbp-control-dashboard",
                   "repo": "gptkiosk/rbp-control-dashboard",
                   "branch": "project-5/installable-releases"}],
       "commands": ["Bash(limactl list:*)"]}}
```

- The key is the RCD project id. `dir` is a clone directly under the project's working directory.
- `branch` must be `project-<id>/<slug>` for the same id. `main` can never be granted.
- At most 4 clones and 20 extra `commands` (Claude `Bash(...)` patterns). Anything invalid
  grants nothing and is logged.

## Prepare a clone

`scripts/agent-git/setup-clone.sh` (run by the operator or a setup story) clones the repo,
cuts the project branch from `main`, adds the local tag `project-<id>-base`, and wires the
clone. It pushes nothing.

```sh
scripts/agent-git/setup-clone.sh --repo gptkiosk/rbp-control-dashboard \
  --dest ~/work/rbp-control-dashboard --project 5 --slug installable-releases \
  --pre-push-cmd 'cd apps/api && .venv/bin/python -m pytest -q'
```

It installs the operator-owned files into `~/.rcd-control/agent-git/`, outside every repo:

- `git-credential-mcd-agent`: serves the token in `~/.rcd-control/agent-git/token` (mode 600)
  over HTTPS for `gptkiosk/rbp-control-dashboard` and `gptkiosk/rbp-control-dashboard` only.
- `hooks/commit-msg`: conventional subject of 72 characters or fewer; trailers required.
- `hooks/pre-commit`: at most 400 changed lines and 25 files (lock files, generated output
  and binary assets do not count), a `gitleaks` scan of the staged changes, and the tests
  related to the staged code (`apps/api/tests/test_<module>*.py`, `vitest related`).
- `hooks/pre-push`: only `refs/heads/<branch>` (plus the base tag, and `-rc.N` tags when
  allowed), no delete, no non-fast-forward, at most 6 pushes an hour, and the full
  `mcd.prePushCmd` suite when code changed. Documentation-only pushes skip it.

## Limits to know

- The hooks are guidance and a safety net, not a security boundary. An agent with a full
  shell (OpenClaw, or Claude with extra commands) can bypass them, and Codex can edit
  `.git/config`. The token itself is the real boundary.
- Until GitHub rulesets and a separate GitHub identity exist, the token acts as its owner:
  nothing on GitHub stops a push to `main` or a tag. See the project plan.
- Pushing consumes GitHub Actions minutes only when a workflow runs. Keep CI on draft PRs
  to ready-for-review or manual dispatch, skip docs-only paths, and cancel superseded runs.
