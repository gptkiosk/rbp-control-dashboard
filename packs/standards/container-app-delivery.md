# Delivering a containerized web app, local first

For a web app that is not published to a cloud yet: it lives in a private GitHub repository, a pipeline builds and tests its image, and
it runs on the owner's own machine in a container runtime (Colima on a Mac). Publishing to a cloud is a separate, later project.

1. **The repository comes first.** A private repository exists before code is planned. Create it with an initial README commit so
   branches and pull requests work, confirm it is private before anything is pushed, then add the repository's own standards file and
   agent notes. Creating the repository, the first push and any repository secret are a person's approval.
2. **One branch and one pull request per story.** After the first commit nothing is pushed to the main branch directly.
3. **The container.** A small base image pinned by digest, a multi-stage build, a non-root user, only the site's port exposed, no
   secrets in any layer, a `.dockerignore`, and a compose file for the local run.
4. **The pipeline** (GitHub Actions, Linux runners only; one build per change with layer caching, because macOS runners cost ten
   times as much). Lint and tests, build the image, run a container smoke test (every page answers, the health check passes), scan
   the image and dependencies, scan for secrets. Third-party actions are pinned by commit and the workflow token has least privilege.
5. **Run it locally.** Start the runtime (`colima start`), `docker compose up --build`, and check pages, themes and forms in a
   browser. A verification story reports the exact commands and what they showed.
6. **Done for now** means the change is merged with a green pipeline and, for a milestone, tagged. No registry push, no deploy.
7. **Later, in the cloud:** a new project. Registry, infrastructure and rollout follow the hosted web app guide.

**Who approves.** Low and medium risk stories run end to end. Creating the repository, the first push, repository secrets, pipeline
permissions and anything that publishes or costs money wait for a person.
