# Persistenz CLI SoT Implementierung

## Zweck
Arbeitsdokumentation fuer die Implementierung der Persistenzvertraege in `/BRIDGE`, mit der CLI als kanonischer Source of Truth fuer Agentenidentitaet, Home und laufzeitnahe Artefakte.

## Scope
- `/home/user/bridge/BRIDGE/Backend`
- Fokus: Identity, Home, Memory, Resume, Context-Bridge, Retrieval, Restart, Diary

## Harte Prämisse
- Die CLI ist die SoT fuer die persistente Agentenidentitaet.
- Der Server darf CLI-/Home-/Resume-Zustand spiegeln, pruefen und koordinieren, aber nicht eigenmaechtig als primaere Identitaetsquelle ersetzen.
- Wenn CLI-Zustand und Serverzustand auseinanderlaufen, ist Kontinuitaet nicht bewiesen.

## Arbeitsplan
1. CLI-SoT Pfadauflösung und kanonische Artefaktauflösung zentralisieren.
2. Identity/Home/Resume serverseitig an diese CLI-SoT anbinden.
3. Memory- und Context-Bridge-Aufloesung kanonisieren.
4. Knowledge-Retrieval fuer operative Aktionen erzwingbar machen.
5. Multi-Incarnation kontrollieren.
6. Start-/Restart-Pfad an der CLI-SoT ausrichten.
7. Diary-/Journal-Pipeline vor Compact anschliessen.
8. Reproduzierbare Tests und Runtime-Verifikation aufbauen.
9. Restliche Legacy-Abweichungen dokumentieren oder abbauen.

## Statuslog

### Batch 1
- Status: code-seitig umgesetzt, runtime-seitig teilweise verifiziert
- Ziel: kanonische CLI-Workspace-/Artefaktauflösung fuer Server, Watcher und Resume-Fallback einziehen
- Betroffene Dateien:
  - `Backend/persistence_utils.py`
  - `Backend/server.py`
  - `Backend/bridge_watcher.py`
  - `Backend/tmux_manager.py`
  - `Backend/tests/test_cli_persistence_layout.py`
- Umgesetzter Kern:
  - zentrale CLI-Layout-Helfer fuer `home_dir`, `workspace`, `project_root`
  - engine-spezifische Instruktionsdateierkennung mit Workspace-Prioritaet
  - serverseitige Restore-/Health-Aufloesung auf CLI-Workspace umgestellt
  - watcherseitige Context-Bridge- und Dynamic-Instruction-Updates auf CLI-Workspace umgestellt
  - Resume-Fallback liest nicht mehr starr nur Projekt-`CLAUDE.md`, sondern engine-spezifisch und workspace-first
- Erwartete Wirkung:
  - weniger Pfaddrift zwischen `home_dir` und `.agent_sessions/{agent_id}`
  - Codex wird bei dynamischen Instruktionsupdates nicht mehr implizit wie Claude behandelt
  - deterministischere Aufloesung fuer Restore, Health und Watcher
- Offene Punkte nach Batch 1:
  - Retrieval-Zwang ist noch nicht implementiert
  - Multi-Incarnation-Schutz noch nicht implementiert
  - Diary-/Journal-Pipeline noch nicht implementiert
  - Memory-Write-Pfade sind noch nicht voll konsolidiert

### Runtime-Neuverifikation zu Batch 1 am 2026-03-11
- Vorzustand verifiziert: Port `9111` war vor dem Test nicht erreichbar, relevante Bridge-Prozesse liefen nicht.
- Realer Neustart ueber `Backend/start_platform.sh` gestartet.
- Verifiziert wirksam im neuen Live-Code:
  - `/agents/codex/persistence` liefert jetzt `instruction_md` und `workspace`.
  - `codex` wird ueber `/home/user/bridge/BRIDGE/.agent_sessions/codex/AGENTS.md` bewertet und nicht mehr ueber ein fehlendes root-`CLAUDE.md`.
  - `/agents/backend/persistence` liefert die CLI-Workspace-Pfade unter `/home/user/bridge/BRIDGE/.agent_sessions/backend/...`.
  - `context_bridge_md` wird fuer aktive Agenten aus den CLI-Workspaces berichtet.
- Verifizierter Gegenbefund im selben Neustartlauf:
  - `/runtime` blieb nach dem Neustart auf `configured=false`.
  - `start_platform.sh` scheiterte wiederholt beim POST auf `/runtime/configure` mit `Remote end closed connection without response`.
  - Der Server wurde waehrend des Startpfads real neu gestartet; dadurch wurde der Configure-Schritt mindestens dreimal unterbrochen.
  - `start_agents.py` protokollierte weiterhin Fehlstarts fuer mehrere Auto-Start-Agents (`404` bzw. fehlendes `/home/user/bridge/BRIDGE/config/mcp_catalog.json`).
  - `/agents/assi/persistence` fiel weiterhin auf root-/Mischpfade zurueck (`/home/user/bridge/BRIDGE/CLAUDE.md`, kein `SOUL.md`, `healthy=false`).
- Schlussfolgerung:
  - Batch 1 ist fuer den aktiven Persistenz-Endpunkt wirksam verifiziert.
  - Der Start-/Restart-Vertrag ist damit noch nicht stabil. Die CLI-SoT-Aufloesung ist live, aber der kanonische Neustartpfad reproduziert die Runtime-Konfiguration noch nicht deterministisch.

