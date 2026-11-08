# Documentation Publisher 2.0.10-dev — Konfigurations-Wirksamkeitsprüfung

**Status: NICHT vollständig abgenommen / NICHT release-ready**  
Prüfdatum: 2026-11-06  
Prüfgegenstand: 2.0.10-dev R8-Korrekturpaket einschließlich des später ergänzten R8-027-Dev-Container-Add-ons.

## 1. Ergebnis in einem Satz

Die vorhandene Suite und mehrere reale Integrationspfade funktionieren; eine vollständige Bestätigung, dass *jede* unterstützte Konfigurationsoption in *jeder* Kombination greift, ist mit dem aktuellen Teststand ausdrücklich **nicht** erbracht.

Ein Konfigurationsschema bestätigt zunächst nur, dass ein Wert formal zulässig ist. Für einen Wirksamkeitsnachweis muss der Wert bis zur richtigen Laufzeitphase durchlaufen und das erwartete beobachtbare Verhalten auslösen. Build, Publish und Workflow-Generierung sind getrennte Phasen und dürfen nicht als gegenseitiger Nachweis gezählt werden.

## 2. Tatsächlich ausgeführte Prüfungen

| Prüfung | Ergebnis | Was sie belegt – und was nicht |
|---|---:|---|
| Gesamte Testsuite des isolierten 2.0.10-dev-R8-027-Pakets | **142/142 bestanden** | Bestehende Unit-, Regression- und Integrations-Fixtures bestehen. Das beweist nicht alle Werte aller Konfigurationsfelder. |
| Python-Produktcode-Line-Coverage (`coverage --source=publisher_engine --branch`) | **76,1 %** | Rund ein Viertel der ausführbaren Produktcodezeilen wurde in dieser Suite nicht ausgeführt. |
| Python-Produktcode-Branch-Coverage | **67,5 %** | Rund ein Drittel der gezählten Verzweigungen wurde nicht ausgeführt. Dies ist ein klarer Hinweis gegen eine Behauptung vollständiger Konfigurationsabdeckung. |
| Separate Schema-/Semantic-Enum-Sweep-Prüfung | **39/39 akzeptiert** | Alle dabei mutierten Enum-Werte wurden von Schema und semantischer Validierung angenommen. Die Sweep-Prüfung führte die jeweiligen Features nicht aus. |
| Boolean-Sweep (31 boolesche Felder, beide Werte) | **62/62 erwartungsgemäß** | Alle Werte wurden schema-/semantisch korrekt angenommen oder bewusst abgelehnt (`submodules=true`, `require_no_symlinks=false`). Das ist kein Laufzeit-Wirksamkeitstest. |
| Keycloak-Smoke-Build im Nutzer-Codespace | **success** | Quelle wurde integriert, Maven-Task lief 110,005 s, Site mit 438 Dateien / 37.892.553 Bytes erzeugt. |
| Keycloak-Edit-Link-Ergebnis | **362 Vorkommen / 359 eindeutige Ziele** | Alle 359 unterschiedlichen Zielpfade wurden im Git-Baum des Quell-Commits `30cf683465a1ddf7151462d7f480d6d17f986844` gefunden. Das beweist Dateiexistenz und die Link-Mapping-Kette, nicht den Browser-Editor oder sämtliche anderen Link-Modi. |
| Base-Path-Beobachtung aus Nutzer-Scan | **ein Canonical mit `/keycloak-pages`** | Belegt nur diesen gefundenen Canonical-Wert. Der damalige Scan fand keine root-relativen Attribute; er hat nicht alle relativen URL-Auflösungen und Ressourcentypen bewiesen. |

Die Coverage-Zahlen wurden frisch mit der im Paket enthaltenen Suite ermittelt. Enum- und Boolean-Sweeps waren zusätzliche, separat ausgeführte Schema-/Semantic-Validierungsprüfungen; sie beweisen ausdrücklich noch nicht die Laufzeitwirkung der jeweils geänderten Werte.

## 3. Wichtige Provenienzabweichung

Das im bereitgestellten 2.0.10-dev-R8-027-ZIP enthaltene `publisher.keycloak.example.yml` hat lokal SHA-256:

`1d29e783539afc4b04558b17f7714a868f02578dc247bcb36fef07f4c26bfc4c`

Der im tatsächlichen Codespace-Build ausgegebene Konfigurations-Hash war dagegen:

`3fb14985bfee70d9f4ffc67ebd2fa924a03d5df966ff181fcb1590ca2e6cab88`

