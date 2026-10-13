#!/usr/bin/env bash
# Install the pinned ZeroClaw release for the RCD adapter. No provider key is read, written or needed.
#
#   integrations/zeroclaw/install-zeroclaw.sh [install_dir]     (default: ~/.local/share/rcd/zeroclaw)
#
# The archive digest below is GitHub's published sha256 for the release asset (cross-checked
# 2026-10-11 against the archive used on the Lima aarch64 test VM). Update both lines together.
set -euo pipefail

VERSION="0.8.5"
ASSET="zeroclaw-aarch64-unknown-linux-gnu.tar.gz"
SHA256="aaa7e2c656dedf651217a70ea487e1e65f51b4ca771d114e60bf409165700986"
URL="https://github.com/zeroclaw-labs/zeroclaw/releases/download/v${VERSION}/${ASSET}"
DEST="${1:-${HOME}/.local/share/rcd/zeroclaw}"

[ "$(uname -m)" = "aarch64" ] || { echo "This pinned asset is for aarch64 (64-bit Raspberry Pi OS); got $(uname -m)." >&2; exit 1; }

work="$(mktemp -d)"          # downloads are untrusted: fresh directory, removed on exit
trap 'rm -rf "$work"' EXIT
curl --fail --location --silent --show-error --output "$work/$ASSET" "$URL"
echo "${SHA256}  $work/$ASSET" | sha256sum --check --status || { echo "Checksum mismatch; refusing to install." >&2; exit 1; }

mkdir -p "$DEST"
tar -xzf "$work/$ASSET" -C "$work"
install -m 0755 "$(find "$work" -type f -name zeroclaw | head -n1)" "$DEST/zeroclaw"
"$DEST/zeroclaw" --version
echo "Installed to $DEST/zeroclaw. Export RCD_ZEROCLAW_BIN=$DEST/zeroclaw for the adapter and tests."
