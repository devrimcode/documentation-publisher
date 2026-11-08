# Workblock 12 — HTTP documentation links vs. redirect policy

**Project:** Documentation Publisher `2.0.12-dev`  
**Date:** 2026-11-08  
**Parent archive:** Workblock 11 — `workblock11.tar.gz`  
**Parent SHA-256:** `54625d251201eb68d6d6ed7d9c9f404f1604506ba66bed59853103bafaff2d08`  
**Scope:** correct the site validator so the redirect-scheme policy does not reject ordinary HTTP documentation hyperlinks.  
**Status:** local regression, configuration, schema, package and synthetic real-subtree build acceptance passed. The live Keycloak build must be rerun in the user's Codespace; remote link/browser/deployment acceptance remains open.

## 1. Failure reproduced from Codespace output

The Workblock 11 production build reached site validation and failed on ordinary generated HTML links in `docs/current/keycloak/server_admin/index.html`, including HTTP examples for `localhost:8080`, `broker-keycloak:8180`, `host.com/*$$` and `host:port`.

The production configuration intentionally retains:

```yaml
validation:
  validate_redirect_schemes:
    - https
```

That policy is appropriate for automatic redirects. It was incorrectly applied by `publisher_engine/engine.py` to every `href`, including normal `<a href="http://localhost:8080/...">` documentation examples. As a result, ordinary clickable documentation examples were mistaken for redirects.

## 2. Corrected behavior

`validation.validate_redirect_schemes` now applies only to actual redirect destinations:

- HTML `<meta http-equiv="refresh">` destinations;
- generated component fallback redirect URLs.

Ordinary `<a>` and `<area>` navigation anchors use the normal web/contact scheme set: `http`, `https`, `mailto` and `tel`. Active and unsupported schemes remain rejected. `data:` remains restricted to passive raster image data on `<img src>`. External-host validation remains a separate setting and is not silently enabled or disabled by this correction.

**Important:** `publisher.yml` still allows only HTTPS for redirects. The fix does not weaken the redirect policy by adding HTTP to `validate_redirect_schemes`.

## 3. Regression coverage

Added tests prove:

1. The exact classes of Keycloak HTTP example endpoints reported by the Codespace are accepted as normal anchors while `validate_redirect_schemes` remains `https` only.
2. HTTP meta-refresh remains rejected under the HTTPS-only redirect policy.
3. Unsupported anchor schemes such as `ftp:` remain rejected.
4. Active JavaScript links and JavaScript meta-refresh remain rejected.
5. A full synthetic local `git_subtree` build succeeds with the HTTP example anchors, preserves their original URLs in the generated HTML, and uses the same HTTPS-only redirect policy.

## 4. Files changed

- `publisher_engine/engine.py` — distinguish navigation anchors from actual redirects.
- `tests/test_p2_meta_refresh.py` — HTTP documentation-anchor and real local-subtree build regressions.
- `docs/CONFIGURATION.md` — document the scheme-policy distinction.
- `publisher_engine/__init__.py`, `pyproject.toml` — version `2.0.12-dev`.
- `scripts/codespaces_acceptance.py`, `tests/test_packaging.py` — update version acceptance.
- `CURRENT-SOURCE.md`, `STATUS.md`, this report and the project manifest.

The Workblock 11 publisher/source/edit/issue/navigation configuration is retained. The `.devcontainer/` files and `publisher_engine/gitops.py` are unchanged.

## 5. Verification results

| Check | Result |
|---|---:|
| Main regression (excluding manifest/package/process groups) | 276 passed, 1 skipped, 104 subtests |
| Manifest/cleanup group | 6 passed |
| Wheel packaging group | 3 passed |
| Process/timeout group (`ResourceWarning` treated as error) | 6 passed |
| **Total** | **291 passed, 1 skipped, 104 subtests** |
| Targeted `test_engine.py` + `test_p2_meta_refresh.py` | 215 passed, 96 subtests |
| `publisher.yml` configuration validation | passed: 1 source, 1 component, 1 task |
| Component plan | exactly `keycloak-documentation`; source mode `git_subtree`; prefix `.publisher-sources/keycloak` |
| Python `compileall` | passed |
| Both Draft 2020-12 schemas | valid |
| Root/package schema parity | byte-identical |
| Root/package generic example config parity | byte-identical |
| Archive manifest | all entries verified after packaging |

The one skipped test requires a real Git LFS client plus a live HTTP LFS batch/object fixture. The environment did not have the Git LFS executable; this is unrelated to the HTTP documentation-anchor correction. The user's separate Codespace environment has Git LFS installed.

## 6. External acceptance still required

This Workblock does not claim that the real upstream Keycloak Maven build has now passed. The user must rerun `documentation-publisher build --config publisher.yml --components all` after installing this source correction in the Codespace. Additional site-validation errors, if any, must be assessed individually rather than disabling validation wholesale.

Also still open: full inventory of upstream link forms, existence of each destination AsciiDoc/neighbor file on `devrimcode/keycloak`, user write permission for edit targets, browser click acceptance, GitHub Actions execution and GitHub Pages deployment.

No `git add`, commit, push, pull request, remote mutation or deployment was performed.
