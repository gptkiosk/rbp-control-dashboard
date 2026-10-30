# Pipeline packs

Pipeline packs carry optional project templates for one kind of deliverable, such as a upubhub class. They are offered in **Settings → Installs & updates → Template store**: choose a template in **Add a template** and press **Add**. Under the choice the store shows whether the template is **Official** (from the store's maintainers) or **Community** (accepted from a contributor) and by whom, the settings you choose when you start a project, and anything this host lacks with a link to fix it. A missing tool does not stop you adding a template; a template that needs a newer dashboard cannot be added until you update. An installed pack shows its version, offers **Update** when the store has a newer one, and can be removed. Removing a pack does not change projects already planned with it; new projects can no longer pick its type.

The **Tools** tab lists the agents, system tools, providers, checks and services a template may require, from the same signed release, and whether this host has each one.

A pack for a service (for example upubhub.com) needs that service's credential first. Until it is saved in **General → Private credentials**, the pack's **Install** button is disabled and the reason is shown next to it.

## What a pack can and cannot do

A pack is data: JSON and Markdown. It gives the planner a project type (planner text, failure points, sign-offs, plan checks, intake questions) and short format guides. A pack may replace the general software guides (development practice, security) for its own types, so a course plan does not spend its guidance budget on deployment advice; it can only choose among shipped guides for that.

A pack never runs code on this host. Checks and service connectors are part of the dashboard; a pack names the ones it uses. A pack that names one this dashboard does not have is refused with "Update the dashboard".

Your own copy of a project type in `<data>/project-types/` still replaces a pack's.

## Checks a pack can name

- `course-package`: for course packs such as upubhub-class. When you accept the project's static verification story ("Verify course package files"), the dashboard checks the project's `course/` folder and refuses the acceptance with every problem listed until it passes. It checks that each lesson in `course/course.json` has its textbook, lesson plan and assessment settings; textbook `## ` headings match the outline; discussion-topic anchors occur exactly once on a plain prose line; each lesson stays within upubhub's 12 topics and 60,000 characters; assessment settings are within upubhub's ranges; credits carry an allowed open licence and an https source; images exist, have alt text and are published in Media studio or credited; AI provenance is declared; and `UPLOAD.md` exists. The rules match what upubhub accepts on import and in class setup. A `code` in `course.json` must follow the class code standard `SUBJ:LL-Class name` (3 to 5 capital letters, a level from 00 for kindergarten to 16 for the last college year, then the class name); when the project's settings give `subject_code`, `level` and `class_name`, the code must be exactly that.

## Where packs come from

Packs are published as GitHub releases of `gptkiosk/dashboard-pipeline-packs`. The dashboard reads the latest release without a GitHub token, so the list is cached for 15 minutes; **Check for packs** reads it again.

A release holds one index, `pipeline-packs.json`, with its detached signature `pipeline-packs.json.sig`, plus one archive per pack. The index is signed with the same `dashboard-release` key as dashboard releases. The dashboard checks it against that public key, which ships inside the dashboard's own verified code, so MCD (which pins release digests) and RCD (which checks release signatures) verify packs the same way.

An install then checks the archive against the sha256 the signed index gives it, checks the pack's own `pack.json` matches the index entry, and validates every file before anything is written. Installed packs live in `<data>/packs/<id>/<version>/`; `<data>/packs/<id>/active` names the version in use, and the previous version stays on disk.

## Formats

`pack.json`:

```json
{
  "format": "dashboard-pipeline-pack", "version": "0.1",
  "id": "upubhub-class", "pack_version": "0.1.0",
  "label": "upubhub class (textbook, lesson plans, assessments)",
  "service": {"id": "upubhub", "label": "upubhub.com", "credential": "upubhub"},
  "app_min": "0.6.87",
  "project_types": ["upubhub-class"],
  "guides": ["upubhub-class-format.md"],
  "general_guides": ["readme-and-docs.md"],
  "checks": [], "connectors": []
}
```

An archive `<id>-<pack_version>.tar.gz` holds `pack.json`, `project-types/<id>.json` for every listed type and `guides/<name>.md` for every listed guide, optionally under one top folder. Nothing else is allowed: no links, no other files, at most 40 files of 40 KB each. A pack guide may not reuse a shipped guide's name.

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
