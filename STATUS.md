# Status — Workblock 15

- Version: `2.0.15-dev`.
- Current candidate is a complete project-tree reconstruction from the verified Workblock 14 archive (SHA-256 `d5bf9f38cd3c8d41888421e9093f8ecb690c17458d23ca11ac96f1b76414165e`).
- Keycloak source-link adapter supports both the current upstream `/edit/{ref}/docs/documentation/...` URL and the legacy `/tree/{ref}/docs/documentation/...` format. The source provenance, edit destination, issue destination and neighbor/navigation destination remain independent.
- The current upstream header was inspected at Keycloak source commit `c5b9177451d77adc3807a4a3bd0583c3dc79402c`; it defines `docs_repo_edit_base` as `https://github.com/keycloak/keycloak/edit/main`.
- Python 3.11 syntax compatibility is restored in the GitLab workflow generator. All 25 project Python files parse under Python 3.11 grammar.
- Dev Container runtime tests use a deterministic Python 3.13 fixture by default, so their assertions do not accidentally depend on a Python 3.11/3.12 CI runner version.
- Production GitHub Actions workflow now pins Temurin JDK 25 setup and exports the Maven Resolver retry flags used by Keycloak's own documentation workflow.
- Concurrency can be ref-scoped; production uses a unique group per Git ref and does not cancel a running job. Repository-dispatch runs check source-head freshness before artifact upload and immediately before Pages deployment.
- Local regression results in the recovered build environment: main 292 passed, 1 skipped, 104 subtests; manifest/cleanup 6 passed; packaging 3 passed; process groups 6 passed. Combined isolated groups: **307 passed, 1 skipped, 104 subtests**.
- The skipped test requires a real HTTP Git LFS batch/object fixture; this container did not provide that fixture. Python 3.11 grammar was checked, but native Python 3.11/3.12 matrix runs remain external.
- Production config validates (1 source, 1 component, 1 task). Generated Actions YAML parses with duplicate-key rejection. Root/package schema copies are identical.
- Not yet externally accepted: actual Maven build against the current fork revision in GitHub Actions, source notifier installation, dispatch token, a real repository-dispatch run, Pages source configuration, and successful live Pages deployment.
- No GitHub repository was deleted or modified by this workblock. No `git add`, commit, push, PR, remote secret mutation or deployment was performed.

---

## Workblock 13 — GitHub issue route prefix correction (historical)

Detailed evidence: `WORKBLOCK-13-ISSUE-ROUTE-PREFIX-CORRECTION.md`.

- User's generated Workblock 12 site had 362 edit links matching the expected `devrimcode/keycloak` target, 259 neighbor links matching the expected navigation target, and 375 issue links recorded in the manifest but zero matching the intended `/issues` target prefix.
- Root cause: the issue selector prefix `/keycloak/keycloak/issues` was stripped, and the old URL template appended the remaining suffix directly to the repository root. This generated `/repo/123` rather than `/repo/issues/123`. A prior regression assertion encoded the incorrect result.
- Correction: the resolver emits an empty suffix for the issue-list root; production and smoke `links.issues.url_template` explicitly place the mapped suffix below `{target_url}/issues/`.
- Query strings and fragments are preserved. `target_url` remains the independently configured repository root.
- Added targeted issue-root/new/ticket/query/fragment tests and a full synthetic real-Git-Subtree build checking final edit/issue/navigation links.
- The `.devcontainer/` tree and `publisher_engine/gitops.py` are unchanged byte-for-byte from Workblock 12 (10 files checked).
- Version: `2.0.13-dev`.
- Regression: main 278 passed, 1 skipped, 104 subtests; manifest/cleanup 6; packaging 3; process 6. Total 293 passed, 1 skipped, 104 subtests.
- Production `publisher.yml` and smoke config validation, component plan, Python compileall, schema validation and schema/template parity passed.
- External gate: rerun the actual Keycloak Maven build in the user's Codespace with Workblock 13 and rerun the generated-HTML link-prefix inspection. Remote edit/navigation target-file existence, write permissions, browser links, GitHub Actions and Pages deployment remain open.
- No `git add`, commit, push, pull request or deployment.

## Workblock 12 — HTTP documentation anchors vs. redirects (current)

