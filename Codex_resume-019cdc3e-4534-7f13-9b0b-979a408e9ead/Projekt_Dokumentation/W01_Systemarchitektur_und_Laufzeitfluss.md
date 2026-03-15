# W01_Systemarchitektur_und_Laufzeitfluss

## Zweck
Abbildung der realen Systemarchitektur und des Laufzeitflusses innerhalb von `/BRIDGE` fuer den Slice Runtime, Entry-Points, Build und Run.

## Scope
Architektur- und Runtime-Schichten innerhalb von `/home/leo/Desktop/CC/BRIDGE`, insbesondere `Backend/server.py`, `Backend/runtime_layout.py`, `Backend/bridge_watcher.py`, `Backend/output_forwarder.py`, `Backend/common.py`, `Backend/agent_liveness_supervisor.py`, `Backend/start_platform.sh`, `Backend/stop_platform.sh`, `Backend/restart_wrapper.sh`, `Backend/start_agents.py`, `bridge_ide/cli.py`, `bridge_ide/_backend_path.py`, `Archiev/bridge_ide/cli.py`, `Archiev/bridge_ide/_backend_path.py`, `Dockerfile`, `docker-compose.yml`, `entrypoint.sh` und `Backend/config.py`.

## Evidenzbasis
- `/home/leo/Desktop/CC/BRIDGE/Backend/server.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/runtime_layout.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/bridge_watcher.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/output_forwarder.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/common.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/agent_liveness_supervisor.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/start_platform.sh`
- `/home/leo/Desktop/CC/BRIDGE/Backend/stop_platform.sh`
- `/home/leo/Desktop/CC/BRIDGE/Backend/restart_wrapper.sh`
- `/home/leo/Desktop/CC/BRIDGE/Backend/start_agents.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/config.py`
- `/home/leo/Desktop/CC/BRIDGE/bridge_ide/cli.py`
- `/home/leo/Desktop/CC/BRIDGE/bridge_ide/_backend_path.py`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/bridge_ide/cli.py`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/bridge_ide/_backend_path.py`
- `/home/leo/Desktop/CC/BRIDGE/Dockerfile`
- `/home/leo/Desktop/CC/BRIDGE/docker-compose.yml`
- `/home/leo/Desktop/CC/BRIDGE/entrypoint.sh`
- verifizierende Shell-Checks im Working Tree:
  - `python3 -c "import bridge_ide.cli as cli; import bridge_ide._backend_path as bp; print(cli.build_parser().prog); print(bp.repo_root())"` -> `bridge-ide` plus Repo-Root
  - `python3 setup.py bdist_wheel` -> erfolgreich
  - `python3 -m pip install --no-deps --target /tmp/bridge_pkg_target dist/bridge_ide-0.1.0-py3-none-any.whl` -> erfolgreich
  - `PYTHONPATH=/tmp/bridge_pkg_target python3 -c "import bridge_ide.cli as cli; print(cli.build_parser().prog)"` -> `bridge-ide`
  - `/tmp/bridge_pkg_venv3/bin/bridge-ide status --url http://127.0.0.1:9111` -> erfolgreicher Live-Status-Read
  - `env PATH=/tmp/bridge_pkg_venv3/bin:$PATH bridge-ide stop` -> erfolgreicher Live-Stop mit Abschluss `platform stopped`
  - `env PATH=/tmp/bridge_pkg_venv3/bin:$PATH bridge-ide start` -> erneuter erfolgreicher Live-Start bis `Platform is running.`, Runtime `configured=true`; der frueher beobachtete `8787`-Fehler ist durch Orphan-Bereinigung geschlossen, und der Wrapper meldete danach `UI server already running (tmux session: ui8787)`

## Ist-Zustand
Die Runtime-Architektur ist praktisch sechsstufig:

