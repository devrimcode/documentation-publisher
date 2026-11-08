# Workblock 11 — three independent link destinations

**Project:** Documentation Publisher `2.0.11-dev`  
**Date:** 2026-11-08  
**Parent archive:** `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-WORKBLOCK-10-EDIT-TARGET-SEPARATION.tar.gz`  
**Parent SHA-256:** `b7c2880dea2b2bd9f62b2a9796809ba132d9783536bee005f71274bff9eed2b9`  
**Scope:** finish the original Publisher/source/edit/issue/navigation identity separation.  
**Status:** local regression and configuration acceptance passed; real Maven/Codespaces/remote browser/deployment acceptance remains open.

## 1. Required identity model

The Publisher is `devrimcode/documentation-publisher`. It owns the engine, configuration and generated workflow. It is not automatically the repository targeted by links in the published documentation.

The build source is independently configured as `keycloak/keycloak`, read-only, on `main`, integrated into the temporary Publisher working clone using the existing real `git_subtree` mode and `.publisher-sources/keycloak` prefix.

The three link classes have three independently configured policies:

| Link class | Config entry | Workblock 11 example destination |
|---|---|---|
| Edit this Section / Edit this page | `links.edit` → `authoring_targets[]` | `https://github.com/devrimcode/keycloak` (`main`) |
| Issue links | `links.issues` | `https://github.com/keycloak/keycloak` |
| Neighbor/navigation pages | `links.navigation` | `https://github.com/devrimcode/keycloak` (`main`) |

No one of these identities or destinations is inferred from the Publisher checkout, source clone URL, or another link class. A second target configuration in the regression matrix routes all three link classes to `https://github.com/xyz/mein-keycloak` while leaving Publisher and build source unchanged.

## 2. Code corrections

### 2.1 Edit links

The Keycloak AsciiDoc adapter continues to validate the incoming edit URL using only `sources[].vcs.web_url` and `sources[].vcs.default_ref`. It extracts the exact source `.adoc` path and provenance. The regular authoring-target resolver then validates the original source file and maps the path to the separately configured `authoring_targets[]` repository/ref/template. The Publisher repository is not used as the default edit destination.

### 2.2 Issue links

Issue classification now uses the explicit `links.issues.source_prefixes` URL/path selectors, not visible text such as `Report an issue`. A renamed, localized, icon-decorated or ticket-number anchor is therefore still routed when its URL is in the configured issue class. The production profile uses the narrow selector `https://github.com/keycloak/keycloak/issues`; it does not select every URL under the source repository. Issue root, issue creation and numbered-ticket URLs retain their path/query/fragment through the explicit template. The destination is independent and may be changed without altering the source or Publisher.

`communication.issues` remains a separate generic communication-marker channel. It is not used as a substitute for the dedicated Keycloak issue-link target.

### 2.3 Neighbor/navigation pages

Navigation selectors are independent from edit and issue selectors. The adapter supports configured absolute HTTPS prefixes, root-relative prefixes (which cannot match absolute links to another host), and explicitly selected relative prefixes such as `../`. Relative links are resolved against `source_page_base_url` plus the current component-relative page path before the source prefix is checked. Fragment-only/self-page links are not converted.

Only page-like URLs (extensionless routes, `.html`, `.htm`, `.xhtml`) are routed as neighbor pages. Static PDFs/images/assets are not treated as navigation pages. The configured mapping supports exact path rules, source/target prefixes, stripping a version segment, and collapsing `index.html` to the directory before constructing the destination URL.

### 2.4 Configuration and schema

- Added/validated independent global `links.issues` and `links.navigation` policies and component-level `link_overrides`.
- Both policies support `inherit`, `override`, and `disable` with explicit source selectors.
- Added `relative_prefixes`, `source_page_base_url`, `strip_leading_segments` and `collapse_index_file` support with path/URL safety validation.
- Target URLs must be explicit HTTPS URLs; URL templates must preserve a specific mapped `{path}` and cannot escape the configured host/repository path or include credentials/sensitive query keys.
- Root schema and packaged schema are byte-identical. Root template and packaged template are byte-identical.
- `publisher.yml` uses the requested target split; `publisher.keycloak.smoke.yml` now demonstrates the same independent identities as a dry-run fixture with a reserved example origin.
- The GitHub Actions workflow was regenerated from `publisher.yml`.

## 3. Regression matrix

The new end-to-end fixture keeps Publisher and build source fixed and checks:

1. Separate destinations: edit=`devrimcode/keycloak`, issues=`keycloak/keycloak`, navigation=`devrimcode/keycloak`.
2. Change only the edit target to `xyz/mein-keycloak`.
3. Change only the issue target to `xyz/mein-keycloak`.
4. Change only the navigation target to `xyz/mein-keycloak`.
5. Change all three targets to `xyz/mein-keycloak`.

Each scenario verifies the final host, path, branch, query/fragment preservation where applicable, and that unrelated external links remain unchanged. The issue fixture includes `Report an issue`, a differently labelled issue-ticket anchor, and the issue-list root. The relative-navigation fixture verifies page routing while preserving fragment-only, same-guide and PDF download links.

## 4. Preservation of Workblock 10 infrastructure

The nine files under `.devcontainer/` and `publisher_engine/gitops.py` match their Workblock 10 `PROJECT-MANIFEST.SHA256` hashes byte for byte. No Dev Container provisioning file or Git subtree implementation file was modified for the link-routing change. The existing `git_subtree` source integration configuration and implementation are retained.

## 5. Tests and static checks

| Test/check | Result |
|---|---:|
| `tests/test_engine.py` | 197 passed, 96 subtests |
| Main separated regression group (excluding manifest/package/process groups) | 273 passed, 1 skipped, 104 subtests |
| Manifest/cleanup group | 6 passed |
| Packaging group | 3 passed |
| Process/timeout group with `ResourceWarning` treated as error | 6 passed |
| Combined separated groups | 288 passed, 1 skipped, 104 subtests |
| `publisher.yml` config validation | passed; 1 source, 1 component, 1 task |
| `publisher.keycloak.smoke.yml` config validation | passed; 1 source, 1 component, 1 task |
| Component plan | selected exactly `keycloak-documentation`; source integration reported as `git_subtree` |
| Workflow generation | passed |
| Python `compileall` | passed |
| JSON Schema Draft 2020-12 meta-validation | passed |
| Root/package schema parity | byte-identical |
| Root/package generic config template parity | byte-identical |
| `.devcontainer` and `gitops.py` preservation | all 10 original hashes verified |

The single skipped test requires a real Git LFS client, which is not installed in this environment. The packaging group and process group passed when executed separately after an outer combined test command hit its time limit; no test failure remains in those groups.

## 6. Open external acceptance gates

This local Workblock does not claim:

- a real Keycloak Maven documentation build;
- a fresh Docker/GitHub Codespaces rebuild using the updated archive;
- a full inventory of every generated upstream Keycloak HTML link form;
- that every destination `.adoc`/neighbor file exists on the remote `devrimcode/keycloak` branch;
- that the current GitHub user has write access to the edit destination;
- browser click acceptance for edit, issue and neighbor links;
- successful GitHub Actions execution, GitHub Pages deployment or HTTP smoke test.

These are external acceptance steps for the fresh Codespace/repository. Local tests prove that configured source selectors and destinations are kept independent and that their URL transformations behave as specified for the fixtures.

## 7. Git/repository operations

No `git add`, commit, push, pull request, GitHub Actions run, repository mutation or Pages deployment was performed. The original Workblock 10 archive remains unchanged; this Workblock is a new complete project archive built from its verified extraction.
