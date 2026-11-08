# Workblock 14 — automated source-to-Publisher deployment

**Project:** Documentation Publisher `2.0.14-dev`  
**Date:** 2026-11-08  
**Parent:** Workblock 13 (`workblock13.tar.gz`)  
**Parent SHA-256:** `c36e91248011a1499b33f5743c7774138f9ce3d43127081eca84c0412c2a687c`  
**Scope:** automate a push from the editable Keycloak fork through the Publisher build and validated GitHub Pages deployment.  
**Local status:** implementation, config validation, workflow generation, regression and exact-commit subtree fixture pass. Cross-repository GitHub installation/dispatch/Pages acceptance remains open.

## 1. Identity model and production configuration

| Role | Configured identity |
|---|---|
| Publisher / workflow owner | `devrimcode/documentation-publisher` |
| Physical build-source clone | `devrimcode/keycloak`, branch `main` |
| Source link provenance emitted by upstream Keycloak AsciiDoc headers | `keycloak/keycloak` |
| Edit this Section destination | `devrimcode/keycloak` |
| Issue destination | `keycloak/keycloak/issues` |
| Neighbor/navigation destination | `devrimcode/keycloak` |

`publisher.yml` now sets `sources[].vcs.clone_url` to the fork. `sources[].vcs.web_url` deliberately remains the upstream canonical Keycloak URL: the AsciiDoc header in the fork still emits original `keycloak/keycloak/tree/...` URLs, which the Keycloak adapter must recognize as source provenance before mapping them to the fork. This preserves the established separation of physical build source, incoming-link provenance, and the three independently configured final link destinations.

The fork is integrated read-only into the temporary Publisher working clone with the existing real `git_subtree` operation at `.publisher-sources/keycloak`. The Publisher engine never pushes to the source or Publisher repository.

## 2. Cross-repository event contract

`publisher.yml` adds:

```yaml
triggers:
  repository_dispatch:
    event_type: keycloak-documentation-updated
    source_id: keycloak
    source_repository: devrimcode/keycloak
    source_branch: main
```

The selected source declares `vcs.dispatch_sha_env: PUBLISHER_KEYCLOAK_SOURCE_SHA`.

The generated Publisher workflow listens only for the configured event type. Its source-event guard checks, before invoking the build:

- `client_payload.repository` equals `devrimcode/keycloak` (case-insensitive repository comparison);
- `client_payload.ref` equals `refs/heads/main` exactly;
- `client_payload.sha` is a full 40- or 64-character hexadecimal Git commit ID.

The SHA is passed to the build as `PUBLISHER_KEYCLOAK_SOURCE_SHA`. `publisher_engine.gitops.integrate_subtree()` validates it as a commit ref and fetches that exact commit. Without a dispatch SHA (manual Publisher run or Publisher-repository push), the integration continues to use the configured source branch/tag `main`.

This exact-SHA pinning avoids a race where the source branch advances between the source push event and when the Publisher runner fetches the repository. The actual fetched source commit continues to be recorded in the site build manifest.

## 3. Source-side notifier workflow

The archive includes:

`integration/source-repository/.github/workflows/notify-documentation-publisher.yml`

Copy this file to the source fork as:

`.github/workflows/notify-documentation-publisher.yml`

It runs on pushes to `main` and posts a `repository_dispatch` event to `devrimcode/documentation-publisher` with the configured event type and payload `{repository, ref, sha}`. It has only `contents: read` workflow permissions and does not print or embed a token.

The source repository must store a secret named `PUBLISHER_DISPATCH_TOKEN`. Use a fine-grained PAT (or a GitHub App installation token) restricted to the single receiving repository `devrimcode/documentation-publisher`, with the `Contents: write` repository permission required by GitHub's Create a repository dispatch event API. Do not store the token in the Publisher repository, YAML source, or generated build manifest. The required `Contents: write` scope is broader than the single dispatch API call, so restrict the fine-grained token to the one Publisher repository, do not expose it to pull-request workflows, protect the source fork's `main` branch, and require review for changes to the notifier workflow. A GitHub App installation token is an alternative for short-lived credentials, with the permission the endpoint requires.

GitHub's documentation states that a `repository_dispatch` workflow must exist on the receiver's default branch to run, and that fine-grained tokens need `Contents: write` on the receiving repository for the create-dispatch endpoint. See the links in the implementation handoff below.

## 4. Publisher build/deploy gate

The generated `.github/workflows/documentation-publisher.yml`:

1. Receives `keycloak-documentation-updated`.
2. Validates source repository, source branch and full SHA.
3. Runs the ordinary config validation and Publisher build.
4. Uploads the Pages artifact only when the build/validation succeeded and the Publisher run is on the configured deploy branch (`main`), never on a pull request.
5. Runs the separate Pages deploy job only when the build job explicitly reports `deploy=true`.

