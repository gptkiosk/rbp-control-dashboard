# Changelog

All notable changes to Raspberry Pi Control Dashboard (RCD) are listed here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). RCD and the Mac Control Dashboard (MCD) share
major.minor, so a feature level means the same in both. Release notes on GitHub are generated from
the section of the version being released, and a release cannot be built without one.

Internal operator notes, private hostnames and personal identifiers are omitted by policy.

## [Unreleased]

## [0.6.38] - 2026-10-20

### Added

- **Model recovery settings:** choose ordered configured fallback routes, optionally include free/membership alternatives in future story maps, and explicitly allow configured memberships or separately approved paid API routes on a free-only installation. The paid toggle never authorizes a run by itself.
- **Local reliability advice:** repeated provider, timeout or invalid-output failures show possible costs and link directly to the recovery toggle. Healthier alternatives take priority without enabling paid routes automatically.
- **Shared-feature parity checks** and a source inventory covering planning contracts, bootstrap, recovery settings and task controls.

### Fixed

- **Bootstrap starts from a built-in editable plan.** Review and submit bounded readiness, configuration, verification and human-action stories without needing a provider to generate valid plan data. Starting setup again reopens its existing project.
- **Planning recovery keeps the same task:** one bounded output repair supplies validation feedback, then approved alternatives are tried. Project retry resumes its failed step; normalized free-route aliases cannot cause repeated automatic attempts.
- **Approved dispatch survives provider errors:** the app derives the approved dependency order itself if dispatch advice fails. Scope, route approval and human acceptance gates still apply.
- **Task controls match across dashboards:** failed stories offer the same free, membership and paid retry choices; timeouts retain their partial-work review requirement. Recovery alternatives must satisfy story risk rules.

## [0.6.37] - 2026-10-20

### Fixed

- **Planning retries reuse their task card.** Manual retries and automatic approved-route fallbacks keep run history together instead of creating another failed planning card each time.

## [0.6.36] - 2026-10-20

### Fixed

- **Failed project-planning tasks can be retried directly.** Retry the current failed planning step on its existing or another already-approved route without restarting completed planning steps. Project-owned tasks no longer show a generic board Run action that cannot retry their approved scope.

## [0.6.35] - 2026-10-19

### Fixed

- **Bootstrap planning now requires bounded stories:** the bundled setup brief asks for explicit instructions, scope and acceptance criteria, with read-only readiness checks separated from configuration work.
- **Malformed planning output can recover:** when a planning run succeeds at the process level but returns data that fails project validation, RCD retries the same planning step on the next already-approved route. The retry never starts project stories; invalid saved output is no longer offered as resumable.

## [0.6.34] - 2026-10-19

### Fixed

- **RCD run-ID recovery:** a completed in-memory adapter receipt no longer blocks a new durable run when a database restore reuses that numeric ID. Active-run collisions remain rejected.

## [0.6.33] - 2026-10-19

### Fixed

- **Projects no longer need to be deleted after a planning route fails.** Coordinator, planner and plan-review tasks retry failures, timeouts and interruptions on the next approved route. Free-only policy is rechecked before every attempt and never permits a paid fallback. When eligible routes are exhausted, the saved project remains available to edit and retry.

## [0.6.32] - 2026-10-19

### Fixed

- **Coordinator setup readiness** now tells the operator to apply Hermes guidance when it is missing and links directly to Agent roles.

## [0.6.31] - 2026-10-19

### Added

- **Coordinator setup kickoff:** Profile checks that Hermes is installed, assigned as Coordinator, guided and has a default model. When ready, it creates and opens a reviewable agent-platform setup project draft from the saved preferences; it does not start model work or alter platform configuration.

### Changed

- **Agent setup guidance:** Hermes is shown as the fixed Coordinator, while worker, reviewer and security labels remain configurable for other installed platforms.
- **Packaged Hermes guidance** now explains the in-app setup-draft flow, platform readiness checks, preservation of existing agent files, and human-only setup steps.

### Fixed

- **Manual Docker setup on Linux** now enables and starts the Docker service, adds the current user to its group, and shows the sign-out/sign-in and RCD service restart steps needed for a clean health check.
- **Docker health checks** distinguish socket permission errors from engine failures and show a short engine diagnostic.
- **Hermes health checks** recognize the installed pinned source commit when Hermes reports its upstream git-describe version.

## [0.6.30] - 2026-10-19

### Changed

- **Project and media actions:** human-assigned stories link to task details, their project Media studio, and approval guidance. The media flow keeps slot costs, estimates, and the explicit generation and review gates visible.
- **Clearer navigation:** project planning and approval dialogs link to in-app how-tos; missing fal credentials link to Settings; media prices link back to Projects; the setup prompt appears on Overview only.
- **Simpler operational pages:** Services, Agents, telemetry, Help, and Settings use shorter summaries and expandable technical details.

## [0.6.29] - 2026-10-19

### Fixed

- **A freshly installed managed Hermes could not start** under your own Hermes home: Hermes 0.22.0 keeps each install's dependency environment under the home that installed it, so the command wrapper (which runs with your `~/.hermes`) found none and stopped with "no dependency environment is committed". The wrapper now links that one per-install folder into the home in use (a profile maps to its root; an existing folder is never replaced).
- **Health check** shows the tool's own error line when it cannot run, and no longer calls a working managed copy "needs attention" because an older copy (for example Homebrew's `gh`) comes first on your PATH: that is a tip, with the `brew upgrade` suggestion.

### Added

- **Repair** on an Agent tools card whose command wrapper is out of date (installs made by an earlier release): rewrites the wrapper for the installed version. Nothing is downloaded and the version does not change.

||||||| 41540ed
- **See what was already made, and manage what it costs to keep.** The Media studio now shows every published slot as a gallery (the picture, or the clip with its player) with its size, and tucks Regenerate under *More* once something is done. A **Storage** line says what the published media and the unused takes take up, and **Clear unused takes…** deletes the generated takes of slots you have already decided (published or skipped), after a confirmation. Takes still waiting for your decision and all published files are never touched. New operator-only routes: `GET /api/media/published` (one published file of a slot named in `media/slots.json`) and `POST /api/media/clear-unused`; `/api/media/slots` now returns `storage` and each slot's `published_bytes`.

## [0.6.28] - 2026-10-19

### Fixed

- **Upgrading a tool you installed yourself (Hermes, `gh` from Homebrew) was always refused** with "The native version could not be verified". The tools helper put the macOS sandbox up before it re-read the tool's version, and the sandbox hides the home folder, so Hermes (in `~/.hermes`) could not run and every Upgrade was refused with nothing shown. The version is now read first and the plan reuses it. A test reproduces the sandbox.

### Changed

