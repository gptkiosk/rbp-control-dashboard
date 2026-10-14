#!/bin/bash
# Publish the GitHub Release for a version that is committed and pushed: the tag v<version> on that
# commit, with the notes taken from its CHANGELOG.md section. Run by the operator with their own gh
# login; publication requires explicit operator authorization.
#
#   scripts/release/publish-release.sh --version 0.2.0 --target <commit> [--repo owner/name] [--prerelease] [--package] [--dry-run]
#
# Refuses when the commit is not on GitHub, the commit's version differs, the changelog has no dated
# section for the version, or a tag or release already exists. Then roll the running app onto the
# tag with scripts/upgrade-driver.sh, so the footer shows the commit the release names.
#
# --package creates only the tag. The platform release workflow then builds the package,
# signs its manifest and creates a DRAFT release with these same notes, which you review and publish
# on GitHub. It needs the repository secret RELEASE_SSH_PRIVATE_KEY and refuses without it. Without
# --package a plain release (notes, no package) is created, which the in-app updater cannot install.
set -euo pipefail
version=""; target=""; repo=""; pre=0; dry=0; package=0
here="$(cd "$(dirname "$0")" && pwd)"; root="$(cd "$here/../.." && pwd)"; gh_bin="${MCD_GH:-gh}"; leaks_bin="${MCD_GITLEAKS:-gitleaks}"
while [ $# -gt 0 ]; do case "$1" in
  --version) version="$2"; shift 2;; --target) target="$2"; shift 2;; --repo) repo="$2"; shift 2;;
  --prerelease) pre=1; shift;; --package) package=1; shift;; --dry-run) dry=1; shift;; -h|--help) sed -n 2,19p "$0"; exit 0;; *) echo "unknown option $1" >&2; exit 2;; esac; done
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo "--version must be a semantic version" >&2; exit 2; }
[ -n "$target" ] || { echo "--target (the commit the release names) is required" >&2; exit 2; }
die() { echo "release: $*" >&2; exit 1; }
[ -n "$repo" ] || repo="$(python3 -I -c "import json,sys;print(json.load(open(sys.argv[1]))['repository'])" "$root/packaging/product.json" 2>/dev/null)" || die "no --repo and no packaging/product.json repository"
tag="v$version"
sha="$(git -C "$root" rev-parse --verify -q "$target^{commit}")" || die "commit $target is not in this checkout"
at_target() { git -C "$root" show "$sha:$1" 2>/dev/null; }
actual="$(at_target apps/api/version.py | sed -n 's/^__version__ *= *"\(.*\)".*/\1/p' | head -n 1)"
[ "$actual" = "$version" ] || die "commit ${sha:0:7} carries version '${actual:-none}', not $version"
notes="$(mktemp)"; trap 'rm -f "$notes"' EXIT
tmp_cl="$(mktemp)"; at_target CHANGELOG.md > "$tmp_cl"
python3 -I "$here/changelog.py" notes "$version" --repo "$repo" --changelog "$tmp_cl" > "$notes" || { rm -f "$tmp_cl"; die "the changelog is not ready for $version"; }
rm -f "$tmp_cl"
command -v "$leaks_bin" >/dev/null 2>&1 || die "gitleaks is required to publish (brew install gitleaks)"
prev_tag="$(git -C "$root" describe --tags --abbrev=0 --match 'v[0-9]*' "$sha^" 2>/dev/null || true)"
if [ -n "$prev_tag" ]; then range="$prev_tag..$sha"; else range="$sha"; fi
"$leaks_bin" git "$root" --log-opts="$range" --redact --no-banner -l error >/dev/null 2>&1 || die "gitleaks reported a possible secret in $range; review it (a .gitleaksignore entry records a reviewed false positive)"
"$gh_bin" api "repos/$repo/commits/$sha" --jq .sha >/dev/null 2>&1 || die "commit ${sha:0:7} is not on GitHub yet (push it first)"
if "$gh_bin" api "repos/$repo/git/ref/tags/$tag" >/dev/null 2>&1 || "$gh_bin" release view "$tag" --repo "$repo" >/dev/null 2>&1; then die "$tag already exists in $repo; releases are never moved or replaced (publish a higher version)"; fi
if [ "$package" = 1 ]; then
  "$gh_bin" secret list --repo "$repo" 2>/dev/null | grep -Eq '^RELEASE_SSH_PRIVATE_KEY([[:space:]]|$)' \
    || die "--package needs the repository secret RELEASE_SSH_PRIVATE_KEY (punchlist N9: the operator creates the signing key); the workflow would fail at signing, so no tag was created"
fi
echo "release: $repo $tag on ${sha:0:7}$([ "$pre" = 1 ] && echo ' (prerelease)')$([ "$package" = 1 ] && echo ' (tag only; the workflow drafts the release with the package)')"; echo "---- notes ----"; cat "$notes"; echo "---------------"
[ "$dry" = 0 ] || { echo "dry run: nothing published"; exit 0; }
if [ "$package" = 1 ]; then
  "$gh_bin" api -X POST "repos/$repo/git/refs" -f "ref=refs/tags/$tag" -f "sha=$sha" >/dev/null || die "could not create the tag $tag"
  echo "tagged: $tag on ${sha:0:7}. The draft release (package, signature, notes) appears at https://github.com/$repo/releases when the workflow finishes; review it and publish it there."
  exit 0
fi
flags=(--repo "$repo" --target "$sha" --title "$tag" --notes-file "$notes")
[ "$pre" = 1 ] && flags+=(--prerelease) || flags+=(--latest)
"$gh_bin" release create "$tag" "${flags[@]}"
echo "published: https://github.com/$repo/releases/tag/$tag"
