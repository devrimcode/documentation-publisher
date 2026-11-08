# Documentation Publisher 2.0.10-dev — kumulativer Projektstand P11

**Stand:** 7. November 2026  
**Pakettyp:** vollständiges Projektarchiv / direkt testbarer Codespaces-Testkandidat mit Quellcode, Regressionstests, Umgebungsskript, Dokumentation und Auditnachweisen  
**Freigabestatus:** nicht als produktionsfreigegeben einzustufen; offene Integrations- und Konfigurationsabnahmen sind unten ausdrücklich ausgewiesen.

## 1. Wichtige Provenienz- und Rekonstruktionsangabe

Die früheren vollständigen P4–P10-Projektarchive bzw. kumulativen P4–P10-Quellpatches waren in der verfügbaren Ablage nicht vorhanden. Verfügbar war das vollständige P3-Projektarchiv. Dieses Paket wurde deshalb **nicht** aus einem nicht vorhandenen P10-Arbeitsbaum weitergeschrieben.

Stattdessen wurde der bytegenau identifizierte P3-Projektstand frisch entpackt und die P4–P11-Korrekturen anhand der dokumentierten Defekte neu implementiert und mit neu aufgenommenen Tests belegt. Die Änderungen sind in diesem Paket vollständig enthalten. Sie sind jedoch **keine byteidentische Wiederherstellung der seinerzeitigen P4–P10-Zwischenstände**. Wo diese Unterscheidung für die Nachvollziehbarkeit relevant ist, wird sie in diesem Bericht offengelegt.

P3-Basisarchiv:

- Datei: `documentation-publisher-v2-r8-corrected-2.0.10-dev-P3-full-project.zip`
- SHA-256: `afea9b8d4c0707bdd0d677745ae881c80b782110749923b48e770f5becd52fcc`
- Frisch entpackte Baseline: **168 Tests bestanden**.

Es wurde keine Änderung am GitHub-Remote, am Keycloak-Upstream oder am Codespace des Nutzers vorgenommen. Es gab keinen Commit, Push oder Deploy.

## 2. Enthaltener kumulativer Korrekturumfang

| Korrektur | Enthaltene Änderung | Nachweis im Paket |
|---|---|---|
| P1 | Validierungsschalter unabhängig voneinander ausführen; URL-Schemes weiterhin aktiv sperren | P1-Tests und P3-Baseline-Suite |
| P2 | Meta-Refresh-URLs in Scheme-/Host-/Pfad-/Fragmentvalidierung aufnehmen | `tests/test_p2_meta_refresh.py`; P3-Baseline-Suite |
| P3 | Deploy-Entscheidung als Job-Output des Build-Jobs exportieren | `tests/test_p3_workflow_deploy_output.py`; P3-Baseline-Suite |
| P4 | `workflow.environment` auch dem `validate-config`-Workflow-Schritt zuführen; Secret-Export getrennt halten | `tests/test_p4_p5_workflow.py` |
| P5 | `triggers.paths` für Push und Pull Request korrekt abbilden; negative-only Filter als `paths-ignore`; ungültige Triggerkombinationen ablehnen | `tests/test_p4_p5_workflow.py` |
| P6 | Finales Build-Manifest vor abschließender Site-Validierung schreiben; Manifest in `max_files`/`max_site_bytes` einrechnen; erforderliche Manifestdatei konsistent bereitstellen | `tests/test_p6_p7_manifest_cleanup.py` |
| P7 | `workspace.fail_on_cleanup_error` unabhängig von `cleanup_on_success` durchsetzen; nicht fataler Cleanup-Fehler wird im Manifest vermerkt | `tests/test_p6_p7_manifest_cleanup.py` |
| P8 / R8-017 | Git-LFS-Include-Filter auf source-relative Pfade umstellen, nicht auf den Zielpräfix im Publisher-Repository | `tests/test_p8_git_lfs.py`; echter LFS-Transfer ist noch nicht abgenommen (siehe Abschnitt 4) |
| P9 / R8-019 | Gemeinsame Build-Plan-Auflösung für CLI-`plan` und Build; Komponentenabhängigkeiten, transitive Task-Abhängigkeiten und erforderliche Sources übereinstimmend auflösen | `tests/test_p9_plan.py` |
| P10 / R8-021 | ZIP-Central-Directory vor `ZipInfo`-Materialisierung begrenzt vorprüfen; EOCD, Kommentare, SFX-Präfix und ZIP64 abdecken | `tests/test_p10_zip_preflight.py` |
| P11 / R8-022 | Subprocess-Ausgaben inkrementell drainen und nur begrenzte stdout/stderr-Tails behalten; bei Timeout POSIX-Prozessgruppe stoppen und Child reapen; Windows-Tree-Kill-Pfad implementiert | `publisher_engine/process.py`; `tests/test_process.py` |