- **Settings is reorganised into three tabs**: *Settings* (preferences, Hermes on Discord, private credentials), *Updates & installs* (dashboard, agent tools, optional system tools) and *Maintenance & access* (housekeeping, report storage, bug reports, roles, GitHub). Old links such as `/profile#agent-tools` or `#github-settings` open the right tab. Explanations moved out to How-to links, hover text and the docs; controls are switches, a segmented appearance control and one compact row per credential instead of paragraphs and checkboxes.
- **One card for every installable thing**, the same one the setup checklist uses: a status mark, the version (`installed → latest`), one line of state, the buttons, a progress bar while it works, the log, and a **health check** with next steps. The dashboard update, each agent tool and each optional system tool use it.
- **Private credentials** are one list of cards (signed-in agent, OpenRouter, fal.ai, Discord bot, GitHub) merging the old key guide and the input fields: saved or not, one line on what it is for, a Get a key link, and Save, Remove, share and spending controls on the same card.
- **Tasks lanes are cards**: each status (In progress, Needs approval, Queued, Backlog, Failed, Done) is its own bordered card with a coloured edge, the status pill, a count badge and a one-line description, so the lanes are easy to tell apart. An empty lane drops its column header.
- **Every menu page opens the same way**: icon and title, one line saying what the page is, a **How-to** link into the documentation, and the page's actions on the right. Long explanations that did not need to be on screen (Agent access, billing and rate notes, model facts, ops trend, media, GitHub) are folded behind a quiet **Notes** line; the safety warnings in confirmation dialogs are unchanged. Projects trims its explanatory text and shows the four-step workflow as tiles. New How-to: *Read jobs and telemetry*.
- **Media: the studio and the price list are separate, and human media stories link to the studio with the cost up front.** The project's *Media* tab is now the **Media studio** (spent so far, left to make at the chosen tiers, waiting for review, and the spending acknowledgement in a bordered box). Agents → *Media* became **Media prices**, a price list; generating for a folder that is not a project moved into a folded section there. A human story about media (in the task row, the decision box and the card panel) shows a callout: published slots, about what is left to spend, what has been spent, and **Open media studio**. `GET /api/media/project/{id}` and `/api/media/slots` now return `cost` (estimates from the ledger and the slots' prices; fal's invoice is the truth).
- **Screen audit pass over every page in RCD and RCD**: Settings' Maintenance & access panels (Housekeeping, Bug reports, Agent roles, GitHub actions) get the same header as the rest, with a status pill and How-to link, and environment-variable instructions folded behind a Notes line; Services shows seven columns that fit (PID sits with the state, run counts share one column); Help and the Pi health page use the shared page header; Ops reports drops a duplicate list of report folders and folds its fleet-health notes; the by-hand update steps are folded; Projects loses a stray hint and punctuates the media banner. New How-to: *Keep the dashboard tidy*.

### Added

- **Agent tool health check** (`GET /api/agent-installs/health`): runs each installed tool's version command, says whether a new terminal reaches the managed copy, and lists next steps (upgrade, sign in, fix the PATH). It runs by itself after every install or upgrade.
- **Optional system tools in Settings**: **Install (All)** and **Upgrade (All)** for Python, ffmpeg, Docker (with Colima) and `gh` through Homebrew, as one job with a progress bar and log, the Homebrew prerequisite and its install command shown first, **Check for updates** (what Homebrew reports outdated), **Start Colima**, and a health check (`/api/host/readiness/tools`, `/tools/health`). On Linux it shows one `apt` command to copy and never runs it.
- Two How-to guides, *Install or upgrade the agent tools* and *Install or upgrade the optional system tools*.

## [0.6.27] - 2026-10-18

### Fixed

- The host readiness network check no longer reports OpenRouter as unreachable: Python's default client was refused with a 403 by OpenRouter, which is an answer from a reachable server. Any HTTP answer now counts as reachable, the check sends a normal User-Agent, and a real failure names its reason.

### Added

- **GitHub CLI (`gh`) in Agent tools**: a pinned, checksum-verified per-user install (no administrator rights) for Linux arm64 (tar.gz) and Apple Silicon (zip, with a new safe zip extractor that refuses links, devices and anything outside the folder). Its sign-in note warns that a signed-in `gh` stores a credential any full-shell agent can read; pushing a branch needs only the SSH key from Host readiness.
- **Website property** plans must leave a preview script (`tools/preview.sh`) that serves the site on the host's Tailscale address, a `/health.txt`, the clickable address of every page, a curl check and the stop command, so the human look sign-off has something to open and test.
- **Per-slot media resolution**: a slot in `media/slots.json` can set `resolution` (`1K`/`2K`/`4K` for pictures, `480P`/`768P`/`1080P` for MiniMax clips) so a small picture or a retro clip is not made and billed at the tier's full size; the request and the estimate both follow it. The Website property type now tells the planner how to keep the media bill small.
- **Host readiness installs and updates tools**: each missing optional tool says how to get it (Agent tools for `gh` and Node; a copy-paste administrator command on Linux). On a Mac with Homebrew the wizard installs ffmpeg, python, docker and colima, starts Colima, and **Update tools with Homebrew** runs `brew update` and upgrades only its own packages, as a one-at-a-time job with a live log, a clean environment and a time limit. It checks Homebrew and Colima first and, without Homebrew, shows its official install command for you to run.

## [0.6.26] - 2026-10-18

### Fixed

- The Setup wizard's host step is tidier: the workspace controls are grouped with a compact Save button, and the host readiness panel is rebuilt as an even list of cards with status badges, aligned actions, a two-column git identity form, and a public-key block that wraps cleanly on a phone.
- Host readiness on a Pi: **Test GitHub access** no longer fails with "Bad owner or permissions" on the system ssh config (the test now ignores system and user ssh config); "ready to deliver" now needs a key GitHub has actually accepted, not just a key that exists; Claude Code installed after startup is recognized as an agent that builds; and tools the dashboard installed are found in RCD's own tools folder, so the PATH row and Node detection no longer say nothing is installed.

## [0.6.25] - 2026-10-18

### Added

- A fix for tools the dashboard installed that a plain shell cannot find (typing `codex login --device-auth` on a Pi said *command not found*): the sign-in command shown on each installed tool now starts with its full path when its folder is not on the PATH, and Host readiness can put the installed tools on the PATH for new shells (**Put installed tools on my PATH**, idempotent, a marked block in `~/.profile` and `~/.bashrc`).
- **Host readiness** in Setup wizard step 1: a checklist of what the machine needs to build and deliver projects (workspace folder, git, git identity, GitHub access, an agent that can write code, optional tools, disk, and an on-request network test) with one-click fixes that each do one named thing: create the workspace folder, set the git identity, make a GitHub SSH key (the private half stays on the host) and test it. Hermes is shown as a manager, not a builder. Built so a new Raspberry Pi can be made ready without hand configuration.

## [0.6.24] - 2026-10-18

### Fixed

- The media panel's Generate buttons no longer sit dimmed and silent until the spending box is ticked: pressing one without it says what is missing and takes you to the box.
- Generation progress now sits under the slot's own button: a spinner and a status line (waiting, generating with fal's progress text, finished, or the failure), and the button reads Generating… and stays off until it finishes. The list at the bottom of the panel is gone.

### Added

- **Other** project type for work that does not exactly fit Web app, Packaged app or Website property: the plan says which type it resembles and which of that type's gates it keeps or drops.
- Every project type now asks for documentation that shows the application: a README with a hero screenshot, a Mermaid architecture and data-flow diagram when the project is more than a local install, and a screenshot and how-to for each application area beyond installation and sign-in. Screenshots come from a Playwright script in the repository run by a person or the pipeline (agents cannot run a browser); the plan gets warnings if there is no README story or no such story. The browser-check warning no longer fires for an agent that only writes the screenshot script.
- The project consultant asks for the project type before it starts (a required dropdown with Other), tells the consultant the type's planning guidance, says in the brief which type it is, and hands the type to the plan when you review the brief.
- Every project type now asks that the project ends in the remote repository: the working folder is a clone of the repository (not a scratch folder), and the plan has a delivery story (push the project branch, open the pull request) and one that reads the pipeline result. A plan without one gets a warning. The repository is public for an externally packaged MIT-licensed app and private for a proprietary one, and the plan says which. The first website project finished with nothing pushed because it ran in a scratch folder.
- Help, the help chat and the docs now cover project types (picking one, plan checks, the website guides), making media with fal (tiers, progress, Another take, accepting and publishing), media spend (estimates are an upper bound, repeats and unpriced runs are shown), creating or replacing the fal key (fal fixes its model list at creation), and Accept anyway. Five new how-tos; the project consultant chat is told the project types and the media rules.

## [0.6.23] - 2026-10-18

### Fixed

