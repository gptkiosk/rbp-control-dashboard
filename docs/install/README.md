# Raspberry Pi Control Dashboard (RCD): install and upgrade docs

These pages cover installing, verifying, upgrading, rolling back, recovering, uninstalling and troubleshooting
the public **Raspberry Pi Control Dashboard (RCD)** release for **Linux arm64 (64-bit Raspberry Pi OS)**.

| Page | Covers |
|---|---|
| [First install](first-install.md) | `bootstrap-rcd.sh` from a GitHub release, or from a local archive and manifest |
| [Verify a release by hand](verify-release.md) | SHA-256 checks, what the manifest pins, and what is not yet verified |
| [Updates, rollback and recovery](updates-rollback-recovery.md) | The Settings updater, `update_helper.py`, rollback, restore and recovery |
| [Uninstall and troubleshooting](uninstall-troubleshooting.md) | Removing RCD, data location, and the messages you may see |

## Read this first: current status

These docs describe commands as they appear in the source. **None of the install, upgrade, rollback or recovery
commands has been run on a Raspberry Pi or on a Raspberry Pi OS image.**

- **Helper copy list fixed in source, not re-run.** `scripts/install/bootstrap-rcd.sh` now copies all five helper
  modules, including `release_fetch.py` and `update_recovery.py`, which a first install previously lacked. A source
  unit test checks the list. Neither the bootstrap nor the test has run on a Pi or an ARM64 guest.
- **No install receipt exists.** The clean-install verification (story `s13_clean_rcd`) is **blocked**. There is no
  install, update, rollback or recovery receipt.
- **The Lima test guest is not Raspberry Pi OS.** The `pi4-test` instance is Ubuntu 24.04.5 on aarch64. Its last
  recorded state is `Broken`, and its removal is incomplete. Earlier runs on it covered component tests only (see
  below). They say nothing about the installer, the systemd units or the Pi OS image.
- **No public GitHub release exists yet**, so there is nothing to download. Nothing has been uploaded or published.
- **Authenticity is not available yet.** The bootstrap checks a manifest digest that you copy from the release page.
  No signing key is configured, and the trust-root decision is still open. The bootstrap checks integrity only.
- **The Settings updater is off after a bootstrap install.** The unit does not set `MAC_CONTROL_UPDATE_ROOT`, so the
  updater shows manual steps. See [Updates, rollback and recovery](updates-rollback-recovery.md#settings-updater).
- **The Settings one-button fetch needs the digest typed in unless the host trusts the release signature.** A bootstrap from
  0.3.2 on switches to signature trust when the package ships the release key; older hosts switch with
  `enable-signed-updates` (see [Updates, rollback and recovery](updates-rollback-recovery.md)).

Each page marks what is confirmed by reading the source and what has been run. Until a verification receipt exists,
treat every command here as unverified.

## Receipts that exist (component tests on the Lima guest)

These are the only Lima results in the workspace. They ran before `pi4-test` went `Broken`.

| Check | Where it ran | Result as recorded | Does not cover |
|---|---|---|---|
| `tests/zeroclaw`, `tests/picoclaw`, `bench/tests`, `tests/adapter_conformance` | `pi4-test` (Ubuntu 24.04.5 aarch64), ZeroClaw 0.8.5, Python 3.12 | 92 passed | The installer, Pi OS, or the systemd units |
| Report-storage preview (synthetic data, port 8894) | `pi4-test` | 46 focused API tests passed on Mac and guest; guest Node build passed | Install, update or rollback |
| Clean RCD install (`s13_clean_rcd`) | Not run | Blocked: sandbox refused Lima access; no public release to install from | Everything in this page's install flow |
| Temporary guest removal (`s9-retire`) | `pi4-test` | Forced delete failed with `operation not permitted`; instance still `Broken` | — |

Physical Raspberry Pi hardware, Raspberry Pi OS, thermal and throttle readings, and live-provider conformance are
**not** verified.

## Supported platform (documented target, not verified)

- Raspberry Pi with a 64-bit Raspberry Pi OS (`uname -m` reports `aarch64`)
- Python 3.11 with venv (Raspberry Pi OS Bookworm ships 3.11; other releases need 3.11 installed separately)
- A systemd user session for the service user

Other operating systems and 32-bit OS images are refused by the installer.

- [Agent tools](agent-tools.md): pinned per-user CLI installation and its validation limits.