1. Wrapper- und Packaging-Schicht:
   - Das aktive Wrapper-Paket fuer `pyproject.toml` und `setup.py` liegt im aktuellen Tree wieder unter `/BRIDGE/bridge_ide`.
   - Der Altpfad `/BRIDGE/Archiev/bridge_ide` existiert weiter als archivierte Doppelung.
   - `cli.py` bietet `init`, `start`, `stop`, `status`.
   - `cmd_init()` erstellt zwar frei waehlbare Zielverzeichnisse, aber `cmd_start()`, `cmd_stop()` und `cmd_status()` arbeiten ausschliesslich ueber `backend_dir()` und nicht ueber den bei `init` angelegten Pfad.
   - `_backend_path.py` prueft zuerst `BRIDGE_ROOT`, danach einen relativen Source-Checkout-Pfad und faellt sonst auf feste Kandidaten (`~/Desktop/CC/BRIDGE`, `/opt/bridge-ide`) zurueck.
   - Im aktiven Root-Paket greift der relative Source-Checkout-Pfad im aktuellen Tree wieder, weil `bridge_ide/_backend_path.py` zwei Ebenen nach oben auf den Repo-Root zeigt und dort `Backend/server.py` findet.

2. Server-Kern:
   - `Backend/server.py` bindet fest an `127.0.0.1:9111` und `127.0.0.1:9112`.
   - `/` und `/ui` liefern `Frontend/control_center.html`; statische HTML-, CSS-, JS- und Bilddateien werden direkt aus `Frontend/` ausgeliefert.
   - Die Runtime-Layout-, Pair-Mode- und Runtime-Spec-Helfer sind nicht mehr ausschliesslich in `server.py` gebuendelt; `server.py` delegiert diesen Teil inzwischen an `Backend/runtime_layout.py`.
   - Der Server nutzt eigene Konstanten fuer Ports und Basisverzeichnisse; `Backend/config.py` ist fuer diesen Startpfad keine wirksame Source of Truth.

3. Shell-Orchestrierung:
   - `Backend/start_platform.sh` ist der tiefste lokale Startpfad im aktiven Code.
   - Das Skript restabilisiert zuerst nur den Server-Supervisor, prueft `/status`, schickt dann `POST /runtime/configure` mit Retry-Logik und startet erst danach Watcher, optional Output-Forwarder und WhatsApp-Watcher, Auto-Start-Agenten und einen zusaetzlichen statischen UI-Server auf Port `8787`; ein verwaister `python3 -m http.server 8787` wird davor explizit abgeraeumt.
   - Die Runtime-Env fuer gemanagte CLIs propagiert inzwischen nicht mehr nur `BRIDGE_TOKEN_CONFIG_FILE`, sondern auch explizit `BRIDGE_REGISTER_TOKEN`; dadurch haengt der Erst-Registerpfad der Bridge-MCP-Prozesse nicht mehr davon ab, dass die CLI-Laufzeit die Token-Datei ausserhalb des Agent-Workspaces selbst lesen kann.
   - `Backend/stop_platform.sh` stoppt die Plattform nicht sofort: erst `/runtime/stop`, dann Restart-Warnung an `all`, danach `sleep 60`, erst dann PID-Dateien, Orphans, einen verwaisten `python3 -m http.server 8787` und die tmux-Sessions `ui8787` und `whatsapp_watcher`.

4. Agent-Startschicht:
   - `Backend/start_agents.py` startet nur `active=true`-Agents aus `team.json` ueber `POST /agents/{id}/start`.
   - Vorher wird `/runtime` abgefragt; ohne `configured=true` bricht das Skript ab.
   - Der Dateikopf behauptet einen Fallback auf `agents.conf`, die aktuelle Implementierung enthaelt diesen Fallback nicht mehr.

