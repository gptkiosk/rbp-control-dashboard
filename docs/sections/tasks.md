# Tasks

## Purpose

Open **Tasks** (`/tasks`) to see which work is running, queued, blocked, waiting for approval or done. Open a task to inspect its instructions, definition of done, dependencies and latest run evidence.

## Screenshots

Pending capture: `tasks-board.png` (grouped board) and `tasks-story-assignment.png` (new task form). No RCD capture exists yet.

## Controls

1. Use the agent, priority and tag filters to narrow the board. Collapse or hide lanes to focus on current work; these display preferences are saved locally.
2. Select **Add task**, choose a human or agent assignee, and provide instructions and a definition of done. For agent work, choose the working directory, model, OpenClaw target where applicable, Read/Edit mode and timeout. Review the assignment before queueing it.
3. Open the task to inspect the latest run, including requested/reported model, result, error, duration and captured usage. Missing telemetry is shown as missing, not as zero.
4. Use the action matching the pending approval:
   - **Approve run** authorizes a standalone task waiting for execution approval. The approval covers one execution of the exact version you reviewed: its agent, model, target, mode, folder and prompt. Automatic retries and restart requeues of that same execution keep it. It expires if unused for 24 hours (`MAC_CONTROL_APPROVAL_TTL_S`). A changed route or prompt, a new run, or a repeated or stale approve request sends the task back to Review for a fresh approval. Refused attempts are recorded on the task.
   - **Answer run decision** resumes a paused run once. The decision is bound to that run's current pause and route; a replayed, expired or other-run decision is refused and recorded in the run's events. Rejecting is always allowed.
   - **Approve & continue** lets a supported read-only Claude project story continue, with MCD saving one proposed Markdown output. It does not accept an unfinished artifact or grant shell/file-write tools.
   - **Approve handoff** accepts a completed project result after its definition of done has been reviewed. If workspace files changed, the shortcut opens the project review path so you can inspect and select files.
   - **Record decision** opens the human story's instructions and a required decision field. Record the actual choices and conditions, not just a generic acknowledgment.
5. Review failed work before retrying. Project stories use **Projects → Stories & runs** and its **Retry same story** or **Retry with** choices. Only previously approved routes are offered.

Only queued agent cards can be newly claimed by the dispatcher. Running cards already belong to an active run. Prerequisites must be **Done** before dependent work starts; a successful project run remains in **Needs approval** until its handoff is accepted. Standalone successful runs normally move directly to Done.

Standalone cards may be moved between allowed lanes. Running agent cards cannot be dragged, and project-bound assignments/dependencies are protected by the approved project manifest. Use Projects for project workflow changes.

Claude Read mode uses plan mode; Codex uses a read-only sandbox. Their Edit modes permit workspace edits according to each CLI's policy. Hermes and OpenClaw use their native tool permissions: Read/Edit is advisory for them. The working directory and task instructions do not create an OS sandbox for those agents.

## Settings involved

- Installed agent binaries, allowlisted working directories, default timeout and dispatcher concurrency are host settings.
- Billing & rates controls subscription/API accounting. Keep approved subscription routes on the account's existing login.
- Project assignments, dependencies and alternate model routes are frozen at submission. A blank model follows the native default; an explicit assignment controls that run.
- The dispatcher must be enabled for queued work to start. Collection is separate from dispatch.

## Troubleshooting

- **Nothing is running:** look for a prerequisite in Needs approval, a ready human decision, a paused project, a disabled dispatcher or an unavailable agent. Sequential projects wait for each accepted handoff; parallel projects also respect workspace and target conflicts.
- **OpenClaw timeout with exit code 0:** process exit and agent outcome are separate. Read the reported timeout/error and partial output before retrying; increasing the local timeout cannot override a shorter provider limit.
- **Quota reached:** MCD can capture a checkpoint and try another approved route for a recognized quota/rate-limit failure. Timeouts, cancellation and malformed output need an explicit retry. Switching within the same subscription may share the exhausted quota.
- **Interrupted by restart:** inspect partial work and retry explicitly. MCD does not blindly rerun interrupted jobs.
- **Handoff shortcut refuses changed files:** open the full project review, inspect the diff/new files and select only the reviewed artifact files. The shortcut never snapshots them automatically.

## Related pages

- [Projects](projects.md): planning, handoffs and approved routes.
- [Agents](agents.md): activity, subagents and cost coverage.
- [Chat](chat.md): direct agent conversations.
- [Settings](../configuration/settings.md) and [environment configuration](../configuration/environment.md).
