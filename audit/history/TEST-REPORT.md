# Development test report

Date: 2026-11-05  
Package version: `2.0.8-dev`

## Executed checks

- `python -m unittest discover -s tests -v`: **108 tests passed**.
- `python -m py_compile publisher_engine/*.py tests/*.py`: passed.
- `python -m publisher_engine.cli --help`: passed.
- `python -m publisher_engine.cli --version`: reports `2.0.8-dev`.
- `Draft202012Validator.check_schema()` on `schemas/publisher.schema.json`: passed.
- Configuration loading rejects duplicate YAML mapping keys while retaining standard YAML `<<` merge-key behavior and explicit overrides of inherited values.
- The merged configuration is JSON-Schema-validated before and after supported environment interpolation. Malformed nested structures and malformed/inactive profile definitions fail as `ConfigError` rather than causing incidental resolver exceptions.
- Environment interpolation tests verify supported public identity/URL/path fields, missing-variable behavior, and that task secret values and workflow environment expressions remain symbolic.
- Generated GitHub Actions YAML is parsed with a strict loader that rejects duplicate mapping keys. Workflow tests also verify that nested configuration files generate the workflow at the checkout root, that the generated workflow references the exact config file, and that the Pages artifact path matches the build output location relative to that config file.
- A real local bare-repository integration test executes `git subtree add`, builds a fixture site, verifies a separate authoring target, generated edit/issue/email links, unchanged publisher remote state, and temporary workspace cleanup.
- A failure-path integration test verifies that a failed build does not publish a partial site and removes its temporary workspace.
- Archive tests cover ZIP/TAR traversal, symlink/special-entry rejection, Windows alternate-data-stream path rejection, size/count/compression-ratio limits, streamed TAR entry counting, and cleanup after extraction failure.
- Path tests cover drive/ADS ambiguities, NUL characters, and `.git` metadata path denial across configuration, output, route, static-asset, workflow and Git-related paths, including a symlink whose resolved target enters `.git`.
- Publishing tests cover atomic and non-atomic filesystem publishing, source/destination overlap rejection, pre-commit symlink detection, replacement policy, cleanup/restore failure paths, destination validation, failed-copy rollback and partial-destination cleanup, command adapter environment allowlists, secret redaction, timeout handling, and unknown template placeholders.
- File-copy tests verify that symlinks are preserved as links during tree staging and rejected before activation, and that regular-file copying detects a source changed to a symlink after the initial `lstat` check. `O_NOFOLLOW` is used where supported by the operating system.
- Cleanup regression coverage verifies that permission repair does not change the mode of an external target reached through a symlink.
- Sensitive environment-name validation includes common personal access token and signed-token names such as `GH_PAT` and `JWT`; explicit secret classification remains mandatory in supported passthrough contexts.
- Site validation tests cover broken links, fragments, CSS assets, active schemes, size/file-count limits, and browser-style backslash/encoded-backslash path normalization in HTML and CSS URLs.
- Workflow tests cover pinned action SHAs, action-reference validation, shell-injection resistance for the config path, duplicate YAML-key rejection, separate build/deploy jobs, permissions, triggers, and secret restrictions.
- CLI explicit-output tests verify that `generate-workflow --output` refuses direct paths inside `.git` and paths through an existing symlink into `.git`, while still allowing an explicitly chosen external output directory.
- Git LFS remote lifecycle tests are mocked. No live Git LFS fetch was performed.
- The two direct runtime dependencies present in this run (`PyYAML 6.0.3` and `jsonschema 4.26.0`) satisfy `requirements.txt` constraints.

## Coverage

Measured with `coverage run --branch --source=publisher_engine -m unittest discover -s tests` on this 108-test state. The report includes only `publisher_engine/*.py`, not tests:

- Statement coverage: **79.3%** (1,844 of 2,326 statements; exact 79.2777%).
- Branch coverage: **65.4%** (815 of 1,246 branches; exact 65.4093%).

These values remain short of exhaustive testing. Coverage percentages alone do not establish correctness or security. The configuration, archive, links, Git, and build/publish engine modules still contain untested validation and platform-dependent branches.

## Runtime used for this test run

- Python: 3.13.5
- Git: 2.47.3
- PyYAML: 6.0.3
- jsonschema: 4.26.0
- Operating environment: Linux development container

The suite uses local temporary repositories and fixture files. It does not establish compatibility with every target OS, Python/Git version, CI runner, Git host, or publishing service. In particular, no native Windows runner was available for this test run.

## Environment note

A global `python -m pip check` is **not clean** in this shared development container because the unrelated preinstalled package `moviepy 2.2.1` requires `Pillow<12`, while the container has `Pillow 12.3.0`. `Pillow` is not a direct or transitive dependency declared by this publisher's `requirements.txt`; the publisher's two direct runtime dependency constraints were checked separately and are satisfied. This environment-wide conflict is not silently reported as a clean dependency check.

## Important limitations

- The example configuration intentionally contains placeholders and must fail until populated.
- `generic-git-web` is a configurable URL-template mechanism; provider-specific editor URLs need live acceptance tests.
- The generated workflow supports GitHub Actions + GitHub Pages only. Nested config-file handling is covered locally, but still needs a real CI run in the intended repository.
- Nested Git submodules are rejected; LFS requires the Git LFS extension. LFS remote lifecycle is unit-tested with mocks, not against a real LFS server.
- Build tasks execute with runner OS permissions and are not sandboxed. Only trusted build code should run.
- Public site publication always rejects symlinks; `validation.require_no_symlinks` must remain `true`.
- Repository-relative paths reject colon-bearing segments, NUL characters, and `.git` metadata path segments. URL validation normalizes backslashes for traversal checking, but this does not replace native target-OS acceptance testing.
- Sensitive environment-name detection is heuristic. It recognizes common names including PAT/JWT markers, but it is not a credential scanner and cannot replace least-privilege runner configuration, secret rotation, or code review.
- Filesystem publishing rejects source/destination overlap. Atomic publishing stages and checks the copy before switching; non-atomic publishing remains intentionally not gap-free, but failed copies remove partial output and restore an untouched previous destination where possible.
- Directory replacement is not a guaranteed gap-free directory swap. If old-backup cleanup fails after a new tree is active, the new tree remains live and the remaining backup path is reported; it is not rolled back to a possibly partial backup.
- External links are not guaranteed to be reachable unless external checking is explicitly enabled and network behavior is controlled.
- Static assets are copied from paths inside the publisher checkout. Their destination paths are checked against generated routes and reserved files.
- The regular-file no-follow copy guard uses OS facilities where available; behavior still needs verification on every intended target filesystem and OS.
- No live remote repository or production/staging publishing target was accessed during this run.
- No changes were pushed to any remote repository, and nothing was published.

## Release status

**NOT PRODUCTION-READY.** This is a development implementation with a focused test suite. The release gates in `docs/KNOWN-LIMITS.md` remain mandatory, including a disposable-clone acceptance run against the intended repositories, provider-specific edit-link verification, credential/permission review, target-OS checks, and staging publication with rollback verification. Deployment still requires explicit owner approval.
