# R8 2.0.8-dev – technischer Auditbericht

**Auditgegenstand:** Publisher-Quellstand aus `R8-AUDIT-BUNDLE.tar.gz`  
**Paketversion:** `2.0.8-dev`  
**Konfigurationsstand:** enthaltene `publisher.yml`  
**Audit-Bundle SHA-256:** `dc6d4735a11050f59b25ea60813ac0b92bc2b5262506bf88947941db8f83ac79`  
**Auditumfang:** Python-Engine, JSON-Schema, Beispielkonfiguration, aktuelle Konfiguration, Tests, README, Testreport und Dokumentation.

## 1. Gesamturteil

**R8 2.0.8-dev ist nicht freigabefähig.** Der Quellabruf, der Maven-Build und die lokale Site-Erzeugung funktionieren im vom Benutzer ausgeführten Keycloak-Test. Die Implementierung weist jedoch reproduzierbare Sicherheits-, Konfigurations-, URL-, Workflow- und Funktionsintegrationslücken auf. Die vorhandenen 108 Tests bestehen, decken diese Fälle aber nicht hinreichend ab.

Das ist kein Widerspruch: Die Testsuite prüft vorhandene Testfälle. Sie beweist nicht, dass nicht getestete Konfigurationskombinationen sicher und semantisch korrekt sind.

### Verifizierte Prüfergebnisse

| Prüfung | Ergebnis |
|---|---:|
| Unittest-Suite | 108/108 bestanden |
| Python-Bytecode-Kompilierung | bestanden |
| CLI `--help` / `--version` | bestanden; Version `2.0.8-dev` |
| JSON-Schema-Metaschema-Prüfung | laut beiliegendem TEST-REPORT bestanden |
| Statement-Coverage laut TEST-REPORT | 79,3 % |
| Branch-Coverage laut TEST-REPORT | 65,4 % |
| Produktiver GitHub-Actions-Lauf | nicht durchgeführt |
| Git-LFS gegen echten LFS-Server | nicht durchgeführt; Tests sind Mock-basiert |
| Native Windows-Prüfung | nicht durchgeführt |
| Staging-/Produktiv-Publishing | nicht durchgeführt |
| Keycloak-Edit-Link gegen echte Editor-UI | nicht durchgeführt; im aktuellen Build nicht integriert |

Die Unittests wurden im Audit erneut ausgeführt: `python -m unittest discover -s tests -v` – 108 Tests, alle bestanden.

## 2. Umfang und Grenzen

Das Archiv enthält 27 Tar-Einträge (21 Dateien und 6 Verzeichnisse), insgesamt rund 350,6 kB entpackte Nutzdaten. Es enthielt keine Symlinks und keine unsicheren Tar-Pfade. Enthalten sind u. a.:

- `publisher_engine/{archive,cli,config,engine,gitops,links,workflow}.py`
- `schemas/publisher.schema.json`
- `publisher.example.yml` und die aktuelle `publisher.yml`
- `tests/test_engine.py`
- `README.md`, `TEST-REPORT.md`, `HARDENING-RELEASE-NOTES.md`
- die Dokumentation in `docs/`

Nicht enthalten waren das originale R8-ZIP-Archiv, `.publisher-sources` mit dem geklonten Keycloak-Quellcode und `_site-smoke` mit dem tatsächlich gebauten HTML. Daher wurde die bekannte SHA-256-Prüfsumme des ursprünglichen R8-ZIP nicht erneut verifiziert. Die nachfolgenden Codebefunde beziehen sich auf den hochgeladenen Quellstand; die reale Browserbeobachtung und Build-Ausgabe des Benutzers werden als externe Beobachtungen berücksichtigt, nicht als im Audit-Archiv selbst reproduzierte Browserprüfung.

## 3. Kritische und hohe Befunde

### R8-001 – Ausgabeziel kann einen versionierten Publisher-Codeordner zerstören

**Schweregrad:** Kritisch (P0)  
**Dateien:** `publisher_engine/engine.py` ca. Zeilen 865–869, 1028–1050; `docs/GIT-AND-SECURITY.md`  
**Reproduktion:** `site.output_directory: publisher_engine` besteht die semantische Validierung. Bei `--replace-output` akzeptiert der Build das bestehende Verzeichnis. Auch die Filesystem-Publishing-Zielprüfung schützt nicht allgemein vor einem existierenden getrackten Unterverzeichnis. Eine isolierte Reproduktion in einem temporären Testverzeichnis zeigte, dass `publisher_engine/important.py` durch die Ausgabe ersetzt werden kann.

**Auswirkung:** Ein Konfigurationsfehler kann Quellcode und Tests im Publisher-Repository löschen/überschreiben. Das widerspricht ausdrücklich der Dokumentationszusage, dass getrackte Quellverzeichnisse geschützt seien.

