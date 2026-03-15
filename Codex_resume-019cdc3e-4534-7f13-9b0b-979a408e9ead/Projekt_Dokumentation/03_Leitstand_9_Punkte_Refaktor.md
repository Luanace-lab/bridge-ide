# 03_Leitstand_9_Punkte_Refaktor

## Zweck
Kanonische Fuehrungs- und Arbeitsdokumentation fuer den laufenden `server.py`-Refactor im Haupt-Workspace.

## Scope
- `/home/user/bridge/BRIDGE`
- Fokus: kontrollierte Zerlegung von `Backend/server.py` in Handler-Module
- Parallelziel: Dokumentation und Runtime-Verifikation im selben Arbeitsgang frisch halten

## Evidenzbasis
- `/home/user/bridge/BRIDGE/AGENTS.md`
- `/home/user/bridge/Viktor/CLAUDE.md`
- `/home/user/bridge/Viktor/Refaktoring_Plan_server_py.md`
- `/home/user/bridge/Viktor/CONTEXT_BRIDGE.md`
- `/home/user/bridge/Viktor/Slice_00_Freeze.md` bis `/home/user/bridge/Viktor/Slice_49_codex_poll_gating.md`
- `/home/user/bridge/BRIDGE/Backend/server.py`
- `/home/user/bridge/BRIDGE/Backend/handlers/`
- `/home/user/bridge/BRIDGE/Backend/daemons/`
- `/home/user/bridge/BRIDGE/Backend/tests/`

## Ist-Zustand
Verifiziert durch Ausführung.

- Claude ist gestoppt.
- Codex fuehrt den Refactor im Haupt-Workspace allein weiter.
- Bridge-MCP-Persistenz ist aktuell nicht nutzbar (`Transport closed`).
- Operativer persistenter Kontext liegt bis zur Wiederherstellung in:
  - `/home/user/bridge/Viktor/CONTEXT_BRIDGE.md`
  - `/home/user/bridge/Viktor/Slice_*.md`
  - dieser repo-internen SoT
- Aktueller Live-Zustand:
  - Leo-Anweisung 2026-03-14 ist operativ umgesetzt: nur `codex` bleibt aktiv
  - Eingeschobene Creator/Data-Pruefung (2026-03-15) real abgeschlossen:
    - `server.py` dispatcht `/data/*`
    - `Backend/bridge_mcp.py` enthaelt Creator-/Data-MCP-Tools fuer Voices/Library und Data-Register/Ingest/Profile/Query/Run
    - Creator live bestaetigt aus User- und Agent-Perspektive
    - Data live bestaetigt aus User- und Agent-Perspektive
    - `bridge_creator_voiceover`-Contract korrigiert
    - `/creator/search` liefert ohne `GOOGLE_API_KEY` jetzt `400` statt `500`
  - Eingeschobene MCP-Library-Pruefung (2026-03-15) real abgeschlossen:
    - Library-Datei liegt real unter `config/capability_library.json`
    - `5387` Eintraege bestaetigt
    - Builder reproduzierbar
    - Capability-Library-Endpunkte real grün
    - Qualitaetsbefund: `bestof_mcp_servers` liefert derzeit grossenteils Kategorie-/Aggregator-Noise und ist nicht als produktreife Source freizugeben
  - Neuer Delivery-/Buddy-Recheck (2026-03-15) real abgeschlossen:
    - historischer Replay-Sturm nach Agent-Restart war auf fehlende Cursor-Wiederherstellung beim `/register` zurueckzufuehren
    - `last_message_id_received` wurde vor Slice 108 zwar persistiert, aber nicht wieder in `_CURSORS` uebersetzt
    - Fix:
      - `Backend/handlers/messages.py::cursor_index_after_message_id(...)`
      - `Backend/server.py::_restore_receive_cursor_from_state(...)`
    - Live-Nachweis:
      - `system -> buddy` Heartbeat-Marker
      - `user -> buddy` Live-Marker
      - Antworten:
        - `buddy -> system`
        - `buddy -> user`
      - Buddy zog nach Restart real nur noch die frischen Marker statt grosser Altlog-Buffers
    - Forwarder-Einordnung:
      - `forwarder.session="acw_ordo"`
      - Buddy-Nachrichtenzustellung funktionierte trotzdem
      - daraus folgt: Forwarder ist nicht der primaere Nachrichtentransport
  - aktueller Re-Check:
    - `Backend/team.json` -> nur `codex.active=true`
    - `/status` -> `registered_count=1`, `online_count=1`, `disconnected_count=0`
    - `/runtime` -> `configured=true`, `pair_mode=multi`, `agent_ids=["codex"]`
    - `/health` -> `status=ok`
    - `/agents/buddy` -> `online=false`, `status=offline`
    - `user -> all_managers`:
      - ohne aktive Manager -> `/send` liefert `warning`, `delivery_count=0`, `delivery_targets=[]`
      - mit temporaer aktiviertem `ordo` -> `/send` liefert `delivery_targets=["ordo"]`, `delivery_count=1`
      - `GET /receive/ordo?limit=10` enthaelt die Broadcast-Nachricht real
  - Forwarder-Einordnung unter Ein-Agent-Betrieb:
    - `forwarder.status=ok`
    - `running=false`
    - `required=false`
    - Grund: bewusst kein aktiver Manager-/Lead-Sessionpfad
- Buddy-Widget-Nachverifikation:
    - Buddy-Statusdot folgt jetzt `/agents/buddy` statt statisch gruen zu bleiben
    - `user -> buddy` wird im Widget nach History-Merge nicht mehr doppelt gerendert
    - der Verlauf scrollt in den Themes `warm|light|rose|dark|black` real im Browser-Regressionslauf
- Slice-47-Nachverifikation:
  - `agent -> system` ist serverseitig wieder erlaubt
  - interne `to:"system"`-/`to:"watcher"`-Nachrichten werden im Main-Chat nicht mehr gerendert
  - Live-Beleg:
    - `POST /send` mit echtem Codex-Session-Token -> `201`, `codex -> system`
    - `chat.html` zeigt die Testnachricht `SLICE47_SYSTEM_ROUTE_LIVE` real **nicht**
  - Persistenzkorrektur:
    - externe Codex-MEMORY angepasst auf `System routing is valid again`
  - Delivery-Architektur bleibt aktuell hybrid:
    - Push: WebSocket / watcher / MCP buffer
    - Fallback/Nudge: `bridge_receive`, `/receive`, `codex_poll`
  - Slice-48-Nachverifikation:
    - Doppelzustellung aus `WS buffer -> /receive fallback` ist im MCP-Pfad jetzt clientseitig dedupliziert
    - Live-Probe mit isoliertem `delivery_probe_*`:
      - erste echte Message-ID gilt als bereits gesehen
      - Fallback liefert real nur die neue zweite ID
      - nachfolgender Fallback liefert leer
- Die nach Slice 35 beobachtete Runtime-Drift ist inzwischen real als separater MCP-/Registrierungsfehler eingegrenzt und behoben:
  - `Backend/bridge_mcp.py::bridge_receive()` auto-registriert nun CLI-Agents und faellt bei leerem lokalem Buffer auf `GET /receive/{agent_id}?wait=0&limit=50` zurück
  - Re-Check nach kanonischem Neustart:
    - `/status` -> `online_count=5`, `disconnected_count=0`
    - `/runtime` -> `configured=true`
    - `/agents/codex` -> `phantom=false`
    - `/health` -> `status=ok`
  - der historische `ordo`-Limitfall ist ebenfalls aufgeloest:
    - `ordo` laeuft jetzt auf `sub1` / `/home/user/.claude-agent-mobile/`
    - `CLAUDE_CONFIG_DIR=/home/user/.claude-agent-mobile claude auth status` -> `redacted@example.com`
    - `/agents/ordo` -> `online=true`, `phantom=false`

## Slice-48-Zusatzbefund
Verifiziert durch Ausführung.

- Reales Symptom vor Slice 48:
  - dieselbe Systemnachricht `77563` wurde in `acw_codex` zweimal verarbeitet
  - `Backend/messages/bridge.jsonl` belegt:
    - `77563` `system -> codex`
    - `77564` erste Antwort
    - `77565` Duplikat-Antwort
- Reale Ursache:
  - `Backend/bridge_mcp.py::_bridge_receive_server_fallback()` filterte IDs `<= _last_seen_msg_id` bisher nicht heraus
- Reale Korrektur:
  - Fallback dedupliziert jetzt gegen `last_seen`
  - dieselbe Restart-Heuristik fuer resetete IDs wird im WS-History-Sync und im Fallback gemeinsam genutzt
- Verifikation:
  - `python3 -m py_compile Backend/bridge_mcp.py Backend/tests/test_bridge_mcp.py`
  - `cd Backend && pytest -q tests/test_bridge_mcp.py -k 'HistoryRecovery or bridge_receive_server_fallback'`
    - `6 passed`
  - Live-Probe gegen echten `/receive`-Pfad:
    - `delivery_probe_1773525617`
    - echte IDs `77580`, `77581`
    - mit `last_seen=77580` liefert Fallback nur `[77581]`
    - naechster Fallback liefert `[]`
- Restrisiko:
  - `codex_poll` bleibt aktiv; Slice 48 entfernt nur Doppelzustellung, nicht den Poll-/Nudge-Mechanismus selbst

## Slice-49-Zusatzbefund
Verifiziert durch Ausführung.

- Reale Hauptursache des aktuellen Chatter:
  - aktive Schedule-Automation `auto_21334601` sendete jede Minute `[SCHEDULED PROMPT] ENDLOSSCHLEIFE ...` an `codex`
  - aktive Test-Automation `auto_c2f82b8a` sendete periodisch `test` an `user`
- Reale operative Korrektur:
  - `PATCH /automations/auto_21334601/active` -> `false`
  - `PATCH /automations/auto_c2f82b8a/active` -> `false`
- Reale Poll-Haertung:
  - `Backend/bridge_watcher.py` prueft fuer `codex_poll` jetzt vor dem Nudge echten Task-Backlog
  - ohne `acked`- oder claimable `created`-Tasks wird der Nudge uebersprungen
  - neue Direktvertraege in `Backend/tests/test_watcher_poll_contract.py`
- Verifikation:
  - `python3 -m py_compile Backend/bridge_watcher.py Backend/tests/test_watcher_poll_contract.py`
  - `cd Backend && pytest -q tests/test_watcher_poll_contract.py`
    - `4 passed`
  - kanonischer Neustart:
    - `./stop_platform.sh && ./start_platform.sh`
    - `Platform is running.`
  - 75s Live-Leerlaufprobe:
    - `bridge_codex_poll.json` -> `polls_total=0`, `polls_injected=0`, `polls_skipped_no_work=2`, `last_skip_reason=no_task_backlog`
    - `GET /history?after_id=77610&limit=30` zeigt keine neuen `SCHEDULED PROMPT`- oder `test`-Nachrichten
