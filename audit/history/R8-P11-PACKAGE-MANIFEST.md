# Documentation Publisher 2.0.10-dev – P12 R8-028-P1A cumulative correction candidate

This is the complete reconstructed project tree with an **active** GitHub Codespaces
configuration. It contains `.devcontainer/devcontainer.json` (not an example-only file),
the active `.devcontainer/devcontainer.json` (waits for `postCreateCommand`), Dockerfile-based Git Subtree installation, lifecycle scripts, publisher source, schema, examples,
tests, documentation and the historical R8 audit evidence.

## Provenance

The available cumulative full-project source baseline was the verified P3 archive. Earlier P4–P10 full project archives were not present in the retained file set. P4–P11 were
reconstructed from the recorded defect descriptions and reports; this is not a byte-identical
restoration of earlier intermediate trees. The actual P11 ZIP recovered for this P12 work is
`documentation-publisher-v2-r8-2.0.10-dev-P11-ACTIVE-DEVCONTAINER.zip`, SHA-256
`a35bcfe52c130a8505422806f58fc429f7bbad8b0fbcae1d89722d35ba212936`. P12/P1A changes are
applied to that exact recovered tree, not reconstructed from a patch-only approximation.

## Current R8-028-P1A test record

- Main regression excluding `tests/test_process.py`: **218 passed, 1 skipped, 73 subtests** – `audit/evidence/R8-028-P1A-MAIN-REGRESSION.txt`.
- Process-group suite, separate invocation with `ResourceWarning` as error: **6/6 passed** – `audit/evidence/R8-028-P1A-PROCESS-REGRESSION.txt`.
- Targeted first correction group: **48/48 passed** (31 config/security, 12 active Dev Container config, 5 runtime verifier) – `audit/evidence/R8-028-P1A-TARGETED-TESTS.txt` and the three split logs.
- Complete `scripts/test-in-codespaces.sh` run with transparent test-doubles for host-missing Java 25/JDK 21, Git LFS and Maven: `audit/evidence/R8-028-P1A-CODESPACES-STARTER-TEST-DOUBLE-OUTPUT.txt`.
- Unmodified local-host environment blockers: `audit/evidence/R8-028-P1A-LOCAL-HOST-ACCEPTANCE-BLOCKERS.txt`.
- Differential P11 baseline proof: `audit/evidence/R8-028-P1A-UNMODIFIED-P11-BASELINE-NEGATIVE-TESTS.txt` and its summary.
- Exact test-double starter sublogs: `audit/evidence/R8-028-P1A-CODESPACES-STARTER-ENVIRONMENT-TEST-DOUBLE.txt`, `...-MAIN-TEST-DOUBLE.txt`, `...-PROCESS-TEST-DOUBLE.txt`.
- Detailed changes and limits: `audit/R8-028-P1A-SECURITY-TOOLCHAIN-REPORT.md`.

The one skipped regression remains the real Git-LFS object transfer. The Dev Container Python base image is currently tag-pinned but not digest-pinned, and the APT `git-subtree` package is not pinned to a Debian snapshot version; exact image rebuild reproducibility is not claimed. Actual Docker/Codespaces image creation, Windows process-tree acceptance, Project Pages/Keycloak browser acceptance and remaining R8-028 option behavior gates remain open. This is a cumulative development/test candidate, not a production release.

## Install the Codespaces config before creating a Codespace

Copy the entire `.devcontainer/` directory into the repository root and save it on the
branch from which the new Codespace will be created. See `.devcontainer/README.md` and
`TEST-IN-CODESPACES.md` for the exact procedure.


The current R8-027 active-configuration corrections are recorded in
`audit/evidence/R8-027-ACTIVE-CONFIG-CHANGELOG.md`. A historical 7-test log from the
superseded candidate is retained with an explicit historical filename. The older
`P3-TO-P11-RECONSTRUCTION.patch` records the earlier P3-to-P11 reconstruction; it is
not a substitute for the final `.devcontainer/` directory in this package.
