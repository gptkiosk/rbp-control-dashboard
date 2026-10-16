# Changelog

All notable changes to Raspberry Pi Control Dashboard (RCD) are listed here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). RCD and the Mac Control Dashboard (MCD) share
major.minor, so a feature level means the same in both. Release notes on GitHub are generated from
the section of the version being released, and a release cannot be built without one.

Internal operator notes, private hostnames and personal identifiers are omitted by policy.

## [Unreleased]

## [0.6.6] - 2026-10-16

### Fixed

- Closing a project no longer leaves its tasks behind on the board. Closing offers to remove the project's tasks in the same step, a Closed project has
  **Remove tasks from the board** for later, and each queued, Backlog, Review or failed task of a Closed project can be deleted on its own (before, only failed
  ones could). The ledger keeps the handoff, incident and decision entries; the tasks' run history is deleted.
- Leftover queued tasks of a Closed or Complete project no longer block an in-app update.

### Changed

- The planner is told what a sandboxed coding agent cannot run. A Codex story cannot reach the local container engine, so the plan no longer asks an edit story to
  build an image or run a container. Container and pipeline files are planned as an edit story that ends with the files committed and the static checks passing, and
  the build and smoke run are planned as a later verification story for a person or a read-only agent. Prompt pack version 7. A planner prompt you edited under
  `roles/custom` in the data folder is used as you wrote it, so add the same rule to your copy.

## [0.6.5] - 2026-10-16

### Fixed

- An update is no longer blocked by the queued stories of a paused project. A failed story leaves the stories after it queued, project stories cannot be moved
  to Backlog by hand, and pausing the project did not change the count, so the update check stayed blocked until the project finished or was closed. Queued stories
  of a paused project cannot start and are no longer counted. Running tasks, plain queued tasks on the board and the stories of an active project still block, and
  the message now says to pause the project.

## [0.6.4] - 2026-10-16

### Fixed

- A Codex story with a git grant can create its project branch and commit again. The permission profile that replaces Codex's plain workspace sandbox left `.git`
  read-only in current Codex builds, so a story stopped with "could not create its ref under `.git/refs/heads`" before doing any work. The profile now makes `.git`
  writable while the repository's hooks folder and config stay read-only, so an agent can still not rewrite the operator's hooks or credential helper. A test runs
  the real Codex sandbox (when Codex is installed on a Mac) so a future Codex change shows up here and not in the middle of a project. A story stopped this way can
  be retried with **Rerun task**.

## [0.6.3] - 2026-10-16

### Fixed

- A submitted plan no longer stops with "Hermes dispatch order does not exactly match the approved stories." Hermes only chooses the order between orders the approved
  dependencies already allow, so its answer is now advice. A phase key or a repeated key in it is ignored, and an answer that leaves a story out or breaks a dependency
  is replaced by the approved plan's own dependency order, with a note in the project memory saying so. No story, route or scope changes. A project already stopped as
  `dispatch_failed` can be submitted again with **Review & submit**.

## [0.6.2] - 2026-10-16

### Fixed

- Replanning no longer hands you the same plan back. The planner was shown the stories already on the map along with the brief, and a free model returned them
  unchanged even after the brief and the working directory changed (so a Docker project kept its old packaged-app stories and failed the new repository's
  standards). The planning request now has **Plan from scratch**, which keeps the current stories out of the planner's view; it is ticked for you when the current
  plan fails the standards.
- The review and submit dialog is readable. It shows the working directory, preference and build mode as a short facts table, a short explanation, the standards
  check, the stories and the billing notes in folded sections, and the approvals and buttons in a padded, bordered action row, instead of one long unspaced
  column of text.
- The standards check is shown before you submit, with one line per story, and the areas a repository lists are shown once instead of after every story. A plan
  that fails it cannot be submitted from the dialog, and refusals from the server keep their line breaks.
- The panels on a project page (heading, planning progress, repository access, schedule, brief) now have even spacing between them.

## [0.6.1] - 2026-10-16

### Fixed

