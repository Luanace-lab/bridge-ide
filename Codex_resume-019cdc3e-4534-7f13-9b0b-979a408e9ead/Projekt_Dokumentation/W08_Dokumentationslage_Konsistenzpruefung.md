# W08_Dokumentationslage_Konsistenzpruefung

## Zweck
Pruefung, welche Dokumentation im aktuellen `/BRIDGE`-Scope vorhanden ist, was davon konsistent oder veraltet wirkt und welche Luecken gegenueber dem realen Codezustand bestehen.

## Scope
Root-Dokumente, der faktische Detaildoku-Bestand und deren Abgleich mit realen Code- und Strukturartefakten.

## Evidenzbasis
- `/home/leo/Desktop/CC/BRIDGE/README.md`
- `/home/leo/Desktop/CC/BRIDGE/CLAUDE.md`
- `/home/leo/Desktop/CC/BRIDGE/LAUNCH_CHECKLIST.md`
- `/home/leo/Desktop/CC/BRIDGE/TEAM_FINDINGS.md`
- `/home/leo/Desktop/CC/BRIDGE/docs/README.md`
- `/home/leo/Desktop/CC/BRIDGE/docs/frontend/contracts.md`
- `/home/leo/Desktop/CC/BRIDGE/bridge_ide/cli.py`
- `/home/leo/Desktop/CC/BRIDGE/bridge_ide/_backend_path.py`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/docs/README.md`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/docs/config/team-json.md`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/docs/frontend/README.md`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/docs/frontend/contracts.md`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/docs/frontend/gap-analysis-vs-release.md`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/docs/specs/SPEC_SIMPLE_SETUP.md`
- `/home/leo/Desktop/CC/BRIDGE/Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`
- Root- und Codeartefakte unter `Backend/`, `Frontend/`, `pyproject.toml`, `setup.py`

## Ist-Zustand
Vorhandene Root-Dokumentation:

- `README.md`
- `CLAUDE.md`
- `LAUNCH_CHECKLIST.md`
- `TEAM_FINDINGS.md`
- `docs/README.md` als neuer Root-Index fuer die aktuelle Dokumentlage

Vorhandene Detaildokumentation in der Working Copy:

- `Archiev/docs/README.md`
- `Archiev/docs/config/team-json.md`
- `Archiev/docs/frontend/README.md`
- `Archiev/docs/frontend/contracts.md`
- `Archiev/docs/frontend/gap-analysis-vs-release.md`
- `Archiev/docs/specs/SPEC_SIMPLE_SETUP.md`
- `Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/*`

Bewertung der Dokumentationslage:

- Dokumentiert:
  - Frontend-Grundstruktur und Frontend-Backend-Kontrakte, aber nicht unter einem aktiven Root-`docs/`-Baum
  - `team.json` als kanonische Team-Konfiguration
  - Backend-API- und Infrastrukturbreite in `Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`
  - Root- und Gap-Analyse im Resume-Dokumentationssatz
- Veraltet oder inkonsistent:
  - Root-`README.md` war vor der Aktualisierung deutlich zu klein fuer den realen Root- und Plattformzustand.
  - `LAUNCH_CHECKLIST.md` markiert mehrere Root-Dokumente als vorhanden, die in der aktuellen Working Copy fehlen.
  - `CLAUDE.md` referenziert teils nicht sichtbare Root-Pfade und Rollenordner.
  - `TEAM_FINDINGS.md` ist wertvolle Historie, aber kein kanonisches Ist-Zustandsdokument.
  - Teile der Resume-Dokumentation hingen bis zu diesem Slice dem reparierten Root-`bridge_ide/`-Pfad und den workflow-/n8n-Verifikationen hinterher.
- Fehlend oder nur indirekt vorhanden:
  - ein konsistenter Root-`docs/`-Baum mit den im Release-/Launch-Kontext behaupteten Dateien
  - eine zentrale Klassifikation, welche Dokumente aktiv, historisch oder verschoben sind
  - eine Root-nahe Gesamtkarte, die Packaging-Sicht, Root-Struktur, UI-Einstiege und Detaildoku zusammenfuehrt

## Datenfluss / Kontrollfluss
Die vorhandene Dokumentation folgt keinem einzigen, konsistenten SoT-Fluss:

1. Root-Dokumente geben operative Hinweise, aber nur teilweise passend zum sichtbaren Root.
2. Detaildoku liegt nicht in einem einzigen Root-Baum, sondern verteilt in `docs/frontend/`, `Archiev/docs/`, `Backend/docs/` und dem Resume-Paket.
3. Historische oder operative Findings in `TEAM_FINDINGS.md` dokumentieren Sprintarbeit, aber nicht den bereinigten aktuellen Root-Zustand.
4. Der reale Codezustand ist groesser als die Summe der Root-Dokumente.

