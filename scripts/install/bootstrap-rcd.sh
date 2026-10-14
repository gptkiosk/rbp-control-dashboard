#!/usr/bin/env bash
# First-time install of a released Raspberry Pi Control Dashboard (RCD) build on Linux arm64
# (Raspberry Pi OS 64-bit). Later upgrades belong to the in-app updater.
#
# Usage:
#   bootstrap-rcd.sh --version X.Y.Z --manifest-sha256 HEX [options]
#   bootstrap-rcd.sh --archive FILE --manifest FILE --manifest-sha256 HEX [options]
#
# Options:
#   --root DIR          install root (default: ${XDG_DATA_HOME:-~/.local/share}/rcd-control)
#   --python PATH       absolute path to Python 3.11, the version the release pins
#   --manifest-sha256   SHA-256 of the .manifest.json, copied from the release page. Required:
#                       it is the trust anchor until a signing key is configured.
#   --allow-prerelease  required for a prerelease version or manifest
#   --dry-run           download/verify everything, print the plan, change nothing
#   -h, --help          show this help
#
# --version downloads rcd-X.Y.Z-linux-arm64.tar.gz and .manifest.json from the public release
# vX.Y.Z of gptkiosk/rbp-control-dashboard. No token is needed. Only HTTPS is used, and redirects
# must land on GitHub hosts. --archive/--manifest use local files instead.
#
# Verification happens before anything is installed: the manifest must match the pinned digest,
# the archive must match the manifest's size and SHA-256, the manifest must name product rcd and
# linux-arm64, and every archive member must be a plain file or directory inside the release
# root. The packaged update helper then verifies the whole package again during staging.
#
# Layout: <root>/versions/<version>-<sha256[:12]>/ holds the release and its venv at runtime/.
# <root>/current is a symlink to it. The user service runs <root>/current. Runtime data stays
# in ~/.rcd-control and is never inside <root>.
#
# Installs: systemd user units rcd-api.service (port 8800) and rcd-update-recover.timer.
# Needs: Python 3.11 with venv (sudo apt install python3.11 python3.11-venv), curl (for
# --version), and a systemd user session. For boot-time start without a login run:
# sudo loginctl enable-linger <user>
set -euo pipefail

REPO_SLUG="gptkiosk/rbp-control-dashboard"
# Fingerprint of the public key that signs releases (also in packaging/allowed_signers and the release
# guide). The first install is anchored by the digest you pass; once it is in place, a package that ships
# this key lets later updates be verified by signature, so the updater needs no pasted digest.
RELEASE_KEY_FINGERPRINT="SHA256:CV1+p0B/fa4k3eDVXkZSoph1/Mkrth9v0jBg6Z9WOW8"
PLATFORM="linux-arm64"
PORT=8800
SERVICE_UNIT="rcd-api.service"
RECOVER_TIMER="rcd-update-recover.timer"
ROOT="${RCD_INSTALL_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/rcd-control}"
DATA="${MAC_CONTROL_DATA_DIR:-$HOME/.rcd-control}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

VERSION=""
ARCHIVE=""
MANIFEST=""
MANIFEST_SHA=""
PY_ARG=""
ALLOW_PRERELEASE=0
DRY_RUN=0

die() { echo "error: $*" >&2; exit 1; }
need_value() { [ $# -ge 2 ] || die "$1 needs a value"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version) need_value "$@"; VERSION="$2"; shift 2 ;;
    --archive) need_value "$@"; ARCHIVE="$2"; shift 2 ;;
    --manifest) need_value "$@"; MANIFEST="$2"; shift 2 ;;
    --manifest-sha256) need_value "$@"; MANIFEST_SHA="$(printf '%s' "$2" | tr 'A-F' 'a-f')"; shift 2 ;;
    --root) need_value "$@"; ROOT="$2"; shift 2 ;;
    --python) need_value "$@"; PY_ARG="$2"; shift 2 ;;
    --allow-prerelease) ALLOW_PRERELEASE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

# --- arguments ----------------------------------------------------------------------------

