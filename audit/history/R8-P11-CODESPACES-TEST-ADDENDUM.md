> **Historischer Addendum-Stand:** Das hier genannte Ergebnis von 202 Tests stammt von vor den zusätzlichen R8-027-Konfigurationstests. Für den aktuellen Stand ist `audit/evidence/P11-CURRENT-COMPLETE-REGRESSION-209-PASS.txt` maßgeblich.

# P11 Codespaces test-candidate addendum — 2026-11-07

This addendum records the changes made to prepare the cumulative candidate for direct testing in the user's Codespaces environment.

## Additional P11 correction

A stricter timeout test exposed open parent-side stdout/stderr pipe handles on the timeout exception path. After terminating the process tree and allowing reader threads to drain, `publisher_engine/process.py` now explicitly closes both captured pipe handles and joins the readers again. A dedicated regression test asserts that both handles are closed.

The timeout-output test was also made deterministic by writing its diagnostic payload immediately and allowing a longer process timeout, so interpreter start-up latency does not produce an empty-tail false failure.

Verification:

- `python -m pytest -q tests/test_process.py`: **6 passed**.
- `python -Werror::ResourceWarning -m pytest -q tests/test_process.py`: **6 passed**; no ResourceWarning is tolerated.
- Full suite after this addendum: **202 passed, 1 skipped, 53 subtests passed**.

The one skip is still the genuine Git-LFS transfer test. It is not counted as a pass.

## Codespaces acceptance harness

Added `requirements-dev.txt`, `scripts/test-in-codespaces.sh`, `scripts/codespaces_acceptance.py`, and `TEST-IN-CODESPACES.md`.

The environment harness tests the active container without setting or overriding `GIT_EXEC_PATH`. It checks dependencies, `git --exec-path`, `git subtree -h`, Python compilation, CLI version, Keycloak example-config validation, and the selected Keycloak build plan. It writes a timestamped environment report under `test-results/`.

The shell wrapper then runs the main regression and the subprocess/process-group module in separate direct invocations. Each pytest output is redirected to a regular log file under `test-results/`; the process-group suite is not nested inside the Python environment harness.

## Scope

This addendum makes the package directly testable in Codespaces. It does not make the outstanding external acceptance items pass: Git-LFS live object transfer, deployed Project Pages/browser acceptance, real Keycloak editor/browser acceptance, native Windows process-tree test, and the full 191-field runtime effectiveness matrix remain open.


## Current active-Dev-Container addendum

The current cumulative status adds the active `.devcontainer/devcontainer.json`, Dockerfile-based
Git Subtree provisioning, lifecycle scripts and nine config/test-runner regressions. Current
regression evidence is **203 passed + 1 skipped** in the main suite and **6 passed** in the
separate process-group suite (**209 passed + 1 skipped** overall). See
`../R8-P11-CUMULATIVE-STATUS.md` and `evidence/P11-CURRENT-COMPLETE-REGRESSION-209-PASS.txt`.

The environment harness is run separately from pytest. The shell wrapper starts pytest directly
in two separate invocations and writes their logs under `test-results/`. The real image build and
GitHub Codespaces acceptance are still pending.