## 3. Regression und reproduzierbare Prüfungen

### Vollständige Regression

Ausgeführt im rekonstruierten P11-Projektstand:

```text
209 passed, 1 skipped, 53 subtests passed
```

Es gab **keinen fehlgeschlagenen Test**. Der aktuelle, nach der Dockerfile-basierten R8-027-Änderung geprüfte Stand wurde in zwei getrennten Läufen geprüft: 203 Tests plus 1 Skip in der Hauptsuite und danach 6/6 Tests für den Subprocess-Prozessgruppenblock. Aggregiert sind das **209 bestanden, 1 übersprungen, 0 fehlgeschlagen**. Die genauen Kommandos und Ergebnisse stehen in `audit/evidence/P11-CURRENT-COMPLETE-REGRESSION-209-PASS.txt`; die 9 gezielten aktiven Dev-Container-Tests sind in `audit/evidence/R8-027-DEVCONTAINER-TESTS.txt` dokumentiert. Der eine Skip ist der echte Git-LFS-Objekttransfer: Der reale Client-/Server-Transferfixture ist noch nicht vorhanden. Die source-relative Argumenttests für LFS bestehen.

### Codespaces-Prüfskript

`TEST-IN-CODESPACES.md` beschreibt die isolierte Testausführung im tatsächlichen Codespace. `scripts/test-in-codespaces.sh` startet zunächst die Toolchain-/CLI-/Konfigurationsprüfung über `scripts/codespaces_acceptance.py` und führt danach die Hauptsuite sowie die Prozessgruppen-Suite direkt und getrennt aus. Die Testausgaben werden in `test-results/` protokolliert. Der aktuelle lokale Linux-Host-Harness-Lauf liegt unter `audit/evidence/R8-027-LOCAL-HOST-ACCEPTANCE-CURRENT.txt`. Er meldet zwei erwartete Host-Blockaden: Maven und Git LFS fehlen außerhalb eines gebauten Dev Containers. Git, Subtree, Java 21, Python-Dependencies, Kompilierung, CLI, Keycloak-Konfigurationsvalidierung und Komponentenplan bestehen. Der aktuelle Regressionstand mit 209 bestandenen Tests ist separat im oben genannten P11-209-Protokoll dokumentiert. Dies ist **kein** Live-Test des Nutzer-Codespace. Die Dockerfile-/Feature-Provisionierung muss im echten Codespace bestätigt werden.

### P4–P11 gezielte Tests

| Bereich | Ergebnis |
|---|---:|
| P4–P5 Workflow Env/Path Filter | 9/9 bestanden |
| P6–P7 Manifest/Cleanup | 6/6 bestanden |
| P8 Git-LFS-Filter | 2 bestanden, 1 übersprungen |
| P9 Plan/Build-Parität | 4/4 bestanden |
| P10 ZIP-Preflight | 7/7 bestanden |
| P11 Subprocess-Sicherheit | 6/6 bestanden (inkl. zusätzlichem Pipe-Close-Test) |

Zusammen waren es zunächst 34 neu hinzugefügte P4–P11-Tests. Der neue P11-Test zum Schließen der Pipe-Handles ergänzt diese Abdeckung um einen weiteren Test. Der echte LFS-Transfer bleibt der einzige übersprungene Test.

### Differential- und Baseline-Nachweise

Die neuen Tests wurden teilweise auf einer frischen, unveränderten P3-Baseline ausgeführt. Dort schlugen 8 der 15 P4–P7-Tests mit den erwarteten Fehlerbildern fehl; 7 Kontroll-/Negativtests bestanden bereits. Zusätzliche P8–P11-Probes auf P3 dokumentieren:

