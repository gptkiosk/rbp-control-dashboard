# Install 0.3.0 on a clean Mac or Raspberry Pi

MCD targets Apple Silicon MacBook Pro and Mac mini (M1 or newer), macOS 14 or later. RCD targets Raspberry Pi 4, including the **4 GB model**, with Raspberry Pi OS **64-bit** (`uname -m` must report `aarch64`). Physical Pi acceptance is still pending; the arm64 installer receipts so far came from Lima. Use your own login account, not root.

The current 0.3.0 source is public on `codex/mcd-resume-20261013` and `codex/rcd-resume-20261013`. Signed downloadable releases are pending operator signing setup. The source-build path below works without a published tag; it builds a local candidate from the code you cloned. Record `git rev-parse HEAD` with your test results. When v0.3.0 is published, use its tagged source and release manifest digest instead.

## 1. Prepare the computer

### Apple Silicon Mac

Install Apple's command-line tools (`xcode-select --install`) if missing. Install Homebrew using its [official instructions](https://brew.sh/), then:

```sh
brew install git python@3.12 node@24
export PATH="/opt/homebrew/opt/node@24/bin:$PATH"
/opt/homebrew/bin/python3.12 --version
node --version
npm --version
uname -m
```

Architecture must be `arm64`. Open Terminal under your normal logged-in desktop account so launchd has a GUI user session. A packaged install needs Python3.12; it does not use or replace macOS's system Python.

### Raspberry Pi OS 64-bit

Connect the Pi to the network and log in locally or over SSH as the account that will run RCD. These commands are for the operator to run:

```sh
uname -m
cat /etc/os-release
sudo apt update
sudo apt install -y git curl ca-certificates xz-utils
```

