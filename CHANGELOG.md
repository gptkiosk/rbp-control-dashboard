# Changelog

All notable changes to Raspberry Pi Control Dashboard (RCD) are listed here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). RCD and the Mac Control Dashboard (MCD) share
major.minor, so a feature level means the same in both. Release notes on GitHub are generated from
the section of the version being released, and a release cannot be built without one.

Internal operator notes, private hostnames and personal identifiers are omitted by policy.

## [Unreleased]

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
[Unreleased]: https://github.com/gptkiosk/rbp-control-dashboard/compare/v0.4.4...HEAD
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