- falsches Git-LFS-Include `vendor/generated-docs/**` statt Source-Pfad `manuals/en/**`;
- Plan-Ausgabe ohne Dependency-Closure und mit ungenutzter Source;
- ZIP-`infolist()`-Materialisierung vor `max_files`-Grenzprüfung;
- vollständige Pufferung von jeweils 4 MiB stdout und stderr sowie Überleben eines Nachfahrenprozesses nach Parent-Timeout.

Die exakten Protokolle liegen unter `audit/evidence/`.

### CLI-/Konfigurationsprüfung

- Python-Bytecode-Kompilierung von `publisher_engine/*.py` und `tests/*.py`: bestanden.
- CLI-Version: `2.0.10-dev`.
- `publisher.keycloak.smoke.yml`: `validate-config` erfolgreich (1 Source, 1 Component, 1 Task).
- CLI-`plan` für `keycloak-docs`: wählt genau `keycloak-docs`, die Source `keycloak` und Task `build-keycloak-docs`.
- Produktionscode-Scan: keine direkten `subprocess.run`, `capture_output=True` oder direkten stdout/stderr-Pipe-Aufrufe außerhalb des zentralen `publisher_engine/process.py` gefunden.

## 4. Offene Abnahmen und Grenzen

Dieses Archiv ist ein vollständiges Projektpaket. Das bedeutet nicht, dass jede externe Abnahme des gesamten R8-Audits abgeschlossen ist.

| Befund | Status nach diesem Paket | Noch erforderliche Abnahme |
|---|---|---|
| R8-009 Project-Pages `base_path` | Implementierung und lokale Fixtures vorhanden | Browser-Akzeptanz gegen einen tatsächlich bereitgestellten GitHub-Pages-Project-Pfad sowie Domain-/Custom-Canonical-Prüfung. Es wurde nicht deployed. |
| R8-011 Keycloak Authoring/Edit | Adapter und Fixture-Tests vorhanden; vorherige Quelldatei-/Commitprüfung ist als historische externe Evidenz dokumentiert | echter Upstream-Keycloak-Build mit anschließender Browser-/Editor-Akzeptanz; keine Änderung am Keycloak-Upstream vorgenommen |
| R8-017 Git LFS | source-relative Filterkorrektur vorhanden; Argumenttests bestanden | realer `git-lfs`-Client-Transfer gegen einen lokalen HTTP-LFS-Batch-/Object-Server; derzeit 1 Test übersprungen |
| R8-022 Subprocess | begrenztes Streaming, POSIX-Prozessgruppenabbruch und Schließen beider Pipe-Handles bei Timeout auf Linux getestet; 6/6 P11-Prozesstests | nativer Windows-Lauf zur Abnahme des `taskkill /T /F`-Pfades; unabhängige Peak-RSS-Messung bleibt ergänzend offen |
| R8-027 Codespaces/Devcontainer | aktive `.devcontainer/devcontainer.json` plus Dockerfile und Lifecycle-Skripte enthalten | tatsächlicher Codespaces-Rebuild und Git-Subtree-Discovery ohne manuell gesetzte Umgebungsvariable; nicht im Nutzer-Codespace ausgeführt |
| Konfigurations-Wirksamkeit insgesamt | vollständiges historisches Schema-Inventar mit 218 Property-Knoten / 191 Blattpfaden beigelegt; neue Defekttests ergänzt | Feld-für-Feld-Laufzeitmatrix und risikobasierte Interaktionsmatrix sind weiterhin nicht lückenlos abgenommen. Schema-/Enum-/Boolean-Akzeptanz ist kein Laufzeit-Wirksamkeitsnachweis. |
| GitHub Actions / Pages | generierte YAML lokal getestet und regressionsgeprüft | echter GitHub-Actions-Lauf, Artifact-Upload und Deployment wurden nicht ausgeführt |

### Befundübersicht der ursprünglichen 27 Auditpunkte

- **23 lokal behoben bzw. umgesetzt:** R8-001 bis R8-008, R8-010, R8-012 bis R8-016, R8-018 bis R8-026. R8-022 ist auf Linux lokal getestet; die Windows-Plattformabnahme ist separat offen.
- **4 mit externer oder weitergehender Abnahme offen/teilweise:** R8-009, R8-011, R8-017 und R8-027.

