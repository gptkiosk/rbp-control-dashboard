# Agent runtimes (RCD)

RCD dispatches each story to one agent runtime through a common adapter interface, `rcd.adapter.v1`.
This directory explains that interface and how to work with it.

| Page | Read it when |
| --- | --- |
| [Adapter contract](adapter-contract.md) | You need the operations, messages, status states, idempotency keys or error codes. |
| [Adding a runtime](adding-a-runtime.md) | You are writing a new adapter, or wiring one into the dispatcher or conformance suite. |
| [Runtime evaluation](runtime-evaluation.md) | You want the ZeroClaw versus PicoClaw evidence, what is still missing, and the status of the runtime decision. |
| [Timeout, cancel, retry and approval](lifecycle-semantics.md) | You need to know what happens when a run is slow, stopped, failed, paused for a human, or restarted. |

## Sources of truth

These pages summarise, and must agree with, the following files. If they disagree, the source wins and
the page should be fixed.

| Source | Role |
| --- | --- |
| `docs/port/adapter-contract.md` | Normative design for `rcd.adapter.v1` (status: design, proposed). |
| `apps/api/adapter_contract.py` | Python interface, state machine (`TRANSITIONS`), error table (`ERRORS`). |
| `apps/api/adapter_schemas/` | JSON Schema bundle and sample payloads. |
| `apps/api/dispatcher.py`, `apps/api/legacy_adapters.py` | What the running dispatcher does today. |
| `docs/port/S3-*-handoff.md` | Per-story implementation notes and open risks. |
| `tests/adapter_conformance/` | Conformance suite that any runtime must pass. |

## Current status

- The contract is in place. Claude, Codex, Hermes and OpenClaw run through the legacy adapter path.
- ZeroClaw and PicoClaw have adapter code under `integrations/`. Neither is registered in the API dispatcher.
- No Pi agent runtime has been selected. The decision is a human gate (`S2_decide_runtime`).
- No measured Pi memory or reliability figures exist yet. See [runtime evaluation](runtime-evaluation.md).
