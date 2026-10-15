# Delivering a hosted web app (starter pattern)

For software the operator runs on their own infrastructure. The pattern has worked for small teams shipping a live service with
no staging environment; add environments if you have them.

1. **Change on a branch with tests.** CI runs the tests, the type check and the build, a secret scan and a dependency audit.
   Only changed areas need to run for docs-only edits, but a change to CI itself runs everything.
2. **Merge when CI is green.** Wait for CI on the main branch too; it is the only check on a commit pushed directly.
3. **Build the image from the exact commit** (full commit id, not a short one) and verify it exists before pointing anything at it.
4. **Migrate first, additively.** Run schema changes against the new image before the service rolls, so the old version keeps
   working while the new one starts. Never ship a migration the running version cannot tolerate.
5. **Roll a new revision** through the infrastructure-as-code path, not by hand, so the recorded configuration matches reality.
   Check the branch you commit to; verify the roll landed where the deploy reads it.
6. **Verify in production, not in the tool's exit status.** Ask the live service for its release (version and commit), check the
   health endpoint, and exercise one thing specific to the change.
7. **Keep a rollback.** Know the previous revision, keep migrations reversible or compatible, and roll back first, investigate second.
8. **Watch it.** Errors, latency and spend are alerted through a path that does not depend on the service being watched.

**Refinement loop.** After release, read failure logs and user reports, turn each into a small story, and measure whether the
change helped (first-pass success, time, cost). Update the standards when a mistake repeats.

**Who approves.** Low and medium risk changes can run end to end under the automation. High-risk changes (money, authentication,
data, migrations, secrets, infrastructure) state what ships and how to roll back, then wait for an explicit go for that release.
Destroying infrastructure, secret values, DNS, deleting data and spending money stay with a person.
