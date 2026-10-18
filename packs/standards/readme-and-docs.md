# README and docs that show the application

A README is the front door. Mix words with pictures, and write it for someone who has never seen the app.

## Structure
- What it is in one sentence, a hero screenshot, who it is for, licence and whether the repository is public or private, and the pipeline status badge.
- Quick start: the exact commands to run it locally, and what you should see.
- Architecture: when it is more than a local install (several services, containers, a database, a queue, cloud resources, third-party APIs, sign-in), add a Mermaid diagram. One `flowchart` of the parts and how they connect, and one `sequenceDiagram` of the main data flow, for example a request from the browser to the data store and back, or a release from commit to pipeline to package. GitHub renders Mermaid in the README.
- Configuration table: each setting, what it does, its default, where it is set. Never a real secret.
- Application guide: one short how-to for each area of the application beyond installation and first sign-in, such as daily use, each page or panel, an admin task, an update, a rollback, and what to do when something fails. Each how-to has numbered steps and a screenshot.
- Troubleshooting and where to ask for help.

## Screenshots
- Make them with Playwright from a script kept in the repository (for example `docs/screenshots/capture.spec.ts`), so they can be regenerated. Fixed 1280 by 800 viewport, both themes when the app has them, one file per application area, descriptive names and alt text.
- Use only seeded test data against a local or CI instance. No real accounts, addresses or visitor data.
- Agents cannot run a browser. Plan a human story, or a CI job, that runs the script and commits the images; the agent writes the script, the README and the how-tos.
- Check each screenshot is current when the screen changes; update it in the same pull request.
