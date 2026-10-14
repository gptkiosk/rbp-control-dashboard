# Project consultant and AI defaults (0.3.1)

Open Projects and choose **Refine with project consultant** below Create project brief. Its glass panel asks for the project name, allowed working directory and initial goal. Start begins a tracked read-only agent conversation. Discuss the goal, phases, stories, scope, definitions of done and dependencies; ask the consultant to produce a complete brief when ready.

Choose **Review brief & submit to Hermes** to copy the latest completed reply into an editable New project review. Check the title, brief, workspace and planning model. Approve coordination and submit, or save a draft. Hermes must be the assigned Delegator in Settings → Agent roles. Coordination returns a project map for review; implementation stories still require their separate approved revision. Busy or approval-pending chat turns cannot be silently handed off. Closing the panel keeps its thread; its Projects URL includes the consultant thread number for reopening. Full conversation history is also in Chat.

## Free-first settings

Profile → **AI defaults** sets the agent/model for new consultant chats, agent chats, task forms and project planning. The initial values are Hermes and `openrouter/free`. Every feature links to these settings and this help topic. Install the selected runtime and configure its provider on the dashboard host. The dashboard spending-check credential is not automatically copied to native agents.

To use membership capacity, select the installed Claude Code, Codex or Grok Build CLI and enter a supported model for that CLI. Sign into the native account owning the eligible membership. API keys and OpenRouter BYOK use separate usage billing; they do not use membership allowances. A preference does not authorize paid fallback, bypass the installation's free-only policy, or change existing conversations/approved project routes. Unavailable default runtimes require installation or an explicit settings change; there is no automatic switch to a paid agent. Free routes may throttle, time out or become unavailable.

The built-in help chat reads local how-to guides without model calls. Project consultant chat uses the configured model and displays normal turn status, errors, approvals, and available usage information through the existing chat interface. No model calls happen merely by opening Projects or the panel.

## Installation and privacy

Use your own Google OAuth client, host origins and approved accounts. No personal Tailscale endpoint, provider key or maintainer account is bundled. The consultant does not request secrets. Agent execution and model-policy checks remain on the host. Read mode has the existing runtime-specific enforcement limits shown in Chat; review the selected agent's capabilities. Keep confidential material out of prompts sent to providers you have not approved.

The earlier installer, OAuth setup, saved-key, wizard navigation and inline refreshing helper-log fixes are included in 0.3.1. Existing live installations need the new build; source publication is not installation or signed release publication.
