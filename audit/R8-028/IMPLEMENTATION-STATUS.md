# R8-028 — Group 3 parent implementation and acceptance status

Use the root [`STATUS.md`](../../STATUS.md) as the one current top-level status. This file is the detailed implementation index for the Group 3 parent stage; subsequent Workblocks 04 and 05 are documented separately. Historical Group 1/2 outcomes remain under `audit/history/` and the earlier Group 2 logs are retained as historic evidence.

## Group 3 findings

- **F12 — closed locally:** safe `init-config`; packaged generic fail-closed template; no-overwrite and path protections; tested both in source tree and installed wheel.
- **F14 — closed locally for Linux wheel:** PEP 517 wheel, runtime package resources, PEP 621 metadata and console command tested from a temporary environment outside checkout. Cross-platform packaging/package-index acceptance remains open.
- **F15 — partially closed:** explicit provider registry and schema consistency. Only existing providers are declared; no new GitLab, Bitbucket or remote provider API adapters were added.
- **F19 — closed locally:** uniform repeatable profile arguments for all config-consuming CLI phases; ordered resolution and generated workflow propagation covered by tests.

## Group 3 parent matrices

250 option/contract nodes, 258 schema/dynamic coverage rows and all 31,125 unordered pairs. The pair matrix contains 87 direct relationship IDs on 87 rows and 31,038 `N/A` rows. `N/A` means unverified, not compatible. Direct Group 3 contracts are in `F12-F14-F15-F19-CONTRACT-RELATIONSHIPS.csv`.

## Group 3 parent verification (historical after Workblock 04)

Core: 245 passed, one Git-LFS skip; package: 3 passed; process: 6 passed with `ResourceWarning` as error. Total 254 passed, one skip, zero failures. Full evidence is under `audit/evidence/R8-028-GROUP-3-*`; test accounting and external limitations are in `GROUP-3-TEST-SUMMARY.md`.
