# Historischer Audit- und Phasen-Nachweisindex

Dieses Verzeichnis trennt aktuelle Projektaussagen von früheren Phasenständen.

- **Einziger aktueller Status:** `../STATUS.md`.
- **Verifizierte Parent-Basis und aktuelle Nachfolge:** `ARCHIVE-RECONCILIATION.md`; Workblock 07 ist der aktuelle lokale Nachfolger über Group 3 → Workblock 04 → Workblock 05 → Workblock 06 (superseded) → Workblock 07.
- **Archivregister:** `ARCHIVE-INVENTORY.csv` (61 Library-Archive zum Zeitpunkt der Bereinigung).
- **Aktuelle F01–F20-Matrix:** `R8-028/R8-028-GROUP-3-FINDING-STATUS.csv`.
- **Aktuelle Options-/Paar-/Schema-Matrizen:** `R8-028/input-matrices/` (Group 3: 250 nodes, 31,125 pairs).
- **Group-3-Parent-Nachweise:** `evidence/R8-028-GROUP-3-*`.
- **Workblock-04/05/06-Nachweise:** `R8-028/WORKBLOCK-04-*.md`, `R8-028/WORKBLOCK-05-*.md`, `R8-028/WORKBLOCK-06-*.md` und ihre jeweils benannten Nachweise. Workblock 06 ist nach dem tatsächlichen Codespaces-Buildfehler superseded.
- **Aktueller Workblock-07-Nachweis:** `R8-028/WORKBLOCK-07-*.md` plus `evidence/R8-028-WORKBLOCK-06-CODESPACES-REBUILD-FAILURE.md`.
- **Historische Phasenberichte und alte Statuszahlen:** `history/` sowie mit P1/P11/P12 gekennzeichnete alte Nachweise unter `evidence/`.

Die historischen Reports wurden unverändert in `history/` verschoben. Sie werden nicht mehr als aktuelle Statusquelle verlinkt.

**Archivregel:** P12 Group 1 ist der verifizierte Vorfahr; der reconciliierte Gruppen-3-Quellstand baut darauf auf. Workblock 04/05/06/07 sind isolierte lokale Nachfolger. Workblock 07 ist aktuell und korrigiert den durch echten Codespaces-Build widerlegten Workblock-06-Paketnamen. Die unveränderte Group-3- und Workblock-06-Basis bleibt als Provenienz erhalten; frühere Archivgenerationen sowie parallele Workblock-01-Artefakte dürfen nicht als aktuelle Basis verwendet werden. Jede neue Lieferung muss von diesem Stand abgeleitet, mit vollständiger Regression nachgewiesen und im Status samt Quellhash registriert werden.

- Root-level prior P1/P2/P3/P11/P12 reports were moved unchanged to `history/` to prevent current/historic status confusion.

Historical P11/P12 project file hash lists are retained with `HISTORICAL-ROOT-PATHS` in their filename because the reports were relocated under `audit/history/`; they are not the current project manifest.

- Current local remediation head: Workblock 07 (Git Subtree provisioning correction), derived through verified Group 3 and Workblocks 04/05/06; see `../STATUS.md` and `../CURRENT-SOURCE.md`.
- Group 2 input matrices were preserved under `history/R8-028-GROUP-2-matrices/` before Group 3 matrix expansion.
