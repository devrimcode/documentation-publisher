# R8-028 Group 3 — F12, F14, F15 and F19

**Source:** canonical P12 reconciled Group 2 only. This report describes the new Group 3 source tree; historical Group 1/2 totals remain under `audit/history/` and earlier `audit/evidence/` logs.

## F12 — safe first-run initialization

Added `documentation-publisher init-config` (also available through `python -m publisher_engine.cli`). It copies the packaged generic `publisher.example.yml` unless `--template` specifies a separate regular, non-symlink YAML file. The default output is `publisher.yml`; `--output` selects another path.

Safety contract:

- destination must not already exist; exclusive-create semantics prevent overwrite/race replacement;
- a destination symlink is rejected;
- parent directory must already exist and resolve successfully;
- writing beneath a `.git` path is rejected;
- no directories, repository owners, names, branch names, hosting provider, credentials or deployment targets are guessed;
- the generated file remains fail-closed until required placeholders are replaced;
- the Keycloak smoke config is deliberately not used as a starter because it is project-specific and dry-run-only.

Tests cover default packaged template, required placeholders, no-overwrite, symlink/.git protection, missing parent and custom regular template. The package test also invokes the installed wheel's console command to create a config from outside the checkout.

**Local contract: closed.** Actual use in the user's new GitHub repository remains an external integration acceptance, not something performed by this archive build.

## F14 — installable Python distribution

Added PEP 621 metadata in `pyproject.toml`, a PEP 517/setuptools build configuration, runtime dependencies, a `dev` extra, package-data declarations and the installed command:

`documentation-publisher = publisher_engine.cli:main`

The wheel contains the schema, generic config starter and provider capability registry. Runtime schema loading uses `importlib.resources`, so installed configuration validation no longer depends on a sibling `schemas/` directory or a source checkout. Root schema and package schema, and root generic template and package template, are compared byte-for-byte by regression tests.

The packaging test builds a wheel, checks `METADATA`/`entry_points.txt` and packaged resources, installs it in a temporary virtual environment, then runs the installed `documentation-publisher --version`, `init-config`, `capabilities` and `validate-config` commands from outside the source checkout. The last command validates the Keycloak smoke fixture while the source tree is not on `sys.path`, proving the installed wheel resolves its packaged JSON Schema rather than a checkout-relative file.

**Local Linux wheel build/install contract: closed.** No PyPI/package-index upload or Windows/macOS wheel install was performed. Version remains a development version (`2.0.10.dev0` distribution metadata; CLI displays `2.0.10-dev`).

## F15 — explicit provider/capability contracts

Added the versioned machine-readable file `publisher_engine/data/provider-capabilities.json` and `documentation-publisher capabilities`. It declares exactly what is implemented and separately lists provider/API families that are not implemented.

Declared implementation surfaces:

- workflow: `github_actions` only, targeting GitHub Pages artifact/deploy;
- source VCS: `git` only, with `git_subtree` integration;
- publishing: `artifact`, `filesystem`, `command`; none is a built-in remote hosting API client;
- component link adapter: `keycloak_asciidoc` only;
- authoring links: explicit `edit_url_template`; provider labels are metadata only;
- communication: `mailto_template` and generic HTTPS URL templates; no provider issue/discussion API clients.

Tests compare the registry IDs with the schema enums/constants and verify unsupported workflow, VCS, publishing and component-link identifiers are rejected. Registry descriptions do not create adapters; GitLab/Bitbucket pipelines/pages and provider REST API publishing remain unsupported.

**Capability contract: locally explicit and schema-consistent.** Additional provider implementations remain a separate feature, not claimed as closed by documentation alone.

## F19 — uniform ordered profile selection

`--profile NAME` is now repeatable on `publish` and `generate-workflow`, matching the existing `validate-config`, `plan` and `build` commands. `publish()` accepts the same profile list through its API. Profile names must match `^[a-z][a-z0-9_-]{0,63}$`; duplicate selections are rejected. Selection order is preserved through the deep-merge sequence.

When profiles are selected during workflow generation, the generator includes the same ordered `--profile` arguments in both generated `validate-config` and `build` commands. This prevents CI from silently reverting to an unprofiled configuration after the local generation step.

Tests cover CLI forwarding, API behavior, invalid/duplicate IDs and exact profile forwarding into both generated workflow commands.

**Local CLI/profile propagation contract: closed.** The generated workflow has not been run on GitHub Actions, and a production publish has not been executed.

## Acceptance limits

The tests prove local CLI, file, wheel, registry, schema and generated-YAML behavior. They do not prove the final workflow on a hosted runner, external provider API support, a release upload, a real Codespace build or a production deployment. Those remain distinct acceptance gates.
