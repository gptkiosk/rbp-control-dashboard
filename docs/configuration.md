# Configuration, credentials and report folders

The current local RCD prototype retains MCD’s MAC_CONTROL_ environment prefix but uses ~/.rcd-control as its runtime default; MCD uses ~/.mac-control. Keep an existing RCD installation’s former runtime by setting MAC_CONTROL_DATA_DIR explicitly. Application code remains held for sign-off. Separate installations/previews must use separate state. No literal developer username/home path is required; paths should belong to the current operator/install.

| Setting | Purpose |
|---|---|
| MAC_CONTROL_HOST / PORT | Loopback bind and unused port; default 127.0.0.1:8800. Keep test previews private. |
| MAC_CONTROL_DATA_DIR | Private runtime database/run state. Ops report defaults now derive from this installation’s data directory in the local prototype. Dotenv loading still follows the product’s default runtime path; custom installs should provide the service environment explicitly. |
| MAC_CONTROL_WEB_DIST | Built frontend directory for the selected source snapshot. |
| MAC_CONTROL_OPS_REPORTS_DIR | Existing environment override for the primary report folder. |
| MAC_CONTROL_HERMES_REPORTS_DIR | Optional Hermes report/archive folder. |
| MAC_CONTROL_REPORTS_ALLOWED_ROOTS | Host-installed JSON allowlist of dedicated report folders; the UI cannot expand it. |
| MAC_CONTROL_COLLECTOR_ENABLED | Whether host observations are collected. Turn off in a fixture-only preview. |
| MAC_CONTROL_DISPATCHER_ENABLED | Whether queued work can run. Turn off for UI-only previews. |
| MAC_CONTROL_ALERTS_ENABLED | Whether configured alert delivery is active. Turn off for isolated previews. |
| MAC_CONTROL_AUTH_ENABLED | Google sign-in enforcement; configure required OAuth settings and allowlisted origins before enabling. |

The OpenRouter key saved in Profile can optionally be shared with Hermes and OpenClaw: see [Share the saved OpenRouter key](configuration/saved-openrouter-key.md).

Jobs and telemetry (who work is assigned to, the agent and model that ran it, time and cost) is described in [Jobs and telemetry](configuration/telemetry.md).

Housekeeping (leftovers you approve, which Hermes may propose) is described in [Housekeeping](configuration/housekeeping.md), and the standard fields on planned work in [The standard job envelope](configuration/job-envelope.md).

## Ops reports

The default shown in the UI is computed from the installation user’s home/runtime convention; seeing a username in that displayed path does not itself imply a hardcoded source path. Configure a portable folder with MAC_CONTROL_OPS_REPORTS_DIR. Optional Hermes archives use MAC_CONTROL_HERMES_REPORTS_DIR. Only supported UTF-8 Markdown/text reports are read, with bounded traversal/size and no-follow symlink handling.

A missing configured folder currently produces an empty/unavailable state. The local follow-up implementation now exposes Host report storage controls in Settings, setup and Ops reports on both platforms. Signed-in operators select existing folders within the host-installed allowlist; modes distinguish default, configured, disabled and unavailable sources. Choices persist atomically in a private report-storage.json outside profile exports; restoring defaults returns to the installation’s environment/data-dir settings. Save/reset was verified with synthetic reports on Mac and ARM64 Linux. This code is not part of the current public docs-only release and is not a production security sign-off.

Keep test reports synthetic and production reports private. A path-setting UI must be operator-only, constrain readable folders and preserve existing no-follow protections; it must not create arbitrary filesystem access.

## Credentials

Google OAuth/server configuration, profile vault credentials, native agent provider keys, MCP grants, Discord profile pairing and GitHub CLI login are separate interfaces. No shared token substitutes for another. Use per-install user configuration, private files and the encrypted profile store when present; never commit real values, runtime DBs or vault roots.

A provider key saved in a profile does not prove a runtime is wired to it. A dollar budget alert is not necessarily a hard enforcement cap. RCD live conformance is currently free-only/$0 paid; the Mac installation’s separately approved Google BYOK fallback is not a Pi-test spending grant. Paid routing, new permissions and credential rotation require concrete operator decisions.
