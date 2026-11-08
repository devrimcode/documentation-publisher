> **Historischer Stand:** Die damalige R8-027-Aussage bezog sich auf eine repository-lokale Dev Container Feature. Sie wurde am 7. November 2026 durch die aktive `.devcontainer/devcontainer.json` plus Dockerfile-basierte Git-Subtree-Installation im aktuellen Testkandidaten ersetzt.

# R8 correction status – 2.0.10-dev

**Status: NOT RELEASE READY.** This is a separate correction copy derived from the independently checked 2.0.9-dev tree, with the R8-009 changes and a repository-local Dev Container Feature for R8-027. The original R8 archive and the 2.0.9-dev package remain unchanged. No commit, push, live Codespace rebuild, GitHub Actions run, or deployment was performed.

## Provenance

- Original base: hash-verified `documentation-publisher-v2-hardened-r8.zip` (R8 2.0.8-dev)
- Intermediate correction: 2.0.9-dev
- This iteration: 2.0.10-dev
- Scope of this package: R8-009 GitHub Pages Project-Site base-path behavior and R8-027 Dev Container provisioning.

## Audit finding matrix

| Finding | Status | Correction / remaining evidence |
|---|---|---|
| R8-001 | Fixed | Build output and filesystem publishing reject destinations overlapping tracked repository content; regression verifies tracked publisher code stays byte-identical. |
| R8-002 | Fixed | Workspace paths are resolved and checked against `.git` metadata, including symlink resolution, before directory creation. |
| R8-003 | Fixed | Active `data:` URLs and `srcdoc` are rejected; only narrowly scoped passive base64 raster image data URLs are allowed. |
| R8-004 | Fixed | `dry_run` defaults fail-closed: generated workflows contain neither Pages artifact upload nor deploy job. Deployment requires explicit `dry_run: false`. |
| R8-005 | Fixed | Reserved/internal environment variables are blocked; duplicate YAML mapping keys are rejected by the strict parser. |
| R8-006 | Fixed | Build and deploy permissions are restricted to explicit least-privilege allowlists. |
| R8-007 | Fixed | Generated checkout step sets `persist-credentials: false`. |
| R8-008 | Fixed | Parent/child and rendered component-route collisions are rejected during config validation. |
| R8-009 | Partial – smoke checks passed; deployed browser acceptance pending | The implementation covers canonical URLs, `{page_url}`, root-relative references in HTML/XHTML/SVG and CSS, `srcset`, inline/block CSS, `@import`, forms/media/scripts/images and meta refresh. In the user's Keycloak smoke site, the canonical URL contained `/keycloak-pages`; the generated HTML scanner found no root-relative references to assess. **Still required:** full browser acceptance against an actual GitHub Pages Project-Site path and domain-root/custom-canonical deployment verification. |
| R8-010 | Fixed | `robots: noindex` is applied to all generated HTML pages, including index and 404 pages. |
| R8-011 | Partial – live Keycloak build and source-path checks passed; browser acceptance pending | The Keycloak Maven task completed successfully in the user's Codespace (110 seconds). The generated site reported 362 edit-link occurrences / 359 unique URLs; all 359 unique targets were present in the exact source commit's Git tree. Browser/editor acceptance remains pending; no Keycloak source was edited. |
| R8-012 | Fixed | Component `inherit` inherits the global edit policy; explicit component override/disable remains authoritative. |
| R8-013 | Fixed | Empty/unsafe component output paths fail semantic validation. |
| R8-014 | Fixed | Fallback redirect schemes use the same allowlist as runtime validation. |
| R8-015 | Fixed | Publisher, source and authoring Git refs are checked with Git ref grammar before network/clone operations. |
| R8-016 | Fixed | `file://` repository URLs are rejected; local filesystem path support remains a separate explicit local-path form. |
| R8-017 | Open | Git LFS include-filter source-relative behavior still needs correction/verification with a real LFS object and server fixture. Current mock-based tests are not sufficient acceptance evidence. |
| R8-018 | Fixed | `keep_failed_workspace` now retains workspaces only for failures; success retention remains separately controlled. |
| R8-019 | Open | `plan` still needs to report the exact dependency closure and selected task/source graph used by build. |
| R8-020 | Fixed | HTML void elements no longer affect nesting depth; tag depth handling has regression coverage. |
| R8-021 | Open | ZIP entry-count validation still needs to bound central-directory processing before full metadata materialization. |
| R8-022 | Open | Subprocess stdout/stderr still require bounded streaming/ring-buffer handling and process-group termination on timeout. |
| R8-023 | Fixed | Artifact adapter contract is documented as workflow handoff; config validation now requires `publishing_targets[].output_path` to match `site.output_directory`. |
| R8-024 | Fixed | `site.base_url` and `canonical_base_url` reject path, query and fragment; `base_path` remains the separate path setting. |
| R8-025 | Fixed (documentation contract) | Unrendered project fields are explicitly documented as metadata-only; rendered fields are named. No additional UI rendering is claimed. |
| R8-026 | Fixed (documentation contract) | `validate_external_links` is explicitly documented as host allowlist validation, not DNS/HTTP reachability validation. |
| R8-027 | Partial – Dev Container feature packaged; Codespaces rebuild pending | Added a repository-local Dev Container Feature that installs the distro `git-subtree` package when needed, links only that helper into the active `git --exec-path`, and validates discovery during image creation. Two new regression tests cover the mismatched exec-path and idempotent paths. The user's current Codespace has not yet been rebuilt with this feature, so live Codespaces acceptance remains pending. |

