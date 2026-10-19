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

## Existing native installations

Agent tools detects commands already installed outside the dashboard and reads their version with a bounded version-only check. Native installs show their current version and an **Upgrade** button when older than the latest hash-verified catalog release. Equal or newer versions are kept; an unreadable version is shown as unavailable instead of being called missing or silently downgraded.

Confirming a native upgrade stages a managed copy for dashboard use; it preserves the original program and account configuration. The confirmation names both versions and this behavior. Removing that managed copy restores native discovery. Rollback/removal controls only apply to dashboard-managed receipts. The catalog's checked date identifies when vendor releases were verified; installation never fetches an unverified floating latest version.

## From the setup wizard

Settings, Updates & installs shows one card per tool: version (`installed → latest`), Install or Upgrade, a progress bar while the helper runs, the helper log, and a **health check** that runs by itself afterwards. The check asks the tool for its version, confirms a new terminal reaches the managed copy (not an older native one earlier on the PATH) and lists next steps. It is read-only: `GET /api/agent-installs/health[?tool=id]`. The helper reads a native tool's version *before* it applies the macOS sandbox, which hides the home folder (an earlier release refused every native Hermes upgrade as unverifiable because of this).

The Coordinator & workers step links directly to Settings → Agent tools. “Executable not found” is a detection result, not a request to configure an absent program. Install Hermes first, then add your chosen workers. In Agent tools choose Install, review its version, downloads, supporting runtime requirements and host resource checks, and confirm the exact plan. Existing native installations show their versions and offer Upgrade when applicable.

When installation finishes, run the displayed setup/sign-in command in a terminal on the machine hosting the dashboard (an SSH session works when browsing remotely). Google dashboard sign-in grants access to the installer; each agent still needs its own provider configuration or eligible membership login. Installing a desktop application alone does not supply a worker CLI.

Use Return to coordinator setup or Return to membership setup, then choose Refresh checks. The wizard keeps saved progress and reports executable detection separately from provider/account readiness. Review assigned models and spending rules before dispatching. You can reopen Agent tools later for upgrades and return to either setup step. Nothing installs merely by opening the wizard or following its links.