- Look and feel. The bug report dialog now uses the app's standard padded dialog layout (header with an icon and close button, labelled fields, a bordered
  action row) instead of bare text and stacked buttons, and the preview block and the sent-or-open-GitHub buttons are laid out properly.
- The Updates panels are roomier and clearer: titled Available and Rollback blocks with dividers, padded release and confirmation cards, proper spacing for
  checkboxes and text, bordered action rows with the primary button on the right, and an update progress card with state chips. This covers the packaged
  update panel on both products and the checkout update panel on MCD.
- Every log, command output and exact-text window (update logs, release notes, run and chat live output, agent tool logs, service logs, patches, evidence,
  GitHub request previews and reports) now shares one style: the same padding, border, monospace font, line height and scroll height.
- The new project panels (Repository access for agents, Parallel build) have the same vertical spacing as the others, and the bug report preview says
  "1 email" instead of "1 emails". Housekeeping no longer runs "After hours:" into the next word.

## [0.6.0] - 2026-10-16

New in 0.6.0: a bug icon in the header, repository bootstrap for projects that need a new private GitHub repository, and an opt-in parallel build. Bug
intake, Hermes repository proposals and the parallel auto-accept gate are all off until you turn them on, and a project builds serially unless you switch parallel on.

### Added

- A Discord alert when a project's planning or story hand-out stops after its run succeeded, for example when the plan is refused for a
  missing field or a bad dependency. Until now only failed runs alerted, so a plan that came back and then failed validation was
  silent. One alert per project, revision and reason; turn it off with `[projects] enabled = false` in `alerts.toml`.
- A bug icon in the header. It opens a short form, shows the exact issue that would be sent (with paths, emails, addresses and
  key-shaped text removed and listed), and then either files it on the product's official GitHub repository as your signed-in account
  (through the same guarded GitHub action as other writes, after you confirm) or opens a prefilled GitHub page for you to submit under
  your own account. No token, relay or hosted service is involved. See `docs/configuration/bug-reports.md`.
- Bug intake (off by default, `MAC_CONTROL_BUG_INTAKE_ENABLED`). Issues a maintainer has labelled `bug-report` and `accepted` become one
  read-only triage task each, tagged `release-blocker` (label `break-fix`) or `release-queued`, with the report quoted as untrusted
  evidence. A Profile panel lists new tasks and the reports still waiting for a maintainer's label.
- Build in parallel, a switch chosen when a project is created (off by default; off builds one story at a time in dependency order). On, the planner is told to
  plan branches that change different files, with a `touches` list per editing story and integration stories where branches join (role pack version 6).
  Submission refuses two stories that can run together but overlap, a longest-chain-first build order, a schedule readout (longest chain, best-case
  speed-up, width, and the real overlap once runs finish), integration-story instructions, and an optional lighter gate
  (`MAC_CONTROL_PROJECT_AUTO_ACCEPT_LOW`, off by default) that accepts low-risk stories whose changes stay inside their declared files. See `docs/PROJECTS.md`.
- Repository bootstrap. Hermes can propose a new private GitHub repository for a project (`propose_repository`, behind a new Profile switch), which
  waits in Profile under "GitHub actions waiting for you" with its exact request. Approving creates it under your account, always private, with an
  initial README commit, and adds it to the install's GitHub list. A project's "Repository access for agents" form grants agents one branch,
  `project-<id>/<name>`, never main. The planner starts a plan with the approval and setup steps when a repository is missing (role pack version 5).
  See `docs/configuration/repository-bootstrap.md`.
- A "Delivering a containerized web app, local first" guide and a paragraph in the coordinator context (role pack version 4): a private
  repository created first, a pipeline on Linux runners that builds and tests the image, a local run on Colima, and repository setup
  planned as the first step with the repository creation, first push and secrets left to a person.

### Fixed

- The Updates page no longer calls a normal update interrupted. While the helper is staging or removing a version (minutes on a Raspberry
  Pi) the page used to warn "An earlier update was interrupted" and list the folder being built or removed as "only partly staged".
  Both are shown only when no helper is working, so a real interruption still says so. After a successful update the release you just
  installed is no longer offered again under "Update to ...".