Detailed evidence: `WORKBLOCK-12-HTTP-DOC-LINK-SCHEME-CORRECTION.md`.

- Root cause: `validation.validate_redirect_schemes: [https]` was incorrectly being applied to ordinary HTML anchor hrefs, rejecting legitimate HTTP Keycloak service examples.
- Correction: that allowlist now applies to actual meta-refresh and fallback redirects. Ordinary `<a>`/`<area>` navigation anchors allow `http`, `https`, `mailto` and `tel`; active/unsupported schemes remain blocked.
- The production redirect policy remains HTTPS-only; no broad `http` exception was added to the redirect allowlist.
- Workblock 11's five independent identities (Publisher, source, edit, issue, neighbor/navigation) and all three independently configurable link classes are preserved.
- Git subtree and Dev Container infrastructure are preserved. No changes to `.devcontainer/` or `publisher_engine/gitops.py`.
- Version: `2.0.12-dev`.
- Regression: main 276 passed / 1 skipped / 104 subtests; manifest/cleanup 6; packaging 3; process 6. Total 291 passed, 1 skipped, 104 subtests.
- Synthetic end-to-end local Git subtree build with the HTTP URLs from the user's error output passed. Those links remained intact in generated HTML; HTTP meta-refresh was still rejected.
- Production `publisher.yml` validation, component plan, compileall, schema validation and schema/template parity passed.
- External gate: actual upstream Keycloak Maven build must be rerun by the user in Codespaces. Other open gates include remote target-file existence/permissions, browser links, GitHub Actions and Pages deployment.
- No `git add`, commit, push, pull request or deployment.

## Workblock 10 — independent source and edit-target separation (superseded as current status)

Workblock 10 separated the original Keycloak source identity from the edit target, but still left issue links and ordinary neighbor navigation outside the independent routing model. Workblock 11 builds on that code and completes the three-way routing configuration. The original Workblock 10 archive remains unchanged and is the verified immediate parent (SHA-256 `b7c2880dea2b2bd9f62b2a9796809ba132d9783536bee005f71274bff9eed2b9`).

## Workblock 09 — Codespaces Python virtual-environment bootstrap correction (parent)

- **Root cause:** the publisher archive already declared PyYAML and jsonschema correctly. The Dev Container `postCreateCommand` only installed the application when `pyproject.toml` existed at the time of that one lifecycle event. If the Codespace was first created from a branch containing only a README or only `.devcontainer/`, then the Publisher source arriving afterwards did not automatically replay `postCreateCommand`. The configured VS Code Python interpreter preference also did not guarantee activation in an already-open Bash terminal.
- **Bootstrap:** `.devcontainer/ensure-python-environment.sh` is now the common idempotent environment entry point. It validates Python 3.13, recreates a stale/wrong-version `.venv`, fingerprints `pyproject.toml` and requirements files, and installs the full runtime/development declaration when the fingerprint or import/package checks show drift.
- **Lifecycle:** `post-create.sh` invokes the common bootstrap. `postStartCommand` invokes it again before strict toolchain verification, so files added while a Codespace is already established are discovered on the next container start.
- **Terminal activation:** the bootstrap installs one guarded `.bashrc` hook. Every new interactive Bash terminal locates the nearest repository bootstrap, rechecks dependency declarations, then activates that repository's `.venv`. This covers source files added after the initial create without asking the user to manually install a single missing dependency.
- **Fail-closed checks:** the environment verifier now rejects a project checkout whose `.venv` or required imports/package metadata are absent. The Codespaces acceptance script checks that `sys.prefix` resolves to the repository `.venv`, not merely that Python 3.13 exists.
- **Tests in the isolated build environment:** targeted Dev Container tests: 35 passed plus 8 subtests. Main regression group: 265 passed, 1 skipped, 99 subtests. Manifest/cleanup: 6 passed. Packaging: 3 passed. Process/timeout: 6 passed. Across these isolated groups: 280 passed, 1 skipped, 99 subtests. The skipped test requires a real Git LFS executable. A monolithic `pytest -q` run hit its 120-second external timeout; the project's documented isolated groups completed.
- **External acceptance remains open:** no actual Docker/Codespaces image rebuild was run here. The user's next fresh/rebuilt Codespace must verify `.venv`, terminal activation, `python -c 'import yaml'`, the complete Codespaces acceptance script, and the outstanding real Git LFS test.

