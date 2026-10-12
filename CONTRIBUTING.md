# Contributing to RCD

This project welcomes independent forks, documentation improvements, bug reports and proposed changes under the [MIT license](LICENSE). Personal and commercial use are allowed subject to that license. Upstream development, support, response times, security fixes and PR review are not promised. Public collaboration is available; it does not create a maintenance commitment.

## Where to participate

- [Discussions](https://github.com/gptkiosk/rbp-control-dashboard/discussions): questions, ideas, usage tips and fork announcements.
- [Issues](https://github.com/gptkiosk/rbp-control-dashboard/issues/new/choose): reproducible bugs and concrete feature requests.
- [Pull requests](https://github.com/gptkiosk/rbp-control-dashboard/pulls): focused improvements with evidence and documentation.
- [Wiki](https://github.com/gptkiosk/rbp-control-dashboard/wiki): navigation and operator guidance; versioned docs in this repository are authoritative.
- [Private security reports](https://github.com/gptkiosk/rbp-control-dashboard/security/advisories/new): vulnerabilities only. Never disclose sensitive details in public issues, logs or PRs.

## Changes and review

Fork this repository, create a topic branch, and submit a focused pull request describing the problem, resulting behavior and verification. Check for an existing issue/PR first. Preserve attribution and third-party notices. Use synthetic examples and your own credentials; no private databases, native agent configs, OAuth files, VM identities or tokens belong in commits.

Read [AGENTS.md](AGENTS.md) for human and agent contribution rules and [agent workflow](docs/development/agent-workflow.md) for model assignments, scope and handoffs. A test passing or an agent saying “done” is proposed evidence; it does not replace the requested review.

For documentation-only changes run `python3 scripts/check-docs.py`. Where application sources are present, use Python 3.12 in an isolated venv with `apps/api/requirements.lock.txt`, then run API tests; use Node 22 and `npm ci`, `npm run type-check`, `npm test`, and `npm run build` in `apps/web`. Additional runtime-specific suites and limits are documented in the app source. Never run tests against production state or a live dispatching dashboard.

Any UI change must include a reachable isolated preview URL, how to start/stop it, the source revision and test data/limitations. See [UI testing](docs/development/ui-testing.md). Actual Pi hardware and live-provider tests require explicit environment access and spending authorization; VM or fixture results must be labelled.

PRs remain open for maintainer review after checks pass. CI does not merge, publish releases, dispatch agents, use provider keys or deploy. Questions and proposals may receive community replies, but users who need dependable maintenance should maintain their own fork.
