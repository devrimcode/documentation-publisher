# Workblock 08 — Codespaces validation plan

Run only in the user's intended Debian Bookworm Codespace after extracting this full archive. Do not infer success from archive integrity.

## A. Targeted regression checks

```bash
python -m pytest -q tests/test_devcontainer_apt.py
```

Expected coverage:

- Existing active-exec-path helper is reused and locked.
- Explicit fallback path is honored.
- Missing helper fails closed when the hermetic fixture provides no fallback candidates.
- Installer remains idempotent.
- Unexpected additional APT source files are rejected.
- Mutable Debian mirror URI is rejected even when the lock checksum is recomputed to match the modified source file.

## B. Main regression

```bash
python -m pytest -q --ignore=tests/test_process.py --ignore=tests/test_packaging.py --ignore=tests/test_p6_p7_manifest_cleanup.py
```

## C. Full Codespaces acceptance

```bash
bash scripts/test-in-codespaces.sh
```

The runner additionally executes manifest/cleanup, wheel packaging, and subprocess/process-group suites.

## D. Outstanding live-transfer acceptance

`tests/test_p8_git_lfs.py::GitLfsPathFilterTests::test_real_git_lfs_transfer_requires_local_lfs_server_fixture` remains an explicit skip until a local HTTP LFS batch/object transfer harness is implemented. Do not count this as a pass.

## Evidence capture

Save the full terminal output, command exit code, and generated `test-results/` logs. Report each check as PASS, FAIL, BLOCKED, or NOT RUN; do not convert skipped or unexecuted work into PASS.
