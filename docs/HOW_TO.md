# Using Mac Control Dashboard

Open [MCD](http://127.0.0.1:8800/) and sign in with an allowed Google account.
Use **Help** in the header to ask a feature question, or **Help & how-tos** in the sidebar to browse these guides.
Help answers from built-in instructions locally, without sending questions to a model or changing settings.
Its Open links navigate to a section or open an unsubmitted form. You decide whether to save, approve, or run anything.
Help conversation stays in memory and clears on sign-out or reload. Never paste credentials into help.

On Tailscale, use your dashboard origin on port 9443 instead of localhost; in-app links retain the current origin.

## Set up RCD on your Raspberry Pi

A six-step wizard for local installation, Google access, agents, provider keys, subscriptions and navigation.

1. Open Setup wizard from the header account icon, Settings or this guide. New profiles also see Start setup wizard above their dashboard. Later hides the welcome prompt; the wizard remains available.
2. Review the Pi prerequisites (Raspberry Pi OS on a Pi 4 or newer) and save an allowed default working directory. Agent binaries run on the Pi even when you browse from a phone.
3. Configure Google OAuth privately on the host and sign in with an allowed account. The wizard explains callbacks, test users and the local importer; it does not collect OAuth client secrets.
4. Install Hermes and OpenClaw using their official guides. Check executable detection and independently confirm native provider/model routing and fallback spending caps. The wizard does not launch agents or grant permissions.
5. Save your OpenRouter key in encrypted, write-only profile storage. Check key with OpenRouter reads actual key spending; inference credentials still need native agent configuration.
6. Install and sign into Codex and Claude Code using eligible subscriptions on the Pi. For included membership usage, use native subscription sign-in; API/OpenRouter billing is separate. Desktop app login alone does not establish CLI readiness. Confirm the host sign-in yourself; RCD does not collect tokens or verify entitlement.
7. Try header Help chat and browse the main menu. Finish walkthrough saves your reviewed progress; pending items stay listed. Reopen and refresh checks after changes.

Setup progress belongs to your profile. Finishing the walkthrough does not complete project tasks, install software, change model routes, authorize paid usage or enable remote access.

[Open setup wizard](http://127.0.0.1:8800/setup) · [Manage private credentials](http://127.0.0.1:8800/profile#credentials-profile) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=setup)

## Connect your profile to Hermes on Discord

Create, revise and receive project plans without opening RCD; keep settings and credentials private.

1. Open Profile. Save your default workspace and assignment preference. Balanced is centered at 50 and is the default for new profiles.
2. Enter the Discord channel where Hermes replies and choose your configured HTTPS dashboard address. Enable plan notifications. If you want to start planning from Discord, select Allow my Discord requests to start subscription planning with Hermes coordination; this covers its configured free-first / capped BYOK route, not paid API planners or execution.
3. Choose Get pairing code and send the displayed instruction to Hermes in that channel within 10 minutes. Choose Check pairing. Unlink Discord revokes remote project access.
4. Ask Hermes to plan a project. It asks for missing goal, name or workspace and creates a draft with your preference. Request planning when ready. In RCD, New project → Submit to Hermes starts planning after the coordination checkbox is reviewed; Save draft starts no models.
5. Projects shows actual planning stages and Discord delivery status. When the map is ready, edit its stories in Projects or tell Hermes your changes. Hermes asks whether a diagram is needed; request the image to review dependencies and assignments off-app. Execution still needs Review & submit in RCD.
6. Save provider credentials using the password fields. Values are encrypted and write-only. OpenRouter checks report actual key spending; saving a key does not change native agent routing or its cap. Export/import preferences copies settings only and excludes secrets and Discord identity; review installation-specific paths and re-pair on a new Mac.

Keep the database and vault.key together in a private backup to recover encrypted credentials. Subscription logins, Google OAuth and gateway credentials remain private host setup. Uncertain Discord sends are not automatically retried.

[Open your profile](http://127.0.0.1:8800/profile) · [Connect Discord](http://127.0.0.1:8800/profile#discord-profile) · [Create a project](http://127.0.0.1:8800/projects?action=new) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=profile-discord)

## Plan a project with Hermes and a shared mind map

Turn a brief into reviewed stories, model assignments and shared handoffs.

1. Choose New project. Write the brief and select an allowed working directory. Set Story assignment preference: Economy favors OpenClaw free-first tasks; Capability favors Claude/Codex subscriptions; Balanced splits routine and difficult work. Save changes before requesting a plan.
2. Plan with Hermes starts a reviewed coordinator → subscription planner → Hermes review workflow. The slider guides suggestions rather than guaranteeing cost or quality. Change it under Project brief & planner and save/replan to revise recommendations; existing assignments stay untouched until you replan or edit them. The returned map is a proposal: select nodes to edit instructions, scope, definition of done, agents, models and prerequisites. Drag nodes or use Arrange.
3. Choose sequential execution or parallel isolated Git stories. Parallel mode requires a clean repository root; RCD creates story worktrees and local branches from its reviewed commit.
4. Review & submit freezes the saved revision and its approved model routes. Hermes orders the stories; RCD creates them once. Pause dispatch stops new stories while running ones can finish.
5. In Stories & runs, verify artifacts and checks, then accept the handoff. Dependent stories wait for acceptance and receive approved context. Review tracked diffs and explicitly select changed files to create a local handoff snapshot (or commit them yourself); prerequisite conflicts stop for review. Source branches are never merged automatically.

Shared memory is a project ledger injected into RCD project runs. Native private histories are not merged; Export context supports independent sessions. Up to 20 latest accepted handoffs/decisions/checkpoints fit within a bounded prompt; full records remain in Projects. Read/Edit is advisory for Hermes and OpenClaw.

[Create a project brief](http://127.0.0.1:8800/projects?action=new) · [Open project library](http://127.0.0.1:8800/projects) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=projects)

## Approve project handoffs and watch the live map

Batch routine agent handoffs or enable automatic handoffs for one approved revision.

1. Open the project library and select your running project. Live map is view-only and refreshes every three seconds; opening it does not save or replace the plan.
2. Read the story and phase colors: blue running, amber review or approval, teal queued, gray blocked, green done and red failed. The project bubble and completion counter summarize progress. Select a story and Open task for details.
3. Choose Approve all except human-required tasks. Review Included and Requires human input or approval. Keep the future-handoffs option selected to pass successful eligible results automatically, or clear it for a one-time batch.
4. Acknowledge the listed scope and submit. The same assignments, model routes and dependencies remain in force. Only a completed successful result with handoff text can pass; this does not independently verify artifacts.
5. Choose Require individual reviews to stop automatic handoffs. Pause dispatch also pauses automatic acceptance; running jobs may still finish into Review.

Tasks needing human interaction, decisions or required answers stay manual, including security/credential/license reviews, external actions and isolated Git snapshots. Failed runs and unfinished plans never pass as complete. Output continuation and paid-route changes retain their separate approvals. Approval applies to the exact submitted revision, not other projects.

[Open project library](http://127.0.0.1:8800/projects) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=project-approvals)

## Choose models and recover failed work

Configure ordered alternatives and retry the same task without rebuilding the project.

1. Open Settings → Coordinator setup → Model recovery. Enable automatic route recovery and select up to six configured alternatives in the order you want. A route can use a different runtime/model. Hermes retains the Coordinator guidance; planning helpers only return proposals.
2. On a free-only host, explicitly enable Allow membership routes alongside free models to use configured subscription accounts. Membership consumes shared account quota and any enabled account overage still applies. This switch does not enable paid API routes; their separate toggle and planning/task approval are required.
3. Planning permits one output repair on its approved route, followed by untried approved alternatives. Validation applies to every route. After all alternatives fail, the saved project and task remain available for a manual route choice; no project stories start before plan approval.
4. Open the failed planning task to choose another configured model. A paid route requires a separate API-charge acknowledgment. Membership access does not cover provider API billing. Global spending settings and host restrictions remain in force.
5. Enable Include alternatives in future project plans to put eligible free and membership alternatives on the editable story map. Review them before submitting. Provider/rate-limit failures may hand off to an approved untried route; model lock disables automatic story switching, and editing timeouts require review of partial work.
6. After three provider, runtime, timeout or output failures in the last five local attempts, the app recommends a route change with its possible cost and a link to the enabling toggle. It lowers that route’s recovery priority without changing permissions or enabling paid use.
7. Start agent setup in Coordinator setup to create or reopen a built-in, editable bootstrap plan. No provider call is needed to construct it. Review and submit the plan; the app releases its validated dependency order, then Hermes inspects readiness, prepares missing guidance, and leaves linked human prerequisites. Existing configurations are preserved.

Provider responses and free-model availability cannot be guaranteed. Telemetry samples up to 500 terminal local runs over seven days, and process success is not independent acceptance. Recovery preserves scope, workspace, dependencies, history and approval gates. The app never silently enables paid API fallback.

[Configure recovery routes and toggles](http://127.0.0.1:8800/profile#route-recovery) · [Start or reopen agent setup](http://127.0.0.1:8800/profile#coordinator-bootstrap) · [Review project models](http://127.0.0.1:8800/projects) · [Inspect actual key spending](http://127.0.0.1:8800/agents#openrouter-spending) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=project-models)

## Get started with RCD

Use Overview to check your Pi and agents, then open a feature for details.

1. Sign in with an allowed Google account. Overview shows Pi health, agent activity and alert delivery.
2. Use the sun/moon button in the header to switch the whole app between light and dark mode. Your choice is saved in this browser; without a saved choice, RCD follows your device appearance.
3. Open Agents for sub-agents and costs, Tasks for work, or Chat for a direct agent conversation.
4. Open Help chat in the header from any page. Ask a question or choose a topic; Open links take you to the feature.

[Open Overview](http://127.0.0.1:8800/) · [Open task board](http://127.0.0.1:8800/tasks) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=getting-started)

## Check live fleet status

Overview combines Pi health with top-level agent and sub-agent activity.

1. Read the sample age above the Pi tiles to check freshness.
2. In Agents, compare current RCD turns, recent captured activity and observed processes.
3. Select an agent or named sub-agent to open its explorer. Activity updates every five seconds; usage every fifteen seconds.

An observed process can be idle. “Recent activity” means a captured update within the last minute; missing telemetry is not zero usage.

[Open live agents](http://127.0.0.1:8800/#overview-agents-title) · [Open agent explorer](http://127.0.0.1:8800/agents) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=overview)

## Inspect Pi health

Inspect temperature, throttling and undervoltage flags, SD/NVMe disk, memory, swap, CPU and busy processes.

1. Open Pi health. The tiles at the top show the latest temperature, throttling, undervoltage, CPU, memory, swap and disk readings.
2. Throttling and Undervoltage read the Pi firmware flags. Active means the condition is happening now; Since boot means it happened earlier. Repeated undervoltage usually points to a weak power supply or cable.
3. Choose a chart time window to compare trends, and check sample freshness before drawing conclusions.
4. Scroll to Top processes for process CPU and resident memory; Tailscale peers and pending updates are below.

Disk used is used bytes divided by total bytes on the data volume (SD card or NVMe); df Use% is calculated differently. Process memory and system memory are different measurements.

[Open Pi health](http://127.0.0.1:8800/pi#pi-title) · [Open Top processes](http://127.0.0.1:8800/pi#apps-title) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=hardware)

## Investigate a service problem

The service table shows background jobs, their schedules, exits and crash-loop flags.

1. Open Services. The most severe jobs appear first.
2. Compare State, PID, Last exit and Runs in 24 h with the allowed launches for that schedule.
3. Use Pi health or the agent explorer to investigate related resource/activity changes. This page observes services; stopping or restarting a job is an operator action outside this table.

[Open service health](http://127.0.0.1:8800/services#services-title) · [Open alert history](http://127.0.0.1:8800/#alerts-title) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=services)

## Review Pi updates and Tailscale peers

Check updates and peer connectivity without changing the machine.

1. Open Pending updates on the Pi health page and review the available items and restart requirements.
2. Install updates with apt in a terminal on the Pi; RCD lists them read-only.
3. Open Tailscale peers to inspect reachability. Existing Serve proxies are not changed by viewing this page.

[Open available updates](http://127.0.0.1:8800/pi#upd-title) · [Open Tailscale peers](http://127.0.0.1:8800/pi#ts-title) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=updates)

## Check, install or roll back a dashboard update

Look for a newer release on GitHub, read what changed, then update or roll back with operator sign-in.

1. Sign in as the operator. Only the operator can see or change dashboard updates; other sessions get a sign-in message.
2. Open Updates in Settings and press Check for updates. This reads the public GitHub release list and nothing else: it downloads nothing and changes nothing. The release notes appear as plain text.
3. Press Update to the new version and confirm once. With signature trust set up, or on a source checkout, that one button does the rest. Otherwise paste the manifest SHA-256 from the release page: the package is downloaded, verified against that digest and staged, and you confirm the install after reading what changed.
4. The helper stops the service, saves a data snapshot, switches versions and runs a health check; a failed check rolls the version back by itself. Progress is shown step by step until the update finishes or the page reconnects.
5. An installed package can be rolled back to the previous version from the same panel. It returns the code only; data written meanwhile stays.

Every step stays disabled while an update is in progress or a blocker is listed. If managed updates are not set up, the panel shows the manual steps instead.

[Open dashboard updates](http://127.0.0.1:8800/profile#updates) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=app-updates)

## Create and run an agent task

Start with a Backlog draft, give it a clear outcome, then review and run it.

1. Choose New task, select an agent, and enter a title, description and definition of done.
2. Choose an allowed working directory, Read or Edit mode, model, timeout, budget and tags. Save the draft, then add dependencies in its task details if needed.
3. Open the task and select Run. Unfinished dependencies block dispatch; work needing approval waits in Needs approval until you approve it.

The working directory must be within the allowed workspace roots. Read/Edit enforcement differs by agent; OpenClaw and Hermes treat it as advisory. Cost limits depend on usage the agent reports.

[Open New task](http://127.0.0.1:8800/tasks?action=new) · [Open task board](http://127.0.0.1:8800/tasks) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=agent-tasks)

## Track your own work and definition of done

Human tasks track decisions, approvals and actions that only you can complete.

1. Choose New task and select You as assignee. Lane quick-add also creates a human task.
2. Write a definition of done that makes completion verifiable, such as “Google login succeeds on a second device.” Add due date, tags and dependencies if useful.
3. Open the task and use Move to… as your work progresses. Mark it Done only after its definition of done is satisfied. Human tasks never dispatch an agent.

[Open New task](http://127.0.0.1:8800/tasks?action=new) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=human-tasks)

## Link tasks with dependencies

A task waits for its prerequisites to reach Done before an agent can run it.

1. Open a task and find Dependencies.
2. Choose the prerequisite task and add it. The board shows its task number and whether it still blocks work.
3. Open the prerequisite by selecting its link. Once every prerequisite is Done, queued work can dispatch. Remove a link only when it is no longer a real prerequisite.

A task cannot depend on itself, and circular dependencies are refused. Hermes draft access can change dependencies only on its own Backlog drafts.

[Open tasks to link](http://127.0.0.1:8800/tasks) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=dependencies)

## Filter tasks and hide lanes

Keep the vertical task board readable with search, tags, filters and lane controls.

1. Search by title, tags or #ID. Open Filters for agent, assignee, priority and tag choices.
2. Use Lanes to hide statuses you do not need, or collapse a lane with its header.
3. If a task seems missing, clear filters and choose Show all lanes. Your board preferences are saved in this browser.

[Open board controls](http://127.0.0.1:8800/tasks#board-controls) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=task-filters)

## Review and approve work

Inspect the requested action and approval reasons before allowing sensitive work.

1. Tasks shows ready approvals in Needs approval, including project operator decisions whose prerequisites are finished. Open the task to inspect the description, definition of done, result and artifacts first.
2. Use the blue Approve run button for a task awaiting execution permission. Approval reasons appear beside it. Editing approved task details clears that approval.
3. For an unfinished read-only project plan, choose Approve & continue directly on its task row. This resumes the same scoped story; RCD saves one private Markdown document and the agent remains read-only.
4. For a successful project story, choose Approve handoff directly on its task row or details. This accepts the latest displayed result and current Markdown hash and releases ready dependents. Workspace changes still require explicit file review in Projects; RCD never automatically snapshots them.
5. Choose Record decision for a ready human project story. Write the required choices or sign-off, then Approve decision. RCD does not invent decisions or approve blocked or failed work. MCP changes retain their separate review on the MCP page.

[Open task reviews](http://127.0.0.1:8800/tasks) · [Open project story reviews](http://127.0.0.1:8800/projects?view=work) · [Open MCP change reviews](http://127.0.0.1:8800/mcp#changes-title) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=approvals)

## Read run output and handle a failure

Task details show run history, output, exit status and captured usage.

1. Open the task, then inspect the last run and its output/history.
2. Read Stage and Error before Exit code. OpenClaw can exit with code 0 while its agent result reports a provider timeout. Timed out means the agent did not finish; it does not authorize a model switch.
3. Review partial output and changed files against the task’s definition of done. Correct the task or timeout setting when necessary, then use Rerun task or an approved alternative on the failed task screen. After a subscription limit, Go Free! lets you select a configured OpenClaw target and OpenRouter :free model for that story only; it excludes paid-model and Google BYOK fallback. Cancel run is available for an active run. Failed, timed-out or interrupted runs can generate alerts; cancellation does not.

[Open task run history](http://127.0.0.1:8800/tasks) · [Open alert history](http://127.0.0.1:8800/#alerts-title) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=runs)

## Drill into agents, sub-agents and models

Use an agent and sub-agent/session selector to inspect activity and captured usage.

1. Select an agent in the fleet row or Agent dropdown.
2. Choose a named Sub-agent / session. Review its configuration, observed processes and captured activity.
3. Choose This month, Last 7 days or Last 24 hours. Inspect Model usage and source coverage; use Show all to leave a selected session.

Some sources expose lifetime session snapshots rather than period-level records. Those are labeled and excluded from period totals when attribution is unavailable. Unpriced records make cost partial.

[Open agent explorer](http://127.0.0.1:8800/agents#agents-title) · [Open OpenClaw sub-agents](http://127.0.0.1:8800/agents?agent=openclaw#explorer-target) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=agent-explorer)

## Chat with a named OpenClaw agent

Select a configured OpenClaw agent by name instead of typing its ID.

1. Open New chat and choose OpenClaw.
2. Choose the named OpenClaw agent in its dropdown, plus the title, model and working directory you need.
3. Start chat, then send your prompt. Each turn runs through the gateway; replies stay in this dashboard and are not delivered to a messaging channel.

Read/Edit is advisory for OpenClaw. The configured agent’s own tool policy still applies.

[Open New chat](http://127.0.0.1:8800/chat?action=new) · [Inspect OpenClaw configuration](http://127.0.0.1:8800/agents?agent=openclaw#explorer-target) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=openclaw-chat)

## Start or resume an agent chat

Talk to Claude Code, Codex, Hermes or OpenClaw and retain the conversation.

1. Choose New chat, select the agent, and set a title, working directory, model and Read/Edit mode.
2. Select Start chat. Type a prompt and send it; an agent turn can consume usage.
3. Open an existing thread in the thread list to continue it. The selected thread has a shareable local ?thread= link; an approval-required turn waits for your review.

Read/Edit restrictions depend on the agent. Check the explanatory note in New chat; Hermes and OpenClaw use their own tool policies. Today, ask Hermes in Chat for setup advice or a setup brief, or use an installed and configured Claude Code or Codex CLI on the host. The planned Hermes bootstrap will detect ready installed platforms and create a project brief whose tasks use the standard RCD review, approval and execution flow, with Hermes as the sole bootstrap agent. Until that capability is implemented, Hermes can explain or draft setup briefs but cannot run the bootstrap workflow. You still review proposed changes and verify native settings and credentials.

[Open New chat](http://127.0.0.1:8800/chat?action=new) · [Open existing conversations](http://127.0.0.1:8800/chat) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=agent-chat)

## Configure subscriptions and compare savings

Compare captured API-equivalent usage against each agent’s full monthly subscription.

1. RCD is free-only by default. If this installation deliberately provides a native Claude Code or Codex subscription route, open Agents → Billing & rates and explicitly save that account as Subscription.
2. Select This month in Agents and read the agent’s subscription and savings summary.
3. Savings compare captured API-equivalent usage for this calendar month against the full monthly subscription, counted once across that agent’s sub-agents.

These are captured-usage estimates, not provider invoices. Partial coverage or missing prices limits the comparison; a negative result means captured API-equivalent usage is below the subscription fee.

[Open Billing & rates](http://127.0.0.1:8800/agents?agent=codex&action=billing) · [Open cost summary](http://127.0.0.1:8800/agents?agent=codex#usage-summary) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=subscriptions)

## A task fails with PRICE_UNKNOWN

Dispatch refuses any route that has no reviewed pricing class. The run fails in under a second and never starts an agent.

1. Claude Code or Codex: the effective Billing & rates configuration is authoritative. Standard membership defaults are Subscription; save only if you intentionally changed a mode or amount.
2. OpenClaw: an approved project story automatically reviews its exact pinned :free model and target. Go Free records its exact route separately. Standalone tasks need an exact free entry in MAC_CONTROL_DISPATCH_ROUTE_CLASSES (for example openclaw|mm-developer|<exact model id>). Restart RCD after changing a host setting.
3. Hermes: project coordination pins the configured native free model. Other Hermes tasks need an explicit configured free route.
4. Rerun the task. Each rerun takes a fresh claim, so a fix applies to new runs only; failed runs keep the class they froze.

This is the pre-dispatch spending guard, not a fault. A :free model name, a billing estimate or a past successful run does not classify a route. Paid OpenClaw and Hermes routes are always refused.

[Open Billing & rates](http://127.0.0.1:8800/agents?action=billing) · [Open Tasks](http://127.0.0.1:8800/tasks) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=price-unknown)

## Use Grok Build as an agent

Grok Build is xAI’s terminal coding agent. RCD can run it on a SuperGrok subscription, next to or instead of any other agent.

1. Install the CLI on the Pi and sign in with grok login (or grok login --device-code on a machine without a browser). RCD never sees the sign-in.
2. Open Agents, then Billing & rates, set Grok Build to Subscription and save. Until you do, RCD refuses to start it, because the CLI has no dollar cap and an API-billed route cannot be bounded.
3. Create a task or choose Grok Build as a project story agent or fallback. Pick a model such as grok-4.6, grok-4.5 or grok-build-0.1, or leave it blank for the CLI default.
4. Read the data notice first: Grok sends the task and the files it reads to xAI. RCD runs it with telemetry and trace upload off, inside a filesystem sandbox (read-only for a read task, the working directory for an edit task), with git push and merge blocked.

RCD works with any mix of agents installed, including only Grok Build. Usage for Grok comes from the runs RCD dispatches; it does not read the CLI’s own session history. Grok is not used as a project planner, and subscription limit notices cover Claude Code and Codex only.

[Open Billing & rates](http://127.0.0.1:8800/agents?action=billing) · [Open Agents](http://127.0.0.1:8800/agents) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=grok-build)

## A Claude or Codex limit was reached

RCD notes when a subscription limit lifts, moves stories to an approved alternate on its own, and lets you send the rest across in one click.

1. When a run stops on a limit, a notice appears at the top of every page with the time it lifts in your time zone. It appears once per limit; use the × to hide it.
2. Each story that meets the limit already moves to its approved alternate route by itself. The notice counts these rather than announcing every one.
3. To avoid wasted attempts, select Send the waiting stories to the other subscription. Stories that have not started then go to the approved alternate of the same grade (Haiku to Luna, Sonnet to Terra, Opus to Sol) until the limit lifts, and return to their own route afterwards. Turn it off in the same notice.
4. If the other subscription is limited too, or a story has no approved alternate, it waits. You can also ask Hermes in Discord for the status; changing the routing from Discord needs Allow my Discord requests to change how work is routed in your profile.

Only routes the approved plan already lists are ever used, and nothing is approved, dispatched or spent beyond that. A limit with no reported lift time expires after a few hours or at the first later success.

[Open Projects](http://127.0.0.1:8800/projects) · [Open your profile](http://127.0.0.1:8800/profile) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=subscription-limits)

## Price an unrecognized model

Add explicit token rates when a model’s usage is captured but its API equivalent is unpriced.

1. Open Billing & rates and expand Model rates · USD per million tokens.
2. Choose or enter the exact model ID, enable Save custom rates for this model, and fill all five non-negative input/output/cache rates.
3. Save and review usage again. Source-reported cost takes precedence; custom rates apply uniformly up to their input limit.

Use rates from the model provider. Models ending in :free cost 0. Other missing rates remain unpriced; tools, taxes and other surcharges are outside token estimates.

[Open model rate settings](http://127.0.0.1:8800/agents?action=billing) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=model-rates)

## Track actual OpenRouter spending

Read the provider’s current-key totals separately from estimated API-equivalent usage.

1. Open OpenRouter actual spending on Overview or the agent explorer.
2. Compare Today, This week, This month and Key lifetime. These use provider UTC calendar windows and refresh every minute.
3. Read OpenRouter credits and external BYOK usage separately. If Hermes and OpenClaw share a key, the meter shows one shared total.

Key-wide spending includes every app using that key. A shared-key total cannot be split by agent, model or sub-agent. BYOK usage is separate from OpenRouter credits and provider invoices; secrets are never shown.

[Open actual spending](http://127.0.0.1:8800/#openrouter-spending) · [Open Hermes usage](http://127.0.0.1:8800/agents?agent=hermes#usage-summary) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=openrouter)

## Add or remove an MCP server

MCP changes are prepared as requests and applied only when you approve them.

1. Choose Request a server. Select the agent, server name and stdio command/arguments or HTTP URL.
2. Name required environment variables without entering secret values in the request. Supply their values privately in the Pi’s RCD configuration.
3. Inspect the request under Changes, then Approve or Reject it. Refresh the server list and verify the result. A failed change is not a connected server.

Account-managed Claude connectors are managed in claude.ai. Granting RCD task access is a separate action from registering the RCD MCP server.

[Open MCP servers](http://127.0.0.1:8800/mcp) · [Open change reviews](http://127.0.0.1:8800/mcp#changes-title) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=mcp)

## Manage Hermes planning access

Give Hermes expiring access to read tasks or manage its own Backlog drafts.

1. Open MCP → Agent access and choose Review Hermes access.
2. Select Read only or Read + planning drafts, and an expiry of 1, 7 or 30 days. Read the limits, then approve. A new grant replaces the previous grant.
3. Register the RCD server through its separate MCP change. Start a new Hermes session to load it. Use Revoke access here to block the grant immediately.

Draft access cannot queue/start runs, approve/complete/delete tasks, change integrations, or read chats/logs/billing/credentials. An expired grant must be reviewed by you; never give Hermes a browser session or recovery token.

[Open Agent access](http://127.0.0.1:8800/mcp#agent-access-title) · [Open Hermes MCP server](http://127.0.0.1:8800/mcp#mcp-hermes) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=hermes-access)

## Browse GitHub projects, PRs and issues

Inspect accessible repositories and their current open work using the existing GitHub login.

1. GitHub is optional. If it is not set up, open Settings > GitHub (optional), choose the account already signed in with gh, list the repositories to show, and save. Your profile’s public contribution graph is a separate GitHub setting: Profile > Contribution settings > Private contributions.
2. Open GitHub and search the repository list.
3. Select a repository to load its open pull requests and issues. Select an item’s link to open it on GitHub.
4. Use Refresh to check again. Notice partial, stale or capped results; this panel does not merge PRs, edit issues or broaden your token’s scopes.

[Open GitHub projects](http://127.0.0.1:8800/github#github-title) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=github)

## Read Hermes operational reports

Read actual Markdown/text reports with their source and timestamp.

1. Open Ops reports. The newest modified report is selected first; choose another from the list.
2. Check the source, timestamp and historical warning before interpreting its findings.
3. Use Refresh to rescan. Hermes cron archives show the actual Response, omitting archived Prompt instructions. Viewing does not generate a new report or enable a schedule.
4. For collector reports, a warning or critical finding can become one Backlog task from the report. The task keeps a link back to the report; choosing the same finding again opens the existing task.

The catalog is capped at 200 files. Oversized/binary files are not previewed. An empty source is different from an unavailable source; old reports do not describe current fleet health.

[Open operational reports](http://127.0.0.1:8800/reports#reports-title) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=reports)

## Check Discord alert delivery

Overview shows failed-run and crash-loop alert delivery and recent outcomes.

1. Open Alerts on Overview and expand Recent alerts.
2. Read the outcome and any delivery acknowledgement. Failed/timed-out/interrupted runs and new crash-loop incidents can alert; successful and cancelled runs do not.
3. For uncertain delivery, inspect the Discord channel before taking further action. Mark reviewed records your inspection without resending.

Rules are configured in the Pi’s private alerts.toml. RCD does not automatically retry uncertain sends, restart services or send task prompts/logs. It uses the channel authorized by the operator.

[Open alert history](http://127.0.0.1:8800/#alerts-title) · [Inspect service health](http://127.0.0.1:8800/services) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=alerts)

## Refine a project with the consultant

Talk your idea through, say when it is enough, then send the plan to the coordinator.

1. Open Projects and choose Refine with project consultant below Create project brief.
2. Choose an allowed workspace, enter a project name and goal, and choose a project type (the closest fit, or Other if nothing fits exactly). The type is required here so it is always part of the plan. The consultant is told the type’s planning guidance and says if your goal does not fit it.
3. New AI conversations use Hermes with openrouter/free unless you changed Profile → AI defaults. Install and configure the selected native agent first.
4. The consultant answers, then asks what it needs to know. Keep talking until you are satisfied; you never have to read its instructions.
5. Choose That’s enough, write up the plan. The brief opens for you to edit. Confirm the working directory and approve coordination; Hermes coordinates the selected planner and returns the project map and stories.
6. Review the returned project map before separately approving story execution.

Free routes can throttle or fail. Profile → AI defaults also supplies new chat, task and planning forms; existing work keeps its routes. Native membership accounts and API billing are separate. The built-in help chat uses local guides and makes no model calls.

[Configure AI defaults](http://127.0.0.1:8800/profile#ai-settings) · [Open Projects](http://127.0.0.1:8800/projects) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=project-consultant)

## Pick a project type so the plan follows a template

A type tells the planner how this kind of project is planned and where it has failed before, then checks the plan.

1. Open Projects, choose New project and pick a type: Web app, Packaged app, Website property, or Other when nothing fits exactly (the plan then says which type it resembles and which gates it keeps). When your brief clearly fits one, MCD suggests it and you can accept or ignore the suggestion. A project with no type is planned as before.
2. The type adds planner text and known failure points to the plan prompt, hands its guides to the planner and agents (for a website: the design guide and the spacing and timing guide), and lists the keys it usually needs.
3. After a plan is proposed, read Plan checks for this project type. They only warn: for example no README story or no story that makes the Playwright screenshots (a person or the pipeline runs that script; agents cannot run a browser), no delivery story (the project must end in the remote repository, public for an MIT-licensed package others install and private for proprietary work, with the branch pushed, a pull request open and the pipeline result read), no file verification story, a preview that does not follow verification, a container story an agent cannot do, generated media planned for an agent, or no responsive review. Fix the plan or ignore a warning on purpose.
4. Look for the human sign-offs the type expects, such as making the media in MCD, approving the look from a live preview and the final local verification. Agents cannot render pages, so you check rendering in the preview.
5. To change a type, copy packs/project-types/<id>.json into the project-types folder of your data directory and edit it; your copy replaces the shipped one. When a project fails for a reason that could have been planned around, add it to the type’s failure points.

Types guide planning. They never block a plan and never run model output. A Website property also starts its background clips on the cheapest video tier in the media panel.

[Start a project](http://127.0.0.1:8800/projects?action=new) · [Open Projects](http://127.0.0.1:8800/projects) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=project-types)

## Make site art and video for a project (fal)

Open the Media studio from the project (or from a human media story), see what it will cost, generate stills and clips, review them and publish the ones you choose.

1. Save a fal key first in Profile, Private credentials. The guide Create or replace the fal key lists the models it needs.
2. Open the project’s Media studio tab (a project whose folder has media/slots.json gets one). A human story about media, and a banner while slots are unresolved, link straight to it and say what is left to spend. The studio opens with three numbers: spent so far, left to make at the chosen tiers, and waiting for your review. Tick the spending acknowledgement under them; pressing Generate without it tells you what is missing and takes you to the box.
3. Each slot starts on a tier from its project type: a website’s clips start on the cheapest video tier (MiniMax H3 Max Turbo) and images on standard. Standard clips use MiniMax H3 Max and premium uses Veo 3.1. Change the tier or how many, read the estimate, press Generate and confirm.
4. Everything already published appears as a gallery at the bottom, with its size. The Storage line shows what the media and the unused takes take up; Clear unused takes… deletes the generated takes of slots you have decided (never published files, never takes waiting for review) after you confirm.
5. Watch progress under that slot’s button: a spinner, waiting or generating text, then finished or the failure. The button reads Generating… until it ends.
6. Review each candidate as a thumbnail or video. Accept and publish the one you want (RCD converts and records it), choose None of these to make another, or Skip to keep the site’s drawn fallback.
7. To keep the bill small, give each slot in media/slots.json only the resolution it needs: "resolution": "1K" for a picture shown small, "480P" for a retro or VHS-look clip (it costs 0.625 of 768p). The estimate on the slot follows it.
8. A slot with generations still waiting for review is not generated again unless you choose Another take, so a double click never pays twice. A published slot is only regenerated when you choose Regenerate.

A clip starts from a published, approved still. A draft still is too small to publish; make stills at standard or premium. Agents never receive the fal key and cannot generate media.

[Open Projects](http://127.0.0.1:8800/projects) · [Media prices (what it costs)](http://127.0.0.1:8800/agents?action=billing) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=project-media)

## Check media spend and avoid paying twice

Estimates are an upper bound; fal’s usage page is the truth. Repeats and unpriced runs are shown, not hidden.

1. Every estimate comes from list prices checked against fal’s own usage table: Veo 3.1 Fast $0.15 a second, Veo 3.1 $0.40 a second, MiniMax H3 Max $0.08 and Turbo $0.04 a second at 768p, and a 2K Nano Banana picture is 1.5 image units of $0.08. fal’s usage page is the truth.
2. Under the Media panel the spend line shows runs finished, the estimated total, how many runs repeated a slot already generated, and any runs with no price. An unpriced run is named, never counted as zero.
3. To keep cost down: leave website clips on the cheapest tier, generate one take at a time, review before asking for another, and set a credit limit at fal. MiniMax’s launch discount ends on 31 October 2026, so estimates use the higher price.
4. If fal’s usage is far above MCD’s total, check for runs with no price and for repeats. Every run, with its fal request id, is in media/ledger.jsonl in MCD’s data folder.
5. MCD does not cap spending. The limits are the confirmation, the repeat guard and the credit limit you set at fal.

In the first real website run fal billed $16.88 while MCD showed about $2, because Veo clips had no price and repeat generations were not flagged. Both are fixed.

[Media models and prices](http://127.0.0.1:8800/agents?action=billing) · [Open Projects](http://127.0.0.1:8800/projects) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=media-spend)

## Create or replace the fal key

fal fixes a key’s allowed models when the key is created, so a model added later needs a new key.

1. At fal.ai/dashboard/keys create a key with the API preset, add its allowed models, and set a credit limit. fal cannot change a key’s model list afterwards.
2. Add these patterns: minimax/h3-max* (the default video models), fal-ai/nano-banana-2* and fal-ai/nano-banana-pro* (images), and fal-ai/veo3.1* only if you want the premium Veo tier. If a wildcard is refused, add the exact endpoint ids listed in Agents, Billing & rates, Media models.
3. Copy the secret once and paste it into Profile, Private credentials, fal.ai key. It is encrypted, write-only and never shown again, and agents never receive it.
4. Run one cheap generation to confirm. If a model is refused, the key’s list does not include it: make a new key, replace the saved one and delete the old key at fal.

The edit screen for an existing fal key shows the model list read-only; that is why adding a model there does nothing.

[Save the key](http://127.0.0.1:8800/profile#credentials-profile) · [Media models and prices](http://127.0.0.1:8800/agents?action=billing) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=fal-key)

## Accept a story whose agent reported unfinished work

Accept anyway records the agent’s report and your reason, keeps the run failed in history and releases what waits on it.

1. When an agent finishes but its report says work is unfinished or a check could not run, the story fails and blocks what depends on it. Read its report first.
2. If you are content with the result (for example the missing items are made by a later human step, or a check needs a browser the agent does not have), choose Accept anyway… on the story, in Projects under Stories & runs or in the board’s task panel beside Rerun.
3. Type a reason of at least ten characters. RCD records the agent’s own report and your reason as the handoff, keeps the run as failed in the history and releases the stories that depend on it.
4. A crash or timeout leaves no report to accept: use Retry same story instead. A human story is decided, not accepted this way.

Nobody should later read an accepted story as a clean pass: the handoff begins with the operator’s acceptance and keeps the agent’s list of gaps.

[Open Projects](http://127.0.0.1:8800/projects) · [Open the task board](http://127.0.0.1:8800/tasks) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=accept-anyway)

## Read jobs and telemetry

See how work is going across approved plans and stories: who it is assigned to, which agent and model ran it, how long it took and what it cost.

1. Open Jobs & telemetry. Pick a period and, if you like, filter by job, kind, risk, size, tier, assignee, agent or model.
2. The tiles count unassigned work, work in progress, work waiting for you, what finished in the period, work missing an estimate and failures.
3. The charts break work down by status, route, property, assignee, job, model and kind, with completed work per week and median time per kind.
4. Cost shows what was reported and the API-equivalent estimate. Runs that could not be priced are counted, not guessed.
5. Open Jobs: the numbers for the table behind the charts. A job is one approved plan revision.

Telemetry only reads what the dashboard already recorded. It changes nothing.

[Open Jobs & telemetry](http://127.0.0.1:8800/telemetry) · [Price an unrecognised model](http://127.0.0.1:8800/help?topic=model-rates) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=jobs-telemetry)

## Keep the dashboard tidy: housekeeping, bug reports, roles and GitHub

Settings, Maintenance & access holds the cleanup scan, bug-report intake, agent roles, report folders and the GitHub settings and actions.

1. Housekeeping scans for leftovers by fixed rules, with no model involved. Press Scan now, read the findings and approve only what you want removed. Hermes may propose a cleanup but can never change anything itself. After hours cleanup is off unless the host enables it (the Notes line says how).
2. Bug reports shows whether intake is on and when GitHub was last checked. A maintainer labels an issue bug-report and accepted to make it a Backlog task. Press Check GitHub now to look immediately.
3. Hermes is the fixed project Coordinator. Agent roles lets you label other agents as Workers, Reviewers or Security; Coordinator and Delegator are not selectable there. Preview role changes shows exactly what will be written before anything is.
4. Report storage sets the folders the Ops reports page reads. Reports are read-only.
5. GitHub settings turns on repository, pull request and issue views for the repositories you choose, using the account already signed in with gh. GitHub actions waiting for you lists anything drafted that would write to GitHub: read the exact request, confirm, and it runs once.

Nothing here changes anything until you approve it. Agents can draft, never approve.

[Open Maintenance & access](http://127.0.0.1:8800/profile#housekeeping) · [Ops reports](http://127.0.0.1:8800/reports) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=maintenance)

## Install or upgrade the agent tools

Settings, Updates & installs: one card per agent CLI with its version, an Install or Upgrade button, a progress bar, the install log and a health check.

1. Open Settings, then Updates & installs. Each agent tool is a card showing the version installed and the version this release has verified.
2. Press Install or Upgrade. A confirmation lists the versions, downloads, commands and what stays unchanged. Tick it to run. Nothing needs sudo and nothing signs in.
3. Watch the progress bar and open the log if you want the detail. Only one install runs at a time.
4. When it finishes the health check runs by itself: it asks the tool for its version, checks that a new terminal reaches the managed copy, and lists next steps. Press Check health to run it again.
5. A tool you installed yourself (native, for example Hermes or gh from Homebrew) is offered a reviewed upgrade that installs a managed copy beside it; your own copy and account settings are kept. Put the tools folder first on your PATH if the health check says a different copy answers.
6. If the health check says the tool did not run, press Repair when the card offers it: it rewrites the command wrapper without downloading anything. Then press Check health again.
7. Sign in yourself with the command on the card. API keys go in Private credentials, never on this page.

Roll back switches to the version kept on this host. Remove deletes the program but keeps your tool data, for example ~/.hermes.

[Open Updates & installs](http://127.0.0.1:8800/profile#agent-tools) · [Check the machine in the setup wizard](http://127.0.0.1:8800/setup) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=agent-tools)

## Install or upgrade the optional system tools

Install (All) and Upgrade (All) for Docker, ffmpeg, Python and gh, with a log and a health check. Homebrew on a Mac; a command to copy on Linux.

1. Open Settings, then Updates & installs, then Optional system tools. Each tool shows its installed version; Check for updates asks Homebrew which are outdated and shows the newer version beside those. Managed Agent tools use their verified catalog version.
2. On a Mac, Homebrew comes first. If it is missing the card shows the one command to run yourself in Terminal (it asks for your password; the dashboard never runs it). Press Check again afterwards.
3. Install (All) runs one brew install for everything missing. Upgrade (All) runs brew update and then upgrades only these tools. The log shows every command.
4. Docker needs its engine: Colima provides it on a Mac. If the health check says the engine is stopped, press Start Colima.
5. On Linux installing packages needs administrator rights, so the card shows one apt command to copy and run in a terminal. gh and Node install from Agent tools.
6. When a job finishes, the health check runs by itself and lists next steps for anything that did not answer.

Only the named tools are installed or upgraded. Nothing else on the machine is touched, and each job runs with a clean environment: no keys or tokens.

[Open optional system tools](http://127.0.0.1:8800/profile#system-tools) · [Setup wizard checklist](http://127.0.0.1:8800/setup) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=system-tools)

## Check that this machine is ready to build projects

A checklist with one-click fixes for the workspace folder, git identity and GitHub access, and a look at which agents can write code.

1. Open Setup wizard, step 1. The panel Is this machine ready to build? lists each check: the workspace folder, git, the git identity, GitHub access, agents that can write code, optional tools and free disk space. Checking changes nothing.
2. Create the workspace folder if it is missing. Projects that must end in a GitHub repository should work in a clone of that repository inside this folder, never in a scratch folder (a scratch folder has no remote).
3. Set the git identity (a name and an email) so commits are attributed. It is saved as the global git identity for this host user.
4. Make a GitHub SSH key. The private half stays on this host; copy the public key shown, add it to your GitHub account (or to one repository’s Deploy keys with write access), then press Test GitHub access.
5. If you installed Codex or OpenClaw from Agent tools and your shell says command not found, press Put installed tools on my PATH (or copy the sign-in command shown on the tool, which starts with its full path), then open a new terminal.
6. Read Agents that build: Claude Code, Codex, OpenClaw and Grok can write code; Hermes plans and coordinates but does not. Install and sign in to a builder from Agent tools if none is listed. Sign-in is not verified here.
7. Optional tools are only needed by some stories: Docker for container images, Node for JavaScript tests and the Playwright screenshot script, ffmpeg for media, gh for pull requests. Each missing tool says how to get it: gh and Node install from Agent tools; on a Mac with Homebrew the wizard installs ffmpeg, python and Docker (through Colima) for you, starts Colima, and Update tools with Homebrew keeps them current; on Linux it shows the command for an administrator to run. Use Recheck with network test to confirm GitHub and your model provider are reachable.

Fixes do one named thing each: create the folder, set the git identity, make or test the GitHub key. Nothing installs software, stores a token or runs project code, and the private key is never shown.

[Open the setup wizard](http://127.0.0.1:8800/setup) · [Open Agent tools](http://127.0.0.1:8800/profile#agent-tools) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=host-readiness)

## Sign in and resolve a login problem

Use an allowed Google account; RCD requests identity access only.

1. Open RCD and select Sign in with Google, then choose an allowed account.
2. If a Gmail test account sees org_internal, the OAuth app audience must allow External users and list that account as a test user during testing.
3. For redirect mismatch, check the exact origin and /auth/callback in Google’s OAuth client. Local and tailnet HTTPS origins use separate callbacks; use Sign out when finished.

Google sign-in does not grant Gmail or Drive access. Local recovery is for the operator on this Pi only; do not paste credentials into help chat.

[Open Overview](http://127.0.0.1:8800/) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=sign-in)

## Open RCD from another Tailscale device

Use RCD’s own HTTPS Serve port on a device signed into your tailnet.

1. On another Tailscale-connected device, open your configured HTTPS dashboard address/.
2. Sign in with an allowed Google account on that device. Verify Overview and an agent drill-down load.
3. Keep the :9443 port in RCD links and its OAuth callback. Port 443 serves OpenClaw; other existing proxies remain separate.

This is tailnet access, not public hosting. A successful local login does not verify login from a separate device.

[Open Tailscale peers](http://127.0.0.1:8800/pi#ts-title) · [Bookmark this how-to](http://127.0.0.1:8800/help?topic=remote)