- Media spend was under-reported: Veo clips had no price, so only images were counted (about $2 against $16.88 on fal's own usage table). Every model now has a price checked against fal's billing, 2K pictures are priced at 1.5 units, and a run with no price is shown as unpriced instead of zero.
- Double generation: a slot with generations still waiting for review is no longer generated again unless you choose Another take, the panel confirms each request with its estimated cost, and the spend line shows how many runs were repeats.

### Added

- MiniMax H3 Max and H3 Max Turbo clip models (text to video, image to video, and start-and-end-still transitions), about a fifth to a half of Veo's cost. They are the standard and draft video tiers; Veo 3.1 is the premium tier. fal fixes a key's allowed models when it is created, so a key made earlier needs replacing: the key guide now lists the exact endpoint ids to add, and says so.
- Project types can set the media tier the panel starts on. A website's background clips start on the cheapest video tier.
- A website design guide ("Making a stylized website that needs little adjustment") that the website property type hands to its planner and agents: one visual language (the approved hero still is the style reference for every other picture), 16:9 photographic cards, wide establishing clips with the ambient loop as a texture, layout rules that broke on a real site, and a responsive review at eight widths in both themes. The type gained matching failure points, planner text and a plan check for the responsive review. A companion guide records the starting spacing, sizing and timing values (1.5 second theme crossing, header and card sizes, breakpoints) for the design direction story to carry into DESIGN.md as tokens, plus the collapsible phone menu and em media-query rules.

## [0.6.22] - 2026-10-18

### Added

- **Accept anyway** on a failed story whose agent finished and reported unfinished work. You give a reason (at least ten characters); the agent's own report and your reason are recorded as the handoff (marked as accepted despite the report, with its gaps still listed), the decision goes in the project ledger, the run stays failed in the history, and dependent stories are released. A story that crashed or timed out has no report to accept and still needs a retry. `POST /api/projects/{id}/stories/{card}/accept-despite-report`. It exists because some checks cannot run where an agent works (a browser, a loopback server), so an honest "unfinished" would otherwise block the project for good.
- All three project types now flag an agent story that asks for rendering, a browser console check or screenshots, and tell the planner to keep agent verification static and leave rendering to the human preview.

## [0.6.21] - 2026-10-18

### Added

- **Media review is part of the project.** A project whose working folder has media slots gets a **Media** tab, and a banner on the project page while slots still need a decision. A human story about media (and the board card for it) shows **Open media review** with where the slots stand, and its decision box shows a summary you can use as your decision. The same panel still opens from Agents, Media. `GET /api/media/project/{id}`.
- **Persistent, systematic decisions.** Each slot ends published or skipped. **Accept and publish** (one click), **None of these: make another**, **Skip: use the fallback** and **Restore** are all recorded in `media/decisions.json` in the project folder (what was generated, accepted, rejected, published or skipped, and by whom), and mirrored into the project's ledger so the project remembers them. The panel groups slots as waiting for your decision, not made yet, skipped and published, and says when every slot is decided. `POST /api/media/decision`.
- **Generations survive a restart.** Every submission to fal is journaled; a generation that was in flight when RCD restarted is finished at the next start (its result is fetched and saved as a candidate) or marked failed in the ledger, and is never resubmitted.
- **No accidental repeats.** RCD refuses to regenerate a slot that is published unless you choose Regenerate, and refuses a second generation for a slot while one is running. Results appear as each job finishes, not when the whole batch does.

### Changed

- The media panel is a review flow: published slots are collapsed with a ✓, candidates show as thumbnails or players with an Accept button, and Generate only appears for slots not yet made (or after you choose Regenerate or Make another).

## [0.6.20] - 2026-10-18

### Added

- **Publish in the media panel.** After **Use this one**, a **Publish** button validates and converts the picked file (a resized JPEG for a still; silent WebM and MP4 with a seamless loop blend and a poster for a clip), then records its tool, model, prompt and date in `media/provenance.json` and `assets/ART-INVENTORY.md`, with RCD's own code (nothing from the project folder is run). No terminal step is needed any more; the project's `tools/media/media.py ingest` still does the same thing. `POST /api/media/publish`. A draft too small for its slot is refused with the reason. Needs `ffmpeg` on the host.

### Fixed

- Feedback now appears beside the button you pressed. **Use this one** worked but confirmed at the very bottom of a long panel, so it looked like nothing happened. The chosen candidate is marked, the inbox file is shown with a Publish button, and errors and results show under that slot.

## [0.6.19] - 2026-10-18

### Added

- **Candidates are shown in the media panel**: each generated image is a thumbnail that opens full size, and each clip is a small video player, so a visual choice can be made where the **Use this one** button is. Served by an operator-only viewer (`GET /api/media/candidate`) that returns only real `<slot>-<number>` media files in the project's `media/candidates` folder.

### Fixed

- A slot no longer claims another slot's candidates. `hero-light` (a video slot) was listing the candidates of `hero-light-still`, and **Use this one** could copy a still into the video slot. A candidate now has to be exactly `<slot>-<number>.<media extension>`, a regular file directly in `media/candidates` (links are refused), for listing, viewing and picking.

## [0.6.18] - 2026-10-17

### Fixed

- Generated stills are now made in the shape of their own slot. The media panel asked every image for a wide 21:9 frame, so the square property-card illustrations and the 16:9 About vignettes came out the wrong shape. The aspect ratio is now the supported one closest to the slot's width and height (a 1200 by 1200 card is 1:1, a 1600 by 900 vignette 16:9, a 2560 by 1100 hero 21:9), and an explicit choice still wins.

## [0.6.17] - 2026-10-17

### Fixed

- A branch grant no longer reaches a story where its clone does not exist. A project in a plain scratch folder that still had a grant was told "a story is finished only when its work is committed on the branch", so a story that did all its work reported itself unfinished and failed. A grant now applies only to clones that are real git working copies under the story's working directory; with none, the story gets no git context and the normal no-push rule.
- Claude stories can run the usual project checks without approval in an unattended run: `python3 -m unittest`, `python3 -m py_compile`, `python3 -m json.tool`, `python3 tests/...` and `xmllint`, in addition to the isolated forms that were already allowed. Plans and projects naturally write the plain forms, which previously needed an approval nobody could give. This is not a general shell.

### Added

- A **Media** button on the Agents page opens Billing & rates straight to the Media models section, expanded, so the fal models, prices and Generate panel are one click away. Billing & rates still opens with that section collapsed.
- **Generate all missing** in the media panel: one tier, one price total (models with no listed price are called out) and one confirmation, then one request per slot that still has nothing published, no candidate and no approved still to wait for. Clips whose stills are not published yet are counted as waiting, so run the stills, pick and ingest, then run it again for the rest.

## [0.6.16] - 2026-10-17

### Added

- **Project types**: choose Web app, Packaged app or Website property when you create a project (RCD suggests one when the brief clearly fits). The planner is told the type's how-to and known failure points, and the plan review shows **Plan checks** for the type: whether there is a file verification story, a preview checkpoint before a human approves how something looks, the human sign-offs, and whether a story needs a container engine or generated media that an agent cannot supply. Warnings only; nothing blocks. Types are data files you can extend. `GET /api/project-types`, `POST /api/project-types/suggest`, `GET /api/projects/{id}/checks`. See `docs/configuration/project-types.md`.

### Changed

- **Delete project** now works only on a closed or completed project, so Close (and its cleanup) always comes first. A draft, review or failed project must be closed before it is deleted.

## [0.6.15] - 2026-10-17

### Fixed

- A good plan is no longer thrown away over small slips from a free planner model. Before validating a planner's answer RCD now drops a route with an empty model (and clears routes on human stories, which are not run), drops blank `touches` entries and maps near-miss work kinds such as `tests` to `test`. Unknown work kinds and real path problems are still refused. A plan that already failed this way can be recovered with **Resume saved plan**, without running the planner again.

### Changed

- **Close project** now offers to delete the project in the same step: after the reason, one confirmation deletes the project with its tasks, ledger and saved records (the working folder is kept). Cancelling keeps the closed project and ledger as before.

### Added

- **Delete project** on any project that is not live (closed, complete, draft, in review or failed). It removes the project from the library together with its tasks and run history, ledger records, deliveries, standards proposals, ledger file, saved outputs and branch grants, so nothing keyed to its id is left to carry over when the id is reused. The working folder and the files in it are never touched. `POST /api/projects/{id}/delete`.

## [0.6.14] - 2026-10-17

RCD catches up with MCD 0.6.11 to 0.6.14 in one release.

### Changed

- Spending limits are off by default. The default run budget and host cap are gone, a run no longer needs a reviewed price, and paid routes on Codex, Hermes and OpenClaw can start once free-only is switched off. RCD still starts free-only. Paid and unpriced runs record a plain
  disclaimer that RCD does not limit spending and that you should set a credit limit with your provider.
- A Done story can be rerun (**Rerun same story**) while nothing that depends on it has started, so a story that was accepted wrongly, such as art that never got embedded, no longer forces a new project revision. Once a dependent has run, reopening is refused as before because its handoff would be invalidated.
- The coordinator's planning prompt now treats anything judged by looking (pages, art, themes, layout) as needing proof: a file-level verification story, then a localhost preview checkpoint with a clickable URL per page and state, then the human decision. The plan reviewer asks for these steps when a plan lacks them. Prompt pack version 9.

### Added

- **Spending & limits** in Agents, Billing & rates: one place, stored in the app, to turn on a reviewed-price requirement, a per-run dollar cap, or the Claude-only rule for paid runs. See `docs/configuration/dispatch-policy.md`.
- **Keys and access** guide at the top of Profile, Private credentials: every key with its level (required for basic use, recommended, optional), what it is for, whether it is in place and where to get it. Basic use needs only an agent signed in.
- A **key check before a project is created**: if the project's name or brief suggests a key that is not saved (generated video or images), a dialog says what, why and where to get it, lets you paste the key there, and lets you continue without it. Only having no agent at all blocks. `GET /api/keys` and `POST /api/keys/check`. See `docs/configuration/keys-and-access.md`.
- **Media models (fal.ai)** in Agents, Billing & rates: a catalog of the image and video models used for site art and motion, with endpoint id, billing unit, quality tier (draft, standard, premium), notes and fal's listed price where it has one. You can enter your own price per model. A **fal.ai key** can be saved in Profile, Private credentials (encrypted, write-only, never given to agents).
- **Generate media from RCD**: pick a project folder with `media/slots.json`, a tier and a count, acknowledge the spend, and RCD calls fal.ai with your saved key and saves the results as candidates in the folder. The key never leaves RCD and no code from the project folder is run; every run is recorded in a ledger with its estimate. Needs `ffmpeg` on the host for the best results. See `docs/configuration/media-models.md`.

## [0.6.10] - 2026-10-16

### Added

- `scripts/probe-agent-capabilities.py` checks what each installed agent can really do in an Edit-mode scratch folder (write files, run a syntax check and a unit test, try git), using RCD's own launch
  arguments, and cleans up after itself. Run it after upgrading an agent runtime or RCD.

### Fixed

- A Claude story in a scratch-folder project can run its own checks. In Edit mode Claude could write files but was allowed no shell commands unless the project had a repository grant, so a story
  wrote its files and then could not run `node --check` or its tests, and reported itself unfinished (the first story of a scratch project did exactly this). An Edit-mode Claude story without a grant
  can now run test and syntax runners (`pytest`, `unittest`, `py_compile`, `json.tool`, `node --check`, `npm run test/type-check/build`, `vitest`, `bash -n`, `shasum`); git, the network tools and
  arbitrary shell stay denied, and a Read-mode story still gets no shell. The harmless helpers models add to compound commands (`echo`, `printf`, `ls`, `cat`, `wc`, `head`, `tail`, `diff`, `sort`, `test`)
  are allowed too.
- The defaults work and security is configured. `MAC_CONTROL_AGENT_PERMISSIONS` (default `working`) lets an Edit story run checks, harmless helpers and package installs and gives a Codex Edit story the
  package indexes and GitHub in its sandbox even without a git grant. `strict` allows only the commands in `MAC_CONTROL_AGENT_EXTRA_COMMANDS` and gives Codex its plain sandbox;
  `MAC_CONTROL_AGENT_EXTRA_NETWORK_DOMAINS` adds hosts Codex may reach. Git grants and the push and merge denials apply either way.
- A Hermes Edit story is told its task folder first, because Hermes' terminal starts in the folder set in its own config.

## [0.6.9] - 2026-10-16

### Changed

- Creating a project is a button push with defaults that work. The working directory now defaults to the scratch area: MCD makes a new private folder for the project, every
  story shares it in order, and there is no repository, branch, branch grant or hook to set up (the usual source of a project that could not run). Name and brief are all the New
  project dialog asks for; the planner, preference, build mode and working directory sit under **Choices (the defaults work)**. Choosing a repository folder is still a specific
  choice and behaves as before, with a branch grant. The consultant chat defaults to the same scratch area, so a brief written in chat creates its folder automatically. The scratch
  area is the managed workspaces folder, which is an allowed working-directory root by default.

## [0.6.8] - 2026-10-16

### Changed

- The project consultant chat and the planner are told how project agents really work, so a brief written in chat plans well: edit versus read mode, coding agents
  cannot run containers, a plain scratch folder is the simplest working directory for a demo, keep plans small, and what to do when a free model fails. Prompt pack
  version 8; a planner prompt you edited under `roles/custom` is used as you wrote it.

### Fixed

- A returned plan can no longer leave a story that implements or writes documentation read-only. A free planner marked every story of a project Read, so none of them
  could commit. RCD now sets such stories (and only those, never a human or review story) to Edit when the plan comes back, and says so in the project memory.
- A story whose run timed out can be retried again. After a timeout the dispatcher refuses every new attempt (MCD cannot tell what the attempt changed or whether the
  provider is still working), and nothing let you authorize one: Rerun, another free model, Haiku or Luna and Pay all queued the story and the dispatcher failed it
  again with no run and no message. The project API now takes `acknowledge_timeout` on `retry`, `go-free`, `low-cost-retry` and `pay-retry`; it is required for a timed-out story (RCD's task panel has no retry buttons yet; MCD's shows a checkbox),
  is recorded on the timed-out run and in the project ledger, and covers that run only. Without it the dispatcher still fails closed.

## [0.6.7] - 2026-10-16

### Added

- A failed free-model task has a way out through the project API: another configured `:free` model on the same OpenClaw agent (`go-free` now also accepts a
  provider timeout or limit on an OpenClaw story), the low-cost subscription models Claude Haiku or Codex Luna (`low-cost-retry`, optionally switching a read-only
  task to edit mode with an acknowledgement), and a paid OpenRouter model for that task only (`pay-retry`). Each choice is an operator-approved amendment recorded
  in the manifest and the ledger; the price check, budget caps and free-only setting still apply, and no Google BYOK route is added. RCD's task panel does not have
  the retry buttons yet; MCD's does.

### Fixed

- The Agent tools panel brings its confirmation into view when you click Upgrade or Install. The confirmation used to appear far below the list of tools, so the
  click seemed to do nothing, and the same applies to its notice and error lines.

## [0.6.6] - 2026-10-16

### Fixed

- Closing a project no longer leaves its tasks behind on the board. Closing offers to remove the project's tasks in the same step, a Closed project has
  **Remove tasks from the board** for later, and each queued, Backlog, Review or failed task of a Closed project can be deleted on its own (before, only failed
  ones could). The ledger keeps the handoff, incident and decision entries; the tasks' run history is deleted.
- Leftover queued tasks of a Closed or Complete project no longer block an in-app update.

### Changed

- The planner is told what a sandboxed coding agent cannot run. A Codex story cannot reach the local container engine, so the plan no longer asks an edit story to
  build an image or run a container. Container and pipeline files are planned as an edit story that ends with the files committed and the static checks passing, and
  the build and smoke run are planned as a later verification story for a person or a read-only agent. Prompt pack version 7. A planner prompt you edited under
  `roles/custom` in the data folder is used as you wrote it, so add the same rule to your copy.

## [0.6.5] - 2026-10-16

### Fixed

- An update is no longer blocked by the queued stories of a paused project. A failed story leaves the stories after it queued, project stories cannot be moved
  to Backlog by hand, and pausing the project did not change the count, so the update check stayed blocked until the project finished or was closed. Queued stories
  of a paused project cannot start and are no longer counted. Running tasks, plain queued tasks on the board and the stories of an active project still block, and
  the message now says to pause the project.

## [0.6.4] - 2026-10-16

### Fixed

- A Codex story with a git grant can create its project branch and commit again. The permission profile that replaces Codex's plain workspace sandbox left `.git`
  read-only in current Codex builds, so a story stopped with "could not create its ref under `.git/refs/heads`" before doing any work. The profile now makes `.git`
  writable while the repository's hooks folder and config stay read-only, so an agent can still not rewrite the operator's hooks or credential helper. A test runs
  the real Codex sandbox (when Codex is installed on a Mac) so a future Codex change shows up here and not in the middle of a project. A story stopped this way can
  be retried with **Rerun task**.

## [0.6.3] - 2026-10-16

### Fixed

- A submitted plan no longer stops with "Hermes dispatch order does not exactly match the approved stories." Hermes only chooses the order between orders the approved
  dependencies already allow, so its answer is now advice. A phase key or a repeated key in it is ignored, and an answer that leaves a story out or breaks a dependency
  is replaced by the approved plan's own dependency order, with a note in the project memory saying so. No story, route or scope changes. A project already stopped as
  `dispatch_failed` can be submitted again with **Review & submit**.

## [0.6.2] - 2026-10-16

### Fixed

- Replanning no longer hands you the same plan back. The planner was shown the stories already on the map along with the brief, and a free model returned them
  unchanged even after the brief and the working directory changed (so a Docker project kept its old packaged-app stories and failed the new repository's
  standards). The planning request now has **Plan from scratch**, which keeps the current stories out of the planner's view; it is ticked for you when the current
  plan fails the standards.
- The review and submit dialog is readable. It shows the working directory, preference and build mode as a short facts table, a short explanation, the standards
  check, the stories and the billing notes in folded sections, and the approvals and buttons in a padded, bordered action row, instead of one long unspaced
  column of text.
- The standards check is shown before you submit, with one line per story, and the areas a repository lists are shown once instead of after every story. A plan
  that fails it cannot be submitted from the dialog, and refusals from the server keep their line breaks.
- The panels on a project page (heading, planning progress, repository access, schedule, brief) now have even spacing between them.

## [0.6.1] - 2026-10-16

### Fixed

- Look and feel. The bug report dialog now uses the app's standard padded dialog layout (header with an icon and close button, labelled fields, a bordered
  action row) instead of bare text and stacked buttons, and the preview block and the sent-or-open-GitHub buttons are laid out properly.
