# Provider and adapter support contract

This document is a normative statement of implemented behavior, not a roadmap. The machine-readable registry shipped in `publisher_engine/data/provider-capabilities.json` is exposed by `documentation-publisher capabilities` and is covered by schema/runtime consistency tests.

## Implemented contracts

| Configuration surface | Accepted implementation | What it actually does |
|---|---|---|
| `workflow.provider` | `github_actions`, `gitlab_ci` | Generates either GitHub Actions + GitHub Pages or GitLab CI + GitLab Pages. GitLab CI requires `workflow.container_image` pinned by a full OCI SHA-256 digest and GitLab 17.9 or newer. |
| `sources[].vcs.provider` | `git` | Source checkout is Git. |
| `sources[].integration.mode` | `git_subtree` | Integrates a resolved Git commit with `git subtree`; there is no fallback checkout/materializer. |
| `publishing_targets[].adapter` | `artifact`, `filesystem`, `command` | `artifact` hands the build output to the generated GitHub Actions or GitLab CI workflow; `filesystem` copies locally; `command` executes explicit operator-supplied argv. None is a built-in remote hosting API client. |
| `components[].link_adapter` | `keycloak_asciidoc` | Rewrites the supported Keycloak AsciiDoc link/xref format into provenance-bearing publisher markers. |
| Authoring URL strategy | `edit_url_template` | Resolves a URL from explicit template and mapping. `provider`/`provider_label` is metadata and does not dispatch GitHub/GitLab/Bitbucket behavior. |
| Communication URL strategy | `mailto_template` / generic HTTPS template | Generates links using the shared formatter and configured host allowlist. `provider`/`provider_label` is metadata only; no provider issue/discussion API is called. |

## Explicitly not implemented

There is no provider-specific GitHub/GitLab/Bitbucket repository API publisher; no Bitbucket Pipelines, Azure Pipelines or Jenkins workflow generator; no Bitbucket Pages deployment adapter; no provider issue/discussion API client; no non-Git source materializer; and no provider-specific authoring adapter selected by a `provider_label` value.

## Validation behavior

The JSON Schema and semantic validator reject unsupported workflow providers, VCS providers, integration modes, publishing adapter IDs and component link adapters. For GitLab CI, the generator requires an immutable image digest, restricts Python to 3.11–3.13, rejects `workflow_call`, negated path filters, SSH-agent auth and secret-bearing merge-request pipelines, and removes common runner job-token variables before project pip-install, validation and build child processes. GitLab project/group variables referenced by `workflow.secrets` must be created and protected/masked by the operator. The CI job token still exists in the runner shell and its project permissions must be restricted in GitLab settings. Authoring/communication provider labels remain free-form display labels by design; they must never be interpreted as proof of adapter support. Use `documentation-publisher capabilities` as the authoritative machine-readable contract and inspect generated URLs/workflows before use.

## Adding a provider

A new provider is not enabled by adding a string to a label. It requires a concrete adapter contract, schema and semantic validation, explicit dry-run behavior, credential/environment allowlists, bounded process/network behavior, output validation, failure/rollback behavior where applicable, positive and negative tests, compatibility tests with the existing adapters, and an updated capability registry. The new adapter must be named in the registry only after its implementation and tests exist.
