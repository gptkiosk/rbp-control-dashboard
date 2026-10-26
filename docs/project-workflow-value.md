# Why plan and deliver projects with MCD / RCD?

**A shared project record, task-matched models and repeatable delivery steps reduce the coordination you have to do yourself.** MCD on Mac and RCD on Linux combine a guided brief, dependency map, Kanban board, agent execution, evidence and handoffs. Coding harnesses such as Codex and Claude Code remain useful execution and finishing tools within that workflow.

This brief describes the implementation at **v0.6.72**, with a planning pilot dated **2026-10-26**. The aim is lower total delivery cost, stronger results and less human administration. Those are goals supported by specific mechanisms below; a measured end-to-end advantage over manual planning or a standalone harness has not yet been established.

## Where the value comes from

| Work you otherwise coordinate | What the dashboard provides | Practical benefit |
| --- | --- | --- |
| Translate an idea into executable tasks | Guided intake for packaged apps, GCP apps, local websites, GCP websites or Other; reviewed stories with scope, acceptance criteria, estimates and dependencies | Reuse a delivery pattern and make missing requirements visible before implementation |
| Keep people and agents aligned | Versioned plans, task IDs, Kanban states, run history, shared decisions and accepted handoffs | Find what happened, what is blocked and what comes next without reconstructing a chat |
| Reintroduce context for every agent | General guidance plus the selected project type, bounded excerpts and links to full records | Limit irrelevant prompt material while retaining a path to the details |
| Choose and switch models | Task-specific routing advice, dated model evidence, local outcomes and reviewed alternatives | Reserve stronger reasoning for work that needs it; use adequate cheaper routes for bounded work |
| Move work between interfaces | Host/path/branch/commit workspace records, cooperative reservations and compact external handoffs | Continue in a coding app and bring its work back into the project record |
| Arrange artwork and preview delivery | Media inventory, generation/selection/integration dependencies and app-managed remote preview controls | Make final media and reviewable output explicit deliverables rather than forgotten follow-up work |
| Track effort and spending | Story estimates, actual run durations, retries, tokens, reported cost and separately labelled API equivalents | Identify rework and estimation errors instead of relying only on impressions |

These mechanisms are implemented, but their effectiveness depends on plan quality, installed tools, configured channels and approved routes. A generated plan or successful process exit is evidence to inspect, not proof of an accepted product.

## Compared with other ways of working

| Approach | A good fit | Coordination responsibility |
| --- | --- | --- |
| Manual project planning | A small known job, or work that primarily needs human judgment | People create/update tasks, choose workers, maintain context and gather evidence |
| Codex or Claude Code alone | Focused coding, exploration, debugging and interactive polish in a checkout | A session can plan and implement; the operator supplies or maintains the wider project record and handoff conventions |
| MCD / RCD with coding agents | Repeatable projects that involve several stages, models, assets or interfaces | The app maintains the board, approved plan, dependency order, routes and durable evidence; agents perform the assigned work |

A standalone harness can also use files, skills and automation to reproduce parts of this workflow. The reason to choose the dashboard is to package those conventions into a shared, visible process. For a tiny edit, dashboard setup and plan review may cost more time than they save. For repeated or interrupted projects, the durable record becomes more valuable.

## Context efficiency is part of the code

The app loads **general guidance plus one selected project type**, rather than every template or unrelated personal chat. Selected guide text shares a **7,000-character budget**. Model guidance is capped at **24 rows / 3,500 characters**. Story brief excerpts are capped at **6,000 characters**, with a private file reference for full material. Prior-map summaries for replanning are bounded too.

These are component limits, not a claim that the entire model request fits in one small budget. Runtime instructions, accepted handoffs and native harness overhead also consume context. Character counts are not token counts. The benefit is controlled growth and retrieval of relevant detail; actual savings depend on the workload and harness.

See the [context and channel contract](configuration/coordinator-pipeline.md), [guide selection code](../apps/api/project_types.py), [story context code](../apps/api/projects.py) and [model guidance code](../apps/api/model_selection.py).

## Match the model to the work

The Economy–Balanced–Capability preference is a classification threshold, not a vendor pin. Recommendations consider specialty, complexity, risk, tools, vision, context, dated research, local run history, speed and expected total cost including retries. Planner quality is chosen separately from the story-worker preference. Explicit assignments and spending permissions still govern execution.

Configured provider snapshots and sourced notes support the decision. OpenRouter and LiteLLM reference inputs are available; the generic evidence import can accept other normalized sources. An authenticated Artificial Analysis or Arena connection is **not included**. Benchmark rankings do not prove local reliability or available quota. Approved alternatives and Model lock let operators control switching without losing task history.

A cheap first attempt that needs repeated repair can cost more overall. Membership quota, free-provider limits, paid API charges and optional media charges must be considered separately. See [model profiles](configuration/model-profiles.md) and [routing implementation](../apps/api/model_selection.py).

## Documentation that survives the chat