- Einordnung:
  - Slice 49 beseitigt den aktuellen Leerlauf-Noise real
  - die Delivery-Architektur bleibt trotzdem hybrid; das ist der naechste strukturelle Delivery-Slice

## Aktueller Refactor-Stand `server.py`
Verifiziert durch Ausführung.

- Bereits extrahiert nach `Backend/handlers/`:
  - `cli.py`
  - `messages.py`
  - `agents.py`
  - `runtime.py`
  - `tasks.py`
  - `scope_locks.py`
  - `whiteboard.py`
  - `approvals.py`
  - `projects.py`
  - `memory.py`
- `skills.py`
- `health.py`
- `workflows.py`
- `federation.py`
- `Backend/daemons/supervisor.py`
- `Backend/daemons/health_monitor.py`
- `Backend/daemons/cli_monitor.py`
- `Backend/daemons/rate_limit_resume.py`
- `Backend/daemons/maintenance.py`
- `Backend/daemons/heartbeat_prompt.py`
- `Backend/daemons/codex_hook.py`
- `Backend/daemons/task_pusher.py`
- `Backend/daemons/auto_assign.py`
- `Backend/daemons/buddy_knowledge.py`
- `Backend/daemons/distillation.py`
- `Backend/daemons/auto_gen.py`
- `Backend/daemons/agent_health.py`
- `Backend/daemons/restart_wake.py`
- `Backend/daemons/restart_control.py`
- `Backend/server_bootstrap.py`
- `Backend/websocket_server.py`
- `Backend/server_startup.py`
- `Backend/server_main.py`
- `Backend/server_utils.py`
- `Backend/server_engine_models.py`
- `Backend/server_runtime_meta.py`
- `Backend/server_agent_state.py`
- `Backend/server_agent_files.py`
- `Backend/server_context_restore.py`
- `Backend/server_request_auth.py`
- `Backend/server_http_io.py`
- `Backend/server_frontend_serve.py`
- `Backend/start_platform_runtime.py`
- `Backend/server.py` hat aktuell `13.765` Zeilen.

### Verifizierte Slice-37-Lage
- `python3 -m py_compile Backend/server.py Backend/server_agent_state.py Backend/tests/test_server_agent_state_contract.py Backend/tests/test_status_model_contract.py`
  - OK
- `pytest -q Backend/tests/test_server_agent_state_contract.py Backend/tests/test_status_model_contract.py Backend/tests/test_context_bridge_updates.py`
  - `33 passed`
- Reale Nacharbeit im Slice:
  - `_cli_identity_bundle(...)` nutzte Persisted-State nach der Extraktion nicht belastbar als Fallback
  - Folgefehler: `/agents/codex_2` und `/agents/ordo` verloren nach Neustart teilweise ihre CLI-Identity-Projektion
  - sauberer Fix: Fallback-Reihenfolge korrigiert auf `payload -> persisted state -> team home`
- Live-Probes nach kanonischem Neustart:
  - `GET /status` -> `registered_count=5`, `online_count=5`, `disconnected_count=0`
  - `GET /runtime` -> `configured=true`, `running_count=2`
  - `GET /health` -> `status=ok`
  - `GET /agents/codex_2` -> `instruction_path=/home/user/bridge/BRIDGE/.agent_sessions/codex_2/AGENTS.md`, `cli_identity_source=cli_register`
  - `GET /agents/codex_2/persistence` -> `healthy=true`

### Verifizierte Slice-38-Lage
- `python3 -m py_compile Backend/server.py Backend/server_agent_files.py Backend/tests/test_server_agent_files_contract.py`
  - OK
- `pytest -q Backend/tests/test_server_agent_files_contract.py Backend/tests/test_runtime_profile_wiring.py Backend/tests/test_ui_strict_auth_contract.py`
  - `30 passed`
- Live-Probes nach kanonischem Neustart:
  - `GET /status` -> `registered_count=5`, `online_count=5`, `disconnected_count=0`
  - `GET /runtime` -> `configured=true`, `running_count=2`, `agent_ids=["codex","claude"]`
  - `GET /health` -> `status=ok`
- Reale `/agent/config`-Proben auf isoliertem Testprojekt `/home/user/bridge/BRIDGE/.tmp_slice38_agent_files`:
  - `GET /agent/config?project_path=<tmp>&engine=codex&slot=a` -> `200`, `instruction_filename=AGENTS.md`
  - `POST /agent/config` mit `action=save_instruction` -> `200`
  - `POST /agent/config` mit `action=set_permission`, `permission=file_write`, `value=true` -> `200`
  - reale Artefakte geschrieben:
    - `AGENTS.md`
    - `.codex/config.toml`

### Verifizierte Slice-39-Lage
- `python3 -m py_compile Backend/server.py Backend/server_context_restore.py Backend/tests/test_server_context_restore_contract.py Backend/tests/test_status_model_contract.py Backend/tests/test_persistence_hardening.py`
  - OK
- `pytest -q Backend/tests/test_server_context_restore_contract.py Backend/tests/test_status_model_contract.py Backend/tests/test_context_bridge_updates.py`
  - `33 passed`
- `pytest -q Backend/tests/test_persistence_hardening.py Backend/tests/test_cli_persistence_layout.py`
  - `59 passed`
- Sanity-Re-Run nach Doku-Sync:
  - `pytest -q Backend/tests/test_server_context_restore_contract.py Backend/tests/test_status_model_contract.py Backend/tests/test_context_bridge_updates.py Backend/tests/test_persistence_hardening.py Backend/tests/test_cli_persistence_layout.py`
  - `92 passed`
- Reale Persistenz-Haertung im Slice:
  - `Backend/server_context_restore.py` zentralisiert den serverseitigen Resume-Handoff
  - jede `context_restore`-Nachricht enthaelt jetzt `## PERSISTENZ-HOOK (JETZT AUSFUEHREN)` mit den konkret aufgeloesten Persistenzpfaden
  - der Hook weist explizit an, von Disk zu lesen und bei Luecken `[UNKNOWN]` statt zu raten zu verwenden
- Live-Probes:
  - `./stop_platform.sh && ./start_platform.sh` grün
  - `GET /agents/codex/persistence` -> `instruction_md.exists=true`, `context_bridge_md.exists=true`, `memory_md.exists=true`
  - `GET /agents/claude/persistence` -> `instruction_md.exists=true`, `context_bridge_md.exists=true`, `memory_md.exists=true`
  - `GET /agents/ordo/persistence` -> `instruction_md.exists=true`, `context_bridge_md.exists=true`, `memory_md.exists=true`
  - `POST /agents/codex/restart` -> neue `context_restore`-Nachricht mit realem `PERSISTENZ-HOOK`
- Wichtige Einordnung:
  - Slice 39 fuehrt keinen neuen Persistenzstore ein
  - die reale Luecke war fehlende Zentralisierung und explizite Resume-Fuehrung
  - Bridge-MCP-Persistenz (`bridge_memory_index`, `bridge_save_context`) bleibt weiterhin mit `Transport closed` blockiert

### Verifizierte Slice-40-Lage
- `python3 -m py_compile Backend/server.py Backend/server_request_auth.py Backend/tests/test_server_request_auth_contract.py Backend/tests/test_ui_strict_auth_contract.py Backend/tests/test_buddy_max_capability_contract.py`
  - OK
- `pytest -q Backend/tests/test_server_request_auth_contract.py Backend/tests/test_ui_strict_auth_contract.py Backend/tests/test_buddy_max_capability_contract.py`
  - `22 passed`
- Reale Auth-Probes:
  - `GET /history?limit=1` ohne Token -> `401`
  - `GET /history?limit=1` mit User-Token -> `200`
  - `GET /agents` ohne Token -> `401`
  - `GET /agents` mit User-Token -> `200`
- Reale Runtime-/Status-Probe nach Neustart:
  - `GET /status` -> `registered_count=4`, `online_count=3`, `disconnected_count=1`
  - `GET /runtime` -> `configured=true`
  - `GET /health` -> `status=ok`
- Reale Einordnung:
  - `codex_2` ist nach dem Neustart nicht mehr registriert
  - `codex_3` bleibt bewusst gestoppt/disconnected
  - der Kernbetrieb mit `claude`, `codex`, `ordo` bleibt grün
  - der Slice aendert keine Auth-Semantik, sondern zieht nur den kritischen Request-Auth-Block aus `BridgeHandler`

### Verifizierte Slice-41-Lage
- `python3 -m py_compile Backend/server.py Backend/server_http_io.py Backend/tests/test_server_http_io_contract.py Backend/server_request_auth.py Backend/tests/test_server_request_auth_contract.py Backend/tests/test_ui_strict_auth_contract.py Backend/tests/test_buddy_max_capability_contract.py`
  - OK
- `pytest -q Backend/tests/test_server_http_io_contract.py Backend/tests/test_server_request_auth_contract.py Backend/tests/test_ui_strict_auth_contract.py Backend/tests/test_buddy_max_capability_contract.py`
  - `28 passed`
- Reale HTTP-Probes:
  - `GET /` -> `200`, UI-Token-Injection real vorhanden
  - `GET /status` mit User-Token -> `200`
  - `GET /history?limit=1` ohne Token -> `401`
  - `GET /history?limit=1` mit User-Token -> `200`
  - `GET /agents` ohne Token -> `401`
  - `GET /agents` mit User-Token -> `200`
- Reale Runtime-/Health-Probe nach Neustart:
  - `./stop_platform.sh && ./start_platform.sh` -> grün
  - `GET /runtime` -> `configured=true`
  - `GET /health` -> `status=ok`
- Operative Nacharbeit:
  - `start_platform.sh` hat `codex_2` und `codex_3` erneut auto-gestartet
  - beide wurden danach sauber via `PATCH /agents/{id}/active` pausiert:
    - `codex_2` -> `200`, `active=false`, `session_alive=false`
    - `codex_3` -> `200`, `active=false`, `session_alive=false`
  - Re-Check:
    - `/status` -> `registered_count=3`, `online_count=3`, `disconnected_count=0`
    - `/health` -> `status=ok`
    - `Backend/team.json` traegt `codex_2.active=false` und `codex_3.active=false`

### Verifizierte Slice-42-Lage
- `python3 -m py_compile Backend/server.py Backend/server_frontend_serve.py Backend/tests/test_server_frontend_serve_contract.py Backend/tests/test_ui_strict_auth_contract.py`
  - OK
