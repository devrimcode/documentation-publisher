# GitHub Codespaces – aktive Entwicklungscontainer-Konfiguration

Diese Ablage ist die **aktive** Codespaces-Konfiguration dieses Repositories. Die Datei
`.devcontainer/devcontainer.json` liegt am Erkennungspfad und verweist auf
`.devcontainer/Dockerfile`. Der Docker-Build-Kontext ist explizit das Repository-Root,
damit die `COPY`-Anweisungen für Snapshot-Quellen und Installer reproduzierbar aufgelöst
werden.

## Bereitgestellte Umgebung

- Python 3.13 aus dem Microsoft Dev-Container-Bookworm-OCI-Image, gepinnt über den vollen
  SHA-256-Digest des OCI-Image-Index; die Build-Architektur ist `linux/amd64`.
- Debian Bookworm, Bookworm-Updates und Bookworm-Security-APT-Metadaten sind auf den
  Snapshot `20261107T000000Z` eingefroren. Alle Quellen verwenden den Debian-Archiv-
  Keyring; APT prüft weiterhin die Repository-Signaturen. `Check-Valid-Until: no` ist
  ausschließlich für den absichtlich historischen Snapshot gesetzt, damit dessen
  abgelaufenes Aktualitätsfenster nicht die Installation blockiert.
- Debian Bookworm, Bookworm-Updates und Bookworm-Security werden aus dem signierten
  Snapshot `20261107T000000Z` eingelesen. Das prüft die feste APT-Metadatenquelle; es
  wird **kein separates `git-subtree`-Paket installiert**, weil Debian Bookworm dieses
  Paket nicht bereitstellt.
- Der gepinnte Microsoft-Base-Image-Digest enthält das Debian-Paket `git`. Dieses Paket
  liefert `/usr/lib/git-core/git-subtree`. Der Installer prüft den dpkg-Dateibesitzer,
  die installierte `git`-Paketversion und den Hash der Helper-Datei. Anschließend verlinkt
  er ausschließlich diesen vorhandenen Helper in das Verzeichnis von `git --exec-path`.
- Das Lock v3 protokolliert Snapshot-ID, APT-Quellhash, Architektur, APT-/dpkg-Version,
  Base-Image-Digest, Build-Plattform, Git-Version, Besitzerpaket/-version, Helper-Hash
  und den tatsächlichen Exec-Pfad-Link. Der Laufzeitprüfer kontrolliert alle Werte bei
  jedem Start und prüft erneut `git subtree -h`.
- Die veränderlichen Debian-APT-Quellen aus dem Basisimage werden vor dem Snapshot-Update
  entfernt. Es kann daher kein Live-`deb.debian.org`-Spiegel unbemerkt verwendet werden.
- Git LFS 3.8.1 über das auf Feature 1.2.5 gepinnte Dev-Container-Feature; Auto-Pull ist
  deaktiviert.
- Eclipse Temurin JDK 25 als Standard und JDK 21 zusätzlich über Java Feature 1.8.3;
  Maven 3.10.0 über dasselbe Feature.
- Python `.venv`; `ensure-python-environment.sh` installiert die deklarierten Abhängigkeiten anhand eines Fingerprints beim Post-Create, bei jedem Containerstart und beim Öffnen eines neuen interaktiven Bash-Terminals.
- Neue Bash-Terminals aktivieren automatisch das nächste Repository-`.venv`; die Aktivierung wird nicht nur der VS-Code-Python-Erweiterung überlassen.

## Snapshot aktualisieren

Der aktuelle Debian-Snapshot ist bewusst auf `20261107T000000Z` festgesetzt. Nicht auf
bewegliche `bookworm`-Live-Mirror umstellen. Für ein Update muss ein neuer Snapshot
geprüft, `ARG DEBIAN_SNAPSHOT` im Dockerfile geändert, das Image neu gebaut und die
entstandene `toolchain-lock.tsv` kontrolliert werden. Ein Base-Image-Update muss den
`FROM`-Digest und `PUBLISHER_BASE_IMAGE_REF` gemeinsam ändern. Anschließend ist die
vollständige Regression auszuführen.

Ein eingefrorener Snapshot erhält nicht automatisch spätere Sicherheitsupdates. Der
Snapshot ist daher regelmäßig nach Review fortzuschreiben; dabei ist auch der gepinnte
Basisimage-Digest gemeinsam zu überprüfen und bei Bedarf zu aktualisieren.

## Einrichtung in einem neuen Repository

1. Den gesamten Ordner `.devcontainer/` in das Root-Verzeichnis des neuen GitHub-Repositories
   kopieren.
2. Alle Dateien auf dem Branch speichern, von dem der Codespace erstellt wird.
3. Den Codespace neu erstellen, damit der Docker-Build samt APT-Snapshot-Prüfung und
   Git-Helper-Verlinkung ausgeführt wird.
4. `postCreateCommand` erstellt `.venv`, installiert Projektabhängigkeiten und prüft das
   Toolchain-Lock.
5. Der erzeugte Toolchain-/Git-Subtree-Lock wird unter `test-results/devcontainer-toolchain-lock.tsv`
   samt SHA-256-Sidecar abgelegt. Er bindet den Debian-`git`-Paketbesitzer, Helper-Hash, Git-Exec-Pfad,
   Base-Image-Digest, Snapshot-Quelle und Paketmanager-Versionen.
6. `postStartCommand` kontrolliert den Toolchain-Lock, Python 3.13, Java 25 aktiv plus Java 21,
   Maven 3.10.0, Git LFS 3.8.1 und Git Subtree bei jedem Start.

## Prüfung nach dem Start

```bash
bash .devcontainer/verify-apt-state.sh
bash .devcontainer/verify-environment.sh
```

Für das vollständige Publisher-Projekt:

```bash
bash scripts/test-in-codespaces.sh
```

F05/F16 gelten erst dann als extern abgenommen, wenn ein frischer Codespace das Image
erfolgreich baut, den Toolchain-/Git-Subtree-Lock ohne Drift prüft und die Regressionen besteht. Statische
Tests und lokale Fake-APT-Fixtures ersetzen keinen echten Docker-/Codespaces-Build.
