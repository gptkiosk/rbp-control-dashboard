export interface HelpGuide {
  id: string
  title: string
  area: string
  summary: string
  keywords: string[]
  steps: string[]
  links: { label: string; to: string }[]
  note?: string
}

/** Reviewed product instructions. Help never sends questions or dashboard data to a model. */
export const helpGuides: HelpGuide[] = [
  {
    id: 'setup', title: 'Set up RCD on your Raspberry Pi', area: 'Start here',
    summary: 'A six-step wizard for local installation, Google access, agents, provider keys, subscriptions and navigation.',
    keywords: ['setup', 'wizard', 'onboarding', 'install', 'prerequisites', 'openrouter', 'google', 'claude', 'codex', 'subscription'],
    steps: ['Open Setup wizard from the header account icon, Settings or this guide. New profiles also see Start setup wizard above their dashboard. Later hides the welcome prompt; the wizard remains available.', 'Review the Pi prerequisites (Raspberry Pi OS on a Pi 4 or newer) and save an allowed default working directory. Agent binaries run on the Pi even when you browse from a phone.', 'Configure Google OAuth privately on the host and sign in with an allowed account. The wizard explains callbacks, test users and the local importer; it does not collect OAuth client secrets.', 'Install Hermes and OpenClaw using their official guides. Check executable detection and independently confirm native provider/model routing and fallback spending caps. The wizard does not launch agents or grant permissions.', 'Save your OpenRouter key in encrypted, write-only profile storage. Check key with OpenRouter reads actual key spending; inference credentials still need native agent configuration.', 'Install and sign into Codex and Claude Code using eligible subscriptions on the Pi, For included membership usage, use native subscription sign-in; API/OpenRouter billing is separate. Desktop app login alone does not establish CLI readiness. Confirm the host sign-in yourself; RCD does not collect tokens or verify entitlement.', 'Try header Help chat and browse the main menu. Finish walkthrough saves your reviewed progress; pending items stay listed. Reopen and refresh checks after changes.'],
    links: [{ label: 'Open setup wizard', to: '/setup' }, { label: 'Manage private credentials', to: '/profile#credentials-profile' }],
    note: 'Setup progress belongs to your profile. Finishing the walkthrough does not complete project tasks, install software, change model routes, authorize paid usage or enable remote access.',
  },
  {
    id: 'profile-discord', title: 'Connect your profile to Hermes on Discord', area: 'Profile',
    summary: 'Create, revise and receive project plans without opening RCD; keep settings and credentials private.',
    keywords: ['profile', 'discord', 'pair', 'pairing', 'credentials', 'keys', 'export', 'portable', 'diagram', 'image', 'notification'],
    steps: ['Open Profile. Save your default workspace and assignment preference. Balanced is centered at 50 and is the default for new profiles.', 'Enter the Discord channel where Hermes replies and choose your configured HTTPS dashboard address. Enable plan notifications. If you want to start planning from Discord, select Allow my Discord requests to start subscription planning with Hermes coordination; this covers its configured free-first / capped BYOK route, not paid API planners or execution.', 'Choose Get pairing code and send the displayed instruction to Hermes in that channel within 10 minutes. Choose Check pairing. Unlink Discord revokes remote project access.', 'Ask Hermes to plan a project. It asks for missing goal, name or workspace and creates a draft with your preference. Request planning when ready. In RCD, New project → Submit to Hermes starts planning after the coordination checkbox is reviewed; Save draft starts no models.', 'Projects shows actual planning stages and Discord delivery status. When the map is ready, edit its stories in Projects or tell Hermes your changes. Hermes asks whether a diagram is needed; request the image to review dependencies and assignments off-app. Execution still needs Review & submit in RCD.', 'Save provider credentials using the password fields. Values are encrypted and write-only. OpenRouter checks report actual key spending; saving a key does not change native agent routing or its cap. Export/import preferences copies settings only and excludes secrets and Discord identity; review installation-specific paths and re-pair on a new Mac.'],
    links: [{ label: 'Open your profile', to: '/profile' }, { label: 'Connect Discord', to: '/profile#discord-profile' }, { label: 'Create a project', to: '/projects?action=new' }],
    note: 'Keep the database and vault.key together in a private backup to recover encrypted credentials. Subscription logins, Google OAuth and gateway credentials remain private host setup. Uncertain Discord sends are not automatically retried.',
  },
  {
    id: 'projects', title: 'Plan a project with Hermes and a shared mind map', area: 'Projects',
    summary: 'Turn a brief into reviewed stories, model assignments and shared handoffs.',
    keywords: ['project', 'projects', 'mind map', 'planning', 'phase', 'slice', 'story', 'shared memory', 'parallel', 'handoff', 'slider', 'economy', 'capability', 'assignment preference', 'live map', 'project status'],
    steps: ['Choose New project. Write the brief and select an allowed working directory. Set Story assignment preference: Economy favors OpenClaw free-first tasks; Capability favors Claude/Codex subscriptions; Balanced splits routine and difficult work. Save changes before requesting a plan.', 'Plan with Hermes starts a reviewed coordinator → subscription planner → Hermes review workflow. The slider guides suggestions rather than guaranteeing cost or quality. Change it under Project brief & planner and save/replan to revise recommendations; existing assignments stay untouched until you replan or edit them. The returned map is a proposal: select nodes to edit instructions, scope, definition of done, agents, models and prerequisites. Drag nodes or use Arrange.', 'Choose sequential execution or parallel isolated Git stories. Parallel mode requires a clean repository root; RCD creates story worktrees and local branches from its reviewed commit.', 'Review & submit freezes the saved revision and its approved model routes. Hermes orders the stories; RCD creates them once. Pause dispatch stops new stories while running ones can finish.', 'In Stories & runs, verify artifacts and checks, then accept the handoff. Dependent stories wait for acceptance and receive approved context. Review tracked diffs and explicitly select changed files to create a local handoff snapshot (or commit them yourself); prerequisite conflicts stop for review. Source branches are never merged automatically.'],
    links: [{ label: 'Create a project brief', to: '/projects?action=new' }, { label: 'Open project library', to: '/projects' }],
    note: 'Shared memory is a project ledger injected into RCD project runs. Native private histories are not merged; Export context supports independent sessions. Up to 20 latest accepted handoffs/decisions/checkpoints fit within a bounded prompt; full records remain in Projects. Read/Edit is advisory for Hermes and OpenClaw.',
  },
  {
    id: 'project-approvals', title: 'Approve project handoffs and watch the live map', area: 'Projects',
    summary: 'Batch routine agent handoffs or enable automatic handoffs for one approved revision.',
    keywords: ['approve all', 'automatic handoffs', 'bulk approval', 'live project', 'project colors', 'unsaved edits', 'queue'],
    steps: ['Open the project library and select your running project. Live map is view-only and refreshes every three seconds; opening it does not save or replace the plan.', 'Read the story and phase colors: blue running, amber review or approval, teal queued, gray blocked, green done and red failed. The project bubble and completion counter summarize progress. Select a story and Open task for details.', 'Choose Approve all except human-required tasks. Review Included and Requires human input or approval. Keep the future-handoffs option selected to pass successful eligible results automatically, or clear it for a one-time batch.', 'Acknowledge the listed scope and submit. The same assignments, model routes and dependencies remain in force. Only a completed successful result with handoff text can pass; this does not independently verify artifacts.', 'Choose Require individual reviews to stop automatic handoffs. Pause dispatch also pauses automatic acceptance; running jobs may still finish into Review.'],
    links: [{ label: 'Open project library', to: '/projects' }],
    note: 'Tasks needing human interaction, decisions or required answers stay manual, including security/credential/license reviews, external actions and isolated Git snapshots. Failed runs and unfinished plans never pass as complete. Output continuation and paid-route changes retain their separate approvals. Approval applies to the exact submitted revision, not other projects.',
  },
  {
    id: 'project-models', title: 'Choose model routes and handle subscription limits', area: 'Projects',
    summary: 'Set the primary model per story and review an ordered list of alternate routes.',
    keywords: ['model switching', 'quota', 'token limits', 'free models', 'byok fallback', 'opus', 'sonnet', 'haiku', 'terra', 'sol'],
    steps: ['Select a story and choose its agent and model. Claude and Codex use their existing subscription logins. Suggestions are editable; availability depends on the installed CLI and account.', 'In Stories & runs, enable Model lock to stop failed tasks without automatic retries or equivalent-model switching. Default off retains approved alternatives; manual retry remains explicit.', 'Add Model route entries in the order you want. Alternate subscription models or reviewed free/API routes are tried once per story after an explicit reported quota or rate limit, using the same workspace and a checkpoint. Other errors require an explicit retry.', 'Use Review & submit to inspect every route. Hermes/OpenClaw API routes require a separate acknowledgment. Automatic alternate API routes are limited to Inkling free, Gemma free and Google Gemini 2.5 Flash.', 'Open Agents to inspect actual key-wide spending and the current monthly limit. The shared key has a $20 monthly cap including recorded BYOK usage. Google calls outside that key and differences in upstream invoicing are outside the cap.'],
    links: [{ label: 'Review project models', to: '/projects' }, { label: 'Inspect actual key spending', to: '/agents#openrouter-spending' }],
    note: 'Quota handoff is reactive; RCD cannot predict all subscription windows or guarantee free-model availability. A model switch within one subscription may share the same exhausted quota. No unapproved paid model is selected automatically.',
  },
  {
    id: 'getting-started', title: 'Get started with RCD', area: 'Start here',
    summary: 'Use Overview to check your Pi and agents, then open a feature for details.',
    keywords: ['getting started', 'tour', 'begin', 'features', 'dashboard', 'how to use', 'theme', 'light mode', 'dark mode', 'appearance'],
    steps: ['Sign in with an allowed Google account. Overview shows Pi health, agent activity and alert delivery.', 'Use the sun/moon button in the header to switch the whole app between light and dark mode. Your choice is saved in this browser; without a saved choice, RCD follows your device appearance.', 'Open Agents for sub-agents and costs, Tasks for work, or Chat for a direct agent conversation.', 'Open Help chat in the header from any page. Ask a question or choose a topic; Open links take you to the feature.'],
    links: [{ label: 'Open Overview', to: '/' }, { label: 'Open task board', to: '/tasks' }],
  },
  {
    id: 'overview', title: 'Check live fleet status', area: 'Overview',
    summary: 'Overview combines Pi health with top-level agent and sub-agent activity.',
    keywords: ['fleet', 'overview', 'live', 'realtime', 'real time', 'status', 'idle', 'running agents'],
    steps: ['Read the sample age above the Pi tiles to check freshness.', 'In Agents, compare current RCD turns, recent captured activity and observed processes.', 'Select an agent or named sub-agent to open its explorer. Activity updates every five seconds; usage every fifteen seconds.'],
    links: [{ label: 'Open live agents', to: '/#overview-agents-title' }, { label: 'Open agent explorer', to: '/agents' }],
    note: 'An observed process can be idle. “Recent activity” means a captured update within the last minute; missing telemetry is not zero usage.',
  },
  {
    id: 'hardware', title: 'Inspect Pi health', area: 'Pi',
    summary: 'Inspect temperature, throttling and undervoltage flags, SD/NVMe disk, memory, swap, CPU and busy processes.',
    keywords: ['hardware', 'pi', 'raspberry', 'cpu', 'memory', 'ram', 'swap', 'disk', 'sd card', 'nvme', 'temperature', 'throttling', 'undervoltage', 'under-voltage', 'power supply', 'network', 'resource', 'top processes', 'charts'],
    steps: ['Open Pi health. The tiles at the top show the latest temperature, throttling, undervoltage, CPU, memory, swap and disk readings.', 'Throttling and Undervoltage read the Pi firmware flags. Active means the condition is happening now; Since boot means it happened earlier. Repeated undervoltage usually points to a weak power supply or cable.', 'Choose a chart time window to compare trends, and check sample freshness before drawing conclusions.', 'Scroll to Top processes for process CPU and resident memory; Tailscale peers and pending updates are below.'],
    links: [{ label: 'Open Pi health', to: '/pi#pi-title' }, { label: 'Open Top processes', to: '/pi#apps-title' }],
    note: 'Disk used is used bytes divided by total bytes on the data volume (SD card or NVMe); df Use% is calculated differently. Process memory and system memory are different measurements.',
  },
  {
    id: 'services', title: 'Investigate a service problem', area: 'Services',
    summary: 'The service table shows background jobs, their schedules, exits and crash-loop flags.',
    keywords: ['services', 'service', 'systemd', 'daemon', 'crash loop', 'restart', 'stopped'],
    steps: ['Open Services. The most severe jobs appear first.', 'Compare State, PID, Last exit and Runs in 24 h with the allowed launches for that schedule.', 'Use Pi health or the agent explorer to investigate related resource/activity changes. This page observes services; stopping or restarting a job is an operator action outside this table.'],
    links: [{ label: 'Open service health', to: '/services#services-title' }, { label: 'Open alert history', to: '/#alerts-title' }],
  },
  {
    id: 'updates', title: 'Review Pi updates and Tailscale peers', area: 'Pi',
    summary: 'Check updates and peer connectivity without changing the machine.',
    keywords: ['updates', 'update', 'install', 'software', 'peers', 'tailscale peers', 'connectivity'],
    steps: ['Open Pending updates on the Pi health page and review the available items and restart requirements.', 'Install updates with apt in a terminal on the Pi; RCD lists them read-only.', 'Open Tailscale peers to inspect reachability. Existing Serve proxies are not changed by viewing this page.'],
    links: [{ label: 'Open available updates', to: '/pi#upd-title' }, { label: 'Open Tailscale peers', to: '/pi#ts-title' }],
  },
  {
    id: 'app-updates', title: 'Review and install a staged dashboard update', area: 'Settings',
    summary: 'Check staged releases of this dashboard and install or roll one back, with operator sign-in.',
    keywords: ['app update', 'dashboard update', 'rollback', 'roll back', 'staged release', 'version'],
    steps: ['Sign in as the operator. Only the operator can see or change dashboard updates; other sessions get a sign-in message.', 'Open Updates in Settings. The panel reads only this host: it makes no network or provider call and lists each staged version with its channel and authenticity status.', 'Only complete stable or prerelease packages get an install button. Development builds and partly staged packages say why they cannot be installed.', 'Confirm the version in the dialog. The helper stops the service, saves a data snapshot, switches versions and runs a health check; a failed check rolls the version back. Progress is shown until the update finishes or the page reconnects.'],
    links: [{ label: 'Open dashboard updates', to: '/profile#updates' }],
    note: 'Install and rollback stay disabled while an update is in progress or a blocker is listed. If managed updates are not set up, the panel shows the manual steps instead.',
  },
  {
    id: 'agent-tasks', title: 'Create and run an agent task', area: 'Tasks',
    summary: 'Start with a Backlog draft, give it a clear outcome, then review and run it.',
    keywords: ['new task', 'create task', 'add task', 'agent task', 'start task', 'run task', 'assign', 'working directory', 'timeout', 'budget'],
    steps: ['Choose New task, select an agent, and enter a title, description and definition of done.', 'Choose an allowed working directory, Read or Edit mode, model, timeout, budget and tags. Save the draft, then add dependencies in its task details if needed.', 'Open the task and select Run. Unfinished dependencies block dispatch; work needing approval waits in Needs approval until you approve it.'],
    links: [{ label: 'Open New task', to: '/tasks?action=new' }, { label: 'Open task board', to: '/tasks' }],
    note: 'The working directory must be within the allowed workspace roots. Read/Edit enforcement differs by agent; OpenClaw and Hermes treat it as advisory. Cost limits depend on usage the agent reports.',
  },
  {
    id: 'human-tasks', title: 'Track your own work and definition of done', area: 'Tasks',
    summary: 'Human tasks track decisions, approvals and actions that only you can complete.',
    keywords: ['human', 'you', 'my tasks', 'definition of done', 'acceptance', 'done', 'complete human', 'decision'],
    steps: ['Choose New task and select You as assignee. Lane quick-add also creates a human task.', 'Write a definition of done that makes completion verifiable, such as “Google login succeeds on a second device.” Add due date, tags and dependencies if useful.', 'Open the task and use Move to… as your work progresses. Mark it Done only after its definition of done is satisfied. Human tasks never dispatch an agent.'],
    links: [{ label: 'Open New task', to: '/tasks?action=new' }],
  },
  {
    id: 'dependencies', title: 'Link tasks with dependencies', area: 'Tasks',
    summary: 'A task waits for its prerequisites to reach Done before an agent can run it.',
    keywords: ['dependency', 'dependencies', 'depends', 'prerequisite', 'blocked', 'waiting', 'cycle'],
    steps: ['Open a task and find Dependencies.', 'Choose the prerequisite task and add it. The board shows its task number and whether it still blocks work.', 'Open the prerequisite by selecting its link. Once every prerequisite is Done, queued work can dispatch. Remove a link only when it is no longer a real prerequisite.'],
    links: [{ label: 'Open tasks to link', to: '/tasks' }],
    note: 'A task cannot depend on itself, and circular dependencies are refused. Hermes draft access can change dependencies only on its own Backlog drafts.',
  },
  {
    id: 'task-filters', title: 'Filter tasks and hide lanes', area: 'Tasks',
    summary: 'Keep the vertical task board readable with search, tags, filters and lane controls.',
    keywords: ['filter', 'filters', 'hide', 'lanes', 'lane', 'tag', 'tags', 'search tasks', 'missing task', 'collapse'],
    steps: ['Search by title, tags or #ID. Open Filters for agent, assignee, priority and tag choices.', 'Use Lanes to hide statuses you do not need, or collapse a lane with its header.', 'If a task seems missing, clear filters and choose Show all lanes. Your board preferences are saved in this browser.'],
    links: [{ label: 'Open board controls', to: '/tasks#board-controls' }],
  },
  {
    id: 'approvals', title: 'Review and approve work', area: 'Tasks',
    summary: 'Inspect the requested action and approval reasons before allowing sensitive work.',
    keywords: ['approve', 'approval', 'review', 'main branch', 'push', 'publish', 'deploy', 'plan mode', 'output approval', 'ExitPlanMode', 'continue output'],
    steps: ['Tasks shows ready approvals in Needs approval, including project operator decisions whose prerequisites are finished. Open the task to inspect the description, definition of done, result and artifacts first.', 'Use the blue Approve run button for a task awaiting execution permission. Approval reasons appear beside it. Editing approved task details clears that approval.', 'For an unfinished read-only project plan, choose Approve & continue directly on its task row. This resumes the same scoped story; RCD saves one private Markdown document and the agent remains read-only.', 'For a successful project story, choose Approve handoff directly on its task row or details. This accepts the latest displayed result and current Markdown hash and releases ready dependents. Workspace changes still require explicit file review in Projects; RCD never automatically snapshots them.', 'Choose Record decision for a ready human project story. Write the required choices or sign-off, then Approve decision. RCD does not invent decisions or approve blocked or failed work. MCP changes retain their separate review on the MCP page.'],
    links: [{ label: 'Open task reviews', to: '/tasks' }, { label: 'Open project story reviews', to: '/projects?view=work' }, { label: 'Open MCP change reviews', to: '/mcp#changes-title' }],
  },
  {
    id: 'runs', title: 'Read run output and handle a failure', area: 'Tasks',
    summary: 'Task details show run history, output, exit status and captured usage.',
    keywords: ['logs', 'log', 'output', 'failed task', 'failure', 'timeout', 'provider timed out', 'cancel', 'retry', 'history', 'run result', 'exit code'],
    steps: ['Open the task, then inspect the last run and its output/history.', 'Read Stage and Error before Exit code. OpenClaw can exit with code 0 while its agent result reports a provider timeout. Timed out means the agent did not finish; it does not authorize a model switch.', 'Review partial output and changed files against the task’s definition of done. Correct the task or timeout setting when necessary, review any new approval requirement, then use Run again. Cancel run is available for an active run. Failed, timed-out or interrupted runs can generate alerts; cancellation does not.'],
    links: [{ label: 'Open task run history', to: '/tasks' }, { label: 'Open alert history', to: '/#alerts-title' }],
  },
  {
    id: 'agent-explorer', title: 'Drill into agents, sub-agents and models', area: 'Agents',
    summary: 'Use an agent and sub-agent/session selector to inspect activity and captured usage.',
    keywords: ['subagent', 'sub-agent', 'sub agent', 'session', 'model usage', 'tokens', 'telemetry', 'agent details', 'missing usage', 'model'],
    steps: ['Select an agent in the fleet row or Agent dropdown.', 'Choose a named Sub-agent / session. Review its configuration, observed processes and captured activity.', 'Choose This month, Last 7 days or Last 24 hours. Inspect Model usage and source coverage; use Show all to leave a selected session.'],
    links: [{ label: 'Open agent explorer', to: '/agents#agents-title' }, { label: 'Open OpenClaw sub-agents', to: '/agents?agent=openclaw#explorer-target' }],
    note: 'Some sources expose lifetime session snapshots rather than period-level records. Those are labeled and excluded from period totals when attribution is unavailable. Unpriced records make cost partial.',
  },
  {
    id: 'openclaw-chat', title: 'Chat with a named OpenClaw agent', area: 'Chat',
    summary: 'Select a configured OpenClaw agent by name instead of typing its ID.',
    keywords: ['openclaw chat', 'openclaw agent', 'mm-main', 'mm-developer', 'gateway', 'target'],
    steps: ['Open New chat and choose OpenClaw.', 'Choose the named OpenClaw agent in its dropdown, plus the title, model and working directory you need.', 'Start chat, then send your prompt. Each turn runs through the gateway; replies stay in this dashboard and are not delivered to a messaging channel.'],
    links: [{ label: 'Open New chat', to: '/chat?action=new' }, { label: 'Inspect OpenClaw configuration', to: '/agents?agent=openclaw#explorer-target' }],
    note: 'Read/Edit is advisory for OpenClaw. The configured agent’s own tool policy still applies.',
  },
  {
    id: 'agent-chat', title: 'Start or resume an agent chat', area: 'Chat',
    summary: 'Talk to Claude Code, Codex, Hermes or OpenClaw and retain the conversation.',
    keywords: ['chat', 'conversation', 'message', 'resume', 'read mode', 'edit mode', 'prompt'],
    steps: ['Choose New chat, select the agent, and set a title, working directory, model and Read/Edit mode.', 'Select Start chat. Type a prompt and send it; an agent turn can consume usage.', 'Open an existing thread in the thread list to continue it. The selected thread has a shareable local ?thread= link; an approval-required turn waits for your review.'],
    links: [{ label: 'Open New chat', to: '/chat?action=new' }, { label: 'Open existing conversations', to: '/chat' }],
    note: 'Read/Edit restrictions depend on the agent. Check the explanatory note in New chat; Hermes and OpenClaw use their own tool policies.',
  },
  {
    id: 'subscriptions', title: 'Configure subscriptions and compare savings', area: 'Costs',
    summary: 'Compare captured API-equivalent usage against each agent’s full monthly subscription.',
    keywords: ['subscription', 'subscriptions', 'savings', 'saving', '20', 'billing', 'monthly', 'claude cost', 'codex cost'],
    steps: ['RCD is free-only by default. If this installation deliberately provides a native Claude Code or Codex subscription route, open Agents → Billing & rates and explicitly save that account as Subscription.', 'Select This month in Agents and read the agent’s subscription and savings summary.', 'Savings compare captured API-equivalent usage for this calendar month against the full monthly subscription, counted once across that agent’s sub-agents.'],
    links: [{ label: 'Open Billing & rates', to: '/agents?agent=codex&action=billing' }, { label: 'Open cost summary', to: '/agents?agent=codex#usage-summary' }],
    note: 'These are captured-usage estimates, not provider invoices. Partial coverage or missing prices limits the comparison; a negative result means captured API-equivalent usage is below the subscription fee.',
  },
  {
    id: 'price-unknown', title: 'A task fails with PRICE_UNKNOWN', area: 'Costs',
    summary: 'Dispatch refuses any route that has no reviewed pricing class. The run fails in under a second and never starts an agent.',
    keywords: ['price_unknown', 'price unknown', 'pricing class', 'dispatch denied', 'reviewed route', 'fails instantly', 'rerun fails', 'free only', 'route classes'],
    steps: ['Claude Code or Codex: the effective Billing & rates configuration is authoritative. Standard membership defaults are Subscription; save only if you intentionally changed a mode or amount.', 'OpenClaw: an approved project story automatically reviews its exact pinned :free model and target. Go Free records its exact route separately. Standalone tasks need an exact free entry in MAC_CONTROL_DISPATCH_ROUTE_CLASSES (for example openclaw|mm-developer|<exact model id>). Restart RCD after changing a host setting.', 'Hermes: project coordination pins the configured native free model. Other Hermes tasks need an explicit configured free route.', 'Rerun the task. Each rerun takes a fresh claim, so a fix applies to new runs only; failed runs keep the class they froze.'],
    links: [{ label: 'Open Billing & rates', to: '/agents?action=billing' }, { label: 'Open Tasks', to: '/tasks' }],
    note: 'This is the pre-dispatch spending guard, not a fault. A :free model name, a billing estimate or a past successful run does not classify a route. Paid OpenClaw and Hermes routes are always refused.',
  },
  {
    id: 'grok-build', title: 'Use Grok Build as an agent', area: 'Agents',
    summary: 'Grok Build is xAI\u2019s terminal coding agent. RCD can run it on a SuperGrok subscription, next to or instead of any other agent.',
    keywords: ['grok', 'grok build', 'xai', 'supergrok', 'agent', 'install', 'login', 'subscription'],
    steps: ['Install the CLI on the Pi and sign in with grok login (or grok login --device-code on a machine without a browser). RCD never sees the sign-in.', 'Open Agents, then Billing & rates, set Grok Build to Subscription and save. Until you do, RCD refuses to start it, because the CLI has no dollar cap and an API-billed route cannot be bounded.', 'Create a task or choose Grok Build as a project story agent or fallback. Pick a model such as grok-4.6, grok-4.5 or grok-build-0.1, or leave it blank for the CLI default.', 'Read the data notice first: Grok sends the task and the files it reads to xAI. RCD runs it with telemetry and trace upload off, inside a filesystem sandbox (read-only for a read task, the working directory for an edit task), with git push and merge blocked.'],
    links: [{ label: 'Open Billing & rates', to: '/agents?action=billing' }, { label: 'Open Agents', to: '/agents' }],
    note: 'RCD works with any mix of agents installed, including only Grok Build. Usage for Grok comes from the runs RCD dispatches; it does not read the CLI\u2019s own session history. Grok is not used as a project planner, and subscription limit notices cover Claude Code and Codex only.',
  },
  {
    id: 'subscription-limits', title: 'A Claude or Codex limit was reached', area: 'Costs',
    summary: 'RCD notes when a subscription limit lifts, moves stories to an approved alternate on its own, and lets you send the rest across in one click.',
    keywords: ['limit', 'limit reached', 'session limit', 'usage limit', 'resets', 'quota', 'reroute', 'fallback', 'alternate', 'codex', 'claude', 'resume time'],
    steps: ['When a run stops on a limit, a notice appears at the top of every page with the time it lifts in your time zone. It appears once per limit; use the × to hide it.', 'Each story that meets the limit already moves to its approved alternate route by itself. The notice counts these rather than announcing every one.', 'To avoid wasted attempts, select Send the waiting stories to the other subscription. Stories that have not started then go to the approved alternate of the same grade (Haiku to Luna, Sonnet to Terra, Opus to Sol) until the limit lifts, and return to their own route afterwards. Turn it off in the same notice.', 'If the other subscription is limited too, or a story has no approved alternate, it waits. You can also ask Hermes in Discord for the status; changing the routing from Discord needs Allow my Discord requests to change how work is routed in your profile.'],
    links: [{ label: 'Open Projects', to: '/projects' }, { label: 'Open your profile', to: '/profile' }],
    note: 'Only routes the approved plan already lists are ever used, and nothing is approved, dispatched or spent beyond that. A limit with no reported lift time expires after a few hours or at the first later success.',
  },
  {
    id: 'model-rates', title: 'Price an unrecognized model', area: 'Costs',
    summary: 'Add explicit token rates when a model’s usage is captured but its API equivalent is unpriced.',
    keywords: ['unpriced', 'rates', 'price', 'pricing', 'million', 'cache', 'custom model'],
    steps: ['Open Billing & rates and expand Model rates · USD per million tokens.', 'Choose or enter the exact model ID, enable Save custom rates for this model, and fill all five non-negative input/output/cache rates.', 'Save and review usage again. Source-reported cost takes precedence; custom rates apply uniformly up to their input limit.'],
    links: [{ label: 'Open model rate settings', to: '/agents?action=billing' }],
    note: 'Use rates from the model provider. Models ending in :free cost 0. Other missing rates remain unpriced; tools, taxes and other surcharges are outside token estimates.',
  },
  {
    id: 'openrouter', title: 'Track actual OpenRouter spending', area: 'Costs',
    summary: 'Read the provider’s current-key totals separately from estimated API-equivalent usage.',
    keywords: ['openrouter', 'actual cost', 'actual spending', 'api cost', 'keys', 'shared key', 'byok', 'credits', 'hermes cost', 'openclaw cost'],
    steps: ['Open OpenRouter actual spending on Overview or the agent explorer.', 'Compare Today, This week, This month and Key lifetime. These use provider UTC calendar windows and refresh every minute.', 'Read OpenRouter credits and external BYOK usage separately. If Hermes and OpenClaw share a key, the meter shows one shared total.'],
    links: [{ label: 'Open actual spending', to: '/#openrouter-spending' }, { label: 'Open Hermes usage', to: '/agents?agent=hermes#usage-summary' }],
    note: 'Key-wide spending includes every app using that key. A shared-key total cannot be split by agent, model or sub-agent. BYOK usage is separate from OpenRouter credits and provider invoices; secrets are never shown.',
  },
  {
    id: 'mcp', title: 'Add or remove an MCP server', area: 'MCP',
    summary: 'MCP changes are prepared as requests and applied only when you approve them.',
    keywords: ['mcp', 'server', 'tools', 'integration', 'filesystem', 'github token'],
    steps: ['Choose Request a server. Select the agent, server name and stdio command/arguments or HTTP URL.', 'Name required environment variables without entering secret values in the request. Supply their values privately in the Pi’s RCD configuration.', 'Inspect the request under Changes, then Approve or Reject it. Refresh the server list and verify the result. A failed change is not a connected server.'],
    links: [{ label: 'Open MCP servers', to: '/mcp' }, { label: 'Open change reviews', to: '/mcp#changes-title' }],
    note: 'Account-managed Claude connectors are managed in claude.ai. Granting RCD task access is a separate action from registering the RCD MCP server.',
  },
  {
    id: 'hermes-access', title: 'Manage Hermes planning access', area: 'MCP',
    summary: 'Give Hermes expiring access to read tasks or manage its own Backlog drafts.',
    keywords: ['hermes access', 'planning', 'draft', 'grant', 'revoke', 'expired', 'authenticate', 'permission', 'token file'],
    steps: ['Open MCP → Agent access and choose Review Hermes access.', 'Select Read only or Read + planning drafts, and an expiry of 1, 7 or 30 days. Read the limits, then approve. A new grant replaces the previous grant.', 'Register the RCD server through its separate MCP change. Start a new Hermes session to load it. Use Revoke access here to block the grant immediately.'],
    links: [{ label: 'Open Agent access', to: '/mcp#agent-access-title' }, { label: 'Open Hermes MCP server', to: '/mcp#mcp-hermes' }],
    note: 'Draft access cannot queue/start runs, approve/complete/delete tasks, change integrations, or read chats/logs/billing/credentials. An expired grant must be reviewed by you; never give Hermes a browser session or recovery token.',
  },
  {
    id: 'github', title: 'Browse GitHub projects, PRs and issues', area: 'GitHub',
    summary: 'Inspect accessible repositories and their current open work using the existing GitHub login.',
    keywords: ['github', 'repository', 'repositories', 'pull request', 'pr', 'issue', 'repo'],
    steps: ['GitHub is optional. If it is not set up, open Settings > GitHub (optional), choose the account already signed in with gh, list the repositories to show, and save. Your profile’s public contribution graph is a separate GitHub setting: Profile > Contribution settings > Private contributions.', 'Open GitHub and search the repository list.', 'Select a repository to load its open pull requests and issues. Select an item’s link to open it on GitHub.', 'Use Refresh to check again. Notice partial, stale or capped results; this panel does not merge PRs, edit issues or broaden your token’s scopes.'],
    links: [{ label: 'Open GitHub projects', to: '/github#github-title' }],
  },
  {
    id: 'reports', title: 'Read Hermes operational reports', area: 'Ops reports',
    summary: 'Read actual Markdown/text reports with their source and timestamp.',
    keywords: ['report', 'reports', 'cron', 'fleet health', 'ops', 'archive', 'historical', 'morning'],
    steps: ['Open Ops reports. The newest modified report is selected first; choose another from the list.', 'Check the source, timestamp and historical warning before interpreting its findings.', 'Use Refresh to rescan. Hermes cron archives show the actual Response, omitting archived Prompt instructions. Viewing does not generate a new report or enable a schedule.', 'For collector reports, a warning or critical finding can become one Backlog task from the report. The task keeps a link back to the report; choosing the same finding again opens the existing task.'],
    links: [{ label: 'Open operational reports', to: '/reports#reports-title' }],
    note: 'The catalog is capped at 200 files. Oversized/binary files are not previewed. An empty source is different from an unavailable source; old reports do not describe current fleet health.',
  },
  {
    id: 'alerts', title: 'Check Discord alert delivery', area: 'Overview',
    summary: 'Overview shows failed-run and crash-loop alert delivery and recent outcomes.',
    keywords: ['alerts', 'alert', 'discord', 'notification', 'uncertain', 'mark reviewed', 'delivery'],
    steps: ['Open Alerts on Overview and expand Recent alerts.', 'Read the outcome and any delivery acknowledgement. Failed/timed-out/interrupted runs and new crash-loop incidents can alert; successful and cancelled runs do not.', 'For uncertain delivery, inspect the Discord channel before taking further action. Mark reviewed records your inspection without resending.'],
    links: [{ label: 'Open alert history', to: '/#alerts-title' }, { label: 'Inspect service health', to: '/services' }],
    note: 'Rules are configured in the Pi’s private alerts.toml. RCD does not automatically retry uncertain sends, restart services or send task prompts/logs. It uses the channel authorized by the operator.',
  },
  {
    id: 'project-consultant', title: 'Refine a project with the consultant', area: 'Projects',
    summary: 'Talk your idea through, say when it is enough, then send the plan to the coordinator.',
    keywords: ['consultant','ai defaults','free','openrouter','membership','plan'],
    steps: ['Open Projects and choose Refine with project consultant below Create project brief.', 'Choose an allowed workspace, enter a project name and goal, and choose a project type (the closest fit, or Other if nothing fits exactly). The type is required here so it is always part of the plan. The consultant is told the type\u2019s planning guidance and says if your goal does not fit it.', 'New AI conversations use Hermes with openrouter/free unless you changed Profile → AI defaults. Install and configure the selected native agent first.', 'The consultant answers, then asks what it needs to know. Keep talking until you are satisfied; you never have to read its instructions.', 'Choose That’s enough, write up the plan. The brief opens for you to edit. Confirm the working directory and approve coordination; the assigned Delegator then creates the project map and stories.', 'Review the returned project map before separately approving story execution.'],
    links: [{label:'Configure AI defaults',to:'/profile#ai-settings'},{label:'Open Projects',to:'/projects'}],
    note: 'Free routes can throttle or fail. Profile → AI defaults also supplies new chat, task and planning forms; existing work keeps its routes. Native membership accounts and API billing are separate. The built-in help chat uses local guides and makes no model calls.',
  },
  {
    id: 'project-types', title: 'Pick a project type so the plan follows a template', area: 'Projects',
    summary: 'A type tells the planner how this kind of project is planned and where it has failed before, then checks the plan.',
    keywords: ['project type','template','website','website property','web app','packaged app','plan checks','failure points','design guide','sign-offs'],
    steps: ['Open Projects, choose New project and pick a type: Web app, Packaged app, Website property, or Other when nothing fits exactly (the plan then says which type it resembles and which gates it keeps). When your brief clearly fits one, MCD suggests it and you can accept or ignore the suggestion. A project with no type is planned as before.', 'The type adds planner text and known failure points to the plan prompt, hands its guides to the planner and agents (for a website: the design guide and the spacing and timing guide), and lists the keys it usually needs.', 'After a plan is proposed, read Plan checks for this project type. They only warn: for example no README story or no story that makes the Playwright screenshots (a person or the pipeline runs that script; agents cannot run a browser), no delivery story (the project must end in the remote repository, public for an MIT-licensed package others install and private for proprietary work, with the branch pushed, a pull request open and the pipeline result read), no file verification story, a preview that does not follow verification, a container story an agent cannot do, generated media planned for an agent, or no responsive review. Fix the plan or ignore a warning on purpose.', 'Look for the human sign-offs the type expects, such as making the media in MCD, approving the look from a live preview and the final local verification. Agents cannot render pages, so you check rendering in the preview.', 'To change a type, copy packs/project-types/<id>.json into the project-types folder of your data directory and edit it; your copy replaces the shipped one. When a project fails for a reason that could have been planned around, add it to the type’s failure points.'],
    links: [{ label: 'Start a project', to: '/projects?action=new' }, { label: 'Open Projects', to: '/projects' }],
    note: 'Types guide planning. They never block a plan and never run model output. A Website property also starts its background clips on the cheapest video tier in the media panel.',
  },
  {
    id: 'project-media', title: 'Make site art and video for a project (fal)', area: 'Projects',
    summary: 'Generate stills and clips from the project’s Media tab, review them, and publish the ones you choose.',
    keywords: ['media','fal','image','video','clip','still','art','generate','publish','candidate','another take','tier','minimax','veo','nano banana','spending acknowledgement'],
    steps: ['Save a fal key first in Profile, Private credentials. The guide Create or replace the fal key lists the models it needs.', 'Open the project’s Media tab (a project whose folder has media/slots.json gets one, and a banner while slots are unresolved). Tick the spending acknowledgement at the top of the panel; pressing Generate without it tells you what is missing and takes you to the box.', 'Each slot starts on a tier from its project type: a website’s clips start on the cheapest video tier (MiniMax H3 Max Turbo) and images on standard. Standard clips use MiniMax H3 Max and premium uses Veo 3.1. Change the tier or how many, read the estimate, press Generate and confirm.', 'Watch progress under that slot’s button: a spinner, waiting or generating text, then finished or the failure. The button reads Generating… until it ends.', 'Review each candidate as a thumbnail or video. Accept and publish the one you want (MCD converts and records it), choose None of these to make another, or Skip to keep the site’s drawn fallback.', 'A slot with generations still waiting for review is not generated again unless you choose Another take, so a double click never pays twice. A published slot is only regenerated when you choose Regenerate.'],
    links: [{ label: 'Open Projects', to: '/projects' }, { label: 'Media models and prices', to: '/agents?action=billing' }],
    note: 'A clip starts from a published, approved still. A draft still is too small to publish; make stills at standard or premium. Agents never receive the fal key and cannot generate media.',
  },
  {
    id: 'media-spend', title: 'Check media spend and avoid paying twice', area: 'Costs',
    summary: 'Estimates are an upper bound; fal’s usage page is the truth. Repeats and unpriced runs are shown, not hidden.',
    keywords: ['media spend','fal cost','estimate','repeat','double generation','unpriced','ledger','credit limit','usage','veo','minimax','price'],
    steps: ['Every estimate comes from list prices checked against fal’s own usage table: Veo 3.1 Fast $0.15 a second, Veo 3.1 $0.40 a second, MiniMax H3 Max $0.08 and Turbo $0.04 a second at 768p, and a 2K Nano Banana picture is 1.5 image units of $0.08. fal’s usage page is the truth.', 'Under the Media panel the spend line shows runs finished, the estimated total, how many runs repeated a slot already generated, and any runs with no price. An unpriced run is named, never counted as zero.', 'To keep cost down: leave website clips on the cheapest tier, generate one take at a time, review before asking for another, and set a credit limit at fal. MiniMax’s launch discount ends on 31 October 2026, so estimates use the higher price.', 'If fal’s usage is far above MCD’s total, check for runs with no price and for repeats. Every run, with its fal request id, is in media/ledger.jsonl in MCD’s data folder.', 'MCD does not cap spending. The limits are the confirmation, the repeat guard and the credit limit you set at fal.'],
    links: [{ label: 'Media models and prices', to: '/agents?action=billing' }, { label: 'Open Projects', to: '/projects' }],
    note: 'In the first real website run fal billed $16.88 while MCD showed about $2, because Veo clips had no price and repeat generations were not flagged. Both are fixed.',
  },
  {
    id: 'fal-key', title: 'Create or replace the fal key', area: 'Access',
    summary: 'fal fixes a key’s allowed models when the key is created, so a model added later needs a new key.',
    keywords: ['fal key','allowed models','minimax','wildcard','pattern','replace key','api preset','credit limit','refused'],
    steps: ['At fal.ai/dashboard/keys create a key with the API preset, add its allowed models, and set a credit limit. fal cannot change a key’s model list afterwards.', 'Add these patterns: minimax/h3-max* (the default video models), fal-ai/nano-banana-2* and fal-ai/nano-banana-pro* (images), and fal-ai/veo3.1* only if you want the premium Veo tier. If a wildcard is refused, add the exact endpoint ids listed in Agents, Billing & rates, Media models.', 'Copy the secret once and paste it into Profile, Private credentials, fal.ai key. It is encrypted, write-only and never shown again, and agents never receive it.', 'Run one cheap generation to confirm. If a model is refused, the key’s list does not include it: make a new key, replace the saved one and delete the old key at fal.'],
    links: [{ label: 'Save the key', to: '/profile#credentials-profile' }, { label: 'Media models and prices', to: '/agents?action=billing' }],
    note: 'The edit screen for an existing fal key shows the model list read-only; that is why adding a model there does nothing.',
  },
  {
    id: 'accept-anyway', title: 'Accept a story whose agent reported unfinished work', area: 'Projects',
    summary: 'Accept anyway records the agent’s report and your reason, keeps the run failed in history and releases what waits on it.',
    keywords: ['accept anyway','unfinished','incomplete','failed story','verification','handoff','reason','blocked','agent reported'],
    steps: ['When an agent finishes but its report says work is unfinished or a check could not run, the story fails and blocks what depends on it. Read its report first.', 'If you are content with the result (for example the missing items are made by a later human step, or a check needs a browser the agent does not have), choose Accept anyway… on the story, in Projects under Stories & runs.', 'Type a reason of at least ten characters. MCD records the agent’s own report and your reason as the handoff, keeps the run as failed in the history and releases the stories that depend on it.', 'A crash or timeout leaves no report to accept: use Retry same story instead. A human story is decided, not accepted this way.'],
    links: [{ label: 'Open Projects', to: '/projects' }, { label: 'Open the task board', to: '/tasks' }],
    note: 'Nobody should later read an accepted story as a clean pass: the handoff begins with the operator’s acceptance and keeps the agent’s list of gaps.',
  },
  {
    id: 'host-readiness', title: 'Check that this machine is ready to build projects', area: 'Start here',
    summary: 'A checklist with one-click fixes for the workspace folder, git identity and GitHub access, and a look at which agents can write code.',
    keywords: ['readiness','ready to build','setup','workspace','git identity','github','ssh key','deploy key','agents','build host','pi','prerequisites','push'],
    steps: ['Open Setup wizard, step 1. The panel Is this machine ready to build? lists each check: the workspace folder, git, the git identity, GitHub access, agents that can write code, optional tools and free disk space. Checking changes nothing.', 'Create the workspace folder if it is missing. Projects that must end in a GitHub repository should work in a clone of that repository inside this folder, never in a scratch folder (a scratch folder has no remote).', 'Set the git identity (a name and an email) so commits are attributed. It is saved as the global git identity for this host user.', 'Make a GitHub SSH key. The private half stays on this host; copy the public key shown, add it to your GitHub account (or to one repository’s Deploy keys with write access), then press Test GitHub access.', 'If you installed Codex or OpenClaw from Agent tools and your shell says command not found, press Put installed tools on my PATH (or copy the sign-in command shown on the tool, which starts with its full path), then open a new terminal.', 'Read Agents that build: Claude Code, Codex, OpenClaw and Grok can write code; Hermes plans and coordinates but does not. Install and sign in to a builder from Agent tools if none is listed. Sign-in is not verified here.', 'Optional tools are only needed by some stories: Docker for container images, Node for JavaScript tests and the Playwright screenshot script, ffmpeg for media, gh for pull requests. Use Recheck with network test to confirm GitHub and your model provider are reachable.'],
    links: [{ label: 'Open the setup wizard', to: '/setup' }, { label: 'Open Agent tools', to: '/profile#agent-tools' }],
    note: 'Fixes do one named thing each: create the folder, set the git identity, make or test the GitHub key. Nothing installs software, stores a token or runs project code, and the private key is never shown.',
  },
  {
    id: 'sign-in', title: 'Sign in and resolve a login problem', area: 'Access',
    summary: 'Use an allowed Google account; RCD requests identity access only.',
    keywords: ['login', 'log in', 'sign in', 'signin', 'google', 'account', 'org_internal', '403', 'access blocked', 'callback'],
    steps: ['Open RCD and select Sign in with Google, then choose an allowed account.', 'If a Gmail test account sees org_internal, the OAuth app audience must allow External users and list that account as a test user during testing.', 'For redirect mismatch, check the exact origin and /auth/callback in Google’s OAuth client. Local and tailnet HTTPS origins use separate callbacks; use Sign out when finished.'],
    links: [{ label: 'Open Overview', to: '/' }],
    note: 'Google sign-in does not grant Gmail or Drive access. Local recovery is for the operator on this Pi only; do not paste credentials into help chat.',
  },
  {
    id: 'remote', title: 'Open RCD from another Tailscale device', area: 'Access',
    summary: 'Use RCD’s own HTTPS Serve port on a device signed into your tailnet.',
    keywords: ['remote', 'tailscale', 'tailnet', 'magic dns', '9443', 'another device', 'second device', 'phone'],
    steps: ['On another Tailscale-connected device, open your configured HTTPS dashboard address/.', 'Sign in with an allowed Google account on that device. Verify Overview and an agent drill-down load.', 'Keep the :9443 port in RCD links and its OAuth callback. Port 443 serves OpenClaw; other existing proxies remain separate.'],
    links: [{ label: 'Open Tailscale peers', to: '/pi#ts-title' }],
    note: 'This is tailnet access, not public hosting. A successful local login does not verify login from a separate device.',
  },
]

