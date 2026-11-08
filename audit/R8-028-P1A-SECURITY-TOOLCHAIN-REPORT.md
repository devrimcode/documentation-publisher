# R8-028 / P1A – Sicherheits- und Toolchain-Korrekturgruppe 1

**Projektstand:** Documentation Publisher `2.0.10-dev`, kumulativer Kandidat P12 auf Basis des wiederhergestellten P11-Archivs  
**Prüfdatum:** 2026-11-07  
**P11-Basisarchiv SHA-256:** `a35bcfe52c130a8505422806f58fc429f7bbad8b0fbcae1d89722d35ba212936`

## 1. Was in dieser Gruppe geändert wurde

### Repository-Host-Allowlisten

- `publisher.allowed_hosts`, `sources[].vcs.allowed_hosts`, globale Communication-Allowlisten und komponentenspezifische Communication-Allowlisten lehnen `*` und `*.`-Muster ab.
- Einträge werden auf vollständige Hostnamen geprüft: keine Scheme-/Path-/Port-/Credential-Bestandteile, keine leeren Labels, keine Labels mit führendem/abschließendem Bindestrich und keine ungültigen Host-Längen.
- Repository-URL-Prüfung erlaubt keinen Wildcard-Bypass.
- Die generische `publisher.example.yml` verwendet `<PUBLISHER_ALLOWED_HOST>` und `<SOURCE_ALLOWED_HOST>` statt `*`. Die Vorlage bleibt absichtlich nicht lauffähig, bis sämtliche Platzhalter konkret ersetzt wurden.

### Live-Publishing mit reservierten oder nicht öffentlichen Origins

- `publishing.dry_run: false` blockiert reservierte Example-/Test-Domains einschließlich Subdomains (`.example`, `.invalid`, `.test`, `.localhost`, `example.com`, `example.net`, `example.org`).
- Nicht-globale IP-Ursprünge (Loopback, private, Link-Local, Dokumentations-, Multicast- und sonstige nicht globale IP-Bereiche) werden ebenfalls blockiert.
- `site.base_url` und `site.canonical_base_url` werden beide geprüft.
- Explizite Dry-Run-Fixtures dürfen diese reservierten Origins weiterhin verwenden; der Keycloak-Smoke-Plan bleibt damit verwendbar.

### Beispiel- und Smoke-Konfigurationen

- `publisher.keycloak.example.yml` wurde in `publisher.keycloak.smoke.yml` umbenannt.
- Der Datei-Header nennt die tatsächlichen Annahmen (konkretes Publisher-Repository, Upstream Keycloak `main`, reservierte `https://example.invalid`-Origin), hält `publishing.dry_run: true` fest und erklärt die Datei ausdrücklich als projektbezogene Smoke-Fixture, nicht als generische oder Live-Deployment-Vorlage.
- Der Codespaces-Harness validiert diese Smoke-Datei und erzeugt ihren Komponentenplan unter dem neuen Namen.

### Entwicklungsumgebung und Repository-Hygiene

- Root-`.gitignore` ignoriert Python-/Pytest-Caches, `.venv`, Testresultate sowie Publisher-generierte Arbeitsverzeichnisse.
- Dev-Container-Feature-Versionen sind explizit gepinnt: Java Feature `1.8.3`, Git-LFS-Feature `1.2.5`, Git LFS `3.8.1`, Temurin Java `25` als Standard plus Java `21`, Maven `3.10.0`. Die Python-Basisimage-Referenz ist derzeit tag-, nicht digest-gepinnt; das APT-Paket `git-subtree` ist nicht auf Snapshot/Version fixiert. Vollständige bit-identische Reproduzierbarkeit ist damit noch nicht erreicht.
- `.devcontainer/verify-environment.sh` fordert Python `3.13` exakt, aktives Java `25`, einen zusätzlich installierten SDKMAN-JDK-21-Kandidaten, Git LFS `3.8.1`, Maven `3.10.0` und `git subtree` im aktiven Git-Exec-Pfad.
- `scripts/codespaces_acceptance.py` prüft denselben Toolchain-Vertrag, dazu Generic-Template-Fail-Closed-Verhalten, Keycloak-Smoke-Konfiguration und Smoke-Buildplan.

## 2. Reproduzierbare Regression

| Testgruppe | Ergebnis |
|---|---:|
| Konfigurations-/Sicherheitsregression | 31/31 bestanden |
| Devcontainer-Konfigurationsregression | 12/12 bestanden |
| Devcontainer-Runtime-Verifier mit positiven und negativen Test-Doubles | 5/5 bestanden |
| Gezielte Korrekturgruppe zusammen | 48/48 bestanden |
| Hauptregressionssuite, ohne `tests/test_process.py` | 218 bestanden, 1 übersprungen, 73 Subtests |
| Prozessgruppen-/Subprocess-Suite, separat | 6/6 bestanden, `ResourceWarning` als Fehler |
| Gesamtergebnis über getrennte Haupt- und Prozessläufe | **224 bestanden, 1 übersprungen, 0 fehlgeschlagen** |

Der eine Skip bleibt der echte Git-LFS-Objekttransfer. Er wurde nicht als bestanden gezählt.

Die vollständigen Ausgaben liegen in `audit/evidence/R8-028-P1A-*.txt`.

## 3. Differentieller Vorher-/Nachher-Nachweis

