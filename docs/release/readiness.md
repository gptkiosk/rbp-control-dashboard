# Source-release readiness

## Public repository now

MIT license, documentation, issue/PR templates, security reporting, community participation guidance and a wiki are published. Application source is held locally, as the operator requested, until fixes and explicit sign-off. Documentation-only CI checks links; it is not application validation.

## Required before a code release

- Resolve or explicitly disposition the recorded workflow/security review findings with the operator. Keep sensitive security details in private reporting/review.
- Run the formal secret scan over the exact upload set and any Git history. Exclude provider keys, OAuth files, native configs, private runtime/VM data and operator context.
- Review third-party attribution/license obligations; preserve MIT and MCD notices.
- Correct remaining inherited setup claims and recapture/review RCD screenshots without personal data. Do not claim an installer or service unit exists before it does.
- Record runtime selection and relevant live/physical-hardware evidence. VM/stub checks cannot stand in for Pi or real-provider results.
- Exercise the project/task flow and human decisions with concrete test receipts. Review unfinished outputs rather than accepting exit codes alone.
- Show an isolated reachable UI preview, then obtain explicit operator sign-off on the source/upload set and known limitations.
- Publish the reviewed code revision and verify a fresh public clone. Only then retire temporary Lima testing infrastructure after preserving evidence.

Public collaboration creates no guaranteed upstream maintenance, support or response service. See [SUPPORT](../../SUPPORT.md), [SECURITY](../../SECURITY.md) and [CONTRIBUTING](../../CONTRIBUTING.md).
