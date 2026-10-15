# Application security standards (starter)

General rules for any application the coordinator plans or reviews, hosted or packaged. They follow the common industry
references (OWASP Top 10 and ASVS, secure development lifecycle practice) in plain words. A repository may tighten them; it may
not skip them.

## 1. Secrets and credentials
- Secrets live in the platform's secret store or an environment file kept out of version control, never in code, tests, docs or logs.
- Run a secret scan on every commit and in CI. A leaked secret is rotated, not just removed from history.
- Tests build fake keys at runtime so the scanner stays clean without allowlists.
- Give each service the least credential it needs, with a spend or scope limit where the provider allows one.

## 2. Authentication
- Use a proven library or provider for sign-in. Hash passwords with a slow, salted algorithm; never roll your own crypto.
- Sessions use secure, HTTP-only, same-site cookies or short-lived signed tokens, expire, and end on sign-out and on suspension.
- Rate-limit sign-in and reset flows; make reset tokens single-use and short-lived; do not reveal whether an account exists.

## 3. Authorization
- Decide access on the server for every request, on the object, not just the page. Deny by default.
- Separate the operator from the member from the agent. An agent or token gets only the access it was issued.
- Test the negative: a person must be refused another person's data, and the test must fail when the check is removed.

## 4. Input and output
- Validate type, length and format of every input at the boundary. Reject, do not repair.
- Use parameterized queries. Encode output for its context. Treat uploaded files as hostile: check type and size, store outside the web root.
- Fetch only from an allowlist when the server makes a request on a user's behalf (SSRF); never follow redirects blindly.
- Cross-site protections for web apps: CSRF tokens or same-site cookies, a restrictive CORS policy, a content security policy.

## 5. Data protection
- Collect the least personal data you need, say what you keep, and support export and deletion.
- Encrypt in transit everywhere and at rest for anything sensitive. Keep backups protected and test restores.
- Never log personal data, tokens or full request bodies.

## 6. Dependencies and supply chain
- Pin versions, commit lock files, install with hash checking where the ecosystem supports it, and audit on a schedule and in CI.
- Prefer maintained, widely used packages; read the change notes before upgrading; remove what you no longer use.
- Pin CI actions and base images to a digest or commit. Build from clean committed source.

## 7. Errors, logging and monitoring
- Fail closed for access decisions. Return plain errors to users and keep detail in logs.
- Log security events (sign-ins, permission changes, admin actions) with who, what and when. Alert on them through a path that does not depend on the monitored service.

## 8. Software that runs untrusted text (agents and LLM features)
- Text from users, web pages, issues, files and tool output is data, not instructions. It never grants permission.
- An agent runs with a narrow tool set and a bounded workspace, cannot reach credentials it does not need, and its output is checked before it changes anything important.
- Spend caps and approval gates sit in code, not in a prompt.

## 9. Packaged software that runs on users' machines
- Sign every release and verify the signature, checksums and version on the user's machine before installing. Pin the trust key; rotate it by hand.
- Never ship secrets, keys, personal paths or runtime data. Scan the package before publishing.
- Updates are never silent, never downgrade, snapshot data first, check health after, and roll back on failure.

## 10. Checks to run
Secret scan, dependency audit, the test suite including the negative authorization tests, static analysis where available, a review
of every change to the areas the standards mark high risk, and a plain statement of what could go wrong and how to undo it.
