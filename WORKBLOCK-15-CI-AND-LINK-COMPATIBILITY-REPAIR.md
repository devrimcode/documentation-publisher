# Workblock 15 — CI and Keycloak Link Compatibility Repair

**Project:** Documentation Publisher `2.0.15-dev`  
**Date:** 2026-11-08  
**Parent:** recovered Workblock 14 archive  
**Parent SHA-256:** `d5bf9f38cd3c8d41888421e9093f8ecb690c17458d23ca11ac96f1b76414165e`  
**Keycloak source revision inspected:** `c5b9177451d77adc3807a4a3bd0583c3dc79402c`  
**Package status:** complete replacement source tree; local regression groups pass; external GitHub acceptance remains open.

## 1. Why this Workblock exists

The failed Publisher Actions build exposed a source-link contract change in Keycloak's current AsciiDoc header. The same CI batch also exposed a Python 3.11 syntax error in the GitLab workflow generator and Python 3.12 false failures in Dev Container runtime tests. This Workblock starts from the verified full Workblock 14 archive and integrates all corrections into one complete project tree. It is not a collection of one-file patches.

## 2. Keycloak Edit-link contract

The current Keycloak `main` source revision inspected for this Workblock defines:

- `docs/documentation/topics/templates/document-attributes.adoc`: `:docs_repo_edit_base: https://github.com/keycloak/keycloak/edit/main`
- `docs/documentation/topics/templates/header.adoc`: `link:{docs_repo_edit_base}/docs/documentation/{include_filename}[Edit this section, ...]`

That produces incoming provenance URLs of the form:

`https://github.com/keycloak/keycloak/edit/main/docs/documentation/<path>.adoc`

The previous Workblock 14 adapter expected only `/tree/main/`, and rejected the current `/edit/main/` form. `publisher_engine/links.py` now accepts both `/edit/<ref>/docs/documentation/` and the legacy `/tree/<ref>/docs/documentation/` prefix. It still validates HTTPS, the exact configured upstream repository authority, the configured source ref, no query/fragment, safe relative path and `.adoc` suffix before attaching the source provenance marker.

The regression test now drives the real current header URL through HTML rewriting and checks the final Edit URL on `devrimcode/keycloak`. The multi-destination regression continues to test legacy `/tree/main/` input and independently configured destinations.

The identity model is unchanged:

| Role | Repository / destination |
|---|---|
| Publisher | `devrimcode/documentation-publisher` |
| Physical build source | `devrimcode/keycloak:main` |
| Incoming AsciiDoc provenance | `keycloak/keycloak` |
| Edit this Section | `devrimcode/keycloak` |
| Issue links | `keycloak/keycloak/issues` |
| Neighbor/navigation | `devrimcode/keycloak` |

The upstream `sources[].vcs.web_url` remains the source-link provenance identity. The physical source clone and the three final link destinations remain independent.

## 3. Python 3.11 and 3.12 CI corrections

### Python 3.11 syntax

The GitLab workflow generator previously placed a string containing an escaped quote inside an f-string expression. Python 3.11 rejects this grammar. The Git Subtree shell probe is now defined as a separate string before YAML serialization. The generated GitLab command remains functionally equivalent, but is parseable on the declared minimum Python version.

### Python 3.12 fixture isolation

The Dev Container runtime verifier tests had only created a fake `python3` command when a test explicitly supplied a custom wrapper. On a Python 3.12 GitHub runner, ordinary fixtures therefore inherited the runner's real Python 3.12 executable and failed a test that was supposed to model a Python 3.13 Dev Container image. The default fixture now installs a deterministic fake `python3` wrapper that reports Python 3.13 and delegates non-version calls to the active test interpreter. The explicit negative test still injects Python 3.12 and verifies fail-closed behavior.

## 4. Keycloak build runtime and Maven configuration

The current Keycloak documentation workflow was inspected at the same source revision. Its local `.github/actions/java-setup/action.yml` uses the pinned `actions/setup-java` commit `de7274f081f381c8f8158605e0321c36c376e2e6`, defaults to Temurin JDK 25 and exports these Maven Resolver arguments:

`-B -nsu -Daether.connector.http.connectionMaxTtl=25 -Daether.connector.http.retryHandler.count=5 -Daether.connector.http.retryHandler.serviceUnavailable=429,502,503,504`

The Publisher production workflow now supports an optional pinned `workflow.actions.setup_java` and `workflow.java_version` pair. The production config explicitly selects Temurin Java 25. `MAVEN_ARGS` is passed into the Publisher build step, and `publisher.yml` already declares that variable in the task's `pass_environment` allowlist. The existing Keycloak Maven command and the independent repository/link configuration are unchanged.

The schema rejects neither existing workflows nor dry-run workflows that do not configure Java. If `java_version` is provided, a pinned `setup_java` action is required; configuring the action without a version is rejected.

## 5. Concurrency and stale repository-dispatch protection

