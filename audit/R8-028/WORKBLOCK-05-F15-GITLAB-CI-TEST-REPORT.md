# Workblock 05 — F15 GitLab CI + GitLab Pages test report

**Parent:** P12 / R8-028 / `RECONCILED-GROUP-3`, through Workblock 04.

- Parent ZIP SHA-256: `dc06b8b23c77f7999ac8a336565d99e95f3514149ea0ab629972c138eca43db3`
- Parent TAR.GZ SHA-256: `cee4217a13faf5e2acddddcbac60e806f35fd49b71d6ab0a458f761a122d6c95`
- Package version: `2.0.10-dev`
- Local Python: 3.13.5

## Regression results

The project's four-group acceptance layout was executed with independent pytest invocations. The main regression command is the same command used by `scripts/test-in-codespaces.sh` (manifest, wheel and process groups excluded); the other three groups were then run independently.

| Group | Command | Result |
|---|---|---:|
| Main regression | `python -m pytest -q --ignore=tests/test_process.py --ignore=tests/test_packaging.py --ignore=tests/test_p6_p7_manifest_cleanup.py` | **249 passed, 1 skipped, 99 subtests** |
| Manifest/Cleanup | `python -m pytest -q tests/test_p6_p7_manifest_cleanup.py` | **6 passed** |
| Wheel/Packaging | `python -m pytest -q tests/test_packaging.py` | **3 passed** |
| Process/Timeout | `python -Werror::ResourceWarning -m pytest -q tests/test_process.py` | **6 passed** |
| Total | Separate groups; no tests double-counted | **264 passed, 1 skipped, 0 failed; 99 subtests** |

The single skip is `tests/test_p8_git_lfs.py`: the real `git-lfs` client is not installed in this execution environment. This is an explicit limitation, not a pass. The real pointer-to-object hydration and credential flow remain an external acceptance gate.

## F15 provider tests

Targeted GitLab workflow tests: **11 passed** (including 9 subtests). The full main regression includes all tests in `tests/test_engine.py`, so these focused tests are included in—not added again to—the total above.

Coverage verifies:

- `workflow.provider: gitlab_ci` dispatch and default `.gitlab-ci.yml` output;
- digest-pinned OCI image requirement and supported Python minors;
- YAML syntax and duplicate-key rejection;
- validate/build-only dry-run, with no Pages job;
- explicit live Pages job, `pages.publish`, `artifacts.paths`, deploy-branch gate and merge-request suppression;
- config-relative artifact paths and ordered profile forwarding;
- secret allowlist and rejection of secret-bearing merge-request builds;
- runner-reserved variables, token environment stripping from pip-install, validation and build child processes;
- rejected unsupported trigger/path combinations.

## Static checks

- `python -m compileall -q publisher_engine tests scripts`: passed.
- Both source and packaged JSON schemas parse and are byte-for-byte equal: passed.
- `provider-capabilities.json` parses and advertises `gitlab_ci` as implemented: passed.
- CLI reports version `2.0.10-dev`: passed.
- A full CLI path using the checked-in Keycloak smoke config plus a temporary GitLab workflow block passed `validate-config` and `generate-workflow`; the emitted `.gitlab-ci.yml` was parsed with duplicate-key rejection, checked for digest pinning and dry-run omission of `deploy-pages`, then removed. See `audit/evidence/WORKBLOCK-05-GITLAB-CLI-END-TO-END.txt`.

## Scope and acceptance boundary

The GitLab generator and its local contract are implemented and tested. **No real GitLab runner or Pages deployment was started.** GitLab CI/CD variable protection, job-token allowlist settings, runner image availability and external GitLab YAML lint/pipeline behavior remain to be accepted in an actual GitLab project. The implementation is therefore locally verified, but F15 remains partial until a real GitLab pipeline passes.

F05 remains partial because APT package metadata and `git-subtree` package/dependency resolution are not snapshot-pinned and a fresh Codespaces rebuild is external. F07's GitHub Actions matrix is implemented but has not yet completed on GitHub. F16/F18 need real Codespaces/Windows acceptance. F17 remains open for the real Git-LFS client transfer.

## Evidence files

- `audit/evidence/WORKBLOCK-05-MAIN-REGRESSION.txt`
- `audit/evidence/WORKBLOCK-05-P6-P7-MANIFEST-CLEANUP.txt`
- `audit/evidence/WORKBLOCK-05-WHEEL-PACKAGING.txt`
- `audit/evidence/WORKBLOCK-05-PROCESS-TIMEOUT.txt`
- `audit/evidence/WORKBLOCK-05-GITLAB-TARGETED.txt`
- `audit/evidence/WORKBLOCK-05-GITLAB-CLI-END-TO-END.txt`
- `audit/evidence/WORKBLOCK-05-STATIC-CHECKS.txt`
