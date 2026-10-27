# Model recovery and bootstrap

Settings → Coordinator setup → **Model recovery** (`/profile#route-recovery`) contains the operator’s ordered fallback list. Changes apply to future planning requests and editable story maps. Existing approved story routes are retained. The default is manual recovery; select routes and explicitly enable automatic recovery. Up to six configured routes can be selected. Availability means the executable/configuration was found, not that live credentials or a provider response have been verified.

## Billing and permissions

Configured Claude/Codex membership routes consume the account’s quota; optional provider overage still applies. Which cost classes may run is set in **Settings → Models & providers** ([route policy](route-policy.md)); Model recovery shows them and links there. Paid API routes remain refused unless the policy allows paid API and the operator approves the specific planning/task use. A membership does not include provider API charges. Paid planning alternatives need separate API approval on the planning request or manual retry; a saved fallback list alone cannot authorize them. Price checks, budget caps, model locks, execution scopes and human approval gates remain effective.

## Bounded recovery

Every planning runtime receives the same output contract and the same central schema/semantic checks. With recovery enabled, an invalid output receives one repair attempt with validation feedback, then untried approved routes are eligible. Each planning step tries a route at most once after that repair. Manual retry may explicitly authorize another attempt. Project-level retry resumes the failed step on the same card unless planning from scratch is requested. Completed earlier steps and all attempts remain in history.

A validated approved dependency graph is sufficient to create its story cards; failed or malformed dispatch advice cannot rewrite that graph or force a new project. Bootstrap starts from an app-owned editable plan and dispatches that graph after operator approval without planning-provider calls.

When alternatives are included on future story maps, operator plan approval authorizes those exact routes. Provider outages and quota/rate limits can hand off within that approved list. Timeouts on editing tasks stop for review of partial work. An incomplete report is not accepted as completed work automatically.

## Local route telemetry

The app samples at most 500 terminal local runs over seven days by runtime and requested model. Categories include provider, runtime, rate limit, timeout, invalid planning output, sign-in, policy and execution failures. Three provider, runtime, rate-limit, timeout or invalid-output failures among the last five attempts trigger a recommendation and move that fallback behind healthier alternatives. Advice includes possible cost and a direct link to the toggle; it never turns on a paid route. No prompts, raw provider errors, credentials or account identities are returned by this telemetry endpoint. Process success does not verify task correctness.

## Bootstrap sequence

Coordinator setup is done by the dashboard itself; see [agent roles](agent-roles.md#coordinator-setup). **Start validation project** creates or reopens a small project with one read-only story per ready platform; its stories use the same route recovery as any other project.

## Deleting projects and usage history

Deleting a closed project removes its app tasks, run details/logs, ledger, saved outputs and project grants. The working folder stays. Usage-only accounting stays separately, including unpriced records so an unknown bill is not silently dropped. Paid, free and unknown records contain usage metadata rather than prompts, answers, working paths or links to deleted tasks. Native telemetry supersedes matching retained snapshots to avoid counting twice.

Native agent sessions belong to the agent runtime and may include work outside this app. Project deletion does not erase those native sessions. The overview lists configured agents separately; historical sessions and cost estimates remain in the agent explorer. Exact `openrouter/free` aliases are zero list price unless the runtime reports a different actual cost, which remains authoritative.
