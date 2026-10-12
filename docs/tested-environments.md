# Tested environments and evidence limits

| Environment | Verified in this audit | Not established |
|---|---|---|
| Ubuntu 24.04 ARM64 in temporary Lima VM, 4 CPU / 4 GiB / 20 GiB | Python lockfile dependencies installed; Node22 frontend typecheck/build passed; isolated backend /healthz and Projects UI reachable | Physical Pi/Pi OS compatibility, live runtime/provider conformance, end-to-end project execution, production security sign-off |
| Mac development host | MCD reference product and RCD local source preparation | This does not certify RCD as a Mac production install or a Pi release |
| Raspberry Pi 4/5, 64-bit Pi OS | Intended target only | No real hardware certification or published Pi memory/performance evidence |

The live UI preview uses fresh separate state, no provider/Google/Discord/GitHub credentials, and disabled collector/dispatcher/alerts. The public docs deliberately do not embed the operator’s VM identity, local username, home path, private tailnet address or preview endpoint.

Lima and its preview are temporary. Retire after app testing, explicit operator sign-off and public publication, preserving source and receipts outside the guest. Their later absence is normal; recreate only for requested further testing.

Historical agent reports and completed board cards are evidence records, not new measurements. Label fixture/stub, VM, live-provider and physical-hardware results separately and name the source revision.
