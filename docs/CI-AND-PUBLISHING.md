# CI and publishing

## GitHub Actions + GitHub Pages

The workflow generator currently supports GitHub Actions and a separate GitHub Pages deployment job. Every action reference must be configured as a full 40-character commit SHA. The build job is restricted to `contents: read`, and checkout uses `persist-credentials: false`. The deploy job receives only `pages: write`, `id-token: write` and `actions: read`. `publishing.dry_run: true` (also the default when omitted) generates a build-and-validate-only workflow with no Pages upload or deploy job. A deployment workflow requires the explicit opt-in `publishing.dry_run: false`; it is gated to the configured deploy branch and is skipped for pull requests.

Artifact name and retention are read from `publishing.artifact_name` and `publishing.retention_days`. The `artifact` publishing adapter is a handoff/status contract: the CLI reports the validated site path as ready/planned, while the generated CI workflow performs the actual GitHub Pages artifact upload. It does not create a separate local ZIP or upload an artifact itself. The Pages upload path is derived from `site.output_directory` relative to the configuration file; `publishing_targets[].output_path` must match that path for an artifact target; configuration validation rejects mismatches before a workflow can be generated. Action versions are never guessed. Review generated YAML and the exact action commit SHAs before committing it.


## Cross-repository source updates (GitHub Actions)

GitHub Actions workflows may opt into `triggers.repository_dispatch`. The generated Publisher workflow listens only to the configured event type, validates the exact source repository and branch in `client_payload`, requires a full commit SHA, and provides that SHA to the selected source's `vcs.dispatch_sha_env`. The Git-subtree adapter fetches this immutable commit instead of a moving branch head. See [SOURCE-TO-PUBLISHER-AUTOMATION.md](SOURCE-TO-PUBLISHER-AUTOMATION.md) for the source-side notifier workflow, token permissions, setup sequence and deployment boundaries.

This cross-repository event is GitHub-specific; the GitLab CI generator rejects it rather than silently ignoring it. A successful build and site validation are prerequisites for the Pages artifact and deploy job. GitHub documents that the workflow must exist on the receiver's default branch for `repository_dispatch` to trigger, and that fine-grained tokens need `Contents: write` permission on the receiving repository for the create-dispatch endpoint.

## GitLab CI + GitLab Pages

Set `workflow.provider: gitlab_ci`, configure `workflow.container_image` with an immutable OCI image reference ending in `@sha256:<64 lowercase hex characters>`, and set `workflow.python_version` to `3.11`, `3.12` or `3.13`. The configured image must contain that exact Python minor version, Git and `git-subtree`; it must also contain `git-lfs` if any source enables LFS. The generator writes `.gitlab-ci.yml` by default. It emits validation and build jobs; a Pages job is emitted only when `publishing.dry_run: false` is set explicitly.

The generated pipeline uses a digest-pinned image, validates the runtime Python minor version, checks that `git subtree` is installed, forwards ordered profiles, creates a retained build artifact, and uses the artifact handoff for GitLab Pages. Live deployment is restricted to `triggers.deploy_branch`; merge-request pipelines never deploy. `triggers.pull_request` maps to GitLab merge-request pipelines. `triggers.manual` maps to the GitLab **Run pipeline** UI, and a non-empty `triggers.schedule` enables scheduled pipeline sources; the actual schedule cadence must still be created in GitLab project settings. `triggers.paths` accepts positive path globs only. `workflow_call`, SSH-agent authentication, and secret-bearing merge-request builds are deliberately rejected.

GitLab CI job variables referenced through `workflow.secrets` must be configured in GitLab project/group CI/CD settings and should be masked and protected as appropriate. The generator exports only names in that explicit mapping and removes `CI_JOB_TOKEN`, `CI_REPOSITORY_URL`, `CI_REGISTRY_PASSWORD` and `CI_DEPLOY_PASSWORD` from the **pip install, validation and build child processes**. GitLab still injects its standard variables into the runner shell, and arbitrary project/group CI/CD variables are not made safe merely because they are absent from `workflow.secrets`: protect every sensitive variable in GitLab settings, restrict the job-token allowlist/permissions, and do not run untrusted build code in a trusted deployment pipeline. The image digest and GitLab Pages syntax are locally validated, but the pipeline still requires a real GitLab CI acceptance run. GitLab Pages `pages.publish` requires GitLab 17.9 or newer and the published directory must contain a non-empty root `index.html`. See the [GitLab CI/CD YAML reference](https://docs.gitlab.com/ci/yaml/), [workflow rules reference](https://docs.gitlab.com/ci/yaml/workflow/) and [GitLab Pages documentation](https://docs.gitlab.com/user/project/pages/).

## Other CI providers

Azure Pipelines, Jenkins, Buildkite and Bitbucket Pipelines can invoke `validate-config` and `build` directly, but this project does not generate their native pipeline files yet.

## Publishing adapters

The current implementation includes a local/artifact-oriented adapter path and generated GitHub Pages and GitLab Pages workflow handoffs. A provider-specific publisher (for example object storage, Git-based Pages, SFTP or a hosting API) must implement an explicit adapter with dry-run, atomicity, credential scoping, rollback and post-publish verification contracts. Do not infer that a declared provider is supported merely because its URL can be configured. Filesystem publishing rejects source/destination overlap and checks the copied tree for symlinks before activation. Non-atomic mode is intentionally not gap-free, but failed copies attempt to remove partial output and restore the previous tree.

## Release checklist

- Validate the exact production configuration and active profiles.
- Review source and authoring repository/ref identities independently.
- Verify the source-to-authoring mapping with known sample sections.
- Inspect the generated workflow. Pin GitHub Actions to reviewed commit SHAs; pin the GitLab runner image by OCI digest.
- Verify pull/merge-request builds cannot access deployment credentials or broadly scoped job tokens.
- Build on the same runner image/toolchain used in production.
- Run the complete test suite and inspect the site validation report.
- Test deployment in a non-production target first.
- Confirm the deployed URLs and edit links manually before announcing availability.
Workflow environment values are literal single-line values. GitHub Actions workflows cannot override runner-reserved `GITHUB_*` or `RUNNER_*` names or embed GitHub expression syntax; GitLab CI workflows cannot override `CI_*` or `GITLAB_*` names or embed shell variable expansion in static values. Export mapped secrets only through `workflow.secrets` so the generator can validate each declared mapping and reject unsupported merge-request secret use. This mapping is not a security boundary for other CI/CD variables injected by the hosting platform; protect those in the host's project/group settings.

## Machine-readable adapter contract

Run `documentation-publisher capabilities` to print the exact supported workflow, source, publishing, authoring-link, component-link, and communication strategies. A `provider_label` is never adapter selection. Unsupported workflow/VCS/integration/publishing/component-adapter identifiers are rejected by schema validation; a provider-specific remote API or deployment adapter must be implemented and tested before it can be declared supported.


## Profile propagation

`generate-workflow --profile NAME` resolves that profile while generating the workflow and writes the same ordered `--profile NAME` arguments into the generated validation and build commands. Repeated options layer profiles in order. The generated workflow therefore executes the same selected configuration as the command that generated it; profile names are restricted to a safe lower-case identifier syntax before they are embedded in shell commands. `publish --profile NAME` uses the same resolver before selecting the publishing target and dry-run/live behavior.