**Korrektur:** Vor Erzeugung und vor Ersetzung: Pfad gegen Git-Index (`git ls-files -z`) und gegen geschützte Projektpfade prüfen; nicht nur `.git` und Repository-Root. Für ein Outputziel unterhalb eines vorhandenen getrackten Pfades grundsätzlich verweigern, außer es existiert ein expliziter, eng begrenzter, separat bestätigter Allowlist-Mechanismus. Gleiche Regel für Filesystem-Publishing. Regressionstest muss sicherstellen, dass vorhandene Datei byte-identisch erhalten bleibt.

### R8-002 – Workspace kann innerhalb von `.git` angelegt werden

**Schweregrad:** Hoch (P1)  
**Datei:** `publisher_engine/engine.py` Zeilen 871–882; `publisher_engine/config.py` Pfadprüfungen  
**Reproduktion:** `workspace.temp_root: .git/objects/publisher-tmp` besteht die Konfigurationsprüfung und wird durch `mkdir` angelegt. Die `.git`-Schutzprüfung gilt nicht für diesen Workspace-Pfad.

**Auswirkung:** Temporäre Dateien können Git-Metadaten verunreinigen oder beschädigen. Das ist besonders kritisch, weil der Workspace den Publisher-Clone, Source-Subtrees und Build-Artefakte enthält.

**Korrektur:** Workspace-Pfad mit derselben Symlink-aufgelösten `.git`-Schutzlogik wie andere Repository-Pfade prüfen; keine Schreiboperation vor Abschluss dieser Prüfung. Absoluten Pfad außerhalb des Repositorys als Standard empfehlen.

### R8-003 – Aktive `data:`-URLs in HTML-Ressourcen werden nicht zuverlässig blockiert

**Schweregrad:** Hoch (P1)  
**Datei:** `publisher_engine/engine.py` Zeilen 375–400  
**Reproduktion:** `validate_site` akzeptierte `data:`-URLs in `iframe src`, `script src` und `object data`. Die Scheme-Prüfung verwirft nicht alle aktiven Schemes für alle URL-Attribute: die Allowlist-Prüfung ist aktuell auf `href` begrenzt und die explizite Verbotsliste deckt `javascript`, `vbscript`, `file`, aber nicht `data` umfassend ab.

**Auswirkung:** Eingebettete aktive Inhalte können eine veröffentlichte Site ausführen bzw. Inhalte aus Daten-URLs einbetten. Das ist nicht mit einer sicheren HTML-Validierung vereinbar.

**Korrektur:** Zentrale Tag-/Attribut-Scheme-Policy für alle URL-tragenden Attribute (`href`, `src`, `srcset`, `poster`, `data`, ggf. `action`, `formaction`, `xlink:href`, `srcdoc`) implementieren. `data:` grundsätzlich sperren oder auf klar definierte passive Bildtypen in erlaubten Attributen beschränken. `srcdoc` separat sanitizen/verbieten. Negativtests für `iframe`, `script`, `object`, `embed`, `link`, `img` ergänzen.

### R8-004 – Workflow ignoriert `publishing.dry_run: true`

**Schweregrad:** Hoch (P1)  
**Dateien:** `publisher_engine/engine.py` Zeilen 1182–1186; `publisher_engine/workflow.py` Zeilen 220–234  
**Reproduktion:** Workflow mit `publishing.dry_run: true` generiert weiterhin einen `deploy`-Job und den Schritt `Deploy validated artifact`. `dry_run` wird in `publish()` verwendet, aber nicht beim Workflow-Generator.

**Auswirkung:** Eine Konfiguration, die als Dry-Run verstanden wird, erzeugt weiterhin einen deployfähigen CI-Workflow. Ein Sicherheits-/Betriebsmodus wird nicht über die gesamte Ausführungskette durchgesetzt.

**Korrektur:** Semantik festlegen: Entweder `dry_run` verhindert Workflow-Deploy vollständig (kein Deploy-Job / Upload) oder Workflow-Generator erhält ein separates explizites Deploy-Opt-in. Default muss fail-closed sein. Tests für `dry_run=true/false`, alle Trigger und Job-Graph.

### R8-005 – Workflow-Umgebungsvariablen können reservierte Werte überschreiben und YAML-Duplikate erzeugen

**Schweregrad:** Hoch (P1)  
**Datei:** `publisher_engine/workflow.py` Zeilen 167–218  
**Reproduktion:** `workflow.environment` mit `CONFIG_FILE` erzeugt einen doppelten YAML-Key im Build-Step; strikter YAML-Parser lehnt das Dokument ab. `PATH` ist überschreibbar und kann die beim Build ausgeführten Tools auf einen anderen Suchpfad lenken. Weitere intern verwendete Variablen sind `SELECTED_COMPONENTS` und `PUBLISHER_REF`.

