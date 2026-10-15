# Starter standards

## Purpose

Explains the engineering standards RCD ships with so a project is useful out of the box, even when its repository has no standards
of its own. They are general: how to deliver a hosted web app and a packaged app, application security, and everyday development
practice. They are a starting point that you can change.

## Screenshots

Pending capture: `project-standards-starter-line.png`.

## Controls

On a project's **Project brief & planner**, the standards line says which standards apply:

- **Repository standards** when the project's repository has `docs/development/standards.md` (see [Repository standards](standards.md)).
  These always win.
- **Starter standards** when it does not, or when that file cannot be understood. The line says which, so you can fix the file.
  The starter is "shipped" (the copy that came with RCD) or "your copy" (see below).

What the starter gives a plan:

- **Areas with a minimum risk.** Fifteen general areas: authentication, authorization, payments, secrets, personal data, migrations,
  the update and release path and infrastructure are high risk; the public API and input handling, dependencies and business logic
  are medium; the interface, documentation, tests-only changes and research are low. The planner is told them. A story whose area is
  one of them cannot have a lower risk; any other area name is allowed.
- **No free-only route for a high-risk story.** A high-risk story must use a subscription or other foundation route, or a human
  review. Free routes stay fine for low-risk, reversible, read-only work.
- **Checks in the definition of done.** Every agent story that writes (implement, test, docs, ops) gets the starter's checks: tests,
  linter and type checker, dependency audit, secret scan, migration rehearsal, preview and docs. A high-risk story also gets the
  security checks, and has to say how each is met.

The guides behind it are plain text you can read and adapt: [Application security](../../packs/standards/security.md),
[Development practices](../../packs/standards/practices.md), [Delivering a hosted web app](../../packs/standards/web-app-delivery.md) and
[Delivering a packaged app](../../packs/standards/packaged-app-delivery.md). The tables are in
[starter.md](../../packs/standards/starter.md).

## Changing them

Copy `packs/standards/starter.md` to `<data folder>/standards/starter.md` (by default `~/.rcd-control/standards/starter.md`) and edit
the two tables and the security list. RCD uses your copy instead of the shipped one; if it cannot be read, the shipped copy is used.
Delete your copy to go back. Two optional lines tune the rules:

```
- unknown areas: refused        (default for a repository's own standards; the starter allows them)
- high-risk free routes: allowed (default: refused)
```

Nothing in these files can grant an agent a permission: they can raise a story's risk and add checks, never lower a risk or widen
what an agent may run.

Your copy is kept across updates; see [What survives an update](upgrades-and-your-data.md).

## Settings involved

- Data folder file: `standards/starter.md`. No environment setting.
- Operator API: `GET /api/projects/{id}/standards` (the standards that apply, with their source).
