# Project packets

A project packet carries a project to another dashboard, another host or a coding app (Claude Code, Codex, Grok Build) without losing its context. Format: `bamcio.project-packet/1`.

## What it holds

| File | Contents |
| --- | --- |
| `PACKET.json` | Schema, generator product/version/commit, source project and revision, workspace branch/commit, freshness, document and asset index with SHA-256 hashes, the confirmed intent (brief, constraints, intake answers) and a story summary |
| `START-HERE.md` | At most 4 KB: freshness, next work, the five continuation rules and the document index |
| `01-brief.md` … `07-media.md` | Brief and amendments, source map, environment (configuration names only), state, decisions, evidence, media |
| `history/ledger.md` | The project ledger, redacted, newest entries kept within 1 MB |

Statuses keep the dashboard's meaning: *accepted* (operator or approved project-wide policy, marked as such), *reported* (an agent or external result awaiting review) and *planned*. Nothing is promoted on export. Credentials, e-mail addresses, home-directory names and private addresses are redacted; configuration values and `.env` files are never read.

## Where it lives and who writes what

The app writes the packet only to its private data folder: `<data dir>/project-packets/project-<id>/` (mode 700/600). It never writes into a workspace, so it cannot dirty a checkout or create a commit loop. It is rebuilt when something it reports changes, whenever it is read: the Workspace panel, export, Copy handoff and every story prompt.

Agents maintain `docs/project/` in the workspace (`architecture.md`, `decisions.md`, `operations.md`) in the same story that changes the source. The planner rule in role pack 27 adds this to acceptance; story prompts carry a `project_packet` pointer (about 350 bytes) with the START-HERE path and that duty. The packet indexes these files by hash and never edits them. `AGENTS.md`, `CLAUDE.md` and personal harness files are never touched; START-HERE tells an agent to read them first.

## Freshness

| State | Meaning |
| --- | --- |
| Current | The workspace matches the state at the last recorded work |
| Stale | Commits or edits since the last accepted handoff, recorded external work or checkpoint. They are reported as unreported with unknown authorship, never attributed |
| Work in progress | An app run is using the workspace, it is reserved for external work, or a story result awaits review |
| Unknown | No readable Git repository, or the read timed out |

Only recorded work moves the baseline. An operator note does not hide unreported changes, and a rolled-back transaction does not move it.

## Export

**Projects → Workspace → Download packet (.zip).** Includes the documents, `docs/project/` files and reference images (each at most 10 MB). Published media is opt-in. The archive is capped at 64 MB; anything left out (too large, missing, a link) is listed in `PACKET.json` with where to copy it from. Workspace files are read through directory descriptors and links are never followed. Source code is not included: continue from the named repository, branch and commit, or copy the source separately when there is no remote.

## Import

**Projects → Import packet…** The upload is validated before anything is shown: schema major version 1, every member listed with a matching hash, only expected paths (documents, `living/docs/project/`, `media/references/`, published media), no links, absolute paths or `..`, size and compression limits, image bytes, and no credentials in text. A packet from a newer major version is refused with an update message. Nothing in a packet is executed.

The review shows the source, accepted and remaining work, and anything missing. Choose a working directory on this host (a path from another host is never used) and whether to copy the reference images. Import then creates **one draft project**: the brief plus a continuation section, type and intake answers when they apply here, reference images, the packet files kept read-only in the new project's packet folder under `imported/`, and a decision entry with the provenance and whether the destination checkout matches the source commit. Tasks, approvals, routes, model locks, branch grants, spending decisions and credentials never carry over. Plan the draft as usual.

## Hermes, MCP and Discord

`packet(project_id)` is a read through `/api/projects/coordinator`, native `coordinator_read` grants and the paired Discord `mcd_project` tool (with Discord diagnostics enabled). It returns freshness, the document index, START-HERE and the download link. Download and import are web-only; capabilities list them with an operator link instead of a tool.

## Limits

The source map is the bounded repository scan (1,500 files, 2 MB, 4 seconds). Inferred architecture is a map, not verified design. Setup and run commands come only from `docs/project/operations.md`; the app does not infer them. A packet is not a repository backup.