- `pytest -q Backend/tests/test_server_frontend_serve_contract.py Backend/tests/test_ui_strict_auth_contract.py Backend/tests/test_server_http_io_contract.py Backend/tests/test_server_request_auth_contract.py`
  - `23 passed`
- Reale HTTP-Probes:
  - `GET /` -> `200`, `window.__BRIDGE_UI_TOKEN` im Body
  - `GET /control_center.html` -> `200`, `window.__BRIDGE_UI_TOKEN` im Body
  - `GET /bridge_runtime_urls.js` -> `200`, `application/javascript; charset=utf-8`
- Reale Einordnung:
  - der erste kanonische Neustart nach Slice 42 scheiterte nicht am Frontend-Serve
  - offengelegt wurde stattdessen ein separater Startup-Konflikt mit bewusst deaktiviertem `claude`
  - dieser wurde in Slice 43 behoben

### Verifizierte Slice-43-Lage
- `python3 -m py_compile Backend/start_platform_runtime.py`
  - OK
- `pytest -q Backend/tests/test_start_platform_runtime_contract.py Backend/tests/test_runtime_configure_contract.py`
  - `9 passed`
- Reale Vorprobe:
  - `POST /runtime/configure` mit explizitem Ein-Agent-Payload fuer `codex` -> `200`, `configured=true`
- Reale Nacharbeit:
  - erster Re-Run rot wegen `KeyError: BRIDGE_DIR`
  - zweiter Re-Run rot wegen fehlender Engine-Ableitung aus `PAIR_MODE`
  - beide Fehler klein und lokal behoben
- Kanonischer Neustart danach:
  - `./stop_platform.sh && ./start_platform.sh` -> grün
  - `/status` -> `registered_count=1`, `online_count=1`
  - `/runtime` -> `configured=true`, `pair_mode=multi`, `agent_ids=["codex"]`
  - `/agents/codex` -> `online=true`, `phantom=false`
  - `Backend/team.json` -> nur `codex.active=true`
- Offene operative Luecke:
  - `/health` bleibt unter diesem gewollten Ein-Agent-Betrieb `degraded`, weil `forwarder.status=warn` ist
  - das ist kein Startup-Blocker mehr, aber eine Health-/Semantik-Luecke fuer den naechsten Slice

### Verifizierte Slice-44-Lage
- `python3 -m py_compile Backend/server.py Backend/server_message_audience.py Backend/tests/test_server_message_audience_contract.py`
  - OK
- `pytest -q Backend/tests/test_server_message_audience_contract.py Backend/tests/test_server_request_auth_contract.py Backend/tests/test_server_http_io_contract.py`
  - `14 passed`
- Reale `all_managers`-Proben:
  - ohne aktive Manager:
    - `POST /send` -> `201`
    - Response enthaelt:
      - `warning="recipient 'all_managers' currently resolves to 0 active targets"`
      - `delivery_targets=[]`
      - `delivery_count=0`
  - mit temporaer aktiviertem `ordo`:
    - `PATCH /agents/ordo/active` -> `200`
    - `POST /agents/ordo/start` -> `200`
    - `/agents/ordo` -> `active=true`, `online=true`, `status=waiting`, `tmux_alive=true`
    - `POST /send` -> `delivery_targets=["ordo"]`, `delivery_count=1`
    - Watcher-Log:
      - `all_managers -> ['ordo']`
      - `user→ordo: injiziert+confirmed`
    - `GET /receive/ordo?limit=10` enthaelt die Broadcast-Nachricht real
    - Cleanup sofort danach:
      - `PATCH /agents/ordo/active` -> `200`
      - `/agents/ordo` -> `active=false`, `online=false`
- Reale Produktverbesserung:
  - leerer Manager-Audience-Fall ist jetzt sichtbar statt still
  - der Non-MCP-Sofortnotify-Pfad behandelt `all_managers`/`leads`/`team:*` nicht mehr wie Vollbroadcasts

### Verifizierte Slice-36-Lage
- `python3 -m py_compile Backend/server.py Backend/server_runtime_meta.py Backend/tests/test_server_runtime_meta_contract.py`
  - OK
- `pytest -q Backend/tests/test_server_runtime_meta_contract.py Backend/tests/test_runtime_profile_wiring.py Backend/tests/test_status_model_contract.py Backend/tests/test_buddy_max_capability_contract.py Backend/tests/test_task_scaling_live.py Backend/tests/test_process_stability_contract.py`
  - `86 passed, 8 skipped`
- Live-Probes nach kanonischem Neustart:
  - `GET /status` -> `registered_count=5`, `online_count=5`, `disconnected_count=0`
  - `GET /runtime` -> `configured=true`, `running_count=2`
  - `GET /health` -> `status=ok`
  - `GET /agents/codex` -> `online=true`, `phantom=false`
- Reale Einordnung:
  - der echte `task_scaling_live`-Capability-Pfad blieb im aktuellen Setup `1 skipped`; der Slice-Nachweis kommt deshalb hier aus Direkt-/Contract-Tests plus den Runtime-Probes

### Verifizierte Slice-8-Lage
- `python3 -m py_compile Backend/server.py Backend/handlers/projects.py`
- `pytest -q Backend/tests/test_project_config_scan_contract.py Backend/tests/test_runtime_profile_wiring.py -k 'build_context_map or create_project or scaffold_docs_include_runtime_profile_fields'`
  - `3 passed, 16 deselected`
- `pytest -q Backend/tests/test_api_server.py -k 'TestProjectsCreate'`
  - `6 passed, 97 deselected`
- kombinierter Re-Run inkl. `test_process_stability_contract.py`
  - `17 passed, 142 deselected`
- Live-Probes gegen frisch gestarteten Server:
  - `GET /projects`
  - `GET /context`
  - `GET /projects/open`
  - `POST /projects/create`
  - alle real gruen

### Verifizierte Slice-9-Lage
- `python3 -m py_compile Backend/server.py Backend/handlers/memory.py`
- `pytest -q Backend/tests/test_memory_engine.py Backend/tests/test_memory_read_canonical.py Backend/tests/test_legacy_memory_migration.py Backend/tests/test_legacy_memory_sync.py`
  - `71 passed`
- `pytest -q Backend/tests/test_process_stability_contract.py`
  - `37 passed`
- Live-Probes gegen frisch gestarteten Server:
  - `POST /memory/scaffold`
  - `POST /memory/write`
  - `GET /memory/read`
  - `GET /memory/status`
  - `POST /memory/migrate`
  - alle real gruen auf isoliertem Testprojekt `/home/user/bridge/BRIDGE/.tmp_slice09_memory_project`

### Verifizierte Slice-10-Lage
- `python3 -m py_compile Backend/server.py Backend/handlers/skills.py`
- `pytest -q Backend/tests/test_skill_manager.py Backend/tests/test_buddy_setup_contract.py Backend/tests/test_process_stability_contract.py`
  - `82 passed`
- Live-Probes gegen frisch gestarteten Server:
  - `GET /skills`
  - `GET /skills/proposals`
  - `GET /skills/buddy`
  - `GET /skills/buddy/section`
  - `POST /skills/propose`
  - `POST /skills/assign`
  - `PATCH /skills/proposals/{id}`
  - alle real gruen
- Aufraeumen:
  - temporaere Pending-Proposals wieder verworfen
  - temporaere Draft-Dateien unter `shared_tools/proposals/` wieder geloescht
  - `GET /skills/proposals?status=pending` -> `count=0`

### Verifizierte Slice-11-Lage
- `python3 -m py_compile Backend/server.py Backend/handlers/health.py`
- `pytest -q Backend/tests/test_status_model_contract.py Backend/tests/test_ui_strict_auth_contract.py Backend/tests/test_bridge_api.py -k 'health or memory_health or persistence'`
  - `1 passed, 1 skipped, 30 deselected`
- Live-Probes gegen frisch gestarteten Server:
  - `GET /health`
  - `GET /agents/buddy/persistence`
  - `GET /agents/buddy/memory-health`
  - `GET /agents/codex/memory-health`
  - `POST /agents/codex/warn-memory`
  - alle real gruen
- Reale Nacharbeit im Slice:
  - erster Testlauf rot mit `NameError: log is not defined`
  - Ursache: `_init_health(...)` uebergab nicht existierenden `server.log`
  - Fix: `handlers/health.py` nutzt jetzt eigenen Modul-Logger
- Kanonischer Restart bleibt weiterhin nur am bekannten Runtime-Blocker rot:
  - `start_platform.sh` endet mit `runtime configure failed after retries`
  - `GET /runtime` bleibt `configured=false`
  - `Backend/logs/server.log` zeigt weiter `Agents did not register within 30.0s: ['claude']`

### Verifizierte Slice-12-Lage
- `python3 -m py_compile Backend/server.py Backend/handlers/workflows.py`
- `pytest -q Backend/tests/test_workflow_registry.py Backend/tests/test_workflow_templates_contract.py Backend/tests/test_repair_n8n_bridge_auth_contract.py Backend/tests/test_ui_strict_auth_contract.py`
  - `27 passed`
- Live-Probes gegen frisch gestarteten Server:
  - `GET /workflows/templates`
  - `GET /workflows/tools`
  - `GET /workflows/suggest?message=workflow%20erstellen%20wochenreport`
  - `GET /n8n/workflows`
  - alle real gruen
- Runtime-/Restart-Re-Check:
  - `./start_platform.sh` -> grün
  - `POST /runtime/configure` -> `200`, `configured=true`
  - `GET /runtime` -> `configured=true`
  - `GET /health` -> `status=ok`
- Reale Nacharbeit im Slice:
  - `test_workflow_registry.py` patchte vor der Extraktion die alte interne Callsite `server._save_workflow_registry`
  - sauberer Fix: Mock-Target auf `handlers.workflows._save_workflow_registry` umgestellt

### Verifizierte Slice-13-Lage
- `python3 -m py_compile Backend/server.py Backend/handlers/federation.py`
- `pytest -q Backend/tests/test_federation_runtime.py Backend/tests/test_federation_gateway.py Backend/tests/test_federation_server_inbound.py Backend/tests/test_federation_protocol.py Backend/tests/test_federation_crypto.py Backend/tests/test_federation_config.py Backend/tests/test_federation_relay.py`
  - `37 passed`
- Live-Probes gegen kanonisch neu gestartete Instanz:
  - `GET /status`
  - `GET /runtime`
  - `GET /health`
  - alle real gruen
- Federation-Error-Projektion:
  - `POST /send` mit `to=backend@inst-test` -> stabil `503 {"error":"federation relay is not configured"}`
