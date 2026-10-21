# Standing engineering rules

These rules come from operator decisions and from real failures on hardware. A change that undoes one of them needs the operator's explicit approval; another agent's plan or a tidier design is not enough. They apply to both products (MCD on the Mac, RCD on the Raspberry Pi).

## Parity
- MCD and RCD match in function, look and ease of use wherever the platform allows. An improvement made to one goes to both in the same release.
- Run `python3 scripts/check-shared-features.py --peer <other checkout>` before release; it must report 0 contract failures.
- Shared code never imports a module that only one product has. For example, build an agent's environment with `Dispatcher._env(agent)`, not RCD's `legacy_adapters`.

## Token efficiency (agent prompts)
- Every story run pays for its whole prompt, and free models have small context windows. Keep prompts bounded.
- Long material goes in a file whose path is in the prompt, not inline. The project brief is the model: each story carries the first `BRIEF_LIMIT` (6,000) characters, and the cut-off names a private file with the full brief (`project-<id>-brief.md`, beside the project ledger).
- Add a context field only when there is data (for example `reference_art` appears only when a project has reference images), and keep its text short.
- Report the prompt-size impact of any change to story context, the planner brief or the guidance packs.

## Coordinator setup
- Setup is done by the dashboard itself, with no model involved, so every run behaves the same. Do not move it back into a Hermes-run project.
- Two modes: *Stable start* creates only what is missing from the versioned templates in `packs/agents/`. *I'll configure the platforms myself* changes nothing and only checks.
- Never overwrite an existing agent, file or folder. Refuse a stale preview (digest). Run applies in the background with item states and a log, and never twice at once (server lock and disabled controls).
- OpenClaw itself is the source of truth for registered agents: use `openclaw agents list --json`, with the config file only as a fallback, everywhere targets are checked (`native_routes.read` merges the CLI's list, cached briefly). A page never waits for the CLI: reads return the last known list and refresh it in the background; only actions that must be current (submitting a plan) pass `wait=True`. CLI output can start with log lines such as `[plugins] ready`, so find the JSON with `native_routes.json_list`.

## Repository setup
- A project's repository is set up by the dashboard at submission, as step 1, with no model and in a fixed order: private repo, starter files on `main`, clone in the project folder, `project-<id>/setup` branch, GitHub list, branch grant. Every step can be retried.
- Hermes and other agents never get GitHub write access for this; do not move it into a story or give the Coordinator `gh repo create` permission. The operator chose this on 2026-10-21.

## Models, routes and failover
- Every run needs an explicit model; the dispatch gate refuses a blank one (PRICE_UNKNOWN). Never leave a Hermes or OpenClaw story on "Agent default". Free-model pinning gives it a reviewed free model and free fallbacks, and validation stories name their model.
- A high-risk story never uses a free route, as its main route or as a fallback.
- *Fix automatically* makes only safe-direction changes: it raises risk to the area minimum, drops free fallbacks from high-risk stories, and moves a high-risk story to an approved non-free fallback or the cheapest subscription route.
- *Use one route for all stories* keeps each story's fallbacks unless the operator chooses backups. Every route change is a new revision the operator reviews before submitting; a submitted plan is never changed.
- A failover from one OpenClaw model to another keeps the story's agent target. Never fall back to a hard-coded agent such as `mm-main`.

## Interface
- A slow load says what is loading (LoadingCard), and says it is still working after a few seconds.
- An approved plan is never edited; a project in progress takes dated brief amendments instead, given to later stories within a bounded size.
- A long action shows that it is working (state, progress and a log) and cannot be started twice.
- Say where work comes from. For example, Coordinator setup itself creates no tasks; its validation project does.
- Reference art lives in a project's `media/references/`. Uploads are checked by their bytes, not their name, and are sent as the raw request body, so no new upload dependency is needed.

## Tests
- At least one test of each external-command path uses the real runner, not only a fake. A fake runner hid MCD's broken setup environment in 0.6.40–0.6.41.
- A test that depends on product defaults (MCD subscription billing, RCD free-only) pins those defaults itself.