- The Updates panels are roomier and clearer: titled Available and Rollback blocks with dividers, padded release and confirmation cards, proper spacing for
  checkboxes and text, bordered action rows with the primary button on the right, and an update progress card with state chips. This covers the packaged
  update panel on both products and the checkout update panel on MCD.
- Every log, command output and exact-text window (update logs, release notes, run and chat live output, agent tool logs, service logs, patches, evidence,
  GitHub request previews and reports) now shares one style: the same padding, border, monospace font, line height and scroll height.
- The new project panels (Repository access for agents, Parallel build) have the same vertical spacing as the others, and the bug report preview says
  "1 email" instead of "1 emails". Housekeeping no longer runs "After hours:" into the next word.

## [0.6.0] - 2026-10-16

New in 0.6.0: a bug icon in the header, repository bootstrap for projects that need a new private GitHub repository, and an opt-in parallel build. Bug
intake, Hermes repository proposals and the parallel auto-accept gate are all off until you turn them on, and a project builds serially unless you switch parallel on.

### Added

- A Discord alert when a project's planning or story hand-out stops after its run succeeded, for example when the plan is refused for a
  missing field or a bad dependency. Until now only failed runs alerted, so a plan that came back and then failed validation was
  silent. One alert per project, revision and reason; turn it off with `[projects] enabled = false` in `alerts.toml`.
