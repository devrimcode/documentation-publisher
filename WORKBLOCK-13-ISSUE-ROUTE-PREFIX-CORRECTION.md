# Workblock 13 — GitHub issue route prefix correction

**Project:** Documentation Publisher `2.0.13-dev`  
**Date:** 2026-11-08  
**Parent:** Workblock 12 — `workblock12.tar.gz`  
**Parent SHA-256:** `6cb3b47652b9e60edbee74e3e7283e7ef1673b76f3ce0ff99673d9f78013994e`  
**Scope:** correct the independent issue-link target URL path after inspection of the user's Workblock 12 build output.  
**Status:** code, config, local regression and synthetic full subtree-build checks passed. The user's production Keycloak build must be rerun with this Workblock before remote/browser acceptance.

## 1. Defect observed in the actual Workblock 12 site

The user inspected the generated HTML in `_site` (10 HTML files) and compared it with `build-manifest.json`:

| Link class | HTML count | Manifest count | Expected destination |
|---|---:|---:|---|
| Edit | 362 | 362 | `devrimcode/keycloak` |
| Issues | **0 matching the `/issues` target prefix** | **375** | `keycloak/keycloak/issues` |
| Navigation | 259 | 259 | `devrimcode/keycloak` |

Edit and navigation destinations passed the user's exact URL-prefix check. Issue routing failed that same check even though 375 links were classified and reported as resolved.

Root cause in `build_routed_link_url()`:

- `source_prefixes` selected incoming links below `/keycloak/keycloak/issues`.
- `_prefix_suffix()` removed that source selector.
- For issue tickets, the remaining suffix (`123`, `new`, etc.) was appended directly to `target_url`.
- The production template was `"{target_url}/{path}..."`, so a ticket could be emitted as `/keycloak/keycloak/123`, not `/keycloak/keycloak/issues/123`.
- The old regression test asserted the incorrect `/repo/123` behavior, so this escaped the previous test suite.

This was a real defect in the previous Workblock's link resolver/configuration, not an error in the user's HTML inspection.

## 2. Corrective change

`target_url` continues to mean the destination repository root. The provider-specific issue route is explicit in the independently configured URL template.

For GitHub, production and smoke configuration now specify:

```yaml
links:
  issues:
    mode: override
    source_prefixes:
      - https://github.com/keycloak/keycloak/issues
    target_url: https://github.com/keycloak/keycloak
    url_template: "{target_url}/issues/{path}{query_suffix}{fragment_suffix}"
```

The resolver now represents the empty suffix for the issue-list root as an empty `{path}`. Non-empty suffixes are still path-mapped and safely encoded. The explicit template consistently places all of them beneath `/issues/`:

| Incoming source link | Destination with the example config |
|---|---|
| `/issues` | `https://github.com/keycloak/keycloak/issues/` |
| `/issues/new?template=bug.yml` | `https://github.com/keycloak/keycloak/issues/new?template=bug.yml` |
| `/issues/123?tab=comments#issuecomment-7` | `https://github.com/keycloak/keycloak/issues/123?tab=comments#issuecomment-7` |

Changing only `links.issues.target_url` to `https://github.com/xyz/mein-keycloak` sends all three to that repository, without changing Publisher, build source, edit target or navigation target. The route itself is explicit in `url_template`, not inferred from another repository identity.

## 3. Regression correction and new end-to-end coverage

- Updated the five-case independent-target regression matrix. Its prior assertions incorrectly accepted issue paths at `/repo/new`, `/repo/123` and `/repo/issues`. It now requires `/repo/issues/new`, `/repo/issues/123` and `/repo/issues/`.
- Added focused resolver coverage for issue-list root, issue creation, ticket numbers, query strings and fragments, with the destination changed to `xyz/mein-keycloak`.
- Added a synthetic full local `git_subtree` build test. It creates temporary publisher/source Git remotes, integrates the source with a real Git Subtree operation, builds generated HTML, resolves all three classes, and checks the final URLs in the assembled site.
- Updated both `publisher.yml` and `publisher.keycloak.smoke.yml` with the explicit GitHub issues route.
- Documented the target-repository-root versus provider-issue-route distinction in `docs/CONFIGURATION.md`.

The new real-subtree fixture passed and asserted: one edit, three issue, one navigation and one email link resolved. It verified final issue URLs under `/issues/` and the independent `xyz/mein-keycloak` issue destination.

## 4. Verification results

| Check | Result |
|---|---:|
| Main regression group | 278 passed, 1 skipped, 104 subtests |
| Manifest/cleanup | 6 passed |
| Wheel/package installation | 3 passed |
| Process/timeout (`ResourceWarning` is error) | 6 passed |
| **Total** | **293 passed, 1 skipped, 104 subtests** |
| Targeted independent-target and issue-route tests | 3 passed, 5 subtests |
| Production `publisher.yml` validation | passed; 1 source, 1 component, 1 task |
| Smoke config validation | passed; 1 source, 1 component, 1 task |
| Python compileall | passed |
| JSON Schema Draft 2020-12 validation | passed |
| Root/package schema and generic config template parity | byte-identical |
| Dev Container and Git Subtree source preservation | all 10 files byte-identical to Workblock 12 |

The single skipped test requires a real HTTP Git LFS batch/object fixture. The full test groups were run separately; the packaging and process groups both passed independently after a combined shell command exceeded its overall tool timeout following the main and manifest groups.

## 5. Preserved requirements and infrastructure

- Publisher: `devrimcode/documentation-publisher`.
- Read-only build source: `keycloak/keycloak`, `main`, integrated with real `git_subtree` at `.publisher-sources/keycloak`.
- Edit target: `devrimcode/keycloak`.
- Issue target: `keycloak/keycloak`.
- Neighbor/navigation target: `devrimcode/keycloak`.
- All three link targets remain separately configurable. The five-case test matrix includes changing each one alone and all three together to `xyz/mein-keycloak`.
- All nine `.devcontainer/` files and `publisher_engine/gitops.py` match their Workblock 12 hashes byte-for-byte.

## 6. Remaining external acceptance

The user's Workblock 12 real Maven/Keycloak build completed successfully, and its output confirmed 362 edit, 375 issue and 259 navigation link classifications. However, Workblock 12's issue destination path was wrong. The actual production Keycloak build must be rerun after installing Workblock 13. The user's same generated-HTML check should then find 375 issue links under `https://github.com/keycloak/keycloak/issues` (or whatever separate issue target is explicitly configured).

This Workblock does not claim that every remote `.adoc` or neighbor file exists in `devrimcode/keycloak`, that the user has write permission there, that browser click testing has passed, or that GitHub Actions / GitHub Pages deployment has run.

No `git add`, commit, push, pull request, upstream Keycloak mutation or deployment was performed.
