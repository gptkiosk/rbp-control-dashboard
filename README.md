# Raspberry Pi Control Dashboard (RCD)

## Functionality at a glance

A separate Linux/Raspberry Pi control dashboard for host monitoring, reviewed agent work, task/project planning, media workflows, and release/update management.

- Runtime: FastAPI and Vue with a Linux platform layer; local access is private by default. Provider/agent connections depend on the operator's installed tools and credentials.
- Connectivity: the same signed [pipeline-pack catalog](https://github.com/gptkiosk/dashboard-pipeline-packs) contract as MCD, with separate application state and host setup. upubhub packages are prepared for operator import, not automatically published by a pack.
- Acceptance limits: application source and release tooling are present; Linux VM checks do not establish physical Raspberry Pi or live-provider acceptance. ZeroClaw/PicoClaw remains experimental. See the release and support qualifications below.

RCD is the Linux/Raspberry Pi port of [Mac Control Dashboard (MCD)](https://github.com/gptkiosk/mac-control-dashboard). It is a separate product and repository; MCD project 2 recorded its planning and implementation work.

## Why use a project dashboard?

**Turn a brief into tracked work, task-matched models and documented handoffs.** Guided templates, bounded context, a Kanban record, media steps and remote previews help reduce repeated coordination across agents and coding apps.

**[Read the project-workflow brief](docs/project-workflow-value.md)** — benefits versus manual planning or a standalone coding harness, measured planning results, cost limits, and the next step for improving time estimates from actual project history.

**0.3.1 first production release:** the application source includes managed agent installers, assignable Delegator roles, reviewed project controls and verified release-update tooling. Signed installer assets are published through the product’s GitHub release workflow; see [release signature verification](packaging/release-signing.md). Linux arm64 VM checks do not certify Raspberry Pi hardware or live provider behavior. ZeroClaw/PicoClaw integration remains experimental. No production support, upstream development, security fixes or PR review is promised. Personal/commercial use and independent forks are welcome under [MIT](LICENSE).

The local prototype reuses the FastAPI/Vue workflow engine and adds a Linux platform layer and lightweight-runtime adapter work. Its UI has been built and served in a temporary Ubuntu 24.04 ARM64 Lima VM. Physical Raspberry Pi / Raspberry Pi OS validation, runtime selection, live conformance and release checks remain incomplete. See [release readiness](docs/release/readiness.md).

## Documentation

- [Documentation index](docs/README.md)
- [Getting started and present availability](docs/getting-started.md)
- [Features and workflows](docs/features.md)
- [Configuration and report folders](docs/configuration.md)
- [Agent/runtime status](docs/agents.md)
- [Tested environments and limits](docs/tested-environments.md)
- [UI testing and temporary previews](docs/development/ui-testing.md)
- [Hermes/OpenClaw contribution workflow](docs/development/agent-workflow.md)
- [MIT license](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md), [contributing](CONTRIBUTING.md), [security](SECURITY.md), [support](SUPPORT.md)

## Public interaction

[Issues](https://github.com/gptkiosk/rbp-control-dashboard/issues/new/choose), [pull requests](https://github.com/gptkiosk/rbp-control-dashboard/pulls), [Discussions](https://github.com/gptkiosk/rbp-control-dashboard/discussions) and the [wiki](https://github.com/gptkiosk/rbp-control-dashboard/wiki) are available for community interaction. Documentation contributions and release-readiness questions are welcome now; code contributions become possible when application sources are published. Do not post credentials or private security details.

## Install

Follow [clean Mac and Raspberry Pi installation](docs/install/clean-os-0.3.1.md).
