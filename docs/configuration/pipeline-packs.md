# Pipeline packs

Pipeline packs carry optional project templates for one kind of deliverable, such as a upubhub class. They are offered in **Settings → Template store**, laid out like an app store: **Installed** templates on top, **Available** templates below as cards (an icon, a category, the summary and an **Add** button on each), then the tools templates use. A search box filters both lists. Each available card shows whether the template is **Official** (from the store's maintainers) or **Community** (accepted from a contributor) and by whom, the settings you choose when you start a project, and anything this host lacks with a link to fix it. A missing tool does not stop you adding a template; a template that needs a newer dashboard cannot be added until you update. An installed pack shows its version, offers **Update** when the store has a newer one, and can be removed. Removing a pack does not change projects already planned with it; new projects can no longer pick its type. Card icons are files in the web app named after the template id; see [Template store icons](template-store-icons.md).

The **Tools** tab lists the agents, system tools, providers, checks and services a template may require, from the same signed release, and whether this host has each one.

A pack for a service (for example upubhub.com) needs that service's credential first. Until it is saved in **General → Private credentials**, the pack's **Install** button is disabled and the reason is shown next to it.

## Updating templates

Templates update apart from the dashboard, so a template can be improved and tested without waiting for a dashboard release.

- **Check the store** reads the latest signed release (the list is otherwise cached for 15 minutes). The **Template store** tab
  shows how many updates are waiting, for example *Template store · 2*.
- An installed card with a newer version shows **What's new** (the version's `changes` text) and **Update to x.y.z**.
  **Update all** updates every template that has one, one after another, and reports each result. A template that needs a
  newer dashboard is left out until you update the dashboard.
- Earlier versions stay on this host. Pick one under **Version** on the installed card to switch back
  (`POST /api/pipeline-packs/<id>/activate`); the stored files are checked again before they are used. Removing a template
  deletes every version.
- Projects already planned keep their plans. A new plan uses the version that is active when you plan.

## Importing your own template (unvetted)

**Import a template** installs a template from a `.zip` or `.tar.gz` of its folder (`pack.json`, `project-types/`,
`guides/`; macOS **Compress** works). Use it to try a template you are writing before you submit it, or one someone sent you.

- You must tick that you accept the risk. An imported template is **not vetted**: the store's security scan, model review and
  rehearsal did not run, nothing checked who made it, and its text goes to your AI models as planning guidance.
- It must still be data only, within the same limits as store templates, and pass the same checks (`POST
  /api/pipeline-packs/import?accept_risk=true`, the archive as the request body).
- It can never use a store or built-in id, or a project type id another template already provides, so store and local copies
  never mix. Give it your own id, for example `my-geology-class`.
- It is marked **Local, unvetted** in the store and in the project type picker, and never receives store updates. Import a
  higher `pack_version` to replace it; the earlier one stays available under **Version**.
- A store template with the same id cannot be added while your own is installed; remove yours first.

