# Publisher archive reconciliation — canonical source decision

**Reconciliation date:** 2026-11-07  
**Scope:** all 61 archive objects returned by the Library listing, plus the newly uploaded P12 Group 1 TAR.GZ.  
**Decision:** P12 R8-028 Group 1 was selected as the canonical base. Group 2 reconciled it; Group 3 is the current cumulative descendant and the sole current development candidate. Do not merge or alternate between prior archives by filename or timestamp alone.

## Canonical ancestry and verified hashes

| Role | Archive | SHA-256 | Disposition |
|---|---|---|---|
| Verified P11 ancestor | `documentation-publisher-v2-r8-2.0.10-dev-P11-ACTIVE-DEVCONTAINER.zip` | `a35bcfe52c130a8505422806f58fc429f7bbad8b0fbcae1d89722d35ba212936` | Provenance ancestor only |
| Canonical P12 Group 1 TAR.GZ | `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-GROUP-1.tar.gz` | `a7cc1cfe79f35a2fdb74f324ce70d4f80a35ea70342e1eb0c1f63704d3d329bb` | Verified base for current Group 2 candidate |
| Canonical P12 Group 1 ZIP | `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-GROUP-1.zip` | `6a6968c9caed26aac4b5b4795c0a9de9ad5f0bb1e34c2e8ffa420470fd3e287f` | Same 138-file project tree as P12 TAR.GZ |
| Parallel Workblock 01 ZIP | `documentation-publisher-v2-r8-2.0.10-dev-r8-028-workblock-01.zip` | `50698868278ed8f5bfd81f2838756aeac0d2669c7cf41ba35c038084c0677f1a` | Superseded parallel branch; do not use as base |
| Parallel Workblock 01 TAR.GZ | `documentation-publisher-v2-r8-2.0.10-dev-r8-028-workblock-01.tar.gz` | `761ecf4be14344a9962aef70dcd5a98d39ae4a4054a713c3a000e5e7f500627d` | Same project tree as its ZIP; superseded |

The uploaded file `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-GROUP-1.tar(1).gz` is byte-identical to the Library P12 TAR.GZ (SHA-256 above). The historical P12 package status at `history/P12-PACKAGE-STATUS.md` identifies the P11 Active ZIP hash as its source ancestor; that hash matches the archived P11 baseline.

## Why Workblock 01 is not the canonical source

P12 and Workblock 01 are parallel descendants of the same P11 Active source, not a linear sequence. The extracted trees compared as follows:

- P12: 138 files; Workblock 01: 137 files.
- 64 same-name files byte-identical.
- 19 same-name files differ.
- 55 files occur only in P12; 54 occur only in Workblock 01.

The differences include executable code and tests. In particular, Workblock 01 weakened P12's strict allowlist handling and reserved-origin checks, and its communication link runtime admitted `*` wildcard hosts by bypassing the strict rejection. Those changes are not merged. Selected additions from Workblock 01 (exact environment-reference validation, IANA timezone validation, Python 3.13 check, `.gitignore`, and clarifying documentation) were independently ported to the P12 tree and re-tested while preserving P12's stronger security routines.

## Archive inventory

`ARCHIVE-INVENTORY.csv` lists every one of the 61 archive objects returned by the recursive Library inventory, classified as canonical, verified ancestor, superseded parallel branch, historical project snapshot, audit-only material, Keycloak support, or unrelated project material.

Use the following rules:

1. Only the reconciled R8-028 Group 3 archive is the current development candidate. Group 2 is its verified parent; P12 Group 1 is a historical ancestor, not a second current candidate.
2. P11 Active is retained as provenance, not as an alternative current project.
3. Workblock 01 is retained as a superseded branch. Do not merge it wholesale.
4. P1/P2/P3/P11 cumulative candidates and earlier hardened R6/R7/R8 archives are history/evidence, not current sources.
5. R8-028 audit bundles are evidence/matrix artifacts, not standalone source trees.
6. Keycloak Pages/edit-link/runbook archives are integration evidence or fixtures, not alternative publisher-engine source trees.
7. NIS2/guides archives are separate content projects and not part of the publisher source lineage.

