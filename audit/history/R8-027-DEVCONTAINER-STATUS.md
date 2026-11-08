# R8-027 – GitHub Codespaces Dev Container

## Status in this candidate

**Active configuration implemented and locally validated; actual Codespaces image build/rebuild remains pending.**

The earlier candidate supplied only `.devcontainer/devcontainer.json.example`, so a fresh
repository did not have the active configuration Codespaces discovers. That mistake is fixed
here: `.devcontainer/devcontainer.json` is present at the exact discovery path and uses
`.devcontainer/Dockerfile`.

## Provisioned environment

- Python 3.13 from `mcr.microsoft.com/devcontainers/python:3.13-bookworm`.
- `git-subtree` installed from Debian package during Docker image build and linked into the
  directory reported by `git --exec-path`; no `GIT_EXEC_PATH` override.
- Git LFS 3.8.1 via pinned Feature 1.2.5 with `autoPull: false`.
- Eclipse Temurin Java 25 as default and Java 21 additionally installed via pinned Feature 1.8.3; Maven 3.10.0.
- `MAVEN_ARGS` mirrors the current Keycloak CI HTTP retry/connection settings. The Keycloak
  documentation build should continue to use the source repository's `./mvnw` wrapper.
- `postCreateCommand` creates `.venv` and installs `requirements-dev.txt` or `requirements.txt`
  if present. A fresh repository with only `.devcontainer/` can still finish provisioning.
- `waitFor: postCreateCommand` waits for `.venv` setup before Codespaces reports creation as ready.
- `postStartCommand` verifies exact Python 3.13, active Java 25 plus installed Java 21, Maven 3.10.0, Git LFS 3.8.1 and Git Subtree at each start.

The Git Subtree setup is in a Dockerfile, not a repository-local Feature installer. This avoids
relying on an executable bit being preserved when files are added through GitHub's web UI.
The Python base image is tag-pinned but not digest-pinned; the APT `git-subtree` package is not
snapshot-pinned. Full bit-identical image rebuilds are therefore not yet guaranteed.

## Local validation

- Active `devcontainer.json` parses as strict JSON.
- Dockerfile content is checked by static regression tests; no Docker/Podman runtime is
  available here to build the image.
- Lifecycle and acceptance shell scripts pass `bash -n`.
- Active Dev Container configuration tests: 12/12 pass.
- Runtime verifier tests with positive/negative tool doubles: 5/5 pass.
- Main regression excluding `tests/test_process.py`: 218 pass, 1 skipped, 73 subtests pass.
- `tests/test_process.py`: 6/6 pass in a separate run; combined total 224 pass and 1 skip.
- The unmodified local host acceptance reports four expected toolchain blockers: Git LFS is
  absent, Java 21 (not 25) is active, no additional SDKMAN Java-21 candidate is present, and
  Maven is absent. Python 3.13, Git/Subtree, CLI and smoke config/plan checks pass. The complete
  Codespaces starter passed with test-doubles for only those missing/wrong host tools; this is
  not a live Docker or Codespaces build.

## External acceptance still required

No Docker/Podman runtime is available here; therefore no real image build was performed. The
actual acceptance must happen after `.devcontainer/` is stored at the repository root on the
branch to be used for Codespaces. Create a new Codespace and run:

```bash
bash .devcontainer/verify-environment.sh
```

It must pass without manually setting `GIT_EXEC_PATH`. Until this real Codespace check passes,
R8-027 remains externally pending. No remote repository or user Codespace was modified here.


## R8-028-P1A – stricter toolchain verification

The first R8-028 correction group pins Java Feature 1.8.3, Git-LFS Feature 1.2.5, Git LFS 3.8.1 and Maven 3.10.0; the verifier requires Python 3.13, Java 25 as active default plus Java 21 additionally installed. It no longer accepts Java 21 as the default. Exact local negative/positive verifier cases are covered in `tests/test_devcontainer_runtime.py` (5/5). Real container build and user Codespace acceptance remain open.
