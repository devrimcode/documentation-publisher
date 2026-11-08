# Workblock 09 — Codespaces Python `.venv` bootstrap correction

Date: 2026-11-08  
Project: Documentation Publisher `2.0.10.dev0`  
Parent: Workblock 08 full-source archive  
Status: complete local correction candidate; real Codespaces acceptance still open

## Finding

The runtime dependency declaration was not missing PyYAML. Both `pyproject.toml` and `requirements.txt` already declare `PyYAML>=6.0.2,<7`; both also declare `jsonschema`.

The failure was lifecycle ordering. The previous `post-create.sh` only installed dependencies if `pyproject.toml` existed during the one-time `postCreateCommand`. The documented staging case allowed a Codespace to be created before Publisher source files arrived. When the project source was later extracted into that workspace, Dev Containers did not automatically replay the earlier `postCreateCommand`. A shell command `python -m ...` could therefore resolve to the system interpreter rather than the intended project `.venv`. The old `python.defaultInterpreterPath` setting was not a shell-start activation guarantee.

The remote repository state observed during this investigation also showed only `README.md` on `origin/main`; the Codespace status showed the full source tree and `.devcontainer/` as untracked local files. The initial remote branch therefore did not contain the complete project source or active Dev Container definition at the time of its last published commit.

## Full-tree corrections

1. Added `.devcontainer/ensure-python-environment.sh` as the single idempotent bootstrap entry point.
2. The bootstrap validates the base Python 3.13 interpreter and replaces an existing `.venv` if it was created with the wrong Python minor version.
3. It hashes all present Python dependency declarations. New or changed `pyproject.toml` / requirements files trigger installation of the complete declared runtime/development set, not an ad hoc single package.
4. `post-create.sh` now calls the shared bootstrap.
5. `postStartCommand` runs the bootstrap before the strict environment verifier on every container start.
6. The bootstrap installs one idempotent Bash startup hook. Every new interactive Bash shell finds the repository bootstrap, rechecks dependency declarations, and activates the repository `.venv` before accepting commands.
7. `verify-environment.sh` now fails closed when project files exist but `.venv` or declared imports/package metadata are absent.
8. `scripts/codespaces_acceptance.py` verifies that `sys.prefix` is exactly the repository `.venv`.
9. Added hermetic lifecycle tests and updated the setup/runbook documentation.

## Test evidence

Executed in the isolated build environment with Python 3.13.5:

- Targeted Dev Container group (`test_devcontainer_apt.py`, `test_devcontainer_runtime.py`, `test_devcontainer_config.py`, `test_devcontainer_python_bootstrap.py`): **35 passed, 8 subtests passed**.
- Main regression group, excluding the three intentionally isolated groups: **265 passed, 1 skipped, 99 subtests passed**.
- Manifest/cleanup group: **6 passed**.
- Wheel packaging group: **3 passed**.
- Process/timeout group with `-Werror::ResourceWarning`: **6 passed**.

Across those separated project regression groups: **280 passed, 1 skipped, 99 subtests passed**. The skipped Git LFS HTTP batch/object-transfer test requires a real `git-lfs` executable not present in the isolated build environment.

A single combined `pytest -q` invocation exceeded its 120-second outer timeout. All four documented isolated regression groups subsequently completed successfully when run separately.

## Acceptance still required in the user's Codespace

This report does not claim a real Docker image build or a GitHub Codespaces rebuild. The user must validate that the resulting container:

- starts with `.venv` activated in a newly opened interactive Bash terminal;
- resolves `python` to `.venv/bin/python` and imports `yaml` successfully;
- passes `.devcontainer/verify-environment.sh` and `scripts/test-in-codespaces.sh`;
- runs the real Git LFS object-transfer test when its required fixture is available.

F05/F16 and the real Git LFS transfer acceptance remain open until those external checks pass. No commit, push, repository deletion, Codespace rebuild, release upload or deployment was performed during this workblock.
