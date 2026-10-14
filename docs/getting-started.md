# Getting started

The 0.3.0 application source is public on `codex/rcd-resume-20261013`. Signed release publication is pending operator signing setup; physical Raspberry Pi acceptance is still pending.

Follow [clean OS installation](install/clean-os-0.3.1.md) for a fresh Raspberry Pi OS64-bit install, pinned Python3.11, Node web-build prerequisites, a source-built package, the bootstrap/systemd service, SSH tunneling and agent setup. The same guide includes AppleSiliconMac instructions for MCD.

RCD targets Pi4/aarch64. Existing isolated Linuxarm64 tests ran in Lima, not on physical Pi. The bootstrap validates archive/manifest integrity and installs user services; use your own account and provider settings. Do not use the first-install bootstrap to overwrite an existing service.

Once running, open `/setup`; the wizard guides sign-in, profile, Hermes/OpenRouter and optional membership-backed agents. Operator account setup and spending approval remain separate from installing a tool. ZeroClaw/PicoClaw remain experimental integrations. See [configuration](configuration.md), [features](features.md), [test limits](tested-environments.md) and [release readiness](release/readiness.md).