Das sind **nicht dieselben Bytes**. Das vorbereitete Paket enthält daher nicht bytegenau die Konfigurationsdatei, mit der der Nutzer-Smoke-Build lief. Die Nutzer-Ausgabe belegt, dass die dortige Datei von `validate-config`, `plan` und `build` akzeptiert wurde; sie darf aber nicht mit der im ZIP liegenden Beispielkonfiguration gleichgesetzt werden.

## 4. Was das Keycloak-Profil tatsächlich ausgeübt hat

Die folgende Tabelle bezieht sich auf die vom Nutzer gepostete und im Build-Manifest gehashte Keycloak-Smoke-Konfiguration.

| Konfigurationsbereich | Im Keycloak-Build aktivierter Pfad | Nicht durch diesen Build geprüft |
|---|---|---|
| Publisher-Repository | Git-Clone/Ref, Host-Allowlist, Auth `none`, Clone-Timeout | Andere Auth-Modi, andere Ref-Typen, ungültige Hosts/Timeouts |
| Source-Repository | Git, Branch `main`, depth `1`, LFS aus, Submodules aus, Git-Subtree, shallow history, squash | LFS-Download, full history, depth `0`, Tags/Commit-SHA, Auth `environment`/`ssh_agent`; Submodules/sparse paths sind absichtlich nicht unterstützt |
| Build-Task | `command`, Maven-Wrapper-Argumente, Source-Working-Directory, Allowlist der Umgebungsvariablen, 3600-s-Timeout, keine Retries | Publisher-Working-Directory, mehrere abhängige Tasks, secret environment, Retry-Erfolg/Retry-Abbruch/Timeout-/Output-Fehlerfälle |
| Component | Ein Component, `directory`, Index `index.html`, ein erforderliches Output-File, Keycloak-Adapter, Version `current`, Locale `en` | File/ZIP/TAR als Component-Output, mehrere Components, Component-Dependencies, mehrere Versionen/Locales, Provenance-Datei, andere Fallback-Pfade |
| Edit-Link-Konfiguration | Global `override`, konkretes Authoring-Target, Mapping `docs/documentation`, Marker erforderlich, unresolved `fail`; 362 Vorkommen verarbeitet | Global `inherit`/`disable`, Component-Override/Disable, `omit`, alternative Mapping-Regeln, fehlende/inkonsistente Provenance im echten Keycloak-Ausgabeumfang |
| Communication | Alle Kanäle `inherit` | Kein Communication-Override- oder Disable-Pfad wurde durch dieses Profil ausgeübt |
| Site | Project-Site-Prefix `/keycloak-pages`, Canonical-Origin `example.invalid`, `generate_index=true`, `robots=noindex`, eine Locale und Version | Domain-Root ohne Prefix, Custom Canonical Origin, mehrere Locale/Version-Kombinationen, `generate_index=false`, Navigationseinträge, statische Assets, alternate root target, alternative trailing-slash-/404-Konfiguration |
| Validation | Lokale Links, Fragmente, CSS, Edit- und Communication-Link-Prüfung aktiviert; externe Link-Prüfung aus; Größenlimits gesetzt | Negativfälle jedes Schalters, externe Host-Allowlist-Modi, Größen-/Datei-/HTML-Tiefen-Grenzwerte und alle erlaubten/abgelehnten URL-Schemata |
| Workspace | temporäre Workspaces; Cleanup auf Erfolg/Fehler aktiviert; kein Retain auf Erfolg | alle Cleanup-/Retention-/Retry-/Lock-Konstellationen |
| Publishing | Artifact-Target konfiguriert, `dry_run=true` | **Publish wurde nicht aufgerufen**; damit sind Adapter-Ausführung, `atomic`, Replace-Verhalten, Publish-Timeout und `pre_publish_validation` nicht durch den Keycloak-Smoke-Build bewiesen |
| Workflow/Triggers | Im aktiven Keycloak-Profil nicht konfiguriert | **Workflow-Generierung wurde nicht ausgeführt**; Trigger, Action-SHAs, Build-/Deploy-Permissions, Secrets, Environment und Pages-Deployment sind nicht durch den Build bewiesen |

## 5. Schema-Inventar und Felder ohne normale Laufzeitwirkung

