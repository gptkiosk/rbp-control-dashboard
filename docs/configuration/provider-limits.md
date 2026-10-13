# Subscription limits: when they lift and what moves

When a Claude Code or Codex run stops on a usage or session limit, RCD records one **limit
event** for that provider, reads the time it lifts from the CLI's own message, and shows a
single notice at the top of every page. Nothing is announced per story.

## What RCD does on its own

- Each project story that meets the limit hands itself to its approved alternate route and
  carries on with the same story (unchanged behaviour). The notice counts these.
- The failed run's error gains "Limit lifts about 4:00 PM", so the time is on the run too.
- The event ends when the time passes, when a later run on that provider succeeds, or, when
  the CLI gave no time, after six hours.

Recognised wording: Claude "resets 7:40pm (America/Los_Angeles)" and "resets 11am (...)", Codex
"try again at 10:03 PM." and "try again at Oct 13th, 2026 3:04 AM." A rate limit or HTTP 429 only
counts when it also says when to try again; otherwise it stays a short transient error.

## The one choice you have

**Send the waiting stories to the other subscription.** While the event lasts, a story that has not
started is claimed directly on the approved alternate route of the same grade, so no attempt is
wasted: Haiku to Luna, Sonnet to Terra, Opus to Sol. When the limit lifts, new stories go back to
their own route. Stories already moved stay where they are. The run's checkpoint records
`rerouted_from`.

Limits of the feature, by design:
- Only routes the approved project plan already lists are used. No new model, spend or route.
- Never to a provider that is itself limited; the story waits and the notice says so.
- Project stories only. Standalone cards show the lift time but are not moved.
- OpenClaw and Hermes stories are not affected; they have no subscription limit.

## API

- `GET /api/limits`: active events with `lift_at`, `seconds_left`, `handoffs`, `rerouted`,
  `waiting`, `alternate`, `can_reroute`.
- `POST /api/limits/{claude|codex}/reroute` with `{"enabled": true|false}`.

## Through Hermes and Discord

The paired Discord account can ask Hermes for the status at any time (`limits`, read-only). Turning
the reroute on or off (`limits_reroute`) needs **Allow my Discord requests to change how work is
routed** in RCD Profile. RCD checks the Discord user and channel Hermes's gateway supplies against
the paired profile; the model cannot choose them. Approvals, dispatch, billing and credentials stay
in RCD.