Die Zuordnung unterscheidet lokale Codekorrektur von externer Akzeptanz. Die Gesamt-Konfigurationswirksamkeit ist darüber hinaus nicht als vollständig bestätigt zu werten.

## 5. Nicht durchgeführt

- kein Commit, Push, Pull Request oder Deployment;
- keine Änderung des GitHub-Remotes und keine Änderung am Keycloak-Upstream;
- keine Änderung oder Rebuild des Nutzer-Codespaces; das neue Umgebungsskript wurde nur im hier verfügbaren Linux-Container ausgeführt;
- kein echter Git-LFS-Objekttransfer;
- keine native Windows-Ausführung;
- keine Browserakzeptanz auf einer produktiv bereitgestellten Pages-Site;
- keine vollständige Abnahme aller 191 Konfigurationsblattpfade und ihrer Interaktionen.

## 6. Paketinterpretation

Das Archiv enthält den vollständigen, ausführbaren Publisher-Projektbaum einschließlich Quellcode, JSON-Schema, Beispielkonfigurationen, Dokumentation, Tests und Auditnachweisen. Die P4–P11-Änderungen wurden aus dem verifizierten P3-Projektstand rekonstruiert und lokal regressionsgeprüft.

Es wird **nicht** als byteidentischer historischer P10-Stand, nicht als vollständig browser-/plattformabgenommener Release und nicht als Nachweis einer vollständigen 191-Felder-Konfigurationswirksamkeit ausgegeben. Es ist jetzt ausdrücklich mit `scripts/test-in-codespaces.sh` für einen isolierten Test im tatsächlichen Codespace vorbereitet; die dortige Ausführung ist noch nicht erfolgt.


## R8-027 correction – active Codespaces configuration

The previous test candidate contained only `.devcontainer/devcontainer.json.example`; that was not discovered automatically by GitHub Codespaces. The current package replaces it with the active `.devcontainer/devcontainer.json` plus `.devcontainer/Dockerfile`; the Dockerfile installs Git Subtree into the active Git exec path, while Dev Container Features install Java 25 plus Java 21, Maven and Git LFS. Lifecycle scripts run after creation and on subsequent starts. Static JSON/shell/configuration regression tests pass. The repository has not yet been rebuilt as an actual GitHub Codespace, so R8-027 remains externally unaccepted until that happens.


## R8-027 – aktive Codespaces-Konfiguration (Korrektur des vorherigen Kandidaten)

Der frühere Kandidat enthielt nur `.devcontainer/devcontainer.json.example`; diese Datei wird nicht als aktive Repository-Konfiguration ausgewählt. Im aktuellen Paket liegt stattdessen die echte Datei `.devcontainer/devcontainer.json` am Entdeckungspfad. Sie konfiguriert Python 3.13 (`3.13-bookworm`), Temurin JDK 25 (JDK 21 zusätzlich), Maven, Git LFS ohne Auto-Pull, die Dockerfile-basierte Installation von Git Subtree sowie `post-create.sh` und `verify-environment.sh`. Die Dateien befinden sich im Projektarchiv unter dem Root-Pfad `.devcontainer/`.

Die neuen Active-Configuration-/Dockerfile-Tests bestehen mit 9/9 (`audit/evidence/R8-027-DEVCONTAINER-TESTS.txt`). JSON-, Dockerfile-Static-Assertions, Shell-Syntax- und Python-Kompilierungsprüfungen bestehen. Ein synthetisches leeres Git-Repository wurde außerdem mit gemockten Java-/Maven-/Git-LFS-Kommandos durch `post-create.sh` und `verify-environment.sh` geführt; der Test bestand. Der echte Remote-Dev-Container-Build wurde nicht ausgeführt: Im aktuellen lokalen Runner fehlen Docker/Podman, Git LFS und Maven. Git LFS und Maven werden in der Codespaces-Umgebung über die Dev-Container-Features bereitgestellt; der endgültige R8-027-Nachweis muss nach Einpflegen dieses Ordners in das neue GitHub-Repository und Erstellen des Codespaces erfolgen.


### R8-027 – wichtiger Setup-Fix für das frisch angelegte GitHub-Repository