- Architekturentscheidung im Slice:
  - `handlers/federation.py` nutzt Callback-Injection via `_init_federation(...)`
  - fuer Patchbarkeit werden in `server.py` Call-Through-Lambdas statt eingefrorener Funktionsobjekte gebunden

### Verifizierte Slice-14-Lage
- `python3 -m py_compile Backend/tmux_manager.py Backend/tests/test_codex_resume.py`
  - OK
- `pytest -q Backend/tests/test_codex_resume.py Backend/tests/test_runtime_configure_contract.py Backend/tests/test_agent_start_contract.py Backend/tests/test_verify_cli_runtime_e2e.py`
  - `46 passed, 1 skipped`
- Reproduzierter Bug vor Fix:
  - `_extract_resume_lineage(...)` zog fuer `codex` eine stale ID aus global `~/.codex`
  - lokale Workspace-SoT unter `.agent_sessions/codex/.codex-home` enthielt neuere Sessions
- Minimaler Fix:
  - `Backend/tmux_manager.py::_discover_codex_resume_id(...)` priorisiert jetzt im Workspace-Fall lokale `.codex-home`-/`.codex`-SQLite- und Session-Roots vor globalem `~/.codex`
- Live-Nachweis nach kanonischem Neustart:
  - `./start_platform.sh` grün
  - `Resume ID for codex from codex SoT: 019cec28-d5ef-75d1-a601-f7e9f9275776`
  - `POST /runtime/configure` -> `200`
  - `/runtime configured=true`
  - `/status`, `/health`, `/agents/codex`, `/agents/claude` real gruen
- Zusatz-E2E:
  - `python3 Backend/verify_cli_runtime_e2e.py --engines codex --restart-count 1 --scenario-timeout 180`
  - `status=ok`

### Verifizierte Slice-15-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/supervisor.py Backend/tests/test_process_stability_contract.py`
  - OK
- `pytest -q Backend/tests/test_watchdog.py Backend/tests/test_agent_liveness_supervisor_contract.py Backend/tests/test_process_stability_contract.py`
  - `50 passed, 15 skipped`
- Reale Nacharbeit im Slice:
  - `test_server_uses_same_forwarder_session_resolution_for_platform_and_supervisor` war nach der Extraktion rot
  - Ursache: der Contract pruefte noch den alten Inline-Code in `server.py`
  - sauberer Fix: Test auf `Backend/daemons/supervisor.py` umgestellt, ohne extrahierten Code zurueck in `server.py` zu duplizieren
- Live-Nachweis nach kanonischem Neustart:
  - `./start_platform.sh` grün
  - `/status` -> `200`, `running`
  - `/runtime` -> `200`, `configured=true`, `running_count=2`
  - `/health` -> `200`, `status=ok`
  - `watcher` und `forwarder` bleiben im Health-Block beide `status=ok`
- Objektidentitaet verifiziert:
  - `server._PROCESS_SUPERVISOR_STATE is daemons.supervisor._PROCESS_SUPERVISOR_STATE` -> `True`

### Verifizierte Slice-16-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/health_monitor.py Backend/tests/test_health_monitor_daemon_contract.py Backend/bridge_watcher.py`
  - OK
- `pytest -q Backend/tests/test_health_monitor_daemon_contract.py Backend/tests/test_watchdog.py Backend/tests/test_process_stability_contract.py`
  - `42 passed, 15 skipped`
- Reale Nacharbeit im Slice:
  - erster Lauf rot mit `ModuleNotFoundError: No module named 'daemons'`
  - sauberer Fix: `BACKEND_DIR`-`sys.path`-Initialisierung in `test_health_monitor_daemon_contract.py`
  - zweiter Lauf rot wegen realem Pfaddrift in `bridge_watcher.PID_FILE`
  - sauberer Fix: `Backend/bridge_watcher.py` nutzt jetzt `os.path.abspath(...)`
- Live-Nachweis nach kanonischem Neustart:
  - `./start_platform.sh` grün
  - `/status` -> `200`, `running`
  - `/runtime` -> `200`, `configured=true`, `running_count=2`
  - `/health` -> `200`, `status=ok`, `watcher=ok`, `forwarder=ok`
- Re-Import verifiziert:
  - `server._send_health_alert is daemons.health_monitor._send_health_alert` -> `True`

### Verifizierte Slice-17-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/cli_monitor.py Backend/tests/test_cli_monitor_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_cli_monitor_daemon_contract.py Backend/tests/test_watchdog.py Backend/tests/test_process_stability_contract.py`
  - `42 passed, 15 skipped`
- Reale Nacharbeit im Slice:
  - erster Direktvertragslauf rot
  - Ursache: die Direktvertraege modellierten den Hash-Stabilitaetsvertrag des Monitors nicht korrekt
  - sauberer Fix: `_AGENT_OUTPUT_HASHES` im Test vorseeden statt Produktcode aufzuweichen
- Live-Nachweis nach kanonischem Neustart:
  - `./start_platform.sh` grün
  - `/status` -> `200`, `running`, `registered_count=5`, `online_count=5`
  - `/runtime` -> `200`, `configured=true`, `running_count=2`, `agent_ids=["codex","claude"]`
  - `/health` -> `200`, `status=ok`, `watcher=ok`, `forwarder=ok`
- Re-Import verifiziert:
  - `server._AGENT_OUTPUT_HASHES is daemons.cli_monitor._AGENT_OUTPUT_HASHES` -> `True`

### Verifizierte Slice-18-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/rate_limit_resume.py Backend/tests/test_rate_limit_resume_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_rate_limit_resume_daemon_contract.py Backend/tests/test_cli_monitor_daemon_contract.py Backend/tests/test_process_stability_contract.py`
  - `47 passed`
- Live-Nachweis nach kanonischem Neustart:
  - `./start_platform.sh` grün
  - `/status` -> `200`, `running`, `registered_count=5`, `online_count=5`
  - `/runtime` -> `200`, `configured=true`, `running_count=2`, `agent_ids=["codex","claude"]`
  - `/health` -> `200`, `status=ok`, `watcher=ok`, `forwarder=ok`
- Re-Import verifiziert:
  - `server._rate_limit_resume_tick is daemons.rate_limit_resume._rate_limit_resume_tick` -> `True`
  - `server._rate_limit_resume_loop is daemons.rate_limit_resume._rate_limit_resume_loop` -> `True`

### Verifizierte Slice-19-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/maintenance.py Backend/tests/test_maintenance_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_maintenance_daemon_contract.py Backend/tests/test_task_create_contract.py Backend/tests/test_process_stability_contract.py`
  - `42 passed`
- Live-Nachweis nach kanonischem Neustart:
  - `./start_platform.sh` grün
  - `/status` -> `200`, `running`, `registered_count=5`, `online_count=5`
  - `/runtime` -> `200`, `configured=true`, `running_count=2`, `agent_ids=["codex","claude"]`
  - `/health` -> `200`, `status=ok`, `watcher=ok`, `forwarder=ok`
- Re-Import verifiziert:
  - `server._task_timeout_loop is daemons.maintenance._task_timeout_loop` -> `True`
  - `server._v3_cleanup_loop is daemons.maintenance._v3_cleanup_loop` -> `True`

### Verifizierte Slice-20-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/heartbeat_prompt.py Backend/tests/test_heartbeat_prompt_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_heartbeat_prompt_daemon_contract.py Backend/tests/test_process_stability_contract.py Backend/tests/test_status_model_contract.py`
  - `57 passed`
- Live-Nachweis nach kanonischem Neustart:
  - `./start_platform.sh` grün
  - `/status` -> `200`, `running`, `registered_count=5`, `online_count=5`
  - `/runtime` -> `200`, `configured=true`, `running_count=2`
  - `/health` -> `200`, `status=ok`
- Re-Import verifiziert:
  - `server._heartbeat_prompt_loop is daemons.heartbeat_prompt._heartbeat_prompt_loop` -> `True`

### Verifizierte Slice-21-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/codex_hook.py Backend/tests/test_codex_hook_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_codex_hook_daemon_contract.py Backend/tests/test_process_stability_contract.py Backend/tests/test_status_model_contract.py`
  - `59 passed`
- Reale Nacharbeit im Slice:
  - erster Lauf rot mit `NameError: MSG_LOCK`
  - sauberer Fix: Hook bekommt den echten Nachrichten-Lock injiziert
- Live-Nachweis nach kanonischem Neustart:
  - `./start_platform.sh` grün
  - `/status` -> `200`, `running`, `registered_count=5`, `online_count=5`
  - `/runtime` -> `200`, `configured=true`, `running_count=2`
  - `/health` -> `200`, `status=ok`
- Re-Import verifiziert:
  - `server._codex_hook_loop is daemons.codex_hook._codex_hook_loop` -> `True`

### Verifizierte Slice-22-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/task_pusher.py Backend/tests/test_task_pusher_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_task_pusher_daemon_contract.py Backend/tests/test_process_stability_contract.py Backend/tests/test_task_create_contract.py`
  - `44 passed`
- Reale Live-Funktionsprobe:
  - temporärer Probe-Agent via `/register`
  - Task via `/task/create` mit `assigned_to=<probe_id>`
  - beobachtete Nachrichtenfolge:
    - `task_notification`
    - `restart_task_recovery`
    - `auto_claim_push`
  - der Zielbefund war verifiziert:
    - `meta.type == "auto_claim_push"`
    - `meta.task_id == <probe task id>`
    - Inhalt enthielt `[AUTO-CLAIM REQUIRED]`
- Reale Runtime-Nacharbeit waehrend Slice-22-Abnahme:
  1. `/agents/{id}/start` force-restartete stale Sessions nicht, weil `last_heartbeat` zu frueh refreshed wurde
  2. `daemons.codex_hook` erhielt einen stale Import-Alias statt des echten Locks `LOCK`
- Zusatz-Verifikation nach den Folgefixes:
  - `pytest -q Backend/tests/test_codex_hook_daemon_contract.py Backend/tests/test_process_stability_contract.py Backend/tests/test_agent_start_contract.py Backend/tests/test_task_pusher_daemon_contract.py Backend/tests/test_task_create_contract.py`
    - `57 passed`
  - kanonischer Restart: `./start_platform.sh` grün
  - `/status` -> `200`, `running`, `registered_count=5`, `online_count=5`
  - `/runtime` -> `200`, `configured=true`, `running_count=2`, `agent_ids=["codex","claude"]`
  - `/health` -> `200`, `status=ok`