- A bug icon in the header. It opens a short form, shows the exact issue that would be sent (with paths, emails, addresses and
  key-shaped text removed and listed), and then either files it on the product's official GitHub repository as your signed-in account
  (through the same guarded GitHub action as other writes, after you confirm) or opens a prefilled GitHub page for you to submit under
  your own account. No token, relay or hosted service is involved. See `docs/configuration/bug-reports.md`.
- Bug intake (off by default, `MAC_CONTROL_BUG_INTAKE_ENABLED`). Issues a maintainer has labelled `bug-report` and `accepted` become one
  read-only triage task each, tagged `release-blocker` (label `break-fix`) or `release-queued`, with the report quoted as untrusted
  evidence. A Profile panel lists new tasks and the reports still waiting for a maintainer's label.
- Build in parallel, a switch chosen when a project is created (off by default; off builds one story at a time in dependency order). On, the planner is told to
  plan branches that change different files, with a `touches` list per editing story and integration stories where branches join (role pack version 6).
  Submission refuses two stories that can run together but overlap, a longest-chain-first build order, a schedule readout (longest chain, best-case
  speed-up, width, and the real overlap once runs finish), integration-story instructions, and an optional lighter gate
  (`MAC_CONTROL_PROJECT_AUTO_ACCEPT_LOW`, off by default) that accepts low-risk stories whose changes stay inside their declared files. See `docs/PROJECTS.md`.
- Repository bootstrap. Hermes can propose a new private GitHub repository for a project (`propose_repository`, behind a new Profile switch), which
  waits in Profile under "GitHub actions waiting for you" with its exact request. Approving creates it under your account, always private, with an
  initial README commit, and adds it to the install's GitHub list. A project's "Repository access for agents" form grants agents one branch,
  `project-<id>/<name>`, never main. The planner starts a plan with the approval and setup steps when a repository is missing (role pack version 5).
  See `docs/configuration/repository-bootstrap.md`.
- A "Delivering a containerized web app, local first" guide and a paragraph in the coordinator context (role pack version 4): a private
  repository created first, a pipeline on Linux runners that builds and tests the image, a local run on Colima, and repository setup
  planned as the first step with the repository creation, first push and secrets left to a person.

### Fixed

- The Updates page no longer calls a normal update interrupted. While the helper is staging or removing a version (minutes on a Raspberry
  Pi) the page used to warn "An earlier update was interrupted" and list the folder being built or removed as "only partly staged".
  Both are shown only when no helper is working, so a real interruption still says so. After a successful update the release you just
  installed is no longer offered again under "Update to ...".

## [0.5.5] - 2026-10-16

### Fixed

- A failed project task can be deleted as soon as its retry is queued or running. Retrying from Projects creates a new task, and the old
  failed one used to stay greyed out until the retry finished, which looked like a duplicate you could not remove. The retry itself stays
  protected, a lone failed task is still kept (it holds the only record), and the project ledger notes the deletion.
- The consultant no longer ends every reply with another question. Once you say you are done it confirms and waits, and the brief it
  writes has no closing question: anything still undecided becomes a stated assumption or a human decision story (or is dropped if it
  does not change the plan), so it reaches the coordinator as work instead of a dangling question.
- The planner is told that every story needs its instructions in the description field. A free planner returned a story with scope and
  acceptance but no description, and planning stopped with "needs instructions". (Coordinator role pack version 3.)
- Planning no longer stops with "Dependencies must connect different stories in this project" when the planner orders phases against each
  other or makes a story depend on its own phase. Those links are dropped from planner proposals (story order is kept; a dependency on a
  key that does not exist is still refused, and your own edits are checked as written). Because the saved plan is read again by **Resume
  saved plan**, a project that failed this way can continue from the saved proposal without another planning run.

