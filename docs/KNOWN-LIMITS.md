# Known limits and acceptance gates

This implementation is deliberately not described as universal or production-ready. The following areas require additional adapters or live-environment acceptance before relying on them:

- Git provider-specific authentication, ref semantics, rate limits, LFS and nested submodules. Nested submodules are rejected; no recursive submodule materializer is provided.
- Generated CI workflows currently support GitHub Actions and GitLab CI. GitLab Pages requires GitLab 17.9+, an operator-supplied OCI image pinned by digest, and a real external pipeline acceptance. Bitbucket Pipelines, Azure Pipelines, Jenkins and Buildkite do not have native workflow generators yet.
- GitHub Pages and GitLab Pages are the current generated deployment targets. Other hosting systems need dedicated publishing adapters.
- Authoring/communication `provider_label` values (and the deprecated `provider` alias) are metadata only; they do not select provider adapters. Authoring URLs are produced by `edit_url_template`; communication URLs use the shared generic template formatter. Provider-specific route, encoding, authentication and API behavior is not implemented and must not be inferred from a label. GitHub/GitLab/Bitbucket and self-hosted installations can differ.
- Build tasks are trusted code running with runner permissions, not isolated sandboxes.
- Repository-relative paths reject colon-bearing segments, NUL characters, and `.git` metadata path segments to prevent drive/alternate-data-stream ambiguity and accidental writes into Git internals. Local HTML/CSS URL validation normalizes backslashes before traversal checks, but a real Windows runner acceptance pass is still required.
- Public output is required to be symlink-free. `validation.require_no_symlinks: false` is rejected; symlinks are not a supported publishing feature.
- Static asset sources must be inside the publisher checkout, and asset destinations must not overlap generated routes, index files, the build manifest, or the configured not-found page.
- Symlinks in component/static-asset trees are copied as links (never intentionally dereferenced) and then rejected; regular-file copies use `O_NOFOLLOW` where the platform provides it. This reduces symlink-following risk but still needs acceptance on the actual target OS/filesystem.
- Git LFS remote lifecycle has mock-based unit coverage only; an actual LFS server and credential flow still require an acceptance test.
- External links are not guaranteed to be reachable unless external checking is explicitly enabled and network behavior is controlled.
- Source provenance depends on the configured build adapter emitting accurate source mappings. The publisher cannot infer include provenance reliably from arbitrary generators.
- Edit, issue and navigation link destinations are independently configurable. The Keycloak adapter classifies edit links by source repository/ref and exact anchor label, issue links by configured URL `source_prefixes` regardless of their visible label, and neighbor pages by configured absolute/root-relative prefixes and optional relative prefixes resolved from `source_page_base_url` plus the current component-relative page path. Neighbor classification is limited to extensionless and HTML page paths, not static downloads/assets. URLs outside those explicit selectors are deliberately left unchanged; every source URL form used by a project must be listed in its profile. Remote destination path existence and user write access are not verified by offline link rewriting.
- Locale/version routing, redirect semantics and canonical URLs must be verified against each site's actual routing strategy.
- `private_target_attested: true` (and legacy `private_target: true`) is an operator assertion, not a technical verification of an external endpoint's privacy or ACL. Production security destinations require independent provider-side access-control acceptance.
- Dynamic communication channel names and query-key names are constrained by schema and semantic validation. `inherit`/`disable` cannot carry ignored override settings, and channel-specific override fields are checked to prevent silent no-ops.
- The JSON Schema and semantic validator must evolve together; every new option requires positive and negative tests.

## Release gates

Do not release until all are true:

1. Full unit and integration tests pass on the production Python/Git versions.
2. A real representative source repository is integrated by `git subtree add` in a disposable clone.
3. Source and authoring repositories are demonstrably distinct in at least one acceptance fixture.
4. Each editable page has a verified provenance mapping and a manually opened editor URL.
5. Edit, issue and navigation destinations are separately exercised with three different repositories and with all three pointed at one alternate repository; every mapped remote path is confirmed to exist.
6. `inherit`, `override`, and `disable` are verified for every supported communication channel.
7. Every enabled security-report endpoint is private and access-controlled.
8. Workflow action SHAs, permissions, secrets and branch protections are reviewed.
9. Build failure, timeout, cancellation and cleanup failure behavior are tested.
10. Publishing is tested against a staging destination with rollback/verification.
11. The original archive and repository remain preserved; deployment is explicitly approved.

- `init-config` creates a new generic starter but deliberately does not guess repository URLs, refs, host allowlists, authoring mappings, credentials or provider choices. The generated file is intentionally invalid until the operator replaces all required placeholders.
- A wheel and `documentation-publisher` console entry point are now provided by `pyproject.toml`; the CLI package includes its schema, generic template and provider capability registry. Installing the package does not imply support for any remote provider API that is not listed as implemented by `documentation-publisher capabilities`.
