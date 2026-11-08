# Generic Documentation Publisher v2

A configuration-driven publisher that temporarily integrates one or more Git source repositories into an isolated clone of the publisher repository using **real `git subtree add` operations**, runs explicit build tasks, assembles a static site, validates it, and optionally hands it to a publishing adapter.

This repository is an implementation workspace, not a claim of universal compatibility. Providers and build systems are supported only where an adapter exists and its contract is tested. The workflow generator targets GitHub Actions + GitHub Pages and GitLab CI + GitLab Pages; other CI systems can invoke the CLI directly, and other publishing providers require an adapter.

## Safety and non-goals

- Never run this tool against the only copy of important work. Use a disposable clone and preserve the original archive/repository separately.
- The engine does not push commits to the publisher or source repositories. An opt-in GitHub `repository_dispatch` contract can trigger a build from an exact source commit; the source-side notifier is a separate workflow template and requires an explicitly scoped secret.
- Publisher, build source, edit destination, issue destination and neighbor/navigation destination are separate identities. None of the link destinations is inferred from the publisher repository, source clone URL, or another link class.
- `git subtree` is mandatory for `integration.mode: git_subtree`; there is no checkout fallback.
- Build commands are executable + argument arrays, not implicit shell strings.
- Credentials are supplied through explicit environment-variable references and are not written into the public build manifest.
- A successful build is not proof that every external URL is reachable or that every Git provider's editor behavior is identical. The generated public site must be symlink-free; this invariant cannot be disabled. Static assets are copied from configured relative paths in the publisher checkout even when index generation is off.
- Repository-relative content/output configuration may not point into a `.git` metadata directory. File-copy paths preserve and reject symlink entries rather than dereferencing them into public output.

## GitHub Codespaces

An active Codespaces configuration is included at `.devcontainer/devcontainer.json` (not an example-only file). It provisions Python 3.13, Temurin Java 25 with Java 21 additionally available, Maven 3.10.0, Git LFS 3.8.1, and the Dockerfile-based Git Subtree installation into the active Git exec path. The Python bootstrap creates `.venv`, installs project dependencies whenever their declarations appear or change, and activates the project environment automatically in each new interactive Bash terminal. The post-start verifier rejects version drift and requires Python 3.13, Java 25 active plus Java 21 installed. See [`.devcontainer/README.md`](.devcontainer/README.md) before creating a new Codespace.

## Requirements

- Python 3.11+ (the current development run used Python 3.13)
- Git
- The `git-subtree` extension for source integration
- Optional: Git LFS when a source explicitly enables `vcs.lfs`

Install the package and dependencies:

```sh
python -m pip install .
documentation-publisher --version
```

For development, install the editable package with test dependencies:

```sh
python -m pip install -e '.[dev]'
```

## First setup

1. Run `documentation-publisher init-config --output publisher.yml` (or copy `publisher.example.yml` manually).
2. Replace every `<UPPERCASE_PLACEHOLDER>` with a real, reviewed value.
3. Configure publisher, source, authoring, public-site, and publishing identities independently.
4. Configure build tasks as `argv` arrays. Do not put secrets in arguments.
5. Configure the edit, issue and neighbor/navigation link destinations independently. Each has its own `inherit`, `override` or `disable` mode, selectors and target repository/path mapping; none is inferred from the publisher or source repository.
6. Configure the publishing adapter and workflow only if you intend to use them.
7. Run `documentation-publisher capabilities` to inspect which providers/adapters are actually implemented; labels do not enable unsupported providers.

The generic example intentionally contains unresolved URL and exact-host placeholders and **must fail validation until completed**. `init-config` never overwrites an existing target and creates the same packaged template used by the wheel. Wildcard host allowlists and malformed exact hostnames are rejected; add only actual publisher/source hosts you reviewed. Live publishing also rejects reserved example/test origins and non-global IP origins; keep those only in explicit dry-run fixtures. The Keycloak file is named `publisher.keycloak.smoke.yml` because it is project-specific and uses `https://example.invalid`; it is a dry-run fixture, not a live deployment config.

## CLI

The installable `documentation-publisher` console command and `python -m publisher_engine.cli` expose the same commands. Profile selection is consistent across all configuration-consuming commands; repeat `--profile` to layer profiles in order.

```sh
documentation-publisher init-config --output publisher.yml
documentation-publisher capabilities
documentation-publisher validate-config --config publisher.yml --profile staging
documentation-publisher plan --config publisher.yml --profile staging --components all
documentation-publisher build --config publisher.yml --profile staging --components all
documentation-publisher publish --config publisher.yml --profile staging
documentation-publisher generate-workflow --config publisher.yml --profile staging
# Multiple profiles are applied in the order supplied:
documentation-publisher publish --config publisher.yml --profile base --profile production
# Explicitly opt in to replacing an existing workflow after reviewing it:
documentation-publisher generate-workflow --config publisher.yml --profile production --replace-existing
```