SEMVER='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z][0-9A-Za-z.-]*)?$'
if [ -n "$VERSION" ]; then
  [ -z "$ARCHIVE" ] && [ -z "$MANIFEST" ] || die "use either --version or --archive with --manifest, not both"
  printf '%s' "$VERSION" | grep -Eq "$SEMVER" || die "--version must be X.Y.Z or X.Y.Z-pre"
  MODE=download
elif [ -n "$ARCHIVE" ] && [ -n "$MANIFEST" ]; then
  MODE=local
else
  die "give --version X.Y.Z, or --archive FILE --manifest FILE (see --help)"
fi
printf '%s' "$MANIFEST_SHA" | grep -Eq '^[0-9a-f]{64}$' \
  || die "--manifest-sha256 must be the 64-hex digest from the release page"

# Paths end up in unit files and JSON; keep them to a plain character set.
valid_path() {
  case "$1" in /*) ;; *) return 1 ;; esac
  case "$1" in *[!A-Za-z0-9._/+:-]*) return 1 ;; esac
}
valid_path "$ROOT" || die "--root must be an absolute path of letters, digits and ._/+:- only: $ROOT"
valid_path "$DATA" || die "MAC_CONTROL_DATA_DIR must be an absolute plain path: $DATA"

# --- Python -------------------------------------------------------------------------------

# The release pins Python 3.11 (manifest runtime.python); the update helper refuses any other.
find_python() {
  local candidate found
  # An explicit --python is the only candidate; a bad path must not fall back to another interpreter.
  if [ -n "${PY_ARG}" ]; then
    set -- "${PY_ARG}"
  else
    set -- "${RCD_PYTHON:-}" python3.11 python3
  fi
  for candidate in "$@"; do
    [ -n "${candidate}" ] || continue
    found="$(command -v "${candidate}" 2>/dev/null)" || continue
    [ "$("${found}" -I -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" = "3.11" ] || continue
    printf '%s' "${found}"
    return 0
  done
  return 1
}
PY="$(find_python)" || die "Python 3.11 is required. On Raspberry Pi OS: sudo apt install python3.11 python3.11-venv (or pass --python PATH)"
case "$PY" in /*) ;; *) die "the Python path must be absolute: $PY" ;; esac
"$PY" -I -c 'import venv, ensurepip' 2>/dev/null \
  || die "$PY lacks venv/ensurepip. On Raspberry Pi OS: sudo apt install python3.11-venv"

# --- host ---------------------------------------------------------------------------------

WORK="$(mktemp -d "${TMPDIR:-/tmp}/rcd-bootstrap.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

fetch() { # Fetch one HTTPS hop at a time and validate its destination before the next request.
  local url="$1" dest="$2" max="${3:-104857600}" headers="${WORK}/headers.$$" body="${WORK}/body.$$" code location hop=0
  while [ "$hop" -le 5 ]; do
    case "$url" in https://github.com/*|https://objects.githubusercontent.com/*|https://release-assets.githubusercontent.com/*|https://github-releases.githubusercontent.com/*) ;; *) die "download URL uses an unexpected host: $url" ;; esac
    code="$(curl --silent --show-error --proto '=https' --tlsv1.2 --max-redirs 0 \
      --connect-timeout 15 --max-time 900 --speed-limit 1024 --speed-time 60 \
      --max-filesize "$max" --dump-header "$headers" --output "$body" --write-out '%{http_code}' "$url")" \
      || die "download failed: $url"
    case "$code" in
      2*) mv "$body" "$dest"; rm -f "$headers"; return 0 ;;
      3*) location="$(awk 'BEGIN{IGNORECASE=1} /^Location:/{sub(/^[^:]*:[[:space:]]*/,""); sub(/\r$/,""); value=$0} END{print value}' "$headers")"
          [ -n "$location" ] || die "redirect has no Location header: $url"
          case "$location" in https://*) url="$location" ;; *) die "redirect must use an absolute HTTPS URL: $location" ;; esac
          hop=$((hop + 1)) ;;
      *) die "download returned HTTP $code: $url" ;;
    esac
  done
  die "too many download redirects: $1"
}

