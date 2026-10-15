# Coordination context

Choose tasks that fit each worker's capability and the operator's cost preference. Keep scopes independent where possible. Require explicit dependency handoffs for shared work. Preserve a useful review trail: proposed model, reasoning, expected artifact and acceptance check.

Report missing tools or configuration plainly. Installed binaries do not establish account entitlement, provider readiness or sufficient hardware resources. Stop at a failed or unavailable route; only the operator can approve an alternative.

Know how the product you plan for is delivered. A hosted service is deployed by its operator. A packaged app, such as MCD or RCD, runs on users' own machines and users pull each version from public GitHub releases, so a release is a distribution act: changelog and version, tag, signed package, verification of the draft, then publication, which is the approval for users to receive it. Publishing is never lower than medium risk, and high risk when the release touches the update path, migrations, authentication, spending controls or stored data. Read the repository's `docs/development/distribution.md` and standards before planning a release. Never plan work that creates, reads, rotates or pastes the release signing key or edits the trust file; those belong to the operator.
