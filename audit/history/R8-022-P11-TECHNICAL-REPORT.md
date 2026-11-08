> **Historischer Teststand:** Dieser Bericht wurde vor den sieben R8-027-Dev-Container-Konfigurationstests erstellt. Der aktuelle aggregierte Regressionstand liegt in `R8-P11-CUMULATIVE-STATUS.md` und `audit/evidence/P11-CURRENT-COMPLETE-REGRESSION-209-PASS.txt`.

# R8-022 / P11 — Subprocess-Ausgabe begrenzen und Prozessgruppen bereinigen

## Ausgangsfehler auf der unveränderten P3-Baseline

Die Baseline-Probe startete einen Fake-Git-Prozess, der jeweils 4 MiB auf stdout und stderr ausgab. Der bisherige `subprocess.run(..., capture_output=True)`-Pfad hielt beide vollständigen Ausgaben im Speicher, bevor `run_git()` den Diagnose-String auf den Tail kürzte. Eine zweite Probe ließ einen Parent-Prozess einen verzögert schreibenden Child starten und anschließend in den Timeout laufen. Der Parent wurde beendet, der Child-Prozess lief weiter und schrieb die Markerdatei.

Die Messwerte stehen in `evidence/P8-P11-P3-BASELINE-PROBES.txt`.

## Implementierung in diesem Projektstand

- Neuer gemeinsamer Runner `publisher_engine/process.py`.
- stdout und stderr werden parallel in festen 64-KiB-Chunks gelesen. Der Runner hält pro Stream nur einen Tail-Puffer mit konfigurierter Obergrenze (Standard 16 KiB); Speicher für die vollständige Ausgabe wird nicht aufgebaut.
- Null-Retention (`max_output_bytes=0`) verwirft Ausgabe, drainiert die Pipes aber weiter, damit der Kindprozess nicht an vollen Pipes blockiert.
- Der Runner verwendet Argumentlisten und keine Shell-Expansion.
- POSIX: Prozessstart in einer neuen Session; Timeout beendet die Prozessgruppe erst regulär und eskaliert danach zu SIGKILL. Der direkte Child wird ge-wait/reaped.
- Windows: neuer Prozessgruppen-Start; Timeout versucht die Prozessbaum-Beendigung über `taskkill /T /F`, mit Fallback auf das Beenden des direkten Prozesses.
- Ein begrenztes Pipe-Drain-Zeitfenster verhindert, dass ein Nachfahre, der Dateideskriptoren geerbt hat, den Aufrufer unbegrenzt festhält.
- Git-Befehle, Git-Subtree-Preflight/Ref-Prüfungen, Git-LFS-Verfügbarkeitsprüfung, Build-Tasks, Publishing-Commands und Git-Ref-Prüfung aus der Konfigurationslogik verwenden den gemeinsamen Runner.

## Tests

Der ursprüngliche R8-022-Kern enthielt fünf Tests:

1. 12 MiB stdout und 12 MiB stderr drainieren; pro Stream bleiben bei einem 4-KiB-Limit nur die letzten 4 KiB verfügbar.
2. Bei Null-Retention werden Pipes weiterhin vollständig drainiert und der Prozess beendet sich normal.
3. Timeout-Ausgabe bleibt auf das konfigurierte 512-Byte-Limit beschränkt.
4. POSIX-Prozessgruppentest: ein Parent startet einen verzögert schreibenden Child; nach Timeout darf die Markerdatei nicht entstehen.
5. stdout/stderr können gemeinsam in einen einzigen begrenzten Stream geführt werden.

Das spätere Pipe-Handle-Cleanup-Addendum ergänzte einen sechsten Test, der beide Handles im Timeout-Pfad prüft. Der aktuelle Prozesstestblock besteht auf Linux mit **6/6 bestanden**; der historische Fünf-Test-Kern ist nur noch als Teilstand zu verstehen.

## Grenzen

- Der Prozessgruppen-Test wurde unter Linux ausgeführt. Die Windows-`taskkill`-Variante wurde hier nicht nativ getestet und bleibt eine Plattform-Abnahme.
- Der Test misst die begrenzte Länge des gespeicherten Outputs und prüft die Chunk-/Tail-Implementierung; er ist keine unabhängige Peak-RSS-Speichermessung des gesamten Python-Prozesses.
- Die bestehenden Secret-Redaktionspfade der Aufrufer wurden beibehalten. Der P11-Testblock ergänzt jedoch keinen separaten vollständigen Secret-Matrix-Test für alle Aufrufer und alle Fehlerausgaben.


## Addendum 2026-11-07 — Pipe-Handle-Cleanup und Codespaces-Testlauf

Ein zusätzlicher, zuvor nicht separat geprüfter Ressourcenaspekt wurde korrigiert: Im Timeout-Pfad werden stdout/stderr-Pipe-Handles nach dem Beenden des Prozessbaums geschlossen und Reader-Threads erneut gejoint. `tests/test_process.py::test_timeout_closes_captured_pipe_handles` prüft beide Handles explizit. Der Prozesstestblock besteht nun mit **6/6**, auch mit `-Werror::ResourceWarning`.

Zum Zeitpunkt dieses Addendums bestand die Hauptsuite mit 202 passed und 1 skipped. Der aktuelle Stand nach den zusätzlichen R8-027-Konfigurations- und Teststarter-Regressionen liegt bei 203 passed und 1 skipped in der Hauptsuite sowie 6/6 im separaten Prozessgruppenblock, insgesamt 209 passed und 1 skipped. Der aktuelle Nachweis steht in `audit/evidence/P11-CURRENT-COMPLETE-REGRESSION-209-PASS.txt`. Der Skip bleibt der echte Git-LFS-Objekttransfer.
