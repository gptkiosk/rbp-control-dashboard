# Agent tools (Linux arm64)

Settings → Agent tools installs pinned versions of Claude Code, Codex CLI, OpenClaw and Hermes for the dashboard service user. Each action shows its exact plan and requires operator sign-in and confirmation. Agents cannot authorize an install. Installing does not change billing, routes, the free-only policy or sign-in state.

Programs live under `~/.local/share/rcd-agent-tools` (override with `MAC_CONTROL_AGENT_TOOLS_ROOT`). Versions are immutable after their checks pass; `current` and `previous` symlinks support rollback. Removal keeps native account data. Hermes may create its own toolchain under its data folder; the confirmation explains retained data. The dashboard discovers managed wrappers without restarting, while explicit binary paths retain precedence.

The catalog pins Node archives by SHA-256 and publisher SHASUMS, npm dependencies by committed lockfiles and integrity hashes, and Hermes by commit and installer-script hash. npm lifecycle scripts are disabled except the catalog's named steps. `python3 scripts/tools/check.py --verify` checks the local pins. The checker can propose and apply selected updates; review and test changed pins before shipping them.

The helper runs outside the dashboard service, with Linux `no_new_privs`, a clean environment and an isolated install HOME. Under systemd it uses a separate transient user unit. Required system packages are shown as one manual command; the dashboard never runs sudo. Low disk, 32-bit hosts, root and unsupported platforms are refused; low memory is warned. Login commands are shown for the operator to run personally. Gateway services are not installed or enabled.

## Manual helper

When dashboard sign-in is unavailable, use the installed API Python with its helper:

```sh
python3 -I apps/api/tool_install_helper.py --root "$HOME/.local/share/rcd-agent-tools" status
python3 -I apps/api/tool_install_helper.py --root "$HOME/.local/share/rcd-agent-tools" plan codex install
# Read the plan, then use its plan_sha256 only if you approve every step:
python3 -I apps/api/tool_install_helper.py --root "$HOME/.local/share/rcd-agent-tools" run codex install --plan-sha256 <digest>
```

The helper rebuilds the plan and refuses a changed digest. Interrupted operations are journalled and recovered on the next helper invocation. Install/remove receipts and bounded logs are under the tools root's `state/` directory.

## Verification and limits

On 2026-10-13, the real helper installed, checked `--version` and removed each of Claude Code 2.1.296, Codex 0.162.1, OpenClaw 2026.10.3 and Hermes 0.21.7 in an isolated HOME on Ubuntu 24.04 arm64 in Lima, 4 GiB RAM. Fake-installer tests exercise update, rollback, recovery and refusal paths. Real upgrade/rollback across vendor versions, sign-in, gateways, Raspberry Pi hardware, Mac installers and Grok installation remain pending. No provider/model work was dispatched.