## Verifizierter Restbefund nach Batch 1
- Batch 1 kanonisiert die Aufloesung fuer `SOUL.md`, `CONTEXT_BRIDGE.md` und engine-spezifische Instruktionsdateien workspace-first im aktiven Codepfad von `server.py`, `bridge_watcher.py` und `tmux_manager.py`.
- Historische Drift im Dateibaum ist dadurch nicht beseitigt. Reale Altartefakte ausserhalb aktiver CLI-Workspaces existieren weiterhin, unter anderem in `BRIDGE/Backend`, `BRIDGE/Frontend_persönlich` und `BRIDGE/Archiev/...`.
- `CONTEXT_BRIDGE.md` ist damit im aktiven Schreibpfad kanonischer adressiert, aber im Repository weiterhin mehrfach vorhanden; der Dateibaum ist also noch nicht auf einen einzigen Artefaktbestand bereinigt.
- `MEMORY.md` ist weiterhin ueber mindestens zwei reale Backends verteilt: runtime-/restore-seitig ueber `~/.claude*`-basierte Pfade und reflections-/lesson-seitig ueber `Backend/agents/{agent_id}/MEMORY.md`.
- Daraus folgt verifiziert: Batch 1 reduziert Pfaddrift in den aktiven CLI-SoT-Pfaden, eliminiert aber den historischen Driftbestand noch nicht und macht Altpfade ohne weitere Konsolidierung noch nicht bedeutungslos.

### Batch 2
- Status: code-seitig umgesetzt, live-seitig teilweise verifiziert
- Ziel: Punkt 2 des Arbeitsplans umsetzen und die serverseitige Register-Identitaet explizit an die CLI-SoT binden
- Betroffene Dateien:
  - `Backend/tmux_manager.py`
  - `Backend/bridge_mcp.py`
  - `Backend/server.py`
  - `Backend/tests/test_bridge_mcp.py`
  - `Backend/tests/test_status_model_contract.py`
  - `Backend/tests/test_codex_resume.py`
- Umgesetzter Kern:
  - `tmux_manager.py` exportiert beim CLI-Start die kanonische Arbeitsidentitaet in die Agent-Umgebung:
    - `BRIDGE_RESUME_ID`
    - `BRIDGE_CLI_WORKSPACE`
    - `BRIDGE_CLI_PROJECT_ROOT`
    - `BRIDGE_CLI_INSTRUCTION_PATH`
  - `bridge_mcp.py` liest diese Werte aus der laufenden CLI-Umgebung und schickt sie sowohl bei `bridge_register()` als auch bei `_auto_reregister()` an `/register`.
  - `server.py` normalisiert diese CLI-Identitaetsdaten, spiegelt sie in `REGISTERED_AGENTS`, persistiert sie im `agent_state` und surfaced sie in:
    - `GET /agents/{id}`
    - `GET /agents/{id}/persistence`
- Erwartete Wirkung:
  - Register-Zustand beschreibt nicht mehr nur `agent_id` plus Heartbeat, sondern die konkrete CLI-Arbeitsidentitaet.
  - Server und API koennen jetzt sauber zwischen gespiegelt ermittelter CLI-Identitaet und reiner Team-Home-Fallback-Zuordnung unterscheiden.
  - Auto-Re-Register nach Server-Restart behaelt dieselbe CLI-Identitaet im Transportpfad bei.
- Verifizierte Tests:
  - `pytest -q Backend/tests/test_bridge_mcp.py Backend/tests/test_status_model_contract.py Backend/tests/test_codex_resume.py`
  - Ergebnis: `39 passed`

### Runtime-Verifikation zu Batch 2 am 2026-03-11
- Reale Plattform-Neustartsequenz ueber `Backend/start_platform.sh` erneut ausgefuehrt.
- Verifiziert live:
  - Der neue `server.py`-Prozess ist aktiv; `GET /agents/codex` liefert nun die neuen Identitaetsfelder `resume_id`, `workspace`, `project_root`, `home_dir`, `instruction_path`, `cli_identity_source`.
  - Eine frische Probe-Registrierung ueber das **aktualisierte** `bridge_mcp.py` gegen den Live-Server belegt den End-to-End-Transportpfad:
    - Probe-Agent: `probe_cli_identity`
    - gesetzte CLI-Identitaet:
      - `resume_id=cccccccc-cccc-cccc-cccc-cccccccccccc`
      - `workspace=/tmp/bridge_cli_probe/.agent_sessions/probe_cli_identity`
      - `project_root=/tmp/bridge_cli_probe`
      - `instruction_path=/tmp/bridge_cli_probe/.agent_sessions/probe_cli_identity/AGENTS.md`
    - `GET /agents/probe_cli_identity` liefert exakt diese Werte live zurueck.
- Gleichzeitig verifiziert negativ:
  - `start_platform.sh` scheitert weiterhin bei `/runtime/configure` mit `Remote end closed connection without response`.
  - `GET /runtime` bleibt nach dem Neustart auf `configured=false`.
  - `start_agents.log` zeigt weiter `404`-Fehlstarts fuer Auto-Start-Agents.
  - `server.log` zeigt weiterhin fehlendes `/home/user/bridge/BRIDGE/config/mcp_catalog.json`.
- Schlussfolgerung:
  - Punkt 2 ist fuer Register-Transport und Server-Surfacing live **teilweise verifiziert**.
  - Nicht live verifiziert ist bislang die durch `tmux_manager.py` gestartete, frisch gebootete Managed-CLI-Instanz mit denselben neuen Env-Exports, weil der Restart-/Configure-Pfad weiterhin vor einem sauberen Auto-Start scheitert.

## Noch nicht verifiziert
- Neustartverifikation unter mehreren aufeinanderfolgenden erfolgreichen `start_platform.sh`-Laeufen ohne Configure-Abbruch.
- Vollstaendig deterministische Wiederherstellung von Runtime-Configure und Auto-Start auf einem frischen Fremdrechner.
- Live-End-to-End-Nachweis, dass ein frisch **durch `tmux_manager.py` gestarteter** Managed-Agent die neuen CLI-Identity-Exports ebenfalls bis `/register` transportiert.

