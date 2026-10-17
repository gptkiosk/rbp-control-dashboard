# Project types

A project type is a template for a kind of project we deliver. It makes plans consistent: the planner is told how the type is planned and where it has failed before, and the plan is checked for the gates a person expects, such as a file verification, a preview before anyone approves how something looks, and the human sign-offs.

Choose the type in **New project** (or in the brief panel of a draft). When your brief clearly fits one, MCD suggests it and you can accept or ignore the suggestion. A project with no type is planned exactly as before.

| Type | For | Where a person looks and signs off |
| --- | --- | --- |
| **Web app** (containerized, deployed to a cloud service) | A hosted web service, monetized or not, deployed to Cloud Run or Fargate. Examples: a subscription site, a free community site. | Infrastructure apply, payment and account-data stories, the go-live, and how visitor-facing pages look (after a preview). |
| **Packaged app** (local install from a public GitHub release) | An app installed from a signed package published as a GitHub release; not cloud deployed. Examples: the Mac and Raspberry Pi control dashboards. | An install and update test on the target hardware, approving the publish, anything touching the update path, and how screens look. |
| **Website property** (static site with generated media) | A static, original, stylized site built with the media pipeline. | Making the generated media in MCD, approving the look from a live preview, the contact form and container stories, and the final local verification. |

## What a type contains

- **Planner text and failure points.** Added to the planner prompt. Failure points are real causes of failed projects, for example "a story that needs a container engine cannot be done by an agent", "a human approval has nothing to judge without a live preview", "a Dockerfile that copies only html, css and js ships no assets".
- **Plan checks.** After a plan is proposed, the review shows **Plan checks for this project type**: warnings such as "no file verification story", "the preview checkpoint does not follow a verification story", "a story needs a container engine, make it a human story", "generated media is made by the operator, not an agent". They only warn and never block, and they read story titles for gates and the full story text for risky commands.
- **Keys.** The keys the type usually needs, which feed the key check before a project is created.

## Growing the types

Types are plain files: `packs/project-types/<id>.json` in the release, or your own copy in `<data directory>/project-types/<id>.json`, which replaces the shipped one of the same id. A file that is not valid, has an unknown check kind or has a pattern that does not compile is ignored, never half used. When a project fails for a reason that could have been planned around, add it to the type's `failure_points` (and a check if it can be detected from the plan) so the next plan avoids it. Check kinds: `has_story` (a story whose title matches, optionally human or agent), `order` (a story matching one pattern must come after one matching another) and `not_agent_for` (a story that runs a risky command must be a human story).
