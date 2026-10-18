# Host readiness

Before a project can be built and delivered from this machine, the machine needs a few things. **Setup wizard, step 1** shows them as a checklist with one-click fixes, so a new host (a Mac, or a Raspberry Pi running RCD) does not have to be set up by hand.

## What it checks

| Check | Ready when | Fix offered |
| --- | --- | --- |
| Workspace folder | One of the allowed workspace folders (`MAC_CONTROL_WORKDIR_ROOTS`, by default `~/Projects` and the data directory's `workspaces`) exists and is writable. | **Create** the first allowed folder. Only an allowed folder can be created. |
| git | `git` is installed. | None: install it with the system package manager. |
| git identity | The global git `user.name` and `user.email` are set. | **Set the git identity** (name up to 100 characters, a valid email). |
| GitHub access | A key made here (`~/.ssh/rcd-github`) exists **and GitHub has accepted it** (the check shows a warning until **Test GitHub access** succeeds; only then is the machine "ready to deliver"). | **Make a GitHub SSH key**, then **Test GitHub access**. |
| Installed tools on your shell PATH | Tools this dashboard installed (Codex, OpenClaw and the rest) live in their own `bin` folder, which a plain shell does not search, so `codex login` says *command not found*. Ready when that folder is on the PATH or already set up. | **Put installed tools on my PATH** adds a marked block to `~/.profile` and `~/.bashrc`; open a new terminal afterwards. |
| Agents that build | At least one of Claude Code, Codex, OpenClaw or Grok is installed. Hermes plans and coordinates but does not write code, so it does not count. | None: install a builder from Agent tools and sign in. Sign-in is not verified. |
| Optional tools | Docker (container images), Node (JavaScript tests, the Playwright screenshot script), ffmpeg (media), `gh` (pull requests from this host). On a Mac also Homebrew and Colima (the Docker engine, which must be *running*). | Each missing tool says how to get it. **`gh`** and **Node** install from Agent tools (pinned, checksum-verified, no administrator rights). On a **Mac** with Homebrew the wizard installs **ffmpeg, python, docker and colima** for you (**Install … with Homebrew**), starts Colima (**Start Colima**) and keeps them current (**Update tools with Homebrew**). If Homebrew itself is missing, the first step is its official install command, shown for you to run in Terminal (it asks for your password). On **Linux** system packages need administrator rights, so the wizard shows the `apt` command to copy and never runs it. |
| Disk | At least 5 GB free. | None. |
| Network | GitHub and OpenRouter are reachable (only when you ask for the network test). | None. |

The summary line says whether the machine is **ready to build** (workspace, git, identity and a builder) and **ready to deliver to GitHub** (and a GitHub key).

## The GitHub key

**Make a GitHub SSH key** creates an ed25519 key with no passphrase at `~/.ssh/rcd-github` (mode 600) and adds a marked block to `~/.ssh/config` so `github.com` uses it. The private key never leaves the host and is never shown or returned; only the public key is displayed. An existing key is never replaced. Add the public key to your GitHub account (one key then reaches every repository you can access) or to a single repository's **Deploy keys** with write access (the narrower choice, one repository per key). **Test GitHub access** asks GitHub whether it accepts the key, ignoring the system ssh config so a hardened service cannot trip on it; the first test records GitHub's host key (`accept-new`), and a success is remembered next to the key.

Agents push only through a project's git grant, never with this key directly. See [Branch-scoped git access](agent-git.md).

## Homebrew installs and updates (Mac)

The wizard runs `brew install` itself, with no password, for only these packages: `ffmpeg`, `python`, `colima`, and for Docker `colima docker docker-compose`. **Update tools with Homebrew** runs `brew update` and then `brew upgrade` for just the wizard's packages that are already installed through Homebrew; nothing else on the Mac is upgraded, and a failed update upgrades nothing. One job runs at a time, in a clean environment (no tokens or keys from the dashboard's own environment), with a time limit, and its log is shown in the panel. The packages are fixed by the dashboard, never taken from the request.

## What it never does

Checks change nothing. A fix does one named thing the operator asked for, through an operator-only route, and shows what it changed. It never uses `sudo`, stores a token, changes agent routing or runs project code. The only software it installs is the fixed Homebrew list above on a Mac; everything else is an Agent tools install or a command shown for a person to run.

The API is `GET /api/host/readiness` (add `?network=true` for the network test) `GET /api/host/readiness/job` for the running or last job, and `POST /api/host/readiness/fix` with one of `create_workspace`, `set_git_identity`, `make_github_key`, `test_github_ssh`, `add_tools_to_path`, `brew_install`, `brew_update`, `colima_start`.