Install the pinned Python3.11 runtime separately so this works on both Bookworm and newer OS releases. [uv's official Python installation guide](https://docs.astral.sh/uv/guides/install-python/) supports managing that version without replacing the OS Python:

```sh
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
sh /tmp/uv-install.sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.11
rcd_python="$(uv python find 3.11)"
"$rcd_python" --version
```

For building the web UI from source, install the pinned Node24 arm64 release. It is optional when using an already-built release package. Download from the official Node distribution, verify its published checksum, then extract into your account:

```sh
mkdir -p "$HOME/rcd-prerequisites"
cd "$HOME/rcd-prerequisites"
curl -fSLO https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-arm64.tar.xz
curl -fSLO https://nodejs.org/dist/v24.21.0/SHASUMS256.txt
awk '$2=="node-v24.21.0-linux-arm64.tar.xz"' SHASUMS256.txt | sha256sum --check -
tar -xf node-v24.21.0-linux-arm64.tar.xz
export PATH="$HOME/rcd-prerequisites/node-v24.21.0-linux-arm64/bin:$HOME/.local/bin:$PATH"
node --version
npm --version
systemctl --user show-environment >/dev/null
```

Stop if checksum verification fails. If the systemd command fails, log in as the intended service user before continuing. To start at boot and continue after logout:

```sh
sudo loginctl enable-linger "$(id -un)"
```

For later source builds, add the Node and uv PATH entries to your shell startup file. The installed service uses absolute runtime paths.

## 2. Clone and build the candidate

### Mac

```sh
mkdir -p "$HOME/dashboard-install"
cd "$HOME/dashboard-install"
git clone --branch codex/mcd-resume-20261013 https://github.com/gptkiosk/mac-control-dashboard.git mcd
cd mcd
git rev-parse HEAD
/opt/homebrew/bin/python3.12 -I scripts/release/release.py build --platform darwin-arm64 --out "$HOME/dashboard-install/mcd-package"
```

### Pi

```sh
mkdir -p "$HOME/dashboard-install"
cd "$HOME/dashboard-install"
git clone --branch codex/rcd-resume-20261013 https://github.com/gptkiosk/rbp-control-dashboard.git rcd
cd rcd
git rev-parse HEAD
"$rcd_python" -I scripts/release/release.py build --platform linux-arm64 --out "$HOME/dashboard-install/rcd-package"
```

Keep the checkout clean. The builder installs web dependencies in a temporary copy and produces an archive, manifest and SHA256SUMS. This source build is an unsigned candidate; its integrity is rooted in the source you chose, not a published signature. No agent accounts or model inference are needed to build or install the dashboard.

## 3. Install the package

Use a fresh account/data folder. Port8800 must be free. The bootstrap refuses an existing running dashboard/service; **do not use it to overwrite an existing MCD driver**. Existing installations should use their documented updater/driver upgrade path and backup procedure.

### Mac

From the MCD source checkout:

```sh
mcd_package="$HOME/dashboard-install/mcd-package"
mcd_digest="$(shasum -a 256 "$mcd_package/mcd-0.3.0-darwin-arm64.manifest.json" | awk '{print $1}')"
bash scripts/install/bootstrap-mcd.sh --archive "$mcd_package/mcd-0.3.0-darwin-arm64.tar.gz" --manifest "$mcd_package/mcd-0.3.0-darwin-arm64.manifest.json" --manifest-sha256 "$mcd_digest" --python /opt/homebrew/bin/python3.12 --dry-run
```

Review the plan, then run the same command without `--dry-run`. Default release root is `~/Library/Application Support/MacControlDashboard`; data is `~/.mac-control`; launchd label is `com.operator.mac-control`.

### Pi

From the RCD source checkout, in the same shell that defined `rcd_python`:

```sh
rcd_package="$HOME/dashboard-install/rcd-package"
rcd_digest="$(sha256sum "$rcd_package/rcd-0.3.0-linux-arm64.manifest.json" | awk '{print $1}')"
bash scripts/install/bootstrap-rcd.sh --archive "$rcd_package/rcd-0.3.0-linux-arm64.tar.gz" --manifest "$rcd_package/rcd-0.3.0-linux-arm64.manifest.json" --manifest-sha256 "$rcd_digest" --python "$rcd_python" --dry-run
```

Review the plan, then run the same command without `--dry-run`. The user services are `rcd-api.service` and `rcd-update-recover.timer`; runtime data stays outside the release root. The release pins Python3.11 even if the OS default Python is newer.

Once a signed public v0.3.0 release exists, use tagged source and `--version 0.3.0 --manifest-sha256 DIGEST_FROM_TRUSTED_RELEASE_NOTES` instead of local archive/manifest options. Read the product's `packaging/README.md` for trust and rollback details; the bootstrap currently checks pinned digest integrity and does not automatically authenticate an SSH signature.

## 4. Verify and open it

```sh
curl -fsS http://127.0.0.1:8800/healthz
```

Verify version0.3.0, the expected source commit and built web status. Open `http://127.0.0.1:8800/` locally. For a headless Pi, keep the dashboard on loopback and tunnel from your Mac (`PI_USER` and `PI_HOST` are your actual login and host):

```sh
ssh -N -L 8814:127.0.0.1:8800 PI_USER@PI_HOST
```

Then open `http://127.0.0.1:8814/` on the Mac. Keep the SSH command running. Configure any LAN/remote HTTPS exposure separately through the documented authenticated setup.

Check RCD service health with `systemctl --user status rcd-api.service rcd-update-recover.timer` and `journalctl --user -u rcd-api.service -n 50 --no-pager`. On Mac use `launchctl print "gui/$(id -u)/com.operator.mac-control"`. The footer and header should agree on version/commit.

## 5. Configure agents and spending

Open `/setup` and Settings. Create your own [OpenRouter account](https://openrouter.ai/), configure its key through the operator settings, install Hermes as coordinator and select a reviewed `openrouter/free` route. Use OpenClaw for supported MCD free-route work. RCD's ZeroClaw/PicoClaw integrations remain experimental; Hermes is the supported coordinator, and the dashboard does not expose those experimental integrations as selectable workers.

Free routes can be throttled or time out. Optionally add a native membership-backed Codex, Claude Code or eligible Grok Build account through that tool's own login. Membership quotas are separate from API billing; an OpenRouter API key/BYOK does not transfer ChatGPT or Claude subscription quotas. See `docs/install/agent-tools.md` and the setup/billing panels for current eligibility/pricing links. You do not need all three paid memberships; a free-only configuration is possible. RCD spending defaults remain free-only until you explicitly approve a different policy.

In a submitted project, open **Stories & runs** and enable **Model lock** to stop failed tasks on their assigned model without automatic retries or equivalent-model switching. Defaultoff permits only the alternatives already approved in that project. Manual retry remains explicit.

Record physical Pi hardware, OS, source commit, health/service status and installer/version checks with your acceptance results. Lima validation is not physical Pi certification. Never include provider keys, native credentials or runtime databases in public receipts.
