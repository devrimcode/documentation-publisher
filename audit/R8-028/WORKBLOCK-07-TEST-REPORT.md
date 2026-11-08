# Workblock 07 — test report placeholder / acceptance ledger

This file is intentionally a ledger template, not a claim of test success. The user required that project tests run in their Codespace, not in the assistant's isolated runtime. No Workblock 07 project tests or image builds have been executed here.

| Gate | Result | Evidence |
|---|---|---|
| Archive provenance and manifest | Prepared for delivery; archive checksum is in the companion `.SHA256` file | Exact Workblock 06 parent hashes, regenerated internal file manifest and root-level TAR.GZ layout |
| Fresh Dev Container build | Pending user's Codespace run | Full Dev Container build log |
| Git Subtree helper owner/link | Pending user's Codespace run | `dpkg-query -S`, `git --exec-path`, `git subtree -h` |
| Workblock 07 targeted tests | Pending user's Codespace run | pytest output |
| Four-group full regression | Pending user's Codespace run | `test-results/` logs |
| Second clean build lock comparison | Pending second fresh Codespace | two `toolchain-lock.tsv` files and hashes |
| Full R8-028 acceptance | Pending F01–F20 and platform/provider programme | completed finding matrix and evidence |

Do not treat this document or the prior Workblock 06 test counts as a successful Workblock 07 test run.