if [ "$MODE" = download ]; then
  ASSET="https://github.com/${REPO_SLUG}/releases/download/v${VERSION}/rcd-${VERSION}-${PLATFORM}"
  fetch "${ASSET}.manifest.json" "$WORK/release.manifest.json" 1048576
  fetch "${ASSET}.tar.gz" "$WORK/release.tar.gz" 104857600
  MANIFEST="$WORK/release.manifest.json"
  ARCHIVE="$WORK/release.tar.gz"
fi
[ -f "$MANIFEST" ] || die "manifest not found: $MANIFEST"
[ -f "$ARCHIVE" ] || die "archive not found: $ARCHIVE"

GOT_SHA="$(sha256sum "$MANIFEST" | cut -d' ' -f1)"
[ "$GOT_SHA" = "$MANIFEST_SHA" ] || die "manifest sha256 is $GOT_SHA, not the pinned $MANIFEST_SHA; refusing this package"

# Package checks, run before the host is touched. Prints: version artifact-sha256 channel.
CHECK_PY='
import hashlib, json, re, sys, tarfile
manifest_path, archive_path, want, allow_pre = sys.argv[1:5]
problems = []
def need(ok, why):
    if not ok:
        problems.append(why)
try:
    with open(manifest_path, "rb") as f:
        m = json.loads(f.read().decode("utf-8"))
except (OSError, ValueError) as exc:
    sys.exit("error: manifest is not valid JSON: %s" % exc)
if not isinstance(m, dict):
    sys.exit("error: manifest is not a JSON object")
need(m.get("schema") == "dashboard-release-manifest/v1", "manifest schema is not dashboard-release-manifest/v1")
need(m.get("product") == "rcd", "manifest is for product %r, not rcd: cross-product packages are refused" % (m.get("product"),))
plat = m.get("platform") if isinstance(m.get("platform"), dict) else {}
need(plat.get("key") == "linux-arm64" and plat.get("os") == "linux" and plat.get("arch") == "arm64",
     "manifest is not for linux-arm64")
version = m.get("version") if isinstance(m.get("version"), str) else ""
need(re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z][0-9A-Za-z.-]*)?", version) is not None,
     "manifest version is not X.Y.Z")
channel = m.get("channel")
need(channel in ("stable", "prerelease"), "manifest channel is %r; only stable or prerelease packages install" % (channel,))
need(channel != "prerelease" or allow_pre == "1", "a prerelease needs --allow-prerelease")
src = m.get("source") if isinstance(m.get("source"), dict) else {}
need(src.get("release_eligible") is True, "manifest was not built from a clean committed tree")
need(not want or want == version, "manifest version %s is not the requested %s" % (version, want))
base = "rcd-%s-linux-arm64" % version
art = m.get("artifact") if isinstance(m.get("artifact"), dict) else {}
need(art.get("name") == base + ".tar.gz" and art.get("root") == base,
     "artifact name or root does not match version %s" % version)
with open(archive_path, "rb") as f:
    data = f.read()
need(art.get("size") == len(data), "archive is %d bytes; the manifest says %r" % (len(data), art.get("size")))
need(art.get("sha256") == hashlib.sha256(data).hexdigest(), "archive sha256 differs from the manifest")
if not problems:
    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            count = 0
            for mem in tf:
                count += 1
                parts = mem.name.split("/")
                bad = (not (mem.isreg() or mem.isdir()) or mem.name.startswith("/") or ".." in parts
                       or "\\" in mem.name or parts[0] != base or (mem.mode & 0o6000))
                if bad or count > 5000:
                    problems.append("archive member refused: %r" % (mem.name,))
                    break
    except tarfile.TarError as exc:
        problems.append("archive is not a valid tar.gz: %s" % exc)
if problems:
    for p in problems:
        sys.stderr.write("error: %s\n" % p)
    sys.exit(1)
print(version, art["sha256"], channel)
'
PACKAGE_INFO="$("$PY" -I -c "$CHECK_PY" "$MANIFEST" "$ARCHIVE" "$VERSION" "$ALLOW_PRERELEASE")" \
  || die "package refused; nothing was installed"
