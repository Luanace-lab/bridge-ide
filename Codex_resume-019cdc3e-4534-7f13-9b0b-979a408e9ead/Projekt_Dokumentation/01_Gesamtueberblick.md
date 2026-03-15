# 01_Gesamtueberblick

## Zweck
Verdichteter Gesamtueberblick ueber den realen Ist-Zustand von `/BRIDGE` als interne Nachschlagebasis.

## Scope
Gesamter `/home/user/bridge/BRIDGE`-Scope, mit Schwerpunkt auf Architektur, UI, Kommunikation, Datenhaltung, Arbeitsmodell und Dokumentationslage.

## Evidenzbasis
- `/home/user/bridge/BRIDGE/Backend/server.py`
- `/home/user/bridge/BRIDGE/Backend/runtime_layout.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_mcp.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_cli_identity.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_watcher.py`
- `/home/user/bridge/BRIDGE/Backend/team.json`
- `/home/user/bridge/BRIDGE/Backend/tasks.json`
- `/home/user/bridge/BRIDGE/Backend/workflow_registry.json`
- `/home/user/bridge/BRIDGE/Backend/automations.json`
- `/home/user/bridge/BRIDGE/Frontend/chat.html`
- `/home/user/bridge/BRIDGE/Frontend/control_center.html`
- `/home/user/bridge/BRIDGE/bridge_ide/cli.py`
- `/home/user/bridge/BRIDGE/Archiev/bridge_ide/cli.py`
- `/home/user/bridge/BRIDGE/docs/*`
- die thematischen Dateien `W01` bis `W08` in diesem Ordner

## Ist-Zustand
`/BRIDGE` ist eine reale, lokal ausgerichtete Multi-Agent-Plattform mit starkem Funktionsumfang, aber heterogener Struktur.

Verifizierte Kernfakten:

- Backend-Kern:
  - `Backend/server.py` mit 21768 Zeilen
  - `Backend/runtime_layout.py` mit 308 Zeilen als bereits extrahierter Runtime-Layout-Helfer
  - `Backend/bridge_mcp.py` mit 11333 Zeilen
  - `Backend/bridge_cli_identity.py` mit 97 Zeilen als extrahierter CLI-Identity-/Heartbeat-Helfer
  - `Backend/bridge_watcher.py` mit 3087 Zeilen
- Frontend-Kern:
  - `Frontend/chat.html` mit 10632 Zeilen
  - `Frontend/control_center.html` mit 10071 Zeilen
  - kein Frontend-Build-System; statische Single-File-Seiten
- Team-/Org-Modell:
  - `Backend/team.json` Version 3
  - 2 Projekte
  - 14 Teams
  - 59 Agents
  - 6 als `active=true` markierte Agents
- Arbeitsmodell:
  - Tasks in `Backend/tasks.json`
  - Workflows in `Backend/workflow_registry.json`
  - Automationen in `Backend/automations.json`
  - Scope-Locks, Whiteboard, Eskalation und Agent-State als getrennte dateibasierte Stores

## Datenfluss / Kontrollfluss
Der beobachtete Hauptfluss ist hybrid:

1. UI oder CLI sendet HTTP- oder MCP-Aktionen an den Server.
2. `server.py` verarbeitet die Aktion, persistiert Zustandsaenderungen dateibasiert und broadcastet Ereignisse.
3. Live-Zustellung laeuft parallel ueber WebSocket, MCP-Listener, tmux-Watcher-Nudges und teilweise Legacy-Receive-Pfade.
4. Frontend-Seiten lesen Snapshots ueber `fetch()` und ergaenzen Live-Zustaende ueber WebSocket oder Polling.
5. Tasks, Ownership und Workflow-Ausfuehrung greifen auf mehrere persistente Stores gleichzeitig zu.

## Abhängigkeiten
- Python >= 3.10
- tmux fuer Agent-Sessions
- `websockets`, `httpx`, `mcp`, `croniter`, `watchdog`
- optionale externe Systeme wie n8n, Browser-Runtimes und weitere Integrationen
- dateibasierte Persistenz im Repository-Baum selbst

## Auffälligkeiten
- Das System ist funktionsreich, aber nicht in wenige scharf getrennte Subsysteme aufgeteilt; `server.py` bleibt trotz erster Extraktion von Runtime-Layout-Logik nach `Backend/runtime_layout.py` der dominierende Monolith.
- `bridge_mcp.py` bleibt trotz erster Extraktion des CLI-Identity- und Heartbeat-Helferblocks nach `Backend/bridge_cli_identity.py` ein grosser Tool- und Transport-Monolith.
- Kommunikation, Runtime-Steuerung und Persistenz nutzen mehrere parallele Kanaele.
- Das Frontend besteht aus zwei sehr grossen operativen Hauptseiten, die je viele Fachbereiche gleichzeitig tragen.
- Der Root-Baum mischt Quellcode, Live-Daten, persoenliche Bereiche, Evidence und Altartefakte.
- Die aktive Dokumentation deckt Teilbereiche gut ab, aber keine durchgehende Gesamtkarte.

## Bugs / Risiken / Inkonsistenzen
- Reale Evidence belegt Last-, Register- und Runtime-Inkonsistenzen.
- Der Docker-/Compose-Pfad deckt jetzt die zentralen Control-Plane-Stores ab; `runtime_team.json` wird dabei bewusst nicht in den Container uebernommen, damit dort kein hostseitiger Runtime-Zustand vorgetaeuscht wird.
- Dieselbe Docker-Variante ist aber kein vollstaendiger Fremdnutzer-Betriebspfad fuer die Agent-Runtime, weil die operative SoT weiter host-nativ ueber `tmux_manager.py` und die nativen `codex`-/`claude`-CLIs laeuft.
- Die Dokumentation driftet teilweise vom Codezustand weg.
- Daten- und Ownership-Zustaende sind ueber mehrere JSON-/JSONL-Stores verteilt.
- Backup- und Altartefakte liegen direkt neben aktiven Produktivdateien und erschweren Orientierung.

## Offene Punkte
- Welche Startvariante, welche UI-Seite und welche Dokumente operativ kanonisch sind, ist nicht in einem einzigen SoT-Artefakt festgelegt.
- Ob die aktuelle Persistenzlage auf Disk den Live-Zustand vollstaendig abbildet, bleibt ohne Laufzeitpruefung offen.
- Welche Teile des Root-Baums bewusst persoenlich, historisch oder produktiv sind, ist nicht zentral klassifiziert.