## Verification completed in this iteration

- `python -m unittest discover -s tests -v`: **142 tests passed** in the isolated correction-package test environment (140 existing tests plus 2 Dev Container feature tests).
- `python -m py_compile publisher_engine/*.py tests/*.py`: passed.
- CLI version: `2.0.10-dev`; CLI help: passed.
- `python -m publisher_engine.cli validate-config --config publisher.keycloak.smoke.yml`: passed (1 source, 1 component, 1 build task).
- JSON Schema metaschema check: passed.
- A local Git-subtree Project-Site fixture build passed; its root-relative HTML references and CSS references were rewritten, the CSS/image assets were included, canonical URLs contained the base path, and local-link validation passed.
- User Codespace Keycloak smoke build passed: source commit `30cf683465a1ddf7151462d7f480d6d17f986844`, Maven task succeeded in 110.005 seconds, 362 edit-link occurrences / 359 unique targets, and 359/359 targets matched files in the source commit Git tree.
- User Codespace smoke-site canonical URL included `/keycloak-pages`; 1 canonical URL found and prefixed. The scanner found no root-relative references in the 10 generated HTML files, so this observation is not a full proof of every URL type.
- R8-027 reproduced in Codespaces without override (`git --exec-path=/usr/local/libexec/git-core`, `git subtree` unavailable) while the installed package exists at `/usr/lib/git-core/git-subtree`.

## Remaining release gates

Do not label this package production-ready or publish it while R8-017, R8-019, R8-021 and R8-022 remain open, while R8-009 has not passed the deployed browser acceptance, while R8-011 has not passed the real Keycloak build/browser acceptance, and while R8-027 has not passed a Codespaces rebuild using the repository-local Dev Container Feature. The 142 local tests do not replace these integration and resource-boundary checks.

## Incremental correction P1 — independent validation switches

**Status: IMPLEMENTED AND REGRESSION-TESTED in the P1 package.** This addendum is based on the exact R8-027 archive listed in the P1 report and changes only `publisher_engine/engine.py` and `tests/test_engine.py`.

- `validate_local_links` now controls local target existence checks only; it no longer suppresses fragment validation, external-host allowlisting, or `max_html_depth`.
- `validate_css_assets` controls local CSS asset resolution only; external CSS host validation is independent.
- Always-on active-content and forbidden-scheme protections remain active when optional local-link validation is disabled.
- Seven new regression tests cover the independent switch behavior and ensure disabling one check does not unintentionally disable another.

Verification for this P1 package:

- Targeted `SiteValidationTests`: **13 passed**.
- Full suite: **149 passed, 0 failed** (`python -m unittest discover -s tests -v`).
- `python -m py_compile publisher_engine/*.py tests/*.py`: passed.

This P1 result does not close P2–P7 or the separate release gates R8-017, R8-019, R8-021, R8-022, R8-009, R8-011, and R8-027. The 149-test result applies to this P1 archive only; it must not be retroactively attributed to earlier packages. No commit, push, publish, or deployment was performed.

## Incremental correction P2 — meta-refresh validation

**Status: IMPLEMENTED AND DIFFERENTIALLY REGRESSION-TESTED in the cumulative P2 package.** This builds on the exact P1 complete project archive with SHA-256 `0b003f46ba7877b9f8ef77a69a0f7be2baf1c247c8f411196ef522cc208ec78f`.

- HTML `meta http-equiv="refresh"` destinations now enter redirect-scheme, external-host, local-target and fragment validation.
- `mailto:` and `tel:` are not accepted as meta-refresh redirect targets.
- malformed quoted refresh destinations fail closed even with local-link existence checks disabled.
- Delay-only refresh content without a URL remains valid.
- 15 targeted P2 tests: 11 fail against a fresh P1 baseline, 15 pass on P2 (four baseline controls remain green).
- Full cumulative suite: **164 passed, 0 failed**.
- Python compilation, CLI version and Keycloak sample config validation pass.
- A real local Git-subtree build containing a `javascript:` meta-refresh fails validation before `_site` is installed and cleans its workspace.

P2 does not close the remaining R8 release gates or establish live Keycloak browser acceptance. No commit, push, publish, deployment, or user Codespace change was performed.

## Incremental correction P3 — deploy decision job output

**Status: IMPLEMENTED AND DIFFERENTIALLY REGRESSION-TESTED in the cumulative P3 package.** P3 builds on the P2 project archive and changes only `publisher_engine/workflow.py` plus a new dedicated test module.

