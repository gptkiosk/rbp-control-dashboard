# Projects

## Purpose

Open **Projects** (`/projects`) to turn a larger goal into a reviewed visual map, bounded stories and ordered execution. Creating/viewing a draft uses no model tokens. Planning approval and story execution approval are separate. Every agent story needs instructions, a definition of done, scope, an assignment and dependencies.

## Screenshots

Pending capture: `projects-brief.png` (new project), `projects-planning-map.png` (visual map), `projects-story-assignment.png` (story instructions) and `projects-story-assignment-model.png` (model and route choices). No RCD capture exists yet.

## Controls

### From goal to work

1. Create a project with a name, goal, constraints/exclusions and an allowlisted working directory. Set **Story assignment preference**, centered on Balanced by default, and save the draft.
2. Review **Plan** (the button names your planner). Hermes, the Coordinator, coordinates an approved subscription planner, MCD runs the selected CLI and Hermes reviews the returned proposal. Paid API planning needs its own approval. A validated plan returns for your review; it does not begin story execution.
3. Edit phases and stories on the map. Use Arrange/Fit map; review instructions, scope, definition of done, dependencies, agent/model, OpenClaw target and Read/Edit mode. Add ordered alternate model routes if wanted. Circular dependencies are refused.
4. Use **Review & submit** to freeze the reviewed revision, workspace, assignments and routes. Hermes proposes a dependency-respecting order; MCD materializes each story once on the board.
5. In **Stories & runs**, inspect each successful result against its definition of done. Review the handoff summary and artifact files before accepting. Human stories require the actual operator decision. Dependents wait for acceptance, not just a successful process exit.
6. Pause dispatch to prevent new stories from starting; active runs can finish. Resume when ready. Publication/security decisions remain explicit human stories where the plan requires them.

### Project types and media