## Abhängigkeiten
- Die Konsistenzpruefung haengt direkt an der aktuellen Working Copy.
- Besonders relevant sind `server.py`, `chat.html`, `control_center.html`, `pyproject.toml`, `setup.py` und die sichtbare Root-Struktur.
- Der neue Root-Index `docs/README.md` haengt wiederum an den archivierten Detaildokumenten unter `Archiev/docs/` und `Backend/docs/`.

## Auffälligkeiten
- Die aktuelle Doku ist nicht nur asymmetrisch, sondern auch topologisch verschoben: Detaildoku und Root-Hinweise liegen an unterschiedlichen Orten.
- `TEAM_FINDINGS.md` und `Codex_resume-*` liefern viel operative Evidenz, sind aber keine intuitive Einstiegsschicht fuer neue Leser.
- Die Root-Doku muss derzeit zugleich Release-Hinweise, Live-Arbeitsraum und Archivdrift erklaeren.
- Der reparierte Root-Wrapperpfad `bridge_ide/` ist jetzt real verifiziert, aber diese Reparatur musste in mehreren Dokumenten nachgezogen werden.
- Drei Root-Auditnotizen waren zwischenzeitlich selbst zu einer zweiten Doku-Schicht geworden:
  - `docs/buddy-bridge-gap-register.md`
  - `docs/frontend/clickpath-verification-matrix.md`
  - `docs/frontend/design-theme-consistency-audit.md`
  - ihre noch gueltigen Befunde sind jetzt in `W02`, `W06`, `W08` und `02_Gap_Map` integriert; die drei Dateien werden deshalb explizit als veraltet markiert statt weiter als primaere Referenz gefuehrt zu werden
- Der repo-interne Resume-Satz unter `BRIDGE/Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/` ist der kanonische Projekt-Doku-Satz fuer diese Working Copy.
- Eine zweite, gleichnamige Resume-Kopie ausserhalb des Repositories war parallel weitergelaufen und erzeugte echte Doku-Drift; diese Parallelkopie wurde nach Inhaltspruefung entfernt und ist nicht Teil der kanonischen SoT.

## Bugs / Risiken / Inkonsistenzen
- Das groesste Dokumentationsrisiko ist nicht nur Unterbeschreibung, sondern falsche Erwartung durch fehlende oder verschobene Pfade.
- Root-Dokumente koennen Leser auf einen cleanen Wrapper-/Release-Zustand fuehren, den die aktuelle Working Copy so nicht abbildet.
- Fehlende klare Trennung zwischen aktiver Referenz, Historie und ausgelagerter Detaildoku erhoeht Analyse- und Onboarding-Reibung.
- Packaging-Doku und Docker-/Compose-Pfad sind inzwischen in `W07_Projektstruktur_Entry_Points_Abhaengigkeiten_Build_Run.md` konsistenter nachgezogen; der Containerpfad ist dort jetzt inklusive Teardown-Nachweis dokumentiert, und der verbleibende Doku-Split liegt vor allem zwischen Root-Hinweisen und dem repo-internen Resume-Satz.
- Wenn die drei Audit-Notizen weiter als "aktuelle" Notes referenziert bleiben, entsteht erneut Konkurrenz zwischen:
  - kanonischem Resume-/Projekt-Doku-Satz
  - Root-Index unter `docs/`
  - historischen Audit-Snapshots
- Wenn erneut eine zweite gleichnamige Resume-Kopie ausserhalb des Repositories parallel weitergefuehrt wird, entsteht dieselbe Drift erneut auf Ordnerebene.

## Offene Punkte
- Welche Dokumente als aktive Referenz und welche nur als historische Spur gelten sollen, ist nicht durch ein zentrales Dokument festgelegt.
- Ob `Archiev/docs/` kuenftig nur Archiv oder wieder aktive Detaildoku sein soll, ist eine Folgeentscheidung ausserhalb dieses Doku-Slices.
- Ob `Archiev/bridge_ide/` kuenftig als reine Historie, archiviertes Artefakt oder sekundaere Referenz behandelt werden soll, bleibt offen.

## Offene Punkte
- Die Frage einer parallelen externen Resume-Kopie ist fuer diese Working Copy entschieden und bereinigt: kanonisch ist nur der repo-interne Resume-Satz.
- Ob alle Team-Mitglieder dieselben Dokumente als SoT verwenden.
