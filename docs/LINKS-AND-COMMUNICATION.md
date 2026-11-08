# Link routing and communication channels

## Three independently configured documentation link classes

The publisher distinguishes three link classes. Their source selectors and destination repositories are independent. None of the destinations is inferred from `publisher`, `sources[]`, or either of the other link classes.

1. **Edit links** (`Edit this section` / `Edit this page`): `links.edit` selects an `authoring_targets[]` entry. The Keycloak adapter validates the incoming source link against `sources[].vcs.web_url` and `sources[].vcs.default_ref`; it does not require the editor target to be the source repository.
2. **Issue links** (`Report an issue` / `Report issue`): `links.issues` supplies its own incoming URL prefixes, destination base URL and URL template.
3. **Neighbor/navigation links**: `links.navigation` supplies its own incoming URL/path prefixes, destination base URL, ref, URL template and source-to-target path mapping.

A fourth identity remains separate: `publisher` is only the repository containing this engine/configuration/workflow. The read-only build source, link destinations and public Pages origin do not change when one another's URLs are changed.

Example for the current Keycloak scenario:

```yaml
publisher:
  clone_url: https://github.com/devrimcode/documentation-publisher.git
  ref: main

sources:
  - id: keycloak
    vcs:
      clone_url: https://github.com/keycloak/keycloak.git
      web_url: https://github.com/keycloak/keycloak
      default_ref: main

# Edit destination: independently configured repository/ref/path.
authoring_targets:
  - id: keycloak-edit
    web_url: https://github.com/devrimcode/keycloak
    repository: devrimcode/keycloak
    ref: main
    source_id: keycloak
    edit_url_template: "{web_url}/edit/{ref}/{path}"
    mapping:
      source_prefix: docs/documentation
      target_prefix: docs/documentation

links:
  edit:
    mode: override
    target_id: keycloak-edit
  issues:
    mode: override
    source_prefixes:
      - https://github.com/keycloak/keycloak/issues
    target_url: https://github.com/keycloak/keycloak
    url_template: "{target_url}/{path}{query_suffix}{fragment_suffix}"
  navigation:
    mode: override
    source_prefixes:
      - https://www.keycloak.org/docs/
      - /docs/
    relative_prefixes:
      - ../
    source_page_base_url: https://www.keycloak.org/docs/latest/
    target_url: https://github.com/devrimcode/keycloak
    target_ref: main
    url_template: "{target_url}/tree/{target_ref}/{path}{query_suffix}{fragment_suffix}"
    mapping:
      strip_leading_segments: 1
      target_prefix: docs/documentation
      collapse_index_file: index.html
```

To send all three classes to another repository, change only the three respective destination settings. For example, set the authoring target's `web_url`/`repository`, `links.issues.target_url`, and `links.navigation.target_url` to `https://github.com/xyz/mein-keycloak` and keep the source and publisher settings unchanged. The issue template remains independently configurable, so it can preserve the source issue path or use another issue URL template.

## Edit this section

The edit link is generated only when the rendered HTML contains an explicit edit marker and the engine can resolve it to a real file in a checked-out source. The Keycloak adapter recognizes `Edit this section` and `Edit this page` anchors whose URLs match the configured source repository/ref under `docs/documentation/`. It extracts the source-relative `.adoc` path. The usual marker resolver then:

1. verifies the original `.adoc` file exists in the source checkout;
2. selects the explicit `authoring_targets[]` entry;
3. maps the source path to the target path;
4. constructs the configured editor URL and validates its HTTPS authority.

The source clone URL is not used as the edit destination. The editor repository may be a fork or any other configured repository. A matching target file must also exist at the destination repository/ref/path for GitHub to open it; local configuration validation cannot prove that a remote file exists or that the current user has write access.

For a GitHub target, the common template is `/edit/{ref}/{path}`. Other providers need their own explicit URL template. `provider_label` is display metadata and does not select a provider adapter.

## Issue links