5. Liveness-, Nudge- und Supervisor-Schicht:
   - `Backend/server.py` betreibt parallel mehrere Hintergrundschichten:
     - `_agent_health_checker()` mit 10s-Zyklus
     - `_health_monitor_loop()` mit 60s-Zyklus
     - `_supervisor_daemon_loop()` mit 30s-Zyklus
     - `_heartbeat_prompt_loop()` mit 300s-Zyklus
   - `agent_connection_status()` leitet Liveness nicht nur aus `last_heartbeat`, sondern ueber `_agent_liveness_ts()` aus `REGISTERED_AGENTS.last_heartbeat` plus `AGENT_LAST_SEEN` aus `/receive`- und `/send`-Traffic ab.
   - `_compute_health()` bewertet Agenten zusaetzlich gegen tmux-Lebenszeichen und Context-Prozent; Warnungen und Kritikalitaet laufen ueber die systemische Message-Ebene an `ordo` und im kritischen Fall an `user`.
   - `_PROCESS_SUPERVISOR_STATE` und `_supervisor_check_and_restart()` ueberwachen derzeit nur die Hilfsprozesse `watcher` und `forwarder`; das ist Prozess-Supervision, keine semantische Agenten-Liveness.
   - `Backend/bridge_watcher.py` bildet eine zweite, davon getrennte Supervisor-Ebene:
     - Context-Monitor
     - Context-Bridge-Refresh
     - Codex-/Claude-Poll-Daemons
     - Behavior-Watcher
     - Memory-Health
     - resilienter WebSocket-Reconnect mit Auth
   - `Backend/output_forwarder.py` liefert kein Heartbeat-Signal. Der Prozess leitet nur abgeleitete Self-Activity (`POST /activity`, Action `typing`) aus tmux-Spinner-/Statuszeilen ab und kann optional Relay-Nachrichten ueber `POST /send` schreiben.
   - `Backend/agent_liveness_supervisor.py` ist ein neuer optionaler externer Guard:
     - liest die aktuellen Runtime-Agenten ueber `/runtime`
     - prueft pro Agent `/agents/{id}` und `/activity`
     - loest die Runtime-Agenten ohne explizite `--agent`-Flags pro Iteration neu auf und bleibt bei temporaer leerem `/runtime` im Loop
     - greift nur ueber `POST /agents/{id}/start` ein
     - verhindert Doppelstarts ueber `Backend/pids/agent_liveness_supervisor.pid`
     - bleibt damit unter der serverseitigen Start-/Nudge-SoT

6. Container- und Minimalpfad:
   - `entrypoint.sh` initialisiert nur `team.json`, `automations.json`, `logs`, `pids` und `messages` und startet dann direkt `python3 -u /app/Backend/server.py`.
   - Der verifizierte Compose-Pfad ist damit bewusst ein Control-Plane-/n8n-Proxy-Profil und nicht der kanonische Host-Runtime-Pfad:
     - `docker-compose.yml` mountet die dateibasierten Control-Plane-Stores `messages`, `logs`, `uploads`, `agent_state`, `team.json`, `automations.json`, `workflow_registry.json` und `event_subscriptions.json`
     - `${HOME}/.config/bridge/tokens.json` und `${HOME}/.config/bridge/n8n.env` werden in den Container gemountet
     - `N8N_BASE_URL` wird im Compose-Profil auf `http://host.docker.internal:5678` umgebogen
     - `GET /status` und `GET /runtime` liefen im isolierten Compose-Lauf auf `19111/19112` real erfolgreich
     - `GET /runtime` lieferte dort bewusst `configured=false`, `running_count=0`, `agent_ids=[]`
     - `GET /workflows` und `GET /n8n/executions?limit=5` lieferten im Compose-Lauf mit gueltigem `X-Bridge-Token` real `200`
     - `GET /n8n/executions?limit=1` lieferte ohne Token im Compose-Lauf real `401`
     - direkte Containerinspektion zeigte `missing:codex`, `missing:claude`, `missing:n8n`

## Datenfluss / Kontrollfluss
Der beobachtbare Laufzeitfluss ist:

