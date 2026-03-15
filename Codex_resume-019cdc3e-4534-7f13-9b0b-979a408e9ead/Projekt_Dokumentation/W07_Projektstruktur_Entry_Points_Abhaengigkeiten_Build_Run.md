# W07_Projektstruktur_Entry_Points_Abhaengigkeiten_Build_Run

## Zweck
Dokumentation der realen Projektstruktur, Entry-Points, Abhaengigkeiten sowie Build- und Run-Pfade im `/BRIDGE`-Scope fuer den Slice Runtime, Entry-Points, Packaging und Build.

## Scope
Root von `/home/leo/Desktop/CC/BRIDGE` sowie `Backend/server.py`, `Backend/runtime_layout.py`, `Backend/bridge_watcher.py`, `Backend/output_forwarder.py`, `Backend/common.py`, `Backend/agent_liveness_supervisor.py`, `Backend/start_platform.sh`, `Backend/stop_platform.sh`, `Backend/restart_wrapper.sh`, `Backend/start_agents.py`, `Backend/config.py`, `Backend/tests/test_process_stability_contract.py`, `Backend/tests/test_output_forwarder_strict_auth_contract.py`, `Backend/tests/test_agent_liveness_supervisor_contract.py`, `Backend/tests/test_packaging_contract.py`, `Backend/tests/test_workflow_bot_contract.py`, `Frontend/chat_workflow_buttons.spec.js`, `bridge_ide/`, `Archiev/bridge_ide/cli.py`, `Archiev/bridge_ide/_backend_path.py`, `Dockerfile`, `docker-compose.yml` und `entrypoint.sh`.

## Evidenzbasis
- `/home/leo/Desktop/CC/BRIDGE/pyproject.toml`
- `/home/leo/Desktop/CC/BRIDGE/setup.py`
- `/home/leo/Desktop/CC/BRIDGE/README.md`
- `/home/leo/Desktop/CC/BRIDGE/entrypoint.sh`
- `/home/leo/Desktop/CC/BRIDGE/Dockerfile`
- `/home/leo/Desktop/CC/BRIDGE/docker-compose.yml`
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
- `/home/leo/Desktop/CC/BRIDGE/Backend/tests/test_process_stability_contract.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/tests/test_output_forwarder_strict_auth_contract.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/tests/test_agent_liveness_supervisor_contract.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/tests/test_packaging_contract.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/tests/test_workflow_bot_contract.py`
- `/home/leo/Desktop/CC/BRIDGE/Frontend/chat_workflow_buttons.spec.js`
- `/home/leo/Desktop/CC/BRIDGE/bridge_ide/__init__.py`
- `/home/leo/Desktop/CC/BRIDGE/bridge_ide/_backend_path.py`
- `/home/leo/Desktop/CC/BRIDGE/bridge_ide/cli.py`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/bridge_ide/cli.py`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/bridge_ide/_backend_path.py`
- verifizierende Shell-Checks im Working Tree:
  - `python3 -c "import bridge_ide.cli as cli; import bridge_ide._backend_path as bp; print(cli.build_parser().prog); print(bp.repo_root())"` -> `bridge-ide` plus Repo-Root
  - `python3 setup.py bdist_wheel` -> erfolgreich, Wheel unter `dist/bridge_ide-0.1.0-py3-none-any.whl`
  - `python3 -m pip install --no-deps --target /tmp/bridge_pkg_target dist/bridge_ide-0.1.0-py3-none-any.whl` -> erfolgreich
  - `PYTHONPATH=/tmp/bridge_pkg_target python3 -c "import bridge_ide.cli as cli; print(cli.build_parser().prog)"` -> `bridge-ide`
  - `python3 -m venv --system-site-packages /tmp/bridge_pkg_venv3 && /tmp/bridge_pkg_venv3/bin/pip install -e . --no-deps --no-build-isolation` -> erfolgreich
  - `/tmp/bridge_pkg_venv3/bin/bridge-ide status --url http://127.0.0.1:9111` -> erfolgreicher Live-Status-Read
  - `env PATH=/tmp/bridge_pkg_venv3/bin:$PATH bridge-ide stop` -> erfolgreicher Live-Stop
  - `env PATH=/tmp/bridge_pkg_venv3/bin:$PATH bridge-ide start` -> erneuter erfolgreicher Live-Start bis `Platform is running.`; der frueher beobachtete `8787`-Fehler ist geschlossen und der Wrapper meldete `UI server already running (tmux session: ui8787)`
  - `docker run --rm hello-world` -> erfolgreich
  - `.dockerignore`-Fix reduzierte den realen Build-Kontext von mehr als `7 GB` auf rund `84 MB`
  - `/usr/bin/sg docker -c 'docker build -t bridge-e2e-local:20260313 .'` -> erfolgreich
  - isolierter Containerlauf auf Host-Port `19111` -> externer `GET /status` real `200`
  - interner Container-Read:
    - `GET /runtime` -> `200`
    - `GET /workflows` -> `503 {"error":"n8n API key not configured ..."}`
    - `GET /n8n/executions?limit=5` ohne Auth -> `401`
  - `docker/compose:1.29.2 config` -> Compose-Manifest erfolgreich aufgeloest

