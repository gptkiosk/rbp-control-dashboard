# Projects, model routes and shared memory

Open **Projects** (`/projects`) or the Help topic `projects`. Creating or viewing a draft
uses no model tokens. Live work starts only from a reviewed planning/submission action.

## From brief to work

1. Create a project, choose an allowlisted working directory, and write its goal,
   constraints and exclusions. Set **Story assignment preference** from Economy / OpenClaw
   first through Balanced to Capability / Claude & Codex first. The initial default is centered
   at Balanced (50/100). Save changes as a new revision.
2. **Plan** (the button names your planner, for example *Plan (Codex planner)*) reviews the coordinator request. Hermes chooses an approved
   subscription candidate (Claude Opus or the configured Codex model), MCD invokes that
   CLI, and Hermes reviews its returned JSON plan. Explicit Hermes API planning needs its
   own approval. Planner output must satisfy the bounded node schema; malformed or
   unapproved selections stop without implementing anything. If you changed the brief or the
   working directory since the last plan, tick **Plan from scratch** in the request: the planner
   is then not shown the stories already on the map. Without it the planner sees them and a
   free model tends to hand them straight back unchanged. (It is ticked for you when the
   current plan already fails the standards.)
3. Edit the returned visual map. Add phases and child stories, drag nodes, use Arrange or
   Fit map, and choose each story's instructions, scope, definition of done, agent, model,
   Read/Edit mode, OpenClaw target and prerequisites. Circular links are refused.
4. Add ordered **Model route** alternatives where appropriate. They are part of the
   reviewed revision, never generated dynamically from a failure. Choose execution mode.
5. **Review & submit** first shows the standards check for this plan: what it breaks (an area the
   repository's standards do not list, a risk below an area's minimum, a high-risk story on a
   free-only route), one line per story, with the areas the standards do list shown once. A plan
   that fails it cannot be submitted until you fix the stories or plan again from scratch.
   It then freezes this revision, working branch, assignments and routes.
   Hermes returns a dependency-respecting order. MCD creates those board stories once.
   Board edits/dependency changes/deletion cannot bypass the project approval.
6. **Stories & runs** links to actual task evidence. Successful runs stop in Review.
   Verify the definition of done, edit the handoff summary and accept it. Human stories
   need a verified operator summary. Dependencies wait for acceptance, rather than merely
   successful process exit. Pause dispatch blocks new stories; current runs can finish.

## Recovering a failed plan

If a successful planner/reviewer result was rejected during validation, **Resume saved plan**
revalidates that result without rerunning the subscription planner. It refreshes the native
execution catalog before Hermes review. Human decision/review stories with an omitted scope
receive a visible scope bounded to their own instructions and acceptance criteria. Agent
stories still require explicit scope; errors name the affected story and missing fields.
Invalid JSON, a failed run, or a changed revision cannot use this shortcut. The parser
accepts no arbitrary trailing content; one redundant closing brace after a complete `nodes`
object is tolerated, and the original run output remains available. **Retry planning**
starts a new planning pipeline after its coordination review. A failed coordinator, planner
or plan-review run automatically retries the same read-only step on the next approved route
that has not already failed. Configured free Hermes models/providers are kept as recovery
routes; candidates outside the route policy are excluded, and paid API is tried last. No retry grants permission to
spend, dispatch project stories or publish. If every eligible route fails, the project stays
editable and can be retried after changing the planner route; it does not need to be deleted.
Recovery never starts story execution or authorizes publication.

## Story assignment preference

The five-position slider is saved in the project document as `planning_bias` (0–100).
Hermes coordination, the subscription planner and Hermes plan review all receive this
preference. Economy recommends OpenClaw for well-bounded work and reserves subscriptions
for complex, sensitive or integration stories. Capability recommends Claude/Codex for most
implementation, with OpenClaw handling small supporting tasks. Balanced uses task complexity
to split the work. Agents can explain exceptions in the assignment rationale; the slider
is a soft preference, not a fixed allocation percentage or a cost/quality forecast.

The preference applies to story agents, not the planner selection. OpenClaw's gateway is
local, but its models run with cloud providers. Free-first routes may use the already
configured capped Google BYOK fallback. Subscription fees stay fixed; choosing OpenClaw
can conserve subscription quota, but does not inherently lower those fees. Existing API
and execution review requirements still apply.