## [0.5.4] - 2026-10-16

### Fixed

- Planning runs and board tasks on the default free model now start too. 0.5.3 fixed new chats; a project plan run, a task made from a form
  or an older saved task still carried the generic `openrouter/free` and was stopped with `PRICE_UNKNOWN` ("Budget check stopped the
  run"). The dashboard now replaces that default with the free model Hermes or OpenClaw is set up with when a task is created or edited,
  when a plan is requested, and when a saved task starts, so retrying a task that failed this way works without editing it. A model you
  name is never replaced, and a paid default is never chosen for you. Your saved keys were never involved.

## [0.5.3] - 2026-10-16

### Fixed

- Chats with Hermes or OpenClaw on the default model now start. The default, `openrouter/free`, is a generic name that neither agent
  lists, so the dashboard refused every new chat with `PRICE_UNKNOWN` (0.5.2 made that refusal readable; this removes the cause). A new
  chat on that default now uses the free model the agent is set up with (its own default, for example the one `hermes setup` chose),
  shown on the chat as the model in use. A model you pick by name is never replaced, and a paid default is never chosen for you. A
  chat created earlier that has not run yet is corrected the same way when you send its first message.

## [0.5.2] - 2026-10-16

### Fixed

- The project consultant's first message no longer waits for an approval nobody knew to give. The consultant opens with long guidance and
  your installation's standards, which mention releases and deploys, and the approval check read all of it as if you had asked to
  publish something. The guidance now travels as background beside your own words, and only your words are checked. The chat shows
  your message with a note that background was sent with it, and a "Sending your goal" line while the first message goes out.
- The project consultant now works as a conversation. It answers what you ask, asks a few clarifying questions at a time, and keeps going
  until you choose **That’s enough, write up the plan**, which asks for the brief from the whole discussion and opens it for you to edit
  before anything goes to the coordinator. The chat no longer shows the consultant’s instructions or your installation’s background.
- A chat on a model the dashboard has no reviewed pricing for (for example Hermes on `openrouter/free` when Hermes does not list that
  model) no longer looks sent and then fails with `PRICE_UNKNOWN` in the bubble. The dashboard now says so before the conversation
  starts: which agent and model, that the route has not been reviewed, and which free models Hermes is set up with so you can choose
  one in Profile, AI defaults. No empty thread is left behind.

## [0.5.1] - 2026-10-16

### Added
- After-hours housekeeping. Set `MAC_CONTROL_HOUSEKEEPING_AUTO` to the kinds you want cleaned up overnight (`stale_approval_wait`, `old_update_backup`) and the server applies exactly those fixed actions once a day inside a window (default 1 to 5 local time). Off by default. Each finding is re-checked at that moment, a database backup is taken before any row changes, and every action is audited as `after-hours`. The Housekeeping panel shows the last run; Hermes can read and explain the status.

## [0.5.0] - 2026-10-15

### Added
- Coordinator scorecard, in a new section of the Telemetry page. Every approved plan is scored by fixed checks (schema, the job envelope, estimates against size, checkable acceptance criteria, bounded scope, dependencies, route reasons, no stories too big to run, a review for high-risk work, and the standards' floors), compared with what the coordinator returned (how many nodes a person added, removed or changed) and recorded with the planner, the Delegator and the coordinator wording in effect (a version label such as `v2`, `+custom` for your own copies, and a hash). The page shows plan score by planner and by wording with edits per plan, first-pass completion and estimate error, so a change can be compared with the one before it. Eight fixed, general briefs and a scoring route let you try any model or wording change on the same plans. See `docs/configuration/coordinator-scorecard.md`.
- A weekly model watch (off by default; `MAC_CONTROL_MODEL_WATCH_ENABLED=true`). It reads OpenRouter's public model list and, only when something is new, leaves one Backlog card with the sources and exactly what differs: first, models your catalog lists as free that are no longer free, then new free models and changes. It edits nothing: adopting or dropping a model stays a reviewed change. The Models section shows when it last ran. See `docs/configuration/model-profiles.md`.
- Service actions on the Services page: **Why** (a plain explanation, the safest next step and the job's own log as evidence), **Run now**, **Restart** and **Remove** (stops the service for now; the unit file is untouched; you type the label to confirm). Only listed services can be acted on, the dashboard's own service is protected, and every action is audited. See `docs/configuration/service-actions.md`.


## [0.4.8] - 2026-10-15

### Changed
- The project consultant chat now starts with the same knowledge a plan run gets: how the software is delivered, which agent runtimes are installed here and the spending policy, the standards that apply to the chosen working directory, the methods and practices (development practice, hosted and packaged delivery, application security) and the track record of the models it could recommend. It writes the brief so the coordinator can plan from it directly (approach and methods, risks by standards area, security considerations, model and route considerations). You can keep your own copy of any guide in the data folder. It is advice for the conversation and authorizes nothing; if it cannot be read the chat starts without it. See `docs/project-consultant.md`.

## [0.4.7] - 2026-10-15

### Added
- The coordinator now uses model profiles. A planning request includes a compact paragraph on the models it may choose (free or paid, context, tool support, and the track record here by kind of work, with unproven stated plainly), and the submit review shows non-blocking route advice for each story: a proven poor record for that kind of work, no listed tool use for work that edits files, or an unproven model on medium or high risk work. The gates, risk floors and approvals still decide; your own coordinator wording keeps working. See `docs/configuration/model-profiles.md`.

## [0.4.6] - 2026-10-15

### Added
- Model profiles, in a new Models section of the Telemetry page: what each model can do (free or paid, context size, tools, structured output, reasoning, price), how it has done in your own runs (runs, success rate, median time, cost, by kind of work, with a model shown as unproven for a kind until it has 10 runs) and notes people add with a source and a date (stale after 90 days). A Refresh free models action reads OpenRouter's public model list and shows what is new, what is no longer free and what changed, without editing your price catalog or any route. RCD ships no opinions about which model is better at what. The last read and your notes are kept across updates, and `MAC_CONTROL_MODEL_REFRESH_ENABLED` can switch the refresh off. See `docs/configuration/model-profiles.md`.

## [0.4.5] - 2026-10-15

### Added
- Ask Hermes to add to a repository's standards. With the new Profile switch on, Hermes can read a project's standards and propose an addition to the repository's standards file: a risk area, a check, a security bullet or a tightening rule. The server proves it is only an addition (nothing removed, reworded, lowered or loosened) and shows you the exact diff on the project page. Approving creates a new branch in the repository for you to review and merge; your current branch and files are not touched and nothing is pushed. See `docs/configuration/standards.md`.

## [0.4.4] - 2026-10-15

### Added
- You can keep your own coordinator wording across updates. Copy a file from `packs/roles/delegator/` into `roles/custom/` in your data folder and edit it: your copy is used instead of the shipped one, survives every update, and a copy that would break planning (a dropped placeholder, a stray `$`, empty or unreadable) is ignored in favour of the shipped text. The roles status lists customized and ignored files.
- A guide, `docs/configuration/upgrades-and-your-data.md`, says what an update keeps, replaces and never touches: settings, the database, preferences, credentials, the coordinator assignment and guidance, standards, project memory, and what your agents know.

### Fixed
- Agent settings are now covered by tests for every agent (Claude Code, Codex, Grok, Hermes, OpenClaw): installing, updating, rolling back or removing a managed agent tool, applying role guidance and starting a run leave each agent's own settings, credentials and memory untouched. The guide says exactly what RCD writes into an agent's folder (only the marked guidance block).
- A profile saved by a newer version (for example after a rollback) no longer breaks the profile page in an older one: preferences this version does not know are ignored when loading, and missing ones take their defaults.

## [0.4.3] - 2026-10-15

### Changed
- Repository standards now shape plans. When a project's repository has `docs/development/standards.md`, the planner is told the repository's areas and their minimum risk, every story's `area` must be one of them, its risk may not be below the area's minimum, and a high-risk story may not use a free-only route. A plan that breaks these is refused at approval with the reasons. A missing or unreadable file still only warns. See `docs/configuration/standards.md`.
- Starter standards: RCD now ships general standards, so a project is useful out of the box even when its repository has none. They cover areas with a minimum risk, checks for the definition of done and a security checklist for high-risk stories, plus plain guides on application security, development practice and delivering hosted and packaged apps. They apply when a repository has no standards of its own, you can change them by placing your own copy in the data folder, and the project page says which standards apply. See `docs/configuration/starter-standards.md`.
- The repository's checks (its Definition of done table) are frozen on the approved plan revision and added to the definition of done of every agent story that writes, so the agent has to run and report them. The Delegator's planning guidance now also explains how to choose area and risk and to cite the standard in the route reason.
- Telemetry can be cut by property (the standards' property the plan was approved under): a Property filter and a "Work by property" chart with each property's first-pass rate and median time.

## [0.4.2] - 2026-10-15

### Added
- A reference page, `docs/development/distribution.md`, for how this product reaches users: it is packaged code users pull from public releases, not a hosted service. It covers the steps from changelog and version to tag, signed package, draft verification and publishing, what makes a version offered to users, what users do, and what to do about a bad release. The Delegator's guidance now includes this model, and treats publishing a release as at least a medium-risk act.
- Repository standards, matching MCD 0.4.8: a project reads `docs/development/standards.md` from its working directory, shows on the project page which standards it is working under (the property, the number of areas and checks, and the file's hash), and records that on each approved plan revision. The two tables in the file (Definition of done, Risk by area) are parsed by fixed code. A missing or unreadable file is a warning and planning goes on without it. Nothing is fetched and nothing outside the working directory is read. See `docs/configuration/standards.md`.

## [0.4.1] - 2026-10-15

### Added
- Telemetry: a Jobs and telemetry page, matching MCD 0.4.7. It shows how work is going by job (one approved plan revision), kind, risk, size, route, who it is assigned to (a person or an agent), agent and model: unassigned, in progress, waiting for you, completed, estimates missing and failed work; as charts you can read at a glance (donuts for workload by status and by route; stacked bars for work by assignee, by job, by model and by kind; completed per week; median time per kind), with the numbers on hover. The detailed tables (jobs, agents and models with success rate, median time, tokens, reported cost, API-equivalent cost and how often a different model served a run than the one requested, and kinds of work) are folded away until you open them. Read-only and computed from the existing records, so it stays light on a Raspberry Pi. See `docs/configuration/telemetry.md`.

## [0.4.0] - 2026-10-15

RCD adopts the 0.4 feature level for the parts that make sense on a Raspberry Pi: update progress, Housekeeping and the job envelope, matching MCD 0.4.5 and 0.4.6. The MCD-only checkout updater is not part of it; RCD updates from its signed package.

### Added
- The Updates panel shows an update step by step, as the MCD checkout updater does: download, verify the signature, prepare the release on the host, safety checks, back up your data, switch, restart and check health, finish. It shows how the update ended (succeeded, rolled back or refused, with the reason) and a log, survives a page reload and the service restart, and reports a helper that stopped without a result. `update_helper.py refresh-helper` brings an older pinned helper up to the current version so it writes this record.
- Housekeeping in Profile: runs left in "awaiting approval" on stories that are already done can be resolved by you, with the database backed up first and an audit trail. Hermes can read the findings and propose a fix on a free model (new Profile switch, off by default); only your approval acts. Update backups are managed by the updater here, so only stale approval waits are listed.
- A standard job envelope on every planned story (work kind, size, risk, estimate and a reason for the route), with the job and route tier derived by the server, standard tags, and refusal of an incomplete plan at approval. Human tasks can name the user they are assigned to. The Delegator role pack explains when a free route is safe and when to escalate to a foundation model.
- Tags may contain a colon.

## [0.3.7] - 2026-10-15

### Fixed
- An update is no longer blocked by approval waits that nobody can decide. A run left in "awaiting approval" on a story that is already done or failed (a later run completed it) was counted as a pending human decision forever, so the Updates panel and the helper refused to install. Only waits on stories that are still open, or on no story, block an update now.

## [0.3.6] - 2026-10-15

### Added
- Opt-in sharing of the OpenRouter key saved in Profile with Hermes and OpenClaw, so it is not typed into each agent. Off by default, one operator per installation, saved key wins over the agent's own. The key is supplied only in the environment of Hermes and OpenClaw runs, scrubbed from anything they print, and never given to Claude Code, Codex or Grok. Paid models still follow the dispatch policy. Turning it off or removing the key stops it at once. See `docs/configuration/saved-openrouter-key.md`.

## [0.3.5] - 2026-10-14

### Fixed
- The one-confirmation update no longer stops half way when the page is reloaded or left. Staging builds the runtime on the host, which takes minutes on a Raspberry Pi; the panel now keeps the update you confirmed for this tab (30 minutes, that version only), shows the host's staging phase, and carries on to the install when you return. The server still drain-checks before anything is stopped.
- A staging run that fails on the host is reported at once with its reason, instead of the panel waiting ten minutes.
- The release notes footer no longer tells you to paste a digest on a host that verifies the release signature.

## [0.3.4] - 2026-10-14

### Fixed
- The Updates panel no longer offers an older staged version as an install. Only a newer package is listed under Available; older ones are listed as kept for rollback, and the Rollback button is the way back. The Rollback button is no longer stretched across the panel.

## [0.3.3] - 2026-10-14

### Fixed
- The Updates panel works on a host installed with the bootstrap. The service unit it wrote never set `MAC_CONTROL_UPDATE_ROOT`, so the panel said "no update root is configured" and offered only manual steps. The unit now sets it. A host installed earlier adds a one-line systemd drop-in once; the steps are in `docs/install/updates-rollback-recovery.md`.

## [0.3.2] - 2026-10-14

### Added
- One-confirmation updates on a host that trusts the release signature: Check for updates, then **Update to X.Y.Z**. The release's SSH signature is verified against the release key pinned on the host, so no digest is typed; the install still drains work, takes a data snapshot, checks health and rolls back by itself. A host that still pins a digest keeps the two-step flow and the panel says how to switch.
- `update_helper.py enable-signed-updates --fingerprint SHA256:...` switches an existing host to signature trust after you name the key. The release package now ships the public release key, and the bootstrap switches a new install automatically when the key matches the fingerprint in the script.

### Changed
- The Updates panel is easier to read: clearer spacing and headings, and the work that must finish first is shown before you confirm.

### Fixed
- The MCP page no longer shows a red "list failed (exit 127)" for an agent whose command is not on this host. It shows a quiet "Not available on this host" note. A command that runs and fails is still reported as a failure.

## [0.3.1] - 2026-10-14

### Added
- First production release with signed installer manifests and a committed public verification key for both products.
- Project consultant conversation in a glass panel below the project brief controls. Refine goals, phases, stories, scope, definitions of done and dependencies, then review an editable brief before submitting it to Hermes coordination. Existing planning and execution approvals remain required.
- Profile AI defaults start new consultant chats, agent chats, task forms and project planning with Hermes and OpenRouter free. Installed membership CLI/model routes are configurable, with settings links and help guidance. Existing conversations and approved routes retain their choices.

### Fixed
- OAuth setup uses installation-specific paths and explicit host origins; shared client JSON no longer imports unrelated callbacks. Generic examples and private-address disclosure keep personal endpoints out of standard setup.
- Wizard links missing agents to runtime installers and explains install, native configuration and readiness refresh. Saved OpenRouter keys no longer trigger another entry form; spending checks remain available.
- Installer helper status resumes after navigation, retries temporary failures, updates every three seconds while active, and shows its log below the matching runtime's buttons. Completed logs remain available.
- Raspberry Pi wizard prerequisites match the packaged Python 3.11 runtime.


## [0.3.0] - 2026-10-13

- Fixed Python 3.11 project-planning syntax that blocked Pi package installation. RCD CI and package syntax validation now use the pinned Python runtime.

- Agent tools recognizes existing native installs, shows current versions and offers verified upgrades. Claude Code pin updated to2.1.299 and Hermes to0.22.0.

- Project Model lock stops failed tasks without automatic retries or equivalent-model failover; default behavior retains reviewed alternatives. Clean Mac/Pi OS install instructions are included.

### Added
- Matching lower-cost planning tiers, operator-reviewed paused-project retiering and repair of explicitly
  incomplete read-only story assignments, preserving scope and execution gates.
- Header version and commit tags remain visible on small screens; release footer information matches
  across products with product/owner, environment, API/web commits and modified status.
- Operator-confirmed managed installers for Claude Code, Codex CLI, Grok Build, Hermes and OpenClaw,
  with pinned downloads, update/remove/rollback, clean install environments and platform privilege restrictions.
- Agent roles with one assignable Delegator, generic starter guidance, managed instruction-block previews,
  private backups, rollback and interrupted-assignment recovery. In-progress pipelines keep their approved
  Delegator and model; a changed assignment requires new coordination review.
- OpenRouter/Hermes free-first setup guidance, platform worker choices and native membership prerequisites.
  Free-only planning can use a reviewed free Delegator route without a subscription CLI. Membership access,
  provider API charges and Google credit eligibility are explained separately.
- Grok Build is a supported agent, next to Claude Code, Codex, Hermes and OpenClaw: tasks, chat, project story
  agent and approved fallback, on an eligible Grok membership only (the CLI has no dollar cap, so an API route is
  refused). It has a native Linux arm64 build, verified in Lima; Raspberry Pi hardware remains untested. Runs are confined: telemetry and
  trace upload off, a filesystem sandbox, git push and merge denied. xAI prices are in the price catalog and
  the price checker reads docs.x.ai. See `docs/configuration/grok.md`. Not run against a signed-in account.
- Operator-only Agent tools panel for pinned per-user installation, update, removal and rollback of Claude Code, Codex CLI, OpenClaw and Hermes on Linux arm64. Confirmation shows sources, commands, disk and memory. System packages remain manual and sign-in is never automated. Install/remove and version checks were exercised in an Ubuntu arm64 Lima VM; Raspberry Pi hardware, Mac installers and Grok installation remain unverified or pending. See `docs/install/agent-tools.md`.

### Changed
- RCD works with any mix of agents installed. Setup readiness needs any one subscription CLI and any one of
  Hermes or OpenClaw instead of all of them, a new project story starts on an agent that is installed, and the
  story agent picker marks agents that are not installed. A test runs every one of the 32 combinations.

## [0.2.0] - 2026-10-13

RCD reaches the 0.2 feature level it shares with MCD. These were built and tested against the MCD
code base on a Mac; nothing in this release was tested on Raspberry Pi hardware.

### Added
- Branch-scoped agent git access: an operator can grant one approved project's stories permission to
  commit and push to one named branch of an allowlisted repository, through operator-owned hooks and a
  credential helper outside every repository. Without a grant agents still cannot commit or push.
- Subscription limits: when Claude Code or Codex stops on a usage limit RCD shows one calm notice with
  the time it lifts, moves stories that meet the limit to an approved alternate of the same grade, and
  offers one button to send waiting stories across until the limit lifts. Hermes can report the status
  in Discord, and change the routing when the operator enabled it in Profile.
- Shared project context is smaller and cheaper without losing anything: long handoffs become digests
  that point to a complete ledger file, the stable part of the prompt comes first so a provider's prompt
  cache can reuse it, and the story's own text comes last. The size of each prompt is recorded.
- Failure mining: Hermes can answer "what has been failing and why?" in Discord from failed runs
  classified by cause, with counts by agent, model and project, repeated errors and the cards still
  Failed. Read only, redacted and bounded, behind its own switch in Profile.
- Close project: ends a project that will not be finished, with a reason kept in its ledger. It shows as
  Closed, never Complete, and its failed tasks can be removed from the board.
- Failed project cards that another card already carries, and duplicates, can be deleted.
- The GitHub settings pick repositories from a checklist loaded from the account and report which
  repository failed and why.
- Tasks list has a Model column with a condensed model name.
- Price catalog (`apps/api/pricing_catalog.json`) with the published prices of the recent models of each
  platform, and `scripts/pricing/check.py` to compare it with the providers' pages, find models used
  without a price and add them. Models ending in `:free` cost 0. A model used without a recorded price is
  named next to the unpriced count; runs that used no model are not usage records.
- Release flow: release notes generated from this changelog, `scripts/release/publish-release.sh` (which
  scans the released commits with gitleaks and refuses on a finding) and the standard footer with a
  modified marker, product and owner. See `docs/development/release-flow.md`.

### Fixed
- A chat message sent just after the service started could be failed with "service restarted" by the first
  recovery pass. Recovery now fails only turns left by a previous process.
- Combining accepted prerequisite work into a parallel story no longer needs git 2.45; it works on the
  older git that Raspberry Pi OS and Ubuntu 24.04 ship, and a conflict returns the workspace to where it began.
- An unreaped runner (a zombie) no longer makes every operator request "could not be verified" on Linux.

### Changed
- The application updater API moved to `/api/app-updates`, so it no longer collides with the
  collector's `/api/updates`.
- Claude Code stories may use web search and fetch without any shell, credential or publish permission.

[0.3.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.0
[Unreleased]: https://github.com/gptkiosk/rbp-control-dashboard/compare/v0.6.30...HEAD
[0.6.29]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.29
[0.6.28]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.28
[0.6.27]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.27
[0.6.26]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.26
[0.6.25]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.25
[0.6.24]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.24
[0.6.23]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.23
[0.6.22]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.22
[0.6.21]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.21
[0.6.20]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.20
[0.6.19]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.19
[0.6.18]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.18
[0.6.17]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.17
[0.6.16]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.16
[0.6.15]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.15
[0.6.14]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.14
[0.6.10]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.10
[0.6.9]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.9
[0.6.8]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.8
[0.6.7]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.7
[0.6.6]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.6
[0.6.5]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.5
[0.6.4]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.4
[0.6.3]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.3
[0.6.2]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.2
[0.6.1]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.1
[0.6.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.0
[0.5.5]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.5
[0.5.4]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.4
[0.5.3]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.3
[0.5.2]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.2
[0.5.1]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.1
[0.5.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.5.0
[0.4.8]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.8
[0.4.7]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.7
[0.4.6]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.6
[0.4.5]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.5
[0.4.4]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.4
[0.4.3]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.3
[0.4.2]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.2
[0.4.1]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.1
[0.4.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.4.0
[0.3.7]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.7
[0.3.6]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.6
[0.3.5]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.5
[0.3.4]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.4
[0.3.3]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.3
[0.3.2]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.2
[0.2.0]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.2.0

## Before versioned releases

### Documentation and community staging — 2026-10-12

- Published MIT license with preserved MCD attribution, operator/developer docs and public collaboration configuration.
- Application source deliberately held for fixes, verification and explicit operator sign-off.
- Recorded Linux ARM64 UI preview as temporary test evidence, without claiming Pi hardware or live-provider certification.

[0.3.1]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.3.1
[0.6.30]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.30
[0.6.31]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.31
[0.6.32]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.32
[0.6.33]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.33
[0.6.34]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.34
[0.6.35]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.35
[0.6.36]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.36
[0.6.37]: https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/v0.6.37

[0.6.38]: https://github.com/gptkiosk/rbp-control-dashboard/compare/v0.6.37...v0.6.38