## Ist-Zustand
Die Root-Struktur mischt Quellcode, Runtime-Daten, Dokumentation, persoenliche Bereiche und gebuendelte Alt- bzw. Packaging-Artefakte in einem gemeinsamen Baum.

Praegende Root-Bereiche im aktuellen Tree:

- aktive Runtime-Kerne: `Backend/`, `Frontend/`, `config/`, `Codex_resume-.../`
- operative Laufzeitdaten: `.agent_sessions/`, `Backend/agent_state/`, `Backend/messages/`, `Backend/logs/`, `Backend/pids/`
- historische, persoenliche oder archivierte Bereiche: `Archiev/`, `Frontend_persoenlich/`, diverse `*.bak`-Artefakte
- Packaging-Artefakte existieren jetzt zweischichtig:
  - aktiver Root-Pfad fuer `pyproject.toml`/`setup.py`: `bridge_ide/`
  - archivierter Altpfad unter `Archiev/`:
  - `Archiev/bridge_ide/`
  - `Archiev/build/`
  - `Archiev/bridge_ide.egg-info/`
  - `Archiev/UNKNOWN.egg-info/`

Verifizierte Entry-Points und Build-/Run-Befunde:

- `Backend/server.py`
  - bindet fest an HTTP `9111` und WebSocket `9112`
  - liefert `control_center.html` unter `/`
  - importiert `Backend/runtime_layout.py` fuer Runtime-Layout-, Pair-Mode- und Runtime-Spec-Aufloesung
  - enthaelt neben den Runtime-Endpunkten auch einen serverinternen Platform-Control-Pfad (`POST /platform/start|stop`), der Watcher/Forwarder und Auto-Start-Agenten direkt startet
  - dieser serverinterne Pfad loest die Forwarder-Session jetzt ebenfalls kanonisch aus `team.json` bzw. `FORWARDER_SESSION` auf und startet den Forwarder nicht mehr mit einem separaten harten `acw_manager`
  - enthaelt ausserdem die n8n-Proxy- und Workflow-Deploy-Pfade:
    - `GET /workflows`
    - `GET /n8n/executions`
    - `POST /workflows/deploy`
    - `POST /workflows/deploy-template`
    - `DELETE /workflows/{id}`
    - `GET /events/subscriptions`
- `Backend/runtime_layout.py`
  - enthaelt die aktuell extrahierten, reinen Helfer fuer Runtime-Layout-Aufloesung, Validierung und Profil-Ableitung
  - wird von `server.py` weiter ueber Wrapper-Funktionen genutzt, damit bestehende Call-Sites und Tests stabil bleiben