- Objektwahrheit:
  - `server._idle_agent_task_pusher is daemons.task_pusher._idle_agent_task_pusher` -> `True`
  - `server._task_pusher_tick is daemons.task_pusher._task_pusher_tick` -> `True`
  - `daemons.codex_hook._msg_lock is server.LOCK` -> `True`

### Verifizierte Baselines fuer den naechsten Slice
- Team:
  - `pytest -q Backend/tests/test_board_api_regression.py Backend/tests/test_control_center_global_counts_contract.py`
  - Ergebnis: `2 failed, 2 passed`
  - Vorbestehende `404`-Fehler blockieren einen sauberen grünen Team-Slice
- Kombinierter Task-/Scope-/Board-Altlastenblock:
  - `pytest -q Backend/tests/test_board_api_regression.py Backend/tests/test_control_center_global_counts_contract.py Backend/tests/test_scope_lock_regressions.py Backend/tests/test_task_system_regressions.py`
  - Ergebnis: `14 failed, 3 passed`
  - Vorbestehende `404`-/`401`-Fehler blockieren Team- und Live-Task-Slices ohne Vorreparatur
- Workflow:
  - `pytest -q Backend/tests/test_workflow_builder.py Backend/tests/test_workflow_registry.py Backend/tests/test_workflow_templates_contract.py Backend/tests/test_workflow_bot_contract.py`
  - Ergebnis: `22 passed`
  - Live-E2E gegen Workflow-Read-/List-Pfade ist jetzt verifiziert.
  - `Nicht verifiziert.`
    - ein dedizierter Write-/Deploy-Live-E2E gegen `/workflows/deploy` oder `/workflows/deploy-template`

## Daten- und Kontrollfluss
Kanonischer Fuehrungsfluss fuer diese Phase:

1. Slice-Grenze aus realer Baseline bestimmen.
2. Doku in `/Viktor` anlegen oder aktualisieren.
3. Kleinsten sauberen Write-Set umsetzen.
4. Compile, targeted Tests und Live-HTTP/Runtime pruefen.
5. Repo-interne SoT und `/Viktor` im selben Arbeitsgang nachziehen.

## Auffaelligkeiten
- Der Refactor ist im Code weiter als der urspruengliche 9-Punkte-Persistenzplan.
- Die Runtime-Baseline ist seit Slice 12 wieder grün:
  - `./start_platform.sh` laeuft kanonisch durch
  - `POST /runtime/configure` bleibt gruen
  - `GET /runtime` ist `configured=true`
  - `GET /health` ist `status=ok`
- Ein realer Codex-Resume-Drift im Runtime-Startpfad war danach noch vorhanden und ist in Slice 14 gezielt gehaertet worden.
- Team-/Board-Routen haben weiter vorbestehende rote Regressionstests.
- Scope-/Task-Live-Regressionstests sind weiterhin auth-rot und muessen vor einem grünen Team-/Task-Folgeslice neu eingegrenzt werden.
- Der Watcher-PID-Vertrag war real nicht normalisiert und wurde in Slice 16 lokal gehaertet.

### Verifizierte Slice-24-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/buddy_knowledge.py Backend/tests/test_buddy_knowledge_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_buddy_knowledge_daemon_contract.py Backend/tests/test_process_stability_contract.py Backend/tests/test_buddy_setup_contract.py Backend/tests/test_buddy_user_scope_contract.py`
  - `53 passed`
- Live-Probes gegen kanonisch neu gestartete Instanz:
  - `GET /status`
  - `GET /runtime`
  - `GET /health`
  - real grün, mit vorbestehendem `ordo`-Warnzustand im Gesamt-Health
- Buddy-Home-Artefakte:
  - `Buddy/knowledge/KNOWLEDGE_INDEX.md`
  - `Buddy/knowledge/SYSTEM_MAP.md`
  - beide real vorhanden und mtime-konsistent zu `Backend/team.json`
- Objektidentität verifiziert:
  - `server._buddy_knowledge_loop is daemons.buddy_knowledge._buddy_knowledge_loop`
  - `server._generate_buddy_knowledge is daemons.buddy_knowledge._generate_buddy_knowledge`
  - `server._buddy_knowledge_tick is daemons.buddy_knowledge._buddy_knowledge_tick`

### Verifizierte Slice-25-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/distillation.py Backend/tests/test_distillation_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_distillation_daemon_contract.py Backend/tests/test_process_stability_contract.py Backend/tests/test_buddy_setup_contract.py`
  - `48 passed`
- Live-Probes gegen kanonisch neu gestartete Instanz:
  - `GET /status`
  - `GET /runtime`
  - `GET /health`
  - real grün
- Objektidentität verifiziert:
  - `server._distillation_daemon_loop is daemons.distillation._distillation_daemon_loop`
  - `server._distillation_tick is daemons.distillation._distillation_tick`
  - `server._DISTILLATION_PROMPT == daemons.distillation._DISTILLATION_PROMPT`

### Verifizierte Slice-26-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/auto_gen.py Backend/tests/test_auto_gen_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_auto_gen_daemon_contract.py Backend/tests/test_process_stability_contract.py Backend/tests/test_buddy_setup_contract.py`
  - `48 passed`
- Live-Probes gegen kanonisch neu gestartete Instanz:
  - `GET /status`
  - `GET /runtime`
  - `GET /health`
  - real grün
- Objektidentität verifiziert:
  - `server._auto_gen_watcher is daemons.auto_gen._auto_gen_watcher`
  - `server._auto_gen_tick is daemons.auto_gen._auto_gen_tick`
  - `server.AUTO_GEN_PENDING is daemons.auto_gen.AUTO_GEN_PENDING`

### Verifizierte Slice-27-Lage
- `python3 -m py_compile Backend/server.py Backend/daemons/agent_health.py Backend/tests/test_agent_health_daemon_contract.py`
  - OK
- `pytest -q Backend/tests/test_agent_health_daemon_contract.py Backend/tests/test_process_stability_contract.py Backend/tests/test_agent_start_contract.py Backend/tests/test_status_model_contract.py`
  - `66 passed`
- Live-Probes gegen kanonisch neu gestartete Instanz:
  - `GET /status`
  - `GET /runtime`
  - `GET /health`
  - real grün
- Objektidentität verifiziert:
  - `server._agent_health_checker is daemons.agent_health._agent_health_checker`
  - `server._agent_health_tick is daemons.agent_health._agent_health_tick`

## Risiken
- Ohne disziplinierte Slice-Grenzen drohen wieder breite Seiteneffekte in `server.py`.
- verbleibende Daemon-/Team-Slices haben ein hoeheres Risiko als die bisherigen Handler-Slices, weil sie die jetzt grüne Runtime direkt beruehren.
- `tmux_manager.py` ist trotz Slice 14 weiter ein sensibler Runtime-Pfad; neue Resume-/Start-Aenderungen brauchen weiterhin echte tmux-/Runtime-/E2E-Verifikation.
- Dokumentationsdrift ist ein realer Release-Risikohebel und muss aktiv verhindert werden.
- der verbleibende groessere Infrastrukturblock liegt jetzt im `main()`-/Startup-Block; dieser beruehrt Daemon-Start, WebSocket-Thread und Scheduler-Bootstrap direkt.

## Entscheidung
- Slice 23 bis Slice 34 sind abgeschlossen.
- Naechster Slice-Kandidat ist der Engine-/Model-Registry-Cluster vor `BridgeHandler` in `Backend/server.py`.
- Aktuell beste Kandidatenlage:
  - Federation, Codex-Resume-Haertung, der Watcher-/Forwarder-Supervisor, der Health-Monitor, der CLI-Monitor, der Rate-Limit-Resume-Timer, die Maintenance-Loops, der Heartbeat-Prompter, der Codex-Hook, der Task-Pusher, der Auto-Assign-Daemon, der Buddy-Knowledge-Daemon, der Distillation-Daemon, der Auto-Gen-Watcher und der Agent-Health-Checker sind abgeschlossen
  - Team bleibt wegen vorbestehender 404s rot
  - verbleibende Buddy-/Inline-Daemon-Domaenen muessen gegen die grüne Runtime-Baseline neu priorisiert werden

## Aktuelle Ownership
- Hauptagent:
  - laufende `server.py`-Refaktor-Slices
  - Runtime-/HTTP-Verifikation
  - Leitstand- und Slice-Dokumentation

