# Codespaces setup and acceptance

## Before the first Codespace

The repository must contain the complete Publisher source tree at its root, including the active `.devcontainer/devcontainer.json` and Dockerfile. Do not create the production Codespace from a branch that contains only `.devcontainer/` or only a README; the complete source, `pyproject.toml`, `requirements*.txt`, and `publisher_engine/` must be present in the branch before its first Codespace is created. The bootstrap also supports staged source arrival: it rechecks dependency declarations at container start and before each new interactive Bash terminal.

For a fresh project repository, copy the complete contents of this project archive into the repository root. Confirm that `.devcontainer/devcontainer.json`, `pyproject.toml`, `publisher_engine/`, `schemas/` and `tests/` are root-level entries. Commit those files before creating the Codespace.

## First-start lifecycle

`postCreateCommand` runs `.devcontainer/post-create.sh`, which calls `.devcontainer/ensure-python-environment.sh`. It verifies Python 3.13, creates `.venv`, installs the editable Publisher package plus the `dev` extra (pytest, setuptools and wheel), then runs the strict environment verifier. A dependency-file fingerprint is checked again by `postStartCommand` and each new interactive Bash shell; if source or dependency declarations are added after initial container creation, the next start/terminal bootstraps the complete environment before activating `.venv`. The package installation creates the `documentation-publisher` console command and installs its schema, generic starter template and provider capability registry.

The Dev Container pins Java Feature 1.8.3, Git LFS Feature 1.2.5, Maven 3.10.0 and Git LFS 3.8.1. Java 25 is the active JDK; JDK 21 is also installed. The Python 3.13 Bookworm base image is pinned by OCI index digest and the build target is fixed to `linux/amd64`. The signed Bookworm, Bookworm-updates and Bookworm-security snapshot `20261107T000000Z` is used for APT metadata validation. Debian's `git` package in the digest-pinned base image supplies `/usr/lib/git-core/git-subtree`; the build verifies its dpkg owner/version and links it into the active Git exec path. Lock v3 also records the base-image digest, platform, APT source hash, architecture, Git version, helper hash and symlink target. Workblock 06's real build failed because it attempted to install a nonexistent `git-subtree` package; Workblock 07 corrects this and still requires a new real Codespaces build.

## First-run Publisher configuration

After the container starts, open a new Bash terminal and verify the selected interpreter before using the CLI:

```bash
printf 'VIRTUAL_ENV=%s\n' "${VIRTUAL_ENV:-<not-active>}"
command -v python
python -c 'import sys, yaml; print(sys.executable); print("PyYAML", yaml.__version__)'
documentation-publisher --version
documentation-publisher init-config --output publisher.yml
```

`init-config` copies the packaged generic fail-closed template and never overwrites an existing file. Replace every `<PLACEHOLDER>` with the repository-specific values. The tool deliberately does not guess a GitHub owner, repository, branch, provider or deployment target. Do not use `publisher.keycloak.smoke.yml` as a generic starter; it is project-specific and dry-run-only.

Check the available adapter/provider contracts and validate the configuration:

```bash
documentation-publisher capabilities
documentation-publisher validate-config --config publisher.yml
documentation-publisher plan --config publisher.yml --components all
```

Profiles can be selected with repeatable `--profile` options on all configuration-consuming commands. Order is significant and duplicate selections are rejected:

```bash
documentation-publisher validate-config --config publisher.yml --profile staging
documentation-publisher build --config publisher.yml --profile staging --components all
documentation-publisher publish --config publisher.yml --profile staging
documentation-publisher generate-workflow --config publisher.yml --profile staging
```

The selected profiles are embedded in the generated workflow's validation and build commands; GitHub Actions must still be run to confirm the remote execution.

## Verify the actual container

```bash
bash .devcontainer/verify-environment.sh
bash scripts/test-in-codespaces.sh
```

The acceptance script records its results under `test-results/`. It runs four independent groups: core regression, manifest/cleanup integration, wheel installation, and process/timeout. The manifest/cleanup tests are isolated because the combined long core process interacted badly with their subprocess build fixture in the local acceptance runner; the same six tests pass as a dedicated group. The real Git-LFS object-transfer integration test remains skipped unless a local LFS server fixture and `git-lfs` client are available.

## Acceptance boundary

Local tests and static checks are not proof that GitHub successfully built the Dev Container. R8-027/F16 closes only after a fresh Codespace is created from the exact target repository branch and the verifier and full acceptance script pass there. This archive has not been pushed or installed in your GitHub repository by this process.

## Workblock 14 — automated fork-to-Publisher deployment

After extracting Workblock 14, validate the production configuration and regenerate the Publisher workflow. The source-side notifier template is deliberately located under `integration/source-repository/` and must be copied into the `devrimcode/keycloak` repository; it is not a Publisher workflow. Configure `PUBLISHER_DISPATCH_TOKEN` as a source-repository Actions secret with a fine-grained token limited to `devrimcode/documentation-publisher` and Contents: write permission. Then validate the generated receiver workflow, run the full Codespaces regression, and complete a real build. Do not enable automatic Pages deployment until the source-side workflow and receiving `repository_dispatch` workflow are both installed and reviewed.

```bash
.venv/bin/python -m publisher_engine.cli validate-config --config publisher.yml
.venv/bin/python -m publisher_engine.cli generate-workflow --config publisher.yml --replace-existing
bash scripts/test-in-codespaces.sh
documentation-publisher build --config publisher.yml --components all --replace-output
```
