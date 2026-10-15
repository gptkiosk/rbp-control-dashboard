# What survives an update

## Purpose

Explains what RCD keeps, replaces and never touches when you update it, so you can customize the coordinator, keep your
agents' knowledge and trust that your preferences are still there afterwards. The short version: an update replaces the
program; everything that is yours lives outside it and is left alone.

## Controls

There is nothing to switch on. This page tells you where each kind of thing lives, what an update does to it, and what to look at
after an update.

| What | Where it lives | An update |
|---|---|---|
| The program: code, built interface, shipped docs, the starter standards and the shipped coordinator text | the install root: `versions/<id>` with `current` pointing at the running one | **Replaces it.** Do not edit files here; each version is sealed once installed, and the updater replaces the whole version folder. |
| Host settings | `the `.env` beside the service (see the install guide)` | **Never touches it.** New settings default to off or safe. The update records the helper configuration in its snapshot but never your settings. |
| Everything RCD remembers: tasks, runs, projects, approvals, decisions, project memory, usage, alerts | the database `the database file named in `helper.json`` | **Keeps it.** Schema changes run at start and only add; the updater copies the database to `<root>/state/backups/` (with its checksum and schema revision) before it switches versions. |
| Profile preferences, linked accounts and switches | the database | **Keeps them.** A preference added by a newer version takes its default (off unless stated). A profile saved by a newer version still opens in an older one; keys the older version does not know are ignored. |
| Saved credentials and tokens | encrypted in the database with `vault.key`, plus `agent-tokens/`, in the data folder | **Keeps them.** They are never part of a package or a release. |
| Who your Delegator is | `<data>/roles/assignments.json` | **Keeps it.** |
| Coordinator guidance inside your agents' own files (the managed block, for example in Hermes `SOUL.md` or Claude `CLAUDE.md`) | the agent's own folder | **Does not change it.** It is a copy made when you applied the roles. Your own text around the block is kept byte for byte. After an update, open the roles preview to see whether the shipped guidance changed and apply it if you want it. |
| Planner, review, dispatch and coordination prompts | shipped in the program, read each time a plan runs | **Changes what they say** as soon as you update. To keep your own wording, use a custom copy (below). |
| Your own coordinator wording | `<data>/roles/custom/<file>` | **Keeps it, and it wins** over the shipped file of the same name. |
| Your own starter standards | `<data>/standards/starter.md` | **Keeps it, and it wins** over the shipped starter. |
| A project's repository standards | in that project's own repository | **Never touched.** They change by a normal change in that repository. |
| What your agents know (Hermes, Claude, Codex, Grok and OpenClaw memory, notes and projects) | each agent's own home | **Never read or changed by an update.** The only thing RCD writes there is the managed guidance block. |
| The last read of the public model list, and your model notes | `<data>/models/` | **Keeps them.** |
| Run logs, reports, project outputs, workspaces, alert rules | the data folder | **Keeps them.** Old runs are pruned only by the retention setting (90 days by default). |

## Your agents' own settings

Claude Code, Codex, Grok, Hermes and OpenClaw keep their settings, credentials, memory and instructions in their own folders
(for example `~/.claude`, `~/.codex`, `~/.hermes`, `~/.openclaw`). RCD does not own any of that, and these rules keep it safe:

- **Managed tool copies live apart.** When RCD installs or updates an agent tool, the program goes into its own tools folder with
  its own `current` and `previous` links, using a throwaway home folder for the installer. Updating, rolling back or removing that
  copy never reads, rewrites or deletes anything in your agent's own folder. An update of the tool is only ever a new program;
  your settings are still read by it from where you put them.
- **Runs see your settings.** An agent started by RCD gets the service's own environment (so `HOME` and any settings location
  such as `CODEX_HOME` or `HERMES_HOME` point where you set them) minus RCD's own settings and credentials.
- **The only things RCD ever writes into an agent's folder** are the marked guidance block when you apply roles (your own text
  around it is kept byte for byte, and rolling back restores it), and, only if you run the Hermes plugin installer yourself, the
  plugin files and one added entry in Hermes' Discord toolset list. It refuses to replace a plugin that differs from its own.
- **Tests check this** for every agent: a synthetic copy of each agent's settings, credentials and memory is left byte for byte
  unchanged, with unchanged modification times and no new files, across install, update, rollback and remove of its managed tool.

## Customizing the coordinator so it survives updates

The shipped coordinator text lives in the program folder, so editing it there would be lost (or would stop a checkout updating).
Put your version in the data folder instead:

1. Copy the file you want to change from `packs/roles/delegator/` (`plan.txt`, `review.txt`, `dispatch.txt`, `coordinate.txt`,
   `SOUL.md` or `context.md`) to `<data>/roles/custom/` with the same name, and edit the copy.
2. Keep every `$placeholder` the shipped file has (for example `$schema`, `$project`, `$catalog`, `$standards`): RCD fills them
   in. A copy that drops one, has a stray `$`, is empty, is a symlink or cannot be read is **ignored** and the shipped text is used,
   so a mistake cannot stop planning. The roles status (`GET /api/roles`) lists which files are customized and which copies are being ignored, and why.
3. The same safety scan applies: a copy cannot carry host paths or credentials.
4. After an update, compare your copy with the new shipped file. Your copy does not pick up new shipped sentences by itself; that
   is the trade for keeping your wording. The changelog says when guidance changed.

Standards work the same way: copy `packs/standards/starter.md` to `<data>/standards/starter.md` (see
[Starter standards](starter-standards.md)).

## How the update paths treat your data

- **Packaged updater** (Profile, Updates; or the helper on the command line): checks the signature, stages the new version beside
  the old one, refuses while work is running, stops the service, copies the database, switches `current` atomically and starts the
  service. The health check must report the new version from a process started after the switch; otherwise it rolls back to
  `previous`. The database is restored automatically only when its schema is the one the snapshot was taken on and the older version
  knows it; otherwise it is left as it is and you restore a snapshot on purpose. Older versions are kept (`keep_versions`).
- **The helper is pinned** outside the version folders, so an update does not replace it. When a release changes the update
  path, run `refresh-helper` once to adopt it; the release notes say so.
- Profiles, keys, tokens, reports and logs live outside the install root and are never opened by an update.

## After an update

1. Read the release notes for the version. Anything that changes the coordinator, standards or defaults is listed there.
2. If you use the managed guidance blocks, open the Agents roles preview. If it shows a change, review it and apply it, or leave
   your current block.
3. If you keep custom coordinator text or your own starter standards, compare them with the new shipped files.
4. Check the Updates panel for the log and the receipt, and confirm the footer shows the new version.

## For people building on this

These are the rules the update path relies on, and any change should keep:

- User data lives outside the install folder, and the program never writes into its own folder at run time.
- Schema changes are additive. A new setting or preference has a safe default (off unless the change says otherwise), and loaders
  ignore keys they do not know.
- Shipped text and user text are separate files. A user's copy wins and a broken copy falls back to the shipped one.
- An update never overwrites a file the user edited, and never reaches into an agent's own folder.
- Backups are taken before the switch, and a rollback restores the program; restoring data is a separate, explicit step.

## Settings involved

- `MAC_CONTROL_DATA_DIR` (the data folder; default `~/.rcd-control`; the install root is separate).
- Files under the data folder: `roles/assignments.json`, `roles/custom/`, `standards/starter.md`, `vault.key`, `agent-tokens/`.
- Operator API: `GET /api/roles` reports `custom` and `custom_ignored`.