## Group 3 changes and Workblock 04 additions

- **F12 — first-run config:** `documentation-publisher init-config` copies the packaged generic fail-closed starter, supports an explicit local template and never overwrites an existing file. It rejects symlink targets, missing parents and `.git` destinations. It does not invent a repository owner, branch, provider, credentials or deployment target.
- **F14 — installable package:** PEP 621/517 `pyproject.toml`, wheel/package-data, runtime dependencies, dev extras and the `documentation-publisher` console entry point are present. Schema, generic starter and provider registry are carried inside the installed package; runtime schema loading uses `importlib.resources`.
- **F15 — provider contracts:** capability registry and schema now declare GitHub Actions/GitHub Pages plus GitLab CI/GitLab Pages. GitLab generator requires an immutable OCI image digest, separates validate/build/deploy, restricts live deployment to the selected branch, suppresses deploy on dry-run, and constrains secrets/triggers. GitLab pipeline execution remains an external acceptance; Bitbucket/Azure/Jenkins workflow generators and provider-specific REST, authoring and communication adapters remain unsupported.
- **F19 — consistent profiles:** `publish` and `generate-workflow` accept repeatable ordered `--profile` flags, matching validate-config/plan/build. Names are restricted to lower-case shell-safe IDs and duplicates are rejected. Generated CI replays the chosen profiles in both validation and build commands.
- **F05 — reproducibility:** Workblock 06's first real Codespaces build disproved its install assumption: Debian Bookworm returned `E: Unable to locate package git-subtree`. The image did successfully fetch the signed snapshot metadata. Workblock 07 corrects the design: Debian's `git` package in the digest-pinned base image owns `/usr/lib/git-core/git-subtree`; the installer verifies dpkg ownership/version and helper hash, links that existing helper into `git --exec-path`, and records it in lock v3 together with the APT snapshot/source hash, base-image digest, architecture, APT/dpkg and Git versions. The corrected image still needs a fresh Codespaces rebuild and a second-build lock comparison. F05 remains externally open.
- **F07 — Python compatibility:** a GitHub Actions matrix is defined for Python 3.11, 3.12 and 3.13, but it has not yet run on GitHub. Earlier Workblock 04/06 local reports recorded separate 3.13 regression results; those historical results have not been re-executed against the current Workblock 07 tree and do not constitute current Workblock 09 acceptance.
- Package installation is included in Dev Container bootstrap and dependency declarations are rechecked on each container start and new interactive Bash terminal. Workblock 09 adds automatic `.venv` activation and fail-closed checks. The bootstrap emits the ignored `test-results/devcontainer-toolchain-lock.tsv` plus SHA-256 evidence after a successful environment setup.

## Workblock 05 — F15 GitLab CI + GitLab Pages adapter

- Added `workflow.provider: gitlab_ci` and a `.gitlab-ci.yml` generator. The generator requires an operator-supplied immutable OCI `container_image` digest and Python 3.11, 3.12 or 3.13. It checks the configured runtime version and `git subtree`; it checks `git lfs version` when a source enables LFS.
- The pipeline has separate validate/build jobs and a real `deploy-pages` job only when `publishing.dry_run: false`. Deployment is branch-gated, the Pages path is derived from the config-relative site output, and the Pages job explicitly declares `pages.publish` and `artifacts.paths`.
- Pull-request secret-bearing builds, SSH-agent auth, `workflow_call`, negated path filters, reserved GitLab runner-variable overrides and unpinned container images are rejected. Only configured `workflow.secrets` names are exported; the generator also unsets common GitLab job-token/registry credentials before pip installation, validation and publisher build child processes. Other CI/CD variables remain operator-managed and must be protected in GitLab settings.
- The machine-readable capability registry and schema now declare GitHub Actions and GitLab CI as implemented workflow generators. Bitbucket Pipelines, Azure Pipelines, Jenkins, provider REST APIs and provider-specific authoring/communication adapters remain unsupported.
- Local static/unit/semantic tests verify both dry-run and live pipeline generation, branch gating, path mapping, secrets, reserved variables, unsupported triggers and default `.gitlab-ci.yml` output. A real GitLab pipeline has not been run; that provider acceptance remains external.