`build` creates a temporary clone of the configured publisher ref, fetches each selected source, resolves its ref to a commit SHA, integrates that SHA with `git subtree add`, runs dependency-ordered tasks, assembles and validates the site, then cleans the workspace according to policy. The output directory is replaced only when the explicit safe-replacement option is supplied and the configured policy allows it. Workflow generation refuses to overwrite an existing workflow by default; `--replace-existing` is an explicit, separate opt-in.
When the configuration file lives below the checkout root, workflow generation keeps all paths aligned: the generated workflow is placed relative to the checkout root, its default config path points to the file passed with `--config`, and the Pages upload path is computed relative to that config file's directory.

## Configuration model

See:

- [Configuration contract](docs/CONFIGURATION.md)
- [Links and communication](docs/LINKS-AND-COMMUNICATION.md)
- [Git integration and security](docs/GIT-AND-SECURITY.md)
- [CI and publishing](docs/CI-AND-PUBLISHING.md)
- [Provider and adapter support contract](docs/PROVIDER-SUPPORT-CONTRACT.md)
- [Known limits and acceptance gates](docs/KNOWN-LIMITS.md)
- [Current reconciled project status](STATUS.md)
- [Archive lineage and canonical-source decision](audit/ARCHIVE-RECONCILIATION.md)
- [Historical hardening notes](audit/history/HARDENING-RELEASE-NOTES.md)

## Tests

The repository also defines a GitHub Actions compatibility matrix for Python 3.11, 3.12 and 3.13 in `.github/workflows/python-compatibility.yml`. It runs the core, manifest/cleanup, wheel-installation and process/timeout regression groups separately on each interpreter. The matrix must complete successfully before claiming cross-version acceptance.

For the complete automated test suite, install the package and development extra, then run the Codespaces acceptance script:

```sh
python -m pip install -e '.[dev]'
bash scripts/test-in-codespaces.sh
```

`requirements-dev.txt` is also provided for environments that install dependencies from requirement files; it includes the wheel build tools used by the package integration test.

The script first validates the environment, Python compilation, CLI/version/configuration/plan checks, and that `git subtree` is discoverable through the **current** Git exec path. It then runs four isolated regression groups (core, manifest/cleanup, wheel installation, and process/timeout), storing each output in a timestamped log file under `test-results/`. It does not modify a separate existing checkout, push, deploy, or contact external repositories. The underlying tests use local temporary Git fixtures for subtree integration.

For direct test-suite runs without the environment checks, run the groups separately. The packaging group builds and installs a wheel in an isolated temporary environment:

```sh
python -m pytest -q --ignore=tests/test_process.py --ignore=tests/test_packaging.py --ignore=tests/test_p6_p7_manifest_cleanup.py
python -m pytest -q tests/test_p6_p7_manifest_cleanup.py
python -m pytest -q tests/test_packaging.py
python -Werror::ResourceWarning -m pytest -q tests/test_process.py
```

See [TEST-IN-CODESPACES.md](TEST-IN-CODESPACES.md) for the isolated Codespaces procedure and safety boundaries.

## Status

This is a development implementation. Do not treat it as production-ready until the full acceptance matrix has been executed in the intended CI environment, provider-specific edit URLs have been verified against real repositories, and publishing credentials/permissions have been reviewed by the repository owner.

## Install and initialize

Install the project as a Python package (this installs the `documentation-publisher` console command and its packaged schema/templates):

```sh
python -m pip install .
documentation-publisher --version
```

For development and tests:

```sh
python -m pip install -e '.[dev]'
```

In a fresh clone, create a new generic configuration without copying files manually:

```sh
documentation-publisher init-config --output publisher.yml
```

The command never overwrites an existing file. It creates the generic fail-closed starter; replace every placeholder and then run `documentation-publisher validate-config --config publisher.yml`. `publisher.keycloak.smoke.yml` is deliberately not offered as an initialization template because it is project-specific and dry-run-only.

Inspect the exact implemented provider and adapter contract at any time:

```sh
documentation-publisher capabilities
```


Current status: see [STATUS.md](STATUS.md). Group 3 work is documented in [F12/F14/F15/F19 report](audit/R8-028/F12-F14-F15-F19-IMPLEMENTATION-REPORT.md).

## Automatic source-to-Publisher updates

See [docs/SOURCE-TO-PUBLISHER-AUTOMATION.md](docs/SOURCE-TO-PUBLISHER-AUTOMATION.md) for the cross-repository `repository_dispatch` contract, source-side workflow template, minimal token setup, exact-SHA subtree fetch, and Pages deploy gating.