### Batch 3
- Status: Punkt 6 abgeschlossen und live end-to-end verifiziert
- Ziel: Start-/Restart-Pfad fail-closed machen und auf einer real verfuegbaren Engine-Kombination bis durch den Wrapper-Restart stabil verifizieren
- Betroffene Dateien:
  - `Backend/server.py`
  - `Backend/tmux_manager.py`
  - `Backend/tests/test_runtime_configure_contract.py`
  - `Backend/tests/test_codex_resume.py`
  - `Backend/tests/test_process_stability_contract.py`
- Umgesetzter Kern:
  - `/runtime/configure` rollt jetzt auf `configured=false` zurueck, wenn ein Runtime-Agent gar nicht startet oder innerhalb des Stabilisationsfensters nicht registriert.
  - `server.py` loescht dabei Runtime-Overlay, Agent-Praesenz und `last_start_at` statt einen halb konfigurierten Zustand stehen zu lassen.
  - `tmux_manager.py` begrenzt den detached Init-Prompt-Wait fuer Codex auf `5s`, damit der Bootstrap-Prompt nicht laenger wartet als der Runtime-Registrierungspfad.
- Verifizierte Tests:
  - `pytest -q Backend/tests/test_codex_resume.py Backend/tests/test_runtime_configure_contract.py Backend/tests/test_process_stability_contract.py`
  - Ergebnis: `35 passed`

### E2E-Verifikation zu Batch 3 am 2026-03-11
- Negativpfad real verifiziert:
  - Beide realen Claude-Credential-Stores (`/home/user/.claude/.credentials.json`, `/home/user/.claude-sub2/.credentials.json`) waren abgelaufen.
  - `./start_platform.sh` im Default `codex-claude` lief deshalb reproduzierbar in `HTTP 500` auf `/runtime/configure`.
  - `GET /runtime` lieferte danach verifiziert:
    - `configured=false`
    - `project_name=""`
    - `agent_profiles=[]`
    - `last_start_at=null`
  - `tmux has-session -t acw_codex` und `tmux has-session -t acw_claude` lieferten danach beide `missing`.
  - `runtime_configure_audit.jsonl` protokollierte den neuen fail-closed Fehlertext:
    - `failed to start runtime agents: ['claude']`
- Positivpfad real verifiziert:
  - `env PAIR_MODE=codex-codex AGENT_A_ENGINE=codex AGENT_B_ENGINE=codex AUTO_START_AGENTS=0 ./start_platform.sh`
  - Ergebnis:
    - `configured=true`
    - `pair_mode=codex-codex`
    - `codex_a` und `codex_b` beide `tmux_alive=true`
    - beide `status=waiting`
    - beide real registriert
- Echter Restart ueber den Wrapper real verifiziert:
  - `POST /server/restart/force` mit `agents=restart` ausgeloest.
  - `GET /server/restart-status` zeigte den realen Zyklus `phase=stop` bis zur Rueckkehr auf `phase=null`.
  - Danach verifiziert:
    - `GET /status` mit neuer `uptime_seconds` von nur noch `17.948`
    - neue `registered_at`-Zeitstempel fuer `codex_a` und `codex_b` (`2026-03-11T15:42:56...+00:00`)
    - `GET /runtime` weiter `configured=true` mit beiden Runtime-Agents alive
    - `GET /health` insgesamt `status=ok`

## Verifizierter Schlussstand zu Punkt 6
- Punkt 6 ist abgeschlossen.
- Verifiziert ist jetzt:
  - harter Fail-Closed bei unstartbarer Runtime
  - erfolgreicher kanonischer Startpfad gegen `/home/user/bridge/BRIDGE`
  - erfolgreicher Wrapper-Restart zurueck in einen live registrierten `codex-codex`-Runtime-Zustand
- Der naechste offene Kernpunkt ist nicht mehr der Restart-Pfad, sondern Punkt 3: der vollstaendige Memory-/Context-Bridge-Vertrag im echten Runtime-Lauf.

### Batch 4
- Status: Punkt 2 abgeschlossen und live end-to-end verifiziert
- Ziel: Die CLI-Identity-Felder der gemanagten Codex-Runtime-Agents nicht nur im Shell-Env, sondern im realen Bridge-MCP-Transport sichtbar machen
- Betroffene Dateien:
  - `Backend/tmux_manager.py`
  - `Backend/tests/test_codex_resume.py`
- Umgesetzter Kern:
  - `tmux_manager.py` schreibt die CLI-Identity fuer Codex jetzt zusaetzlich in `[mcp_servers.bridge.env]` der agent-spezifischen `.codex/config.toml`.
  - Dadurch bekommen die von Codex gestarteten Bridge-MCP-Prozesse dieselben Werte fuer:
    - `BRIDGE_RESUME_ID`
    - `BRIDGE_CLI_WORKSPACE`
    - `BRIDGE_CLI_PROJECT_ROOT`
    - `BRIDGE_CLI_INSTRUCTION_PATH`
    - plus Session-/Incarnation-Metadaten
  - Der Codex-Init-Prompt-Wait bleibt dabei kurz genug, damit beide Runtime-Agents im echten `runtime/configure` registrieren.
- Verifizierte Tests:
  - `pytest -q Backend/tests/test_codex_resume.py Backend/tests/test_runtime_configure_contract.py`
  - Ergebnis: `13 passed`