read -r VERSION ART_SHA CHANNEL <<< "$PACKAGE_INFO"
BASE="rcd-${VERSION}-${PLATFORM}"
VID="${VERSION}-${ART_SHA:0:12}"
echo "package  ${BASE}.tar.gz  sha256 ${ART_SHA}  channel ${CHANNEL}  manifest pinned"

# --- host and existing-install checks -----------------------------------------------------

[ "$(uname -s)" = Linux ] || die "this installer is for Linux (Raspberry Pi OS); it cannot run on $(uname -s)"
case "$(uname -m)" in aarch64|arm64) ;; *) die "the host must be arm64 (uname -m reports $(uname -m))" ;; esac
command -v systemctl >/dev/null 2>&1 || die "systemctl not found: systemd is required"
systemctl --user show-environment >/dev/null 2>&1 \
  || die "no systemd user session; log in as the service user (or run loginctl enable-linger) and retry"
[ ! -e "$ROOT/current" ] || die "$ROOT/current already exists; RCD is installed. Upgrade with the in-app updater."
[ ! -e "$UNIT_DIR/$SERVICE_UNIT" ] || die "$UNIT_DIR/$SERVICE_UNIT already exists; refusing to replace it"
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
  die "something already answers on 127.0.0.1:${PORT}; stop it before installing"
fi

if [ "$DRY_RUN" = 1 ]; then
  echo "dry run: nothing was changed. A real run would:"
  echo "  - stage ${VID} under ${ROOT}/versions and point ${ROOT}/current at it (Python ${PY})"
  echo "  - write ${ROOT}/helper/helper.json and the update helper (trust: release signature when the package ships the release key ${RELEASE_KEY_FINGERPRINT}, otherwise a pinned digest)"
  echo "  - install ${UNIT_DIR}/${SERVICE_UNIT} and rcd-update-recover.timer, then start them"
  echo "  - check http://127.0.0.1:${PORT}/healthz"
  exit 0
fi

# --- install ------------------------------------------------------------------------------

mkdir -p "$ROOT/helper" "$ROOT/inbox" "$ROOT/versions" "$ROOT/state" "$DATA" "$UNIT_DIR"
chmod 700 "$ROOT" "$ROOT/helper" "$ROOT/inbox" "$ROOT/versions" "$ROOT/state" "$DATA"

mkdir "$WORK/tree"
tar -xzf "$ARCHIVE" -C "$WORK/tree" --no-same-owner --no-same-permissions
SRC="$WORK/tree/${BASE}"
[ -f "$SRC/apps/api/update_helper.py" ] || die "the archive has no update helper"

# The helper is the only code that stages or switches; it runs from this pinned copy. Every module
# the helper imports, and the recovery CLI, must be here: update_helper imports release_fetch at load.
for f in update_helper.py update_engine.py release_fetch.py release_verify.py update_recovery.py; do
  [ -f "$SRC/apps/api/$f" ] || die "the archive has no $f"
  cp "$SRC/apps/api/$f" "$ROOT/helper/$f"
  chmod 600 "$ROOT/helper/$f"
done

CONFIG_PY='
import json, os, sys
path, root, db, python, health, prerelease = sys.argv[1:7]
cfg = {"schema": "dashboard-update-helper/v1", "product": "rcd", "platform": "linux-arm64",
       "root": root, "db_path": db, "health_url": health, "python": python,
       "service": {"kind": "systemd-user", "unit": "rcd-api.service"},
       "trust": {"kind": "pinned-digest"}, "readiness_timeout_s": 90, "keep_versions": 3,
       "allow_prerelease": prerelease == "1", "allow_downgrade": False}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(cfg, f, indent=2, sort_keys=True)
    f.write("\n")
'
"$PY" -I -c "$CONFIG_PY" "$ROOT/helper/helper.json" "$ROOT" "$DATA/data.db" "$PY" \
  "http://127.0.0.1:${PORT}/healthz" "$ALLOW_PRERELEASE"

