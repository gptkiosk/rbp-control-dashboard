# Project workspaces and repository intake

Open **Projects → Workspace** for the location, host, branch, commit, recent recorded work and next ready tasks. Select the source checkout or an approved story worktree when a project has several locations. Refresh before handing work to another agent. A path belongs to its displayed host; it does not synchronize a different machine.

## Continue in a coding app

Pause dispatch and let active runs finish. Choose the coding app and **Continue in coding app** to reserve the checkout, then **Copy handoff** into that app. The packet is capped at 3,000 characters and links to the project and full context. It includes current Git state, next task links and the latest recorded handoff. Follow the task's full definition of done at its link.

When the external agent has stopped, refresh and use **Record external work & release workspace**. Record its commit/files, checks/results, unfinished work and next steps. This appends reported evidence, releases the reservation and leaves dispatch paused. Acceptance still uses the task's normal review. The next project run gets a bounded reference to the latest external handoff, explicitly marked unaccepted.

The task and chat dispatchers refuse overlapping reservations, including those belonging to another project. An overdue reservation stays blocking until a handoff releases it; a timeout cannot prove an external process stopped. Reservations coordinate cooperative tools and do not lock arbitrary native processes. Unreported native edits cannot reliably identify their author. Git status observations are freshness indicators, not content verification or an atomic snapshot.

If a folder disappears, its record remains inspectable so its reservation can be released with an explanation. Project deletion is refused while it owns a reservation. No source reset, merge, push, process termination or native instruction-file editing happens through these controls.

## Import existing work

Choose **New project → Import existing project**. Select or enter the actual repository root inside a configured workspace root, then **Inspect repository**. Intake reads tracked text, dependency manifests, documentation and configuration-variable names. **Use this repository** adds a compact inventory summary to the brief and keeps the existing checkout/history. Add the outcome or changes you want, select the project type and review planning normally. The original project brief is retained.

This first inventory covers up to 1,500 tracked text files, 2 MB total, 128 KB per file, depth 10 and four seconds of file traversal. Git commands have separate three-second/output limits. Omitted files are counted. Secrets/config values, `.env` files, VCS internals, caches, generated files, binary files and symlinks are excluded. Reads use directory descriptors to prevent link swaps escaping the approved root. No scripts, hooks, installation, builds or network operations run.

Node manifests expose bounded declared dependency names/versions; requirements files expose names. Other supported language manifests are located for follow-up. Lockfile presence does not prove a complete resolved dependency graph. Configuration references report names and source paths, with requirement status unknown. The inventory hash covers scanned bytes; concurrent native edits can still require another scan. Untracked files are outside this initial intake.

Missing runtimes, tools, permissions, configuration and delivery access belong before dependent implementation in the continuation plan. Import does not grant write access to an existing branch or create a replacement repository.

## Hermes and MCP

The shared read service exposes `workspace(project_id, working_dir)` and `repository_intake(working_dir)` through `/api/projects/coordinator`, native `coordinator_read`, and the paired Discord `mcd_project` tool. Workspace reads return a compact packet and stable host/path-derived workspace ID. Project-specific reads check ownership.

Paired Discord additionally supports `reserve_workspace` and `record_handoff` when **Discord control and diagnostics** are enabled. Read the workspace first; pass its current revision, snapshot and a UUID `operation_id`. Recording also passes the current `reservation_id` and `handoff` summary. Reuse the same operation ID for a retry. The web UI retains the operation ID across a failed-response retry.

Native read/draft MCP grants remain read-only for these features. Full channel control parity, external harness heartbeat adapters, automatic cross-host clone/synchronization and complete incremental dependency/configuration graphs remain future work. Current capabilities explicitly identify unsupported actions rather than inventing tools.
