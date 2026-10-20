# Model recovery and bootstrap

Settings → Coordinator setup → **Model recovery** (`/profile#route-recovery`) contains the operator’s ordered fallback list. Changes apply to future planning requests and editable story maps. Existing approved story routes are retained. The default is manual recovery; select routes and explicitly enable automatic recovery. Up to six configured routes can be selected. Availability means the executable/configuration was found, not that live credentials or a provider response have been verified.

## Billing and permissions

Configured Claude/Codex membership routes consume the account’s quota; optional provider overage still applies. On a free-only installation, the operator can explicitly allow membership routes alongside free routes. Paid API routes remain refused unless the operator separately enables **Allow separately approved paid API routes**, then approves the specific planning/task use. A membership does not include provider API charges. Paid planning alternatives need separate API approval on the planning request or manual retry; a saved fallback list alone cannot authorize them. Price checks, budget caps, model locks, execution scopes and human approval gates remain effective.

## Bounded recovery

Every planning runtime receives the same output contract and the same central schema/semantic checks. With recovery enabled, an invalid output receives one repair attempt with validation feedback, then untried approved routes are eligible. Each planning step tries a route at most once after that repair. Manual retry may explicitly authorize another attempt. Project-level retry resumes the failed step on the same card unless planning from scratch is requested. Completed earlier steps and all attempts remain in history.

A validated approved dependency graph is sufficient to create its story cards; failed or malformed dispatch advice cannot rewrite that graph or force a new project. Bootstrap starts from an app-owned editable plan and dispatches that graph after operator approval without planning-provider calls.

When alternatives are included on future story maps, operator plan approval authorizes those exact routes. Provider outages and quota/rate limits can hand off within that approved list. Timeouts on editing tasks stop for review of partial work. An incomplete report is not accepted as completed work automatically.

## Local route telemetry

The app samples at most 500 terminal local runs over seven days by runtime and requested model. Categories include provider, rate limit, timeout, invalid planning output, sign-in, policy and execution failures. Three provider, rate-limit, timeout or invalid-output failures among the last five attempts trigger a recommendation and move that fallback behind healthier alternatives. Advice includes possible cost and a direct link to the toggle; it never turns on a paid route. No prompts, raw provider errors, credentials or account identities are returned by this telemetry endpoint. Process success does not verify task correctness.

## Bootstrap sequence

**Start agent setup** creates or reopens the current bootstrap project. Review and submit the built-in stories directly; model planning is optional. Hermes checks each selected platform, the operator resolves or excludes missing prerequisites, Hermes prepares selected missing role guidance and shared project areas, and verification and human acceptance follow. Existing agents and files are preserved. Changes outside approved workspaces need the ordinary scoped tools/permissions; otherwise the task stages guidance and provides a linked manual action. Staged files are never reported as registered agents. External provider availability and physical Pi behavior still require verification on the installed host.