The Keycloak adapter identifies issue links by the explicitly configured `links.issues.source_prefixes`, not by their visible label. Thus every anchor to a selected issue path is routed even if its text is renamed, localized or accompanied by an icon. Use a narrow selector such as `https://github.com/keycloak/keycloak/issues`; do not select the whole repository URL. The selected anchors are routed through `links.issues.target_url` and `links.issues.url_template`. The issue path, query and fragment can be carried over with `{path}`, `{query_suffix}` and `{fragment_suffix}`; the issue-list root is supported as well. A separate destination can therefore point to the official upstream tracker while edit/navigation links point to a fork.

`communication.issues` remains a separate dynamic communication channel for anchors marked as publisher communication links. It is not a substitute for the dedicated Keycloak issue-link routing policy.

## Neighbor and navigation links

For a Keycloak documentation component, anchors can be selected in three explicit ways. `source_prefixes` matches absolute HTTPS URL prefixes and root-relative href prefixes. Absolute prefixes compare both host/authority and path. Root-relative prefixes such as `/docs/` match only root-relative inputs; they cannot capture an absolute external URL from another host. `relative_prefixes` (for example `../`) selects relative neighbor hrefs; these require `source_page_base_url`, which is joined with the current component-relative `page_rel` before matching against `source_prefixes`. Fragment-only and same-page links are not converted into neighbor links.

The destination is constructed only from `links.navigation.target_url`, `target_ref`, `url_template` and `mapping`. Only page-like URLs (extensionless routes or `.html`, `.htm`, `.xhtml`) are selected; linked PDFs, images and other static files are not misclassified as neighboring pages. The mapping supports exact path rules, a fixed `source_prefix`/`target_prefix`, `strip_leading_segments` for versioned paths such as `/docs/{version}/{guide}/`, and optional `collapse_index_file` to map a generated `.../index.html` page to its repository directory. These are configuration-driven transformations, not Keycloak-specific constants in the generic resolver.

Only links matching the configured selectors are rewritten. Add every absolute, root-relative and relative neighbor URL form used by the generated documentation to the corresponding selectors; unmatched links are preserved rather than guessed. The target path is constrained to the explicitly configured repository base path. The resolver does not make a remote GitHub API call to prove that the destination file/directory exists.

## `inherit`, `override`, `disable`

Each of `links.edit`, `links.issues` and `links.navigation` supports its own `inherit`, `override` and `disable` mode. Component-level `link_overrides.edit`, `.issues` and `.navigation` can override the respective global policy independently. `inherit` preserves incoming markup; `override` requires explicit target data and source selectors; `disable` removes the actionable anchor while retaining its visible text/content.

An issue or navigation `override` requires a non-empty `source_prefixes` list and a URL template containing `{target_url}` and `{path}`. Navigation can additionally declare `relative_prefixes` and `source_page_base_url` to resolve relative sibling-guide links. `disable` also requires explicit source selectors so it removes only the intended link class. This prevents a configuration from quietly mapping or removing unrelated links. `allowed_hosts`, `unresolved_policy`, `require_markers` and link target behavior remain independently configurable.

## Communication channels

Dynamic communication channels include email, bug reports, feature requests, discussions, support, security, community and feedback. Each supports `inherit`, `override` and `disable`. URL-channel query values are encoded before template insertion. Email overrides validate mailbox addresses. Security reporting overrides require `private_target_attested: true`; this is an operator attestation, not a technical proof of external ACLs.

## Provenance and safety

Generated edit pages need exact source provenance; the engine never guesses a source file from a rendered page URL. All configured destination templates must produce HTTPS URLs without credentials or sensitive query parameters. Path mappings reject traversal and `.git` paths. Unmatched inputs are not silently redirected to another configured repository.

Local acceptance verifies generated targets against fixtures. Before release, inspect a representative deployed page, open all three link classes, confirm the target repository/ref/path, and separately confirm that the linked remote files and tracker route exist.
