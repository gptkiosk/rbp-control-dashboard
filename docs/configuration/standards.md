# Repository standards

## Purpose

Explains how a project picks up the engineering standards of the repository it works in. A repository can carry a standards
file that says how its code is built, what counts as done for each kind of change, and how risky each area is. RCD reads it,
shows which version a plan was made under, and warns when it is missing. Later releases use it to raise a story's risk floor
and to attach the repository's checks to each story.

## Screenshots

Pending capture: `project-standards-line.png`.

## Controls

Open a project and look at **Project brief & planner**. Under the working directory there is one line:

- **Standards: name · N areas · M checks · hash.** The file was found and understood. The hash is the first 12 characters of
  its SHA-256, so you can tell exactly which version a plan was made under. A fold lists notes about rows that could not be
  read.
- **No standards in use.** The file is missing, unreadable (not UTF-8, larger than 128 KB, reached through a symlink, or has
  no tables it can read), or the project has no working directory. This is a warning, never an error: planning goes ahead
  without the standards, and the line says why.

## The file

`docs/development/standards.md` in the project's working directory, read as data. It is never executed and never treated as
instructions. Two tables are parsed by fixed code:

- **Definition of done** (a heading containing those words): columns "Change touches" and "Run".
- **Risk by area** (a heading containing those words): columns "Area" and "Default risk", and optionally "Route". A risk cell
  that names more than one level ("low to medium") counts as the highest.

The first heading may read `# <name> engineering standards`; the name becomes the property shown on the page. A row the parser
cannot understand is skipped and listed under the notes. When a plan revision is approved, its manifest records the state,
property, file hash and the number of areas and checks found.

## What the standards enforce

When the file is found and its risk table is understood, planning and approval follow it:

- **Area is a controlled value.** Each row of the risk table becomes an area name made of lowercase letters and digits joined by
  dashes ("Reader and writer features" becomes `reader-and-writer-features`, at most 40 characters). The planner is told the exact
  values and every story must use one. A story with another area is refused at approval, with the list.
- **Risk has a floor.** A story's risk may not be lower than its area's default risk. The standards can raise a risk, never
  lower one.
- **High risk is not free-only.** A story whose risk is high cannot be assigned a free-only route; choose a subscription route
  or a human review. (Without standards, planning keeps the older rules.)
- **The checks travel with the story.** The file's Definition of done checks (up to 12) are frozen on the approved plan revision
  and appended to the acceptance of every agent story that writes (implement, test, docs, ops), headed with the property and the
  file's hash. The agent runs the ones that match what it changed and always the any-commit check, and reports what ran. Read-only
  stories (research, plan, review, triage) and human stories do not get them.
- **A missing or unreadable file enforces nothing.** It is a warning on the project page, as before.

The planner sees a bounded paragraph with the areas, their minimum risk and route guidance. The text is project data and is
marked as such; it cannot change what an agent is permitted to run. Telemetry groups work by the property the plan was approved
under (`Property` filter and the "Work by property" chart).

## Settings involved

- No setting. RCD only reads the file under the project's working directory; it does not fetch repositories or open anything
  outside that directory.
- Operator API: `GET /api/projects/{id}/standards` (signed-in operator only; agents get 403).
- The standards file changes through a normal pull request in its own repository.
