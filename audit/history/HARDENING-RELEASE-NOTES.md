# Hardening release notes

## 2.0.10-dev — 2026-11-06

This separate correction iteration continues from the hash-verified R8-based 2.0.9-dev tree. R8 and the 2.0.9-dev package remain unchanged.

### R8-009 — GitHub Pages Project-Site base path

- Apply `site.base_path` to root-relative local references in copied and generated HTML, XHTML, SVG and CSS before local-site validation.
- Cover `href`, `src`, `poster`, `action`, `formaction`, `cite`, `background`, `manifest`, `data`, `xlink:href`, `srcset`, inline styles, `<style>` blocks, CSS `url(...)`, CSS `@import`, and meta-refresh targets.
- Preserve relative, fragment-only, protocol-relative and external URLs. Avoid double-prefixing paths that already contain the configured base path.
- Keep canonical URLs and `{page_url}` template values on the same origin/base-path join rule; support a custom canonical origin with a Project-Site path.
- Make HTML and CSS local-link validation resolve prefixed root-relative paths back to the generated site tree.

### Verification scope

- Regression tests cover domain-root deployment, Project-Site deployment, custom canonical origin, query/fragment preservation, idempotence, HTML attributes, `srcset`, meta refresh, inline and block CSS, CSS files, and `{page_url}` template context.
- A real local Git-subtree fixture build verifies rewritten HTML, static CSS, assets, canonical URL generation and local-link validation together.
- This is a targeted correction for R8-009 only. It does not close R8-011 or the other open audit findings and is not a release candidate.

## 2.0.9-dev — 2026-11-06

This is a separate correction build based on the hash-verified R8 2.0.8-dev archive. The original R8 package remains unchanged.

### Security, validation and workflow corrections

- Protect build and filesystem publishing outputs from Git metadata and tracked repository content; reject unsafe workspace paths before creation.
- Enforce fail-closed dry-run workflow generation, least-privilege permissions, reserved environment variables, and checkout credential non-persistence.
- Validate component route overlaps, output paths, Git refs, repository URL schemes, site origins and artifact output-path consistency before execution.
- Apply the configured base path to canonical/page URLs and `noindex` to all generated HTML; tighten active HTML URL validation.
- Clarify project metadata and external-link validation semantics; improve bounded `git subtree` preflight diagnostics.
- Add a Keycloak AsciiDoc edit-link adapter that records exact `.adoc` provenance from the header-generated GitHub tree link and preserves issue links.

### Verification and release status

- **134 unit and local regression tests pass**.
- Python compilation and the Keycloak example configuration validation pass.
- Keycloak adapter fixture checks validate the current upstream link shape; a complete Keycloak Maven build and browser/editor acceptance test remain outstanding.
- R8-017 (real Git LFS behavior), R8-019 (plan dependency closure), R8-021 (bounded ZIP central-directory processing), and R8-022 (bounded subprocess streaming/process-tree cleanup) remain open.

**NOT RELEASE READY.** Do not publish this development build until all open findings and the real Keycloak acceptance gate are closed. See `R8-CORRECTION-STATUS.md` and `TEST-REPORT-2.0.9-dev.md`.

## 2.0.8-dev — 2026-11-05

This iteration builds on `2.0.7-dev`. Earlier release archives remain separate and unchanged.

### Explicit workflow output path

- The CLI `generate-workflow --output` override no longer bypasses Git-metadata protection.
- Existing parent symlinks are resolved before writing; paths that resolve inside a `.git` directory are rejected.
- Final-component symlinks remain rejected.
- An explicitly chosen output directory outside the checkout is still supported.
- Three regression tests cover direct `.git` output, a symlinked parent into `.git`, and a valid external output directory.

### Verification

- The 108-test suite, Python compilation, CLI help/version, strict workflow YAML parsing, and JSON Schema self-validation are rerun for this source state.
- This remains a development build, not a production release. See `TEST-REPORT.md` and `docs/KNOWN-LIMITS.md`.

## 2.0.7-dev — 2026-11-05

This iteration builds on the previously delivered `2.0.6-dev` package. Earlier release archives remain separate and unchanged.

### Repository and workflow path handling

- `safe_child` now checks the resolved path as well as the configured spelling and rejects a symlink that resolves into a `.git` metadata directory.
- The generated GitHub Pages artifact path now combines the repository-relative `workflow.config_file` directory with `site.output_directory`. This matches the build engine's behavior when the configuration lives in a subdirectory.
- When `workflow.config_file` is omitted, the CLI records the exact `--config` file path relative to the nearest checkout root.
- Default `workflow.file` output is repository-root-relative and generated at the checkout root, including when configuration resides in a nested directory. Outside a checkout, the configuration directory is the fallback root.
- Documentation now specifies these path bases explicitly.

### Verification

- **105 unit and local integration tests pass.**
- Product-code coverage: **79.3% statements** (1,833/2,311) and **65.4% branches** (811/1,240).
- Python compilation, CLI help/version, generated workflow YAML parsing, and JSON Schema self-validation pass.
- The suite includes a real local `git subtree add` run, but no live remote repositories, LFS server, or production/staging publishing target.
- The test environment is Linux only; there was no native Windows runner.

**This remains a development build and is not production-ready.** See `TEST-REPORT.md` and `docs/KNOWN-LIMITS.md` for limitations and mandatory release gates.

## Previously delivered 2.0.6-dev baseline

- Configuration loading was reordered to validate the profile-merged structure before and after environment interpolation; malformed nested values return `ConfigError` instead of incidental Python exceptions.
- That release contained 100 tests and reported 79.1% statement / 65.2% branch coverage on its own source state.

## Incremental P1 correction — independent validation switches

- Decoupled local link existence checks from fragment validation, external-host allowlisting, HTML nesting-depth limits, and always-on active-content protections.
- Decoupled local CSS asset existence checks from external CSS host validation.
- Added seven regression tests for switch independence and preservation of the other checks when one option is disabled.
- Verification on the complete P1 project archive: 149 tests passed; Python compilation passed.

This is an incremental development correction, not a release approval. P2–P7 and the outstanding R8 audit gates remain open.

## Incremental correction P2 — meta-refresh validation

- Treats `meta http-equiv="refresh"` destinations as navigation/redirect targets during HTML site validation.
- Applies `validate_redirect_schemes`, `validate_external_links`, local-target existence and fragment checks to those destinations.
- Rejects active/unsupported schemes, `data:` URLs, and `mailto:`/`tel:` refresh destinations; rejects malformed quoted destinations even when local-link checks are disabled.
- Keeps delay-only refresh declarations without `url=` valid.
- Differential evidence: the same 15 P2 tests yield 11 failures and 4 passing controls on a fresh P1 baseline, then 15/15 pass on the P2 candidate.
- Full cumulative suite: 164 passed, 0 failed. A local Git-subtree build containing a JavaScript meta-refresh is rejected before site output is committed.

This incremental correction does not make the package release-ready or close other open audit findings.

## Incremental correction P3 — workflow deploy decision propagation

- Forward the `decision` step's `deploy` output through `jobs.build.outputs.deploy` so the downstream deploy job can read it via `needs.build.outputs.deploy`.
- Keep dry-run workflows free of deployment decision outputs and deploy jobs.
- Add YAML-parsing regression tests for the producer/consumer output contract and dry-run behavior.
- Differential result: 3 failures on the fresh P2 baseline (plus one passing dry-run control); 4/4 P3 tests pass on the corrected candidate.
- Full cumulative P1+P2+P3 regression: 168 tests passed.
- No live Actions run or publication was performed. P4/P5 and the outstanding original audit findings remain open.
