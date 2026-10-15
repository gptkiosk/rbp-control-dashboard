# starter engineering standards

> The standards this dashboard ships with. They apply to a project whose repository has no `docs/development/standards.md` of its own, and
> they are meant to be changed: copy this file to your data folder (see `docs/configuration/starter-standards.md`) and edit the
> tables. A repository's own standards always win over these. Nothing here grants an agent any permission.

## Definition of done

| Change touches | Run | Notes |
|---|---|---|
| any code change | the project's automated tests, and its linter and type checker where it has them | report what ran and what did not |
| dependencies | the package manager's audit command, and a clean install from the lock file | no unpinned or unreviewed package |
| any commit | a secret scan of the staged changes | never commit credentials, keys or real personal data |
| a database change | apply the migration to a copy of the data first and confirm the old version still works | additive; write the rollback plan |
| a user-visible change | check it in a running preview and update the docs and changelog | |
| a release | the release checklist for the delivery model (hosted or packaged) | see the delivery guides |

## Risk by area

| Area | Examples | Default risk | Route | Extra requirement |
|---|---|---|---|---|
| Authentication and sessions | sign-in, tokens, password reset, SSO | high | foundation model | security checklist; a person reviews |
| Authorization and permissions | roles, access checks, tenant isolation | high | foundation model | tests that fail when the check is removed |
| Payments and billing | checkout, subscriptions, webhooks, refunds | high | foundation model | test with real provider objects, not mocks |
| Secrets and credentials | keys, tokens, environment files | high | foundation model | never read, print or commit values |
| Personal or sensitive data | accounts, messages, exports, deletion | high | foundation model | minimize, protect, and honour deletion |
| Database migrations and schema | schema changes, backfills | high | foundation model | additive first; rehearse on a copy |
| Update, install and release path | updater, packaging, signing | high | foundation model | verify before publishing; fix forward |
| Infrastructure and deployment | cloud config, CI, containers | high | foundation model | plan before apply; verify after |
| Public API and input handling | endpoints, parsers, uploads, webhooks | medium | subscription or free with review | validate input; limit size and rate |
| Dependencies and supply chain | adding or upgrading packages | medium | subscription or free with review | audit; pin; read the changelog |
| Business logic | features, workflows, calculations | medium | subscription or free with review | tests for the rule, not only the path |
| User interface | pages, components, styling | low | free with review | check in a preview; keyboard and contrast |
| Documentation and copy | guides, changelog, help text | low | free | plain language; no machine-cadence tells |
| Tests only | new tests, fixtures | low | free | tests must fail without the code they guard |
| Research and triage | reading code, mining failures | low | free | read-only; no writes |

## Security checks for high-risk stories

- No secret, key, token or real personal data appears in code, tests, fixtures, logs or error messages.
- Every new input is validated on the server, with size and rate limits, and is never trusted because a client sent it.
- Every new action checks who is asking and whether they may do this to this object, on the server.
- Queries are parameterized; output is encoded for where it lands; redirects and fetched URLs are restricted.
- New dependencies are pinned, audited and justified; nothing is installed from an unverified source.
- Errors and logs say what failed without leaking internals; failures are closed, not open, for access decisions.
- A test exists that fails if the security check is removed.
- The story states what could go wrong and how to roll it back.
