# Development practices (starter)

Habits that make AI-assisted and human development reliable. They apply to any codebase the coordinator plans work for.

## Scope and size
- One story, one reviewable change. Keep stories small enough to finish, test and review in one sitting.
- Stay inside the story's scope. Note unrelated problems as follow-ups instead of fixing them in passing.
- Prefer the simplest design that meets the requirement. No speculative abstractions, flags or compatibility layers.

## Code
- Match the surrounding code: naming, structure, comment density. Do not reformat files you are not changing.
- Comments explain why: the constraint, the rejected alternative, the bug a guard exists for.
- Handle failure where it can actually happen (network, parsing, user input), not everywhere.
- Keep functions and modules cohesive. Put rules where they can be tested without the user interface.

## Tests
- Test behavior and rules, not implementation. Every guard has a test that fails when the guard is removed.
- Use synthetic data and private temporary state. Test provider integrations with real SDK objects or signed samples, not mocks that accept anything.
- Keep the suite fast and deterministic. A test that depends on random draws, time or order is a bug; fix or pin it.

## Changes and history
- Small commits with a message that says why. Branch per change; review before merge; never commit directly to a protected branch.
- Check the branch before committing. Add named files, not everything.
- Version with semantic versioning, keep a changelog written for the people who use the software, and bump the version in the same change.

## Data and schema
- Migrations are additive first (expand, then migrate, then contract). Rehearse on a copy of real data. Keep a rollback plan.

## Documentation
- Update the guide in the same change as the behavior. Consolidate rather than add pages. Write plainly, for the reader.

## Accessibility and quality
- Keyboard use, visible focus, readable contrast and meaningful labels are part of done for any interface.
- Check the real rendered result, not only the function that produced it.

## Evidence
- A task is done when its checks ran and passed in the working copy, not when a status changed or a command exited 0.
- Report what ran, what failed and what did not run. Never claim a result you did not observe.
- Verify the thing in effect: ask the running service or the installed app, not only the file you edited.
