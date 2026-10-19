# Coordinator scorecard

## Purpose

Explains how RCD measures how well the coordinator plans, so you can tell whether a change to the coordinator's wording, standards or model
choice made plans better or worse. It scores the plan, never the model, and it uses records the app already keeps.

## Screenshots

Pending capture: `telemetry-coordinator-scorecard.png`.

## Controls

Open **Telemetry** and find **Coordinator scorecard**. Each time a plan revision is approved, RCD:

1. **Scores the plan** with fixed checks, each pass or fail with a plain detail: every node fits the plan schema; every story has the standard
   envelope; estimates fit the size class (within a factor of three); acceptance criteria can be checked; each story has a bounded scope;
   dependencies exist and do not loop; every agent route has a reason; nothing is too big to run (no `xl` stories); phases are not empty;
   high-risk work has a human or review story; and the plan respects the standards' risk floors and routes. The score is the share of
   applicable checks that passed.
2. **Compares it with what the coordinator returned**: how many nodes a person added, removed or changed before approving. Moving a node on
   the map does not count as an edit.
3. **Records who planned it** (the planner and Hermes, the fixed Coordinator) and **which coordinator wording was in effect**: the shipped version (`v2`), `+custom`
   when you use your own copies, and a short hash. Plans made under different wording can be compared.

The page shows plan score by planner and by wording (with edits per plan and first-pass completion), and a table of each scored plan behind a
fold, including the checks that failed. **First pass** and **actual over estimate** come from the work the plan led to, so they fill in as
stories finish.

## Fixed briefs

Eight general briefs ship with RCD (a paid checkout, a safe database rename, shipping a desktop app, hardening sign-in, a how-to guide, a flaky
test, a major dependency upgrade, a report page). Each says what a good plan must contain, such as the standards areas it touches, the kinds
of work it needs, a review for high-risk work and no free-only route for high-risk stories. To try a model or a wording change on them, run the
brief through the planner you want and send the plan to the scorer: it gives the same checks as the live scorecard and stores nothing.

## Settings involved

- Operator API: `GET /api/coordinator/scorecard?days=`, `GET /api/coordinator/briefs`, `POST /api/coordinator/score` with `nodes` and an optional
  `brief_id`. Agents get 403.
- The scorecard is part of each approved plan's record; a problem scoring a plan never blocks planning or approval.
- The coordinator wording version is `packs/roles/delegator/VERSION`; your own copies are described in
  [What survives an update](upgrades-and-your-data.md).