**Auswirkung:** Der Workflow kann ungültig sein oder seine vorgesehenen Eingabe-/Ausführungspfade können übersteuert werden.

**Korrektur:** Reservierte Liste für sämtliche vom Generator geschriebenen Keys einführen (`CONFIG_FILE`, `PATH`, `HOME`, `SELECTED_COMPONENTS`, `PUBLISHER_REF`, `GITHUB_ENV`, `GITHUB_OUTPUT` und weitere intern genutzte Variablen). Kollisionen vor YAML-Erzeugung ablehnen. Alle generierten YAML-Dokumente im Test streng parsen und gezielt jede reservierte Variable prüfen.

### R8-006 – Konfigurierbare Workflow-Berechtigungen dürfen über das dokumentierte Minimum hinaus eskalieren

**Schweregrad:** Hoch (P1)  
**Datei:** `publisher_engine/workflow.py` Zeilen 59–77 und 171–172  
**Reproduktion:** `workflow.build_permissions.contents: write` wird akzeptiert, obwohl die Dokumentation `contents: read` für den Build-Job zusagt. Andere gültige GitHub-Permission-Namen lassen sich ebenfalls zusätzlich hinzufügen; der Validator prüft Mindestwerte, nicht einen maximal erlaubten Satz.

**Auswirkung:** Build-Code läuft mit mehr Token-Rechten, als die Dokumentation erwarten lässt. Da Build-Tasks ausdrücklich nicht sandboxed sind, ist das ein wesentlicher Supply-Chain-Risikofaktor.

**Korrektur:** Build-Permissions hart auf minimalen Satz begrenzen (`contents: read` oder `none`, soweit benötigt) und unbekannte/zusätzliche Rechte verweigern. Deploy-Permissions ebenfalls auf eine dokumentierte Allowlist beschränken. Permission-Matrix als feste Regressionstests.

### R8-007 – Checkout-Credentials bleiben im Build-Job standardmäßig verfügbar

**Schweregrad:** Hoch (P1)  
**Datei:** `publisher_engine/workflow.py` Zeilen 181–182  
**Befund:** Der erzeugte `actions/checkout`-Schritt setzt `persist-credentials: false` nicht explizit. Die Checkout-Action persistiert ihre Authentifizierung standardmäßig in der lokalen Git-Konfiguration. Build-Tasks laufen anschließend mit Runner-Rechten und sind laut eigener Dokumentation nicht sandboxed.

**Auswirkung:** Ein kompromittierter oder nicht vertrauenswürdiger Build-Schritt kann unter Umständen das Checkout-Token aus der Arbeitskopie verwenden.

**Korrektur:** `persist-credentials: false` explizit setzen. Schreibzugriff für PR-Builds ausschließen und benötigte Lese-/Schreib-Credentials nur in separat kontrollierten Schritten mit minimaler Reichweite bereitstellen.

### R8-008 – Parent/Child-Komponentenrouten werden nicht gegeneinander geprüft

**Schweregrad:** Hoch (P1)  
**Datei:** `publisher_engine/config.py` Zeilen 553–584; `docs/CONFIGURATION.md` Zeile 46  
**Reproduktion:** Die Routen `keycloak` und `keycloak/server_admin` bestehen die semantische Validierung. Es wird auf identische gerenderte Pfade geprüft, nicht auf Parent/Child-Überlappungen zwischen Komponenten.

**Auswirkung:** Ausgabebäume kollidieren; Ergebnisse hängen von Kopierreihenfolge und Verzeichnis-/Dateistruktur ab. Dokumentation behauptet, Parent/Child-Überlappungen würden geprüft.

**Korrektur:** Für alle gerenderten Komponentenziele paarweise `overlaps()` anwenden, nicht nur für Static Assets und `not_found_path`. Vor Build mit aussagekräftiger Fehlermeldung abbrechen.

### R8-009 – GitHub-Pages `base_path` fehlt in Canonical- und Seiten-URLs

**Schweregrad:** Hoch (P1)  
**Datei:** `publisher_engine/engine.py` Zeilen 597–601 und 728–736  
**Reproduktion:** Bei `base_url=https://example.invalid` und `base_path=/keycloak-pages` wird für `docs/current/index.html` eine Canonical-URL ohne `/keycloak-pages` erzeugt. `page_url` wird ebenso ohne `base_path` gebildet.

**Auswirkung:** Canonical-URLs und Link-Template-Kontext zeigen auf falsche URLs bei Project Pages mit Repository-Unterpfad. Root-relative Site-Links können ebenfalls die Projektbasis umgehen.

