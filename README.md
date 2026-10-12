# Raspberry Pi Control Dashboard (RCD)

RCD is the Linux/Raspberry Pi port of [Mac Control Dashboard (MCD)](https://github.com/gptkiosk/mac-control-dashboard). It is a separate product and repository; MCD project 2 recorded its planning and implementation work.

**Current public repository: MIT license, documentation and collaboration setup only. Application source is held for fixes, validation and explicit operator sign-off.** A completed MCD project does not certify a production-ready Pi release. Do not treat this repository as an installable app yet. No production support, upstream development, security fixes or PR review is promised. Personal/commercial use and independent forks are welcome under [MIT](LICENSE).

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