const stopWords = new Set('how do does i me my you can could please the a an to of for with is it that this in on and or use help show where what why want would about'.split(' '))
function normalize(value: string) { return value.toLowerCase().replace(/[’']/g, '').replace(/[^a-z0-9-]+/g, ' ').trim() }
export function findGuides(question: string, contextId?: string): HelpGuide[] {
  const query = normalize(question)
  if (!query) return []
  const tokens = [...new Set(query.split(' ').filter(t => t.length > 1 && !stopWords.has(t)))]
  const ranked = helpGuides.map(guide => {
    const phrases = [guide.title, ...guide.keywords].map(normalize)
    const words = new Set(phrases.join(' ').split(' '))
    const score = phrases.reduce((n, p) => n + (p && (` ${query} `).includes(` ${p} `) ? (p.includes(' ') ? 10 : 4) : 0), 0)
      + tokens.reduce((n, token) => n + (words.has(token) ? 2 : 0), 0)
    return { guide, score }
  }).filter(r => r.score > 0).sort((a, b) => b.score - a.score)
  if (ranked.length) return ranked.slice(0, 3).map(r => r.guide)
  // Explicit short follow-ups reuse the previous topic, not unrelated unknown questions.
  if (contextId && /^(how|where|what|and|can)\b/.test(query) && /\b(that|it|this|next)\b/.test(query)) {
    const previous = helpGuides.find(g => g.id === contextId)
    return previous ? [previous] : []
  }
  return []
}

export function pageGuide(path: string): HelpGuide {
  const ids: Record<string, string> = { '/': 'overview', '/pi': 'hardware', '/services': 'services', '/tasks': 'agent-tasks', '/agents': 'agent-explorer', '/chat': 'agent-chat', '/mcp': 'mcp', '/github': 'github', '/reports': 'reports' }
  return helpGuides.find(g => g.id === ids[path]) ?? helpGuides[0]!
}