1. Optionaler Wrapper-Pfad ueber `bridge-ide` loest `backend_dir()` auf; im aktuellen Tree zeigt der relative Source-Checkout-Fall des Root-Pakets wieder auf `/home/leo/Desktop/CC/BRIDGE/Backend`, und `bridge-ide status` wurde gegen den laufenden Server real verifiziert.
2. `Backend/start_platform.sh` restabilisiert zuerst den Server-Supervisor und wartet auf einen stabilen `/status`.
3. Danach konfiguriert das Skript die Managed Runtime ueber `POST /runtime/configure`; erst nach `configured=true` folgen Watcher und Auto-Start.
4. `server.py` bedient UI auf `9111` und WebSocket auf `9112` und startet gleichzeitig die internen Background-Control-Loops fuer Health-Monitor, Agent-Health, Nudge und Prozess-Supervision.
5. `bridge_watcher.py` setzt darauf eine zweite Runtime-Schicht fuer Context-Warnungen, Prompt-/Idle-Nudges, `POST /activity` und `POST /state/{agent}`.
6. `output_forwarder.py` liefert dazu nur best-effort-Self-Activity aus tmux-Output; das Signal ist abgeleitet und kein Ersatz fuer Heartbeats.
7. Parallel startet `start_platform.sh` einen zweiten statischen UI-Pfad auf `8787`, der das Repo-Root ausliefert.
8. `start_agents.py` startet Team-Agents ausschliesslich ueber Server-APIs; der Prozess-Spawn liegt damit im Server bzw. in dessen Runtime-Helfern.
9. Docker umgeht diese Shell-Orchestrierung bewusst und startet nur den nackten Serverprozess; nach dem Container-Hardening liefert dieser Pfad jetzt eine ehrliche Control Plane ohne eingebranntes Runtime-Overlay und mit funktionierendem n8n-Lesepfad.
10. Ein optionaler Langlauf-Guard kann parallel zur laufenden Runtime laufen, ohne neue Produktzustandsdateien anzulegen; der einzige neue Laufzeitnachweis ist `Backend/logs/agent_liveness_supervisor.log`.

## Abhängigkeiten
- Python >= 3.10
- `websockets`, `httpx`, `mcp`, `croniter`, `watchdog`, `websocket-client` laut `pyproject.toml`
- `tmux`, `curl` und `python3` fuer den lokalen Shell-Orchestrator
- dateibasierte Stores unter `Backend/`
- optionale Zusatzdienste wie WhatsApp-Watcher, n8n und Browser-/Desktop-Integrationen

## Auffälligkeiten
- Es gibt mindestens zwei reale UI-Serving-Pfade: dynamisch ueber `server.py:9111` und statisch ueber `http.server:8787`.
- `Backend/config.py` formuliert einen zentralen Konfigurationsanspruch, haengt aber nicht am aktiven Entry-Point-Pfad dieses Slices.
- Eine erste kleine Modularisierung im Runtime-Slice ist bereits real vorhanden: `Backend/runtime_layout.py` enthaelt die extrahierte Layout-/Spec-Logik, waehrend Orchestrierung und Seiteneffekte weiter in `server.py` liegen.
- Die Wrapper-CLI ist im aktuellen Working Tree von der dokumentierten Root-Struktur entkoppelt.
- Der lokale Shell-Pfad ist deutlich orchestrierter als der Docker-Pfad.
- Die Laufzeit nutzt bereits zwei getrennte Supervisor-Ebenen:
  - serverintern fuer Health, Cleanup, Prozess-Restarts und Nudges
  - watcher-intern fuer Context-, Prompt- und Behavior-Recovery
- Ein minimaler neuer Self-Activity-Supervisor waere deshalb kein erster Supervisor, sondern muesste sich in diese bestehende Doppelschicht einordnen.
- Der kanonische Default-Pfad `start_platform.sh` -> `runtime/configure` -> `codex-claude` ist am 2026-03-11 wieder real erfolgreich bis `configured=true` verifiziert worden; der nachgelagerte Auto-Start-Block kann trotzdem noch separat fehlschlagen.
- Seit dem Hardening-Batch vom 2026-03-11 gilt fuer den Shell-Pfad zusaetzlich:
  - `start_agents.py` und `POST /platform/start` behandeln nur noch `active=true` und `auto_start=true` als echte Auto-Start-Kandidaten
  - `start_platform.sh` meldet nachgesundem Runtime-Configure Auto-Start-Fehler jetzt degradiert weiter statt den Gesamtstart falsch als Totalausfall zu beenden
  - `stop_platform.sh` entfernt im kanonischen Stop-Pfad jetzt auch orphaned `bridge_mcp.py`-Prozesse