## Letzter verifizierter Fortschritt
- `Backend/tmux_manager.py` priorisiert fuer Codex-Resume jetzt lokale Workspace-SoT vor stale globalem `~/.codex`.
- Die Runtime ist nach Reload weiter real gruen; `codex` registriert sich mit der aktuellen lokalen Resume-ID.
- `verify_cli_runtime_e2e.py --engines codex --restart-count 1` ist nach dem Fix real gruen.
- der Watcher-/Forwarder-Supervisor ist nach `Backend/daemons/supervisor.py` extrahiert und die Runtime bleibt real gruen.
- der Health-Monitor ist nach `Backend/daemons/health_monitor.py` extrahiert und bleibt ueber neue Direkt-Tests plus Runtime-Verifikation grün.
- der CLI-Monitor ist nach `Backend/daemons/cli_monitor.py` extrahiert und bleibt ueber Direkt-Tests plus Runtime-Verifikation grün.
- der Rate-Limit-Resume-Timer ist nach `Backend/daemons/rate_limit_resume.py` extrahiert und bleibt ueber Direkt-Tests plus Runtime-Verifikation grün.
- die Maintenance-Loops sind nach `Backend/daemons/maintenance.py` extrahiert und bleiben ueber Direkt-Tests plus Runtime-Verifikation grün.
- der Heartbeat-Prompter ist nach `Backend/daemons/heartbeat_prompt.py` extrahiert und bleibt ueber Direkt-Tests plus Runtime-Verifikation grün.
- der Codex-Hook ist nach `Backend/daemons/codex_hook.py` extrahiert und bleibt ueber Direkt-Tests plus Runtime-Verifikation grün.
- der Task-Pusher ist nach `Backend/daemons/task_pusher.py` extrahiert und im Live-System bis zum echten `auto_claim_push` verifiziert.
- der Auto-Assign-Daemon ist nach `Backend/daemons/auto_assign.py` extrahiert und bleibt ueber Direktvertraege, Objektidentitaet, kanonischen Restart und gruene Runtime abgesichert.
- ein natuerlicher Auto-Assign-Live-Probeversuch ist ausgefuehrt, war aber nicht isoliert auswertbar, weil ein aktiver Runtime-Agent den unassigned Probe-Task bereits vor dem Auto-Assign-Tick geclaimed hat.
- der stale-Heartbeat-Recovery-Pfad in `POST /agents/{id}/start` ist real repariert und live fuer `codex` verifiziert.
- das Codex-Hook-Wiring nutzt jetzt den echten Runtime-Message-Lock `LOCK` und der bisherige `not initialized`-Fehler ist verschwunden.
- der Restart-Wake-Pfad ist nach `Backend/daemons/restart_wake.py` extrahiert und ueber Direktvertraege, Persistenzregressionen, kanonischen Start und echten Wrapper-Restart abgesichert.
- `POST /server/restart/force` wurde real gefahren; danach kamen `/status`, `/runtime` und `/health` wieder grün hoch und `Backend/logs/server.log` belegt den Wake-Pfad mit `WAKE complete: 6 agents started`.
- der Restart-Control-Block ist nach `Backend/daemons/restart_control.py` extrahiert und ueber Direktvertraege, kanonischen Plattformstart und echten `POST /server/restart/force` abgesichert.
- `Backend/logs/server.log` belegt jetzt fuer `slice29-e2e` real `STOP phase started: 3s` und `KILL phase started`; `Backend/logs/restart_wrapper.log` belegt den geplanten Wrapper-Restart.
- der HTTP-/Server-Bootstrap-Block ist nach `Backend/server_bootstrap.py` extrahiert und ueber Direktvertraege, kanonischen Plattformstart und echten SIGTERM-Recovery-Pfad abgesichert.
- `Backend/logs/server.log` belegt real `Received signal 15. Starting graceful shutdown...`; `Backend/logs/restart_wrapper.log` belegt `Server exited with code 0` und sofortigen Wiederanlauf nach direktem SIGTERM.
- der WebSocket-Block ist nach `Backend/websocket_server.py` extrahiert und ueber Direktvertraege, statische Contracts, kanonischen Plattformstart und echten Live-WebSocket-Smoke abgesichert.
- `BRIDGE_RUN_LIVE_TESTS=1 python3 Backend/tests/test_websocket.py` ist nach Auth-Haertung des Smoke-Scripts real `36/36` gruen.
- der Startup-Orchestrierungsblock ist nach `Backend/server_startup.py` extrahiert und ueber Direktvertraege, kanonischen Plattformstart, Automation-Livepfad und `verify_cli_runtime_e2e.py --engines codex --restart-count 1` abgesichert.
- der verbleibende `main()`-Rest ist nach `Backend/server_main.py` extrahiert und ueber Direktvertraege, kanonischen Plattformstart, Runtime-/Health-Gates und `verify_cli_runtime_e2e.py --engines codex --restart-count 1` abgesichert.
- der Pure-Utility-Block fuer Zeit-/Pfad-/Query-Helfer ist nach `Backend/server_utils.py` extrahiert und ueber Direktvertraege sowie reale `/cli/detect`-/`/history`-/`/projects`-Probes abgesichert.
- `./stop_platform.sh && ./start_platform.sh` ist nach Slice 34 real wieder gruen; `/status` zeigt `online_count=5`, `/runtime configured=true`, `/health status=ok`.
- der Engine-/Model-Registry-Block ist nach `Backend/server_engine_models.py` extrahiert und ueber Direktvertraege sowie reale `/engines/models`-/`/cli/detect`-Probes abgesichert.
- `python3 Backend/verify_cli_runtime_e2e.py --engines codex --restart-count 1 --scenario-timeout 180` bleibt nach Slice 35 real `status=ok`.
- Nach dem kanonischen Restart von Slice 35 blieb jedoch eine beobachtete Runtime-Drift offen:
  - `/runtime configured=true`, aber `running_count=1`
  - `/health status=degraded`
  - `/status` zeigt `codex` und `ordo` als disconnected
  - **Nicht verifiziert.** Kausalitaet zur Slice-35-Aenderung
- `server.py` steht jetzt bei `14.816` Zeilen.
- Slice 50 hat den Register-Persistenzpfad auf den kanonischen Memory-Layer aus `Backend/persistence_utils.py` zurueckgefuehrt.
- `python3 -m py_compile Backend/server.py Backend/tests/test_persistence_hardening.py`
  - OK
- `pytest -q Backend/tests/test_persistence_hardening.py Backend/tests/test_cli_persistence_layout.py Backend/tests/test_server_context_restore_contract.py`
  - `64 passed`
- Kanonischer Neustart nach Slice 50:
  - `./stop_platform.sh && ./start_platform.sh`
  - `Platform is running.`
- Reale Gates nach Slice 50:
  - `GET /status` -> `online_count=1`, `online_ids=["codex"]`
  - `GET /runtime` -> `configured=true`, `running_count=1`
  - `GET /agents/codex` -> `online=true`, `phantom=false`
  - `GET /agents/codex/persistence` -> `healthy=true`, `memory_md.exists=true`
- `Backend/logs/server.log` belegt `[register] Auto-indexed MEMORY.md for codex ...`
- Reale Memory-Endpunkte:
  - `POST /memory/index` -> `ok=true`
  - `POST /memory/search` -> Probe-Datensatz auffindbar
  - `POST /memory/delete` -> Probe-Datensatz wieder entfernt
- Wichtige Einordnung:
  - der weiter beobachtete Befund `bridge_memory_index(...)` / `bridge_save_context(...)` -> `Transport closed` ist aktuell **nicht** als Repo-HTTP-Defekt belegt
  - die repo-internen `/memory/*`-Endpoints tragen real; der Bruch sitzt derzeit am MCP-Tooltransport dieser Arbeitsumgebung
