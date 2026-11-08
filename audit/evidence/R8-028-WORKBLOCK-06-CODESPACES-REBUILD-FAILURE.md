# Workblock 06 — actual Codespaces rebuild failure

**Evidence source:** user-supplied Codespaces Dev Container build log, 2026-11-08 00:09:58–00:11:42 UTC.

## What succeeded

- Codespaces discovered `.devcontainer/devcontainer.json` and invoked `devcontainer up`.
- Dev Containers CLI emitted a non-fatal image-details parsing warning for the digest-qualified reference. BuildKit subsequently loaded the exact digest-pinned `mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:ac334d90ca71f23b58820c90a440b400d175b77d642d312cf67ff0cc9cb2056d` base image successfully; this warning was not the build-stopping error.
- Feature dependencies for Java Feature `1.8.3` and Git LFS Feature `1.2.5` resolved.
- The `linux/amd64` Docker build context was created successfully.
- The build removed mutable Debian source files, installed the configured Deb822 snapshot source and reached the signed Debian snapshot at `20261107T000000Z`.
- Debian Bookworm, Bookworm-updates and Bookworm-security `InRelease` and `Packages` indexes were successfully downloaded (about 9.4 MB total). This directly disproves DNS/network failure as the cause of this build failure.

## Fatal error

The image build then executed `.devcontainer/install-apt-snapshot.sh`, which simulated an installation of a package named `git-subtree`. APT returned:

```text
E: Unable to locate package git-subtree
```

The command exited with APT status `100`; the Docker build stage and Codespaces container creation failed. The fatal line came from the incorrect package name/assumption in Workblock 06, not from failure to reach the snapshot.

## Recovery container is not an acceptance result

Codespaces subsequently created its fallback `mcr.microsoft.com/devcontainers/base:alpine` recovery container and reported that recovery process as successful. That container is not the configured Python 3.13 Publisher image, and the output does not show that the Publisher's APT lock, `postCreateCommand`, `postStartCommand`, Java/Maven/Git-LFS toolchain or regression suite ran successfully.

## Corrective consequence

Debian Bookworm's `git` package file list includes `/usr/lib/git-core/git-subtree`; the helper is not a separate package named `git-subtree`. The original provisioning issue was the mismatch between Git's active exec path and the installed helper location. Workblock 07 therefore restores the original locate-and-link design, validates the helper's dpkg owner/version and checksum, and records this state in a new v3 lock. The new archive must undergo a fresh Codespaces build before any pass is claimed. The non-fatal Dev Containers CLI parsing warning should also be observed on the next build, but do not change or remove the digest pin solely because of this warning while BuildKit itself resolves the digest successfully.
