# Chat

## Purpose

Open **Chat** (`/chat`) to converse directly with an installed agent. A thread records its agent, optional OpenClaw target/model, working directory, Read/Edit mode, messages and run evidence. Chat replies are not approvals of project plans, publication or additional model routes.

## Screenshots

Pending capture: `chat-thread.png` (conversation), `chat-new-dialog.png` (new chat form). No RCD capture exists yet. [Help chat](help.md) is a separate local guide feature, rather than a native agent conversation.

## Controls

1. Select **New chat**. Choose the agent, optional title/model, working directory and mode. For OpenClaw, choose a known named target from the dropdown.
2. Open the thread and type a message. Creating the thread alone does not send a first prompt.
3. If a message needs approval, review its displayed reasons and use **Approve** or **Reject** in the conversation. The composer waits for that decision before another message can proceed.
4. Follow the live response and final result. A busy marker means the thread has work pending/running; it does not guarantee the provider is producing output.
5. Use the conversation's stop control to cancel work when appropriate. Review partial work before sending another request.
6. Return to the thread list with Back. Deleting a thread removes its MCD conversation after confirmation; it does not remove the agent's native transcript files.

A blank model follows the agent's configured default policy. Explicit Hermes/OpenClaw model assignments disable inherited model fallback for that run. Claude and Codex use their CLI modes: Read uses Claude plan mode or Codex's read-only sandbox; Edit allows workspace edits under the relevant policy. Hermes/OpenClaw retain native tool permissions, so their Read/Edit choice is advisory. Do not assume they are sandboxed by this setting.

Chat runs use separate dispatcher slots, but overlapping active project work or the same OpenClaw target can defer a turn. Sessions continue within the thread where the adapter supports resumption. Chat does not automatically share an approved project's full ledger; use [project context export](projects.md) when handing project information into a separate native conversation.

## Settings involved

- Installed binaries and allowlisted working directories control available agents and workspaces.
- Thread agent, target, model and mode determine its route and permissions.
- Chat turns have a 15-minute MCD run limit. OpenClaw receives the timeout and Hermes receives a run budget; providers can impose shorter limits.
- Approval reasons and operator decisions are enforced before a guarded message is claimed.

## Troubleshooting

- **Waiting for approval:** open the thread and approve or reject the specific message there. Project story approval is a different workflow.
- **Waiting while a project runs:** check workspace/target conflicts. Chat has separate concurrency slots, but cannot bypass those conflict checks.
- **No reply yet:** OpenClaw may return its JSON only at the end. Inspect the run status/log and time limit before duplicating the request.
- **Timed out with a normal exit:** read the agent outcome, not just the CLI exit code. Provider silence and MCD's overall limit have distinct error explanations; partial usage/output may remain available.
- **Unexpected file change:** inspect the run evidence and native agent permissions. Read mode is advisory for Hermes/OpenClaw; Claude/Codex enforce their own CLI restrictions.
- **Missing usage/model:** retain the missing-data indication. MCD does not invent a model or cost to fill an absent report.

## Related pages

- [Tasks](tasks.md): board execution and evidence.
- [Agents](agents.md): subagents, sessions and cost coverage.
- [Projects](projects.md): reviewed project planning and shared context.
- [Help](help.md): local feature guidance.
- [Settings](../configuration/settings.md).