- `Backend/agent_liveness_supervisor.py`
  - ist ein neuer optionaler Langlauf-Helfer fuer Agent-Liveness
  - liest nur bestehende Bridge-Flaechen: `/runtime`, `/agents/{id}` und `/activity?agent_id=...`
  - nutzt fuer Eingriffe ausschliesslich `POST /agents/{id}/start`
  - ohne explizite `--agent`-Flags loest er die aktuellen Runtime-Agenten pro Iteration erneut aus `/runtime` auf
  - wenn `/runtime` temporaer leer ist, protokolliert der Helfer nur `agent_supervisor_runtime_empty` statt sich zu beenden
  - sichert Langlaeufe jetzt ueber `Backend/pids/agent_liveness_supervisor.pid` gegen Doppelstart ab
  - damit entsteht keine zweite Recovery- oder Start-SoT ausserhalb von `server.py`
- `Backend/start_platform.sh`
  - nutzt `ROOT_DIR=../..` und `BRIDGE_DIR=${ROOT_DIR}/BRIDGE/Backend`
  - setzt damit einen festen Parent-Layout- und Verzeichnisnamen `BRIDGE` voraus
  - startet Server-Supervisor, Runtime-Configure, Watcher, optionalen Forwarder, optionalen WhatsApp-Watcher, Auto-Start-Agenten und einen statischen UI-Server auf `8787`
  - raeumt davor einen verwaisten `python3 -m http.server 8787` ab, damit `ui8787` nicht an einer Altbelegung ausserhalb von tmux scheitert
  - uebergibt an `/runtime/configure` jetzt explizit `stabilize_seconds`, Default `30`
  - behandelt Auto-Start-Fehler nach erfolgreichem Runtime-Configure seit dem Hardening vom 2026-03-11 als degradierten Folgefehler statt als Totalausfall
  - loest die optionale Forwarder-Session kanonisch aus `team.json` auf:
    - aktiver `role=manager` bzw. Alias `manager|projektleiter|teamlead`
    - sonst aktiver Agent mit `level <= 1`
    - sonst Fallback `acw_manager`
- `Backend/stop_platform.sh`
  - nutzt dieselbe feste Root-Annahme
  - sendet vor dem eigentlichen Stop eine Restart-Warnung und wartet `60s`
  - bereinigt danach auch orphaned `bridge_mcp.py`-Prozesse
- `Backend/restart_wrapper.sh`
  - ist der serverseitige Auto-Restart-Wrapper mit Singleton-PID-Lock, Backoff und optionalem External-Bootstrap-Modus
  - startet im klassischen Pfad nach gesundem Server Watcher plus `start_agents.py`
  - besitzt keinen eigenen semantischen Self-Activity-/Liveness-Controller; diese Rolle liegt heute verteilt in `server.py`, `bridge_watcher.py` und `output_forwarder.py`
- `Backend/start_agents.py`
  - startet nur Agents mit `active=true` und `auto_start=true` ueber `POST /agents/{id}/start`
  - verweigert Starts, wenn `/runtime` nicht `configured=true` meldet
  - behauptet im Docstring einen Fallback auf `agents.conf`, implementiert ihn aber nicht
- `Backend/output_forwarder.py`
  - ist ein Hilfsprozess im Start-/Stop-Vertrag, kein eigener Runtime-Entry-Point fuer Agents
  - loest Agent-Session-Token ueber tmux-Session-Env plus `workspace/.bridge/agent_session.json` auf
  - schreibt darueber `/activity` und optional `/send`, aber keinen Heartbeat
- `Backend/tests/test_process_stability_contract.py`
  - bildet den aktuellen Prozessvertrag fuer Wrapper, Watcher, Forwarder, Stop-Orphans und Runtime-Configure ab
- `Backend/tests/test_output_forwarder_strict_auth_contract.py`
  - prueft den aktuellen Strict-Auth-Vertrag des Forwarders fuer `/send` ueber Agent-Session-Token
- `bridge_ide/cli.py`
  - bietet jetzt wieder den deklarierten Root-Entry-Point `bridge-ide init|start|stop|status`
  - `init` erzeugt Zielstruktur in einem frei waehlbaren Pfad
  - `start|stop|status` arbeiten weiter ueber `backend_dir()` und delegieren bevorzugt an `Backend/start_platform.sh`
- `bridge_ide/_backend_path.py`
  - Source-Checkout-Erkennung funktioniert im aktuellen Tree wieder relativ zum Repo-Root
  - Fallbacks bleiben: `BRIDGE_ROOT`, dann `~/Desktop/CC/BRIDGE` und `/opt/bridge-ide`