## Manifest rule for the reconciled package

The Group 3 `PROJECT-MANIFEST.SHA256` was regenerated from its complete package tree and lists every file except itself. Each Workblock 04/05/06/07/08/09 descendant regenerates its own manifest after changes; its companion archive and evidence record that exact tree. Workblock 09 is the current local correction descendant. Workblock 06 is preserved but superseded after its actual Codespaces build failed on the nonexistent `git-subtree` package. Historical phase reports and test outputs under `audit/history/` must not be used as current test evidence. The only current project status is `STATUS.md`.

## Safety boundary

This reconciliation used isolated copies. It did not alter the user's GitHub repository, Codespace, remote branches, Keycloak upstream, or any Library archive. No commit, push, pull request, or deployment was performed.

## Group 3 parent head

At the Group 3 delivery point, the head was `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-RECONCILED-GROUP-3`. It adds F12/F14/F15/F19 and supersedes the Group 2 delivery. It remains the immutable parent baseline for Workblock 04. The Group 2 parent matrices and reports remain in `audit/history/` or Group 2-named evidence files.


## Workblock 04–07 local remediation descendants

Workblock 04 added the OCI-index digest pin and Python CI matrix. Workblock 05 added the GitLab CI/Pages generator. Workblock 06 attempted to snapshot APT metadata and create a package transaction lock, but its first real user Codespaces build reached the snapshot and failed because no Debian Bookworm package named `git-subtree` exists. Workblock 07 supersedes that mistaken package assumption and restores the original discovery/link behavior: the Debian `git` package owns the helper at `/usr/lib/git-core/git-subtree`; it is linked into Git's active exec path and recorded with package/helper provenance in lock v3.

Workblock 07 is a local development descendant, not an externally accepted release. Its project regression and corrected image have not yet been tested in the user's Codespace; F05/F16 remain open until the clean build and repeat-build lock comparison succeed. F07's remote matrix, real Git-LFS transfer, Windows process acceptance and browser/provider checks also remain open. See `../STATUS.md`, `R8-028/WORKBLOCK-07-GITSUBTREE-PROVISIONING-CORRECTION.md` and `R8-028/WORKBLOCK-07-TEST-PLAN.md`.


## Workblock 08–09 descendants

Workblock 08 retained the complete Workblock-07 tree and corrected two regression assertions (Git Subtree fallback isolation and precise APT-source rejection expectations). Its verified SHA-256 is `6e9fe369a95be2a93af53c3fa99ff80a53a4c3b77149337cff6cdfc741247ea7`. Workblock 09 is a full cumulative rebuild of that tree. It resolves the Codespaces Python bootstrap ordering issue by making dependency installation retryable on container start and new interactive Bash terminal startup, adds automatic project `.venv` activation, strengthens fail-closed verification, and tests the active `sys.prefix`. `CURRENT-SOURCE.md` names the sole current archive. No remote repository or Codespace was changed.


## Workblock 10–13 independent-link descendants

Workblock 10 separated the read-only Keycloak source from the edit repository. Workblock 11 introduced independent edit, issue and neighbor/navigation destinations. Workblock 12 corrected redirect-scheme validation so ordinary HTTP documentation anchors were not rejected. The user's actual Workblock 12 Keycloak build then passed, but the produced HTML audit identified an issue-link path defect: the source `/issues` selector was stripped and its suffix was appended directly under the target repository root. Workblock 13 corrects the GitHub issue route template and resolver, updates the regression that had codified the wrong `/repo/123` result, and adds a synthetic full local-subtree build asserting final `/repo/issues/123` URLs. Workblock 13 (`workblock13.tar.gz`, version `2.0.13-dev`) is the current canonical source; Workblock 12 (`workblock12.tar.gz`, SHA-256 `6cb3b47652b9e60edbee74e3e7283e7ef1673b76f3ce0ff99673d9f78013994e`) is its verified immediate parent. The actual upstream Keycloak build must be rerun on Workblock 13 before accepting the issue-link output.
