# RCD documentation

The public RCD repository currently contains documentation, license and community configuration. Application source publication awaits explicit operator sign-off. These pages describe the verified prototype, its intended workflow and the boundaries still under review.

| Topic | Guide |
|---|---|
| Availability and setup | [Getting started](getting-started.md) |
| Main menus, projects, tasks and shared memory | [Features](features.md) |
| Configuration, credentials and ops reports | [Configuration](configuration.md) |
| OpenClaw, Hermes and lightweight runtimes | [Agents and runtime status](agents.md) |
| Tested systems and what results mean | [Tested environments](tested-environments.md) |
| Release gates and source publication | [Readiness](release/readiness.md) |
| Reachable preview and temporary VM lifecycle | [UI testing](development/ui-testing.md) |
| Agent-managed collaboration | [Agent workflow](development/agent-workflow.md) |
| Standing rules agents must not undo (parity, bounded prompts, setup, models and failover) | [Engineering rules](development/engineering-rules.md) |
| How a release reaches users (changelog, tag, signed package, verification, publishing, updates) | [Release and update pipeline](development/distribution.md) |
| What an update keeps, replaces and never touches | [What survives an update](configuration/upgrades-and-your-data.md) |
| Model profiles: facts, observed numbers and notes | [Model profiles](configuration/model-profiles.md) |
| How well the coordinator plans: scores, edits and outcomes | [Coordinator scorecard](configuration/coordinator-scorecard.md) |
| Why a service is flagged, and run, restart or stop it | [Service actions](configuration/service-actions.md) |
| Reporting a bug from the header, GitHub moderation and tasks | [Bug reports](configuration/bug-reports.md) |
| From no repository to one set up for the project | [Repository bootstrap](configuration/repository-bootstrap.md) |

The [MCD docs](https://github.com/gptkiosk/mac-control-dashboard/tree/main/docs) explain the shared Mac reference workflows. Mac LaunchAgents, Mac health probes and subscription apps are not Raspberry Pi deployment instructions. RCD's wiki indexes these versioned pages; repository docs are authoritative.

- [Clean Mac and Raspberry Pi OS0.3.1 installation](install/clean-os-0.3.1.md)

- [Project consultant and AI defaults (0.3.1)](project-consultant.md)

- [Model recovery and bootstrap](configuration/model-recovery.md) — route choices, telemetry, retry boundaries and built-in setup plans.
- [Shared-feature parity audit](development/parity-audit-0.6.38.md) — inventory, repaired differences and platform limits.

- [Coordinator pipeline, selected context and channel contract](configuration/coordinator-pipeline.md)