Das JSON-Schema enthält, nach Auflösung der wiederverwendeten `$defs`, **218 Schema-Property-Knoten und 191 Blattpfade**. Darunter befinden sich **31 boolesche Felder und 19 Enum-Felder**. Schon die 31 Boolean-Felder erlauben 2³¹ Wertkombinationen; mit den Enum-Entscheidungen wächst der naive Produkt-Raum auf etwa 1,6 × 10¹⁶ Kombinationen, noch ohne freie Strings, Zahlenbereiche und variable Listen. Das ist kein sinnvoll vollständig aufzählbarer Test-Raum; ein belastbarer Nachweis braucht deshalb Feld-für-Feld-, Grenzwert-, Negativ- und risikobasierte Paar-/Interaktionstests. Das vollständige Schema-Inventar liegt zusätzlich als CSV vor.

Folgende akzeptierte Felder sind laut Konfigurationsvertrag derzeit Metadaten und erzeugen keine entsprechende Site-Funktion:

- `project.timezone`
- `project.license`
- `project.copyright`
- `project.repository_url`
- `project.maintainers`

Sie werden nicht als vollständige Footer-, Lizenz- oder Maintainer-UI gerendert. `project.title`, `description`, `locale`, `logo`, `favicon` und `homepage_url` werden hingegen von der Index-/Manifest-Erzeugung verwendet.

Außerdem:

- `authoring_targets[].provider` und `communication.<channel>.provider` lösen keinen eigenen provider-spezifischen Adapter aus; die Verarbeitung läuft über die generischen URL-/Template-Verträge. Diese Felder dürfen nicht als Nachweis einer vollständigen GitHub-/GitLab-/sonstigen Provider-Integration verstanden werden.
- `sources[].vcs.submodules=true` wird semantisch abgelehnt.
- Nicht-leere `sources[].vcs.sparse_paths` werden semantisch abgelehnt.
- `sources[].vcs.provider` muss `git` sein; die Source-Integration unterstützt in v2 ausschließlich `git_subtree`.
- `validation.require_no_symlinks` muss `true` bleiben; `false` wird bewusst abgelehnt.
- `build_tasks[].adapter` unterstützt ausschließlich `command`.
- `workflow.provider` unterstützt aktuell ausschließlich `github_actions`.

Diese Felder sind also nicht alle „fehlende Tests“: manche sind absichtlich Metadaten oder bewusst nicht unterstützte Konfigurationen. Der Vertrag muss diese Unterscheidung klar erhalten.

## 6. Laufzeitphasen – welche Tests für einen echten Wirksamkeitsnachweis noch fehlen

### A. Config Load / Profile / Environment

- Jedes `active_profiles`-/`profiles`-Merge-Szenario inklusive Listen-Ersetzung, verschachteltem Mapping, unbekanntem Profil und inaktivem fehlerhaftem Profil.
- Environment-Interpolation pro ausdrücklich erlaubtem Feld; fehlende Variable, nicht erlaubtes Feld, leere Variable und Secret-Grenzen.
- YAML-Merge-Keys und doppelte explizite Keys mit Positiv- und Negativfällen.

### B. Git / Source / Auth

- Branch, Tag, Commit-SHA und Auto-Ref tatsächlich klonen/fetchen.
- Shallow versus Full History; `depth=0` versus positive Depth.
- `none`, Environment-Askpass und SSH-Agent mit erfolgreicher und fehlgeschlagener Authentifizierung.
- LFS mit echtem LFS-Objekt und Remote-Server-Fixture (R8-017 bleibt offen).
- Host-Allowlist, Local-Path, HTTPS/SSH und Ref-Fehler.
- `submodules=true` und `sparse_paths` als erwartete frühzeitige Ablehnung.

### C. Build-Task / Component Graph

- Source- und Publisher-Working-Directory.
- Task-Abhängigkeiten: lineare Kette, Verzweigung, Mehrfach-Abhängigkeit, unbekannte Abhängigkeit, Zyklus und selektive Component-Auswahl.
- Retry-Safe, Retry-Backoff, endgültiger Fehler, Timeout, Output-Glob und fehlendes Output.
- Directory/File/ZIP/TAR Component Outputs inklusive `archive_root`, Größenlimit, Dateilimit, Kompressionsverhältnis, Symlink und Traversal.
- Fallback `inherit`, `redirect`, `stub`, `omit`, `error`, einschließlich nicht ausgewählter Components und nested index file.
- Mehrere Components, locale/version Routing, dependency closure, duplicate/overlapping routes und mehrere Output-Kinds.

### D. Site / Routing / URL