To share a template with everyone, follow `CONTRIBUTING.md` in
[gptkiosk/dashboard-pipeline-packs](https://github.com/gptkiosk/dashboard-pipeline-packs): test it here with **Import a
template**, then open a pull request. It is scanned, rehearsed and reviewed, and appears as **Community** with your name once a
signed release includes it.

## Pushing to upubhub (`upubhub-push`)

The upubhub class, textbook and lesson-plan templates name the `upubhub-push` connector (`apps/api/upubhub_push.py`). It sends the
project's course package to upubhub.com through its publish API (upubhub 1.41 or newer) as **private drafts**: the textbook and
lesson plans are private works, and a class is created **invite-only and free**. Nothing is published; you review and publish on
upubhub. Pushing again updates the same textbook, plans and class (they are keyed by the course's class code, or its title), and
never changes visibility, entry or anything else you set on upubhub.

1. In upubhub, open **Connections** and create a token with **Also allow pushing classes** ticked (Teacher plan).
2. In the dashboard, save it in **Settings → General → Private credentials** as **upubhub**.
3. Run the project. The **Push to upubhub** panel appears on the push story (titled like *Push the course to upubhub*). It stays
   off until every earlier story, including your final sign-off, is done, the token is saved and the course package check passes;
   it lists anything still missing.
4. Press **Push to upubhub**. The panel links to the textbook, plans and class on upubhub. An assessment whose lesson is still in
   upubhub's moderation shows as waiting; push again once the lesson is published.

What is sent, in order: images the lessons use (uploaded once, then reused), the textbook (`kind: textbook`, one chapter per
lesson), each lesson plan (`kind: lesson_plan`), the textbook's chat-out topics, then the class with one assignment per lesson and
its assessment settings. A textbook package stops after the topics; a lesson-plan package sends one lesson plan.

- **Labels.** Written by the pipeline, the work is labelled AI-assisted on upubhub (upubhub has no separate "AI generated"). With the
  template's content source set to your own files, `course.json` says `hand_crafted` and the work is labelled hand-crafted.
- **The token** is read only when you press Push, sent only to upubhub as a bearer header, and never written to the project, the
  receipt or the project notes. Agents never see it.
- **The receipt** (ids and links only) is kept in the dashboard's data folder, `upubhub-push/project-<id>.json`, and a note is
  added to the project.
- `MAC_CONTROL_UPUBHUB_URL` points the connector at another upubhub, for example `http://127.0.0.1:8000` for a local test stack
  (https otherwise).

## What a pack can and cannot do

A pack is data: JSON and Markdown. It gives the planner a project type (planner text, failure points, sign-offs, plan checks, intake questions) and short format guides. A pack may replace the general software guides (development practice, security) for its own types, so a course plan does not spend its guidance budget on deployment advice; it can only choose among shipped guides for that.

A pack never runs code on this host. Checks and service connectors are part of the dashboard; a pack names the ones it uses. A pack that names one this dashboard does not have is refused with "Update the dashboard".

Your own copy of a project type in `<data>/project-types/` still replaces a pack's.

## Checks a pack can name

- `course-package`: for course packs such as upubhub-class. When you accept the project's static verification story ("Verify course package files"), the dashboard checks the project's `course/` folder and refuses the acceptance with every problem listed until it passes. It checks that each lesson in `course/course.json` has its textbook, lesson plan and assessment settings; textbook `## ` headings match the outline; discussion-topic anchors occur exactly once on a plain prose line; each lesson stays within upubhub's 12 topics and 60,000 characters; assessment settings are within upubhub's ranges; credits carry an allowed open licence and an https source; images exist, have alt text and are published in Media studio or credited; AI provenance is declared; and `UPLOAD.md` exists. The rules match what upubhub accepts on import and in class setup. A `code` in `course.json` must follow the class code standard `SUBJ:LL-Class name` (3 to 5 capital letters, a level from 00 for kindergarten to 16 for the last college year, then the class name); when the project's settings give `subject_code`, `level` and `class_name`, the code must be exactly that.

## Where packs come from

Packs are published as GitHub releases of `gptkiosk/dashboard-pipeline-packs`. The dashboard reads the latest release without a GitHub token, so the list is cached for 15 minutes; **Check the store** reads it again.

A release holds one index, `pipeline-packs.json`, with its detached signature `pipeline-packs.json.sig`, plus one archive per pack. The index is signed with the same `dashboard-release` key as dashboard releases. The dashboard checks it against that public key, which ships inside the dashboard's own verified code, so MCD (which pins release digests) and RCD (which checks release signatures) verify packs the same way.

An install then checks the archive against the sha256 the signed index gives it, checks the pack's own `pack.json` matches the index entry, and validates every file before anything is written. Installed packs live in `<data>/packs/<id>/<version>/`; `<data>/packs/<id>/active` names the version in use, and the previous version stays on disk.

## Formats

`pack.json`:

```json
{
  "format": "dashboard-pipeline-pack", "version": "0.1",
  "id": "upubhub-class", "pack_version": "0.1.0",
  "label": "upubhub class (textbook, lesson plans, assessments)",
  "changes": "What changed in this version, shown as What's new (optional, at most 600 characters).",
  "service": {"id": "upubhub", "label": "upubhub.com", "credential": "upubhub"},
  "app_min": "0.6.87",
  "project_types": ["upubhub-class"],
  "guides": ["upubhub-class-format.md"],
  "general_guides": ["readme-and-docs.md"],
  "checks": [], "connectors": []
}
```

An archive `<id>-<pack_version>.tar.gz` holds `pack.json`, `project-types/<id>.json` for every listed type and `guides/<name>.md` for every listed guide, optionally under one top folder. Nothing else is allowed: no links, no other files, at most 40 files of 40 KB each. A pack guide may not reuse a shipped guide's name. An own import may also be a `.zip` with the same contents; Finder's `__MACOSX` and `.DS_Store` entries are ignored.

`pipeline-packs.json`:

```json
{
  "format": "dashboard-pipeline-pack-index", "version": "0.1",
  "packs": [{"id": "upubhub-class", "pack_version": "0.1.0", "label": "…", "summary": "…",
             "service": {"id": "upubhub", "label": "upubhub.com", "credential": "upubhub"},
             "archive": "upubhub-class-0.1.0.tar.gz", "sha256": "<64 hex>", "app_min": "0.6.87"}]
}
```

Sign it with `ssh-keygen -Y sign -f <release key> -n dashboard-release pipeline-packs.json`.
