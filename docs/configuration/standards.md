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

## Settings involved

- No setting. RCD only reads the file under the project's working directory; it does not fetch repositories or open anything
  outside that directory.
- Operator API: `GET /api/projects/{id}/standards` (signed-in operator only; agents get 403).
- The standards file changes through a normal pull request in its own repository.