### E2E-Verifikation zu Batch 4 am 2026-03-11
- Plattform mit frischem Codepfad neu gestartet:
  - `env PAIR_MODE=codex-codex AGENT_A_ENGINE=codex AGENT_B_ENGINE=codex AUTO_START_AGENTS=0 ./start_platform.sh`
- Verifiziert auf Disk:
  - [`codex_a .codex/config.toml`](/home/user/bridge/BRIDGE/.agent_sessions/codex_a/.codex/config.toml)
  - [`codex_b .codex/config.toml`](/home/user/bridge/BRIDGE/.agent_sessions/codex_b/.codex/config.toml)
  - Beide enthalten jetzt `[mcp_servers.bridge.env]` mit den CLI-Identity-Feldern.
- Verifiziert live:
  - `GET /agents/codex_a` liefert:
    - `resume_id=019cdd83-a611-71b3-95d5-b74aacd7ac90`
    - `workspace=/home/user/bridge/BRIDGE/.agent_sessions/codex_a`
    - `project_root=/home/user/bridge/BRIDGE`
    - `instruction_path=/home/user/bridge/BRIDGE/.agent_sessions/codex_a/AGENTS.md`
    - `cli_identity_source=cli_register`
  - `GET /agents/codex_b` liefert:
    - `resume_id=019cdd88-4154-7a61-997f-2ade08387ec4`

### Batch 5
- Status: Register-Transport fuer Claude-Hardening umgesetzt und live verifiziert
- Ziel: Claude-Registrierung nicht mehr davon abhaengig machen, dass der im CLI-Kontext gestartete `bridge_mcp.py` die Token-Datei ausserhalb des Agent-Workspaces selbst lesen kann
- Betroffene Dateien:
  - `Backend/tmux_manager.py`
  - `Backend/tests/test_auth_bootstrap_contract.py`
  - `Backend/tests/test_codex_resume.py`
- Umgesetzter Kern:
  - `tmux_manager.py` laedt den `register_token` hostseitig aus `BRIDGE_REGISTER_TOKEN` oder `~/.config/bridge/tokens.json`
  - `_bridge_runtime_env()` propagiert jetzt explizit:
    - `BRIDGE_TOKEN_CONFIG_FILE`
    - `BRIDGE_REGISTER_TOKEN`
  - dieselbe Runtime-Env landet dadurch sowohl im CLI-Startkommando als auch in der Bridge-MCP-Env der agent-spezifischen Konfigurationsdateien
- Erwartete Wirkung:
  - `bridge_register()` in Claude- und Codex-Agents braucht fuer den Erst-Registerpfad keinen Dateizugriff ausserhalb des Agent-Workspaces mehr
  - der kanonische `codex-claude`-Bring-up wird nicht mehr daran blockiert, dass `claude` trotz laufender TUI auf `/register` nur `403` produziert
- Verifizierte Tests:
  - `pytest -q Backend/tests/test_auth_bootstrap_contract.py Backend/tests/test_codex_resume.py Backend/tests/test_process_stability_contract.py`
  - Ergebnis: `49 passed`

### Runtime-/Control-Plane-Nachtrag am 2026-03-11 spaet
- Status: weitere Live-Verifikation und Kanonisierung des Forwarder-/Manager-Pfads umgesetzt
- Verifiziert durch Ausfuehrung:
  - native Claude-Auth fuer `ordo` auf dem in `team.json` konfigurierten `config_dir` ist wieder gueltig
  - `env CLAUDE_CONFIG_DIR=/home/user/.claude-sub2 claude -p ok --output-format text` liefert `OK.`
  - `server.py` nutzte vor dem Fix einen zweiten Forwarder-Startpfad mit hartem `acw_manager`; dieser Pfad loeste die Manager-Session nicht wie `start_platform.sh` aus `team.json` auf
  - `server.py` nutzt jetzt fuer `/platform/start` und fuer den Supervisor dieselbe kanonische Session-Aufloesung wie der Shell-Orchestrator:
    - explizites `FORWARDER_SESSION`, falls gesetzt
    - sonst aktiver `role=manager` bzw. Alias `manager|projektleiter|teamlead`
    - sonst aktiver Agent mit `level <= 1`
    - sonst Fallback `acw_manager`
- Negativpfad live verifiziert:
  - `POST /platform/start` liefert ohne passende Manager-Session jetzt explizit
    - `"forwarder": {"started": false, "reason": "forwarder script or session missing", "session": "acw_ordo"}`
  - der Supervisor schreibt in diesem Zustand nur noch `supervisor skip: tmux session 'acw_ordo' missing`, statt blind einen ungebundenen Forwarder neu zu starten
- Positivpfad live verifiziert:
  - mit einer isolierten tmux-Session `acw_ordo` startete `POST /platform/start` den Forwarder explizit auf dieser Session
  - `/proc/<pid>/environ` des frischen Forwarders enthielt `FORWARDER_SESSION=acw_ordo`
  - `Backend/logs/output_forwarder.log` zeigte:
    - `Started PID=... sessions=['acw_ordo']`
    - `pipe-pane attached to acw_ordo`
    - `Sent activity: typing (from acw_ordo)`
  - `GET /activity?agent_id=ordo` lieferte dazu live `action=typing`
- Runtime-Zustand nach Abschluss wiederhergestellt:
  - manueller `POST /runtime/configure` mit explizitem `stabilize_seconds=30` lieferte wieder `configured=true`
  - Runtime-Agenten `codex` und `claude` waren danach beide real registriert und `tmux_alive=true`

## Offenes Restrisiko
- Der optionale Forwarder-Relay-Pfad (`RELAY_AGENTS` -> `POST /send`) ist unter `BRIDGE_STRICT_AUTH=true` weiterhin nicht belastbar:
  - `/activity` funktioniert live
  - `/send` bleibt fuer diesen Hilfsprozess semantisch offen, weil User-Token dort nicht beliebig als Agent senden duerfen
