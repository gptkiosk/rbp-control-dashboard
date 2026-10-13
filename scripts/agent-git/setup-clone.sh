#!/bin/bash
# Prepare one project clone for agent work: clone, cut the project branch from main, wire the
# credential helper, hooks and limits. Pushes nothing. Run by the operator or a setup story.
#
#   setup-clone.sh --repo gptkiosk/mac-control-dashboard --dest DIR --project 5 --slug installable-releases
#                  [--from origin/baseline-branch] [--pre-push-cmd 'cd apps/api && .venv/bin/python -m pytest -q'] [--allow-rc-tags]
set -euo pipefail
repo=""; dest=""; project=""; slug=""; pre_push=""; rc=false; from_ref="origin/main"
while [ $# -gt 0 ]; do case "$1" in
  --repo) repo="$2"; shift 2;; --dest) dest="$2"; shift 2;; --project) project="$2"; shift 2;;
  --slug) slug="$2"; shift 2;; --pre-push-cmd) pre_push="$2"; shift 2;; --from) from_ref="$2"; shift 2;; --allow-rc-tags) rc=true; shift;;
  *) echo "unknown option $1" >&2; exit 2;; esac; done
[[ "$repo" =~ ^gptkiosk/(mac-control-dashboard|rbp-control-dashboard)$ ]] || { echo "repo must be one of the two MCD/RCD repositories" >&2; exit 2; }
[[ "$project" =~ ^[0-9]+$ ]] || { echo "--project must be the numeric MCD project id" >&2; exit 2; }
[[ "$slug" =~ ^[a-z0-9][a-z0-9.-]{0,40}$ ]] || { echo "--slug must be lowercase letters, digits, dots or dashes" >&2; exit 2; }
[ -n "$dest" ] || { echo "--dest is required" >&2; exit 2; }
here="$(cd "$(dirname "$0")" && pwd)"
agent_dir="${MCD_AGENT_GIT_DIR:-$HOME/.rcd-control/agent-git}"
branch="project-${project}/${slug}"; base_tag="project-${project}-base"

# Install the operator-owned helper and hooks outside every repository.
mkdir -p "$agent_dir/hooks" "$agent_dir/state"; chmod 700 "$agent_dir"
cp "$here/git-credential-mcd-agent" "$agent_dir/"; cp "$here"/hooks/* "$agent_dir/hooks/"
chmod 755 "$agent_dir/git-credential-mcd-agent" "$agent_dir"/hooks/*

[ -d "$dest/.git" ] || git clone -q "https://github.com/${repo}.git" "$dest"
cd "$dest"
git fetch -q origin
if git rev-parse -q --verify "refs/heads/$branch" >/dev/null; then git switch -q "$branch"
elif git rev-parse -q --verify "refs/remotes/origin/$branch" >/dev/null; then git switch -q -c "$branch" --track "origin/$branch"
else git switch -q -c "$branch" "$from_ref"; fi
git rev-parse -q --verify "refs/tags/$base_tag" >/dev/null || git tag -a "$base_tag" "$from_ref" -m "Base of $branch (from $from_ref)"

git config user.name "MCD agent"
git config user.email "215035619+gptkiosk@users.noreply.github.com"
git config core.hooksPath "$agent_dir/hooks"
git config --replace-all credential.helper ""
git config --add credential.helper "$agent_dir/git-credential-mcd-agent"
git config credential.useHttpPath true
git config pull.ff only; git config push.default nothing
git config mcd.project "$project"; git config mcd.branch "$branch"; git config mcd.baseTag "$base_tag"
git config --type=bool mcd.requireTrailers true; git config --type=bool mcd.allowRcTags "$rc"
git config --int mcd.maxCommitLines 400; git config --int mcd.maxCommitFiles 25; git config --int mcd.maxPushesPerHour 6
[ -n "$pre_push" ] && git config mcd.prePushCmd "$pre_push"
echo "ready: $dest on $branch (base tag $base_tag). Nothing was pushed."
