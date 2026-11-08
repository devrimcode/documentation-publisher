# R8-027 – Active Dev Container configuration: implementation and local checks

## Defect corrected

The earlier candidate supplied only `.devcontainer/devcontainer.json.example`. That is not
the active configuration Codespaces discovers. The current project includes the real
`.devcontainer/devcontainer.json` and a matching `.devcontainer/Dockerfile`.

## Provisioned environment

- Python 3.13 base image `mcr.microsoft.com/devcontainers/python:3.13-bookworm`. The tag is listed in Microsoft Container Registry.
- Debian `git-subtree` package installed during image build and made discoverable through the
  active `git --exec-path`; no global `GIT_EXEC_PATH` is changed. If the package already places
  the helper at that exact path, the Dockerfile leaves the existing executable untouched.
- Pinned Git LFS Feature 1.2.5 installing Git LFS 3.8.1 with automatic pull disabled.
- Temurin Java 25 default plus Java 21 additional JDK via pinned Java Feature 1.8.3; Maven 3.10.0 pinned.
- Keycloak CI Maven connection/retry settings in `MAVEN_ARGS`; Keycloak itself continues to use
  the checked-in `./mvnw` wrapper.
- `.venv` creation and conditional Python requirements installation at `postCreateCommand`.
- `waitFor: postCreateCommand` waits for Python environment setup before readiness; environment verification runs at every Codespace start.

Git Subtree is installed via Dockerfile rather than a local Feature installer. This avoids a
required executable bit on a repository file, which is important when the folder is uploaded
through GitHub's web interface.

## Local evidence

| Check | Result |
|---|---:|
| Active `devcontainer.json` strict JSON parse | PASS |
| Dockerfile static assertions | PASS |
| Shell syntax (`post-create.sh`, `verify-environment.sh`, acceptance script) | PASS |
| Python compile of acceptance/config tests | PASS |
| Active configuration regression tests | 9/9 PASS |
| Main regression excluding process module | 203 passed, 1 skipped, 53 subtests passed |
| P11 process regression module | 6/6 PASS in separate invocation |
| Combined regression count across the two invocations | 209 passed, 1 skipped, 0 failed |
| `git subtree` in this local host's active Git exec path | PASS |
| Clean-repository post-create fixture with mocked system tools | PASS |

The single skipped test remains the real Git-LFS object transfer, which requires a real LFS
client and batch/object server fixture. The Dockerfile same-path and alternate-path helper installation branches are covered by the active configuration suite.

## Local environment blockers

The current execution host does not have Docker/Podman, Git LFS or Maven installed. The
current environment harness records exactly Git LFS and Maven as blocked on this host; the
Git/Subtree, Java 21, Python, CLI, config and plan checks pass. Details are in
`audit/R8-027-LOCAL-HOST-BOUNDARIES.md`. Git, Subtree,
Java 21, regression tests, Python compilation, CLI, Keycloak configuration validation and
component plan checks pass. Git LFS and Maven are configured to be provisioned by the actual
Codespaces Dockerfile/Features; their presence must be verified in the real Codespace.

## Not verified here

No actual Dev Container image build or live GitHub Codespaces creation was performed. Static
checks cannot prove remote registry reachability or account provisioning capability.

## Required external acceptance

1. Copy the complete `.devcontainer/` directory into the root of the fresh GitHub repository.
2. Save it on the branch to be used for Codespaces creation.
3. Create the Codespace from that branch.
4. Confirm the Dockerfile and Java/Git-LFS Features finish installing.
5. Run `bash .devcontainer/verify-environment.sh`; it must exit zero without manual `GIT_EXEC_PATH`.

Until those steps pass in the real Codespace, R8-027 is implemented in this project candidate
but remains externally pending.


## R8-028-P1A addendum – exact toolchain and origin safety

The 9/9, 203/1 and 209/1 counts in the original report above are historical P11 values and are superseded by the current values below.

The active environment contract is now pinned to Java Feature 1.8.3 (Temurin 25 default,
Java 21 additional, Maven 3.10.0) and Git-LFS Feature 1.2.5 (Git LFS 3.8.1). The environment
verifier checks exact Python 3.13, active Java 25, the additional Java 21 SDKMAN candidate,
Maven 3.10.0 and Git LFS 3.8.1. Five runtime verifier tests prove both a valid toolchain and
rejection of Java 21 as the default, missing JDK 21, Python 3.12, and incorrect LFS/Maven versions.

Current local regression: 218 passed + 1 skipped in the main suite; 6/6 process tests in a
separate run; 48/48 targeted first-group tests (31 security + 12 config + 5 runtime). The full Codespaces starter passed with test
doubles for host-missing/wrong Java/LFS/Maven. The raw local host run records four blockers;
no Docker or live GitHub Codespace build was performed. See
`R8-028-P1A-SECURITY-TOOLCHAIN-REPORT.md` and `evidence/R8-028-P1A-LOCAL-HOST-ACCEPTANCE-BLOCKERS.txt`. A differential run against the unchanged P11 baseline reproduced 11 old-behavior assertion failures/subfailures, while the Dry-Run control remained green; see `evidence/R8-028-P1A-UNMODIFIED-P11-BASELINE-NEGATIVE-TESTS.txt`.
