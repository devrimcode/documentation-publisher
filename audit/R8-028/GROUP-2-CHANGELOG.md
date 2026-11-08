# Reconciled Group 2 — cumulative change log

## Canonical source decision

The P12 R8-028 Group 1 archive is the verified parent. The parallel Workblock 01 archive is not merged wholesale. It weakened P12's strict host/wildcard handling; only independently verified additions were ported. See `../ARCHIVE-RECONCILIATION.md`.

## Code/configuration changes

1. **Live destination protection:** reject reserved example/test origins for live publication and generated live workflows; dry-run fixtures remain valid.
2. **Repository host policy:** preserve P12's exact allowlist validation and wildcard rejection. The generic example uses explicit host placeholders; omission of `allowed_hosts` remains a documented backwards-compatible unrestricted mode.
3. **Environment interpolation:** allow only enumerated `${NAME}` paths and exact adapter environment allowlist references; reject unsupported/unexpanded references.
4. **Timezone metadata:** validate `project.timezone` as a non-empty installed IANA zone. No runtime timezone conversion/rendering is implied.
5. **Codespaces toolchain:** exact Python 3.13 verifier; active Java 25 and Java 21 additional installation; Maven 3.10.0 and Git LFS 3.8.1; Java and Git-LFS Dev Container features pinned. Python image digest and APT snapshot remain open.
6. **Repository hygiene:** root `.gitignore` excludes generated caches, virtual environments, build output and local publisher state.
7. **Smoke fixture:** Keycloak config and header explicitly identify a smoke-only project-specific fixture with a reserved invalid origin and dry-run; it cannot be mistaken for a deploy config.
8. **Provider contract:** provider values are metadata labels only. `provider_label` is preferred; conflicting legacy/current aliases are rejected. No provider-specific adapter is claimed.
9. **Privacy contract:** `private_target_attested` is an operator assertion only, with a deprecated legacy alias. It does not prove endpoint ACL/privacy. Conflicting aliases and use outside security channels are rejected.
10. **Communication contract:** dynamic channel/query key names are constrained; global and component paths share the contract; query values are encoded; inactive and cross-channel fields are rejected.
11. **Historical evidence:** old P1/P2/P3/P11/P12 reports/test outputs moved unchanged to `audit/history/`; `STATUS.md` is now the only current status file.
12. **Audit update:** F01–F20 status file, 239-option matrix, 258 schema/dynamic coverage rows, and complete 28,441-pair matrix refreshed. Direct relationships include C01–C60 plus 14 F09–F11 contracts.

## Verification

The current verified suite is 232 main tests passing, one skipped Git-LFS transfer, and six process tests passing in three independent Linux runs with ResourceWarning treated as error. Static compilation, shell syntax, JSON Schema meta-validation, CLI version, smoke `validate-config`, and keycloak `plan` were also successful. External GitHub/Codespaces, Windows, real Git-LFS, browser/editor and provider ACL acceptance remain open.
