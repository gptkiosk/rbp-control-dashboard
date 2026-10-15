# Model profiles

## Purpose

Explains the **Models** section of the Telemetry page: what each model can do, how it has actually done in your own runs, and what people
have noted about it. It helps you and the coordinator choose a model for a kind of work: when a free model is enough and when a
paid foundation model is justified. It never changes a route by itself.

## Screenshots

Pending capture: `telemetry-models.png`.

## Controls

Open **Telemetry** and scroll to **Models**. The three kinds of information are kept apart:

- **Facts**: from your price catalog and from OpenRouter's public model list: free or paid, context size, whether it supports tools,
  structured output and reasoning, the input types it accepts, and its price.
- **Observed**: computed from the work you have already run (nothing extra is stored): runs, success rate, median time, tokens, cost,
  how often a different model served a run than the one requested, and the same by kind of work. A model with fewer than 10 runs of a
  kind is shown as **unproven** for it. That is the honest starting point for any model you have not tried.
- **Notes**: short text that people add, each with a **source** and a **date**. A note older than 90 days is marked stale. RCD ships no
  opinions about which model is better at what, because those claims age quickly and cannot be checked from here.

**Refresh free models** reads OpenRouter's public list (one HTTPS address, no key, no redirects, a size limit) and stores a dated
snapshot. It then shows what is new and free, what the catalog lists as free that is no longer listed as free, and what changed since the
last read (context, tool support, price). Nothing else changes: adopting or dropping a model is still a normal reviewed change to the price
catalog. Text from the list is shortened and cleaned before it is stored.

The glance chart shows observed success by model. The full profile table and the notes are behind folds.

## The weekly model watch

Switch it on with `MAC_CONTROL_MODEL_WATCH_ENABLED=true` (off by default, because it reads the network on a schedule). Once a week
(`MAC_CONTROL_MODEL_WATCH_INTERVAL_DAYS`, 1 to 30) it reads OpenRouter's public list, compares it with your price catalog and the last read, and, only
when something is new since the last card, leaves **one Backlog card** for a person with the sources and exactly what differs:

- **Check first**: models the catalog lists as free that are no longer listed as free. A model priced at zero that is no longer free can spend money,
  so do not route work to it until the catalog is reviewed.
- **Listed as free but not in the catalog**, with their context and tool support.
- **Changed since the last read** (context, tools, price).

The card says plainly what to do and not to do: nothing was changed; adopting or dropping a model is a normal reviewed change to the price catalog;
try a new model on low-risk work first and add a note with where it came from. A failed read is recorded and tried again next time, never reported as
a change. The Models section shows whether the watch is on, when it last ran and what it found, and links the card. It uses the same fixed read as
Refresh, so `MAC_CONTROL_MODEL_REFRESH_ENABLED=false` stops it too.

## How the coordinator uses it

- **Planner guidance.** When a plan is requested, the planner is given a compact paragraph for the models it may choose: free or paid,
  context, tool support, and what has actually happened here by kind of work (success rate and how many runs), with **unproven**
  stated plainly. It is advice, not authorization: the free-only gate, reviewed routes, the standards' risk floors and your approvals
  still decide. The paragraph is added after your coordinator text is filled in, so your own `plan.txt` copy keeps working.
- **Route advice before you submit.** The submit review shows non-blocking advice for each story's route: a model with a proven poor
  record for that kind of work (under half of at least 10 runs), a model that does not list tool use for work that edits files, and a
  model that is unproven for the kind when the story is medium or high risk. Nothing is refused here; it is a prompt to look again.

## Settings involved

- `MAC_CONTROL_MODEL_REFRESH_ENABLED` (default on). Off: the refresh action is refused and nothing is fetched.
- `MAC_CONTROL_MODEL_WATCH_ENABLED` (default off) and `MAC_CONTROL_MODEL_WATCH_INTERVAL_DAYS` (default 7): the weekly watch.
- Files in the data folder: `models/openrouter.json` (the last snapshot) and `models/notes.json` (your notes). Updates keep both; see
  [What survives an update](upgrades-and-your-data.md).
- Operator API: `GET /api/models/profiles`, `POST /api/models/refresh` (needs `confirm: true`), `POST /api/models/notes`,
  `DELETE /api/models/notes/{id}`, `GET /api/models/advice?project_id=`, `POST /api/models/watch/run` (runs the watch now). Agents get 403.
