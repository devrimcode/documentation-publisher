# Source-to-Publisher automatic deployment

Workblock 15 carries forward Workblock 14's source-to-Publisher event contract and hardens it for the current Keycloak header format and the real CI runtime. The repository roles remain independent; the source repository is never written to by the Publisher.

## Repository roles

- Publisher and GitHub Pages workflow: `devrimcode/documentation-publisher`.
- Editable/build source: `devrimcode/keycloak`, branch `main`.
- Keycloak AsciiDoc source-link provenance: `keycloak/keycloak` remains the `sources[].vcs.web_url` because the upstream AsciiDoc header generates links using that canonical URL. The physical Git clone (`sources[].vcs.clone_url`) is the fork. The Keycloak adapter validates the original header URL and then maps the edit path to `devrimcode/keycloak`.
- Edit links: `devrimcode/keycloak`.
- Neighbor/navigation links: `devrimcode/keycloak`.
- Issue links: `keycloak/keycloak/issues`.

The three link destinations remain independently configurable; changing the build clone does not change their routing policies.

## Event flow

1. A push to `main` in `devrimcode/keycloak` starts the source-side workflow template at `integration/source-repository/.github/workflows/notify-documentation-publisher.yml`.
2. That workflow sends a GitHub `repository_dispatch` event to `devrimcode/documentation-publisher`, with event type `keycloak-documentation-updated` and payload fields `repository`, `ref`, and exact commit `sha`.
3. The Publisher workflow accepts only that event type. Before building, it verifies that the payload repository is exactly `devrimcode/keycloak`, the ref is exactly `refs/heads/main`, and the SHA is a full 40- or 64-character Git commit ID.
4. The Publisher passes the SHA through `PUBLISHER_KEYCLOAK_SOURCE_SHA`. `git_subtree` fetches and integrates that exact commit into `.publisher-sources/keycloak`, rather than a later moving branch head.
5. The existing Maven task, site assembly, URL rewriting, manifest generation and site validation run normally.
6. Before Pages artifact upload, a repository-dispatch run compares the event SHA with the current configured source branch head. A delayed event for an older commit is marked stale and does not upload a Pages artifact.
7. The separate deploy job repeats the source-head check immediately before calling `deploy-pages`. If the branch has moved since the build completed, the deploy action is skipped and the existing Pages site remains in place.
8. Pages deployment still requires a successful build/site validation and the Publisher's configured deploy branch. Pull requests never deploy.

Manual Publisher runs and normal Publisher-repository pushes do not set the dispatch SHA environment variable; they continue to fetch the configured `main` branch from the fork. GitHub Actions concurrency can be scoped by `github.ref`; production uses a branch-specific group and `cancel-in-progress: false`, so a pull-request run cannot cancel a running main deployment.


## CI runtime compatibility

The production GitHub Actions workflow configures Temurin JDK 25 through a pinned `actions/setup-java` action. Its JDK version matches the current Keycloak documentation CI setup. The build step also receives the Maven Resolver CI arguments used by Keycloak's documentation workflow:

`-B -nsu -Daether.connector.http.connectionMaxTtl=25 -Daether.connector.http.retryHandler.count=5 -Daether.connector.http.retryHandler.serviceUnavailable=429,502,503,504`

The Maven build command itself remains the existing production command in `publisher.yml`; the independent edit, issue and navigation destinations are not changed. The generated GitLab workflow source is kept syntactically compatible with Python 3.11. Dev Container runtime verifier tests now stub the configured Python 3.13 image runtime explicitly so running the tests on Python 3.11 or 3.12 GitHub matrix hosts does not cause false failures.

## Install the source-side workflow in the fork

Copy this template into the source repository at:

`.github/workflows/notify-documentation-publisher.yml`

The template is stored under `integration/source-repository/` in this archive so it is not accidentally installed into the Publisher repository by extracting the Workblock archive.

Create a fine-grained personal access token (or a GitHub App installation token) restricted to the single repository `devrimcode/documentation-publisher` and grant the `Contents: write` repository permission required by GitHub's Create a repository dispatch event API. Store the token in the **source repository** (`devrimcode/keycloak`) as an Actions repository secret named:

`PUBLISHER_DISPATCH_TOKEN`

The source workflow itself receives only `contents: read`; it does not receive a token from the source repository's `GITHUB_TOKEN` for cross-repository writes. Do not put the dispatch token in YAML, commit it, or print it in logs. If the Publisher repository name or event contract changes, update the source-side workflow's API URL and event payload to match `publisher.yml`.

The token is used only by the source workflow step that creates the event. The Publisher workflow does not receive this token. Its own build permissions remain `contents: read`; its deploy job keeps only the configured Pages permissions. Because GitHub's repository-dispatch endpoint requires the receiving repository's `Contents: write` permission, the fine-grained token has more capability than the single dispatch call. Restrict it to the one Publisher repository, never expose it to pull-request workflows, protect the source fork's `main` branch, and require review for changes to the notifier workflow. A GitHub App installation token can be used instead when short-lived credentials are preferred; it still needs the receiving repository permission required by the endpoint.

## GitHub Actions prerequisites

- The generated `.github/workflows/documentation-publisher.yml` must be present on the Publisher repository's default branch. GitHub only runs `repository_dispatch` workflows when the workflow file exists on that default branch.
- The Publisher workflow must be enabled, and GitHub Pages must use **GitHub Actions** as its deployment source.
- The Publisher's source fork must be publicly readable with the current `auth.mode: none`, or an explicit read-only source credential must be configured separately.
- The source-side workflow must be added to `devrimcode/keycloak` and the secret must be configured there. These remote setup steps are not performed by the archive generator.

## Fail-closed behavior and limitations

The Publisher rejects a dispatch with a wrong repository, wrong branch, missing/malformed SHA, or mismatched configured source. It never accepts an arbitrary ref from the event. The source commit actually integrated is recorded in `build-manifest.json` as `source_commit` and `source_revisions`.

If the build, link resolution, site validation, artifact upload, or Pages deployment fails, a new Pages artifact is not deployed. The previous public Pages deployment remains the last known published site. The source-head freshness checks prevent a delayed older dispatch from replacing a newer source revision, subject to the unavoidable interval between the final remote-head check and the deployment action. The next source push triggers its own build; no remote operation is performed by the local Publisher archive.

This Workblock can generate and locally test both workflow sides, but a real cross-repository dispatch, GitHub Actions run and Pages deployment remain external acceptance steps until the source workflow is installed and the secret is configured in GitHub.
