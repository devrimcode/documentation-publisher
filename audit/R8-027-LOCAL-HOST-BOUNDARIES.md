# Local runner result versus real Codespaces acceptance

The environment/CLI harness was executed on 2026-11-07 in the available Linux runner.
It exited 1 because exactly two tools are absent on that host:

- Git LFS (`git lfs version` not installed)
- Maven (`mvn` not installed)

The same run passed Python dependencies, Git 2.47.3, active Git exec-path discovery,
`git subtree -h`, Java 21, Python compilation, CLI version, Keycloak config validation and
Keycloak component planning. Full output is in
`audit/evidence/R8-027-LOCAL-HOST-ACCEPTANCE-CURRENT.txt`.

The runner has no Docker/Podman runtime either, so it cannot build the Dockerfile or prove the
Java/Git-LFS Dev Container Features install successfully. These tools are expected to be added
by the actual Dev Container setup. Their presence must be verified in the new GitHub Codespace.

Separately, the source-tree regression has been executed as two direct commands:
- Main suite excluding `tests/test_process.py`: 202 passed, 1 skipped.
- `tests/test_process.py` with `ResourceWarning` promoted to errors: 6 passed.
- Active Dev Container tests are included in the 202-test main suite and also pass independently: 8/8.

The local runner result is not a live GitHub Codespaces result. Do not mark R8-027 accepted until
a Codespace is created from the branch containing `.devcontainer/devcontainer.json` and
`.devcontainer/verify-environment.sh` exits zero without manually changing `GIT_EXEC_PATH`.