- `pyproject.toml` und `setup.py`
  - deklarieren `bridge-ide = bridge_ide.cli:main`
  - finden im aktuellen Tree wieder ein passendes Root-Paket `bridge_ide/`
- `Dockerfile`
  - kopiert nur `Backend/`, `Frontend/` und `entrypoint.sh`
  - kopiert den neuen Root-Pfad `bridge_ide/` derzeit ebenfalls nicht
  - setzt jetzt `PORT`, `WS_PORT`, `BRIDGE_HTTP_HOST=0.0.0.0` und `BRIDGE_WS_HOST=0.0.0.0`
  - der aktive `server.py` wertet diese Bind- und Port-Variablen jetzt aus
- `docker-compose.yml`
  - mountet die aktiven Control-Plane-Stores `messages`, `logs`, `uploads`, `agent_state/`, `team.json`, `automations.json`, `workflow_registry.json` und `event_subscriptions.json`
  - mountet bewusst kein `runtime_team.json`; der Containerpfad soll kein hostseitig eingebranntes Runtime-Overlay als zweite Wahrheit uebernehmen
  - deklariert nur den Service `bridge-server`; ein eigener n8n-Container fehlt weiterhin, aber `tokens.json` und `n8n.env` werden jetzt read-only in `/root/.config/bridge/` eingebunden und `N8N_BASE_URL` zeigt standardmaessig auf `http://host.docker.internal:5678`
- `entrypoint.sh`
  - initialisiert nur `team.json`, `automations.json`, `logs`, `pids`, `messages`
  - startet dann direkt `server.py`
- `.dockerignore`
  - schliesst jetzt grosse Nicht-Build-Baeume wie `Archiev/`, `.agent_sessions/`, `dist/`, `build/`, `Codex_resume-.../` und weitere Arbeits-/Artefaktpfade aus
  - ohne diese Ausschluesse schob der Docker-Build im verifizierten Erstlauf mehr als `7 GB` Kontext
- `Backend/config.py`
  - verwendet gleichzeitig `PROJECT_PATH / "BRIDGE"` und `PROJECT_PATH / "bridge"`
  - legt `MESSAGES_DIR` und `LOGS_DIR` unter dem lowercase-Pfad an
  - wird im geprueften Entry-Point-Slice nicht von `server.py`, `start_platform.sh`, `stop_platform.sh`, `start_agents.py`, `entrypoint.sh` oder der Wrapper-CLI importiert
- aktueller Live-Nachtrag 2026-03-12 nach dem Workflow-Integrationsschritt:
  - n8n ist ueber `~/.config/bridge/n8n.env` wieder erreichbar
  - `GET /workflows` und `GET /n8n/executions?limit=5` liefern real `200`
  - `GET /events/subscriptions` lieferte nach dem Cleanup `count=1`
  - der Read-/Proxy-Pfad lebt also, und die Bridge-managed Workflow-Kette ist auf einen kanonischen Satz reduziert:
    - `TXDHkBWw2JxHjt88` `Bridge: Daily Status Report`
    - `LNX09wVWFu3weiil` `Bridge: Wochenreport`
    - `XuyJQMbdQSqUujSP` `Bridge: Taegliche Chat-Zusammenfassung`
    - `ddvmNgWDKGlffSGd` `Bridge: Task-Benachrichtigung`
  - `POST /send` ohne `X-Bridge-Token` liefert unter `BRIDGE_STRICT_AUTH=true` real `401`
  - `python3 Backend/repair_n8n_bridge_auth.py --dry-run --limit 250` liefert im aktuellen Zustand `repaired_count=0`
  - der Integrationslauf musste zusaetzlich doppelte Template-Deploys und Builder-Probes per `DELETE /workflows/{id}` bereinigen, damit Daily-, Chat- und Task-Benachrichtigungs-Workflows nicht mehrfach feuern
  - `Frontend/chat_workflow_buttons.spec.js` lief danach real erfolgreich gegen den Live-Backendpfad:
    - Panel-Deploy
    - Toggle/Delete
    - Suggestion-Deploy

