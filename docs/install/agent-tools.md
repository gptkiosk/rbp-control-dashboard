# Managed agent tools

Settings → Agent tools installs pinned Claude Code, Codex CLI, Grok Build, OpenClaw and Hermes for the dashboard service user. Every mutation requires operator sign-in, a reviewed plan and confirmation. Installing never changes billing, routes, free-only settings or sign-in.

Programs live under `~/.local/share/rcd-agent-tools` (override with `MAC_CONTROL_AGENT_TOOLS_ROOT`). Immutable versions and current/previous links support rollback. Removal retains native account data and managed Hermes toolchain data described by the plan. Hermes installation uses a separate hermes-install-home under the managed tools root, so native account configuration is not read or modified. Normal operator sessions still use their native HERMES_HOME. Managed wrappers are discovered without restart; explicit binary paths retain precedence.

Node archives are checked against publisher SHASUMS and SHA-256, npm dependencies against committed integrity lockfiles, Hermes against a pinned commit and script hash, and Grok against an exact URL, byte size and SHA-256. Lifecycle scripts are disabled except named catalog steps. Run `python3 scripts/tools/check.py --verify`; review and test proposed pin updates before shipping.

The helper runs outside the dashboard with a clean environment and isolated install HOME. Linux inherits no_new_privs. macOS Seatbelt confines writes to managed state and refuses privilege brokers and native account-file reads. System packages are manual prerequisites; the dashboard never runs sudo. Unsupported platforms, root and low disk space are refused; low memory is warned. Logins are manual. Gateway services are not enabled.

## Manual helper

```sh
python3 -I apps/api/tool_install_helper.py --root "$HOME/.local/share/rcd-agent-tools" status
python3 -I apps/api/tool_install_helper.py --root "$HOME/.local/share/rcd-agent-tools" plan codex install
# Review the exact plan before using its digest:
python3 -I apps/api/tool_install_helper.py --root "$HOME/.local/share/rcd-agent-tools" run codex install --plan-sha256 <digest>
```

Changed plan digests are refused. Interrupted operations recover on the next helper invocation. Receipts and bounded logs live under the tools root's state directory.

## Verification and limits

On 2026-10-13 all five tools installed, passed --version and were removed in an isolated Mac test home. All five also passed those checks on Ubuntu 24.04 arm64 in Lima with 4 GiB RAM. This is not Raspberry Pi hardware evidence. Synthetic tests exercise update, rollback, recovery and refusal paths. Vendor-version upgrades, account logins, gateways and model dispatch were not exercised. See [recommended setup](../configuration/recommended-agent-mix.md).

The dashboard resolves the managed Hermes interpreter from its owner-checked dependency receipt and launches the model-policy shim directly. It does not execute arbitrary shell launchers to discover an interpreter. The real installed shim passed chat --help with a pinned free route on a synthetic account home; no model request was sent.
