# Jobs and telemetry

## Purpose

Explains the Telemetry page: how work is going across jobs and stories, who it is assigned to (a person or an agent), the agent and
model that ran it, how long it took and what it cost. It supports decisions about which models to use for which kind of work.

## Screenshots

Pending capture: `telemetry-overview.png`.

## Controls

Open **Telemetry** in the sidebar. Everything is read-only and computed from the tasks, runs and projects the app already keeps, so
there is nothing extra to maintain.

- **At a glance:** the page leads with the tiles, then charts: donuts for workload by status and by route, stacked bars for work by assignee, by job, by model and by kind, plus completed per week and median time per kind. Hover a bar or a legend row for the numbers behind it. The full tables (jobs, agents and models, kinds of work) are folded away; open one when you want to drill in.
- **Period and filters** (job, property, kind, risk, size, route, assigned to, agent, model) narrow every number and chart on the page at once.
- **Tiles:** unassigned (open work nobody has), in progress (queued or running), waiting for you (needs a decision), completed in the
  period, estimates missing (open work without one) and failed.
- **Workload by status, work by assignee, completed per week, median time per kind.** Assignee is a person for a human task and an
  agent for an agent task.
- **Jobs:** one row per approved plan revision (`pNrR`) with its stories, done, open and failed, estimate against actual time, cost and
  API-equivalent cost.
- **Agents and models:** every run is recorded with its agent, the model requested and the model that actually served it (the reported
  model, which differs after a fallback), and the route (free, subscription, api, human). The table shows runs, success rate, median
  time, tokens, reported cost, API-equivalent cost and how many runs were served by a different model than requested.
- **By kind of work:** time, how often a story finished on the first attempt, and actual time over the estimate.
- **Latest activity.**

**Cost is shown two ways, kept apart.** *Reported cost* is what the agent reported. *API-equivalent* is an estimate from the price
catalog, the figure a flat membership is compared against. Free models count as $0, and usage that cannot be priced is counted and
shown, never guessed. Neither is an invoice.

Work made before the standard job envelope has no kind, size or risk and appears as untagged; its route is worked out from the agent
and model.

## Settings involved

- Reads the `card`, `run`, `project` and `project_task` tables and the price catalog; stores nothing of its own.
- Operator API: `GET /api/telemetry?days=&job=&kind=&risk=&size=&tier=&assignee=&agent=&model=` (signed-in operator only).

## Troubleshooting

- A model shows up twice: the same model served runs under different routes (for example as a free and a subscription route). Filter by
  route.
- Cost is zero but tokens are not: the model is free, or the agent reports no cost and the model is not in the price catalog (see
  [pricing catalog](pricing-catalog.md)).
- Estimates missing is high: the standard envelope asks planners for an estimate on every story, so it falls as planned work replaces
  older tasks.

## Related pages

- [The standard job envelope](job-envelope.md)
- [Pricing catalog](pricing-catalog.md)
- [Failure mining](failure-mining.md)
