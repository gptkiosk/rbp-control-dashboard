# The standard job envelope: how planned work is tagged for filtering and telemetry

## Purpose

Explains the fields every story the coordinator plans must carry, how the server fills the rest, and what a plan needs before you can
approve it. This is the foundation for measuring jobs: time, cost, estimate accuracy and model choice by job, kind and route.

## Screenshots

Pending capture: `task-job-envelope.png`.

## Controls

**A job is one approved plan revision** (project N, revision R). Its stories are the job's work, and it appears on each story as the
tag `job:pNrR`.

Every story the coordinator plans carries:

| Field | Values | Set by |
|---|---|---|
| `work_kind` | research, plan, implement, review, test, docs, ops, triage | the planner |
| `size` | xs (about 15 min), s (45), m (120), l (300), xl (600) | the planner |
| `estimate_minutes` | a number the planner can defend from the size | the planner |
| `risk` | low, medium, high: how costly a wrong or failed result would be | the planner |
| `area` | a short lowercase component name (optional) | the planner |
| `route_reason` | one sentence: why this agent and model, and why a free route is or is not enough | the planner |
| `assignee_user` | for a human task, the approved user it is assigned to (an email or short name); empty = unassigned | the planner or you |
| `route_tier` | free, subscription, api or human | **the server**, from the agent and model that will actually run |
| job | `pNrR` | **the server**, from the approved revision |

**Who it is assigned to.** Work is assigned to a person or to an agent, never both. A human task names its user in `assignee_user`; an agent task is assigned through its agent and model (the telemetry records the agent, the model requested and the model that actually served each run). An agent task cannot carry an `assignee_user`.

**A plan is refused at approval** when any story lacks `work_kind`, `size`, `risk`, `estimate_minutes` or `route_reason`, and the
message names the stories and fields. Tasks you create by hand do not need an envelope; they show as untagged in telemetry, and you
can set the fields on any card.

Cards also get standard tags for filtering: `job:`, `kind:`, `size:`, `risk:`, `tier:` and `area:`. Tags may now contain a colon.
The card detail shows the envelope and "Why this route".

**How the planner chooses a route** (written into the Delegator role pack): prefer a free route when the story is read-only or easily
reversible, low risk, small in context, needs no secrets, and a failed attempt only costs a retry. Choose a subscription or other
foundation model when the work is high risk or security sensitive, hard to reverse, needs long context, or has already failed on free
routes. A paid API route is only chosen when the execution catalog marks it approved. The dispatch gate still enforces free-only
policy and price classes whatever the plan says.

## Settings involved

- Database: new nullable columns on `card` (`kind`, `size`, `risk`, `area`, `route_tier`, `route_reason`; migration 0018). Existing
  cards are untouched.
- API: the card create and update routes and Hermes draft tasks accept `kind`, `size`, `risk`, `area`, `route_reason`; `route_tier` is
  derived and returned.
- Plan nodes: `work_kind`, `size`, `risk`, `area`, `estimate_minutes`, `route_reason` (the node's `kind` stays phase or story).

## Troubleshooting

- "Every story needs a work kind, size, risk, estimate and route reason": open the project, add them to the stories named, and approve
  again. Plans made before this release need the fields added once.
- A card shows no envelope: it was made by hand or before this release.

## Related pages

- [Failure mining](failure-mining.md)
- [Pricing catalog](pricing-catalog.md)
- [Agent roles](agent-roles.md)