## Datenfluss / Kontrollfluss
Es existieren mehrere reale Startpfade mit unterschiedlicher Tiefe:

1. Dokumentierter Packaging-Pfad:
   - `README.md` beschreibt `pip install -e .` und danach `bridge-ide start`
   - dieser Pfad ist im aktuellen Tree wieder real tragfaehig:
     - editable install lief erfolgreich
     - der installierte CLI-Entry-Point `bridge-ide status` lieferte live den aktuellen Bridge-Status
2. Lokaler Shell-Pfad:
   - `Backend/start_platform.sh`
   - ist der tiefste, wirksamste Startpfad im aktiven Tree
3. Wrapper-Pfad:
   - `bridge_ide/cli.py`
   - delegiert bevorzugt an `Backend/start_platform.sh`, faellt sonst auf direkten `server.py`-Start zurueck
4. Docker-Pfad:
   - `Dockerfile` plus `entrypoint.sh`
   - startet nur den nackten Serverprozess
   - ist nach dem Bind-Fix jetzt von aussen erreichbar, bildet aber weiterhin nicht den vollen Plattformstart ab

Zusatzbefund zum aktuellen Stand 2026-03-11:
- Es gibt zwei produktive Startschichten fuer Hilfsprozesse:
  - Shell-Orchestrator `start_platform.sh`
  - serverinterne Platform-Control-Endpunkte in `server.py`
- Die Hilfsprozess-Lebenszyklen sind bereits mehrstufig:
  - `restart_wrapper.sh` haelt `server.py` am Leben
  - `server.py`-Threads supervisen `watcher` und `forwarder`
  - `stop_platform.sh` beendet genau diese bekannten Hilfsprozesse wieder
- Der neue Liveness-Supervisor ist bewusst nicht in diese Standard-Startkette integriert.
  - Er bleibt ein expliziter Opt-in-Loop.
  - Dadurch mussten `start_platform.sh`, `restart_wrapper.sh` und `stop_platform.sh` nicht erweitert werden.
- Fuer den Forwarder war das vorher eine reale Driftquelle.
- Verifiziert durch Ausfuehrung:
  - `POST /platform/start` liefert ohne vorhandene Manager-Session nun explizit `session=acw_ordo` plus sauberen Skip
  - mit vorhandener tmux-Session `acw_ordo` startet derselbe Pfad den Forwarder real und uebergibt `FORWARDER_SESSION=acw_ordo`
  - `bridge_mcp.py` persistiert den aktuellen Agent-Session-Token fuer Hilfsprozesse in `workspace/.bridge/agent_session.json`
  - `output_forwarder.py` loest den Workspace ueber tmux-Session-Env auf und nutzt denselben Agent-Session-Token fuer Helper-Requests gegen `/activity` und `/send`
  - `python3 Backend/agent_liveness_supervisor.py --once`
    - klassifizierte die laufenden Runtime-Agenten `codex` und `claude` live als `healthy`
  - `python3 Backend/agent_liveness_supervisor.py --once --agent codex --stale-seconds 1 --cooldown-seconds 0`
    - traf den echten `POST /agents/codex/start`-Pfad
    - serverseitige Antwort: `status=already_running`
  - `python3 Backend/agent_liveness_supervisor.py --interval 2 --duration-seconds 4`
    - lief real ueber mehrere Iterationen
    - schrieb JSONL-Nachweise nach `Backend/logs/agent_liveness_supervisor.log`
  - autonomer tmux-Lauf:
    - Session `bridge_liveness_supervisor`
    - Prozess `python3 Backend/agent_liveness_supervisor.py --interval 60 --duration-seconds 28800 --pid-file Backend/pids/agent_liveness_supervisor.pid`
    - Exit-Nachweis live in `Backend/logs/agent_liveness_supervisor.autonomous.log` belegt (`uptime_seconds=66336.4`)
  - Doppelstart-Block live verifiziert:
    - `python3 Backend/agent_liveness_supervisor.py --once --pid-file Backend/pids/agent_liveness_supervisor.pid`
    - Ergebnis: `{"ok": false, "error": "supervisor already running: Backend/pids/agent_liveness_supervisor.pid"}`
  - `stop_platform.sh` bereinigt jetzt nicht mehr nur Python-Orphans, sondern auch nackte BRIDGE-CLI-Prozesse:
    - Grundlage: `/proc/<pid>/environ`
    - Schluessel: `BRIDGE_CLI_SESSION_NAME`, `BRIDGE_CLI_INCARNATION_ID`
    - Vergleich gegen `tmux show-environment`
  - der Runtime-Agent `claude` ist im aktuellen produktiven Zustand an `sub2` gebunden:
    - `team.json` enthaelt jetzt `subscription_id=sub2`
    - `config_dir=/home/leo/.claude-sub2/`
    - ohne diese Zuordnung fiel der Runtime-Start real auf `~/.claude` zurueck und `runtime/configure` scheiterte mit `failed to start runtime agents: ['claude']`