F12 and F14 are locally closed for the tested Linux CLI/wheel contract. F19 is locally closed for profile propagation and generated YAML. F15 remains **partially closed**: GitLab CI/GitLab Pages is now implemented locally, but external GitLab execution and other provider/API adapters remain open.

## Workblock 06 — superseded after the first real Codespaces build

Workblock 06 pinned the base-image OCI digest, configured signed Debian Snapshot metadata and created a v2 package-transaction lock. Its installer incorrectly assumed a Debian Bookworm binary package named `git-subtree` existed. The user's first real Codespaces rebuild disproved that assumption: the snapshot metadata downloaded successfully, then APT exited 100 with `E: Unable to locate package git-subtree`. This is recorded in `audit/evidence/R8-028-WORKBLOCK-06-CODESPACES-REBUILD-FAILURE.md`. Workblock 06 must not be treated as a successful container build or a closed F05 result.

## Historical Workblock 07 — Git Subtree provisioning correction (superseded by Workblock 09)

- Restores the original provisioning contract: locate the existing `/usr/lib/git-core/git-subtree` helper supplied by Debian's `git` package, verify `dpkg-query -S` ownership and package version, and link only that helper into the directory returned by `git --exec-path`. No global `GIT_EXEC_PATH` override is introduced.
- Removes the invalid `apt-get install git-subtree` and the false APT simulation requirement. The signed snapshot is used to validate the fixed APT metadata source; the digest-pinned base image is the fixed source of the installed `git` package.
- Replaces lock v2 with lock v3. It records snapshot and source hash, `amd64`/`linux/amd64`, base-image digest, APT/dpkg/Git versions, Debian `git` package version, helper source/hash, active Git exec path and resolved symlink target.
- The runtime verifier now checks the package owner/version, source/target paths, helper hash, `git subtree -h`, base-image reference, architecture and all package-manager metadata on every start.
- Targeted regression fixtures were rewritten for the real Debian package model: existing helper discovery, symlink creation, fail-closed missing helper, no attempt to install `git-subtree`, lock generation, helper/package drift and mutable-mirror rejection. **These tests have not been run in this assistant environment; they are intended for execution in the user's Codespace.**
- The corrected image has not yet been built. The next acceptance is a fresh Codespaces rebuild from this corrected archive, then a second clean rebuild and byte-for-byte lock comparison.

## Historical Workblock 07 test status

No project test suite was executed outside the user's Codespace. The existing Workblock 06 test totals are historical assertions for the superseded code and are not acceptance evidence for Workblock 07. No GitHub Actions matrix, real GitLab pipeline, real Git-LFS transfer, Windows run, browser/editor acceptance or live publishing has been performed as part of this correction.

## Historical Group 3 test results

| Group | Result |
|---|---:|
| Core regression (excluding package/process groups) | **245 passed, 1 skipped**, 94 subtests |
| Wheel/package integration | **3 passed** |
| Process/timeout regression | **6 passed** |
| Combined | **254 passed, 1 skipped, 0 failed** |

The single skip is the actual Git-LFS client/object-transfer integration test; `git-lfs` is not installed in this local environment. The groups were run as separate invocations. An earlier all-in-one invocation timed out when it reached the wheel integration test; that same package suite subsequently passed 3/3 independently. See `audit/R8-028/GROUP-3-TEST-SUMMARY.md` and the raw logs in `audit/evidence/R8-028-GROUP-3-*.txt`.

Static checks passed: Python compileall, Bash syntax, JSON Schema meta-validation, root/package resource parity, CLI version and Keycloak smoke `validate-config`. No real Docker/Codespaces build, Windows runner, GitHub Actions execution, Git-LFS transfer, browser/editor verification or external provider API acceptance was performed.

## Configuration/compatibility matrix

- **250** option/contract nodes.
- **258** schema/dynamic path coverage rows.
- **31,125** enumerated unordered option pairs (`250 × 249 / 2`).
- **87** unique direct relationship IDs are linked to **87** pair rows: C01–C60, F09-A1–A3, F10-A1–A3, F11-A1–A8 and F12/F14/F15/F19 Group 3 relationships.
- **31,038** pair rows remain `N/A`. They are unverified, not implicitly compatible.

