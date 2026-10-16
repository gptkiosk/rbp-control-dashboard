# Repository bootstrap: from no repository to one set up for the project

## Purpose

Explains how a project that needs a GitHub repository gets one: Hermes (or you) proposes a private repository, you approve the exact
request, you grant agents one branch, and a setup story fills the repository in. Read it when you start a project from nothing, such as a
new website that should live in its own private repository with a pipeline.

## Screenshots

Pending capture: `profile-github-actions-waiting.png`, `project-repository-access.png`.

## The path

1. **Plan.** A brief that needs a repository that does not exist yet starts with human steps: approve creating the private repository, and
   grant branch access. Then one setup story. The planner is told this; it never plans work that creates a repository or pushes to the
   main branch.
2. **Propose.** Hermes can draft the request in Discord (`propose_repository`: a name and a purpose). Turn on **Allow Hermes to propose a
   new private GitHub repository for a project** in Profile first. GitHub writes must be on (`MAC_CONTROL_GITHUB_WRITES_ENABLED=true`).
   Hermes drafts only: it cannot approve or create anything. A Backlog card for you records the proposal.
3. **Approve.** Profile → **GitHub actions waiting for you** shows the exact request. Tick the confirmation and **Approve and run**. The
   repository is created under your configured GitHub account, **always private**, with an initial README commit so branches and pull
   requests work, and it is added to this install's GitHub list. Anything that is not private is refused and reported.
4. **Grant branch access.** On the project page, **Repository access for agents**: pick the repository and the folder, and confirm. Agents
   may then commit and push one branch, `project-<id>/<name>`, and nothing else. The main branch can never be named; merging, tagging and
   force pushes stay denied.
5. **Set up.** The setup story clones the repository into that folder, writes the repository's standards file, agent notes, ignore file and
   any container or pipeline files the brief needs, commits on the project branch and pushes it. You review and merge the pull request.

## What is never automatic

Deleting a repository, repository secrets, Actions permissions, publishing and the first push to a branch you have not granted all stay
with you. Hermes and other agents cannot approve a GitHub action; only the operator route can, after reading the exact request.

## What is not built yet

A server-built initial standards file (today the setup story writes it from the starter standards and your instructions, and the
repository's standards are checked the next time the project is planned), and a comment on the project when the repository is created.

## Troubleshooting

- **"GitHub writes are off".** Set `MAC_CONTROL_GITHUB_WRITES_ENABLED=true`, restart, and make sure `gh` is signed in as the configured account.
- **"A repository with this name already exists".** Choose another name; nothing was created.
- **"That repository is not on this install's GitHub list".** Approve the creation first (it adds the repository), or add it in Profile → GitHub.