Production Actions concurrency now appends the GitHub ref to the configured concurrency-group name. Main and PR refs therefore use separate groups. Production sets `cancel_in_progress: false`, so a pull-request run cannot cancel a running main deployment.

For repository-dispatch builds, the generated workflow:

1. validates the dispatch repository, branch and full SHA;
2. builds the exact source SHA (existing Workblock 14 behavior);
3. checks that the event SHA is still the configured source branch head before Pages artifact upload;
4. suppresses upload if the event is stale;
5. repeats the source-head check in the deploy job immediately before `deploy-pages`;
6. skips the deployment action if the branch advanced after the build.

The previous public Pages site remains in place when build/site validation fails or a stale event is rejected. There is an unavoidable short interval between the final remote-head query and the deployment action; a source push in that interval may race with deployment, but the second check minimizes that window and prevents ordinary delayed-event regressions. A subsequent event will build the newer branch head.

## 6. Files and implementation areas

The complete archive carries the Workblock 14 engine and all project files, with changes integrated in these areas:

- `publisher_engine/links.py` — current and legacy Keycloak edit source URL recognition.
- `tests/test_engine.py` — current `/edit/main/` final URL regression; legacy and independent route regression retained.
- `publisher_engine/workflow.py` — Python 3.11-safe GitLab probe, optional Java setup action, ref-scoped concurrency output, source-head checks before artifact and deploy.
- `publisher_engine/config.py`, `schemas/publisher.schema.json`, `publisher_engine/data/publisher.schema.json` — prior workflow validation retained; workflow schema adds `java_version`, `setup_java` and `concurrency_group_per_ref`.
- `publisher.yml` — JDK 25, Maven Resolver args, ref-scoped concurrency and non-cancelling production policy.
- `.github/workflows/documentation-publisher.yml` — regenerated from production config.
- `tests/test_devcontainer_runtime.py` — deterministic Python 3.13 default fixture with explicit bad-version negative test.
- `tests/test_workblock14_repository_dispatch.py` — tests for Java wiring, Maven args, source freshness checks, concurrency and deployment guard.
- `publisher_engine/__init__.py`, `pyproject.toml`, `tests/test_packaging.py`, `scripts/codespaces_acceptance.py`, `CURRENT-SOURCE.md`, `STATUS.md` — package version and source/status metadata update to `2.0.15-dev`.
- `docs/SOURCE-TO-PUBLISHER-AUTOMATION.md` — installation, CI runtime and freshness-gate operational documentation.

The source-side notifier remains a template under `integration/source-repository/.github/workflows/`; it is not installed in the Keycloak fork by archive extraction.

## 7. Verification results

All test groups were executed separately, following the project's documented runner behavior. This avoids the descendant-process pipe inheritance that can keep a monolithic pytest command open even after tests exit.

| Test group | Result |
|---|---:|
| Main regression (manifest/packaging/process excluded) | **292 passed, 1 skipped, 104 subtests passed** |
| Manifest / cleanup | **6 passed** |
| Wheel packaging / installation | **3 passed** |
| Process / subprocess group (`ResourceWarning` as error) | **6 passed** |
| Total across isolated groups | **307 passed, 1 skipped, 104 subtests passed** |
| Targeted Workblock 15 + Keycloak routing + runtime tests | 23 passed, 5 subtests passed |
| GitLab workflow deploy-output compatibility + dispatch tests | 17 passed |
| Python 3.11 grammar parse | 25 Python files checked, 0 syntax errors |
| Python compileall | passed |
| Production config validation | 1 source, 1 component, 1 task — valid |
| Generated GitHub Actions YAML | parsed with duplicate-key rejection; key dispatch, JDK, freshness, concurrency and deploy conditions checked |
| Root and package schemas | valid JSON and byte-identical |

The single skipped `tests/test_p8_git_lfs.py` case requires a real Git LFS HTTP batch/object fixture; the recovered build container did not provide that fixture. Python 3.11 grammar was verified with `ast.parse(feature_version=(3, 11))`; native Python 3.11/3.12 interpreters were not installed in this container, so the actual Actions compatibility matrix remains external acceptance.

The actual full Keycloak Maven build was not executed in this build container. The current source header and matching Keycloak CI setup/command were checked from the read-only GitHub source; successful remote Maven execution must be confirmed by a subsequent GitHub Actions run.

## 8. Not performed / external acceptance gates

This Workblock archive does not delete or mutate GitHub repositories, stage or commit Git files, push, open PRs, install remote workflows, create or change secrets, switch Pages settings, run remote Actions, or deploy a site. The following must still be verified after the user recreates the Publisher repository from this archive:

- upload/review the complete project tree on `devrimcode/documentation-publisher`;
- install the source notifier in `devrimcode/keycloak` and configure `PUBLISHER_DISPATCH_TOKEN` there;
- select GitHub Actions as the Pages build source;
- observe a real `repository_dispatch` run;
- observe Maven documentation build, link rewriting, site validation, artifact upload and successful Pages deployment;
- inspect the public website and final edit/issue/navigation links.

Local tests do not count as proof of a live dispatch or live Pages publication.
