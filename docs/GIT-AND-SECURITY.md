# Git integration, credentials and workspace security

## Real subtree procedure

For each selected source the engine fetches the configured ref, resolves `FETCH_HEAD` to a full commit SHA, and runs `git subtree add --prefix=... [--squash] <sha>`. The subtree prefix must be a safe relative path and must not already exist. Publisher, source and authoring refs are checked with Git ref grammar before any clone/fetch. There is no fallback to copying a checkout into place.

The `git subtree -h` preflight is time-bounded and reports both `git --exec-path` and any `GIT_EXEC_PATH` override when the extension cannot be found. For GitHub Codespaces and other Dev Containers, use the active `.devcontainer/devcontainer.json` and `.devcontainer/Dockerfile` (see [Dev Container setup](DEVCONTAINER.md)). The digest-pinned Debian Bookworm base image supplies `/usr/lib/git-core/git-subtree` as a file owned by its `git` package; Debian Bookworm has no separate `git-subtree` binary package. The installer validates the owner/version and helper SHA-256, then links only this existing helper into the active Git exec path. Signed APT metadata is fixed to snapshot `20261107T000000Z`; lock v3 records the base-image digest, platform, APT source hash, architecture, APT/dpkg/Git versions, helper owner/version/hash and the active link. The startup verifier rejects drift or a mutable Debian mirror. It does not set `GIT_EXEC_PATH` globally or require a per-terminal export. Outside Dev Containers, install the `git-subtree` extension for the operating system and make it discoverable by the Git executable used by the publisher. The operation occurs in a temporary clone of the publisher repository. It does not push the integration commit. The publisher remote is not modified. The workspace is deleted according to cleanup policy; cleanup failures are fatal when `fail_on_cleanup_error` is enabled.

`history: shallow` controls fetch depth and `squash` controls subtree history representation. A shallow source may not provide full source history. If full history is required for provenance/audit, configure full history and test repository size/performance.

## Authentication

Supported Git authentication modes are `none`, `ssh_agent`, and `environment`. Environment auth uses named environment variables and a temporary askpass helper. Do not embed credentials in URLs. Repository URLs may use HTTPS or SSH; `file://` URLs are rejected, while local repositories can be supplied as explicit filesystem paths. A configured `allowed_hosts` list always requires an actual hostname and cannot be bypassed by a hostless URL. Do not print secrets in build logs. GitHub Actions workflow generation rejects pull-request triggers when repository secrets are required, because fork pull requests do not receive those secrets. SSH-agent auth is not provisioned automatically by the generated workflow.

Build tasks receive only explicitly allowlisted environment variables plus a small platform baseline. Git credential variables and askpass helpers are removed from task environments. Names containing common credential markers—including `TOKEN`, `SECRET`, `PASSWORD`, `API_KEY`, `PAT`, `JWT`, `BEARER`, `CLIENT_SECRET`, and `REFRESH_TOKEN`—are treated as sensitive and require explicit secret bindings where passthrough is supported. Workflow-level environment entries cannot carry such sensitive names; bind them through the workflow secret mapping. This name heuristic is a guardrail, not a guarantee that every credential name can be recognized. Secret values should be passed only to the task that requires them and should not be echoed by that task.

## Archive safety

ZIP and TAR extraction reject path traversal, symlinks, special files, and colon-bearing path segments (including Windows alternate-data-stream forms) and enforce configured size/count/ratio limits. TAR headers are processed as a stream so the entry-count limit is checked incrementally. Never extract untrusted archives outside the disposable workspace. Review any new archive format adapter separately.

## Workspace safety

The workspace lock prevents overlapping builds that target the same configured workspace. Temporary files are created under the configured temp root. Output replacement is guarded and must not target the repository root, a tracked file or directory, or any parent/child path that would overlap tracked content. The guard is evaluated against `git ls-files` before the site output is created or replaced. Workspace and publishing paths are also checked against the actual Git metadata directory, including a worktree gitfile target and symlink-resolved paths. Symlinks in generated output and in the site root are rejected unconditionally, including when pre-publish content validation is disabled. Filesystem publishing also rejects any source/destination overlap (same path, destination nested in source, or source nested in destination), preventing recursive staging and self-deletion.

Repository-relative paths must not point into a `.git` metadata directory. The guard is case-insensitive for compatibility with case-insensitive filesystems. That covers configured site output, component routes/output paths, static-asset source/destinations, required files, archive roots, and generated workflow/configuration paths. Static/component file copying uses regular-file opens (with `O_NOFOLLOW` where available); directory copies preserve symlink entries instead of dereferencing them, then reject any staged symlink before the build can be accepted. During recursive cleanup, permission repair never calls `chmod` through a symlink, so a linked external target's mode is not changed as a side effect of cleanup.

## Threat model and limits

The engine is not a sandbox for malicious build tools: a build task runs with the operating-system permissions of the runner. Use ephemeral CI runners, least-privilege tokens, network restrictions where practical, and reviewed build commands. A compromised source/build script can still read any environment variables explicitly passed to its process and can attempt network access available to the runner.

Directory replacement stages a complete new tree before switching the destination. When replacing an existing directory, the old tree is renamed to a uniquely named backup and the staged tree is then renamed into place. This prevents a partially copied tree from becoming the live output, but it is **not a guaranteed gap-free directory swap**. If cleanup of the previous backup fails after the new tree is active, the publisher keeps the new tree active and reports the remaining backup path; it does not roll back to a backup that may already have been partially deleted. Inspect that path manually before cleanup.


Filesystem publish copies preserve symlinks during the copy operation and reject them in the copied tree before the tree is switched into place. Regular files are opened without following symlinks where the OS supports it. The explicitly non-atomic copy mode is not gap-free, but a failed copy removes its partial destination and restores an untouched previous destination when one existed. If restoration or cleanup itself fails, the error reports the remaining recovery path; inspect it before manual cleanup.


Local HTML and CSS URL paths are percent-decoded and backslashes are normalized to path separators before traversal checks. This aligns validation more closely with browser URL handling and prevents Linux from treating a Windows-style `\..\` path as an ordinary filename during link validation.

## External link validation scope

`validation.validate_external_links` is an external-host allowlist check, not a network reachability check. It does not perform DNS lookups, HTTP requests, status-code verification, or redirect-chain checks. Do not interpret a successful build with this option enabled as proof that every external destination is online.


Repository `allowed_hosts` values are exact hostnames only. Wildcards such as `*` and `*.example.com` are rejected; list every permitted hostname explicitly. Omitting `allowed_hosts` retains the documented unrestricted-host behavior, so deployments that require host restriction must set a reviewed non-empty allowlist. The generic `publisher.example.yml` template uses unresolved host placeholders and therefore fails validation until explicit hostnames are supplied.

A live configuration (`publishing.dry_run: false`) must use a real public origin. Reserved example/test origins (`example.invalid`, `.example`, `.test`, `.localhost`, and `example.com/.net/.org`, including their subdomains) are allowed for dry-run fixtures only and are rejected for live publishing. Non-global IP origins (loopback, private, link-local, documentation-only and multicast ranges) are rejected for live publishing as well. Exact host allowlist entries must be syntactically valid hostnames; wildcard, empty labels and labels beginning/ending with a hyphen are rejected.
