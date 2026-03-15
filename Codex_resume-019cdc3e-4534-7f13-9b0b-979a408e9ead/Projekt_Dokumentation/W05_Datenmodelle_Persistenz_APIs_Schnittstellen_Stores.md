# W05_Datenmodelle_Persistenz_APIs_Schnittstellen_Stores

## Zweck
Dokumentation der zentralen Datenmodelle, Persistenzstellen, API-Flaechen und Integrationsschnittstellen im `/BRIDGE`-Scope mit Fokus auf belegte Store-Praezedenz und aktuelle Drift.

## Scope
`/home/user/bridge/BRIDGE/Backend`, `docs/config/team-json.md` sowie die davon abhaengigen API-Lese- und Schreibpfade.

## Evidenzbasis
- `/home/user/bridge/BRIDGE/Backend/server.py`
- `/home/user/bridge/BRIDGE/Backend/team.json`
- `/home/user/bridge/BRIDGE/Backend/runtime_team.json`
- `/home/user/bridge/BRIDGE/Backend/projects.json`
- `/home/user/bridge/BRIDGE/Backend/board_api.py`
- `/home/user/bridge/BRIDGE/Backend/persistence_utils.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_cli_identity.py`
- `/home/user/bridge/BRIDGE/Backend/self_reflection.py`
- `/home/user/bridge/BRIDGE/Backend/execution_journal.py`
- `/home/user/bridge/BRIDGE/Backend/automation_engine.py`
- `/home/user/bridge/BRIDGE/Backend/agent_state/`
- `/home/user/bridge/BRIDGE/Backend/messages/bridge.jsonl`
- `/home/user/bridge/BRIDGE/docs/config/team-json.md`

## Ist-Zustand
Primaere modellierende und persistente Artefakte im aktuellen Code:

- Team-/Projektmodell:
  - `Backend/team.json` ist die persistierte Basis-Konfiguration.
  - Snapshot am 2026-03-11: `2` Projekte, `14` Teams, `59` Agents, davon `6` mit `active=true`.
  - `Backend/runtime_team.json` ist keine rein theoretische Overlay-Datei, sondern ein aktiver Read-Overlay fuer mehrere Team-/Projekt-Endpunkte.
  - Snapshot am 2026-03-11: `active=true`, `2` Runtime-Agents, `1` Runtime-Team, `3` Route-Eintraege.
  - `Backend/projects.json` existiert weiterhin als Legacy-Fallback fuer `board_api.py`.
- Identity-/Home-/Activity-Modell:
  - `server.py` schreibt CLI-Identity-Felder (`resume_id`, `workspace`, `project_root`, `home_dir`, `instruction_path`, `cli_identity_source`) in `REGISTERED_AGENTS` und `Backend/agent_state/{agent_id}.json`.
  - `Backend/agent_state/` ist kein sauber kuratierter Runtime-Store, sondern enthaelt auch Test-/Churn-/Claim-Isolation-Artefakte.
  - Snapshot am 2026-03-11: `3049` JSON-Dateien, darunter `_test_*`, `churn_*`, `claimiso_*`.
- Memory-/Context-Modell:
  - `persistence_utils.py` behandelt die CLI-Workspace-Datei `workspace/MEMORY.md` als ersten Kandidaten.
  - Danach folgen Legacy-Suchpfade unter `~/.claude-agent-{id}`, `~/.claude-sub2` und `~/.claude`.
  - `self_reflection.py` faellt bei fehlender CLI-Aufloesung auf `Backend/agents/{agent_id}/MEMORY.md` zurueck.
  - Reale Legacy-Memory-Dateien existieren aktuell unter `Backend/agents/buddy/MEMORY.md` und `Backend/agents/codex_a/MEMORY.md`.
- Kommunikations- und Journal-Stores:
  - `Backend/messages/bridge.jsonl` ist die einzige Nachrichtendatei unter `Backend/messages/`.
  - Snapshot am 2026-03-11: `68797` Zeilen, `56876167` Bytes.
  - `Backend/execution_runs/` speichert agentenzentrierte Journal-/Run-Artefakte.
  - Snapshot am 2026-03-11: `189` Run-Verzeichnisse.