## Abhängigkeiten
- Python >= 3.10
- `setuptools` fuer Packaging-Metadaten
- `websockets`, `croniter`, `websocket-client`, `httpx`, `mcp`, `watchdog` laut `pyproject.toml`
- `tmux` und `curl` fuer den lokalen Shell-Orchestrator
- Docker fuer den Containerpfad

## Auffälligkeiten
- Die aktive Wrapper-CLI liegt jetzt wieder am vom Packaging erwarteten Root-Pfad `bridge_ide/`; der archivierte Altpfad unter `Archiev/bridge_ide/` bleibt als historische Doppelung bestehen.
- `bridge-ide init` und `bridge-ide start` bilden keinen durchgehenden Pfad: Scaffolding-Ziel und Startziel sind entkoppelt.
- `Backend/config.py` ist nicht die zentrale Startkonfiguration dieses Slices, obwohl die Datei das beansprucht.
- Im Runtime-Pfad existiert bereits ein kleiner sauberer Split: `runtime_layout.py` kapselt reine Layout-Helfer, waehrend `server.py` Orchestrierung, Persistenz und Endpunkte behaelt.
- Docker ist ein Minimalpfad und nicht funktional gleich zum Shell-Orchestrator.
- Docker ist jetzt als separater, real verifizierter Control-Plane-/n8n-Proxy-Pfad dokumentiert; er ist nicht funktional gleich zum host-nativen Shell-Orchestrator.
- Im beobachteten Zustand ist `/home/leo/Desktop/CC/BRIDGE` kein Git-Root.
- Die kanonische Runtime-Gesundheit haengt im aktuellen Produktzustand nicht nur von der Shell-Orchestrierung, sondern auch von der korrekten Agent->Subscription-Zuordnung in `team.json` ab.
- Ein minimaler neuer Self-Activity-Supervisor wuerde dieses Kapitel unmittelbar betreffen, sobald er als eigener Prozess, eigener PID-Vertrag oder eigener Start-/Stop-Hook eingefuehrt wird.

## Bugs / Risiken / Inkonsistenzen
- Packaging- und README-Pfad sind im aktuellen Tree wieder konsistent genug fuer den dokumentierten Root-CLI-Pfad:
  - `pip install -e .` lief in einer lokalen venv erfolgreich
  - `bridge-ide status` lief gegen die reale Bridge erfolgreich
- verbleibende Packaging-/Run-Risiken:
  - `bridge-ide init` und `bridge-ide start` bilden weiterhin keinen vollstaendig pfadgebundenen Projekt-Scaffold-Lebenszyklus
  - die historische Doppelung `bridge_ide/` vs. `Archiev/bridge_ide/` kann kuenftig wieder Drift erzeugen
