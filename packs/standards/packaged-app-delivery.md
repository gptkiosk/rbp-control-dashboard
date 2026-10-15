# Delivering a packaged app (starter pattern)

For software that runs on users' own machines and is pulled from a public release. There is no server of yours that is deployed
to: publishing a release is what makes a version reachable.

1. **Change, tests and docs** on a branch; behavior users can see is documented in the same change.
2. **Changelog.** A dated section for the version, written for the people reading the releases page: what changed for them.
3. **Version.** One version source, mirrored wherever the app reports it; a test fails if copies differ or the changelog section is missing.
4. **Checks.** Tests, type check, build, docs check, secret scan, and a content scan of the package for secrets, personal paths and runtime data.
5. **Merge** through a reviewed pull request with green CI, then **tag** that exact commit. Tags are immutable: never moved, deleted or replaced.
6. **Build and sign in CI** from clean committed source. The release signing key is a repository secret that only the owner holds.
   The build produces the archive, a manifest listing every file with a hash, a detached signature over the manifest, and a checksum list.
   It publishes as a **draft**.
7. **Verify the draft before publishing:** download all assets, check every checksum, verify the signature against the pinned
   public key, and confirm the archive's hash and the version appear in the manifest. A failed download is not a pass.
8. **Publish.** Publishing is the approval for users to receive the version. Only a published, non-draft release whose pre-release
   flag matches its version, newer than what is installed, with a valid signature, is offered.
9. **Users update on their own terms.** Never automatic, never while work is in flight, snapshot data first, switch atomically,
   check health, roll back on failure, never downgrade.
10. **User data survives.** Keep user data, settings and customizations outside the install folder, make schema changes additive, give
    every new setting a safe default, let loaders ignore keys they do not know, keep shipped text and user copies in separate files
    (the user's copy wins), and never overwrite a file the user edited. Document what an update keeps, replaces and never touches.
11. **A bad release is fixed forward** with a higher version. Do not move the tag or replace assets.

**Risk.** Publishing reaches machines you cannot reach. Treat it as at least medium risk, and high risk when it touches the update
path, migrations, authentication, spending controls, secrets or stored data. The signing key, release secret and trust file belong
to the owner; automation never creates, reads, rotates or pastes them.
