# Demo runbook: "Acme docs site with changelog"

This runbook takes you from a fresh checkout to a verified end-to-end run of the RCD workflow:
**create plan → review assignments → execute → interrupt (kill the API) → recover → timeout → cancel →
human decision → resume → finish with artifacts.** You do not need to have written any of it.

Everything runs against a **private RCD API** on a spare loopback port with a scratch data directory and
**offline stub agents**. It never touches the live service on port 8800, the real database, your agent
logins or any network.

> **Status of this runbook:** the fixtures, stubs and harness were written and reviewed against the API
> source but had **not been executed** when they were delivered (the authoring environment could not run
> Python). Treat your first `--mode execute` run as the first real test, and report failures with the
> evidence file (see [Troubleshooting](#troubleshooting)).

## 1. What the demo project is

A fictional "Acme CLI" docs site built by six stories in **three dependency levels**:

| Level | Story | Assignee | Model | Scenario |
|---|---|---|---|---|
| 1 | `S1_content` write the three docs pages | claude | `claude-sonnet-5-5` | normal |
| 1 | `S1_changelog_data` write `changelog.json` | openclaw | `openrouter/cohere/north-mini-code:free` | **slow (12 s): the API is killed here** |
| 2 | `S2_generator` write `build.py` | codex | `gpt-6.1-sol` | **hangs on first try: timeout** |
| 2 | `S2_checker` write `check_site.py` | openclaw | `openrouter/thinkingmachines/inkling:free` | **long first try: cancelled** |
| 2 | `S2_decide_theme` choose light/dark/auto | **human** | none | **operator decision** |
| 3 | `S3_build` build `site/` and check it | codex | `gpt-5.6-terra` | reads the decision from shared context |

`S3_build` is the only level-3 story and depends on all three level-2 stories. `S2_decide_theme` is the one human
story. Two stories use OpenRouter models. Dispatch mode is `sequential`, so MCD runs them one at a time in dependency order:
`S1_content, S1_changelog_data, S2_generator, S2_checker, S2_decide_theme, S3_build`.

Files:

| Path | Purpose |
|---|---|
| `demo/plan/project.json` | The project document: nine nodes (three phases, six stories) |
| `demo/fixtures/site/` | The real content, data, generator (`build.py`) and checker (`check_site.py`) the stubs write |
| `demo/stubs/agent_stub.py` | Offline stand-in for the claude, codex, hermes and openclaw CLIs |
| `demo/stubs/hermes_cli/` | Tiny fake package that lets MCD's own Hermes launcher shim wrap the stub |
| `demo/harness/run_demo.py` | The automation harness and JSON evidence writer |
| `demo/out/<timestamp>/` | Output of each run (git-ignored) |

The phase nodes `P1`–`P3` only group stories on the project map; only the six stories execute.

## 2. Prerequisites

- Python **3.11 or newer** and `git` on `PATH`.
- A virtual environment with the API dependencies. From the repo root:

  ```sh
  python3 -m venv demo/.venv
  demo/.venv/bin/pip install -r apps/api/requirements.lock.txt
  ```

- Port **8801** (or any free port above it). The harness picks one itself; it refuses 8800 and never
  evicts whatever owns an occupied port.
- About 4 minutes for `--mode execute` (most of it deliberate waits: a 12 s slow story, a 30 s timeout, a 25 s story that is cancelled).

Shorthand used below (run from the repo root):

```sh
PY=demo/.venv/bin/python
```

## 3. Step 0: validate the fixtures (no server)

```sh
$PY demo/harness/run_demo.py --mode validate
```

Expected: `V01` and `V02` pass; exit code 0. This checks the plan shape (≥6 stories, exactly 3 levels,
mixed assignees, a human story, ≥2 OpenRouter models), that no story text would be excluded from automatic
handoff, and that every fixture file the stubs copy exists. It needs only the standard library, so you can
run it with the system `python3`.

## 4. Step 1: rehearsal (private server, dispatcher off)

```sh
$PY demo/harness/run_demo.py --mode rehearsal --api-python $PY
```

Expected: `CP01`–`CP03` pass and `CP04`–`CP13` are reported as **skipped: needs the dispatcher**; exit code 0.
This proves the API boots on the private port with a scratch database and that the plan can be created
and its assignments read back exactly as intended, without any agent running.

## 5. Step 2: the full scripted run

```sh
$PY demo/harness/run_demo.py --mode execute --api-python $PY
```

`--mode execute` turns the dispatcher **on for the private instance only**, so the stub agents can run.
This is the only place the dispatcher flag differs from the "preview" safety rules; the live service is
never involved. The collector, alerts and every outbound integration stay off.

Watch the console. Each line is an assertion; `FAIL` stops the run at the first broken guarantee.

### What each checkpoint proves

| ID | Step | The harness asserts | To check by hand |
|---|---|---|---|
| CP01 | Preflight | Port ≠ 8800 and free; scratch data dir; collector off; dependencies import | `evidence.json` → `CP01` |
| CP02 | Create plan | Project created; coordinator → planner → plan-review all ran; project reaches `review` | Projects page |
| CP03 | Review assignments | ≥6 stories, exactly 3 levels, claude/codex/openclaw/human mix, ≥2 OpenRouter models, and the reviewed assignments equal the intended ones | Project map; model column |
| CP04 | Submit | Project becomes `active`; **one card per story, no duplicates**; each card has its agent and model; the human card waits in Backlog; dispatch order respects every dependency | Tasks board |
| CP05 | Handoff policy | Human story excluded; the five agent stories eligible; policy saved as `automatic` | Project → handoff approval |
| CP06 | Level 1 | `S1_content` runs once on its assigned model, writes `content/*.md`, and is accepted **without a manual click** | Run log |
| CP07 | **Interrupt** | While `S1_changelog_data` is `running` on its OpenRouter model, the harness SIGKILLs *its own* API PID; the process is gone and `/healthz` refuses | `evidence.json` → `killed_pid` |
| CP08 | **Recover** | Restart on the same port and data dir; no run is left `running`; **exactly one run succeeded**; still six story cards; every start used the same idempotency key; `changelog.json` is valid. The evidence records whether recovery *reattached* to the surviving process or *requeued* it, and whether any duplicate agent work happened | Run list for the story |
| CP09 | **Timeout** | `S2_generator` hangs; the run ends as `timeout` after 30 s; its process is stopped; card is Failed; downstream stories did not start; no partial `build.py` is kept. An explicit retry then succeeds with exactly one success | Run stage `timeout` |
| CP10 | **Cancel** | While `S2_checker` is running, `POST /api/runs/{id}/cancel`; run ends `cancelled`; process stopped, never finished; no partial `check_site.py`; card Failed and **not** retried automatically; explicit retry then succeeds (`cancelled`, `succeeded`) | Cancel Run button |
| CP11 | **Human decision** | `S2_decide_theme` is ready for the operator; `S3_build` is blocked with reasons; operator pauses dispatch; nothing starts for 5 s; the operator accepts the decision `Decision: theme=dark`; it lands in shared project memory | Backlog card; Accept |
| CP12 | **Resume** | Resume dispatch; `S3_build` starts **once**, only after the decision; it read `theme=dark` from the shared context, on `gpt-5.6-terra`; exactly one run | Run log |
| CP13 | **Finish** | Project `complete`; every story Done; all 11 artifacts exist; site carries `data-theme="dark"`; changelog lists 0.3.0, 0.2.1, 0.2.0; `report.json` ok; no story started before its agent prerequisites finished; every story has exactly one successful run; every run requested **and the CLI received** its assigned model; the context endpoint carries the decision | Artifacts folder |

### Outputs

```
demo/out/<timestamp>/
  evidence.json        every checkpoint, assertion, timestamp and measured value
  stub-events.jsonl    what each stub agent saw: start/finish/terminated, pid, model, key, working directory
  project-memory.json  the project's shared memory ledger at the end
  api.log              the private API's log (both processes, before and after the kill)
  artifacts/           the finished docs site, generator, checker, report.json
```

`evidence.json` top-level `result` is one of `passed`, `failed`, `refused`, `blocked`, with a
`summary` count. Each checkpoint has `status` (`passed`, `failed`, `skipped`), its `assertions`
(`description`, `ok`, optional `data`) and notes. `artifacts` in CP13 maps each file to its SHA-256.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Every checkpoint passed (rehearsal: those it runs) |
| 1 | An assertion failed; read the first `FAIL` line and `evidence.json` |
| 2 | Refused to start (port 8800, port occupied, bad option) |
| 3 | Blocked: dependencies missing or the API did not start |

### Look at the result

```sh
python3 -m json.tool demo/out/<timestamp>/evidence.json | less
open demo/out/<timestamp>/artifacts/site/index.html      # macOS; use xdg-open on the Pi
```

## 6. The API calls behind each step (for doing it by hand)

The harness stops its API when it ends. `--keep-scratch` leaves the scratch directory (`/tmp/rcd-demo-*`,
printed in `evidence.json` as `scratch`) so you can inspect the database, workspace and stub state.
To drive the same steps in a browser, start your own private instance with the environment from `Run.env()`
in `run_demo.py` (fresh `MAC_CONTROL_DATA_DIR`, unused port, collector off) and never the live data directory.

The calls the harness makes (all need the `X-Mac-Control: 1` header):

| Step | Call |
|---|---|
| Create project | `POST /api/projects` |
| Plan | `POST /api/projects/{id}/plan` `{revision, approve_coordination}` |
| Submit | `POST /api/projects/{id}/submit` `{revision, approve_coordination, approve_api_work}` |
| Automatic handoffs | `POST /api/projects/{id}/handoff-policy` |
| Cancel | `POST /api/runs/{run_id}/cancel` |
| Retry | `POST /api/projects/{id}/stories/{card_id}/retry` `{revision}` |
| Pause / resume | `POST /api/projects/{id}/pause` and `/resume` `{revision}` |
| Human decision | `POST /api/projects/{id}/stories/{card_id}/accept` `{summary}` |

## 7. Safety rules the harness follows

- Refuses port 8800 and any occupied port; picks from 8801 up.
- Fresh scratch data dir and a scratch `HOME`; never reads `~/.mac-control`, agent logins or API keys.
- Collector off; no alert, Google sign-in or messaging settings passed.
- Tracks the PID of the API it started and signals **only that PID** (SIGKILL for the interrupt, SIGTERM for
  cleanup). It never looks up a process by port.
- Stub agents make no network calls. Orphans left by the deliberate kill exit on their own within 120 s.
- No commits, pushes, merges or publication; artifacts stay under `demo/out/`.
- `install-launchagent.sh` is never run.

## 8. Troubleshooting

| Symptom | Likely cause and action |
|---|---|
| `BLOCKED: ... cannot import the API dependencies` | Install `apps/api/requirements.lock.txt` into a venv and pass `--api-python` |
| `REFUSED: port ... occupied` | Pass `--port` with a free port. Do not stop whatever uses it |
| `FAILED` in **CP08** with `IDEMPOTENCY_CONFLICT` in `api.log` | The engine rejects the reused key after a restart; this is the known High finding H1 in the S3 code review. Record it; the harness has caught a real defect |
| `FAILED` in **CP09** at "retry" with 409/`IDEMPOTENCY_CONFLICT` | Same finding (timeout retry reuses the key). Attach `evidence.json` and `api.log` |
| `FAILED` in **CP08** "exactly one run succeeded" with two | Duplicate completion after restart (review finding H4/M1 family). Attach the evidence |
| `FAILED` in **CP05** eligible count | A story text matched the outward-action or sensitive-review wording; run `--mode validate` |
| Stuck at CP02 | The coordinator or planner stub failed; read `stub-events.jsonl` and `api.log` |
| Hermes cards fail immediately | MCD's launcher needs a Python shebang and an importable `hermes_cli`; the harness provides both, so check that `--api-python` is a real Python path whose name contains "python" |

Open known gaps, deliberately **not** covered by this harness:

- **In-run decision (pause inside a running agent, then resume the same run).** MCD supports this only for
  checkpointing runtimes (ZeroClaw/PicoClaw adapters), which the plan schema cannot assign yet. The human
  decision here is the project-level one: a human story that gates downstream work, with dispatch paused
  and resumed around it.
- **Real models.** All agents are offline stubs. A live OpenRouter run needs a key, spend caps and operator
  approval and is out of scope.
- **Parallel dispatch.** Sequential mode serialises the DAG; the three levels are declared and verified
  but not run concurrently.
- **Pi hardware.** The harness is portable Python; run it on the Pi the same way to produce Pi evidence.
  Memory use is not measured by this harness.
