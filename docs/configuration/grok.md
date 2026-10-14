# Grok Build

Grok Build is xAI's terminal coding agent (`grok`, Apache-2.0 client, closed models). RCD runs it like Claude
Code or Codex: as a task or chat agent, as a project story agent, and as an approved fallback route.

## Set it up

1. Open Settings → Agent tools and install Grok Build. The managed installer pins the vendor's
   binary version, size and SHA-256 for Apple Silicon and Linux arm64 and shows a confirmation plan.
   The vendor's manual installer is available separately at https://docs.x.ai/build/overview.
2. Sign in on the host: `grok login`, or `grok login --device-code` on a machine without a browser. RCD never
   sees the sign-in. `XAI_API_KEY` is an alternative, but see Billing below.
3. Agents, then Billing & rates: set Grok Build to **Subscription** and save. Until then RCD refuses to start
   it. Setting the path is only needed when `grok` is not in `~/.grok/bin`: `MAC_CONTROL_GROK_PATH`.

## Billing: subscription only

The Grok CLI has no dollar cap, so RCD cannot bound an API-billed run and refuses it
(`BUDGET_UNENFORCED`). An eligible Grok membership (documented by xAI as SuperGrok or X Premium Plus) has subscription limits, so RCD classifies a Grok route as a
subscription route once you save that account. Saving it is also your acceptance of the data notice below.

Prices come from the price catalog (`grok-4.7`, `grok-4.6`, `grok-4.5`, `grok-build-0.1`, from
docs.x.ai/docs/models, long-context tier above 200k prompt tokens). `scripts/pricing/check.py --source xai`
compares them with the page. A run's own reported cost wins when the CLI reports one.

## What it sends, and how RCD runs it

Grok sends your prompt and the files it reads to xAI. Third-party reports from July 2026 said an earlier version
also uploaded repository contents even with data sharing off, and that xAI changed a server setting on the
same day; RCD has not verified either claim. So every run RCD starts is confined:

- telemetry, anonymous analytics and **trace upload are switched off** through the run's environment
  (`GROK_TELEMETRY_ENABLED`, `GROK_TELEMETRY_TRACE_UPLOAD`, `GROK_TELEMETRY_MIXPANEL_ENABLED` set to false);
- a filesystem sandbox: `--sandbox read-only` for a read task and `--sandbox workspace` (the working directory,
  `/tmp` and `~/.grok`) for an edit task. It is enforced by Landlock on Linux and Seatbelt on macOS;
- `git push`, `git merge` and `gh pr merge` are denied, except the one exact push an operator grant allows;
- `--permission-mode plan` for a read task and `acceptEdits` for an edit task. `--always-approve` is never used.

Use Grok only on work you are willing to share with xAI.

## What is and is not supported

| | Grok Build |
|---|---|
| Task, chat, project story agent, approved fallback | yes |
| Operator-granted git push to a project branch | yes (same rules as Claude Code) |
| Project planner (Hermes, Claude Code or Codex plan; auto assignment by planning bias) | no: only chosen by hand |
| Usage and cost | from the runs RCD dispatches (tokens and the CLI's reported cost); the CLI's own session history is not read |
| Subscription limit notice and reroute | no (the CLI's limit wording is not known yet) |
| MCP server management from RCD | no |

## Verification status

Built against the open source (`xai-org/grok-build`, headless output reducer) and the `grok` 1.0.52 binary on an
aarch64 Linux VM (`--help`, `models`, the signed-out error line). **Not run against a signed-in account**, so no
real task output was recorded: the parser is tested with lines shaped like the source's
`streaming-messages-json` frames, which are Claude Code's stream-json shape. The first real run is the real test.

## Any mix of agents

RCD works with any mix of agents installed: Claude Code, Codex, Grok Build, Hermes, OpenClaw, any subset
(`tests/test_agent_mix.py` runs all 32). Readiness, defaults and pickers never assume a particular agent. A task
for an agent that is not installed fails with a reason; a project can only use installed agents.