- Workflow-/Automation-Modell:
  - `Backend/automations.json` ist der Definitionstore.
  - `Backend/logs/automation_history.jsonl` ist der append-only Verlauf.
  - `Backend/workflow_registry.json` bleibt der Bridge-Workflow-Metadatenstore.
  - `Backend/event_subscriptions.json` ist ein separater Persistenzstore fuer Bridge->n8n-Webhook-Subscriptions und darf nicht mit `workflow_registry.json` gleichgesetzt werden.
  - Snapshot nach dem Workflow-Cleanup am 2026-03-12:
    - `workflow_registry.json`: `4` Bridge-managed Records
    - `event_subscriptions.json`: `1` aktive Event-Subscription

## Datenfluss / Kontrollfluss
1. Schreiboperationen laufen ueber HTTP-Endpunkte in `server.py`; `team.json`, `runtime_team.json`, `agent_state`, Workflow- und Automation-Stores werden dateibasiert fortgeschrieben.
2. `bridge_mcp.py` spiegelt CLI-Identity fuer `POST /register`, Re-Register, Heartbeat und SelfReflection-Seeding jetzt ueber den reinen Helper `bridge_cli_identity.py`; serverseitig schreibt `POST /register` diese Felder weiter nach `REGISTERED_AGENTS` und `agent_state`, waehrend Register-Autoindex und Memory-Bootstrap weiterhin direkte `~/.claude*`-Pfade statt ausschliesslich die CLI-Workspace-SoT verwenden.
3. `GET /agents`, `GET /agents?source=team`, `GET /agents/{id}` und `GET /team/orgchart` trennen nach dem aktuellen Semantik-Fix jetzt explizit:
   - `active` als Team-/Konfigurationszustand aus `team.json`
   - `online` als beobachteten Laufzeitzustand
   - `auto_start` als Startpolitik
   - `tmux_alive` als technischen Unterbau
4. `GET /agents/{id}` und `GET /agents/{id}/persistence` lesen Identity- und Artefaktstatus workspace-first, leiten `home_dir` aber aus `workspace` oder `project_root` her.
5. `GET /team/orgchart`, `GET /team/projects`, `GET /teams`, `GET /teams/{id}` und `GET /team/context/{id}` lesen `team.json` nicht isoliert, sondern mergen bei aktivem Runtime-Betrieb das Overlay aus `runtime_team.json`.
6. `board_api.py` nutzt die in `server.py` injizierte `team.json`-Backend-Referenz, behaelt aber technisch den Fallback auf `Backend/projects.json`, falls das Team-Backend nicht initialisiert ist.
7. `execution_journal.py` schreibt agentenzentrierte Diary-Runs unter `Backend/execution_runs/`, ist aber im aktuellen Slice nicht mit einer nachweisbaren Pre-Compact- oder Context-Bridge-Pipeline verbunden.

## Abhängigkeiten
- Dateisystem als primaerer Persistenztraeger
- Python-Standardbibliothek fuer atomare Writes (`os.replace`, `tempfile.mkstemp`)
- tmux-/CLI-Umgebungsvariablen fuer Identity- und Home-Aufloesung
- `server.py` als zentraler Koordinator fuer Register-, Overlay- und Store-Schreibpfade

## Auffälligkeiten
- `team.json` ist weiter die Basiskonfiguration, aber auf API-Lesepfaden nicht die einzige wirksame Quelle.
- `runtime_team.json` ist im Ist-Zustand aktiv und ueberlagert reale Team-/Projektantworten.
- `board_api.py` fuehrt die Legacy-Welt `projects.json` weiterhin mit, obwohl die Doku `team.json` als SoT benennt.
- `agent_state` speichert einerseits operative CLI-Identity, andererseits grosse Mengen Test- und Experimentdaten mit uneinheitlicher Feldabdeckung.
- `bridge_cli_identity.py` kapselt nun den reinen Env->Transport- und SelfReflection-Seed-Pfad fuer CLI-Identity ausserhalb von `bridge_mcp.py`; die serverseitige Persistenz- und SoT-Diskussion bleibt davon unberuehrt.
- Die Memory-Landschaft ist weiterhin dreigeteilt: Workspace-`MEMORY.md`, `~/.claude*`-Auto-Memory und `Backend/agents/{id}/MEMORY.md`.

