# Release flow (MCD and RCD)

A version is finished when it is **committed, on GitHub, released with its notes, and the running app
is on that release**. The same steps apply to both products; MCD and RCD share major.minor. RCD installs update from the
GitHub release; MCD's own host upgrades with its driver script.

1. **Commit** small, conventional commits on the working branch. Update `CHANGELOG.md`: move the
   entries from `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD` under Added, Changed or Fixed, and add
   the `[X.Y.Z]:` link at the bottom. Bump `apps/api/version.py` and `apps/web/package.json` together
   (a test fails if they differ, and another fails if the changelog has no section for the version).
2. **Test.** The API suite, the web type-check and tests, and `scripts/check-docs.py`.
3. **Push** the branch to the product's GitHub repository.
4. **Release.** The operator runs, from the checkout:

   ```sh
   scripts/release/publish-release.sh --version X.Y.Z --target <commit> --dry-run   # shows the notes
   scripts/release/publish-release.sh --version X.Y.Z --target <commit>
   ```

   It creates the tag `vX.Y.Z` on that commit and the release at
   `https://github.com/<owner>/<repo>/releases`, with the notes taken from the changelog section and a
   link to the full comparison. It refuses when the commit is not on GitHub, carries another version,
   has no dated changelog section, or the tag already exists. Tags and releases are never moved or
   replaced; a mistake is fixed by the next version. Use `--prerelease` for a candidate.
5. **Roll.** An installed Raspberry Pi picks the release up from the app: Settings, Application update,
   Check for updates. The panel shows the release's changelog, then downloads, verifies (size, digest,
   signature) and stages the package, and installs it only after an explicit confirmation. A failed
   health check rolls back to the previous version by itself. The same steps are available from the
   helper command line when the web UI cannot start. See `docs/install/updates-rollback-recovery.md`.
6. **Confirm.** The footer names the release's version and commit, and the update panel lists the
   installed and staged versions.

Release notes are written for people reading the Releases page, so each entry says what changed for
the operator, not how. A release cannot be built (`scripts/release/release.py build`) without them.
