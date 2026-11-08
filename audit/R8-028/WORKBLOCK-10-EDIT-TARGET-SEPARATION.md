# Workblock 10 — independent source and authoring repository links

**Date:** 2026-11-08  
**Parent:** Workblock 09 Codespaces VENV bootstrap archive  
**Parent SHA-256:** `5dd87eac59a4509c3356dc8f32948d99398879b4fc6c47e8672ad60699dd29be`  
**Package:** Documentation Publisher `2.0.10-dev`  
**Status:** local code/config tests passed; production source-file and external deployment acceptance remain open.

## Requirement

Keycloak `Edit this section` / `Edit this page` links in generated HTML must point to matching editable source files in `devrimcode/documentation-publisher`, branch `main`, not `keycloak/keycloak`. Keycloak remains the read-only build source. `Report an issue` links remain pointed to the official Keycloak issue tracker.

## Root cause

The previous adapter used the configured `authoring_targets[].web_url/repository/ref` to validate the incoming upstream edit href. This coupled the source identity to the edit target. A YAML-only change to `authoring_targets[]` caused the adapter to reject the original Keycloak href as a repository/ref mismatch.

## Changes

1. Added optional, explicit `sources[].vcs.web_url` to the schema and config validation. It represents the browser URL for the build source and stays distinct from `clone_url` and the authoring target.
2. The Keycloak AsciiDoc adapter now validates incoming header links against `sources[].vcs.web_url` and `sources[].vcs.default_ref` only. It extracts the source-relative `.adoc` path and creates provenance markers.
3. Existing authoring-target mapping then resolves that source path independently to the configured Publisher repo URL/ref/path.
4. Added documentation that only dedicated edit markers are rewritten; report-issue links, other unmarked links, and ordinary local site navigation remain separate.
5. Production `publisher.yml` now sets the edit destination to `https://github.com/devrimcode/documentation-publisher`, branch `main`, with `docs/documentation` → `docs/documentation` mapping. The public Pages origin remains `https://devrimcode.github.io/documentation-publisher/`.
6. Regenerated `.github/workflows/documentation-publisher.yml` from that production config.

## Regression evidence

- Targeted Keycloak adapter tests: 2 passed.
- Core group: 265 passed, 1 skipped, 99 subtests.
- Manifest/cleanup: 6 passed.
- Packaging: 3 passed.
- Process/timeout: 6 passed.
- Combined separated groups: 280 passed, 1 skipped, 99 subtests.
- `python -m publisher_engine.cli validate-config --config publisher.yml`: passed.
- `python -m publisher_engine.cli plan --config publisher.yml --components all`: passed; selected exactly `keycloak-documentation`.
- `generate-workflow`: passed.
- Root schema and packaged schema are byte-identical.

The single skipped test requires a real Git LFS executable not installed in this environment. A monolithic pytest invocation exceeded the outer timeout; all documented test groups completed successfully when run separately.

## Crucial target-file availability finding

A read-only GitHub tree inspection of `devrimcode/documentation-publisher` branch `main` returned only `README.md` and the three Workblock archive files. There is currently no `docs/documentation/` tree in that branch. Therefore the generated editor URL has the correct independent Publisher repository destination, but the corresponding target `.adoc` file will 404 until the source files are present in the Publisher repository at the configured mapped path. This must be solved as a repository-content decision; no fake success is claimed.

## Not performed

No Keycloak Maven build, live Pages workflow run, Pages deployment, browser/editor click-through test, Codespaces rebuild, Git stage/add, commit, push, pull request, or upstream modification was performed.
