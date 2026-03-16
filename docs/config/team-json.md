# team.json

## Zweck
Aktuelle Source-of-Truth-Dokumentation fuer Team-, Agent- und Runtime-Overlay-Konfiguration im Root-Workspace von `./BRIDGE`.

## Aktueller Pfadstand
- Persistierte Basiskonfiguration: `Backend/team.json`
- Persistiertes Runtime-Overlay: `Backend/runtime_team.json`
- Legacy-Board-Fallback: `Backend/projects.json`
- Root-`config/` enthaelt im aktuellen Workspace nur `config/mcp_catalog.json`

Hinweis:
- Vor diesem Update existierte die einzige `team-json.md`-Beschreibung nur unter `Archiev/docs/config/team-json.md`.
- Der Pfad `docs/config/team-json.md` ist im aktiven Root-Workspace jetzt vorhanden.

## Snapshot am 2026-03-11
- `Backend/team.json`: `2` Projekte, `14` Teams, `59` Agents, `6` Agents mit `active=true`
- `Backend/runtime_team.json`: `active=true`, `2` Runtime-Agents, `1` Runtime-Team, `3` Route-Eintraege
- `Backend/projects.json` existiert weiterhin und enthaelt eine aeltere Projekt-/Team-Projektion

## SoT-Regeln im aktuellen Code
1. `Backend/team.json` ist die persistierte Basiskonfiguration fuer Owner, Projekte, Teams und Agents.
2. `server.py` schreibt Aenderungen an `team.json` atomar, unter anderem fuer:
   - `POST /agents/create`
   - Agent- und Team-Updates
   - Hot-Reload-nahe Team-Operationen
3. `runtime_team.json` ist kein rein dokumentarisches Artefakt:
   - `server.py` persistiert das Overlay bei Runtime-Configure.
   - `GET /team/orgchart`
   - `GET /team/projects`
   - `GET /teams`
   - `GET /teams/{id}`
   - `GET /team/context/{id}`
     mergen das aktive Overlay in ihre Antworten.
4. `board_api.py` nutzt `team.json` als Backend, behaelt aber technisch den Fallback auf `Backend/projects.json`, falls das Team-Backend nicht initialisiert ist.
5. `POST /agents/create` schreibt neue Agents direkt in `Backend/team.json` und setzt `home_dir` standardmaessig auf `ROOT_DIR/.agent_sessions/{agent_id}` beziehungsweise `{project_path}/.agent_sessions/{agent_id}`.

## Praktische Konsequenz
- `Backend/team.json` bleibt die Basiskonfiguration.
- Die effektive API-Lesewahrheit fuer Team-/Projekt-Ansichten ist im aktiven Runtime-Betrieb `team.json` plus `runtime_team.json`.
- `projects.json` ist Legacy, aber technisch noch nicht bedeutungslos, solange `board_api.py` den Fallback beibehält.

## Risiken
- Dokumentierte SoT und reale API-Antworten driften, wenn `runtime_team.json` aktiv ist und in der Doku nur `team.json` betrachtet wird.
- `projects.json` kann fachlich von `team.json` abweichen.
- Die dynamisch erzeugten Agent-Eintraege in `team.json` benutzen Workspace-Pfade als `home_dir`; Leser duerfen `home_dir` deshalb nicht implizit mit Projekt-Root gleichsetzen.

## Live-Nachtrag 2026-03-12
- Verifiziert durch Ausführung:
  - `curl -fsS http://127.0.0.1:9111/board/projects`
  - `curl -fsS http://127.0.0.1:9111/team/projects`
  - `env PATH=/tmp/bridge_pkg_venv3/bin:$PATH bridge-ide stop`
- Im aktuellen Live-Betrieb sind Basiskonfiguration und Runtime-Overlay gleichzeitig sichtbar:
  - `/board/projects` und `/team/projects` liefern das Runtime-Projekt `bridge`
  - und parallel persistierte Basisprojekte wie `bridge-ide` und `bug-bounty`
- Damit ist die vereinfachte Aussage „nur Runtime-Overlay“ falsch; die UI-Lesepfade spiegeln aktuell mehrere Schichten zugleich.
- In einem real ausgeführten Stop-Zyklus wurde `Backend/runtime_team.json` entfernt und danach durch den naechsten Startpfad neu aufgebaut.

## Offene Punkte
- Ob weitere historische Dokuartefakte ausserhalb dieses Root-Pfads von Menschen noch als SoT verwendet werden, ist offen.