**Korrektur:** Eine zentrale URL-Join-Funktion für `base_url + base_path + relative path` einsetzen; Canonical, `page_url`, hreflang, Navigation und Root-relative Rewrite aus derselben Funktion ableiten. Test mit Domain-Pages, Project-Pages, Custom-Domain und verschachtelten Konfigurationspfaden.

### R8-010 – `robots: noindex` wird nicht auf die gesamte veröffentlichte Site angewendet

**Schweregrad:** Hoch (P1)  
**Datei:** `publisher_engine/engine.py` Zeilen 596–613 und 636–643; Komponentenkopie 491–540  
**Befund:** Die `noindex`-Meta-Angabe wird für generierte Locale-/Version-Indizes geschrieben, aber nicht für den Root-Redirect und nicht in übernommene Komponenten-HTML-Dateien injiziert.

**Auswirkung:** Ein als `noindex` konfigurierter Build kann trotzdem indexierbare Root- und Inhaltsseiten ausliefern. Das ist eine fehlerhafte Datenschutz-/Preview-Einstellung.

**Korrektur:** `robots=noindex` muss global konsistent auf jede HTML-Seite einschließlich Root-Index, 404 und Komponenten angewendet werden; alternativ HTTP-Header/robots.txt-Strategie dokumentieren und die Meta-Konfiguration entfernen. Acceptance-Test auf jede erzeugte HTML-Datei.

### R8-011 – Keycloak-Authoring-Funktion wird vom aktuellen Build nicht erfasst

**Schweregrad:** Hoch (P1, funktionaler Release-Blocker)  
**Dateien:** `publisher_engine/links.py` Zeilen 113–180 und 282–297; `publisher_engine/engine.py` Zeilen 728–736; aktuelle `publisher.yml`  
**Befund:** Link-Rewriter verarbeitet nur explizite `data-publisher-link`- bzw. `publisher-link-*`-Marker. Der Keycloak-Header erzeugt normale AsciiDoc-/HTML-Links. Im aktuellen Build fehlen `authoring_targets`, die globale Einstellung ist `inherit`, und `link_summary` war `{}`. Die Upstream-Links bleiben daher unverändert.

**Auswirkung:** „Edit this section“ führt nicht in den vom Publisher konfigurierten Editor. Die lokale Site hat keine nachgewiesene, funktionierende Edit-Zuordnung. Der Link bleibt ein upstream `tree/main/docs/documentation/...`-Link (teilweise nur Verzeichnisansicht). Der Issue-Link bleibt der Keycloak-Issue-Formular-Link; der Server-Developer-Guide verweist weiterhin auf die externe DEV-Site.

**Korrektur:** Keycloak-spezifischen Adapter/Transformationsschritt implementieren. Er muss Source-Provenance je Seite/Sektion erzeugen, aus den AsciiDoc-Dateipfaden eine Markerstruktur bauen und die Ziel-URL gegen ein explizites authoring_target abbilden. Bei fehlender Provenance fail-closed. Interne Doc-Links kontrolliert lokal umschreiben; externe Issue-Links bewusst erhalten. Tests für Root-Guide, Topics, Included Sections, Anker, Release-Historie und falsche/fehlende Provenance.

### R8-012 – Komponenten-Override `inherit` übersteuert globale Edit-Override-Konfiguration

**Schweregrad:** Hoch (P1/P2)  
**Datei:** `publisher_engine/engine.py` Zeilen 728–730  
**Befund:** `component_overrides.get("edit", global_edit)` ersetzt die komplette globale Einstellung. Wenn eine Komponente explizit `edit: {mode: inherit}` enthält, überschattet dies einen späteren globalen `links.edit.mode: override`.

**Auswirkung:** Eine Änderung an der globalen Link-Konfiguration wirkt für diese Komponente nicht; dies ist insbesondere beim Beispiel- und aktuellen Konfigurationsmuster verwirrend.

**Korrektur:** Präzedenzregeln eindeutig dokumentieren und per Deep-Merge/tri-state semantics umsetzen. Standardmäßig keine redundanten Komponenten-Overrides erzeugen. Regressionstest: global override greift ohne expliziten Komponenten-Override; expliziter Komponenten-Override darf gezielt abweichen.

## 4. Weitere reproduzierte Korrekturbedarfe

### R8-013 – Leerer Komponenten-Output-Pfad wird nicht abgelehnt

**Schweregrad:** Mittel (P2)  
**Datei:** `publisher_engine/config.py` Zeilen 412–417  
`output_path` wird nur validiert, wenn truthy. Ein leerer String besteht diesen Teil der semantischen Prüfung, obwohl das Schema das Feld als erforderliche Zeichenkette aufführt. Später scheitert der Build. `minLength: 1` und eine unbedingte semantische Prüfung ergänzen.

