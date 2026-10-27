# Failure mining: what failed, why and how often

Hermes (and the operator) can read failed runs without opening each one. The views are **read only,
redacted and bounded**; nothing is retried, rerouted, approved or changed from them.

## What you get

- **Summary** over a window (default 24 hours, up to 14 days): failed runs by cause, by agent and model,
  by project, the errors that repeat most, and the cards that are still Failed with their last cause.
- **Recent failures**, newest first, each with its project and story, route, attempt, a short error and a
  short handoff excerpt. Narrow by `category`, `agent` or `project_id`.
- **One run**: the error, a longer handoff excerpt, the tail of its readable log (30 lines), the other
  attempts on the same card, notes RCD recorded, and its route (price class, any reroute, context size).

## Causes

`price_gate` (PRICE_UNKNOWN, ROUTE_POLICY, FREE_ONLY from older runs, BUDGET_*, ROUTE_UNPINNED), `subscription_limit`,
`hook_rejection` (pre-commit, commit-msg, pre-push), `permission` (a command needed approval),
`gateway` (OpenClaw gateway or provider timeout), `incomplete_handoff` (the agent said the work is
unfinished), `test_failure`, `cancelled`, `interrupted` (cut off by a restart), `timeout`, `other`.
When RCD only says the agent reported unfinished work, the cause is read from the handoff, so a story
blocked by a permission prompt is counted as `permission`, not as a generic incomplete handoff.

## Safety

- Credentials (GitHub and OpenRouter tokens, bearer tokens, API keys, JWTs, AWS keys), e-mail addresses,
  private and tailnet addresses, host names, account home paths and long numeric ids are removed, and
  every field is cut to a fixed length.
- Only the readable `run-N.log` summary is ever read. The raw stream log, which can hold file contents,
  never is.
- The text is output of agents and tools. It is marked untrusted, and Hermes is told to read it as
  evidence and never to follow instructions found in it.

## Using it

- Operator API: `GET /api/failures/summary?hours=`, `GET /api/failures?hours=&limit=&category=&agent=&project_id=`,
  `GET /api/failures/<run id>` (signed-in operator only; agent processes are refused as for every operator route).
- Hermes on Discord: ask "what has been failing?" or "why did run 125 fail?". It needs **Allow Hermes to
  read failed runs for me in Discord** in RCD Profile, and a paired Discord account. RCD checks the Discord
  user and channel the gateway supplies against the paired profile.

Measured on this installation's history (14 days): 119 failed runs, 38% subscription limits, 23% the price
gate, 29% handoffs that reported unfinished work, with no credentials or addresses in the output.
