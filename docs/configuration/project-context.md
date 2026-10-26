# Project context: tighter, cheaper and lossless

Every story prompt carries the rules, the project brief and the history the story needs. Sent in
full, that history was the largest cost of a run: measured on 248 prompts, the median was 27 KB, the
accepted-memory ledger was 63% of it, and no two prompts shared a beginning, so nothing could be
cached. Compaction now works like this.

- **Stable first, the story last.** The rules, the project and revision, the brief and constraints
  come first and are identical for every story of a revision, so a provider's prompt cache can reuse
  them. The story's own text follows under `YOUR STORY (do this now)`.
- **Full text where it matters, a digest elsewhere.** A direct prerequisite's handoff keeps up to
  3,500 characters. Earlier stories in the lineage become a digest of at most 700 characters: the
  first line plus the lines that state status, changes, checks, decisions, risks and next steps.
  Everything else is shorter still. Each digest says how long the original was and where it is.
- **Only relevant decisions.** A story sees decisions about its own lineage and the three newest
  global ones, not every operator decision on unrelated stories.
- **Nothing is lost.** The complete ledger is written to
  `~/.rcd-control/project-ledgers/project-<id>.md` (mode 600, rewritten only when it changes). The
  prompt names that path in `memory_compaction.full_ledger`; an agent that needs an omitted detail
  reads the entry there (`## #<id>`). The database still holds every entry.
- **Same shape for every agent.** A story handed from Claude to Codex or OpenClaw gets the same
  context, so a reroute does not change what the agent knows.
- **Measurable.** Each run's checkpoint records `context_bytes`.

On the real project history (164 stories), context fell from 4.0 MB to 2.7 MB in total (34%), the
median from 27 KB to 19 KB, before any prompt caching. The budget is 16 KB for the JSON payload.


## Context selected by type

See the [Coordinator context contract](coordinator-pipeline.md). Consultant and planner prompts load general guides plus one selected type. Story prompts carry the selected guide names and a private, hashed file reference; unrelated story tails are omitted. The full ledger remains available on demand.

## Project packet pointer

When the project packet can be built, story context carries `project_packet`: the START-HERE path, `docs/project/` and one sentence asking the story to update those docs when it changes architecture, configuration names, decisions or operating steps. It adds about 350 bytes, is identical for every story of a project and sits with the stable keys, so prompt caching is unaffected. See [project packets](project-packets.md).
