# First install

For complete clean-OS instructions, use [the 0.3.0 Mac/Pi guide](clean-os-0.3.1.md). Public source candidates are available; signed release publication and physical Pi acceptance remain pending. The source-build path works before a release tag exists.

## Helper files

`scripts/install/bootstrap-rcd.sh` copies five files into `<root>/helper/`: `update_helper.py`, `update_engine.py`,
`release_fetch.py`, `release_verify.py` and `update_recovery.py`. `update_helper.py` imports `release_fetch` at module
load, so a missing copy made `stage` fail before anything was switched. `scripts/install/test_bootstrap_rcd.py`
(`HelperCopyList`) derives the required set from the real imports and fails if the copy loop drifts.

## What you need

- A Raspberry Pi with 64-bit Raspberry Pi OS. Check with `uname -m`, which should print `aarch64`.
- Python 3.11 with venv and `curl`. On Raspberry Pi OS Bookworm:

  ```sh
  sudo apt install python3.11 python3.11-venv curl
  ```

  Other OS releases need 3.11 installed another way; pass its path with `--python`.
- A systemd user session for the account that will run RCD. Log in as that account, or enable lingering so the
  service starts at boot and survives logout:

  ```sh
  sudo loginctl enable-linger <user>
  ```

- Port `8800` free on `127.0.0.1`. The installer refuses to start if something already answers there.
- The **manifest SHA-256** for the version you are installing, copied from that version's GitHub release page.
  The installer refuses to run without it.

No minimum RAM, CPU or disk size has been measured on a Raspberry Pi. The Lima test guest had 4 CPUs, 4 GiB RAM and
20 GiB disk, but that is a test environment.

## Get the installer

The release archive does not contain the installer. `packaging/product.json` excludes `scripts/`, so the bootstrap
comes from the **tagged source**:

```sh
git clone --branch vX.Y.Z https://github.com/gptkiosk/rbp-control-dashboard.git rcd-install
cd rcd-install
```

The v0.3.0 tag is not yet published. Until it exists, use the public candidate branch and local source-build path in the clean-OS guide.

## Choose a source

**From the GitHub release (recommended once a release exists):**

```sh
scripts/install/bootstrap-rcd.sh --version X.Y.Z --manifest-sha256 <64-hex>
```

This downloads `rcd-X.Y.Z-linux-arm64.manifest.json` and `rcd-X.Y.Z-linux-arm64.tar.gz` from release `vX.Y.Z` of
`gptkiosk/rbp-control-dashboard`. It uses HTTPS only, and redirects must land on GitHub hosts. No token is needed.
The archive is capped at 100 MiB and the manifest at 1 MiB.

**From local files** (for example, a file you downloaded and checked yourself):

```sh
scripts/install/bootstrap-rcd.sh --archive FILE.tar.gz --manifest FILE.manifest.json --manifest-sha256 <64-hex>
```

Use `--allow-prerelease` only for a prerelease version or manifest.

## Dry run first

```sh
scripts/install/bootstrap-rcd.sh --version X.Y.Z --manifest-sha256 <64-hex> --dry-run
```

`--dry-run` checks the manifest digest, the archive size and SHA-256, the product, platform, channel and archive
members. It then prints the plan and changes nothing. It is the only check that runs before anything is written.

## Install

```sh
scripts/install/bootstrap-rcd.sh --version X.Y.Z --manifest-sha256 <64-hex>
```

The installer then:

1. Checks the pinned digest, then the package (see [Verify a release by hand](verify-release.md)).
2. Creates `~/.local/share/rcd-control` (override with `--root`) and `~/.rcd-control` (runtime data).
3. Writes `<root>/helper/helper.json` with `"trust": {"kind": "pinned-digest"}` and the five helper files. After the first
   version is active, if the package ships the release key and its fingerprint matches the one in the script, it switches
   to `ssh-signature` trust so later updates need no pasted digest.
4. Runs `update_helper.py stage`, which extracts the release into `<root>/versions/<version>-<sha256[:12]>/` and
   builds its `runtime/` virtualenv with hash-pinned wheels only.
5. Runs `activate-initial`, which points `<root>/current` at that version.
6. Renders and enables `rcd-api.service` (runs `<root>/current`) and `rcd-update-recover.timer`.
7. Polls `http://127.0.0.1:8800/healthz` for up to 10 seconds.

Staging fails before anything switches. A failed health check after step 6 leaves the service running the new
version, so see [troubleshooting](uninstall-troubleshooting.md#troubleshooting).

## Check it works

```sh
curl -fsS http://127.0.0.1:8800/healthz
systemctl --user status rcd-api.service
systemctl --user list-timers rcd-update-recover.timer
python3.11 -I ~/.local/share/rcd-control/helper/update_helper.py \
  --config ~/.local/share/rcd-control/helper/helper.json status
```

Open `http://127.0.0.1:8800` on the Pi. The API binds loopback only. For access from another machine, see
[remote access](../configuration/remote-access.md); that setup is operator-configured.

## Where things live

| Path | Contents |
|---|---|
| `<root>/versions/<id>/` | One immutable release and its `runtime/` virtualenv |
| `<root>/current` | Symlink to the active version. The service runs `<root>/current` |
| `<root>/helper/` | `update_helper.py`, `update_engine.py`, `release_fetch.py`, `release_verify.py`, `update_recovery.py`, `helper.json` |
| `<root>/inbox/` | Packages waiting to be staged |
| `<root>/state/` | Install journal, lock, backups, `history.jsonl`, `helper.log` |
| `~/.rcd-control/` | Runtime data: database, logs, reports. Outside the install root |
| `~/.config/systemd/user/` | `rcd-api.service`, `rcd-update-recover.service`, `rcd-update-recover.timer` |

## Set your settings

Put settings in `~/.rcd-control/.env`, which the application reads itself. Do not put secrets in the unit files.
See [configuration](../configuration/environment.md) and [settings](../configuration/settings.md).