- Creator-HTTP-Routen sind nach `Backend/handlers/creator.py` extrahiert und ueber Direktvertraege, Creator-HTTP-Vertrag, echten Creator-E2E-Test, kanonischen Neustart und Live-Probes gegen `/creator/social-presets` und `/creator/highlights` abgesichert.
- Execution-Journal-Read-Routen sind nach `Backend/handlers/execution_routes.py` extrahiert und ueber Direktvertraege, `tests/test_execution_http_contract.py`, kanonischen Neustart und Live-Probes gegen `/execution/runs`, `/execution/summary` und `/execution/runs/{id}` abgesichert.
- `POST /execution/runs/prune` ist jetzt ebenfalls nach `Backend/handlers/execution_routes.py` gezogen und durch denselben HTTP-Vertrag abgesichert; der Live-Apply-Probe hatte jedoch einen breiten realen Daten-Seiteneffekt und darf kuenftig nur isoliert oder als `dry_run` wiederholt werden.
- `POST /guardrails/incident-bundle` und `POST /audit/export` sind jetzt ebenfalls nach `Backend/handlers/execution_routes.py` gezogen und ueber denselben HTTP-Vertrag, kanonischen Neustart und nicht-destruktive Live-Probes abgesichert.
- Die Guardrails-Readpfade sind nach `Backend/handlers/guardrails_routes.py` extrahiert und ueber Direktvertraege, `tests/test_execution_http_contract.py`, kanonischen Neustart und Live-Probes gegen `/guardrails/presets`, `/guardrails/summary` und `/guardrails/{agent}` abgesichert.
- Die Guardrails-POST-Pfade sind jetzt ebenfalls nach `Backend/handlers/guardrails_routes.py` extrahiert und ueber Direktvertraege, `tests/test_execution_http_contract.py` und reale Live-Probes gegen `/guardrails/evaluate` und `/guardrails/{agent}/apply-preset` abgesichert.
- Die Guardrails-Policy-Writepfade (`PUT`/`DELETE /guardrails/{agent}`) sind jetzt ebenfalls nach `Backend/handlers/guardrails_routes.py` extrahiert und ueber Direktvertraege, `tests/test_execution_http_contract.py` und reale Live-Probes gegen einen isolierten Probe-Agenten abgesichert.
- Die Creator-Implementierung von Claude/Viktor ist unabhaengig gegen den laufenden Server geprueft; die neue Job-/Campaign-Pipeline traegt in `72` Tests und in realen Live-Probes fuer Ingest, Analyze, Publish und Campaign-Flow.
- Der Live-500-Defekt der Capability-Library ist behoben: `config/capability_library.json` war fehlend, wurde per Builder mit `599` Eintraegen regeneriert, und alle `/capability-library*`-Endpunkte sind wieder real gruen.
- Die Capability-Library-HTTP-Routen sind jetzt nach `Backend/handlers/capability_library_routes.py` extrahiert und ueber Direktvertraege, `tests/test_capability_library.py`, `tests/test_execution_http_contract.py`, einen `test_bridge_mcp.py`-Forwarding-Recheck, kanonischen Neustart und reale Live-Probes gegen alle fuenf `/capability-library*`-Endpunkte abgesichert.
- Die Shared-Tools-Routegruppe ist jetzt nach `Backend/handlers/shared_tools_routes.py` extrahiert und ueber Direktvertraege, einen isolierten HTTP-Vertrag, kanonischen Neustart und eine reale Register/List/Detail/Execute/Delete-Live-Probe gegen ein eindeutiges Probe-Tool abgesichert.
- Der Chat-Upload-Dateiservierpfad ist jetzt nach `Backend/handlers/chat_files.py` extrahiert und ueber Direktvertraege, einen isolierten HTTP-Vertrag, kanonischen Neustart und eine reale Probe-Datei gegen `/files/{filename}` abgesichert.
- Der kleine Meta-/CLI-GET-Block ist jetzt nach `Backend/handlers/meta_routes.py` extrahiert und ueber Direktvertraege, deterministische Fake-HTTP-Vertraege, kanonischen Neustart und reale Live-Probes gegen `/engines/models` und `/cli/detect` abgesichert.
- Die Projekt-GET-Routen `/projects`, `/projects/open` und `/context` liegen jetzt in `Backend/handlers/projects.py` und sind ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und reale Live-Probes gegen den echten Arbeitsbaum `/home/user/bridge/BRIDGE` abgesichert.
- Die Teamlead-Scope-GET/POST-Pfade liegen jetzt in `Backend/handlers/teamlead_scope_routes.py` und sind ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und eine reale, danach rueckgängig gemachte Scope-Probe im BRIDGE-Projekt abgesichert.
- Der Log-Read-Pfad `GET /logs` liegt jetzt in `Backend/handlers/logs_routes.py` und ist ueber Direktvertraege, einen isolierten HTTP-Vertrag, kanonischen Neustart und eine reale auth-geschuetzte Live-Probe gegen `server.log` abgesichert.
- Die Whiteboard-Routegruppe (`GET /whiteboard`, `POST /whiteboard`, `POST /whiteboard/post`, `DELETE /whiteboard/{id}`) liegt jetzt in `Backend/handlers/whiteboard.py` und ist ueber Direktvertraege, einen isolierten HTTP-Vertrag, kanonischen Neustart und eine reale, danach wieder entfernte Probe-Entry abgesichert.
- Der Subscription-CRUD (`GET /subscriptions`, `POST /subscriptions`, `PUT /subscriptions/{id}`, `DELETE /subscriptions/{id}`) liegt jetzt in `Backend/handlers/subscriptions_routes.py` und ist ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und eine reale, danach wieder geloeschte Probe-Subscription abgesichert.
- Der Event-Subscription-CRUD (`GET /events/subscriptions`, `POST /events/subscribe`, `DELETE /events/subscriptions/{id}`) liegt jetzt in `Backend/handlers/event_subscriptions_routes.py` und ist ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und eine reale, danach wieder geloeschte Probe-Subscription abgesichert.
- Die Skills-Read-Routen (`GET /skills`, `GET /skills/{name}/content`, `GET /skills/{agent}/section`, `GET /skills/proposals`, `GET /skills/{agent}`) liegen jetzt in `Backend/handlers/skills.py` und sind ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und reale Read-only-Probes gegen die Live-Skill-Installation abgesichert.
- Die Read-only-MCP-/Industry-Template-Routen (`GET /mcp-catalog`, `GET /industry-templates`) liegen jetzt in `Backend/handlers/mcp_catalog_routes.py` und sind ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und reale Live-Probes abgesichert; zusaetzlich wurde `config/industry_templates.json` als fehlender aktiver Datenkanon wiederhergestellt.
- Die read-only Memory-Routen (`GET /memory/stats`, `GET /memory/status`, `GET /memory/read`) liegen jetzt in `Backend/handlers/memory.py` und sind ueber Direktvertraege, isolierte HTTP-Vertraege, den bestehenden Canonical-/Legacy-Memory-Testblock, kanonischen Neustart und reale Live-Probes gegen ein isoliertes Probeprojekt abgesichert.
- Der mutierende Legacy-/Canonical-Memory-Block (`POST /memory/scaffold`, `POST /memory/write`, `POST /memory/episode`, `POST /memory/migrate`) liegt jetzt ebenfalls in `Backend/handlers/memory.py` und ist ueber Direktvertraege, isolierte HTTP-Vertraege, denselben Memory-Regressionstestblock, kanonischen Neustart und reale Live-Probes gegen ein isoliertes Probeprojekt abgesichert.
- Die Semantic-Memory-POST-Routen (`POST /memory/index`, `POST /memory/search`, `POST /memory/delete`) liegen jetzt ebenfalls in `Backend/handlers/memory.py` und sind ueber Direktvertraege, isolierte HTTP-Vertraege, den bestehenden Memory-Engine-Testblock, kanonischen Neustart und eine reale Index/Search/Delete-Probe gegen einen eindeutig isolierten Scope abgesichert.
- Die Approval-Read-Routen (`GET /approval/pending`, `GET /approval/{id}`, `GET /standing-approval/list`) liegen jetzt in `Backend/handlers/approvals.py` und sind ueber Direktvertraege, isolierte HTTP-Vertraege, den bestehenden Approval-/Auth-Testblock, kanonischen Neustart und eine reale Probe mit anschliessendem Cleanup abgesichert.
- Die Metrics-Read-Routen (`GET /metrics/tokens`, `GET /metrics/costs`, `GET /metrics/prices`) liegen jetzt in `Backend/handlers/metrics_routes.py` und sind ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und reale Read-only-Probes gegen das laufende System abgesichert.
- Die System-/Restart-/Platform-Status-Read-Routen (`GET /server/restart-status`, `GET /system/status`, `GET /system/shutdown-status`, `GET /platform/status`) liegen jetzt in `Backend/handlers/system_status_routes.py` und sind ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und reale Live-Probes abgesichert.
- Der read-only `n8n`-/Workflow-GET-Cluster (`GET /n8n/executions`, `GET /n8n/workflows`, `GET /workflows/capabilities`, `GET /workflows/{id}/definition`, `GET /workflows`, `GET /workflows/templates`, `GET /workflows/tools`, `GET /workflows/suggest`) liegt jetzt in `Backend/handlers/workflows.py` und ist ueber Direktvertraege, Workflow-/Template-/Auth-Vertraege, kanonischen Neustart und reale Live-Probes abgesichert.
- Der read-only Board-GET-Cluster (`GET /board/projects`, `GET /board/projects/{id}`, `GET /board/agents`, `GET /board/agents/{id}/projects`) liegt jetzt in `Backend/handlers/board_routes.py` und ist ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und reale Live-Probes abgesichert.
- Die Creator-Implementierung von Claude/Viktor ist unabhaengig gegen Code, Creator-Testblock und reale Live-Probes auf `:9111` reviewed; belastbar bestaetigt sind Ingest-Job, Batch-Status und Campaign-Pfad, waehrend Live-`analyze`/`publish`/`resume`/`cancel` weiter **nicht verifiziert** sind.
- Der Board-Projekt-Vertragsdrift ist ueber Main-Server und `Backend/api_server.py` geschlossen: `POST /board/projects` akzeptiert jetzt `project_id`, `GET /board/projects?limit=...` respektiert `limit`, und `tests/test_board_api_regression.py` ist zusammen mit den Main-Server-Board-Vertraegen real gruen (`156 passed`).
- Die Projekt-Write-Routen des Board-Clusters (`PUT /board/projects/{id}`, `DELETE /board/projects/{id}`) liegen jetzt ebenfalls in `Backend/handlers/board_routes.py` und sind ueber Direktvertraege, kanonischen Neustart und reale Create/Update/Delete-Probes gegen einen isolierten Projektkandidaten abgesichert.
- Die Team-Write-Routen des Board-Clusters (`POST /board/projects/{id}/teams`, `PUT /board/projects/{id}/teams/{tid}`, `DELETE /board/projects/{id}/teams/{tid}`) liegen jetzt ebenfalls in `Backend/handlers/board_routes.py` und sind ueber Direktvertraege, kanonischen Neustart und reale Projekt+Team-Probes gegen isolierte IDs abgesichert.
- Die Member-Write-Routen des Board-Clusters (`POST /board/projects/{id}/teams/{tid}/members`, `DELETE /board/projects/{id}/teams/{tid}/members/{aid}`) liegen jetzt ebenfalls in `Backend/handlers/board_routes.py` und sind ueber Direktvertraege, kanonischen Neustart und reale Projekt+Team+Member-Probes gegen isolierte IDs abgesichert; fruehere Board-Testartefakte wurden anschliessend gezielt aus dem Live-Board bereinigt.
- Die nun redundanten alten Inline-Board-Bloecke sind aus `Backend/server.py` entfernt; `server.py` enthaelt fuer den delegierten Board-Kerncluster keine doppelten POST/PUT/DELETE-Pfade mehr.
- Der read-only Team-Cluster (`GET /team/projects`, `GET /teams`, `GET /teams/{id}`, `GET /team/context/{agent_id}`) liegt jetzt in `Backend/handlers/teams_routes.py` und ist ueber Direktvertraege, source-basierte Orgchart-Haertungstests, kanonischen Neustart und reale Live-Probes abgesichert; `GET /team/orgchart` bleibt bewusst inline.
- Die Team-Mutationsrouten (`POST /teams`, `PUT /teams/{id}/members`, `DELETE /teams/{id}`) liegen jetzt ebenfalls in `Backend/handlers/teams_routes.py` und sind ueber Direktvertraege, den bestehenden Auth-/Permanenztestblock, kanonischen Neustart und eine reale Create/Update/Soft-Delete-Probe gegen ein isoliertes Team abgesichert; die dabei erzeugten Soft-Delete-Probe-Teams wurden anschliessend wieder aus `Backend/team.json` bereinigt.
- Der read-only Automation-GET-Cluster (`GET /automations`, `GET /automations/{id}`, `GET /automations/{id}/history`, `GET /automations/{id}/history/{exec_id}`) liegt jetzt in `Backend/handlers/automation_routes.py` und ist ueber Direktvertraege, source-sensitive UI-/Auth-Vertraege, kanonischen Neustart und reale Live-Probes gegen bestehende Automation-/History-Daten abgesichert.
- Die normalen Automation-Mutationen (`POST /automations`, `PATCH /automations/{id}/active`, `PATCH /automations/{id}/pause`, `PUT /automations/{id}`, `DELETE /automations/{id}`) liegen jetzt ebenfalls in `Backend/handlers/automation_routes.py` und sind ueber Direktvertraege, source-sensitive UI-/Auth-Vertraege, kanonischen Neustart und eine reale isolierte Create/Toggle/Update/Delete-Probe abgesichert.
- Die verbleibende Run-/Webhook-Logik fuer `POST /automations/{id}/run` und `POST /automations/{id}/webhook` ist jetzt ebenfalls nach `Backend/handlers/automation_routes.py` verschoben; die Regex-Matches bleiben bewusst inline in `Backend/server.py`, damit der source-sensitive Webhook-Vertrag bestehen bleibt. Verifiziert ueber Direktvertraege, source-sensitive UI-/Auth-Vertraege, kanonischen Neustart und reale isolierte Run-/Webhook-Probes mit eindeutigen Message-Nonces.
- Die Workflow-Mutationen fuer bestehende Workflows (`PATCH /workflows/{id}/toggle`, `PUT /workflows/{id}/definition`, `DELETE /workflows/{id}`) liegen jetzt in `Backend/handlers/workflows.py` und sind ueber Direktvertraege, Workflow-Registry-Vertraege, kanonischen Neustart und eine reale isolierte n8n-Live-Probe mit Deploy/Toggle/Update/Delete-Cleanup abgesichert.
- Die verbleibenden Workflow-POST-Routen (`POST /workflows/compile`, `POST /workflows/deploy`, `POST /workflows/deploy-template`) liegen jetzt ebenfalls in `Backend/handlers/workflows.py` und sind ueber Direktvertraege, kanonischen Neustart und eine reale n8n-Live-Probe mit Compile/Deploy/Template/Cleanup abgesichert.
- Der Credential-Store-HTTP-Block (`GET/POST/DELETE /credentials/{service}[/{key}]`) liegt jetzt in `Backend/handlers/credentials_routes.py` und ist ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und einen realen CRUD-Nachweis auf `github/*` abgesichert.
- Die Git-Advisory-Lock-Routen (`GET /git/locks`, `POST /git/lock`, `DELETE /git/lock`) liegen jetzt in `Backend/handlers/git_lock_routes.py` und sind ueber Direktvertraege, `tests/test_git_collaboration.py`, kanonischen Neustart und eine reale isolierte Lock/Unlock-Probe gegen `slice92/oebaxspy` abgesichert.
- `POST /metrics/tokens` liegt jetzt ebenfalls in `Backend/handlers/metrics_routes.py` und ist ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und einen realen Write+Readback-Nachweis fuer das isolierte Modell `slice93-metric-test` abgesichert.
- Der generische Media-POST-Block (`/media/info`, `/media/convert`, `/media/extract`) liegt jetzt in `Backend/handlers/media_routes.py` und ist ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und echte Live-Probes gegen ein isoliertes `ffmpeg`-Testvideo abgesichert.
- `POST /skills/assign` liegt jetzt ebenfalls in `Backend/handlers/skills.py` und ist ueber Direktvertraege, isolierte HTTP-Vertraege, kanonischen Neustart und eine zustandsneutrale Live-Probe gegen den bestehenden `codex`-Skill-Satz abgesichert.
- `POST /onboarding/start` und `GET /onboarding/status` liegen jetzt gemeinsam in `Backend/handlers/onboarding_routes.py` und sind ueber Direktvertraege, lokale HTTP-Vertraege, einen echten Happy-Path-/503-Recheck fuer Buddy-Frontdoor und den Rueckfall auf `nur codex aktiv` abgesichert.
- `POST /team/reload` liegt jetzt ebenfalls in `Backend/handlers/teams_routes.py` und ist ueber Direktvertraege, lokale HTTP-Vertraege, kanonischen Neustart und eine auth-geschuetzte Live-Probe gegen den echten Server abgesichert; der anfängliche rote Re-Run war reiner Test-Drift durch globalen `init(...)`-Zustand und veraltete Payload-Erwartung.
- Der kleine Approval-Write-Cluster (`POST /approval/{request_id}/edit`, `POST /standing-approval/create`, `POST /standing-approval/{id}/revoke`) liegt jetzt ebenfalls in `Backend/handlers/approvals.py` und ist ueber Direktvertraege, lokale HTTP-Vertraege, kanonischen Neustart und einen auth-geschuetzten Live-Zyklus mit echtem Cleanup abgesichert; die Standing-Approval-RBAC bleibt dabei operativ in `Backend/server.py` und wird nur injiziert.
- `POST /agents/{id}/warn-memory` liegt jetzt ebenfalls in `Backend/handlers/agents.py` und ist ueber Direktvertraege, lokale HTTP-Vertraege, kanonischen Neustart und reale auth-geschuetzte Live-Probes fuer den gesunden (`warned=false`) und den nicht aufloesbaren (`404`) Fall abgesichert; die eigentliche Memory-Health-Wahrheit bleibt dabei in `Backend/server.py`.
- `GET /team/orgchart` liegt jetzt ebenfalls in `Backend/handlers/teams_routes.py` und ist ueber Direktvertraege, source-sensitive Persistenzvertraege, kanonischen Neustart und eine auth-geschuetzte Live-Probe mit real getrennter `active`-/`online`-/`auto_start`-Projektion abgesichert.
- `PUT /agents/{id}/subscription` liegt jetzt ebenfalls in `Backend/handlers/agents.py` und ist ueber Direktvertraege, lokale HTTP-Vertraege, kanonischen Neustart und eine state-neutrale auth-geschuetzte Live-Probe gegen `buddy -> sub1` abgesichert; die operative Subscription-Wahrheit bleibt dabei in `TEAM_CONFIG` + `_atomic_write_team_json`.
- `POST /agents/{id}/avatar` liegt jetzt ebenfalls in `Backend/handlers/agents.py` und ist ueber Direktvertraege, lokale HTTP-Vertraege, kanonischen Neustart und eine auth-geschuetzte Live-Probe gegen `assi` abgesichert; dabei wurde ein echter Live-Bug im stale-`TEAM_CONFIG`-Pfad reproduziert, kausal auf einen eingefrorenen Dict-Verweis in `handlers.agents.py` eingegrenzt und per `team_config_getter_fn=lambda: TEAM_CONFIG` + frischem `_get_team_config()` fuer die Agent-Writepfade behoben. Persistenz, `GET /agents/{id}`-Projektion und Dateiserving tragen danach gemeinsam; der Live-Probe-Cleanup hat `Backend/team.json` und `Frontend/avatars/assi.png` wieder auf den Vorzustand zurueckgesetzt.
- `POST /agents/{id}/restart` liegt jetzt ebenfalls in `Backend/handlers/agents.py` und ist ueber Direktvertraege, lokale HTTP-Vertraege, kanonischen Neustart und einen auth-geschuetzten negativen Live-Fall gegen den inaktiven Agenten `assi` abgesichert. Die operative tmux-/CLI-Wahrheit bleibt dabei in `Backend/tmux_manager.py`, die Runtime-Praesenz-Wahrheit in `Backend/server.py`; `handlers.agents.py` bekommt nur die benoetigten Restart-Callbacks und `PORT` injiziert. Positiver Live-Restart eines produktiv laufenden Agents bleibt bewusst `Nicht verifiziert.`
- `POST /mcp-catalog` liegt jetzt ebenfalls in `Backend/handlers/mcp_catalog_routes.py` und ist ueber Direktvertraege, lokale HTTP-Vertraege und eine echte auth-geschuetzte Live-Probe mit vollstaendigem Backup/Restore von `config/mcp_catalog.json` abgesichert. Die operative Catalog-Wahrheit bleibt dabei in `Backend/mcp_catalog.py` plus `config/mcp_catalog.json`; der Handler bekommt Register-Funktion, RBAC-Operator-Menge und WebSocket-Broadcast nur per Injection.
- `POST /agents/create` liegt jetzt ebenfalls in `Backend/handlers/agents.py` und ist ueber Direktvertraege, lokale HTTP-Vertraege und eine echte auth-geschuetzte Live-Probe mit vollstaendigem Backup/Restore von `Backend/team.json` abgesichert; der Handler behaelt dabei die bestehende Agent-Builder-Wahrheit in `TEAM_CONFIG`, `_atomic_write_team_json`, Home-Verzeichnis-Erzeugung und `agent_created`-Broadcast bei.
- `POST /agents/{id}/setup-home` liegt jetzt ebenfalls in `Backend/handlers/agents.py` und ist ueber Direktvertraege, lokale HTTP-Vertraege, den nachgezogenen Buddy-Setup-Vertrag und eine echte auth-geschuetzte Live-Probe mit isoliertem Probe-Agenten abgesichert. Die operative Setup-Wahrheit bleibt dabei strikt verteilt:
  - Engine-Validierung ueber `_SETUP_CLI_BINARIES`
  - Home-Materialisierung ueber `handlers.cli._materialize_agent_setup_home(...)`
  - CLI-Persistenz-Sync ueber `server._sync_agent_persistent_cli_config(...)`
  - `handlers.agents.py` bekommt diese Teile nur per Injection und fuehrt den Rollback weiter zentral ueber `TEAM_CONFIG`.