- `start_platform.sh` faellt im Standardlauf weiter in kurze `runtime/configure`-Fehlerfenster, waehrend der manuelle Configure-Lauf mit laengerem Stabilisationsfenster erfolgreich war.

### Runtime-Verifikation zu Batch 5 am 2026-03-11
- Vor dem Fix live reproduziert:
  - manueller Host-Register-Call mit echtem `X-Bridge-Register-Token` gegen `POST /register` lieferte `200`
  - dieselbe Claude-Session produzierte bei manuell injiziertem `bridge_register(agent_id="claude", role="Agent B")` nur `POST /register 403`
  - `bridge_mcp.py` in der Claude-Session hatte `BRIDGE_TOKEN_CONFIG_FILE`, aber kein explizites `BRIDGE_REGISTER_TOKEN` im Prozess-Env
- Nach dem Fix live verifiziert:
  - isolierter Claude-Einzelstart ueber `POST /agents/claude/start` fuehrte zu realer Registrierung von `claude`
  - `GET /agents/claude` lieferte live:
    - `registered_at=2026-03-11T20:34:46.054910+00:00`
    - `cli_identity_source=cli_register`
    - `resume_id=bfe2b74e-e980-4739-8c16-a4b9281b4824`
  - kanonischer Neustart ueber `Backend/start_platform.sh` im Default `codex-claude` lieferte wieder erfolgreich `configured=true`
  - `GET /runtime` lieferte live:
    - `configured=true`
    - `running_count=2`
    - Runtime-Agents `codex` und `claude` beide `tmux_alive=true`
  - `server.log` enthielt in derselben Neustartsequenz:
    - `[register] Agent registered: codex`
    - `[register] Agent registered: claude`
  - anschliessender Harness:
    - `python3 Backend/verify_cli_runtime_e2e.py --engines codex --restart-count 1 --scenario-timeout 180`
    - Ergebnis: `status: ok`
    - Punkt 6 `Start-/Restart-Pfad an der CLI-SoT ausrichten` = `SUCCESS`

## Neuer Restrisiko-Stand nach Batch 5
- Der Register-Blocker fuer `claude` im kanonischen `codex-claude`-Bring-up ist live behoben.
- Weiter offen und separat zu behandeln:
  - `start_platform.sh` kann trotz `configured=true` am nachgelagerten `start_agents.py` mit Exit-Code `1` enden, wenn zusaetzliche Auto-Start-Agents fehlschlagen.
  - alte/orphaned `bridge_mcp.py`-Prozesse ausserhalb der aktuellen Runtime erzeugen weiter `POST /register 403`-Rauschen in `server.log` und erschweren die Diagnose.
  - `bridge_watcher.py` und `output_forwarder.py` senden im aktuellen Stand `/activity` bzw. `/state/{agent}` noch ohne Auth-Header.
    - `workspace=/home/user/bridge/BRIDGE/.agent_sessions/codex_b`
    - `project_root=/home/user/bridge/BRIDGE`
    - `instruction_path=/home/user/bridge/BRIDGE/.agent_sessions/codex_b/AGENTS.md`
    - `cli_identity_source=cli_register`

## Verifizierter Schlussstand zu Punkt 2
- Punkt 2 ist abgeschlossen.
- Verifiziert ist jetzt:
  - `tmux_manager.py` exportiert die kanonische CLI-Identity
  - `bridge_mcp.py` transportiert diese Identity
  - `server.py` spiegelt sie in Register-State und Agent-Detail-APIs
  - gemanagte Codex-Runtime-Agents liefern dieselben Werte im echten Live-Lauf bis `GET /agents/{id}`

### Batch 6
- Status: Startpfad-, Watcher-/Forwarder-Auth- und Orphan-Cleanup-Hardening umgesetzt und live verifiziert
- Ziel:
  - den kanonischen Startpfad nicht mehr durch nachgelagerte Auto-Start-Fehler falsch als Totalausfall zu beenden
  - Auto-Start auf echte `auto_start=true`-Agents begrenzen
  - Strict-Auth fuer `bridge_watcher.py` und `output_forwarder.py` im Live-Betrieb schliessen
  - alte `bridge_mcp.py`-Orphans beim Stop sicher entfernen
- Betroffene Dateien:
  - `Backend/start_agents.py`
  - `Backend/start_platform.sh`
  - `Backend/stop_platform.sh`
  - `Backend/restart_wrapper.sh`
  - `Backend/server.py`
  - `Backend/common.py`
  - `Backend/bridge_watcher.py`
  - `Backend/output_forwarder.py`
  - `Backend/tests/test_start_agents_contract.py`
  - `Backend/tests/test_auth_bootstrap_contract.py`
  - `Backend/tests/test_process_stability_contract.py`
- Umgesetzter Kern:
  - `start_agents.py` laedt jetzt nur noch Agents mit `active=true` und `auto_start=true`
  - `start_platform.sh` behandelt Auto-Start-Fehler nach erfolgreichem Runtime-Configure als degradierten Folgefehler statt als Totalausfall und meldet diesen sichtbar
  - `server.py` nutzt dieselbe `active && auto_start`-Semantik fuer `POST /platform/start` und `POST /platform/stop`
  - `stop_platform.sh` bereinigt jetzt auch orphaned `bridge_mcp.py`-Prozesse und fuehrt diesen Cleanup selbst dann aus, wenn keine PID-Dateien mehr vorliegen
  - `common.py` kapselt jetzt wiederverwendbar:
    - `load_bridge_user_token()`
    - `build_bridge_auth_headers()`
    - `build_bridge_ws_auth_message()`
  - `bridge_watcher.py` nutzt diese Helfer jetzt fuer:
    - `POST /team/reload`
    - `POST /activity`
    - `POST /state/{agent}`
    - WebSocket-Auth vor `subscribe`
  - `output_forwarder.py` nutzt dieselben Header-Helfer fuer `POST /activity` und `POST /send`