- `base_path` leer, Root-Projektpfad und mehrfach verschachtelter Prefix.
- Alle HTML-/XHTML-/SVG-URL-Attribute, `srcset`, inline CSS, `<style>`, externe CSS-Dateien, `@import`, CSS `url()`, Meta-Refresh, Form- und Media-Ziele.
- Relative Links, root-relative Links, protocol-relative Links, externe Links, query strings, Fragmente, percent-encoded Pfade und bereits präfixierte Pfade.
- `canonical_base_url` leer/gesetzt, `base_url` Root-Origin, `trailing_slash` true/false.
- `generate_index` true/false; `root_index_target`; `not_found_path`; `robots=index/noindex`.
- Navigation label/href/group/order, static asset copy/source/destination, Symlinks und Overlap.
- Mehrsprachige und mehrere Versionen inklusive aller Index-Template-Pfade.

### E. Links / Communication

- Edit: `inherit`, `override`, `disable`; `require_markers` true/false; unresolved `fail`/`omit`; target mappings `source_prefix`/`target_prefix`/rules; source/ref/repository mismatch.
- Keycloak-Asciidoc-Adapter mit Topic-, Index-, Include- und mehreren verschachtelten Includes; unbekannte Label, Nicht-AsciiDoc, falscher Branch/Repo und fehlende Quelldatei.
- Jeder Communication-Kanal mit `inherit`, `override`, `disable`; Email `to/cc/bcc/subject/body`; URL-Template-Query; `_self`/`_blank`; Host-Allowlist; private Security-Ziele; fehlende Marker.

### F. Validation / Workspace

- Jede `validation.*`-Option einzeln ein-/ausschalten bzw. numerische Grenze knapp unter/gleich/über Grenzwert.
- Build-Manifest vorhanden/fehlend/ungültig; Required Files vorhanden/fehlend.
- Symlinks, Race-Swap, `.git`-Metadaten, Path Traversal, Hostile HTML/CSS und aktive URL-Schemata.
- Jeder Workspace-Cleanup-Modus, Keep-on-Success, Keep-on-Failure, Cleanup-Retry, Cleanup-Fehler-Fatalität und Lock-Timeout.

### G. Publish / Workflow

Diese Phasen müssen getrennt von `build` getestet werden.

- Publishing Adapter `artifact`, `filesystem`, `command` mit `dry_run=true/false`.
- `atomic=true/false`, vorhandenes Ziel, `replace_existing=true/false`, externe Destination opt-in, `pre_publish_validation=true/false`, timeout, Command-Exitcode, Secret-Redaction und Symlink-Schutz.
- Workflow-Generator: alle Trigger-Kombinationen, Pfadfilter, Schedule, Workflow Call, Concurrency, Action-SHA-Prüfung, Config-Pfad, nested config, Hidden Files, Permissions, Secrets/Environment und Deploy/Build-Job-Trennung.
- Generiertes Workflow-YAML zusätzlich gegen die erwartete GitHub-Actions-Semantik validieren; Generator-Erfolg allein reicht nicht.

## 7. Konkrete Schlussfolgerung

Der aktuelle Stand rechtfertigt folgende Aussagen:

1. Der gezeigte Keycloak-Build-Pfad funktioniert bis zur erfolgreichen Site-Erzeugung.
2. Der in diesem Profil aktivierte Keycloak-Edit-Link-Override verarbeitet 362 Vorkommen; 359 eindeutige Quellen sind im exakt gebauten Commit vorhanden.
3. Der Base Path wird im festgestellten Canonical-Wert verwendet; die bestehende Test-Suite enthält gezielte Rewrite-Regressionen.
4. Die Publisher-Konfiguration als Ganzes ist **nicht** vollständig wirksamkeitsabgenommen. Insbesondere Publish und Workflow-Generierung sind andere CLI-Phasen und wurden im Smoke-Build nicht ausgeführt.
5. Eine universelle Bestätigung für jede denkbare Kombination ist nicht seriös möglich. Ein vollständiger, nachvollziehbarer Release-Nachweis erfordert die oben beschriebene Feld-/Werte-/Interaktionsmatrix mit Positiv- und Negativtests und klaren erwarteten Wirkungen.

**Freigabeempfehlung:** Keine Release-Freigabe. R8-009 und R8-011 bleiben teilweise, R8-017/R8-019/R8-021/R8-022 offen; R8-027 bleibt bis zum echten Dev-Container-Rebuild offen.
