# Workblock 06 — F05: Debian APT snapshot and package-transaction lock

**Result:** local implementation and regression acceptance completed; real container-image build and repeat-build acceptance remain open.

## Parent provenance

This workblock is based only on Workblock 05 (F15 GitLab CI / GitLab Pages), whose delivered archives were re-hashed before the copy used for this workblock:

- Parent ZIP: `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-WORKBLOCK-05-F15-GITLAB-CI.zip`
  - SHA-256: `92aa38d1ffe1eef08558ec7b98a859b578850a3d3f707ecfd661fa0b154728f4`
- Parent TAR.GZ: `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-WORKBLOCK-05-F15-GITLAB-CI.tar.gz`
  - SHA-256: `2de68a9dbf1abd4366b95574a86931dc0494705f7128c9a158adbb5786f47c7f`

The two parent hashes match the accompanying Workblock 05 checksum file. The P12 / R8-028 RECONCILED GROUP 3 ancestry is documented in the earlier Workblock 04 and 05 records and has not been replaced with the older 2.0.8-dev audit archive.

## F05 changes

### 1. Pin the build platform and base image

- `.devcontainer/Dockerfile` retains the digest-pinned Microsoft Dev Container Python 3.13 Bookworm base image:
  `mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:ac334d90ca71f23b58820c90a440b400d175b77d642d312cf67ff0cc9cb2056d`.
- `.devcontainer/devcontainer.json` sets the Docker build option `--platform=linux/amd64`. The base reference is an OCI index digest, so fixing the target platform prevents the index from selecting a different architecture-specific manifest on another host.
- The repository root remains the explicit build context because the Dockerfile copies tracked `.devcontainer/` inputs.

### 2. Freeze Debian APT metadata

`.devcontainer/debian-snapshot.sources.in` defines two Deb822 source stanzas:

- `https://snapshot.debian.org/archive/debian/20261107T000000Z/` for `bookworm` and `bookworm-updates`;
- `https://snapshot.debian.org/archive/debian-security/20261107T000000Z/` for `bookworm-security`.

Both use `main` and `/usr/share/keyrings/debian-archive-keyring.gpg`. The Dockerfile deletes the base-image `/etc/apt/sources.list` and any `.list` / `.sources` files in `sources.list.d` before installing the generated snapshot-only source file. The installer refuses to run if any other APT source remains active.

Both historical source stanzas explicitly use `Check-Valid-Until: no`. This is a deliberate trade-off for an immutable historical archive: APT does not reject the archived Release metadata solely because its freshness deadline has passed. It does **not** disable signature checking; `Signed-By` still binds both repositories to the Debian archive keyring. Disabling the freshness check also reduces protection against replay of old metadata, so the snapshot must be advanced through a reviewed security-maintenance procedure and must not be left frozen indefinitely.

### 3. Generate and verify package lock format v2

`.devcontainer/install-apt-snapshot.sh`:

1. validates the snapshot ID and the exact two snapshot URIs;
2. verifies that only the generated source file is active;
3. performs `apt-get update` against those sources;
4. simulates `apt-get install --no-install-recommends --no-upgrade git-subtree`;
5. fails unless `git-subtree` is part of the simulated install plan;
6. performs the installation; and
7. records every package in the `Inst` transaction with the installed dpkg version.

The resulting `/usr/local/share/devcontainer/apt-install-lock.tsv` is format v2. Its metadata includes:

- snapshot ID;
- SHA-256 of the generated APT source file;
- dpkg target architecture;
- first-line APT version;
- installed dpkg package version; and
- exact package/version rows for packages installed or upgraded by the `git-subtree` transaction.

`.devcontainer/verify-apt-state.sh` rejects an absent or older lock format, source hash drift, changed snapshot ID, architecture drift, APT/dpkg toolchain drift, missing or version-drifted package rows, and additional mutable Debian mirror entries. It runs during image build and on container start. `post-create.sh` copies the generated lock and a SHA-256 sidecar into ignored `test-results/` as environment evidence.

### 4. Documentation and acceptance records

- `.devcontainer/README.md`, `docs/DEVCONTAINER.md`, `docs/GIT-AND-SECURITY.md`, `TEST-IN-CODESPACES.md`, `CURRENT-SOURCE.md` and `STATUS.md` describe the fixed snapshot, platform, generated lock v2, update policy and external acceptance boundary.
- `audit/R8-028/R8-028-GROUP-3-FINDING-STATUS.csv` records F05 as locally implemented but pending a real image build and repeat-build lock comparison.

## Local evidence

- F05 targeted tests: **26 passed, 8 subtests passed**.
- Main regression group: **256 passed, 1 skipped, 99 subtests**.
- Manifest / cleanup group: **6 passed**.
- Wheel / packaging group: **3 passed**.
- Process / timeout group with `ResourceWarning` treated as error: **6 passed**.
- Total across the four independent regression invocations: **271 passed, 1 skipped, 0 failed; 99 subtests**.
- `bash -n` passed for the APT installer, APT state verifier, environment verifier and post-create script.
- The Debian Deb822 source file, with its fixed snapshot ID substituted, was parsed successfully by the installed APT using `apt-get indextargets` and a temporary source-list override. This checks local syntax only; it does not retrieve repository metadata.
- `python -m compileall -q publisher_engine tests scripts` passed.
- JSON parsing passed for `devcontainer.json` and the repository/package schemas.

The single skipped test is the real Git LFS client/object-transfer test because `git-lfs` is not installed in this execution environment. It is unrelated to F05 and is not counted as passed.

## Explicitly not verified

This execution environment has no `docker` or `podman` executable and cannot resolve `snapshot.debian.org` through DNS. Consequently:

- no Docker/BuildKit image build was run;
- no request to either snapshot archive succeeded from this host;
- no actual `git-subtree` package version or transaction closure was observed here;
- the v2 lock was exercised with deterministic fake APT/dpkg commands, not emitted by a real Debian snapshot install; and
- no second clean container build was performed for byte-for-byte lock comparison.

F05 therefore remains **locally implemented, externally pending**. The required release gate is a fresh Codespaces or Docker build on `linux/amd64`, followed by inspection of the generated v2 lock and a second clean build whose lock matches exactly. The snapshot/base-image update must be deliberate and accompanied by the full regression suite.

## References

- Debian Bookworm `sources.list(5)`: Deb822 sources and `Check-Valid-Until` semantics: <https://manpages.debian.org/bookworm/apt/sources.list.5.en.html>
- Debian RollbackUpdate: historical Snapshot APT source example using `Check-Valid-Until: false` and the archive keyring: <https://wiki.debian.org/RollbackUpdate>
- Dev Container JSON reference: `build.context` and `build.options`: <https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainerjson-reference.md>
- Dockerfile reference: platform selection for digest-pinned multi-platform `FROM` images: <https://docs.docker.com/reference/dockerfile/#from>
