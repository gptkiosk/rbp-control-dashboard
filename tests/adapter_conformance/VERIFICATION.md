# S2_conformance handoff

Changes are confined to `tests/adapter_conformance/`:

- `test_conformance.py`: 21 expanded adapter cases for all ten requested guarantees.
- `fake_adapter.py`: synthetic Protocol implementation and independent fake provider ledger.
- `harness.py`: schema validators, external tools/memory journals, driver Protocol, probes,
  and conservative shared session cost reservations.
- `conftest.py`: fake-by-default factory, explicit live opt-in, required model routes/cap,
  bounded teardown, and named evaluation criteria in pytest/JUnit evidence.
- `test_harness.py`: 15 harness checks including seven intentionally broken behaviors,
  aggregate budget accounting and fail-closed live configuration.
- `README.md`, `requirements.txt`, `__init__.py`: usage, scenario/driver integration,
  dependencies and package structure. This file records proposed verification evidence.

## Checks and results

On 2026-10-11, Python 3.12 from the reference checkout's MCP virtual environment supplied
already-installed pytest 9.1.1 and jsonschema 4.26.0. The interpreter was used only for
isolated tests; no reference checkout, running service or application configuration changed.
No live factory/provider was invoked. No preview, commit, push, merge or publication occurred.

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  <mcd-checkout>/apps/mcp/.venv/bin/python \
  -m pytest -q tests/adapter_conformance \
  -o cache_dir=/private/tmp/rcd-conformance-pytest-cache \
  --junitxml=/private/tmp/rcd-conformance-results.xml
```

Result: **36 passed**, zero failures/errors/skips, in 4.85 seconds. All 21 adapter
cases passed. JUnit includes an `evaluation_criterion` property for every case.
The timeout case recorded **1.011316 seconds** for a one-second limit (allowed 0.9–1.1).
The local JUnit receipt is disposable; regenerate it for operator acceptance.
Python AST checks passed for every new Python file.

The unchanged predecessor contract tests also ran with `--noconftest`, loading only
`adapter_contract.py` through the isolated harness (no API application fixtures):
**57 passed in 0.07 seconds**, including schema validity and all example payloads.
Bootstrap used `runpy.run_path('tests/adapter_conformance/harness.py')` followed by
`pytest.main(['--noconftest', '-q', 'apps/api/tests/test_adapter_contract.py', ...])`.

An initial local venv/pip attempt failed because network resolution was unavailable.
That newly created venv was removed. No dependencies or lock files outside story scope
were changed. A direct contract-test attempt using `PYTHONPATH=apps/api` encountered
an existing `apps/api/platform` shadow of Python's standard-library `platform`; the
isolated bootstrap avoided this without changing another story's implementation.

## Decisions, risks and next-story guidance

The accepted contract governs fallback: adapters never switch routes; a synthetic MCD
caller starts a new approved attempt only after rate-limit/quota failure. Same-key retry
is start-request replay. The production dispatcher remains outside this story.

Live mode is supported through a test driver factory. It reserves at most the configured
session cap across all new runs, checks result costs against independent provider receipts,
and requires runtime/adapter budget enforcement. A future live driver must enforce each
run cap **before** provider requests; post-run assertions cannot prevent upstream billing.
No live driver or real credentials are included. Use the README's driver scenarios to
instrument each runtime rather than reimplementing these guarantees in test glue.

Fake success does not establish live runtime or Pi compatibility. The cancellation case
observes fresh usage receipts for 300ms after cancellation; delayed provider billing and
process-tree cleanup need deployment evidence. Approval continuity is checked within one
adapter lifetime; cross-process recovery belongs to S3_durable_runs. Shared memory uses
external synthetic tools; real dependency scheduling belongs to S3_handoffs_memory.
Busy machines may violate the strict timeout tolerance; retain measurements as evidence.

Operator acceptance is still required. Next adapter stories should implement a driver,
run the identical suite in isolated workspaces, and supply provider-derived model/usage/cost
receipts. Live model routes and costs require their existing MCD/operator authorization.
