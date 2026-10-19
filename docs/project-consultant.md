# Project consultant and AI defaults (0.3.1)

Open Projects and choose **Refine with project consultant** below Create project brief. Its glass panel asks for the project name, allowed working directory and initial goal. Start begins a tracked read-only agent conversation. The consultant answers what you ask, then asks the few questions that would most change the plan, and keeps going until you say it is enough. The chat shows only your words; the guidance and what this installation knows (standards, installed agents, models) travel with the message as background and are not displayed.

Choose **That’s enough, write up the plan** when you are ready. The consultant writes the brief from the whole conversation and it opens as an editable New project review automatically.

If the latest reply already is the brief, **Review brief & submit to Hermes** copies it into the same editable New project review. Check the title, brief, workspace and planning model. Approve coordination and submit, or save a draft. Hermes is the fixed project Coordinator; the planner is selected separately and may be Claude, Codex, Grok Build or another available route. Coordination returns a project map for review; implementation stories still require their separate approved revision. Busy or approval-pending chat turns cannot be silently handed off. Closing the panel keeps its thread; its Projects URL includes the consultant thread number for reopening. Full conversation history is also in Chat.

## What the consultant knows

The first message to the consultant carries the same knowledge a plan run gets, in five labelled parts: how the software is delivered
(hosted or packaged and what that means for risk); which product and host this is, which agent runtimes are installed (and how each is
billed), that Hermes is the Coordinator and which planner/model routes are available, plus the spending policy (no keys, paths or account identities); the standards that apply to the chosen working directory (the repository's own, or the
starter standards) with each area's minimum risk; the methods and practices to build the plan on (development practice, hosted and packaged
delivery, application security); and the track record of the models it could recommend (free or paid, context, tools, how they have done here
by kind of work, unproven stated plainly). The consultant is told to use it in the discussion and to write the brief so the coordinator can plan
from it directly: Approach and methods, Risks and the standards areas they fall under, Security considerations, and Model and route
considerations (free or paid, and why), alongside the usual goal, phases, stories and definitions of done. It is advice for the conversation and
authorizes nothing; the gates and your approvals still decide. If it cannot be read, the conversation starts without it. To change the methods,
copy a guide from `packs/standards/` to `standards/` in your data folder and edit it; your copy is used and survives updates.

## Free-first settings

Profile → **AI defaults** sets the agent/model for new consultant chats, agent chats, task forms and project planning. The initial values are Hermes and `openrouter/free`. Every feature links to these settings and this help topic. Install the selected runtime and configure its provider on the dashboard host. The dashboard spending-check credential is not automatically copied to native agents.

To use membership capacity, select the installed Claude Code, Codex or Grok Build CLI and enter a supported model for that CLI. Sign into the native account owning the eligible membership. API keys and OpenRouter BYOK use separate usage billing; they do not use membership allowances. A preference does not authorize paid fallback, bypass the installation's free-only policy, or change existing conversations/approved project routes. Unavailable default runtimes require installation or an explicit settings change; there is no automatic switch to a paid agent. Free routes may throttle, time out or become unavailable.

The built-in help chat reads local how-to guides without model calls. Project consultant chat uses the configured model and displays normal turn status, errors, approvals, and available usage information through the existing chat interface. No model calls happen merely by opening Projects or the panel.

## Installation and privacy

Use your own Google OAuth client, host origins and approved accounts. No personal Tailscale endpoint, provider key or maintainer account is bundled. The consultant does not request secrets. Agent execution and model-policy checks remain on the host. Read mode has the existing runtime-specific enforcement limits shown in Chat; review the selected agent's capabilities. Keep confidential material out of prompts sent to providers you have not approved.

The earlier installer, OAuth setup, saved-key, wizard navigation and inline refreshing helper-log fixes are included in 0.3.1. Existing live installations need the new build; verify the signed installer release before updating an installation.
