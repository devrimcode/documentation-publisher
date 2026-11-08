# Current canonical project source

**Current source:** Workblock 15 — `2.0.15-dev`  
**Immediate parent:** verified Workblock 14 archive  
**Parent SHA-256:** `d5bf9f38cd3c8d41888421e9093f8ecb690c17458d23ca11ac96f1b76414165e`  
**Current Keycloak source revision inspected:** `c5b9177451d77adc3807a4a3bd0583c3dc79402c`

Workblock 15 is a complete replacement project tree based on Workblock 14. It repairs the concrete GitHub Actions failures and adds pre-deployment protection against delayed source-dispatch events publishing an older Keycloak revision.

## Repository identities remain independent

| Role | Value |
|---|---|
| Publisher / Pages workflow | `devrimcode/documentation-publisher` |
| Physical build source | `devrimcode/keycloak`, branch `main` |
| Incoming AsciiDoc source-link provenance | `keycloak/keycloak` |
| Edit this Section destination | `devrimcode/keycloak` |
| Issue links | `keycloak/keycloak/issues` |
| Neighbor/navigation destination | `devrimcode/keycloak` |

The physical source clone remains `sources[].vcs.clone_url`; upstream source-link provenance remains `sources[].vcs.web_url`. The three final link destinations stay independently configured.

## Workblock 15 corrections

- The Keycloak AsciiDoc adapter accepts the current upstream `/<owner>/<repo>/edit/<ref>/docs/documentation/...` Edit URL and the legacy `/tree/<ref>/...` form. Both are validated against upstream provenance and then mapped to the independent fork edit destination.
- The production link regression now exercises the current `/edit/main/` contract. The independent-target regression continues to cover legacy `/tree/main/` input and ensures issue/navigation routing does not change.
- The GitLab workflow generator no longer uses a backslash-containing expression inside an f-string, restoring Python 3.11 grammar compatibility.
- Dev Container verifier fixtures always provide deterministic Python 3.13 output by default, independent of whether CI's host runner is Python 3.11, 3.12 or 3.13. The explicit negative fixture still proves that an invalid Python version is rejected.
- The GitHub Actions Publisher build configures Temurin JDK 25 with a pinned `actions/setup-java` action and the same Maven Resolver retry/connection flags used by the current Keycloak documentation workflow.
- GitHub Actions concurrency groups can append `github.ref`, separating PR and main runs. The production workflow keeps `cancel-in-progress: false`.
- Repository-dispatch builds still fetch the exact event SHA. The workflow checks that the event SHA is still the current source branch head before uploading the Pages artifact and again immediately before `deploy-pages`. A stale event is not allowed to replace the existing site.

## Local verification in the recovered build environment

| Test group | Result |
|---|---:|
| Main regression, excluding the separately run groups | **292 passed, 1 skipped, 104 subtests passed** |
| Manifest / cleanup integration | **6 passed** |
| Wheel packaging / installation | **3 passed** |
| Process / subprocess groups (`ResourceWarning` as error) | **6 passed** |
| Combined isolated groups | **307 passed, 1 skipped, 104 subtests passed** |
| Python 3.11 grammar parse of all project Python files | 34 checked, 0 syntax errors |
| Production `publisher.yml` schema and semantic validation | 1 source, 1 component, 1 task — valid |
| Generated GitHub Actions workflow | YAML parsed; dispatch, JDK, freshness, concurrency and deploy guards checked |
| Package and root schemas | JSON valid and byte-identical |
| Python compilation | passed |

The one skipped Git-LFS test requires an installed `git-lfs` client and an HTTP LFS batch/object fixture; this recovered container did not provide that fixture. Python 3.11 grammar was checked with `ast.parse(feature_version=(3, 11))`; a native Python 3.11 interpreter was not available in this container. The exact Python 3.11/3.12 GitHub matrix remains an external check.

## External acceptance still required

This archive does not install workflows, create secrets, change Pages settings, run GitHub Actions, or deploy the live Pages site. After the user recreates/reviews the Publisher repository, a fresh repository upload and Actions run must verify the actual Keycloak Maven build and final generated HTML against the live fork commit. The source notifier must still be installed in `devrimcode/keycloak`, `PUBLISHER_DISPATCH_TOKEN` must be configured there, and Pages must use GitHub Actions. The live workflow must be observed completing before calling the automation operational.

No repository was deleted or modified by this archive build. No `git add`, commit, push, PR, remote secret mutation or Pages deployment was performed.
