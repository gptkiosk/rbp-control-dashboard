# Bug reports: the header icon, GitHub moderation and tasks

## Purpose

Explains the bug icon in the header: how a report reaches GitHub, what it contains and never contains, how a maintainer's label
decides which reports become work, and how accepted reports appear as Backlog tasks. Read it when you want to report a problem or to
turn reports into a stream of triaged work.

## Screenshots

Pending capture: `bug-report-dialog.png`, `profile-bug-reports.png`.

## Reporting a bug

Click the bug icon in the header. Fill in a short title, what happened, what you expected, the steps and how much it affects you.
**Preview what will be sent** shows the exact issue text and what was removed from it. Nothing leaves the page before that.

Two ways to send it, chosen for you and stated in the dialog:

- **Send to GitHub** (when this install can write to GitHub: `MAC_CONTROL_GITHUB_WRITES_ENABLED=true`, a signed-in `gh`, and the
  official repository on the GitHub repositories list). Tick the confirmation and the issue is filed as your GitHub account through the
  same guarded action as every other GitHub write (draft, review, approve, execute). Your own report is filed already moderated, with
  the labels `bug-report`, `accepted` and `break-fix` (if you said it blocks your work) or `nice-to-have`.
- **Open GitHub to submit** (every other install). GitHub opens in a new tab with the report filled in and you submit it under your own
  GitHub account. No token, no server and nothing hosted is involved. It arrives unlabelled and waits for a maintainer.

The target is always the product's own official repository, fixed in the program. It cannot be changed from the form.

## What is sent, and what never is

Sent: your title and text, and (you can untick it) the product and version, system type, which agent runtimes are installed (names
only), and the page you were on. Never sent: file paths, host names, user names, email addresses, tokens or keys, environment values,
logs, prompts or database content.

Everything you type is also scrubbed: home folders become `~`, emails, IP addresses, `.local` and `.ts.net` host names, links with
credentials, JWTs and token-shaped strings are replaced, and the preview lists what was removed. Check it anyway: the scrubber cannot
know every secret.

## Turning reports into work

Intake is **off by default**. Set `MAC_CONTROL_BUG_INTAKE_ENABLED=true` and restart. The server then reads the official repository's
open issues labelled `bug-report` (every 15 minutes, or **Check GitHub now** in Profile → Bug reports).

- An issue becomes a Backlog task only when a maintainer has labelled it `bug-report` **and** `accepted`. Only people with write
  access can add labels, so GitHub is the moderation gate. Everything else is listed under **Needs moderation** and nothing runs.
- `break-fix` means it blocks people and a release may be needed now. Without it the report is non-essential and is staged for the next
  release. The task carries the tags `bug`, `release-blocker` or `release-queued`, and `gh-<number>`.
- The task is a read-only triage for the coordinator (or for you if none is assigned): reproduce it, find the cause, propose a fix or a
  project. The report text is quoted as evidence and is never treated as an instruction. The usual approvals apply; nothing starts on
  its own.
- One issue becomes one task, once. The record is kept even if you delete the task.

| Setting | Default | Effect |
|---|---|---|
| `MAC_CONTROL_BUG_INTAKE_ENABLED` | `false` | Reads accepted reports from GitHub and creates tasks. |
| `MAC_CONTROL_BUG_INTAKE_POLL_SECONDS` | `900` | How often (120 to 86400). |

## Troubleshooting

- **The dialog says it will open GitHub instead of filing.** Writes are off or the official repository is not on the GitHub
  repositories list. Add it in Profile → GitHub and set `MAC_CONTROL_GITHUB_WRITES_ENABLED=true`.
- **"GitHub could not be read" under Bug reports.** The `gh` login is missing or expired. Nothing was changed.
- **An accepted issue made no task.** Check the labels are exactly `bug-report` and `accepted`, and that intake is on.