### Runtime-Verifikation zu Batch 6 am 2026-03-11
- Verifizierte Tests:
  - `pytest -q Backend/tests/test_start_agents_contract.py Backend/tests/test_auth_bootstrap_contract.py Backend/tests/test_process_stability_contract.py Backend/tests/test_watcher_runtime_routes.py Backend/tests/test_context_bridge_updates.py`
  - Ergebnis: `52 passed`
- Verifiziert durch Ausfuehrung:
  - `Backend/stop_platform.sh`
    - entfernte real neun alte/orphaned `bridge_mcp.py`-Prozesse (`pid=3129281`, `3134141`, `3134147`, `3134153`, `3134159`, `3134165`, `3134172`, `3220859`, `3260804`)
    - danach zeigte `ps -ef | rg "bridge_mcp.py|bridge_watcher.py|output_forwarder.py"` keine verbliebenen Bridge-Prozesse mehr
  - `Backend/start_platform.sh`
    - erster und zweiter `runtime/configure`-Versuch liefen real in `HTTP 500`
    - dritter Versuch fuehrte live zu `configured=true`
    - der nachgelagerte Auto-Start lief danach mit genau 4 statt zuvor 6 Kandidaten:
      - `ordo`
      - `codex`
      - `codex_2`
      - `codex_3`
    - `ordo` scheiterte weiter reproduzierbar an abgelaufenem Claude-Credential-Store:
      - `WARN: OAuth token expired`
      - `ABORT: Credential validation failed for ordo`
    - der Wrapper meldete trotzdem korrekt degradiert weiter:
      - `agent auto-start degraded`
      - `Platform is running.`
  - `GET /status`
    - live: `online_ids=["claude","codex","codex_2","codex_3"]`
  - `GET /runtime`
    - live: `configured=true`
    - `running_count=2`
    - Runtime-Agents `codex` und `claude` beide `tmux_alive=true`
  - `server.log`
    - keine neuen `POST /register 403` nach dem bereinigten Neustart
    - `POST /team/reload HTTP/1.1" 200`
    - `POST /agents/codex_2/start HTTP/1.1" 200`
    - `POST /agents/codex_3/start HTTP/1.1" 200`
  - `watcher.log`
    - reale `agent_state synced for ...`-Eintraege statt der frueheren `HTTP Error 401: Unauthorized`
    - `server TEAM_CONFIG reload: {'ok': True, ...}`
    - kein erneuter Watcher-eigener `4001 unauthorized`-Loop im aktuellen Neustartfenster
  - Prozessbild nach Neustart:
    - genau vier aktuelle `bridge_mcp.py`-Prozesse fuer `codex`, `claude`, `codex_2`, `codex_3`
    - ein `bridge_watcher.py`
    - ein `output_forwarder.py`
  - Harness:
    - `python3 Backend/verify_cli_runtime_e2e.py --engines codex --restart-count 1 --scenario-timeout 180`
    - Ergebnis: `status: ok`
    - Punkt 6 `Start-/Restart-Pfad an der CLI-SoT ausrichten` = `SUCCESS`

## Neuer Restrisiko-Stand nach Batch 6
- Geloest:
  - Auto-Start-Semantik driftet im Shell-Pfad nicht mehr auf `active=true`
  - `start_platform.sh` beendet den Gesamtstart nach gesundem Runtime-Configure nicht mehr falsch mit Exit-Code `1`
  - orphaned `bridge_mcp.py`-Prozesse werden im kanonischen Stop-Pfad real entfernt
  - Watcher-HTTP-POSTs und der Watcher-Team-Reload laufen unter Strict-Auth wieder real
- Weiter offen und separat zu behandeln:
  - `ordo` bleibt ein realer externer Blocker im Auto-Start-Slice, weil dessen Claude-Credentials abgelaufen sind
  - `server.log` zeigt weiterhin vereinzelte `first message not auth`-WebSocket-Treffer von nicht identifizierten Clients; der Watcher selbst laeuft im aktuellen Neustartfenster jedoch ohne erneuten Unauthorized-Loop
  - `output_forwarder.py` wurde code- und testseitig gehaertet, sein Auth-Pfad war im aktuellen Neustart jedoch mangels passender Manager-Session nicht als eigener Live-POST separat ausloesbar

### Nachtrag Kandidat 2 am 2026-03-11
- Status: kleiner Refactor-Schritt in `bridge_mcp.py` umgesetzt und live gegen die laufende Bridge verifiziert
- Betroffene Dateien:
  - `Backend/bridge_mcp.py`
  - `Backend/bridge_cli_identity.py`
  - `Backend/tests/test_bridge_mcp.py`
- Umgesetzter Kern:
  - Der reine CLI-Identity-/Heartbeat-Helferblock wurde aus `bridge_mcp.py` nach `bridge_cli_identity.py` extrahiert.
  - `bridge_mcp.py` behaelt unveraendert die MCP-Toolnamen, HTTP-/WebSocket-Pfade und Background-Task-Semantik und nutzt den neuen Helper nur ueber Wrapper.
- Verifizierte Tests:
  - `pytest -q Backend/tests/test_bridge_mcp.py`
  - Ergebnis: `26 passed`
