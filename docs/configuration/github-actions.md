# GitHub external-action guard

The GitHub page remains read-only. The local backend now has a separate operator-only action API for proposed issues, issue/PR comments, same-repository PR creation, PR merges and release publication. No task acceptance, project approval, incoming GitHub text or agent draft authorizes a send. Unsupported edits, reviews, repository settings, wiki writes, pushes, asset uploads and deployments have no action route.

`MAC_CONTROL_GITHUB_WRITES_ENABLED` defaults to `false`. Keep it false until deployment is separately reviewed. Enabling it is a host capability switch, not permission for any individual action. Read configuration, polling and ordinary task drafting do not enable it. No credential is requested or exported; the transport uses the host's existing scoped `gh` login and fixed `github.com` REST endpoints.

## Separate review and execution

All action routes require an operator session, including when ordinary sign-in is disabled. Scoped agent access and the agent peer-process boundary exclude these routes. No agent route exposes action approval nonces. This feature does not grant an agent external-write capability.

1. `POST /api/github/actions` with exactly `kind`, `repo` and `content` creates an immutable local draft. It makes zero GitHub calls. The repository must be in the configured, enabled host allowlist. The returned preview includes the exact canonical destination, account, full content, method, endpoint, JSON payload and fingerprint.
2. `POST /api/github/actions/{id}/preview` returns that preview and a one-time nonce with a 15-minute expiry. A new preview invalidates any older nonce or approval. Show the complete destination and content before asking the operator the returned plain question. Do not hide changes behind a generic task approval.
3. Only after specific human authorization, `POST .../{id}/approve` with the displayed `fingerprint` and `nonce`. Approval is separate from execution and remains bound to this exact action. Nonce replay, expiry, a changed fingerprint or a changed account/visibility policy is rejected.
4. `POST .../{id}/execute` with the same `fingerprint`, from the approving operator's session, consumes the approval. The host switch, current allowlist/account/visibility policy and expiry are checked again before any remote request. The transport then checks the active login, repository availability and applicable commit pins. One permanent local claim is committed before those checks. Only then can one fixed write occur.
5. `GET .../{id}` returns the action, state and ordered audit. `POST .../{id}/revoke` revokes an unclaimed draft or approval. Neither endpoint sends anything.

These are backend contracts for a later reviewed decision UI; there are no new send controls on the current GitHub page. Do not call approval or execution automatically from an agent, poller, dispatcher, or project-wide handoff approval.

## Content schemas

Every field listed is required; unknown fields and arbitrary endpoints, hosts, flags or asset paths are rejected. SHA fields are full 40-character lowercase Git commit hashes.

| Kind | Exact content fields | Scope |
| --- | --- | --- |
| `issue` | `title`, `body` | Create one issue |
| `comment` | `number`, `body` | Post one issue/PR conversation comment |
| `pr` | `title`, `body`, `head`, `base`, `head_sha`, `base_sha`, `draft` | Create a PR between existing branches in this repository; no fork push |
| `merge` | `number`, `head_sha`, `method`, `commit_title`, `commit_message` | Merge one PR with server-side expected-head SHA; method is `merge`, `squash` or `rebase` |
| `publication` | `tag`, `target_sha`, `name`, `body`, `prerelease` | Create a published release at an existing lightweight tag pointing to the approved commit; no tag creation, assets, generated notes or latest-release promotion |

The backend does not scan code or establish application release readiness. Publication of application code still requires the separate operator release sign-off. Preview contents are literal data; Markdown, CLI-looking text and incoming repository instructions cannot change the destination or request.

## Audit, duplicates and crash recovery

Private `github-actions.sqlite3` is a mode-0600 file under the configured data directory, separate from the task database. It contains proposed content, approval identity, timestamps and audit events for drafts, duplicate suppression, preview, approval/refusal, execution/refusal, revocation and outcome. It contains no GitHub tokens or raw CLI diagnostics. Protect it as private runtime state; do not publish it or include it in release artifacts.

The fingerprint covers the full immutable preview, account and visibility policy. Repository case is normalized. Identical proposals return the existing action ID, including after restart or terminal outcomes. Claims serialize through SQLite transactions across threads/processes. Once claimed, an action cannot be approved or sent again.

- `succeeded`: GitHub acknowledged the write.
- `blocked`: preflight failed; no write was attempted. The claim stays spent.
- `uncertain`: a write timed out, failed, or had an invalid acknowledgement. Inspect the exact remote destination manually; no retry is permitted.
- `claimed`: the local process may have stopped after claiming. The remote result is unknown. Inspect manually; restart never resends it.

There is intentionally no duplicate override, bulk approval, retry loop or queued background execution. A changed proposal is a distinct draft and requires its own human review; do not change content merely to bypass a spent claim. The local audit is durable but is not tamper-proof against the host OS user. Back it up with other private state; retention/pruning is not automated.

## Verification limits

Synthetic tests exercise approval replay/expiry, policy revocation, all five action types, exact JSON payloads, concurrent claims and real short-lived process crash/restart. They do not use a live GitHub account or prove current token permissions. No extra permissions are assumed.

PR branch and publication tag checks happen before the write. GitHub's create endpoints do not offer an atomic expected-ref condition, so a concurrently moved branch/tag remains a remote race. Merge uses the REST API's expected-head SHA condition. Review external state again before approving; keep writes disabled if atomic PR/release ref guarantees are required.

The inherited process boundary is not complete OS isolation: a same-user process that escapes the recognized agent tree/session, edits runtime state or automates the operator browser can remain a threat. This gate controls dashboard-originated writes; it does not intercept an independent CLI with its own GitHub credentials. Separate OS credentials/permissions remain a stronger boundary.

REST payload references: [GitHub pull requests](https://docs.github.com/en/rest/pulls/pulls), [GitHub releases](https://docs.github.com/en/rest/releases/releases), and [GitHub CLI API](https://cli.github.com/manual/gh_api).