Der vorige P11-Kandidat war für den gewünschten Ablauf ungeeignet: Er enthielt nur eine
`devcontainer.json.example` und damit keine aktive Codespaces-Konfiguration. Der aktuelle
Ordner `.devcontainer/` enthält jetzt die aktive `devcontainer.json` sowie ein Dockerfile.
Die Git-Subtree-Installation liegt im Dockerfile und benötigt deshalb keine ausführbare lokale
Feature-Datei, wenn die Dateien vor dem ersten Codespace-Start über GitHub hochgeladen werden.
Der vollständige Ordner ist als separates Overlay-Archiv verfügbar. Der tatsächliche Build im
GitHub-Codespace muss nach dem Speichern im neuen Repository noch stattfinden.


## First configuration-safety correction group (working tree)

- Generic publisher/source example now requires explicit `PUBLISHER_ALLOWED_HOST` and `SOURCE_ALLOWED_HOST` values; wildcard host entries are rejected by semantic validation for repository and communication allowlists.
- `publishing.dry_run: false` rejects reserved example/test public origins in `site.base_url` and `site.canonical_base_url`.
- The project-specific Keycloak configuration is renamed to `publisher.keycloak.smoke.yml` and explicitly documented as smoke-only.
- `.devcontainer/verify-environment.sh` now requires Python 3.13, active Java 25 and an installed Java 21 SDKMAN candidate.
- Root `.gitignore` covers Python/test caches, virtual environments and Publisher-generated outputs.

This section describes source changes in the current working candidate. The next regression run and archive verification determine whether this group is accepted.


## R8-028 – Sicherheits- und Toolchain-Korrekturgruppe 1

**Status: IMPLEMENTIERT UND LOKAL REGRESSIONSGEPRÜFT.** Diese Korrekturen basieren auf dem tatsächlich wiederhergestellten P11-Archiv, nicht auf ungesicherten Zwischenmeldungen.

- Repository-/Source-/Communication-`allowed_hosts` lehnen Wildcards ab; Einträge müssen vollständige, syntaktisch gültige Hostnamen sein. Die generische Vorlage verwendet explizite Host-Platzhalter statt `*`.
- Live-Publishing (`publishing.dry_run: false`) lehnt reservierte Example-/Test-Domains einschließlich Subdomains und nicht-globale IP-Ursprünge ab. Dieselben reservierten URLs bleiben für ausdrücklich aktivierte Dry-Run-Smoke-Fixtures zulässig.
- `publisher.keycloak.example.yml` wurde in `publisher.keycloak.smoke.yml` umbenannt und im Datei-Header als projektbezogene Smoke-Fixture mit festen Repository-/Branch-Annahmen und reservierter `example.invalid`-Origin gekennzeichnet.
- Root-`.gitignore` deckt Python-/Pytest-Caches, virtuelle Umgebungen, Testresultate und Publisher-Arbeitsverzeichnisse ab.
- Dev-Container-Feature-Versionen sind festgesetzt (Java Feature 1.8.3, Git-LFS Feature 1.2.5; Temurin 25 aktiv plus 21, Maven 3.10.0, Git LFS 3.8.1). Der Verifier fordert exakte Versionen und weist insbesondere Java 21 als falsches Standard-Java zurück.
- Der Codespaces-Akzeptanzstarter prüft dieselben Versionen und hält die generische Vorlage als bewusst fail-closed fest.

Der tatsächliche Docker-/Codespaces-Neuaufbau ist nicht erfolgt; R8-027 bleibt extern offen. Der lokale Teststatus dieser Korrekturgruppe wird in `audit/R8-028-P1A-SECURITY-TOOLCHAIN-REPORT.md` und den `audit/evidence/R8-028-P1A-*`-Dateien belegt.

**Aktueller Regressionstand:** Hauptsuite 218 bestanden / 1 übersprungen / 73 Subtests; Prozesssuite separat 6/6 bestanden; gezielte Korrekturgruppe 48/48 bestanden. Aggregiert: **224 bestanden, 1 übersprungen, 0 fehlgeschlagen** (der gezielte 48er-Lauf ist eine Teilmenge der Hauptsuite, nicht zusätzlich zu zählen). Der Skip ist der echte Git-LFS-Objekttransfer.