### R8-014 – Fallback-Scheme-Prüfung widerspricht der zentralen Redirect-Allowlist

**Schweregrad:** Mittel (P2)  
**Datei:** `publisher_engine/config.py` Zeilen 430–433 versus `engine.py` Zeilen 553–557  
Bei `validate_redirect_schemes: [https]` akzeptiert die Config-Validierung einen HTTP-Fallback, den die Runtime später ablehnt. Beide Stellen müssen dieselbe normalisierte Allowlist verwenden.

### R8-015 – `publisher.ref`/Source-Refs werden nicht vollständig vor dem Clone validiert

**Schweregrad:** Mittel (P2)  
**Datei:** `publisher_engine/config.py` Zeilen 296–298, 374–375; `publisher_engine/gitops.py` Zeilen 48–83  
Die semantische Prüfung verwendet nur eine Teilmenge der Git-Ref-Regeln. Ein ungültiger Ref wie `bad?ref` passiert `validate-config` und wird erst im Git-Aufruf abgelehnt. Git-Ref-Validierung muss vor Netzwerk-/Clone-Aktionen für Publisher und Source identisch erfolgen.

### R8-016 – `file://`-Repository-URL umgeht die Host-Allowlist

**Schweregrad:** Mittel (P2)  
**Datei:** `publisher_engine/config.py` Zeilen 200–219  
`file:///...` ist als Repository-Scheme erlaubt. Da `_repository_host` für eine File-URL keinen Host liefert, greift `allowed_hosts: [github.com]` nicht. Lokale File-Remotes müssen explizit separat aktiviert werden; mit gesetztem `allowed_hosts` darf ein hostloses Scheme nicht stillschweigend passieren.

### R8-017 – Git LFS Include-Filter nutzt Publisher-Subtree-Prefix als Source-Pfad

**Schweregrad:** Mittel (P2; hoher Verdacht, Live-Akzeptanz noch offen)  
**Datei:** `publisher_engine/gitops.py` Zeilen 172–199  
Der Befehl `git lfs fetch --include={prefix}/**` setzt `prefix` auf den Publisher-Zielpfad (z. B. `.publisher-sources/keycloak`). LFS-Include-Muster beziehen sich auf Pfade im Source-Repository. Dadurch kann die Filterung reale LFS-Dateien im Source-Repo auslassen. Der Testreport bestätigt nur Mock-basierte LFS-Tests; ein echter LFS-Server wurde nicht benutzt.

**Korrektur:** Source-relative Includes statt Publisher-Zielpräfix verwenden; mit einem lokalen echten Git-LFS-Server/Fixture und mindestens einem LFS-Objekt beweisen, dass der Pointer durch das tatsächliche Objekt ersetzt wird.

### R8-018 – `keep_failed_workspace` verhindert auch Cleanup nach Erfolg

**Schweregrad:** Mittel (P2)  
**Datei:** `publisher_engine/engine.py` Zeilen 995–1000  
Das Flag `keep_failed_workspace` wird beim Success-Cleanup ebenfalls ausgewertet. Ist es `true`, bleibt auch der erfolgreiche Workspace erhalten – unabhängig von `keep_on_success`. Die Flags müssen orthogonal sein.

### R8-019 – `plan` bildet Abhängigkeitsauflösung und tatsächlich gewählte Tasks nicht korrekt ab

**Schweregrad:** Mittel (P2)  
**Datei:** `publisher_engine/cli.py` Zeilen 89–99; Build-Auflösung in `engine.py` Zeilen 855–862, 904–917  
`plan` listet alle Tasks und alle Sources, statt ausschließlich die nach Auswahl und Dependency-Closure tatsächlich auszuführenden Tasks/Sources. Build ergänzt Component-Dependencies. Dadurch kann Plan-Ausgabe unvollständig oder irreführend sein.

### R8-020 – HTML-Tiefenmessung zählt void-Elemente als verschachtelte Elemente

**Schweregrad:** Mittel (P2)  
**Datei:** `publisher_engine/engine.py` Zeilen 296–316  
Der Collector erhöht die Tiefe bei jedem Start-Tag und reduziert sie nur bei End-Tags. HTML-void-Elemente (`img`, `meta`, `link`, `br`, `input` etc.) haben kein End-Tag. Dadurch kann `max_html_depth` normale Seiten fälschlich ablehnen.

### R8-021 – ZIP-Entry-Limit wird erst nach dem Einlesen der gesamten Central Directory geprüft

**Schweregrad:** Mittel (P2)  
**Datei:** `publisher_engine/archive.py` Zeilen 43–46  
`ZipFile`/`infolist()` materialisieren zuerst die Liste aller Einträge; erst danach wird `max_files` geprüft. Das Dateianzahl-Limit begrenzt daher nicht den Speicherbedarf für sehr große ZIP-Central-Directories. Ein Vorab-/Streaming-Parser oder begrenzte ZIP-Metadaten-Verarbeitung ist erforderlich.

