# How RCD reaches users: the release and update pipeline

RCD is not a hosted web app. It is packaged code that runs on a user's own Raspberry Pi (Pi 4 or newer, 64-bit Raspberry Pi OS), and users pull each new version
from this public repository's GitHub Releases. There is no server of ours that is "deployed to". Publishing a release is what
makes a version reachable, and that act is the approval: nothing is pushed to anyone, and nothing installs without the user's
own confirmation. This page is the reference for people and agents who prepare a release; it applies to MCD in the same
way, with the differences noted in section 7.

## 1. The two kinds of Bamcio software

| | Hosted properties (upubhub, wegamehub, ops) | Packaged apps (RCD, MCD) |
|---|---|---|
| Runs on | Bamcio's own cloud (Cloud Run) | the user's machine |
| Ship by | build an image, migrate, roll a revision, apply infrastructure | tag, build a signed package, verify, publish a release |
| Who decides it is live | the operator rolls it | the user installs it, when they choose |
| Rollback | roll back the revision | the updater restores the previous version and the data snapshot |
| Failure cost | visible to everyone at once | stranded or broken installs on machines we cannot reach |

The second row is why a release is checked harder than a deploy: a bad package cannot be recalled from machines that already
installed it. The only fix is a newer version.

## 2. From change to release (the steps)

1. **Change** on a branch, with tests. Behavior that users can see is documented in `docs/` in the same change.
2. **Changelog.** Move the entries from `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD` under Added, Changed or Fixed, add
   the `[X.Y.Z]:` link at the bottom, and write for the person reading the Releases page: what changed for them, not how. The
   release notes are taken from this section; a release cannot be built without it.
3. **Version.** Bump `apps/api/version.py` and `apps/web/package.json` (and the two version lines at the top of
   `package-lock.json`) together. Tests fail if they differ or if the changelog has no section for the version. MCD and RCD
   share major.minor (the feature level); the patch is each product's own.
4. **Checks.** The API suite, `npm run type-check`, `npm test`, `npm run build`, `python3 scripts/check-docs.py`, and a secret
   scan of the staged changes. A package also passes the content scan in `scripts/release/release.py`.
5. **Merge** to `main` through a pull request with green CI.
6. **Tag.** `scripts/release/publish-release.sh --version X.Y.Z --target <merge commit> --package` creates only the tag
   `vX.Y.Z` on that commit. It refuses when the commit is not on GitHub, carries another version, has no dated changelog
   section, the scan finds a secret, or the tag already exists. Tags are immutable: never moved, deleted and re-made, or
   replaced.
7. **Build and sign.** The tag starts `.github/workflows/release-on-tag.yml`, which builds the package from clean committed
   source on a Linux arm64 runner, writes the manifest, signs the manifest bytes with the dedicated release key (a repository secret
   that only the operator holds; agents never handle it), and creates a **draft** release with the notes, the archive
   `rcd-X.Y.Z-linux-arm64.tar.gz`, `rcd-X.Y.Z-linux-arm64.manifest.json`, its detached `.sig` and `SHA256SUMS`.
8. **Verify the draft before publishing** (see section 4). A failed download is not a pass.
9. **Publish.** `gh release edit vX.Y.Z --draft=false --latest`. This is the approval for users to receive the version.
10. **Confirm** the release page, then roll your own copy through the same updater users have.

## 3. What makes a version offered to users

The updater reads the public Releases list for this repository and offers a version only when all of these hold:

- the release is **published** (not a draft) and its tag is `vX.Y.Z`;
- the GitHub "pre-release" flag agrees with the version (a `-` suffix means pre-release, otherwise stable). The default
  channel is **stable**; users can opt in to **prerelease**;
- the version is newer than the one installed (the updater never downgrades);
- it carries the three allowlisted assets for the user's platform, and the manifest's signature verifies against the release
  key pinned in the install (`packaging/allowed_signers`), with the tag pointing at exactly the commit the signature names.

A draft is invisible. Publishing is therefore the single approval gate, and an unsigned or mismatched release is refused on
the user's machine even if it is published.

## 4. Verification checklist before publishing

```sh
gh release download vX.Y.Z --dir <empty temp dir>            # retry on a transient failure; do not skip
shasum -a 256 -c SHA256SUMS                                  # every asset reports OK
ssh-keygen -Y verify -f packaging/allowed_signers -I dashboard-release -n dashboard-release \
  -s rcd-X.Y.Z-linux-arm64.manifest.json.sig < rcd-X.Y.Z-linux-arm64.manifest.json               # "Good ... signature"
# the archive's sha256 appears in the manifest, and the manifest's version and commit are the release's
```

Publish only when all of it passes. A key rotation means updating `packaging/allowed_signers` by hand from a source you trust
before trusting the new key.

## 5. What users do

- **Packaged install** (the only managed path): **Profile, Updates**. With release-signature trust enabled
  (`enable-signed-updates`), **Check for updates** then **Update to X.Y.Z** is one confirmation: the server downloads the three
  allowlisted assets, verifies the manifest signature against `<root>/helper/allowed_signers`, stages the package and installs
  it with the drain check, data snapshot, health check and automatic rollback. Without signature trust the user pins the
  manifest SHA-256 from the release page. The panel shows numbered steps and a log, and survives a page reload.
- A source checkout or dev build gets the manual steps only.

Updates are never automatic and never run while work is in flight. The user sees each step, the log and the result, and a
failed update is rolled back to the previous version and data snapshot. Release notes are shown with the version, so write
them for the user (section 2, step 2).

## 6. If a published release is bad

Do not move or delete the tag and do not replace the assets. Publish a fixed, higher version as soon as possible; the updater
offers it to everyone on the channel. As an emergency measure only the operator may return the bad release to draft so no new
user fetches it; installs that already updated keep it until the fixed version arrives. Say what happened in the changelog of
the fix.

## 7. RCD specifics

- Platform `linux-arm64`, packaged Python 3.11 (Raspberry Pi OS ships 3.11), service managed by a systemd user unit.
- **The updater is pinned.** Updates never replace the helper under `<root>/helper`. When a release changes `update_engine.py`
  or the helper, installed devices keep the old behavior until the user runs `refresh-helper` once from the current version
  (`python3 -I <root>/current/apps/api/update_helper.py --config <root>/helper/helper.json refresh-helper`). Say so in the
  release notes whenever the update path changed.
- A bootstrap written before 0.3.3 lacks `MAC_CONTROL_UPDATE_ROOT`; the panel shows manual steps until the drop-in in
  `docs/install/updates-rollback-recovery.md` is applied.
- Acceptance for an RCD release is on a real Pi, not only a Linux VM: update through the panel, confirm the footer and
  `/healthz` name the new version, and check the step log completed.

## 8. Rules for the coordinator and for agents

- A story that prepares a release is a job like any other, but **publishing is a distribution act**: it reaches machines the
  operator cannot reach. Treat it as at least medium risk, and high risk when the release touches the update path, migrations,
  authentication, the spend gate or anything that stores data. For a high-risk release the agent states what ships, the
  checks that passed and how users recover, then waits for the operator's explicit go before step 9.
- The signing key, the release secret and the trust file are the operator's. An agent never creates, reads, rotates or pastes
  them, and never edits `packaging/allowed_signers`.
- Do not publish a release from a tree with uncommitted changes, from a commit that is not on `main`, or before the checks in
  sections 2 and 4 pass. Report exactly which checks ran.
- Keep MCD and RCD in step: a feature lands in both before the minor version rises.