## [0.5.5] - 2026-10-16

### Fixed

- A failed project task can be deleted as soon as its retry is queued or running. Retrying from Projects creates a new task, and the old
  failed one used to stay greyed out until the retry finished, which looked like a duplicate you could not remove. The retry itself stays
  protected, a lone failed task is still kept (it holds the only record), and the project ledger notes the deletion.
- The consultant no longer ends every reply with another question. Once you say you are done it confirms and waits, and the brief it
  writes has no closing question: anything still undecided becomes a stated assumption or a human decision story (or is dropped if it
  does not change the plan), so it reaches the coordinator as work instead of a dangling question.
- The planner is told that every story needs its instructions in the description field. A free planner returned a story with scope and
  acceptance but no description, and planning stopped with "needs instructions". (Coordinator role pack version 3.)
- Planning no longer stops with "Dependencies must connect different stories in this project" when the planner orders phases against each
  other or makes a story depend on its own phase. Those links are dropped from planner proposals (story order is kept; a dependency on a
  key that does not exist is still refused, and your own edits are checked as written). Because the saved plan is read again by **Resume
  saved plan**, a project that failed this way can continue from the saved proposal without another planning run.

## [0.5.4] - 2026-10-16

### Fixed

- Planning runs and board tasks on the default free model now start too. 0.5.3 fixed new chats; a project plan run, a task made from a form
  or an older saved task still carried the generic `openrouter/free` and was stopped with `PRICE_UNKNOWN` ("Budget check stopped the
  run"). The dashboard now replaces that default with the free model Hermes or OpenClaw is set up with when a task is created or edited,
  when a plan is requested, and when a saved task starts, so retrying a task that failed this way works without editing it. A model you
  name is never replaced, and a paid default is never chosen for you. Your saved keys were never involved.

## [0.5.3] - 2026-10-16

### Fixed

- Chats with Hermes or OpenClaw on the default model now start. The default, `openrouter/free`, is a generic name that neither agent
  lists, so the dashboard refused every new chat with `PRICE_UNKNOWN` (0.5.2 made that refusal readable; this removes the cause). A new
  chat on that default now uses the free model the agent is set up with (its own default, for example the one `hermes setup` chose),
  shown on the chat as the model in use. A model you pick by name is never replaced, and a paid default is never chosen for you. A
  chat created earlier that has not run yet is corrected the same way when you send its first message.

## [0.5.2] - 2026-10-16

### Fixed

- The project consultant's first message no longer waits for an approval nobody knew to give. The consultant opens with long guidance and
  your installation's standards, which mention releases and deploys, and the approval check read all of it as if you had asked to
  publish something. The guidance now travels as background beside your own words, and only your words are checked. The chat shows
  your message with a note that background was sent with it, and a "Sending your goal" line while the first message goes out.
- The project consultant now works as a conversation. It answers what you ask, asks a few clarifying questions at a time, and keeps going
  until you choose **That’s enough, write up the plan**, which asks for the brief from the whole discussion and opens it for you to edit
  before anything goes to the coordinator. The chat no longer shows the consultant’s instructions or your installation’s background.
- A chat on a model the dashboard has no reviewed pricing for (for example Hermes on `openrouter/free` when Hermes does not list that
  model) no longer looks sent and then fails with `PRICE_UNKNOWN` in the bubble. The dashboard now says so before the conversation
  starts: which agent and model, that the route has not been reviewed, and which free models Hermes is set up with so you can choose
  one in Profile, AI defaults. No empty thread is left behind.

## [0.5.1] - 2026-10-16

### Added
- After-hours housekeeping. Set `MAC_CONTROL_HOUSEKEEPING_AUTO` to the kinds you want cleaned up overnight (`stale_approval_wait`, `old_update_backup`) and the server applies exactly those fixed actions once a day inside a window (default 1 to 5 local time). Off by default. Each finding is re-checked at that moment, a database backup is taken before any row changes, and every action is audited as `after-hours`. The Housekeeping panel shows the last run; Hermes can read and explain the status.

## [0.5.0] - 2026-10-15

### Added
- Coordinator scorecard, in a new section of the Telemetry page. Every approved plan is scored by fixed checks (schema, the job envelope, estimates against size, checkable acceptance criteria, bounded scope, dependencies, route reasons, no stories too big to run, a review for high-risk work, and the standards' floors), compared with what the coordinator returned (how many nodes a person added, removed or changed) and recorded with the planner, the Delegator and the coordinator wording in effect (a version label such as `v2`, `+custom` for your own copies, and a hash). The page shows plan score by planner and by wording with edits per plan, first-pass completion and estimate error, so a change can be compared with the one before it. Eight fixed, general briefs and a scoring route let you try any model or wording change on the same plans. See `docs/configuration/coordinator-scorecard.md`.
- A weekly model watch (off by default; `MAC_CONTROL_MODEL_WATCH_ENABLED=true`). It reads OpenRouter's public model list and, only when something is new, leaves one Backlog card with the sources and exactly what differs: first, models your catalog lists as free that are no longer free, then new free models and changes. It edits nothing: adopting or dropping a model stays a reviewed change. The Models section shows when it last ran. See `docs/configuration/model-profiles.md`.
- Service actions on the Services page: **Why** (a plain explanation, the safest next step and the job's own log as evidence), **Run now**, **Restart** and **Remove** (stops the service for now; the unit file is untouched; you type the label to confirm). Only listed services can be acted on, the dashboard's own service is protected, and every action is audited. See `docs/configuration/service-actions.md`.


## [0.4.8] - 2026-10-15

### Changed
- The project consultant chat now starts with the same knowledge a plan run gets: how the software is delivered, which agent runtimes are installed here and the spending policy, the standards that apply to the chosen working directory, the methods and practices (development practice, hosted and packaged delivery, application security) and the track record of the models it could recommend. It writes the brief so the coordinator can plan from it directly (approach and methods, risks by standards area, security considerations, model and route considerations). You can keep your own copy of any guide in the data folder. It is advice for the conversation and authorizes nothing; if it cannot be read the chat starts without it. See `docs/project-consultant.md`.

## [0.4.7] - 2026-10-15

### Added
- The coordinator now uses model profiles. A planning request includes a compact paragraph on the models it may choose (free or paid, context, tool support, and the track record here by kind of work, with unproven stated plainly), and the submit review shows non-blocking route advice for each story: a proven poor record for that kind of work, no listed tool use for work that edits files, or an unproven model on medium or high risk work. The gates, risk floors and approvals still decide; your own coordinator wording keeps working. See `docs/configuration/model-profiles.md`.

## [0.4.6] - 2026-10-15

### Added
- Model profiles, in a new Models section of the Telemetry page: what each model can do (free or paid, context size, tools, structured output, reasoning, price), how it has done in your own runs (runs, success rate, median time, cost, by kind of work, with a model shown as unproven for a kind until it has 10 runs) and notes people add with a source and a date (stale after 90 days). A Refresh free models action reads OpenRouter's public model list and shows what is new, what is no longer free and what changed, without editing your price catalog or any route. RCD ships no opinions about which model is better at what. The last read and your notes are kept across updates, and `MAC_CONTROL_MODEL_REFRESH_ENABLED` can switch the refresh off. See `docs/configuration/model-profiles.md`.

## [0.4.5] - 2026-10-15

### Added
- Ask Hermes to add to a repository's standards. With the new Profile switch on, Hermes can read a project's standards and propose an addition to the repository's standards file: a risk area, a check, a security bullet or a tightening rule. The server proves it is only an addition (nothing removed, reworded, lowered or loosened) and shows you the exact diff on the project page. Approving creates a new branch in the repository for you to review and merge; your current branch and files are not touched and nothing is pushed. See `docs/configuration/standards.md`.

## [0.4.4] - 2026-10-15

### Added
- You can keep your own coordinator wording across updates. Copy a file from `packs/roles/delegator/` into `roles/custom/` in your data folder and edit it: your copy is used instead of the shipped one, survives every update, and a copy that would break planning (a dropped placeholder, a stray `$`, empty or unreadable) is ignored in favour of the shipped text. The roles status lists customized and ignored files.
- A guide, `docs/configuration/upgrades-and-your-data.md`, says what an update keeps, replaces and never touches: settings, the database, preferences, credentials, the coordinator assignment and guidance, standards, project memory, and what your agents know.

### Fixed
- Agent settings are now covered by tests for every agent (Claude Code, Codex, Grok, Hermes, OpenClaw): installing, updating, rolling back or removing a managed agent tool, applying role guidance and starting a run leave each agent's own settings, credentials and memory untouched. The guide says exactly what RCD writes into an agent's folder (only the marked guidance block).
- A profile saved by a newer version (for example after a rollback) no longer breaks the profile page in an older one: preferences this version does not know are ignored when loading, and missing ones take their defaults.

## [0.4.3] - 2026-10-15

### Changed
- Repository standards now shape plans. When a project's repository has `docs/development/standards.md`, the planner is told the repository's areas and their minimum risk, every story's `area` must be one of them, its risk may not be below the area's minimum, and a high-risk story may not use a free-only route. A plan that breaks these is refused at approval with the reasons. A missing or unreadable file still only warns. See `docs/configuration/standards.md`.
- Starter standards: RCD now ships general standards, so a project is useful out of the box even when its repository has none. They cover areas with a minimum risk, checks for the definition of done and a security checklist for high-risk stories, plus plain guides on application security, development practice and delivering hosted and packaged apps. They apply when a repository has no standards of its own, you can change them by placing your own copy in the data folder, and the project page says which standards apply. See `docs/configuration/starter-standards.md`.
- The repository's checks (its Definition of done table) are frozen on the approved plan revision and added to the definition of done of every agent story that writes, so the agent has to run and report them. The Delegator's planning guidance now also explains how to choose area and risk and to cite the standard in the route reason.
- Telemetry can be cut by property (the standards' property the plan was approved under): a Property filter and a "Work by property" chart with each property's first-pass rate and median time.

## [0.4.2] - 2026-10-15

### Added
- A reference page, `docs/development/distribution.md`, for how this product reaches users: it is packaged code users pull from public releases, not a hosted service. It covers the steps from changelog and version to tag, signed package, draft verification and publishing, what makes a version offered to users, what users do, and what to do about a bad release. The Delegator's guidance now includes this model, and treats publishing a release as at least a medium-risk act.
- Repository standards, matching MCD 0.4.8: a project reads `docs/development/standards.md` from its working directory, shows on the project page which standards it is working under (the property, the number of areas and checks, and the file's hash), and records that on each approved plan revision. The two tables in the file (Definition of done, Risk by area) are parsed by fixed code. A missing or unreadable file is a warning and planning goes on without it. Nothing is fetched and nothing outside the working directory is read. See `docs/configuration/standards.md`.

## [0.4.1] - 2026-10-15

### Added
- Telemetry: a Jobs and telemetry page, matching MCD 0.4.7. It shows how work is going by job (one approved plan revision), kind, risk, size, route, who it is assigned to (a person or an agent), agent and model: unassigned, in progress, waiting for you, completed, estimates missing and failed work; as charts you can read at a glance (donuts for workload by status and by route; stacked bars for work by assignee, by job, by model and by kind; completed per week; median time per kind), with the numbers on hover. The detailed tables (jobs, agents and models with success rate, median time, tokens, reported cost, API-equivalent cost and how often a different model served a run than the one requested, and kinds of work) are folded away until you open them. Read-only and computed from the existing records, so it stays light on a Raspberry Pi. See `docs/configuration/telemetry.md`.

## [0.4.0] - 2026-10-15

RCD adopts the 0.4 feature level for the parts that make sense on a Raspberry Pi: update progress, Housekeeping and the job envelope, matching MCD 0.4.5 and 0.4.6. The MCD-only checkout updater is not part of it; RCD updates from its signed package.

### Added
- The Updates panel shows an update step by step, as the MCD checkout updater does: download, verify the signature, prepare the release on the host, safety checks, back up your data, switch, restart and check health, finish. It shows how the update ended (succeeded, rolled back or refused, with the reason) and a log, survives a page reload and the service restart, and reports a helper that stopped without a result. `update_helper.py refresh-helper` brings an older pinned helper up to the current version so it writes this record.
- Housekeeping in Profile: runs left in "awaiting approval" on stories that are already done can be resolved by you, with the database backed up first and an audit trail. Hermes can read the findings and propose a fix on a free model (new Profile switch, off by default); only your approval acts. Update backups are managed by the updater here, so only stale approval waits are listed.
- A standard job envelope on every planned story (work kind, size, risk, estimate and a reason for the route), with the job and route tier derived by the server, standard tags, and refusal of an incomplete plan at approval. Human tasks can name the user they are assigned to. The Delegator role pack explains when a free route is safe and when to escalate to a foundation model.
- Tags may contain a colon.

## [0.3.7] - 2026-10-15

### Fixed
- An update is no longer blocked by approval waits that nobody can decide. A run left in "awaiting approval" on a story that is already done or failed (a later run completed it) was counted as a pending human decision forever, so the Updates panel and the helper refused to install. Only waits on stories that are still open, or on no story, block an update now.

## [0.3.6] - 2026-10-15

### Added
- Opt-in sharing of the OpenRouter key saved in Profile with Hermes and OpenClaw, so it is not typed into each agent. Off by default, one operator per installation, saved key wins over the agent's own. The key is supplied only in the environment of Hermes and OpenClaw runs, scrubbed from anything they print, and never given to Claude Code, Codex or Grok. Paid models still follow the dispatch policy. Turning it off or removing the key stops it at once. See `docs/configuration/saved-openrouter-key.md`.

## [0.3.5] - 2026-10-14

### Fixed
- The one-confirmation update no longer stops half way when the page is reloaded or left. Staging builds the runtime on the host, which takes minutes on a Raspberry Pi; the panel now keeps the update you confirmed for this tab (30 minutes, that version only), shows the host's staging phase, and carries on to the install when you return. The server still drain-checks before anything is stopped.
- A staging run that fails on the host is reported at once with its reason, instead of the panel waiting ten minutes.
- The release notes footer no longer tells you to paste a digest on a host that verifies the release signature.

## [0.3.4] - 2026-10-14

### Fixed
- The Updates panel no longer offers an older staged version as an install. Only a newer package is listed under Available; older ones are listed as kept for rollback, and the Rollback button is the way back. The Rollback button is no longer stretched across the panel.

## [0.3.3] - 2026-10-14

### Fixed
- The Updates panel works on a host installed with the bootstrap. The service unit it wrote never set `MAC_CONTROL_UPDATE_ROOT`, so the panel said "no update root is configured" and offered only manual steps. The unit now sets it. A host installed earlier adds a one-line systemd drop-in once; the steps are in `docs/install/updates-rollback-recovery.md`.

## [0.3.2] - 2026-10-14

### Added
- One-confirmation updates on a host that trusts the release signature: Check for updates, then **Update to X.Y.Z**. The release's SSH signature is verified against the release key pinned on the host, so no digest is typed; the install still drains work, takes a data snapshot, checks health and rolls back by itself. A host that still pins a digest keeps the two-step flow and the panel says how to switch.
- `update_helper.py enable-signed-updates --fingerprint SHA256:...` switches an existing host to signature trust after you name the key. The release package now ships the public release key, and the bootstrap switches a new install automatically when the key matches the fingerprint in the script.

### Changed
- The Updates panel is easier to read: clearer spacing and headings, and the work that must finish first is shown before you confirm.

### Fixed
- The MCP page no longer shows a red "list failed (exit 127)" for an agent whose command is not on this host. It shows a quiet "Not available on this host" note. A command that runs and fails is still reported as a failure.

## [0.3.1] - 2026-10-14

### Added
- First production release with signed installer manifests and a committed public verification key for both products.
- Project consultant conversation in a glass panel below the project brief controls. Refine goals, phases, stories, scope, definitions of done and dependencies, then review an editable brief before submitting it to Hermes coordination. Existing planning and execution approvals remain required.
- Profile AI defaults start new consultant chats, agent chats, task forms and project planning with Hermes and OpenRouter free. Installed membership CLI/model routes are configurable, with settings links and help guidance. Existing conversations and approved routes retain their choices.

### Fixed
- OAuth setup uses installation-specific paths and explicit host origins; shared client JSON no longer imports unrelated callbacks. Generic examples and private-address disclosure keep personal endpoints out of standard setup.
- Wizard links missing agents to runtime installers and explains install, native configuration and readiness refresh. Saved OpenRouter keys no longer trigger another entry form; spending checks remain available.
- Installer helper status resumes after navigation, retries temporary failures, updates every three seconds while active, and shows its log below the matching runtime's buttons. Completed logs remain available.
- Raspberry Pi wizard prerequisites match the packaged Python 3.11 runtime.


## [0.3.0] - 2026-10-13

- Fixed Python 3.11 project-planning syntax that blocked Pi package installation. RCD CI and package syntax validation now use the pinned Python runtime.

- Agent tools recognizes existing native installs, shows current versions and offers verified upgrades. Claude Code pin updated to2.1.299 and Hermes to0.22.0.

- Project Model lock stops failed tasks without automatic retries or equivalent-model failover; default behavior retains reviewed alternatives. Clean Mac/Pi OS install instructions are included.

### Added
- Matching lower-cost planning tiers, operator-reviewed paused-project retiering and repair of explicitly
  incomplete read-only story assignments, preserving scope and execution gates.
- Header version and commit tags remain visible on small screens; release footer information matches
  across products with product/owner, environment, API/web commits and modified status.
- Operator-confirmed managed installers for Claude Code, Codex CLI, Grok Build, Hermes and OpenClaw,
  with pinned downloads, update/remove/rollback, clean install environments and platform privilege restrictions.
- Agent roles with one assignable Delegator, generic starter guidance, managed instruction-block previews,
  private backups, rollback and interrupted-assignment recovery. In-progress pipelines keep their approved
  Delegator and model; a changed assignment requires new coordination review.
- OpenRouter/Hermes free-first setup guidance, platform worker choices and native membership prerequisites.
  Free-only planning can use a reviewed free Delegator route without a subscription CLI. Membership access,
  provider API charges and Google credit eligibility are explained separately.
- Grok Build is a supported agent, next to Claude Code, Codex, Hermes and OpenClaw: tasks, chat, project story
  agent and approved fallback, on an eligible Grok membership only (the CLI has no dollar cap, so an API route is
  refused). It has a native Linux arm64 build, verified in Lima; Raspberry Pi hardware remains untested. Runs are confined: telemetry and
  trace upload off, a filesystem sandbox, git push and merge denied. xAI prices are in the price catalog and
  the price checker reads docs.x.ai. See `docs/configuration/grok.md`. Not run against a signed-in account.
- Operator-only Agent tools panel for pinned per-user installation, update, removal and rollback of Claude Code, Codex CLI, OpenClaw and Hermes on Linux arm64. Confirmation shows sources, commands, disk and memory. System packages remain manual and sign-in is never automated. Install/remove and version checks were exercised in an Ubuntu arm64 Lima VM; Raspberry Pi hardware, Mac installers and Grok installation remain unverified or pending. See `docs/install/agent-tools.md`.

### Changed
- RCD works with any mix of agents installed. Setup readiness needs any one subscription CLI and any one of
  Hermes or OpenClaw instead of all of them, a new project story starts on an agent that is installed, and the
  story agent picker marks agents that are not installed. A test runs every one of the 32 combinations.

## [0.2.0] - 2026-10-13

RCD reaches the 0.2 feature level it shares with MCD. These were built and tested against the MCD
code base on a Mac; nothing in this release was tested on Raspberry Pi hardware.

### Added
- Branch-scoped agent git access: an operator can grant one approved project's stories permission to
  commit and push to one named branch of an allowlisted repository, through operator-owned hooks and a
  credential helper outside every repository. Without a grant agents still cannot commit or push.
- Subscription limits: when Claude Code or Codex stops on a usage limit RCD shows one calm notice with
  the time it lifts, moves stories that meet the limit to an approved alternate of the same grade, and
  offers one button to send waiting stories across until the limit lifts. Hermes can report the status
  in Discord, and change the routing when the operator enabled it in Profile.
- Shared project context is smaller and cheaper without losing anything: long handoffs become digests
  that point to a complete ledger file, the stable part of the prompt comes first so a provider's prompt
  cache can reuse it, and the story's own text comes last. The size of each prompt is recorded.
- Failure mining: Hermes can answer "what has been failing and why?" in Discord from failed runs
  classified by cause, with counts by agent, model and project, repeated errors and the cards still
  Failed. Read only, redacted and bounded, behind its own switch in Profile.
- Close project: ends a project that will not be finished, with a reason kept in its ledger. It shows as
  Closed, never Complete, and its failed tasks can be removed from the board.
- Failed project cards that another card already carries, and duplicates, can be deleted.
- The GitHub settings pick repositories from a checklist loaded from the account and report which
  repository failed and why.
- Tasks list has a Model column with a condensed model name.
- Price catalog (`apps/api/pricing_catalog.json`) with the published prices of the recent models of each
  platform, and `scripts/pricing/check.py` to compare it with the providers' pages, find models used
  without a price and add them. Models ending in `:free` cost 0. A model used without a recorded price is
  named next to the unpriced count; runs that used no model are not usage records.
- Release flow: release notes generated from this changelog, `scripts/release/publish-release.sh` (which
  scans the released commits with gitleaks and refuses on a finding) and the standard footer with a
  modified marker, product and owner. See `docs/development/release-flow.md`.

### Fixed
- A chat message sent just after the service started could be failed with "service restarted" by the first
  recovery pass. Recovery now fails only turns left by a previous process.
- Combining accepted prerequisite work into a parallel story no longer needs git 2.45; it works on the
  older git that Raspberry Pi OS and Ubuntu 24.04 ship, and a conflict returns the workspace to where it began.
- An unreaped runner (a zombie) no longer makes every operator request "could not be verified" on Linux.

### Changed
- The application updater API moved to `/api/app-updates`, so it no longer collides with the
  collector's `/api/updates`.
- Claude Code stories may use web search and fetch without any shell, credential or publish permission.

[0.3.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.0
[Unreleased]: https://github.com/gptkiosk/rbp-control-dashboard/compare/v0.6.6...HEAD
[0.6.6]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.6
[0.6.5]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.5
[0.6.4]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.4
[0.6.3]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.3
[0.6.2]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.2
[0.6.1]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.1
[0.6.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.0
[0.5.5]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.5
[0.5.4]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.4
[0.5.3]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.3
[0.5.2]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.2
[0.5.1]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.1
[0.5.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.0
[0.4.8]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.8
[0.4.7]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.7
[0.4.6]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.6
[0.4.5]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.5
[0.4.4]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.4
[0.4.3]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.3
[0.4.2]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.2
[0.4.1]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.1
[0.4.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.0
[0.3.7]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.7
[0.3.6]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.6
[0.3.5]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.5
[0.3.4]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.4
[0.3.3]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.3
[0.3.2]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.2
[0.2.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.2.0

## Before versioned releases

### Documentation and community staging — 2026-10-12

- Published MIT license with preserved MCD attribution, operator/developer docs and public collaboration configuration.
- Application source deliberately held for fixes, verification and explicit operator sign-off.
- Recorded Linux ARM64 UI preview as temporary test evidence, without claiming Pi hardware or live-provider certification.

[0.3.1]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.1