- Non-dry-run workflows now export `steps.decision.outputs.deploy` as `jobs.build.outputs.deploy`.
- The downstream `deploy` job consumes that declared value through `needs.build.outputs.deploy`.
- Dry-run remains build-only and has no decision output or deploy job.
- Four dedicated YAML-parsing regression tests: **3 fail against a fresh P2 baseline; 4/4 pass on P3** (the dry-run control passes on both).
- Full cumulative suite on P3: **168 passed, 0 failed**.
- Python compilation, CLI version, Keycloak example configuration validation and generated-output contract assertions pass.
- No live GitHub Actions run, artifact upload or Pages deployment was performed.

P3 does not close P4/P5 workflow issues or the remaining R8 acceptance gates. This remains a development candidate and is not release-ready.


## R8-028 – Sicherheits- und Toolchain-Korrekturgruppe 1

**Status: IMPLEMENTIERT UND LOKAL REGRESSIONSGEPRÜFT (P12 / R8-028-P1A).** Diese Korrekturen basieren auf dem tatsächlich wiederhergestellten P11-Archiv, nicht auf ungesicherten Zwischenmeldungen.

- Repository-/Source-/Communication-`allowed_hosts` lehnen Wildcards ab; Einträge müssen vollständige, syntaktisch gültige Hostnamen sein. Die generische Vorlage verwendet explizite Host-Platzhalter statt `*`.
- Live-Publishing (`publishing.dry_run: false`) lehnt reservierte Example-/Test-Domains einschließlich Subdomains und nicht-globale IP-Ursprünge ab. Dieselben reservierten URLs bleiben für ausdrücklich aktivierte Dry-Run-Smoke-Fixtures zulässig.
- `publisher.keycloak.example.yml` wurde in `publisher.keycloak.smoke.yml` umbenannt und im Datei-Header als projektbezogene Smoke-Fixture mit festen Repository-/Branch-Annahmen und reservierter `example.invalid`-Origin gekennzeichnet.
- Root-`.gitignore` deckt Python-/Pytest-Caches, virtuelle Umgebungen, Testresultate und Publisher-Arbeitsverzeichnisse ab.
- Dev-Container-Feature-Versionen sind festgesetzt (Java Feature 1.8.3, Git-LFS Feature 1.2.5; Temurin 25 aktiv plus 21, Maven 3.10.0, Git LFS 3.8.1). Der Verifier fordert exakte Versionen und weist insbesondere Java 21 als falsches Standard-Java zurück.
- Der Codespaces-Akzeptanzstarter prüft dieselben Versionen und hält die generische Vorlage als bewusst fail-closed fest.

Der tatsächliche Docker-/Codespaces-Neuaufbau ist nicht erfolgt; R8-027 bleibt extern offen. Die Hauptsuite besteht mit 218 passed/1 skipped, die Prozesssuite separat mit 6/6; 48 gezielte Tests bestehen (als Teilmenge nicht zusätzlich gezählt). Aggregiert: 224 passed/1 skipped/0 failed. Ein differentieller Testlauf auf dem unveränderten P11-Quellstand schlägt bei den vier neuen Host-Allowlist-/Reserved-Origin-Tests erwartungsgemäß fehl (11 Assertion failures/subfailures, 1 Dry-Run-Kontrolle grün); damit reproduzieren die Regressionen den alten Fehler. Der aktuelle Nachweis liegt in `audit/R8-028-P1A-SECURITY-TOOLCHAIN-REPORT.md` und `audit/evidence/R8-028-P1A-*`.


## Current P12 / R8-028-P1A acceptance status

The historical status entries above describe earlier correction packages. The first current P12 security/toolchain group is implemented and locally regression-tested:

- 31/31 configuration/security tests; 12/12 Dev Container configuration tests; 5/5 runtime-verifier positive/negative tests (48/48 focused).
- Main suite: 218 passed, 1 skipped, 73 subtests. Process suite: 6/6 passed in a separate invocation. Combined: 224 passed, 1 skipped, 0 failed (focused tests are a subset, not an additional count).
- Four new host-Allowlist/reserved-origin regression tests were run against unchanged P11 and reproduced the old behavior (11 assertion failures/subfailures, one Dry-Run control passed); current P12 passes.
- Codespaces starter passes end-to-end with test doubles for host-missing/wrong tools. Raw host acceptance has four blockers: Git LFS absent, Java 21 active instead of Java 25, additional SDKMAN Java 21 absent, Maven absent.
- Actual Docker/Codespaces build and browser integrations were not run. Base image tag and apt `git-subtree` package remain mutable. The true Git-LFS object-transfer test remains skipped.

Canonical current evidence: `audit/R8-028-P1A-SECURITY-TOOLCHAIN-REPORT.md` and `audit/evidence/R8-028-P1A-*`. This is not a production release or closure of the remaining R8-028 items.