- `_backend_path.py` verlaesst sich im aktuellen Tree auf harte Fallback-Pfade statt auf eine selbstkonsistente Source-Checkout-Aufloesung.
- `start_platform.sh` und `stop_platform.sh` leiten `BRIDGE_DIR` bzw. `PID_DIR` jetzt skriptlokal aus `Backend/` ab; nur der `ROOT_DIR`-Bezug fuer den statischen UI-Pfad `8787` bleibt an die uebergeordnete Workspace-Ebene gekoppelt.
- `server.py` liest `PORT`, `WS_PORT`, `BRIDGE_HTTP_HOST` und `BRIDGE_WS_HOST` real aus der Umgebung; `docker-compose.yml` nutzt jetzt zusaetzlich env-gesteuerte Published-Ports.
- Der Compose-Pfad mountet jetzt die zentralen Control-Plane-Stores `messages`, `logs`, `uploads`, `agent_state`, `team.json`, `automations.json`, `workflow_registry.json` und `event_subscriptions.json`; `runtime_team.json` wird bewusst nicht uebernommen.
- `Backend/config.py` driftet sowohl in Gross-/Kleinschreibung als auch in Pfadbasis vom aktiven Runtime-Pfad weg.
- `agent_liveness_supervisor.py` ist aktuell kein Standardprozess des Plattformstarts.
  - Das reduziert Seiteneffekte.
  - Ein unbeaufsichtigter Langlauf muss deshalb explizit gestartet werden.
  - Watcher-seitige Idle-Nudges und Guard-Liveness bleiben bewusst getrennte Schichten.
- Fuer einen minimalen Self-Activity-Supervisor ist der Prozessvertrag heute noch eng:
  - `start_platform.sh` startet Watcher und Forwarder explizit
  - `server.py` superviset Watcher und Forwarder explizit
  - `stop_platform.sh` beendet Watcher und Forwarder explizit
  - `test_process_stability_contract.py` spiegelt genau diese Menge wider
- Daraus folgt: als eigener Prozess eingefuehrt, muesste ein Supervisor gleichzeitig in Start, Stop, Restart-Wrapper, Server-Supervisor und Prozessvertragstests auftauchen.

## Offene Punkte
- Ob `Archiev/bridge_ide/` nur Archiv oder kuenftige Referenz fuer alte Packaging-Artefakte sein soll, ist nicht zentral dokumentiert.
- Ob der Docker-Pfad bewusst nur fuer einen Minimalserver gedacht ist, ist nicht zentral beschrieben.

## Verifizierter Containerpfad
- Der Docker-/Compose-Pfad ist jetzt real end-to-end verifiziert.
  - verifiziert:
    - Docker-Daemon ist ueber `/usr/bin/sg docker -c ...` in diesem Arbeitskontext nutzbar
    - das Image baut erfolgreich
    - `docker/compose:1.29.2 config` loeste das Compose-Manifest erfolgreich auf
    - `docker/compose:1.29.2 up -d --build` startete den isolierten Compose-Lauf erfolgreich
    - `GET /status` auf `19111` lieferte real `200`
    - `GET /runtime` auf `19111` lieferte real `configured=false`, `running_count=0`, `agent_ids=[]`
    - `GET /workflows` und `GET /n8n/executions?limit=5` lieferten im Compose-Lauf mit gueltigem `X-Bridge-Token` real `200`
    - `GET /n8n/executions?limit=1` lieferte ohne Token real `401`
    - direkte Containerinspektion zeigte:
      - `runtime_team.json` fehlt im laufenden Container weiterhin bewusst
      - `/root/.config/bridge/tokens.json` und `/root/.config/bridge/n8n.env` sind gemountet
      - `codex`, `claude` und `n8n` fehlen im Image
    - `docker/compose:1.29.2 down` entfernte den isolierten Compose-Stack wieder erfolgreich
    - `docker ps` war danach wieder leer
    - `GET /status` auf `19111` war danach real nicht mehr erreichbar
    - der host-native Hauptpfad auf `9111` blieb parallel real gesund (`configured=true`)
  - daraus folgt:
    - der Containerpfad ist jetzt ein ehrlicher Bridge-Control-Plane-/n8n-Proxy-Pfad
    - er ist nicht der host-native CLI-Runtime-Pfad
  - lokaler Tooling-Nachtrag:
    - `docker compose` ist im Hostpfad dieses Agenten weiter kein direkter Befehl
    - die reale Compose-Ausfuehrung lief erfolgreich ueber `docker/compose:1.29.2`

## Offene Punkte
- Ob weitere externe Release- oder Packaging-Repositories ein noch konsistenteres `bridge_ide`-Layout fuehren.