Group 2 matrices are preserved under `audit/history/R8-028-GROUP-2-matrices/`. The current matrices are under `audit/R8-028/input-matrices/`.

## Remaining work / external gates

- **F15:** GitLab CI/GitLab Pages generator is now locally implemented; a real GitLab pipeline must still be accepted. Bitbucket workflow/pages, provider REST, issue/discussion and provider-specific authoring adapters remain unimplemented.
- **R8-017/F17:** real Git-LFS pointer-to-object transfer still unverified (one skipped test).
- **R8-027/F16:** actual fresh GitHub Codespaces build/verification still needed. Workblock 06's actual build failed on the invalid `git-subtree` package name; Workblock 07 restores the original helper-discovery/link flow and writes lock v3. Fresh build and second-build comparison remain required.
- **R8-022/F18:** Windows process-tree timeout/child-reaping acceptance remains open; process suite passed on Linux only.
- **R8-009/R8-011:** Project Pages browser and Keycloak editor/browser acceptance remain external.
- **F05:** signed Debian Snapshot metadata, fixed `linux/amd64` target and v3 base-image/Git Subtree helper lock are prepared. Workblock 09 local tests cover the verifier and provisioning fixtures, but no live Docker/Codespaces image build was performed here. Remaining acceptance: successfully build two clean Codespaces images, compare `toolchain-lock.tsv` byte-for-byte and confirm the helper works without `GIT_EXEC_PATH`.
- **F07:** Python 3.11/3.12/3.13 CI matrix is defined; GitHub-hosted execution and all three version results remain open. The Dev Container itself remains intentionally Python 3.13.
- **F12/F14:** first-run behavior and wheel install were tested locally; a real clean Codespace install and Windows/macOS wheel acceptance remain external.
- **F19:** the generated workflow's profile forwarding is locally asserted; GitHub-hosted execution and production publishing remain unperformed.
- Every `N/A` option pair and higher-order configuration interaction remains open unless separately tested.

## Operational boundary

This Group 3 project is a local development candidate. It has not been inserted into the user's GitHub repository or existing Codespace. No commit, push, pull request, release upload, Keycloak upstream change or deployment was performed.

## Navigation

- Canonical source notice: `CURRENT-SOURCE.md`
- Archive lineage: `audit/ARCHIVE-RECONCILIATION.md`
- Archive inventory: `audit/ARCHIVE-INVENTORY.csv`
- F01–F20 current status: `audit/R8-028/R8-028-GROUP-3-FINDING-STATUS.csv`
- F12/F14/F15/F19 parent report: `audit/R8-028/F12-F14-F15-F19-IMPLEMENTATION-REPORT.md`
- Workblock 05 F15 implementation: `audit/R8-028/WORKBLOCK-05-F15-GITLAB-CI-IMPLEMENTATION.md`
- Workblock 05 F15 tests: `audit/R8-028/WORKBLOCK-05-F15-GITLAB-CI-TEST-REPORT.md`
- Workblock 06 F05 APT snapshot report (superseded after real build failure): `audit/R8-028/WORKBLOCK-06-F05-APT-SNAPSHOT-LOCK.md`
- Workblock 07 Git Subtree provisioning correction: `audit/R8-028/WORKBLOCK-07-GITSUBTREE-PROVISIONING-CORRECTION.md`
- Workblock 06 F05 tests (superseded): `audit/R8-028/WORKBLOCK-06-F05-APT-SNAPSHOT-LOCK-TEST-REPORT.md`
- Workblock 07 test plan: `audit/R8-028/WORKBLOCK-07-TEST-PLAN.md`
- Workblock 07 test ledger: `audit/R8-028/WORKBLOCK-07-TEST-REPORT.md`
- Group 3 changelog: `audit/R8-028/GROUP-3-CHANGELOG.md`
- Group 3 test accounting: `audit/R8-028/GROUP-3-TEST-SUMMARY.md`
- Current option/pair/schema matrices: `audit/R8-028/input-matrices/`