A failed build or failed site validation prevents the artifact/deploy steps from running, leaving the last successful Pages deployment as the public version. Existing concurrency behavior is retained so a newer source push supersedes stale in-progress work.

## 5. Files changed

- `publisher.yml` — clone source from `devrimcode/keycloak`, preserve upstream source-link provenance, add exact SHA environment and repository dispatch trigger.
- `publisher_engine/gitops.py` — additive, validated commit-SHA override in the existing git-subtree fetch path; no clone/checkout fallback was introduced.
- `publisher_engine/workflow.py` — generate `repository_dispatch` receiver, strict event payload guard, and pass event SHA to the configured source environment.
- `publisher_engine/config.py` and both schema copies — validate event type, source ID, source repository, branch, source clone URL match and SHA environment name.
- `publisher_engine/data/provider-capabilities.json` — advertise the GitHub repository-dispatch source trigger.
- `.github/workflows/documentation-publisher.yml` and `documentation-publisher.yml` — regenerate the Publisher workflow from production config.
- `integration/source-repository/.github/workflows/notify-documentation-publisher.yml` — source-side workflow template, stored separately so extracting this archive does not accidentally install it in the Publisher checkout.
- `docs/SOURCE-TO-PUBLISHER-AUTOMATION.md`, `docs/CI-AND-PUBLISHING.md`, `README.md`, `TEST-IN-CODESPACES.md`, `CURRENT-SOURCE.md`, `STATUS.md` — setup/operational documentation.
- `tests/test_workblock14_repository_dispatch.py` — new config, workflow, source-template, identity-separation and exact-commit integration coverage.
- `tests/test_packaging.py`, `scripts/codespaces_acceptance.py`, package version metadata — update to `2.0.14-dev`.

All nine `.devcontainer/` files are byte-identical to Workblock 13. The existing source integration remains `git_subtree`; only an opt-in exact commit SHA override was added to its ref selection.

## 6. Verification results

| Test group | Result |
|---|---:|
| Main regression excluding manifest/packaging/process groups | **289 passed, 1 skipped, 104 subtests** |
| Manifest and cleanup | **6 passed** |
| Wheel installation / packaging | **3 passed** |
| Process groups (`ResourceWarning` as error) | **6 passed** |
| Dedicated Workblock 14 repository-dispatch module | **11 passed** (included in main regression count) |
| Combined total across isolated groups | **304 passed, 1 skipped, 104 subtests** |
| Production `publisher.yml` validation | passed (1 source, 1 component, 1 task) |
| Production component plan | passed; `git_subtree`, `.publisher-sources/keycloak`, branch `main` |
| GitHub Actions workflow generation | passed |
| Generated receiver workflow YAML parse | passed |
| Source-side notifier YAML parse | passed |
| Dispatch event type and exact-SHA env wiring | passed |
| Draft 2020-12 schema meta-validation | passed |
| Root/package schema parity | byte-identical |
| Project manifest | **254 entries**; all verified after archive extraction |
| Python `compileall` | passed |
| Nine `.devcontainer/` files vs Workblock 13 | byte-identical |
| Exact SHA subtree test | passed: after source `main` advanced to commit B, a dispatch SHA for commit A caused the subtree to contain A, not B |

The one skipped test requires a real Git LFS client plus HTTP LFS batch/object fixtures; the local engine test environment did not have that HTTP fixture. The four regression groups were executed separately. A shell sequence that invoked them consecutively timed out while transitioning into the manifest group; the manifest group then passed independently (6/6), as did packaging (3/3) and process (6/6). No group failure remains.

## 7. External acceptance not performed

The implementation package does **not** install workflows or create secrets in GitHub. Still required after the user reviews and authorizes repository changes:

1. Put the generated Publisher receiver workflow and updated Publisher engine/configuration on `devrimcode/documentation-publisher` default branch `main`.
2. Copy the source-side notifier workflow into `devrimcode/keycloak/.github/workflows/`.
3. Create `PUBLISHER_DISPATCH_TOKEN` as a secret in `devrimcode/keycloak` with a fine-grained token restricted to the Publisher repository and the required Contents: write permission.
4. Confirm GitHub Pages deployment source is GitHub Actions.
5. Push a test documentation change to `devrimcode/keycloak:main` and observe the repository-dispatch run, exact fork commit in the build manifest, successful Pages artifact/deployment and final browser URLs.

The build was not run against the real remote fork in this tool environment because direct Git network access was unavailable. Workblock 14's exact-SHA subtree behavior is proven with a local bare-Git end-to-end fixture; the actual fork Maven build remains a Codespaces/GitHub Actions acceptance gate.

No `git add`, commit, push, pull request, remote workflow installation, secret mutation or Pages deployment was performed.
