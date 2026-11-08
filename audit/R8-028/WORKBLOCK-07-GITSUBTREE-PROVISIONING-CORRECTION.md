# Workblock 07 — Git Subtree provisioning correction after real build failure

**Parent:** Workblock 06 F05 APT Snapshot / Package Lock. Parent archive hashes are recorded in `CURRENT-SOURCE.md`.

**Status:** source correction prepared; project tests and real Codespaces rebuild intentionally pending execution in the user's Codespace. Workblock 06 is superseded because its first real image build failed.

## 1. Original problem that motivated `.devcontainer/`

The Publisher's `git_subtree` source integration calls the real Git extension (`git subtree add`). In the original Codespaces environment, `git --exec-path` returned `/usr/local/libexec/git-core`, while the installed helper existed at `/usr/lib/git-core/git-subtree`. Git therefore could not discover the helper. Manually exporting `GIT_EXEC_PATH=/usr/lib/git-core` made it work, but requiring every user to set that variable in each terminal was explicitly rejected. The Dev Container's responsibility is to make `git subtree -h` work by default without any global environment override.

The earlier R8-027 correction solved this by locating the existing helper and linking it into the active Git exec path. Workblock 06 must preserve this behavior.

## 2. Real Workblock 06 failure

The user's first actual Codespaces rebuild (see `../evidence/R8-028-WORKBLOCK-06-CODESPACES-REBUILD-FAILURE.md`) successfully fetched the pinned Debian snapshot metadata, then failed with `E: Unable to locate package git-subtree`. Workblock 06 introduced a false assumption that a separate Debian Bookworm binary package with that name existed. The recovery Alpine container was not a successful Publisher Dev Container build.

Debian Bookworm's official `git` package file list includes `/usr/lib/git-core/git-subtree`. The helper is shipped by `git`; it is not a separately installable `git-subtree` package.

## 3. Corrected design

1. Retain the digest-pinned Python 3.13 Bookworm base image and fixed `linux/amd64` build target.
2. Retain the signed Debian Bookworm/updates/security snapshot as the only active APT source. Remove mutable base-image mirrors before `apt-get update`; subsequent Dev Container Feature APT operations therefore continue to see the fixed snapshot instead of live Debian mirrors.
3. Do not run `apt-get install git-subtree`, do not simulate such a package transaction, and do not claim an APT install delta.
4. Locate an executable `git-subtree` helper, preferring the current `git --exec-path` and then `command -v` and the standard Debian/Git helper locations.
5. Use `dpkg-query -S` to prove the helper is owned by Debian package `git`; record the exact installed package version and Git version.
6. Resolve the helper's real path and SHA-256. Create only the missing link `<git --exec-path>/git-subtree`; preserve an already-correct link and fail closed if a conflicting target exists.
7. Run `git subtree -h` and require the expected usage output before creating the lock.
8. Generate deterministic lock v3 and verify it during image build and every container start.

## 4. Lock v3 contract

`/usr/local/share/devcontainer/toolchain-lock.tsv` records:

- fixed Debian snapshot ID and SHA-256 of the exact Deb822 source file;
- dpkg architecture, fixed build platform and pinned base-image reference;
- APT, dpkg and Git versions;
- helper owner package (`git`) and exact dpkg version;
- canonical helper source path and SHA-256;
- Git's active exec path, symlink path and resolved target;
- a tab-separated package/version row for the base-image `git` package.

The runtime verifier fails on missing or altered source/helper files, wrong package owner/version, base-image/platform mismatch, architecture or toolchain drift, wrong/broken symlink, unexpected APT sources, or failed `git subtree -h`. The lock is intentionally a base-image Git/helper provenance lock; it does not pretend that an APT `git-subtree` install transaction occurred.

## 5. Files changed

- `.devcontainer/Dockerfile`: remove the separate bogus package transaction; pass the digest-pinned image reference and platform into the lock contract.
- `.devcontainer/install-apt-snapshot.sh`: validate snapshot source, run `apt-get update`, find the base-image helper, verify package ownership/version, link and create lock v3.
- `.devcontainer/verify-apt-state.sh`: verify all v3 lock metadata and actual helper/link/package state.
- `.devcontainer/verify-environment.sh`: report the snapshot plus Git Subtree base-image lock.
- `.devcontainer/post-create.sh`: preserve `toolchain-lock.tsv` and its SHA-256 in ignored test evidence.
- `tests/test_devcontainer_apt.py`, `tests/test_devcontainer_config.py`, `tests/test_devcontainer_runtime.py`: rewrite deterministic fixtures for the real `git` package/helper model and add fail-closed/drift cases.
- Codespaces and security documentation, current status, F05 finding register, provenance and evidence.

## 6. Test execution boundary

The user explicitly required that all tests be run in the user's Codespace. Therefore no Workblock 07 project regression tests were run in the assistant's isolated execution environment. The test suite has been rewritten but remains unverified until the user executes it in the corrected Codespace. Archive hashing, manifest generation and packaging are delivery-integrity steps, not a claim that the software tests passed.

## 7. Acceptance still required

- Fresh Codespaces rebuild succeeds from the corrected archive.
- The generated v3 lock exists and `.devcontainer/verify-apt-state.sh` passes.
- `git --exec-path` shows the expected directory, `git subtree -h` works without setting `GIT_EXEC_PATH`, and `dpkg-query -S` identifies `git` as helper owner.
- Both `postCreateCommand` and `postStartCommand` complete.
- Full Codespaces acceptance and the four isolated regression groups pass.
- A second clean rebuild on the same base digest/snapshot/platform generates a byte-identical `toolchain-lock.tsv`.

Until then, F05/F16 remain open. No commit, push, pull request, release, or deployment was performed.