After mapping, edit the slider under **Project settings**, save, then request a new
plan if you want revised recommendations. Moving it alone preserves all existing agent,
model and dependency edits. New manual stories start with OpenClaw below the midpoint
(using the configured developer target when available), otherwise Codex; their model stays
at its configured default. Every story remains individually editable before submission.
Approved projects keep their frozen assignments. Older documents default to 75 without
rewriting their stored document or approved manifest.

## Building in parallel (a switch, off by default)

When you create a project, **Build in parallel** decides how it is built. **Off, the default**, builds one story at a time in dependency
order. **On**, the planner is told to plan for width, and MCD checks and orders the plan to take advantage of it:

- **The planner splits the work into branches** that change different files and can run at the same time, gives each editing story a
  **files it changes** list (`touches`: relative folders or globs), and adds an **integration story** wherever branches come together. An
  integration story depends on at least two stories; it receives their accepted commits and is told to run the combined checks and
  fix only what the join broke.
- **Submission refuses an overlap.** Two editing stories that can run at the same time must not share a file, and must each say what they change. The
  Projects page lists any pair that clash, with the fix: make one depend on the other, split their files, or turn parallel build off.
- **The longest chain starts first.** Stories are created so the chain that sets the finish time is never left waiting behind shorter ones.
- **A schedule readout** on the map shows the longest chain against the total, the best-case speed-up, how many stories can run at once and, as work
  finishes, how much the runs really overlapped. Overlap needs room: with `MAC_CONTROL_MAX_CONCURRENT_RUNS` at its default of 2, at most two stories run at
  once however wide the plan is. Raise it (up to 8) on a machine and provider that can take it; free models may throttle.
- **Optional lighter gate** (`MAC_CONTROL_PROJECT_AUTO_ACCEPT_LOW=true`, off by default). A low-risk story is accepted on its own only when its run
  succeeded without an incomplete or blocked report, it is not an integration story, it changed at least one file, and every file it changed is inside
  its declared files. Medium and high risk stories, integration stories and anything outside its files wait for you. The acceptance is recorded in the
  project ledger as `auto-accept`. It is not independent verification.

Nothing here merges or pushes your source branch; the rest of this section still applies.

## Sequential and parallel work

Sequential mode uses the reviewed project workspace and adds a serial handoff link even
between otherwise independent stories. Parallel mode requires a clean Git repository root
and committed source. It freezes HEAD and creates a local `codex/mcd-…` branch/worktree for
each agent story under the existing workspace allowlist. Independent stories can occupy the
configured dispatcher slots (two by default); dependencies still wait for accepted results.

At acceptance, MCD can create a local snapshot of **explicitly selected reviewed files**.
The dialog shows tracked diffs; inspect new files in the workspace before selecting them.
Every changed file must be selected, or committed/reverted outside MCD, so a handoff leaves
its workspace clean. This avoids requiring Codex to write Git metadata through its sandbox.
Nothing automatically pushes, publishes or merges the source branch.

Before a dependent story starts, MCD applies its accepted prerequisite commits to that
story's worktree. Conflicts abort the cherry-pick sequence and fail that story visibly.
Resolve the workspace, use **Review integration** to confirm the resolved prerequisite files, then retry explicitly. A confirmed integration remains Failed until its own story run and handoff review complete. Consolidated accepted histories supersede their ancestor artifacts, avoiding replay of the original conflict. No conflict resolution is guessed.
Use a final integration/review story with all implementation stories as prerequisites;
review its branch before choosing how to integrate it into the source repository. Worktrees
are retained for inspection/rollback; there is no automatic destructive cleanup.

Claude/Codex work in their assigned directory using their existing CLI modes. Hermes uses
`--in`; its mode is advisory. OpenClaw's gateway retains its configured agent home, receives
an explicit project execution path, and gets a stable separate session per project card.
Runs on the same named OpenClaw target are serialized. Its tool access and Read/Edit remain
advisory; a project workspace is coordination isolation, not a new OS security boundary.

## Shared project memory

Each run receives the approved goal, constraints, story ownership, its full current story,
accepted artifact branch/HEAD references and recent accepted handoffs/decisions/checkpoints.
Context is captured with the run's task/revision. Results are proposals until accepted;
a quota checkpoint explicitly labels partial work unverified. The same story and workspace
continue after a reviewed model handoff. An append-only ledger records who accepted what.