Die vier neuen Runtime-Regressionsfälle wurden zusätzlich auf einer frisch entpackten, unveränderten P11-Baseline ausgeführt (nur das neue Testmodul wurde hineinkopiert; Produktionscode blieb unverändert). Ergebnis: **11 erwartete Assertion-Fehlschläge/Subfailures, 1 Dry-Run-Kontrolle bestanden**. Die Wildcard-Allowlisten wurden akzeptiert und reservierte Live-Origins wurden nicht blockiert. Das Baseline-Protokoll liegt in `audit/evidence/R8-028-P1A-UNMODIFIED-P11-BASELINE-NEGATIVE-TESTS.txt`. Auf P12 bestehen die korrigierten Fälle in der 31er Konfigurations-/Sicherheitsgruppe.

## 4. Codespaces-Teststarter

`bash scripts/test-in-codespaces.sh` wurde Ende-zu-Ende mit Test-Doubles für die vier auf dem Host fehlenden Toolchain-Komponenten ausgeführt:

- Git LFS `3.8.1`
- aktives Java `25`
- zusätzlicher SDKMAN-JDK `21`
- Maven `3.10.0`

Python `3.13.5`, Git `2.47.3`, Git Subtree, Publisher-CLI, YAML-/Schema-Validierung, Smoke-Plan und beide Pytest-Gruppen wurden tatsächlich lokal ausgeführt. Der Acceptance-Teil meldete mit den Test-Doubles `Failed/blocked checks: 0`; Hauptsuite und Prozesssuite bestanden mit den oben genannten Zahlen.

Das ist ein Nachweis des Teststarters und seiner Prüfpfade, **kein** Nachweis einer echten Feature-Installation oder eines Docker-/Codespaces-Image-Builds.

## 5. Unverfälschter Host-Check und offene Abnahme

Der separate Acceptance-Lauf ohne Test-Doubles meldete vier echte Host-Blockaden:

1. `git lfs` ist auf dem Host nicht installiert.
2. Java `21.0.12.1` ist aktiv; die Devcontainer-Konfiguration verlangt Java `25` als Standard.
3. Unter dem erwarteten SDKMAN-Verzeichnis wurde kein zusätzlich installierter Java-21-Kandidat gefunden.
4. Maven ist auf dem Host nicht installiert.

Python `3.13.5`, Git `2.47.3`, Git Subtree, CLI-Version, Konfigurationsvalidierung, Smoke-Plan und Python-Kompilierung bestanden.

Docker/Podman ist nicht verfügbar. Deshalb bleiben folgende externe Grenzen offen:

- echter Build des Dev-Container-Dockerfiles und Installation der gepinnten Features;
- echter GitHub-Codespaces-Neustart aus einem Branch, der `.devcontainer/` enthält;
- echte Git-LFS-Objektübertragung;
- Project-Pages-/Keycloak-Browser- und Editor-Abnahme;
- native Windows-Prozessbaum-Abnahme.

R8-027 ist damit in der Konfiguration und dem Verifier verschärft, aber extern noch nicht abgenommen. R8-017 und die genannten Browser-/Plattformgates bleiben offen.

## 6. Provenienz und Seiteneffekte

- Die Korrektur basiert auf dem P11-Archiv mit dem oben genannten SHA-256.
- Der Projektbaum lag als extrahiertes Archiv vor und besitzt in dieser Arbeitsumgebung keine `.git`-Metadaten. Der Vorher-/Nachher-Unterschied wird deshalb als separater Patch gegen das exakt gehashte P11-Archiv geliefert.
- Kein GitHub-Remote, kein Codespace, kein Keycloak-Upstream wurde geändert.
- Kein Commit, Push, Pull Request oder Deployment wurde ausgeführt.
- Die Testläufe erzeugen lokale Caches und `test-results/`; diese sind durch `.gitignore` abgedeckt und werden aus dem finalen Archiv entfernt, die dauerhaften Nachweise liegen unter `audit/evidence/`.

**Status:** P1A implementiert und lokal regressionsgeprüft. Nicht die vollständige R8-028-Auditliste und keine Release-Freigabe.


## 7. Geprüfte Upstream-Versionen und verbleibende Pinning-Grenzen

Die gepinnten Feature-Optionen wurden gegen die offiziellen Feature-Metadaten geprüft: Java Feature `1.8.3` unterstützt `version`, `additionalVersions`, `jdkDistro`, `installMaven` und `mavenVersion`; Git-LFS-Feature `1.2.5` unterstützt `version` und `autoPull`. Die festgelegten Maven- und Git-LFS-Versionen existieren als veröffentlichte Releases.

- Java Feature-Metadaten: https://github.com/devcontainers/features/blob/main/src/java/devcontainer-feature.json
- Git LFS Feature-Metadaten: https://github.com/devcontainers/features/blob/main/src/git-lfs/devcontainer-feature.json
- Maven 3.10.0 Release: https://maven.apache.org/docs/history
- Git LFS 3.8.1 Release: https://github.com/git-lfs/git-lfs/releases/tag/v3.8.1

Offen bleiben der Digest-Pin des Python-Basisimages und ein reproduzierbarer Debian-APT-Snapshot für `git-subtree`. Die Features sind exakt versioniert, das Gesamtimage aber noch nicht vollständig unveränderlich.
