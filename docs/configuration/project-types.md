# Project types

A project type is a template for a kind of project we deliver. It makes plans consistent: the planner is told how the type is planned and where it has failed before, and the plan is checked for the gates a person expects, such as a file verification, a preview before anyone approves how something looks, and the human sign-offs.

Choose the type in **New project** (or in the brief panel of a draft). When your brief clearly fits one, MCD suggests it and you can accept or ignore the suggestion. A project with no type is planned exactly as before.

| Type | For | Where a person looks and signs off |
| --- | --- | --- |
| **Web app** (containerized, deployed to a cloud service) | A hosted web service, monetized or not, deployed to Cloud Run or Fargate. Examples: a subscription site, a free community site. | Infrastructure apply, payment and account-data stories, the go-live, and how visitor-facing pages look (after a preview). |
| **Packaged app** (local install from a public GitHub release) | An app installed from a signed package published as a GitHub release; not cloud deployed. Examples: the Mac and Raspberry Pi control dashboards. | An install and update test on the target hardware, approving the publish, anything touching the update path, and how screens look. |
| **Website property** (static site with generated media) | A static, original, stylized site built with the media pipeline, following the [website design guide](../../packs/standards/website-design-delivery.md). | Making the generated media in MCD, approving the look from a live preview, the contact form and container stories, and the final local verification. |

| **Other** (does not exactly fit) | Anything that is not one of the three above. | Whatever the plan says it needs: it names the listed type it resembles, which of that type's gates still apply and which it drops and why, so you can overrule it in review. |

The project consultant asks for the type before it starts, in a required dropdown with **Other** at the end, because a typed plan is checked against that type. The chosen type is stated in the conversation, the consultant follows its planning guidance and says if your goal does not fit it, and the type travels to the plan when you review the brief. In **New project** the choice is optional (General, no template).

## What a type contains

- **Planner text and failure points.** Added to the planner prompt. Failure points are real causes of failed projects, for example "a story that needs a container engine cannot be done by an agent", "a human approval has nothing to judge without a live preview", "a Dockerfile that copies only html, css and js ships no assets".
- **Plan checks.** After a plan is proposed, the review shows **Plan checks for this project type**. Completeness findings such as a missing file verification story still warn. A story that asks an agent to use a container engine, browser, release-signing key or other unavailable host-only capability blocks dispatch until the plan is repaired. The checks read story titles for gates and the full story text for risky commands.
- **Keys.** The keys the type usually needs, which feed the key check before a project is created.
- **Guides.** Reviewed guides handed to the planner and agents. A Website property carries the [website design guide](../../packs/standards/website-design-delivery.md) (one visual language, layout rules that broke on a real site, the responsive review) and the [spacing and timing guide](../../packs/standards/website-spacing-and-timing.md) (starting values for transitions, header, cards and breakpoints, the collapsible phone menu, em media queries). The planner is told to carry those numbers into DESIGN.md as tokens in the design direction story.
- **Media defaults.** A type can set the quality tier the media panel starts on, per kind of slot (`media_default_tiers`, values draft, standard or premium). A Website property starts its video on the cheapest tier; other types start on standard. You can always change a slot's tier.

Every type also asks that the project **ends in the remote repository**: when the brief names a repository, the working folder is a clone of it (not a scratch folder, which has no remote), and the plan has a delivery story that pushes the project branch and opens a pull request, then a story that reads the pipeline result so the image or app build and the tests have really run there. A plan without a delivery story gets the warning *No delivery story*. Agents never push to the main branch. The repository is **public** for an app delivered as an MIT-licensed package that others install (a Packaged app), and **private** for anything proprietary or not MIT licensed (a hosted app, a company website); the plan states the visibility and the licence.

Every type also asks for **documentation that shows the application**, following the [README and docs guide](../../packs/standards/readme-and-docs.md): a README with a hero screenshot, a Mermaid architecture diagram and a data-flow diagram whenever the project is more than a local install, and a screenshot plus a short how-to for each application area beyond installation and first sign-in. The screenshots are made with a Playwright script kept in the repository, run by a person or a pipeline job against seeded test data, because agent sandboxes have no browser; the agent writes the script, the README and the how-tos. A plan with no README story, or no human or pipeline story that makes the screenshots, gets a warning.

A website plan is also checked for a **responsive review** story: a person looks at the preview at phone, tablet and wide widths in both themes for sideways scroll, overlapping header pieces, text spacing and pictures that do not fill their box.

## Growing the types

Types are plain files: `packs/project-types/<id>.json` in the release, or your own copy in `<data directory>/project-types/<id>.json`, which replaces the shipped one of the same id. A file that is not valid, has an unknown check kind or has a pattern that does not compile is ignored, never half used. When a project fails for a reason that could have been planned around, add it to the type's `failure_points` (and a check if it can be detected from the plan) so the next plan avoids it. Check kinds: `has_story` (a story whose title matches, optionally human or agent), `order` (a story matching one pattern must come after one matching another) and `not_agent_for` (a story that runs a risky command must be a human story).
