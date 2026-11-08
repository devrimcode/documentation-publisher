# Workblock 08 — Regression-test isolation and APT snapshot assertions

Date: 2026-11-08  
Project: Documentation Publisher `2.0.10.dev0`  
Lineage: P12 / R8-028 RECONCILED GROUP 3, based on Workblock 07.

## Purpose

This is a complete project-source archive, not a patch-only bundle. It carries the full Workblock-07 project tree and corrects the two failing assertions reported by the user's Codespaces run on 2026-11-08.

## Source integrity

- Workblock-07 input archive: `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-WORKBLOCK-07-GITSUBTREE-PROVISIONING-CORRECTION.tar.gz`
- Verified input SHA-256: `3f2cda904d5347b4e654cc604d07aefb0e5ad2cd56da14810d1339884182a5a3`
- Canonical R8-028 Group 3 parent archive SHA-256: `cee4217a13faf5e2acddddcbac60e806f35fd49b71d6ab0a458f761a122d6c95`

## Corrections included

### 1. Git Subtree test isolation

The real Codespaces environment already has the Git Subtree helper at `/usr/local/libexec/git-core/git-subtree`, and Git's active exec path is `/usr/local/libexec/git-core`. The production installer continues to search the active Git exec path first and retains `/usr/lib/git-core/git-subtree`, `/usr/libexec/git-core/git-subtree`, `/usr/local/lib/git-core/git-subtree`, and `/usr/local/libexec/git-core/git-subtree` as its default fallback candidates.

The failing unit test used a synthetic Git executable and a temporary exec path, but the installer could still see the real container helper through its absolute fallback paths. The test was therefore not hermetic. The installer now supports an optional `GIT_SUBTREE_FALLBACK_PATHS` test seam. When the variable is unset, production defaults are unchanged. Test fixtures set it to an empty list so the real container's helper cannot leak into the missing-helper case. A separate fixture test explicitly supplies a temporary package-helper path and verifies that the fallback path is still honored.

This correction does not move, remove, reinstall, or replace the real Codespaces helper.

### 2. APT source rejection tests

The prior test added a second `.sources` file and expected the message `Mutable Debian mirror found`. The verifier correctly failed closed earlier with `Unexpected APT source file exists outside the locked snapshot`.

The test is now split into two precise checks:

- An additional source file is rejected, asserting the verifier's actual early-rejection diagnostic.
- The frozen source file itself is modified to use `https://deb.debian.org/debian/`; the lock's `source-sha256` is recomputed to match the modified file; the verifier must still reject it because its URI no longer points to the immutable snapshot.

This preserves the distinction between extra active sources and mutation of the locked source file.

## Test evidence and limitations

The user's preceding Codespaces run reported:

- 258 passed
- 2 failed
- 1 skipped
- 99 subtests passed

The two failures correspond to the tests corrected here. The skipped test is the real Git LFS HTTP batch/object transfer fixture in `tests/test_p8_git_lfs.py`. This workblock does not claim that live LFS transfer has been tested or that the full regression suite now passes.

No project test suite was executed while assembling this archive. The changes must be validated in the user's Codespaces environment. The regenerated `PROJECT-MANIFEST.SHA256` is an archive file-integrity manifest, not software-test evidence.

## Codespaces validation sequence

Run in the unpacked project inside the intended Debian Bookworm Dev Container:

```bash
python -m pytest -q tests/test_devcontainer_apt.py
python -m pytest -q --ignore=tests/test_process.py --ignore=tests/test_packaging.py --ignore=tests/test_p6_p7_manifest_cleanup.py
bash scripts/test-in-codespaces.sh
```

Record the full command output and exit codes. A skipped LFS transfer remains open until a real local HTTP batch/object fixture is implemented and passes.

## Scope boundary

This archive does not restore or modify any GitHub repository, Codespace, branch, commit, or remote. It is a downloadable full source archive only. No commit, push, release, or deployment was performed.