### R8-022 – Subprocess-Ausgaben werden vollständig gepuffert, obwohl nur ein Tail gespeichert wird

**Schweregrad:** Mittel (P2)  
**Dateien:** `publisher_engine/gitops.py` Zeilen 19–39; `engine.py` Zeilen 190–256 und 1235–1250  
Git, Task- und Publishing-Prozesse schreiben zunächst vollständig in `PIPE`; die Begrenzung auf die letzten Zeichen erfolgt erst nach Prozessende. Große Maven-Logs können daher den Speicherverbrauch stark erhöhen. Timeouts beenden zudem nicht nachweislich den ganzen Prozessbaum. Streamen in begrenzte Ringpuffer/Logdateien und Prozessgruppen-Kill ergänzen.

### R8-023 – Artifact-Adapter ist ein Status-/Handoff-Adapter, kein lokaler Artifact-Upload

**Schweregrad:** Mittel (P2, Dokumentations-/Vertragsklarheit)  
**Datei:** `publisher_engine/engine.py` Zeilen 1163–1191; `workflow.py` 155–158, 225–234  
`publish()` liefert bei `adapter: artifact` nur `planned`/`ready` samt Site-Pfad und Artifact-Name zurück. Das Erzeugen und Hochladen erfolgt erst im generierten GitHub-Pages-Workflow. `publishing_targets[].output_path` steuert diesen Artifact-Upload nicht; der Workflow leitet den Pfad von `site.output_directory` ab. Entweder Feld entfernen/validieren oder Gleichheit erzwingen und die Übergabe klar dokumentieren.

### R8-024 – `site.base_url` lässt Query/Fragment passieren

**Schweregrad:** Mittel (P2)  
**Datei:** `publisher_engine/config.py` Zeilen 266–272, 312–314  
Die URL-Prüfung wird mit `allow_path=True` aufgerufen und lehnt Query/Fragment nicht ab. Query-/Fragment-Anteile gehören nicht in den Site-Origin/Base-URL-Wert. Diese Eingabe wird akzeptiert und erzeugt fehlerhafte Canonical-/Link-URLs.

### R8-025 – `project.robots=noindex` und Projektmetadaten haben unklare Wirksamkeit

**Schweregrad:** Mittel (P2)  
**Dateien:** Schema `project` und `engine.py` Index-Erzeugung  
`project.timezone`, `license`, `copyright` und `maintainers` sind im Schema zugelassen, werden im Engine-Code aber nicht in Site/Manifest/Navigation gerendert. `repository_url`, `homepage_url`, `logo`, `favicon` und `description` werden teilweise genutzt. Nicht genutzte Felder müssen entweder implementiert oder ausdrücklich als reine Metadaten ohne Site-Auswirkung dokumentiert werden.

### R8-026 – `validate_external_links` ist keine allgemeine Reachability-Prüfung

**Schweregrad:** Mittel (P2, Semantik/Benennung)  
**Datei:** `publisher_engine/engine.py` Zeilen 386–394 und CSS-Validierung  
Die Prüfung kann externe Hosts gegen eine Allowlist bewerten; sie führt nicht standardmäßig einen echten DNS-/HTTP-Status-/Reachability-Check durch. Die Option und Dokumentation müssen präzise benennen, was kontrolliert wird. Kein Build sollte allein wegen eines scheinbar aktivierten Checks als „alle externen Links erreichbar“ abgenommen werden.

### R8-027 – Codespaces-Preflight für `git subtree` ist unzureichend dokumentiert

**Datei:** `publisher_engine/gitops.py` Zeilen 42–45; `README.md`/Runbook  
Der Benutzer musste nachweisen und setzen, dass Git die Extension über `GIT_EXEC_PATH=/usr/lib/git-core` findet. Die bloße Aussage „git-subtree installieren“ reicht in Codespaces nicht aus. `ensure_git_subtree()` hat keinen Timeout und die Diagnose nennt den tatsächlich geprüften Git-Exec-Pfad nicht.

## 5. Funktions- und Konfigurationsinventar

Die folgende Matrix deckt alle Top-Level-Blöcke des JSON-Schemas ab. Sie ist eine Funktionsbewertung des geprüften Codes, keine Behauptung, jede mögliche Wertkombination sei bereits in Live-Umgebungen getestet.

