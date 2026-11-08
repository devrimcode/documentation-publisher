# R8-028 Workblock 04 — final archive verification summary

**Source:** `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-RECONCILED-GROUP-3` (the exact P12 Group 3 parent). Parent ZIP SHA-256: `dc06b8b23c77f7999ac8a336565d99e95f3514149ea0ab629972c138eca43db3`; parent TAR.GZ SHA-256: `cee4217a13faf5e2acddddcbac60e806f35fd49b71d6ab0a458f761a122d6c95`. Both values were verified before extraction. The Workblock 04 ZIP and TAR.GZ were then created from the isolated child tree and independently re-extracted.

## Final archive integrity

- Workblock 04 ZIP SHA-256: recorded in the companion `.SHA256` file.
- Workblock 04 TAR.GZ SHA-256: recorded in the same companion file.
- ZIP integrity (`ZipFile.testzip`): passed.
- Fresh ZIP and TAR.GZ extraction trees: byte-identical, **211 files**.
- Internal `PROJECT-MANIFEST.SHA256`: all **210** non-manifest files listed and verified.
- `publisher_engine.__version__`: `2.0.10-dev`.

## Local regression from a fresh extraction of the final ZIP

The following groups were run separately from the freshly extracted final ZIP on Linux x86_64, Python 3.13.5, pytest 9.0.2:

| Group | Result |
|---|---:|
| Core regression (excluding P6/P7, packaging and process groups) | **240 passed, 1 skipped; 94 subtests** |
| P6/P7 manifest and cleanup | **6 passed** |
| Wheel/package installation | **3 passed** |
| Process/timeout (`ResourceWarning` treated as error) | **6 passed** |
| **Combined independent groups** | **255 passed, 1 skipped, 0 test failures** |

The single skip is `tests/test_p8_git_lfs.py::GitLfsPathFilterTests::test_real_git_lfs_transfer_requires_local_lfs_server_fixture`; the `git-lfs` client is not installed in this runner. No real pointer-to-object transfer is claimed.

The `tests/test_devcontainer_config.py` checks are included in the core group; they were also run directly after the Workblock 04 edits: **14 passed, 8 subtests**. The workflow YAML, Dev Container JSON, shell syntax and Python compile checks passed.

## Test-process observations

A monolithic core invocation in this runner stalled when it reached a P6/P7 manifest-build test after the preceding core sequence; the P6/P7 file passed 6/6 independently. A packaging attempt under a constrained test-process environment also stalled during `venv`/`ensurepip` bootstrap. The wheel test then passed **3/3** from the fresh final ZIP in a clean process environment (16.19 seconds). The four-group harness and CI matrix therefore keep core, manifest/cleanup, packaging and process/timeout invocations separate. The monolithic invocation is not represented as passed.

## Additional checks

- `python -m compileall -q publisher_engine tests scripts`: passed.
- `.devcontainer/devcontainer.json`: parsed as JSON.
- `.github/workflows/python-compatibility.yml`: parsed as YAML; matrix is exactly Python 3.11, 3.12 and 3.13, with read-only `contents` permission and four separately declared regression groups.
- `bash -n scripts/test-in-codespaces.sh .devcontainer/verify-environment.sh .devcontainer/post-create.sh`: passed.
- Dev Container structural tests: 14 passed, 8 subtests.

## Not performed / acceptance remains open

- No GitHub Actions run; Python 3.11/3.12 have not been executed in this local environment.
- No Docker image build or fresh GitHub Codespace; the Python base-image digest is pinned, but APT package metadata and `git-subtree` package/dependency resolution remain floating.
- No real Git LFS transfer (client absent).
- No Windows process-tree run.
- No push, commit, pull request, release upload, production publishing or deployment.
