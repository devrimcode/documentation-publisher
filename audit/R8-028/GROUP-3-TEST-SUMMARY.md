# Group 3 regression accounting

All groups were run separately from the current source tree, after the F12/F14/F15/F19 code and test changes.

| Group | Command | Result |
|---|---|---:|
| Core regression | `python -m pytest -q --ignore=tests/test_process.py --ignore=tests/test_packaging.py` | 245 passed, 1 skipped; 94 subtests |
| Wheel/package integration | `python -m pytest -q tests/test_packaging.py` | 3 passed |
| Process/timeout group | `PYTHONWARNINGS=error::ResourceWarning python -m pytest -q tests/test_process.py` | 6 passed |
| Combined count | Separate invocations above | 254 passed, 1 skipped, 0 failed |

The single skipped test is `tests/test_p8_git_lfs.py::GitLfsPathFilterTests::test_real_git_lfs_transfer_requires_local_lfs_server_fixture`. The `git-lfs` binary is absent from this local environment, so actual LFS pointer hydration is not claimed. The wheel test validates a real config with the installed wheel, proving that config validation reads the packaged JSON Schema outside the source checkout.

An earlier all-in-one invocation and a later chained core→packaging shell invocation reached the wheel integration test but did not complete within the outer command timeout. The wheel test passed independently (3/3), as did the process group (6/6); the core group also passed independently (245 passed, 1 skipped). Only the three completed, separately invoked groups are counted. The interrupted chained invocations are not counted as passing test runs and have not been hidden.

Static checks: `compileall` passed; Bash syntax checks passed; JSON Schema Draft 2020-12 meta-validation passed; root/package schema and template byte-parity passed; CLI `--version` returned `2.0.10-dev`; Keycloak smoke `validate-config` passed (1 source, 1 component, 1 task). The real GitHub Actions workflow, real Codespaces/Docker build, Windows packaging/process behavior and remote provider acceptance were not run.