- Verifiziert live gegen die laufende Bridge:
  - direkter Register-Transport ueber `bridge_register()` mit echtem `X-Bridge-Register-Token`
  - direkter Heartbeat ueber `bridge_heartbeat()`
  - anschliessender Live-Read von `GET /agents/probe_live_cli_identity`
  - verifizierter Rueckkanal:
    - `resume_id=11111111-2222-3333-4444-555555555555`
    - `workspace=/tmp/probe_live_cli_identity/.agent_sessions/probe_live_cli_identity`
    - `project_root=/tmp/probe_live_cli_identity`
    - `instruction_path=/tmp/probe_live_cli_identity/.agent_sessions/probe_live_cli_identity/AGENTS.md`
    - `cli_identity_source=cli_register`
    - `heartbeat.registered=true`
- Schlussfolgerung:
  - Der Kandidat-2-Teilschnitt ist nicht nur testseitig, sondern auch ueber den echten `bridge_mcp.py`-Transportpfad gegen die aktive Runtime verifiziert.

## Read-only Ist-Abgleich am 2026-03-11
- Kein Code geaendert. Nur erneuter Abgleich gegen den aktuellen Haupt-Workspace.
- Verifiziert:
  - `persistence_utils.find_agent_memory_path()` sucht `MEMORY.md` workspace-first, faellt danach aber weiterhin auf `~/.claude-agent-{id}`, `~/.claude-sub2`, `~/.claude` und einen Glob-Fallback zurueck.
  - `server.py` umgeht diese Helfer im Register-Pfad noch teilweise:
    - Auto-Index scannt nur `~/.claude-agent-{id}`.
    - Memory-Bootstrap erzeugt nur Legacy-`~/.claude*`-Pfade und nicht `workspace/MEMORY.md`.
  - `self_reflection.py` bevorzugt zwar denselben CLI-Memory-Pfad wie Restore/Health, haelt aber den Legacy-Fallback `Backend/agents/{agent_id}/MEMORY.md` aktiv.
  - Reale Legacy-Dateien existieren aktuell unter `Backend/agents/buddy/MEMORY.md` und `Backend/agents/codex_a/MEMORY.md`.
  - `agent_state` ist kein sauberer Einzelstore fuer operative Identity:
    - Snapshot: `3049` Dateien.
    - reale Mischmenge aus Runtime-Dateien und `_test_*`, `churn_*`, `claimiso_*`.
    - Schema ist uneinheitlich: `codex_a.json` enthaelt CLI-Identity-Felder, `assi.json` nicht.
  - `runtime_team.json` ueberlagert im aktiven Code mehrere Team-/Projekt-Endpunkte; `team.json` ist damit nicht die einzige wirksame Lesewahrheit.
  - `execution_journal.py` speichert agentenzentrierte Diary-Runs in `Backend/execution_runs/`, aber eine belegte automatische Ueberfuehrung nach `CONTEXT_BRIDGE.md` vor Compact ist in diesem Slice weiterhin nicht sichtbar.

## Schlussfolgerung nach dem Read-only-Abgleich
- Punkt 2 bleibt verifiziert.
- Punkt 3 ist weiter nur teilweise geschlossen:
  - Aufloesung workspace-first: verifiziert.
  - Schreib- und Bootstrap-Pfade voll konsolidiert: nicht verifiziert.
- Punkt 7 ist weiter nur teilweise vorbereitet:
  - Diary-Store vorhanden.
  - Pre-Compact- oder Context-Bridge-Anschluss im hier geprueften Scope nicht belegt.

### Batch 7
- Status: Start-/Relay-Haertung umgesetzt und live verifiziert
- Betroffene Dateien:
  - `Backend/start_platform.sh`
  - `Backend/common.py`
  - `Backend/bridge_mcp.py`
  - `Backend/output_forwarder.py`
  - `Backend/tests/test_process_stability_contract.py`
  - `Backend/tests/test_bridge_mcp.py`
  - `Backend/tests/test_output_forwarder_strict_auth_contract.py`
- Umgesetzter Kern:
  - `start_platform.sh` uebergibt an `/runtime/configure` jetzt explizit `stabilize_seconds`, Default `30`.
  - `bridge_mcp.py` spiegelt den aktuellen Agent-Session-Token nach erfolgreichem `bridge_register()` und `_auto_reregister()` kontrolliert in den Agent-Workspace:
    - `workspace/.bridge/agent_session.json`
  - `output_forwarder.py` loest den Agent-Workspace ueber tmux-Session-Env (`BRIDGE_CLI_WORKSPACE`/`BRIDGE_CLI_HOME_DIR`) auf und nutzt fuer Helper-Requests den dort gespiegelten Agent-Session-Token statt eines User-Token-Bypass.
- Verifizierte Tests:
  - `pytest -q Backend/tests/test_output_forwarder_strict_auth_contract.py Backend/tests/test_bridge_mcp.py Backend/tests/test_runtime_configure_contract.py Backend/tests/test_process_stability_contract.py`
  - Ergebnis: `58 passed`
