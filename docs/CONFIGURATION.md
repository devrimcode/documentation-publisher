# Configuration contract

## Independent identities

The configuration deliberately separates these identities:

1. `publisher`: repository containing this engine, its configuration and CI workflow.
2. `sources[]`: repositories fetched and integrated into the temporary publisher clone for building.
3. `authoring_targets[]`: repository/ref/path where a human edits the original source file. This may differ from the build source. For adapters that need to validate incoming source links, set `sources[].vcs.web_url` independently of `sources[].vcs.clone_url` and the authoring target URL.
4. `links.edit`, `links.issues`, and `links.navigation`: three independent destination policies. The edit policy selects an authoring target; issue and navigation policies each have their own source URL selectors, destination URL, ref, template and optional path mapping. Neither derives its target from the publisher, source, or another link policy.
5. `site`: public URL, base path, version/locale routes and output directory.
6. `publishing_targets[]`: destination/adapter that receives the already validated static output.

No identity is derived from another. A missing required identity is a validation error, not an invitation to guess.

## Profiles and precedence

`profiles` are named configuration overlays. Apply them in the order supplied with repeated `--profile` options (or `active_profiles`). Mappings merge recursively; lists replace the previous list in full. This avoids ambiguous list-merging rules. The `profiles` container and every profile entry must be mappings, even when a profile is not active. Unknown profile names fail validation.

Environment interpolation uses `${NAME}` only in the exact non-secret paths handled by the resolver: `project.homepage_url`, `project.repository_url`, `project.logo`, `project.favicon`; `publisher.clone_url`, `publisher.web_url`, `publisher.ref`; `sources[].vcs.clone_url`, `sources[].vcs.web_url`, `sources[].vcs.default_ref`; `authoring_targets[].web_url`, `authoring_targets[].repository`, `authoring_targets[].ref`; `links.issues` and `links.navigation` target URL/template/ref, source prefixes, relative prefixes and source page base URL (also under component link overrides); the supported `site.*` URL/path fields; `workspace.temp_root`; communication address/template/subject/body and `cc[]`/`bcc[]`; component communication overrides; and `publishing_targets[].output_path`. The merged structure is schema-validated before interpolation and validated again afterward.

Every other `${NAME}` occurrence is rejected instead of being passed through as inert text. The only adapter exception is an exact reference such as `${DEPLOY_TOKEN}` inside `build_tasks[].environment` or `publishing_targets[].environment`; it must also be listed in that adapter's `pass_environment` or `secret_environment`, and sensitive values must use `secret_environment`. `workflow.environment`, command arguments, workflow paths and other free-form fields do not expand environment references. Missing variables fail by default. The internal diagnostic `allow_missing_env` mode preserves missing references only in the exact expandable fields; it does not relax unsupported locations. Normal CLI validation does not enable that mode.

## Components, tasks and dependencies

A component maps to one source, route, output, version/locale and a list of build task IDs. Tasks declare an executable and argument vector (`argv`), working-directory scope, dependencies, timeout, retries and expected outputs. Tasks execute in dependency order. Cycles and unknown dependencies are rejected. The optional `link_adapter` currently accepts only `keycloak_asciidoc`; it classifies Keycloak header edit links, configured issue-action links and configured neighbor/navigation links into distinct publisher markers before the normal resolver runs. The edit source-file path is validated against the checked-out source and the configured `authoring_targets[]` repository/ref. Issue and navigation selectors/destinations are defined separately under `links.issues` and `links.navigation`.

Retries default to zero. A task that is not idempotent must not enable retries. Commands are not passed through a shell; shell behavior must be explicitly invoked as a configured executable and reviewed accordingly.

## Independent link destinations

`links.edit`, `links.issues` and `links.navigation` are separate policies. `links.edit.target_id` references an `authoring_targets[]` entry. The issue and navigation policies each require their own `source_prefixes`, `target_url` and `url_template` in `override` mode; the template must include `{target_url}` and `{path}`. The `target_url` is the destination repository root, not an issue-list route. For GitHub issues, the template therefore explicitly adds `/issues/`, for example `"{target_url}/issues/{path}{query_suffix}{fragment_suffix}"`; the incoming suffix (`new`, a ticket number, etc.) is appended beneath that route. The issue-list root is rendered as `/issues/`. This is important: using only `"{target_url}/{path}"` would incorrectly turn `/issues/123` into `/repo/123`. The optional `mapping` supports `source_prefix`, `target_prefix`, exact `rules`, `strip_leading_segments` (0–64) to remove a variable leading path segment such as a documentation version, and `collapse_index_file` to map a generated index filename such as `index.html` to its repository directory. Navigation may additionally use `relative_prefixes` (for example `../`) and an explicit HTTPS `source_page_base_url` to resolve relative sibling-page links against the current component-relative page path. The navigation adapter routes page-like paths (extensionless, `.html`, `.htm`, `.xhtml`) rather than static downloads/assets. Component-level `link_overrides` can independently override the same three classes. Root-relative source prefixes match root-relative hrefs only, never absolute links on unrelated hosts. `disable` also requires source selectors, so it cannot remove unrelated anchors.

Example: the publisher can remain `devrimcode/documentation-publisher`, the read-only build source can remain `keycloak/keycloak`, while edit and navigation targets point to `devrimcode/keycloak` and issue links point to `keycloak/keycloak`. Changing all three link destinations to `xyz/mein-keycloak` requires changing only those destination settings.

