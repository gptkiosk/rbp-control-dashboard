#!/usr/bin/env bash
# Build the RCD Linux arm64 release archive from a clean, committed source tree.
#
# Usage: scripts/release/build-linux-arm64.sh [--out DIR] [--repro]
#   --out DIR   output directory (default: <repo>/dist-release)
#   --repro     build twice into separate directories and require identical bytes
#
# Clean-source gate: the repository must be a git work tree with no tracked, staged or untracked
# change. Without a .git directory no commit can be recorded, so no release can be built.
# The packer itself (scripts/release/release.py) enforces the same rules; this wrapper states them
# first and re-verifies the written files. Requires git, python3.11 or later and, for the
# hash-pinned lock, apps/api/locks/linux-arm64.txt (scripts/release/release.py lock).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${REPO}/dist-release"
REPRO=0
PLATFORM="linux-arm64"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) [ $# -ge 2 ] || { echo "error: --out needs a directory" >&2; exit 2; }; OUT="$2"; shift 2 ;;
    --repro) REPRO=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "git is required"
PY="${RCD_RELEASE_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || die "python3 is required (set RCD_RELEASE_PYTHON to override)"
"$PY" -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || die "python 3.11 or later is required"

if [ ! -e "${REPO}/.git" ]; then
  die "${REPO} has no .git directory: a release needs a committed, clean git work tree. Initialise the repository from the public one first (see packaging/README.md)."
fi
git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "$REPO is not a usable git work tree"

# Any tracked change, staged change or untracked file stops the build.
DIRTY="$(git -C "$REPO" status --porcelain --untracked-files=all)"
if [ -n "$DIRTY" ]; then
  echo "$DIRTY" >&2
  die "source tree is dirty; commit or stash every change before building a release"
fi

LOCK="${REPO}/apps/api/locks/${PLATFORM}.txt"
[ -f "$LOCK" ] || die "missing ${LOCK}: run 'python3 -I scripts/release/release.py lock' (needs uv and PyPI access) and commit it"

COMMIT="$(git -C "$REPO" rev-parse --verify HEAD)"
echo "source  ${COMMIT} (clean)"

RELEASE_PY="${REPO}/scripts/release/release.py"
build() {
  "$PY" -I "$RELEASE_PY" build --platform "$PLATFORM" --out "$1"
}

mkdir -p "$OUT"
if [ "$REPRO" = 1 ]; then
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/rcd-repro.XXXXXX")"
  trap 'rm -rf "$WORK"' EXIT
  echo "repro   building twice into separate directories"
  build "${WORK}/build-1" >/dev/null
  build "${WORK}/build-2" >/dev/null
  for f in "${WORK}"/build-1/*.tar.gz "${WORK}"/build-1/*.manifest.json; do
    name="$(basename "$f")"
    cmp -s "$f" "${WORK}/build-2/${name}" || die "reproducibility check failed: ${name} differs between two builds"
  done
  echo "repro   identical archive and manifest bytes across two builds"
fi

build "$OUT"

ARCHIVE="$(ls -1 "$OUT"/rcd-*-"${PLATFORM}".tar.gz 2>/dev/null | tail -n 1)"
[ -n "$ARCHIVE" ] || die "no archive was written to $OUT"
MANIFEST="${ARCHIVE%.tar.gz}.manifest.json"
# Re-verify the files as written to disk, not only the in-memory copies the packer checked.
"$PY" -I "$RELEASE_PY" verify "$MANIFEST" --artifact "$ARCHIVE" \
  --expect-product rcd --expect-platform "$PLATFORM"
echo "output  ${ARCHIVE}"
echo "        ${MANIFEST}"