The reviewed map becomes bounded stories on the Kanban board. Each story has its own definition of done, owner/route, estimate, dependencies, result and evidence. The project ledger retains decisions and handoffs; replanning preserves completed and attempted history while replacing untouched work through a reviewed revision.

The Workspace view identifies the host, checkout, branch, commit, recent recorded work and next tasks. A compact handoff supports finishing in Codex or Claude Code, followed by recording the external changes and releasing the cooperative reservation. An import inventory can summarize an existing repository's tracked code, dependency manifests, documentation and configuration-variable names; it is not a complete architecture or resolved dependency analysis.

Hermes chat and paired Discord are entry points to the same project. Current channel capabilities are explicit: not every dashboard execution or approval action is available through Discord or native read/draft tools. Workspace paths do not synchronize machines, and unreported native edits cannot identify their author reliably. See [workspace and import guidance](configuration/project-workspaces.md).

## Reduce human administration; retain meaningful decisions

A repeatable illustrated-website workflow is: **guided brief → reviewed plan → asset inventory → approved generation → candidate selection → integration → verification → visual review → delivery**. Media generation requires configured providers and spending approval. References guide the look; actual final artwork must be generated or supplied and integrated.

Routine inventory, implementation and checks should flow through their dependencies. Human attention belongs at missing requirements, spending, media selection, visual acceptance and consequential release/security choices. The app's host preview controls and authenticated remote link avoid asking a remote user to operate a host terminal.

This can reduce repeated briefing, task writing, status chasing, command copying and handoff reconstruction. It does not eliminate review, and it does not make all human gates optional. Quantified human-time savings require a baseline study that includes setup, review, interruptions and rework.

## What the planning pilot actually showed

One frozen illustrated-website brief was planned **three times per route**, with three separate Coordinator decisions per route. Fresh runs used the same core inputs, selected local-website template and allowed execution catalog. No site was built or media generated.

| Requested planner | Schema valid with unique JSON keys | Separate reference publication before dependent scene generation | Median planning time |
| --- | ---: | ---: | ---: |
| Gemma 4 31B free | 3/3 | 2/3 | 157.8 s |
| GPT-6 Luna | 1/3 | 0/3 | 41.9 s |
| GPT-6.1 Sol | 3/3 | 3/3 | 177.8 s |

All nine complex-brief Coordinator decisions selected Sol. A separate simple-spacing control, one run per route, selected Luna in all three cases. This supports trying inexpensive routing with a stronger planner for this complex dependency map. It does not show that the cheapest or strongest model is always best.

The pilot also exposed defects: duplicate dependency keys were accepted by the app, title/browser classifiers produced false findings, and one Sol plan omitted a required typed inventory field despite containing the work. These remain known v0.6.72 limitations. Model reviews were advisory and made factual errors; the conclusions above use schema and actual dependency relationships.

Across 32 instrumented calls, including repairs and advisory reviews, reported usage was **585,195 input / 58,367 output tokens**. The illustrative uncached API-equivalent was **about $0.47**, using dated reference prices; execution used membership/free routes. This excludes the coordinating chat and CI/builds and is not an invoice or per-task subscription charge. Reference rates used were Luna $0.10 input / $0.50 output and Sol $2 input / $10 output per million tokens, with the selected free route at $0, from the [official model reference](https://developers.openai.com/api/docs/models) as read on 2026-10-26. Native harness overhead and provider scheduling differed. The pilot used text descriptions of references, not image inputs, and did not exercise live quotas or the complete production evidence packet.

This is an internal pilot summary; private inputs and raw run logs are not published here. Three trials per route and one project type cannot establish general reliability, visual quality, end-to-end cost savings or human labor saved. A fair next comparison must hold requirements and acceptance checks constant across manual planning, standalone harness planning and dashboard delivery, and count failed attempts and operator minutes.

## Estimates today, better forecasts next

**Today:** stories store estimates; parallel-plan schedule calculations show total estimated work and the dependency critical path as a best-case bound, not a completion promise. Telemetry aggregates actual agent-run minutes, retries, completion/first-pass results, and actual-to-estimated ratios by work kind. The Coordinator scorecard also relates plans to later edits and outcomes. See [telemetry code](../apps/api/telemetry.py), [scheduling code](../apps/api/project_schedule.py) and [scorecard guide](configuration/coordinator-scorecard.md).

**Next improvement, not yet implemented:** calibrate new estimates from comparable accepted work, grouped by project type, story kind, complexity and route. Separate active execution, retries, provider queues, human review and calendar waiting. Show sample counts and forecast ranges; keep cold-start estimates visibly provisional. Parallelism and resource limits belong in calendar forecasts, not just a sum of story estimates. Agent runtime is neither human effort nor elapsed project duration.

Measure success as **cost and operator time per accepted deliverable**, with quality, rework and delivery time beside it. Use past projects to improve forecasting only when there is enough comparable evidence. That is how this workflow can demonstrate its intended advantage over time rather than merely promise one.