HELPER=("$PY" -I "$ROOT/helper/update_helper.py" --config "$ROOT/helper/helper.json")
cp "$ARCHIVE" "$ROOT/inbox/${BASE}.tar.gz"
cp "$MANIFEST" "$ROOT/inbox/${BASE}.manifest.json"
chmod 600 "$ROOT/inbox/${BASE}.tar.gz" "$ROOT/inbox/${BASE}.manifest.json"

STAGED="$("${HELPER[@]}" stage "$BASE" --manifest-sha256 "$MANIFEST_SHA")" \
  || { echo "$STAGED" >&2; die "staging refused the package; nothing was switched"; }
printf '%s' "$STAGED" | grep -q '"ok": true' || { echo "$STAGED" >&2; die "staging did not succeed"; }
[ -d "$ROOT/versions/$VID" ] || die "expected staged version directory $ROOT/versions/$VID"

"${HELPER[@]}" activate-initial "$VID" >/dev/null \
  || die "activate-initial failed; $ROOT/current was not created"

# Later updates: trust the release signature instead of a pasted digest, when this package ships the key
# and it is the one named above. Failure here is not fatal: the install stays on the pinned-digest mode.
if "${HELPER[@]}" enable-signed-updates --fingerprint "$RELEASE_KEY_FINGERPRINT" >/dev/null 2>&1; then
  echo "updates will be verified by the release signature (key ${RELEASE_KEY_FINGERPRINT})"
else
  echo "note: this package does not ship the release key, so later updates need the manifest digest pasted in the updater" >&2
fi

# Units come from the activated version, so they match the code they start.
render_unit() { # TEMPLATE DEST PYTHON WORKDIR
  sed -e "s|__UPDATE_ROOT__|${ROOT}|g" -e "s|__PYTHON_PATH__|$3|g" \
      -e "s|__WORKING_DIRECTORY__|$4|g" -e "s|__DATA_DIR__|${DATA}|g" \
      -e "s|__SERVE_SCRIPT__|serve.py|g" -e "s|__RESTART_SEC__|10|g" \
      -e "/^Environment=MAC_CONTROL_DATA_DIR=/a Environment=MAC_CONTROL_UPDATE_ROOT=${ROOT}" "$1" > "$2.tmp"
  if grep -q '__[A-Z_]*__' "$2.tmp"; then rm -f "$2.tmp"; die "unrendered placeholder in $1"; fi
  chmod 644 "$2.tmp"
  mv "$2.tmp" "$2"
}
TEMPLATES="$ROOT/current/ops/systemd"
render_unit "$TEMPLATES/rcd-api.service.template" "$UNIT_DIR/$SERVICE_UNIT" \
  "$ROOT/current/runtime/bin/python" "$ROOT/current/apps/api"
render_unit "$TEMPLATES/rcd-update-recover.service" "$UNIT_DIR/rcd-update-recover.service" "$PY" "$ROOT"
cp "$TEMPLATES/rcd-update-recover.timer" "$UNIT_DIR/$RECOVER_TIMER"
chmod 644 "$UNIT_DIR/$RECOVER_TIMER"

if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze --user verify "$UNIT_DIR/$SERVICE_UNIT" >/dev/null 2>&1 \
    || echo "note: systemd-analyze reported warnings for $SERVICE_UNIT" >&2
fi
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_UNIT"
systemctl --user enable --now "$RECOVER_TIMER"

if command -v loginctl >/dev/null 2>&1 && [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo "note: run 'sudo loginctl enable-linger $(id -un)' so the service starts at boot and survives logout" >&2
fi

for _ in $(seq 1 20); do
  if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    echo "installed RCD ${VERSION} (${VID}) under ${ROOT}; ${SERVICE_UNIT} healthz OK on 127.0.0.1:${PORT}"
    exit 0
  fi
  sleep 0.5
done
die "installed ${VERSION} but healthz did not answer within 10 s. This is a first install, so there is no previous version to roll back to. Inspect: journalctl --user -u rcd-api -n 50. Remove it with the steps in packaging/README.md, uninstall section."
