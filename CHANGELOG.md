# Changelog

All notable changes to Raspberry Pi Control Dashboard (RCD) are listed here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). RCD and the Mac Control Dashboard (MCD) share
major.minor, so a feature level means the same in both. Release notes on GitHub are generated from
the section of the version being released, and a release cannot be built without one.

Internal operator notes, private hostnames and personal identifiers are omitted by policy.

## [Unreleased]

## [0.3.0] - 2026-10-13

### Added
- Grok Build is a supported agent, next to Claude Code, Codex, Hermes and OpenClaw: tasks, chat, project story
  agent and approved fallback, on a SuperGrok subscription only (the CLI has no dollar cap, so an API route is
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
[Unreleased]: https://github.com/gptkiosk/rbp-control-dashboard/compare/v0.3.0...HEAD
[0.2.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.2.0

## Before versioned releases

### Documentation and community staging — 2026-10-12

- Published MIT license with preserved MCD attribution, operator/developer docs and public collaboration configuration.
- Application source deliberately held for fixes, verification and explicit operator sign-off.
- Recorded Linux ARM64 UI preview as temporary test evidence, without claiming Pi hardware or live-provider certification.