- Verifiziert live:
  - kanonischer Neustart ueber `Backend/stop_platform.sh` -> `Backend/start_platform.sh`
  - `start_platform.sh` endete mit Exit-Code `0`
  - `GET /runtime` lieferte danach wieder `configured=true`, `pair_mode=codex-claude`
  - `GET /agents/ordo` lieferte live:
    - `workspace=/home/user/bridge/BRIDGE/.agent_sessions/ordo`
    - `cli_identity_source=cli_register`
  - reale Helper-Token-Datei vorhanden:
    - `/home/user/bridge/BRIDGE/.agent_sessions/ordo/.bridge/agent_session.json`
    - `agent_id=ordo`
    - `source=bridge_mcp`
    - `session_token` Laenge `64`
  - echter Live-Relay-POST ueber den aktualisierten Helper-Pfad:
    - `output_forwarder.send_relay_message("ordo", "user", "[relay-live-probe] ...", session_name="acw_ordo")`
    - Ergebnis: `SEND_OK True`
    - `GET /history?limit=30` enthielt anschliessend die persistierte Nachricht:
      - `from=ordo`
      - `to=user`
      - `meta.type=relay`
      - `meta.source=output_forwarder`
  - Runtime-Harness:
    - `python3 Backend/verify_cli_runtime_e2e.py --engines codex --restart-count 1 --scenario-timeout 180`
    - Ergebnis: `status: ok`

### Batch 8
- Status: UI-Token-Rotation und BRIDGE-CLI-Orphan-Cleanup umgesetzt und live verifiziert
- Betroffene Dateien:
  - `Frontend/chat.html`
  - `Frontend/control_center.html`
  - `Frontend/ui_token_refresh.spec.js`
  - `Backend/stop_platform.sh`
  - `Backend/tests/test_ui_strict_auth_contract.py`
  - `Backend/tests/test_process_stability_contract.py`
  - `Backend/team.json`
- Umgesetzter Kern:
  - `chat.html` und `control_center.html` behandeln jetzt nicht nur HTTP-`403 invalid session token`, sondern auch WebSocket-Close `4001 unauthorized` als UI-Token-Drift und loesen einen gedrosselten `_bridge_token_refresh` aus.
  - `stop_platform.sh` bereinigt jetzt auch nackte BRIDGE-markierte CLI-Orphans:
    - liest `BRIDGE_CLI_SESSION_NAME` und `BRIDGE_CLI_INCARNATION_ID` aus `/proc/<pid>/environ`
    - vergleicht gegen live-tmux-Session-Env
    - killt nur Prozesse, die keiner tmux-Session mehr gehoeren oder eine stale Incarnation tragen
  - Der aktuelle Runtime-Agent `claude` wurde ueber den vorhandenen Produktpfad `PUT /agents/claude/subscription` kanonisch auf `sub2` gelegt; dadurch ist `config_dir=/home/user/.claude-sub2/` jetzt echte `team.json`-Wahrheit.
- Verifizierte Tests:
  - `pytest -q Backend/tests/test_ui_strict_auth_contract.py`
    - Ergebnis: `6 passed`
  - `pytest -q Backend/tests/test_process_stability_contract.py Backend/tests/test_ui_strict_auth_contract.py`
    - Ergebnis: `33 passed`
  - Browser-Livecheck:
    - `NODE_PATH="$(npm root -g)" npx playwright test Frontend/ui_token_refresh.spec.js --reporter=line`
    - Ergebnis: `2 passed`
- Verifiziert live:
  - kanonischer Stop:
    - `Backend/stop_platform.sh`
    - Logbeleg: `stopping orphan bridge_cli (pid=3220839 session=acw_claude_probe)`
    - anschliessend war PID `3220839` verschwunden und `GET /status` nicht mehr erreichbar
  - kanonischer Restart:
    - erster `Backend/start_platform.sh`-Lauf scheiterte historisch real an `claude` ohne Subscription-Zuordnung
    - historischer Befund in `server.log`: `Credential validation failed for claude. Token expired or missing`
    - Befund in `team.json`: `claude` hatte vorher `config_dir=""` und `subscription_id=""`
  - kanonische Recovery:
    - `PUT /agents/claude/subscription` mit `subscription_id=sub2`
    - danach `team.json`-Beleg:
      - `config_dir=/home/user/.claude-sub2/`
      - `subscription_id=sub2`
    - erneuter `Backend/start_platform.sh`-Lauf lieferte:
      - `configured=true`
      - Runtime-Agents `codex` und `claude` beide gestartet
  - historischer Live-Nachtrag vor dem aktuellen Cleanup:
    - `/home/user/.claude/.credentials.json` und `/home/user/.claude-sub2/.credentials.json` trugen in diesem Zwischenstand gueltige Token-Expiries
    - die damals noch aktive operative Prevalidation in `tmux_manager.py` scheiterte trotzdem auf beiden Profilen bei `claude -p ok --output-format text` mit `You've hit your limit · resets Mar 16, 2am (Europe/Berlin)`
  - aktueller Live-Nachtrag nach dem Credential-Blind-Cleanup:
    - `tmux_manager.py` fuehrt fuer Claude keine Datei-Prevalidation und keine nicht-interaktive `claude -p ok`-Runtimeprobe mehr aus
    - `POST /agents/claude/start` liefert im aktuellen Live-Lauf stattdessen `status=manual_setup_required`
    - `POST /runtime/configure` projiziert den Fail-Closed-Zustand nun ueber offizielle Sessionzustaende in `failed[]`, konkret `interactive_setup/login_required` oder spaeter `runtime_stabilization/registration_missing`
  - Live-Endzustand:
    - `GET /status`:
      - `registered_count=6`
      - `online_ids=["backend","claude","codex","codex_2","codex_3","ordo"]`
    - `GET /runtime`:
      - `configured=true`
      - `pair_mode=codex-claude`
      - `codex`/`claude` beide `tmux_alive=true`
    - `ps -ef | rg "(^leo .*claude|/claude )"` zeigte danach nur noch:
      - den gewollten `acw_claude`-Claude-Prozess
      - keinen zweiten BRIDGE-Resume-Orphan mehr
  - Runtime-Harness:
    - `python3 Backend/verify_cli_runtime_e2e.py --engines codex --restart-count 1 --scenario-timeout 180`
    - Ergebnis: `status: ok`
