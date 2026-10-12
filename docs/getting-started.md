# Getting started and source availability

## Current release boundary

Application sources are not yet published in this repository. There is no released Pi installer, systemd production service or certified physical-Pi deployment. Clone the repository to read/contribute documentation; do not run installation commands for files that are absent.

The operator’s local prototype was built on Ubuntu 24.04 ARM64 in a temporary Lima VM (4 CPUs, 4 GiB RAM, 20 GiB disk), using Python 3.12 and Node 22. This proves a Linux UI preview, not Raspberry Pi OS or physical-Pi compatibility. Raspberry Pi 4 or newer with a 64-bit OS is the intended target; compatibility and memory measurements still need sign-off.

## Reproducing the local prototype once source is available

The verified manual approach creates an isolated Python venv, installs the lockfile, builds the frontend with `npm ci` and `npm run build`, and starts `apps/api/serve.py` on an unused loopback port. The existing bootstrap script has Mac-specific assumptions; it is not a verified one-command Pi installer.

Use a fresh private test data/report directory and disable dispatcher, alerts and external delivery for UI review. Start with no provider or Google credentials. Expose the exact preview URL in the handoff and keep its process separate from production. Host environment settings use the inherited MAC_CONTROL_ prefix; consult [configuration](configuration.md). The settings implementation still needs a clearer cross-platform report-folder configuration workflow.

Google login, Tailscale, provider keys and native runtime installation are separate explicit setup steps. Do not expose an unauthenticated preview on a public/LAN interface, copy production databases, reuse another app’s credentials or assume Mac subscriptions run on the Pi.

## Operator walkthrough

When source is released and a preview is running, use the header’s **Help** chat and **Help & how-tos** menu for feature links. **Settings** manages profile preferences/credentials, while the setup wizard records prerequisites and operator confirmations. A walkthrough completion is not proof of working runtime integrations or permission to dispatch.

See [features](features.md), [agents](agents.md), [test limits](tested-environments.md) and [release readiness](release/readiness.md) before planning a production install.
