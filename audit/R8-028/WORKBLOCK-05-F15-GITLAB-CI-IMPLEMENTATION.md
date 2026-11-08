# Workblock 05 — F15 GitLab CI + GitLab Pages adapter

**Parent:** P12 / R8-028 / `RECONCILED-GROUP-3`, through Workblock 04. Parent ZIP SHA-256: `dc06b8b23c77f7999ac8a336565d99e95f3514149ea0ab629972c138eca43db3`; parent TAR.GZ SHA-256: `cee4217a13faf5e2acddddcbac60e806f35fd49b71d6ab0a458f761a122d6c95`.

## Implemented

- Added `gitlab_ci` to the schema-supported workflow provider IDs and the capability registry.
- Added `generate_gitlab_ci_workflow` and CLI dispatch. The default output is `.gitlab-ci.yml`; `workflow.file` and `--output` retain their existing explicit override semantics.
- Requires `workflow.container_image` with an immutable `@sha256:<64 lowercase hex>` digest and Python 3.11, 3.12 or 3.13. Generated jobs check the actual Python minor version. The configured image must contain Git and `git-subtree`; when any source has `vcs.lfs: true`, the pipeline checks `git lfs version`.
- Generates `workflow.rules` for GitLab web/manual pipeline, schedules, merge requests and configured push branches. Positive `triggers.paths` patterns are supported; negative patterns and unsupported `workflow_call` are rejected.
- Emits validation and build jobs. `publishing.dry_run: true` creates no Pages deployment job. `publishing.dry_run: false` creates `deploy-pages`, gated to `triggers.deploy_branch` and non-merge-request pipelines.
- Resolves the Pages path relative to the configuration file, verifies the expected `index.html`, and declares both `pages.publish` and `artifacts.paths`.
- Reuses the explicit `workflow.secrets` map as GitLab CI/CD variable names. Secrets are exported only in the build job; reserved runner names and secret-bearing merge-request pipelines are rejected. Common built-in GitLab job-token/registry credentials are removed from the pip-install, validation and build child-process environments before project code runs.
- The registry and docs now distinguish implemented GitLab CI/Pages from still-unsupported Bitbucket/Azure/Jenkins pipelines and provider REST, authoring and communication APIs.

## Deliberate boundaries

- GitLab CI/CD variables must be created by the operator and marked masked/protected as appropriate. Their protection scope, project permissions and `CI_JOB_TOKEN` allowlist cannot be verified from a static config file. The runner shell still receives the built-in job token; common token-bearing variables are removed before pip installation, configuration validation and the publisher build child process. Project/group variables not named in `workflow.secrets` are not made safe by that mapping and must be protected separately in GitLab settings.
- The pipeline does not create GitLab schedules; a non-empty `triggers.schedule` permits scheduled-pipeline sources, but cadence is configured in GitLab project settings.
- `GitLab Pages` syntax uses `pages.publish`, requiring GitLab 17.9 or newer. No real GitLab pipeline was triggered from this local workspace.
- This work does not add GitLab repository API, issue/discussion, authoring-link or VCS adapters. Git provider source materialization remains Git + git_subtree.

## Verification approach

Unit tests cover dry-run/live output, branch gating, config-relative artifact path, digest enforcement, profile forwarding, secret allowlists, untrusted MR restrictions, reserved variables, unsupported triggers/path patterns and default output filename. YAML is parsed with a duplicate-key-rejecting loader. Full regression results and archive checksums are in `WORKBLOCK-05-F15-GITLAB-CI-TEST-REPORT.md`.