The prompt includes up to 20 recent records (each bounded) within 180 KiB. The full ledger
and run evidence remain available in Projects/task links; large histories are not silently
represented as the entire memory. Decisions can be appended without rewriting the approved
scope. Export context supports native sessions outside MCD. This does not merge private
Claude/Codex/OpenClaw/Hermes histories or automatically ingest arbitrary native sessions.
Agent tokens cannot approve plans, submit projects or accept handoffs; existing Hermes MCP
Read/Draft access is unchanged. Model output remains data and cannot supply commands,
permissions, branch changes or additional dispatch routes.

## Model switching and quota behavior

Primary models are editable per story. Suggestions include Claude Opus/Sonnet/Haiku 5.5,
GPT-6.1 Sol and GPT-5.6 Terra (`gpt-5.6-terra`, verified in this Mac's Codex catalog).
Account/CLI availability can differ. Claude and Codex use their existing subscription
logins (verified locally as Claude Pro/claude.ai and Codex ChatGPT). Project Claude subscription runs do not apply an API-dollar budget to their API-equivalent usage; API-billed runs keep the CLI budget. Billing configuration still controls API-equivalent cost and subscription savings.

After a failed run explicitly reports a usage/quota/rate limit, MCD captures a checkpoint
and tries the next approved agent/model pair once for that story. A stopped planner can
try another approved subscription candidate. Other errors, timeouts, cancellation and
malformed plan output require explicit review/retry. No unapproved paid model is invented.
Automatic alternate Hermes/OpenClaw routes are restricted to free model IDs (`:free`) or capped Google Gemini 2.5 Flash, with API/BYOK usage acknowledgment at submission. Explicit model assignments disable inherited primary-model fallback for that run; MCD controls approved handoffs. A blank model follows the native agent default and its configured fallback policy.

This is reactive failover: MCD cannot predict every provider's remaining subscription quota,
and switching models in the same subscription can share an exhausted quota. The current
iteration does not claim global quota preflight or guarantee free-model uptime.

For a failed story, **Stories & runs** offers **Retry same story** and explicit
**Retry with** choices from that story's already-approved routes. A route change preserves
the card, scope, definition of done, dependencies and workspace, and records an operator
decision in shared memory. The API rejects unapproved routes, stale revisions, duplicate
retries, retired OpenClaw targets and newly unapproved API billing. A timeout never selects
one of these routes automatically. A successful retry still waits for handoff review.

### Choosing the working directory

A new project defaults to the **scratch area**: MCD creates a new private folder for it (`scratch-<name>-<time>` under the managed workspaces folder), every story shares
that one folder in order, and there is no branch, branch grant, hook or commit rule to set up. Agents write files there and you review and keep them. Creating a project is a
button push: name, brief, create. The planner, preference, build mode and working directory are under **Choices (the defaults work)**; the consultant chat uses the same default. Use a git repository as the working directory when the work must be
committed on a branch; then the project needs a branch grant (`project-<id>/<slug>`) before agents can commit, and the checkout must stay on the approved branch.

An Edit-mode Claude story in a scratch folder can run test and syntax runners (`pytest`, `unittest`, `py_compile`, `json.tool`, `node --check`, `npm run test`/`type-check`/`build`, `vitest`, `bash -n`, `shasum`) and the managed read-only scanners (`gitleaks git`, `gitleaks dir`, `csstree-validator`, installed from Agent tools) and Playwright's `playwright screenshot` and `playwright pdf` so it can verify its own work; git, network tools and arbitrary shell stay denied, and a Read-mode story gets no shell. A Read-mode Claude story runs in plan mode and cannot run any command, so a step that must run a build, a server or a script belongs in a human or CI story; if a read-only story returns only a plan, the run is marked incomplete with that advice.

### What each agent can do in a project folder

MCD grants these in its own launch arguments, not in an agent's own configuration, so installing or upgrading an agent does not remove them. Verified with `scripts/probe-agent-capabilities.py`:

| Agent | In an Edit story, in a scratch folder |
|---|---|
| Claude | writes files; runs test and syntax runners and harmless helpers (see above); git is read-only and `git push`/merge stay denied |
| Codex | writes files in its workspace sandbox and runs `node`, `python3` and tests there; no network except the package indexes and GitHub; no container engine |
| Hermes | writes files and runs shell commands; told its task folder first because its terminal starts in its own configured folder |
| OpenClaw | writes files and runs `node` and `python3` through the configured developer agent |

**Defaults work; security is configured.** The default (`MAC_CONTROL_AGENT_PERMISSIONS=working`) lets an Edit story run test and syntax runners, harmless helpers and package installs
(`npm ci`, `npm install`, `pip install`), and gives Codex the package indexes and GitHub in its sandbox, so a project can finish out of the box. Set `MAC_CONTROL_AGENT_PERMISSIONS=strict` to allow only
the commands you list in `MAC_CONTROL_AGENT_EXTRA_COMMANDS` (for example `["Bash(make test:*)"]`) and give Codex its plain workspace sandbox. `MAC_CONTROL_AGENT_EXTRA_NETWORK_DOMAINS`
(for example `["cdn.example.org"]`) adds hosts Codex may reach. Git grants, `git push` and merge denials, and the branch rules apply in either mode. Restart MCD after changing them.

After upgrading an agent runtime, run `python3 scripts/probe-agent-capabilities.py claude codex hermes openclaw`. It uses a few model requests and removes its throwaway folders.

### Retrying after a timeout

After a run times out MCD cannot tell what the attempt changed or whether the provider is still working on it, so the dispatcher refuses every new attempt on that
story until you confirm you reviewed the partial work. Rerun, **Try another free model**, **Use Claude Haiku / Codex Luna** and **Pay for this task** all show
**I reviewed the partial work and want a new attempt** for a timed-out task, and stay off until it is ticked. The confirmation is recorded on the timed-out run
(`RETRY_AUTHORIZED`) and in the project ledger, covers that run only, and can be given only from the operator pages (agents cannot reach them). Without it the
dispatcher still fails closed and starts nothing.

### A way out when a free model is throttled or failing

A free model can time out, be rate limited or be unavailable. A failed task keeps these ways out, and a rerun never costs more than you chose. MCD's task panel shows them as buttons; in RCD they are
API routes (`go-free`, `low-cost-retry`, `pay-retry`) because RCD's task panel does not have the retry component yet:

- **Rerun task** (free): try the same route again later. Free routes recover on their own, so waiting is often enough.
- **Try another free model** (free): for an OpenClaw task, another configured `:free` model on the same OpenClaw agent. The model that just failed is not offered.
- **Use Claude Haiku or Codex Luna** (your subscription, no per-token charge): the cost-aware Balanced models. For a read-only task you can also tick
  **edit mode**, which switches that one task to workspace execution on the project branch and needs a separate acknowledgement.
- **Pay for this task** (API billing, this task only): a configured OpenRouter model that is not free, on a configured OpenClaw agent. It needs an
  acknowledgement, no Google BYOK route is added, and any limits you turned on in Settings → AI & models → Accounts → Spending & limits, and the route policy still apply when it starts, so it can stop
  there with the reason.

Each choice keeps the story's scope, workspace, dependencies and acceptance, supersedes any pending output continuation, and records an operator decision in
the project ledger and a route amendment in the approved manifest. Only the current failed run can be retried, and only in an active project.

## Native configuration and assigned models

MCD reads the current native Hermes model/fallback fields and OpenClaw agent names,
targets and models when planning. Only these safe fields enter the catalog; credentials
never do. Model overrides are passed to each CLI. OpenClaw's explicit override disables
its inherited fallback chain. The MCD-owned Hermes compatibility shim disables the inherited
chain only inside an explicitly assigned run, and reports the final primary model/provider.
Unassigned coordinator runs keep the native free-first and capped Google BYOK policy.
The shim leaves native configuration untouched and fails before inference if its supported
runtime APIs are unavailable. MCD rejects a reported model mismatch and keeps its usage
evidence for review. Codex does not report its actual model; its requested model remains
visible without claiming independent verification.

Before submission MCD refuses retired OpenClaw targets. Story context prohibits native
re-delegation that could bypass reviewed assignments; Hermes/OpenClaw still use their
native tool permissions (Read/Edit remains advisory). Edit routing in native settings and
review each proposed model/target in MCD before execution.

Hermes and OpenClaw use the same existing OpenRouter key. Its verified limit is **$20,
monthly reset, BYOK included**. Agents shows current key-wide limit/reset/inclusion rather
than inferring the cap from an alert. It covers any caller of that same key and recorded
OpenRouter/BYOK usage. It is not a Google invoice cap, and does not cover direct Google
calls or another key. At exhaustion requests can stop, including free routes on that key;
no alternate uncapped key is used automatically. Model calls were not made during setup.

Private rollback inputs and the cap receipt are under
`~/.mac-control/backups/project-routing-20261010T062707Z/` (directory 700/files 600).
Restoring routing does not restore OpenRouter budget settings; the receipt records their
previous/current values. No credentials are stored in this repository.

Sources: [OpenRouter key limits including BYOK](https://openrouter.ai/docs/api/api-reference/api-keys/update-keys),
[BYOK routing](https://openrouter.ai/docs/guides/overview/auth/byok),
[OpenClaw model parameters](https://docs.openclaw.ai/gateway/config-agents/models),
[Codex models](https://learn.chatgpt.com/docs/models),
[Claude CLI budget/auth flags](https://code.claude.com/docs/en/cli-reference),
[Hermes fallback providers](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/fallback-providers.md).
Installed CLI source/help and read-only account metadata were checked in addition to these docs.

## Implementation and verification

Migration 0010 adds versioned project documents, immutable task bindings and memory records.
Dispatcher claims remain transactional; overlapping project directories cannot run together.
A live restarted process never blindly restarts an interrupted model run. No external sends,
model credentials or additional MCP permissions are introduced by the Projects API.

Tests use temporary databases, real temporary Git repositories and fake model results:
planner/return/dispatch validation, revision conflicts, duplicate dispatch, dependencies,
operator acceptance, pause/resume, finite quota handoffs (including stderr-only failures),
workspace separation, accepted prerequisite integration, conflicts and reviewed snapshots.
Browser verification uses an isolated loopback preview with dispatch/collection disabled;
see [Remote project preview access](configuration/remote-project-previews.md) for the reserved 41350–41399 port group and Tailscale SSH review tunnel.
the example map is not a submitted live project.

Verification: API 237 tests, web 155 tests and MCP 13 tests; production type-check/build pass. Frozen project dependencies are enforced even through curated agent draft tools, and managed workspace symlinks cannot escape the approved root. No real planning/model turn was invoked during verification.

New profiles start at Balanced (50/100); legacy maps lacking the field retain their earlier 75 default for compatibility. See [Profiles and Discord](PROFILES_AND_DISCORD.md) for remote project intake, diagram requests, progress/delivery status and private settings.

## Read-only stories that need a Markdown artifact

Claude Read mode uses its CLI plan mode. If a story returns an unfinished plan because
writing is blocked, MCD marks the run **Awaiting output approval**, rather than treating
that plan as a completed handoff. In **Projects → Stories & runs**, select **Approve output
& continue**. The dialog shows the previous result, the current agent/model, and the exact
private output location. Acknowledge that scope and select **Approve & continue**.

The continuation uses the same story, working directory, definition of done and dependency
links. Claude resumes its prior session when available, with Read/Glob/Grep only; no shell,
file-write, delegation or MCP tools are exposed. It returns strict Markdown/handoff JSON,
and MCD saves one file under its configured data directory's `project-outputs/` folder.
No repository edits, native ExitPlanMode approval or increased agent write access are needed.
Existing output files are not overwritten; symlinks and out-of-folder filenames are refused.
Malformed output stops for explicit retry. Subscription billing and approved model routes
remain in effect; this action never authorizes new API billing.

After completion, **Review handoff** displays the proposed document. Read it and acknowledge
its definition-of-done review before **Accept handoff**. MCD verifies the document hash;
changed or missing output cannot be accepted. Accepted output references join shared project
context. Dependent stories remain blocked until acceptance. Output approval alone never
marks the story Done. This is for read-only Markdown deliverables, not a general edit approval.

### Approving directly from Tasks

Ready project decisions appear in **Needs approval** once their prerequisites finish. This is a board display only; it does not mark a human story complete or change dependencies.

Open a task to inspect its definition of done and latest result, then use its blue action button on the row or details:

- **Approve run** grants the displayed execution approval.
- **Approve & continue** resumes an unfinished read-only story with its existing scoped Markdown output authorization.
- **Approve handoff** accepts the latest displayed successful result with the current proposed document hash, in one click. Ready dependent stories may then start. Missing results, a newer run or unsafe/missing output stop approval. Workspace files must still be reviewed and selected in Projects; this shortcut never snapshots changes automatically.
- **Record decision** opens a form on Tasks for the actual operator choices or sign-off. Write the required decision before **Approve decision**. No human decision is inferred.

The full artifact review remains available under Projects → Stories & runs. Failed and dependency-blocked stories do not offer these approval shortcuts.

## Template store

Optional project templates for one kind of deliverable (a upubhub class, for example) can be added from **Settings → Installs & updates → Template store**. A template is planner guidance, plan checks and format guides, published in a pack; it never runs code. You choose only its settings when you start a project. See [Pipeline packs](configuration/pipeline-packs.md).

## Project totals

Once any of a project's tasks has run, the project page shows its totals above the tabs ("Totals so far" while it runs, "Project totals" when it is complete). They cover every run of every task, planning included: agent time and elapsed time, tokens in, out and cached, and one row per agent and model with how it was billed.

Cost is shown two ways. **Actual cost** is what was charged: membership and free-model runs count as $0, and API runs count at the cost the agent reported or, when it reported only tokens (Codex), the tokens at catalog API rates. **API-rate cost** prices every run at published API rates, so membership use can be compared with paying per token. Both include the Media studio's fal estimate for images generated in the project folder. Billing modes are the ones saved for each agent now, and runs with no published rate are counted and left out. The totals are worked out from the run records and the media ledger each time and never stored.

## Closing a project without finishing it

**Close project…** (Projects, in the project heading) ends a project that will not be finished, for example
one replaced by a newer plan. It needs a reason, which is kept in the project ledger with the rest of the
history. The project becomes **Closed**, never Complete: Complete is for projects whose stories finished.

- No new story starts, and a story that is running must be cancelled first.
- Closing offers to **remove the project's tasks from the board** in the same step. If you decline, a Closed project shows
  **Remove tasks from the board**, which takes every one of its tasks off the board, finished ones included, after a confirmation.
- Each task of a Closed project that is not running or done (queued, in Backlog, in Review or failed) can also be deleted on its own,
  and a failed task of a Complete project can be removed. Finished tasks of a Closed project stay until you use the bulk action.
- The ledger keeps the handoff, incident and decision entries; only the tasks' run history on the board is deleted. The project, its plan
  and its brief stay.
- Queued tasks of a paused, Closed or Complete project do not block an in-app update, because nothing can start them.
- A failed task that another task already carries (an unneeded duplicate) can be removed from any project. That includes the failed task a
  project retry replaced while the retry is still queued or running; the retry itself stays protected.
- Everything else on a project stays protected: only the Projects page changes a story.

## Closing and deleting a project

**Close** ends a project without finishing it. The project stays in the library with its plan and whole ledger, and you can remove its tasks from the board. **Delete project** (on a closed or completed project; close a draft, review or failed project first) is the separate, confirmed step that removes the project itself: its tasks and run history, ledger records, deliveries, standards proposals, ledger file, saved outputs and branch grants. The working folder and its files are never touched, so a new project can be pointed at the same folder. A live project (planning, dispatching, active or paused) must be closed first, and a running story cancelled.

## A story that reports itself unfinished

When an agent finishes a run but its report says work is unfinished or a check could not run, the story fails with that report and blocks what depends on it. **Retry same story** runs it again. If the missing part genuinely cannot be done where the agent works (for example rendering pages in a browser, which agent sandboxes do not have), use **Accept anyway** on the story (in Stories & runs) and give a reason. Your reason and the agent's own report (with its gaps) are recorded as the handoff and in the project ledger, the run stays failed in the history, and dependent stories are released. An approved read-only continuation that finishes but still reports unfinished work waits in review; **Approve handoff** refuses it, and **Accept anyway** is offered there too. A story that crashed or timed out has no report to accept and needs a retry. Plan checks for the project type now flag agent stories that ask for browser rendering so the plan avoids the problem.