| Konfigurationsblock | Felder/Optionen | Auditstatus |
|---|---|---|
| `schema_version` | Version 2 | Validiert. |
| `active_profiles`, `profiles` | Profil-Auswahl, Mapping-Merge, Listenersetzung | Implementiert und mit Tests abgedeckt; Konfigurationsprofile müssen für sämtliche Kombinationen zusätzlich validiert werden. |
| `project` | `id`, `title`, `description`, `locale`, `timezone`, `license`, `copyright`, `logo`, `favicon`, `homepage_url`, `repository_url`, `maintainers` | Teilweise gerendert; mehrere Felder werden angenommen, aber nicht sichtbar verwendet (R8-025). |
| `publisher` | `clone_url`, `ref`, `auth.mode` (`none`, `environment`, `ssh_agent`), `secret_env`, `username_env`, `allowed_hosts`, `clone_timeout_seconds` | Git-Klon/Auth-Mechanik vorhanden; Ref-Validierung ist unvollständig (R8-015); `file://` kann Host-Allowlist umgehen (R8-016). |
| `sources[]` | `id`, `vcs.provider`, `clone_url`, `default_ref`, `ref_type`, `depth`, `submodules`, `lfs`, `sparse_paths`, `allowed_hosts`, `auth`, `root`, `integration.mode`, `prefix`, `squash`, `history` | Git-Subtree implementiert; Submodules und Sparse Paths werden bewusst abgelehnt; LFS nur Mock-getestet und Filterverdacht (R8-017). Ref-/File-URL-Prüfung ergänzen. |
| `authoring_targets[]` | `id`, `provider`, `web_url`, `repository`, `ref`, `ref_type`, `edit_url_template`, `source_id`, `mapping.source_prefix`, `target_prefix`, `rules`, `unresolved_policy` | Generische URL-Template-Mechanik vorhanden; `provider` ist keine echte provider-spezifische Implementierung. Live-Editorprüfung ist zwingend. Keycloak-Marker/Provenance fehlen im aktuellen Build (R8-011). Ref-Regeln für branch/tag vollständig validieren. |
| `build_tasks[]` | `id`, `source_id`, `adapter=command`, `working_directory`, `working_directory_scope`, `argv`, `environment`, `pass_environment`, `secret_environment`, `depends_on`, `timeout_seconds`, `retry`, `retry_safe`, `retry_delay_seconds`, `outputs` | Kommando-Tasks, Allowlist, Secret-Redaction, Retries, Timeouts und Dependency-Graph vorhanden; keine OS-Sandbox. Große Prozessausgaben und Prozessgruppen-Timeouts verbessern (R8-022). |
| `components[]` | `id`, `title`, `description`, `source_id`, `route`, `tasks`, `output_path`, `output_kind` (`directory`,`file`,`zip`,`tar`), `index_file`, `required_output_files`, `archive_root`, `fallback`, `dependencies`, `locale`, `version`, `provenance_file`, `link_overrides` | Grundfunktion vorhanden. Leerer `output_path` (R8-013), Parent/Child-Routen (R8-008), Link-Override-Precedence (R8-012) und Index-Datei-Vertrag müssen nachgeschärft werden. |
| `site` | `base_url`, `base_path`, `output_directory`, `components_root`, `version`, `default_component`, `generate_index`, `robots`, `canonical_base_url`, `locales`, `versions`, `navigation`, `static_assets`, `component_path_template`, `version_index_path_template`, `default_locale`, `default_version`, `root_index_target`, `trailing_slash`, `not_found_path` | Site-/Version-/Locale-Routing vorhanden, aber Base-Path für URLs fehlerhaft (R8-009); noindex unvollständig (R8-010); Base-URL-Query/Fragment (R8-024); Track-Datei-Schutz für Output fehlt (R8-001). |
| `links.edit` | `mode` (`inherit`,`override`,`disable`), `target_id`, `unresolved_policy`, `require_markers` | Marker-basiert; ohne Marker findet keine automatische Umwandlung statt. Global/Component-Precedence korrigieren (R8-012). |
| `communication.*` | `mode`, `provider`, `url_template`, `address`, `cc`, `bcc`, `subject`, `body`, `target`, `query`, `require_markers`, `private_target`, `allowed_hosts` | Generische Marker-/Template-Funktion; Anbieter-URLs und private Zielkonfigurationen müssen live geprüft werden. |
| `validation` | `require_no_symlinks`, `validate_local_links`, `validate_fragments`, `validate_css_assets`, `validate_edit_links`, `validate_communication_links`, `max_site_bytes`, `max_files`, `required_files`, `allowed_external_hosts`, `unresolved_edit_policy`, `validate_external_links`, `validate_redirect_schemes`, `require_build_manifest`, `max_archive_ratio`, `max_html_depth` | Mehrere Prüfungen vorhanden. Daten-Schemes fehlen (R8-003), HTML-Tiefenzählung falsch (R8-020), `validate_external_links` missverständlich (R8-026), Fallback-Scheme-Konflikt (R8-014). |
| `workspace` | `temp_root`, `keep_failed_workspace`, `cleanup_on_success`, `cleanup_on_failure`, `fail_on_cleanup_error`, `cleanup_retries`, `lock_timeout_seconds`, `git_user_name`, `git_user_email`, `keep_on_success`, `cleanup_delay_seconds` | Lock/Cleanup vorhanden; `.git`-Schutz fehlt für `temp_root` (R8-002); `keep_failed_workspace` beeinflusst Erfolg (R8-018). |
| `publishing_targets[]` | `id`, `adapter` (`artifact`,`filesystem`,`command`), `output_path`, `argv`, `environment`, `pass_environment`, `secret_environment`, `timeout_seconds`, `allow_external_destination`, `replace_existing` | Filesystem atomic/non-atomic, command und artifact handoff vorhanden; Schutz gegen getrackte Unterverzeichnisse fehlt (R8-001); artifact `output_path` uneindeutig (R8-023). |
| `publishing` | `target_id`, `artifact_name`, `retention_days`, `dry_run`, `atomic`, `pre_publish_validation`, `timeout_seconds` | Lokaler Publish-Pfad berücksichtigt Dry-Run, aber Workflow-Generator ignoriert es (R8-004). |
| `triggers` | `manual`, `push_branches`, `pull_request`, `schedule`, `workflow_call`, `paths`, `concurrency_group`, `cancel_in_progress`, `deploy_branch` | GitHub-Actions-Trigger-Generator vorhanden; Live-CI-/Branch-Protection-Integration noch offen. |
| `workflow` | `provider=github_actions`, `file`, `python_version`, `actions`, `config_file`, `runs_on`, `deploy_environment`, `build_timeout_minutes`, `deploy_timeout_minutes`, `secrets`, `environment`, `include_hidden_files`, `deploy_permissions`, `build_permissions` | GitHub Actions only. Reservierte Env-Kollisionen (R8-005), Permission-Eskalation (R8-006), Checkout-Persistenz (R8-007), Dry-Run (R8-004) korrigieren. |

