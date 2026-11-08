# Audit-Unterlagen

## Maßgeblicher aktueller Stand

- `../STATUS.md` ist der **einzige aktuelle Projektstatus** für den hier enthaltenen Quellstand.
- `ARCHIVE-RECONCILIATION.md` legt die verifizierte Group-3-Elternbasis sowie die Workblock-04/05/06/07-Nachfolge fest.
- `ARCHIVE-INVENTORY.csv` erfasst die 61 zum Zeitpunkt der Archivbereinigung in der Library vorhandenen Archivobjekte.
- `R8-028/` enthält die R8-028-Code-/Konfigurationsmatrix, die F01–F20-Befundstatusdatei, die Options-/Paarmatrix, die Group-3-Berichte, Workblock 04/05/06/07/08/09/10-Berichte und die aktuelle Workblock-10-Korrektur samt Codespaces-Testplan.
- `evidence/` enthält Testprotokolle für den jeweils bezeichneten Quellstand. `R8-028-GROUP-3-*` dokumentiert den unveränderten Parent-Stand; Workblock 04/05/06/07/08/09/10-Nachweise sind getrennt gekennzeichnet. Das fehlgeschlagene Workblock-06-Rebuild-Protokoll ist ausdrücklich als Fehlernachweis, nicht als erfolgreiche Abnahme, geführt.

## Historische Unterlagen

- `history/` enthält frühere P1/P2/P3/P11/P12-Reports, Paketmanifeste und Testausgaben. Diese Dateien wurden unverändert aus dem Projektstamm verschoben und sind **keine aktuellen Testergebnisse**.
- `evidence/` enthält auch historische Patch-, Hash- und Testprotokolle. Historische Zahlen dürfen nicht mit `../STATUS.md` vermischt werden.
- `input/` enthält die ursprüngliche R8-Auditgrundlage. Sie ist als historische Eingabe erhalten und nicht der aktuelle Akzeptanzstatus.

## Codespaces

Der aktive Dev-Container liegt im Projektstamm unter `.devcontainer/`. Die lokale Prüfkette ist keine echte GitHub-Codespaces-Build-Abnahme. Dafür muss das Archiv in das vorgesehene Repository übernommen und ein neuer Codespace aus genau diesem Commit/Branch aufgebaut werden; erst danach ist `scripts/test-in-codespaces.sh` dort auszuführen.


The current source is Workblock 10, based on the byte-verified Workblock 09 source. Workblock 10 separates upstream Keycloak source provenance from the Publisher-repository edit target. Workblock 09 remains its immediate parent; Workblocks 07 and 08 remain preserved ancestry. See `../STATUS.md`; do not use historical Group 1/2 status or matrix files as current evidence.