1. In **New project**, pick a type (Web app, Packaged app or Website property) or accept the one MCD suggests from your brief. The type adds planning guidance, known failure points, plan checks and human sign-offs. See [Project types](../configuration/project-types.md).
2. A project whose folder has `media/slots.json` gets a **Media** tab. Tick the spending acknowledgement, choose a tier (a website's clips start on the cheapest video tier), press Generate and watch progress under that slot's button. Review each candidate, **Accept and publish** or ask for **Another take**. See [Media models](../configuration/media-models.md).
3. On a failed story whose agent reported unfinished work, **Accept anyway…** records your reason and the agent's report and releases dependent stories.

### Assignment preference and routes

Economy recommends OpenClaw for routine bounded work, reserving subscriptions for difficult/sensitive work. Capability favors Claude/Codex. Balanced splits recommendations by task complexity. This is an advisory preference, not a fixed percentage, quality guarantee or projected discount. OpenClaw's gateway is local; its models can run in the cloud. Subscription fees stay fixed even when quota is conserved.

Moving the slider does not rewrite existing stories. Save it and request a new plan for revised recommendations, or edit each story individually before submission. Legacy documents missing the preference retain their earlier default for compatibility.

Claude/Codex use existing subscription logins when configured for subscription billing. Recognized quota/rate-limit failures can checkpoint partial work and try an unattempted, previously approved route. Other failures/timeouts require explicit **Retry same story** or **Retry with**. Switching models within one account may share an exhausted quota; MCD does not guarantee global quota preflight or free-provider availability.

Automatic Hermes/OpenClaw alternatives are limited to approved free routes or capped Google Gemini 2.5 Flash. Explicit model assignments disable the native inherited fallback chain for that run. A blank model follows native configuration. An approved API/BYOK acknowledgment does not authorize unrelated paid models. The shared configured OpenRouter cap covers that key's reported usage, including BYOK when enabled; it is not a universal Google invoice cap or a cap for other keys/direct calls.

### Shared memory and workspaces

Each story receives its approved goal, constraints, ownership, current instructions, accepted artifact references and recent handoffs/decisions/checkpoints. The append-only **Shared memory** ledger keeps the full history; run context includes up to 20 bounded recent records within roughly 180 KiB. Unverified partial checkpoints remain labeled. This does not merge every agent's private history. **Export context** supports a manual handoff to a native session; context supplies information, not new authorization.

Sequential mode adds a serial dependency between stories in the shared reviewed workspace. Parallel mode requires a clean Git root/committed source and creates story worktrees. Independent work can occupy available dispatcher slots, while dependencies and directory/target conflicts still apply. Workspaces coordinate ownership; they do not create an OS sandbox for Hermes/OpenClaw.

At handoff, inspect diffs and new files and select the reviewed files for a local snapshot. All changed files must be handled to leave the workspace clean. Nothing automatically pushes, publishes or merges the source branch. If prerequisite integration conflicts, resolve it, confirm through **Review integration**, then retry the story explicitly.

A supported read-only Claude story that returns an unfinished plan shows **Approve output & continue**. MCD can save one proposed Markdown output while Claude remains restricted to Read/Glob/Grep. Review that saved output afterward; its hash must still match before acceptance. Continuation approval is not handoff acceptance.

### Live viewing and project-wide handoffs

An active project's **Live map** refreshes status every three seconds without saving the plan. Opening or selecting a project is read-only. Blue nodes are running, amber need review/approval, teal are queued, gray are blocked, green are done and red have failed. Phase colors summarize their stories; the project bubble shows completed/total stories. Select a node and **Open task** to drill down.

Choose **Approve all agent handoffs…** to review the included scope. Keep the future-handoffs checkbox for automatic advancement of successful eligible agent results in this exact revision, or clear it to pass only currently waiting successful results. Acknowledge the policy and submit. **Require individual reviews** disables it; pausing the project also pauses automatic acceptance.

This passes agent-reported completion into shared memory, not independent artifact verification. Human decisions, security/credential/license reviews, external actions and isolated Git snapshots remain manual. Failed jobs, empty results and unfinished plans are never marked complete by this policy. It does not grant new model routes, paid API permission, output-continuation permission, publication or commit actions.

## Settings involved

- Project preference, planner choice, execution mode, workspace and node assignments are saved in the versioned project document.
- Profile preferences seed new projects. Discord pairing supports planning intake/status according to the configured integration; an unpaired preview does not prove notification delivery. Hermes asks whether a diagram is needed before sending one.
- Native configuration supplies current targets/model suggestions. Retired targets, stale revisions and unapproved routes are refused.
- Billing configuration determines subscription accounting and API approval checks. Keep the existing shared spending cap when reviewing routes.

## Troubleshooting

- **Everything is queued:** find the earliest unaccepted handoff or human decision in Stories & runs. Sequential mode waits even when later stories have no original explicit dependency.
- **Planning failed after a successful model run:** inspect the validation error. **Resume saved plan** can revalidate a recoverable saved proposal without rerunning the subscription planner. Otherwise review **Retry planning**; neither action authorizes story execution.
- **Missing instructions/scope/definition of done:** complete the named story's required fields and review the proposal again. Do not accept an incomplete artifact to release the queue.
- **Retired target or changed branch:** restore the approved state or prepare a new reviewed plan; do not silently reroute running work.
- **Changed artifact hash:** review the current output and refresh the evidence. A stale/missing output cannot be accepted.
- **Snapshot includes unrelated edits:** inspect each file; do not select unreviewed work simply to clear the gate.

## Related pages

- [Tasks](tasks.md): board approval shortcuts and current run evidence.
- [Agents](agents.md): model usage, subagents and billing coverage.
- [Chat](chat.md): separate direct conversations.
- [Settings](../configuration/settings.md) and [environment configuration](../configuration/environment.md).

## Model lock

In a submitted active or paused project, open **Stories & runs** and enable **Model lock**. Failed tasks stay on their assigned model and stop for review instead of automatically retrying or switching to an approved equivalent. The default is off, retaining the project's reviewed quota alternatives and transport retry policy. The toggle is revision-checked, persists on the approved project snapshot and records the operator decision in shared memory. It applies to subsequent failure/retry decisions; it does not cancel a running task or undo a previous model change. Explicit manual retry or reviewed reassignment remains available.

## Planning activity

While a plan is being prepared, the panel below the project title shows the current Coordinator stage: review the brief, build the map, then check the plan. Completed stages and the current task's queued, running or approval state come from the project status, refreshed every three seconds. Open the linked planning task for its log and result. No model reasoning or estimated percentage is shown.

The spinner stops when approval, recovery or plan review is needed. Reduced-motion settings stop the animation. The ordinary story counter appears after dispatch; planning an empty map is not shown as “Not started, 0 / 0.” This display adds no provider calls or prompt tokens.
