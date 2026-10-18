# Host readiness

Before a project can be built and delivered from this machine, the machine needs a few things. **Setup wizard, step 1** shows them as a checklist with one-click fixes, so a new host (a Mac, or a Raspberry Pi running RCD) does not have to be set up by hand.

## What it checks

| Check | Ready when | Fix offered |
| --- | --- | --- |
| Workspace folder | One of the allowed workspace folders (`MAC_CONTROL_WORKDIR_ROOTS`, by default `~/Projects` and the data directory's `workspaces`) exists and is writable. | **Create** the first allowed folder. Only an allowed folder can be created. |
| git | `git` is installed. | None: install it with the system package manager. |
| git identity | The global git `user.name` and `user.email` are set. | **Set the git identity** (name up to 100 characters, a valid email). |
| GitHub access | A key made here (`~/.ssh/rcd-github`) exists. | **Make a GitHub SSH key**, then **Test GitHub access**. |
| Installed tools on your shell PATH | Tools this dashboard installed (Codex, OpenClaw and the rest) live in their own `bin` folder, which a plain shell does not search, so `codex login` says *command not found*. Ready when that folder is on the PATH or already set up. | **Put installed tools on my PATH** adds a marked block to `~/.profile` and `~/.bashrc`; open a new terminal afterwards. |
| Agents that build | At least one of Claude Code, Codex, OpenClaw or Grok is installed. Hermes plans and coordinates but does not write code, so it does not count. | None: install a builder from Agent tools and sign in. Sign-in is not verified. |
| Optional tools | Docker (container images), Node (JavaScript tests, the Playwright screenshot script), ffmpeg (media), `gh` (pull requests from this host). | None. |
| Disk | At least 5 GB free. | None. |
| Network | GitHub and OpenRouter are reachable (only when you ask for the network test). | None. |

The summary line says whether the machine is **ready to build** (workspace, git, identity and a builder) and **ready to deliver to GitHub** (and a GitHub key).

## The GitHub key

**Make a GitHub SSH key** creates an ed25519 key with no passphrase at `~/.ssh/rcd-github` (mode 600) and adds a marked block to `~/.ssh/config` so `github.com` uses it. The private key never leaves the host and is never shown or returned; only the public key is displayed. An existing key is never replaced. Add the public key to your GitHub account (one key then reaches every repository you can access) or to a single repository's **Deploy keys** with write access (the narrower choice, one repository per key). **Test GitHub access** asks GitHub whether it accepts the key; the first test records GitHub's host key (`accept-new`).

Agents push only through a project's git grant, never with this key directly. See [Branch-scoped git access](agent-git.md).

## What it never does

Checks change nothing. A fix does one named thing the operator asked for, through an operator-only route, and shows what it changed. It does not install software, store a token, change agent routing or run project code.

The API is `GET /api/host/readiness` (add `?network=true` for the network test) and `POST /api/host/readiness/fix` with one of `create_workspace`, `set_git_identity`, `make_github_key`, `test_github_ssh`, `add_tools_to_path`.