## 6. Nicht automatisch unterstützte oder nicht nachgewiesene Optionen

- `sources[].vcs.submodules: true`: wird bewusst verweigert; keine rekursive Submodule-Materialisierung.
- `sources[].vcs.sparse_paths`: wird bewusst verweigert; kein Sparse-Checkout-Adapter.
- `git-lfs`: nur Mock-Lifecycle-Test; kein echter LFS-Akzeptanzlauf.
- `authoring_targets.provider`: keine automatische provider-spezifische Editor-Implementierung; die URL-Template-Mechanik muss durch echte Provider-UI geprüft werden.
- `publishing_targets.adapter: artifact`: meldet Ready/Planned bzw. überlässt Upload an den GitHub-Pages-Workflow; CLI erzeugt nicht selbst ein herunterladbares Artefakt.
- CI außerhalb GitHub Actions und Publishing außerhalb der unterstützten Adapter sind nicht implementiert.
- Build-Aufgaben sind vertrauenswürdiger Runner-Code, keine isolierte Sandbox.

## 7. Dokumentationswidersprüche

| Dokumentaussage | Tatsächlicher Befund |
|---|---|
| `docs/GIT-AND-SECURITY.md`: Output darf kein getracktes Source-Verzeichnis treffen | `publisher_engine` kann als Output akzeptiert und ersetzt werden (R8-001). |
| `docs/GIT-AND-SECURITY.md`: Repository-Pfade schützen `.git` | `workspace.temp_root` kann unter `.git` liegen (R8-002). |
| `docs/CONFIGURATION.md`: Komponentenrouten und Indizes werden gegen Parent/Child-Overlaps geprüft | Component-Component Parent/Child wird nicht geprüft (R8-008). |
| `docs/CI-AND-PUBLISHING.md`: Build-Job hat read-only contents | `contents: write` ist in `workflow.build_permissions` möglich (R8-006). |
| Link-Doku: Edit-Link öffnet konfigurierte Editor-URL | Nur mit expliziten Markern und gültiger Provenance. Der aktuelle Keycloak-Build hat keine Marker und `link_summary: {}` (R8-011). |

## 8. Erforderliche Freigabegates

R8 bleibt gesperrt, bis alle P0/P1-Korrekturen, alle P2-Konfigurationskorrekturen und die nachfolgenden Akzeptanztests bestanden sind. Der vollständige Korrekturplan steht in `R8-CORRECTION-PLAN.md`; die Feldinventarliste in `R8-CONFIGURATION-MATRIX.md`.

**Keine Dateien im Codespace oder GitHub wurden durch dieses Audit verändert.** Die erzeugten Auditberichte liegen ausschließlich als neue Dateien im Chat-Sandbox-Bereich.
