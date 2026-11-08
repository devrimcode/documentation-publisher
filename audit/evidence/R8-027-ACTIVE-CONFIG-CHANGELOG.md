# R8-027 – active Codespaces configuration change record

## Final repository files

The repository now contains the active configuration at exactly:

- `.devcontainer/devcontainer.json`
- `.devcontainer/Dockerfile`
- `.devcontainer/post-create.sh`
- `.devcontainer/verify-environment.sh`
- `.devcontainer/README.md`

There is no `.devcontainer/devcontainer.json.example` in the final tree.

## Corrections made after the earlier unusable candidate

1. Replaced the example-only file with the active `devcontainer.json` that GitHub Codespaces detects by default.
2. Removed the repo-local Git Subtree Feature installer and placed the `git-subtree` package installation in the Dockerfile. This avoids depending on executable file mode when files are uploaded through the GitHub web UI.
3. Guarded the helper link creation. If Debian already places `git-subtree` at `$(git --exec-path)/git-subtree`, the Dockerfile leaves that executable unchanged; otherwise it links the discovered package helper into the active Git exec path. This prevents a self-referential symlink.
4. Changed the base image to the Microsoft Container Registry-listed `mcr.microsoft.com/devcontainers/python:3.13-bookworm` tag.
5. Set `waitFor` to `postCreateCommand`, so Codespaces does not report readiness before Python virtual-environment setup completes.
6. Kept Git LFS automatic pull disabled; Git LFS is installed but large objects are not fetched implicitly during container creation.

## Local verification

- Strict JSON parse: passed.
- Active configuration tests: 8/8 passed.
- Dockerfile same-path branch against the current host's real `/usr/lib/git-core/git-subtree`: passed; the original executable remained a regular file and `git subtree -h` worked.
- Dockerfile alternate-path branch: covered by the same-path guard unit test.
- Shell syntax: passed.
- Fresh-repository lifecycle fixture: passed with mocked system tool commands.

## Explicitly not verified

No Docker or Podman runtime is available in this execution environment. The Docker image has not been built, and no GitHub Codespace has been created from a repository branch containing these files. The final acceptance still requires saving this directory in the new repository and creating a Codespace from that branch.
