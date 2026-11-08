# P12 – R8-028-P1A complete project candidate

**Status:** P1A implemented and locally regression-tested; not a production release.

## Provenance

Recovered source archive: `documentation-publisher-v2-r8-2.0.10-dev-P11-ACTIVE-DEVCONTAINER.zip`
SHA-256: `a35bcfe52c130a8505422806f58fc429f7bbad8b0fbcae1d89722d35ba212936`

P12 is a complete project tree derived from that exact recovered P11 archive. The cumulative source delta is `audit/evidence/R8-028-P1A-CUMULATIVE.patch`.

## Current test evidence

- Main suite (excluding process tests): 218 passed, 1 skipped, 73 subtests.
- Process suite in separate invocation, with ResourceWarning as error: 6/6 passed.
- Combined regression: 224 passed, 1 skipped, 0 failed.
- Focused P1A tests: 48/48 (31 configuration/security, 12 Dev Container config, 5 runtime verifier). These are included in the main suite and are not counted twice.
- Codespaces starter completed end-to-end with transparent test doubles for four host-missing/wrong tools; this verifies the starter flow, not the image installation.
- Differential P11 baseline run reproduced the old wildcard allowlist and reserved live-origin behavior (11 assertion failures/subfailures; one Dry-Run control passed).

Evidence is under `audit/evidence/R8-028-P1A-*`.

## Still open

- The single skipped test is the real Git-LFS object transfer.
- The raw local host lacks Git LFS and Maven, activates Java 21 rather than Java 25, and has no additional SDKMAN Java-21 candidate.
- No Docker/Podman build or real GitHub Codespace rebuild was performed.
- Python image tag is not digest-pinned; Debian `git-subtree` apt package is not snapshot-pinned.
- Browser acceptance, Windows process-tree acceptance and remaining R8-028 option behavior matrix are not closed.

No remote repository, user Codespace, Keycloak upstream, commit, push or deployment was changed by this work.