## Bugs / Risiken / Inkonsistenzen
- `team.json` als dokumentierte SoT und die reale API-Lesewelt laufen auseinander, solange Overlay-Merges und `projects.json`-Fallback aktiv bleiben.
- Der Register-Pfad benutzt fuer Auto-Index und Bootstrap von `MEMORY.md` weiterhin Legacy-`~/.claude*`-Pfadlogik statt den zentralen Helfer aus `persistence_utils.py`.
- `self_reflection.py` haelt den Legacy-Store `Backend/agents/{id}/MEMORY.md` weiter aktiv; damit bleibt Punkt 3 des Persistenzplans faktisch nur teilweise geschlossen.
- `agent_state` ist als Verzeichnis inhaltlich vermischt; es ist deshalb kein sauberer operativer SoT-Store fuer Identity oder Mode.
- Die Root-Doku zu `team.json` war bis zu diesem Update nicht am erwarteten Pfad `docs/config/team-json.md` vorhanden, sondern nur unter `Archiev/docs/config/team-json.md`.
- Workflow-/n8n-Artefakte bleiben mehrschichtig:
  - `workflow_registry.json.compiled_workflow` speichert die Bridge-Sicht des Deploys
  - das aktive n8n-Zielobjekt kann durch `_inject_bridge_workflow_auth_headers()` zusaetzliche Header-/Sender-Normalisierung tragen, die nicht 1:1 im Source-Artefakt sichtbar ist

## Offene Punkte
- Ob `Backend/projects.json` im aktuellen Live-Betrieb noch jemals als echter Fallback erreicht wird, ist ohne kontrollierten Serverstart ausserhalb des injizierten Team-Backends offen.
- Ob alle `agent_state`-Dateien bewusst aufbewahrt oder teilweise nur Testreste sind, ist nicht zentral klassifiziert.
- Ob die Register-seitige Memory-Indexierung kuenftig ausschliesslich ueber `persistence_utils.find_agent_memory_path()` laufen soll, ist eine Folgeentscheidung ausserhalb dieser Read-only-Pruefung.

## Live-Nachtrag 2026-03-12
- Verifiziert durch Ausführung:
  - `curl -fsS http://127.0.0.1:9111/tasks/summary`
  - `curl -fsS http://127.0.0.1:9111/board/projects`
  - `curl -fsS http://127.0.0.1:9111/team/projects`
  - `rg -n "self_reflection\\.py|_base / \\\"agents\\\" / agent_id / \\\"MEMORY\\.md\\\"|find_agent_memory_path\\(" Backend/*.py Backend/*/*.py -g '!*.bak*'`
- Der aktuelle Disk-vs-Live-Befund ist damit enger:
  - `tasks/summary` meldete live `2281` Aufgaben
  - `Backend/tasks.json` enthaelt `2300` Aufgaben, davon `19` geloescht
  - der beobachtete Live-Gesamtwert passt damit zum Disk-Store minus geloeschter Eintraege
- `/board/projects` und `/team/projects` zeigen aktuell sowohl Runtime-Overlay als auch persistierte Basisprojekte; die Lesewelt ist also mehrschichtig und nicht nur `runtime_team.json`.
- Der Legacy-Store `Backend/agents/{id}/MEMORY.md` ist im aktiven Codepfad weiterhin explizit in `Backend/self_reflection.py` verankert; fuer `server.py` laeuft die normale Aufloesung ueber `find_agent_memory_path()`.

## Offene Punkte
- Ob `runtime_team.json` nach jedem moeglichen Stop-Pfad deterministisch geloescht wird; verifiziert ist das nur fuer die getesteten Stop-Zyklen.