## Fallback behavior

Component routes may not overlap one another by parent/child path, even when their casing differs. Component `output_path` values must be non-empty safe paths. Component fallback modes are explicit: `inherit`, `redirect`, `stub`, `omit`, or `error`. `inherit` means retain/route to the original component default configured for that component; it does not invent a destination. An absent or invalid fallback destination fails validation when the selected mode needs one.

## `inherit`, `override`, `disable`

Link and communication modes are independent per feature:

- `inherit`: preserve the source project's original link/contact unchanged.
- `override`: replace only the explicitly marked link/contact using a configured target/template.
- `disable`: remove the actionable anchor while retaining visible link text/content.

A component-level `inherit` edit setting inherits the global edit setting rather than overriding a global `override` or `disable`. Explicit component `override`/`disable` settings take precedence. The default is not assumed globally by the engine: the example selects `inherit`, and semantic validation requires each configured mode to be one of the supported values.


## Public site assets, routing and symlinks

`site.static_assets` declares files or directories copied from inside the publisher checkout into the generated site. Each entry has a `source` and a `destination`, both relative paths. Static assets are copied whether `site.generate_index` is `true` or `false`. Their destination paths may not overlap generated component routes, locale/version indexes, the root index, `.nojekyll`, the build manifest, or `site.not_found_path`.

`site.base_path` is the URL path prefix used when the public site is hosted below a repository path (for example, GitHub Pages Project Sites at `/keycloak-pages`). It is applied consistently to canonical URLs, `{page_url}` template values, and root-relative references in generated or copied HTML/SVG and CSS. This includes link/navigation targets, scripts, images, media, form actions, `srcset`, inline styles, `<style>` blocks, CSS `url(...)` and CSS `@import`, plus meta-refresh targets. Relative URLs, fragment-only references, protocol-relative URLs and absolute external URLs are preserved. The rewrite is idempotent and is a no-op when `base_path` is empty, as with a domain-root deployment. The local-link validator resolves already-prefixed paths back against the generated site root, so validation checks the same paths the browser will request under the project prefix.

`site.not_found_path` controls the generated not-found page (the example uses `404.html`). It must be a safe relative path and must not collide with generated output or a static asset. Component/index routes and static asset destinations are checked for parent/child overlaps, not only exact string equality.

The published site is required to be symlink-free. `validation.require_no_symlinks` is present for clarity and schema compatibility, but it must remain `true`; setting it to `false` is a configuration error. Symlink freedom is enforced again at publish time even when pre-publish content validation is disabled.

## Workflow file paths

`workflow.file` selects where `generate-workflow` writes the generated workflow when `--output` is not supplied. It is repository-root-relative. The CLI locates the nearest ancestor containing a `.git` directory or worktree gitfile; if the configuration is used outside a Git checkout, its containing directory is the fallback root. Parent traversal, absolute paths, paths into Git metadata (including paths that reach `.git` through a symlink), and paths resolving outside the checkout are rejected. Existing workflow files are preserved unless `--replace-existing` is explicitly supplied. The separate CLI option `--output` is the explicit override for a consciously chosen alternate location. It may point outside the checkout, but the CLI resolves existing parent symlinks and refuses any final path inside a `.git` metadata directory; a final-component symlink is rejected as well.

`workflow.config_file` is the path passed to the generated CI job for configuration loading and is repository-root-relative. When omitted, `generate-workflow` records the exact configuration file supplied with `--config`. An explicitly configured value is respected. The build output directory is relative to the configuration file's directory; the generated Pages artifact upload path joins those two repository-relative paths so nested configuration files upload the same output directory the build created.

## URL scheme validation

`validation.validate_redirect_schemes` applies to actual redirects: HTML meta-refresh destinations and component fallback redirect URLs. It does **not** restrict ordinary documentation anchors. Normal `<a>` and `<area>` navigation links may use `http`, `https`, `mailto` or `tel`; active or unsupported schemes such as `javascript`, `vbscript`, `file` and `ftp` remain rejected. This distinction lets documentation retain legitimate local-service examples such as `http://localhost:8080` while keeping automatic redirects under the stricter configured scheme allowlist.

## Strictness

Unknown configuration keys are rejected by JSON Schema. Duplicate YAML mapping keys written explicitly in the same mapping are rejected while loading, rather than silently allowing the last value to win. Standard YAML merge keys (`<<`) continue to work, including explicit overrides of inherited values. This is intentional: a misspelled or duplicated setting must not appear to work. Add new settings to both `schemas/publisher.schema.json` and semantic validation/tests before using them.

## Metadata and validation scope

The project `title`, `description`, `locale`, `favicon`, `logo` and `homepage_url` currently affect the generated index/manifest as implemented. `project.timezone`, when supplied, is validated against the installed IANA timezone database (for example `UTC` or `Europe/Berlin`) but remains metadata only and does not change rendering or scheduling. Other accepted project fields such as `license`, `copyright`, `maintainers` and `repository_url` are configuration metadata only; they are not currently rendered as site UI or complete footer/license content. `validation.validate_external_links` checks configured external host allowlists only. It does not prove that an external URL resolves or returns a successful HTTP response.