- Neuer Live-Nachtrag 2026-03-12:
  - `agent_liveness_supervisor.py --once` klassifizierte die laufende Runtime `codex`/`claude` real als `healthy`
  - ein Probe-Lauf gegen `codex` traf den echten `POST /agents/codex/start`-Pfad und erhielt `status=already_running`
  - ein kurzer Mehrfachlauf (`--interval 2 --duration-seconds 4`) lief ueber mehrere Iterationen und schrieb JSONL-Nachweise
  - der autonome tmux-Lauf schrieb einen echten Exit-Nachweis mit `uptime_seconds=66336.4` in `Backend/logs/agent_liveness_supervisor.autonomous.log`
  - ein paralleler Doppelstart wurde live ueber den PID-Lock abgewiesen
  - die anschliessende Gegenpruefung gegen `server.py` und `bridge_watcher.py` zeigte: `/activity`-Idle ist im aktuellen System nur eine Projektion, keine kanonische Guard-Wahrheit; daher bleibt der Guard bewusst heartbeat-/statusgetrieben

## Bugs / Risiken / Inkonsistenzen
- Die historische Doppelung `bridge_ide/` vs. `Archiev/bridge_ide/` bleibt ein Drift-Risiko.
- Das Root-Paket ist im aktuellen Tree wieder konsistent installier- und importierbar; der Archivpfad unter `Archiev/bridge_ide/` bleibt aber ohne zentrale Kanonizitaetsmarkierung erhalten.
- `start_platform.sh` und `stop_platform.sh` leiten `BRIDGE_DIR` bzw. `PID_DIR` jetzt skriptlokal aus `Backend/` ab; nur `ROOT_DIR` bleibt fuer den statischen UI-Pfad `8787` an die uebergeordnete Workspace-Ebene gebunden.
- Docker und Shell-Orchestrierung sind nicht semantisch gleich: Docker startet nur `server.py`, Shell startet zusaetzlich Supervisor, Runtime-Configure, Watcher, Auto-Start und Zusatz-UI.
- `server.py` liest `PORT`, `WS_PORT`, `BRIDGE_HTTP_HOST` und `BRIDGE_WS_HOST` real aus der Umgebung; der Compose-Pfad nutzt jetzt zusaetzlich env-gesteuerte Published-Ports.
- Liveness und Self-Activity sind nicht kanonisch vereinheitlicht:
  - Heartbeats und `AGENT_LAST_SEEN` werden in `server.py` zusammengefuehrt
  - der Watcher schreibt zusaetzliche Activity-/State-Signale
  - der Forwarder liefert nur spinnerbasierte `typing`-Impulse
- Ein neuer minimaler Self-Activity-Supervisor wuerde deshalb nicht nur Messaging, sondern auch den Runtime-Topologievertrag beruehren.
- `start_platform.sh` hat weiterhin zwei operative Phasen mit unterschiedlicher Erfolgssemantik:
  - Runtime-Configure kann erfolgreich sein (`configured=true`, Runtime gesund)
  - der nachgelagerte `start_agents.py`-Block kann trotzdem degradiert sein, wenn externe Agent-Starts wie `ordo` an abgelaufenen Credentials scheitern
- Der neue Liveness-Guard ist bewusst nicht Teil dieser Standard-Startkette.
  - Das vermeidet Default-Seiteneffekte.
  - Langlaeufe bleiben ein expliziter Opt-in.

## Offene Punkte
- Ob der UI-Server auf `8787` operativ noch benoetigt wird, ist aus der statischen Analyse nicht ableitbar.
- Ob `bridge-ide init` im Alltag ueberhaupt mit `bridge-ide start` kombiniert wird, ist offen; der Code verbindet beide Befehle nicht.
- Der Docker-Pfad ist jetzt als Control-Plane-Profil real verifiziert; volle CLI-Runtime-Paritaet ist im aktuellen Image nicht vorhanden.

## Offene Punkte
- Ob zusaetzlich ein vollwertiger nativer CLI-Runtime-Pfad innerhalb desselben Containerprofils ueberhaupt Produktziel sein soll.
- Ob alle optionalen Hintergrundprozesse im Standardbetrieb gewollt sind.