- Die Creator-Implementierung von Claude/Viktor ist im Final-Re-Check belastbar: `73 passed` im Creator-Kernblock plus `4 passed` in `CREATOR_E2E=1 tests/test_creator_e2e_longrun.py`; live verifiziert sind jetzt `local-ingest`, `url-ingest`, `analyze`, `publish`, `batch-ingest`, `publish-batch`, `campaign create/plan/approve/metrics/import` sowie ein echter Speech-/Chunked-STT-Job ueber den laufenden Server. Weiter nicht voll live verifiziert bleiben nur `cancel`, `resume`, echter produktiver Multi-Channel-Dispatch und die fehlenden Creator-Job-/Campaign-MCP-Tools in `Backend/bridge_mcp.py`.

## Offene Punkte
- Neue Baseline fuer Slice 36 bestimmen
- naechster Kandidat ist der Runtime-Layout-/Capability-Cluster vor `BridgeHandler`
  - direkte Auth-/Route-Zerlegung ohne weitere Vorarbeit bleibt aktuell risikoreicher
- Beobachteter Altfehler nach kanonischem Neustart:
  - `POST /capability-library/recommend` liefert im laufenden System `500`
  - `Backend/logs/server.log` zeigt als direkte Ursache: fehlende Datei `/home/user/bridge/BRIDGE/config/capability_library.json`
- Beobachtete Runtime-Drift nach Slice 35:
  - `GET /health` -> `degraded`
  - `GET /status` / `GET /runtime` zeigen `codex` und `ordo` als disconnected/warn
  - isolierter Codex-CLI-E2E-Harness bleibt grün
  - `Nicht verifiziert.` ob slice-kausal oder unabhaengiger Runtime-Liveness-Pfad
- Creator-Erweiterung:
  - verifiziertes Pattern fuer parallele Arbeit:
    - neue HTTP-Domäne als `Backend/handlers/creator.py` (real vorhanden)
    - neue MCP-Tool-Gruppe als `Backend/bridge_mcp_creator.py` oder aequivalenter Helper
    - Integration in `Backend/server.py` und `Backend/bridge_mcp.py` bleibt bei Codex
- Automation-Cluster:
  - source-sensitive Rest:
    - die Regex-Matches fuer `run`/`webhook` liegen weiter in `Backend/server.py`
  - funktional ist der Automation-HTTP-Cluster jetzt vollstaendig in `Backend/handlers/automation_routes.py` gekapselt
- Workflow-Cluster:
  - auch der POST-Block liegt jetzt in `Backend/handlers/workflows.py`:
    - `POST /workflows/compile`
    - `POST /workflows/deploy`
    - `POST /workflows/deploy-template`
- Credential-Store-Cluster:
  - `GET/POST/DELETE /credentials/*` liegt jetzt in `Backend/handlers/credentials_routes.py`
  - ein vorbestehender decrypt-Fehler in `~/.config/bridge/credentials/custom.enc` bleibt als Altbestand sichtbar
- Aktueller Zeilenstand nach Slice 107:
  - `Backend/server.py` hat real `9696` Zeilen
- `Nicht verifiziert.`
  - isolierter natuerlicher Auto-Assign-Live-Fall in einer Runtime ohne konkurrierende aktive Worker
  - natuerlicher Buddy-Knowledge-Live-Rewrite-Fall nach `team.json`-Aenderung im laufenden System
  - natuerlicher Live-Distillation-Fall im laufenden System nach `10min` Initial-Delay und `4h` Intervall
  - natuerlicher Live-Auto-Generate-Fall mit echter Teamlead-Antwort und real geschriebener Instruktionsdatei
  - natuerlicher Live-Crash-Fall eines echten Codex-Agenten mit anschließendem Auto-Restart im Produktbetrieb
  - separater Write-/Deploy-Live-E2E fuer Workflow-Routen
  - echter Instanz-zu-Instanz-Federation-Live-E2E mit konfiguriertem Peer und Relay
