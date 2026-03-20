# Bridge Backend + Infrastruktur Referenz

- Generiert: 2026-03-10 22:12:25 UTC
- Scope: `Backend/server.py`, `Backend/server_bootstrap.py`, `Backend/server_startup.py`, `Backend/server_main.py`, `Backend/server_utils.py`, `Backend/server_engine_models.py`, `Backend/server_context_restore.py`, `Backend/server_request_auth.py`, `Backend/server_http_io.py`, `Backend/server_frontend_serve.py`, `Backend/server_message_audience.py`, `Backend/start_platform_runtime.py`, `Backend/websocket_server.py`, `Backend/bridge_mcp.py`, `Backend/bridge_watcher.py`, `Backend/tmux_manager.py`, `Backend/automation_engine.py`, `Backend/knowledge_engine.py`, `Backend/mcp_catalog.py`
- Zweck: API-/Infrastruktur-Dokumentation fuer Task `838393f0-866c-4435-b2cc-d10889ef618b`

## 1) Runtime-Architektur (Kurzueberblick)

- HTTP-Server: `127.0.0.1:9111` (`server.py`, `PORT = 9111`)
- WebSocket-Server: `127.0.0.1:9112` (`websocket_server.py`, `WS_PORT = 9112`)
- Startup-Orchestrierung: `server_startup.py` (Daemon-Threads, Automation-Scheduler, WebSocket-Thread, Restart-Wake, Supervisor)
- Server-Hauptlauf: `server_main.py` (Preload von Disk-/Registry-Zustand, HTTP-Bind/Serve-Lifecycle)
- Shared Server-Utilities: `server_utils.py` (Zeit-, Pfad- und Query-Parsing-Helfer)
- Engine-/Model-Registry: `server_engine_models.py` (CLI-spezifische Model-Discovery und Registry fuer `/engines/models`)
- Context-Restore-/Persistenz-Handoff: `server_context_restore.py` (Resume-Artefakt-Aufloesung, Restore-Message, Cooldown-Logik)
- Request-Auth-/Platform-Operator-Gates: `server_request_auth.py` (Token-Extraktion, Rollenaufloesung, Auth-Tiers)
- Generische HTTP-I/O-Helfer: `server_http_io.py` (CORS, JSON/Bytes-Responses, Request-Body-Parsing, Multipart, Rate-Limit-Check)
- Frontend-/Static-Serve-Helfer: `server_frontend_serve.py` (UI-Token-Injektion, `/`-/`/ui`-Serve und statische Frontend-Auslieferung)
- Message-Audience-Helfer: `server_message_audience.py` (serverseitige Zielauflösung für `all`, `all_managers`, `leads`, `team:*`)
- Startup-Runtime-Payload-Helper: `start_platform_runtime.py` (respektiert aktive Agenten im kanonischen Startpfad)
- Hauptdatenquellen: `team.json`, `runtime_team.json`, `tasks.json`, `messages/bridge.jsonl`, `automations.json`
- SoT fuer Agent-/Team-Struktur: `team.json` (plus Runtime-Overlay in `runtime_team.json`)

## 2) Authentifizierung und Zugriff

- Token-Quellen HTTP: `X-Bridge-Token` oder `Authorization: Bearer <token>`
- Token-Typen: `user`-Token, UI-Session-Token, Agent-Session-Token (inkl. Grace-Token-Fenster)
- GET ist aktuell im Default-Pfad public (`_path_requires_auth_get -> False`), POST/PATCH/DELETE werden je nach Tier/Pfad erzwungen
- Plattform-Operator-Gate fuer sensible Endpunkte via `_require_platform_operator(...)`

Auth-relevante Anker in `server.py`:

- L185: `BRIDGE_STRICT_AUTH = _env_flag("BRIDGE_STRICT_AUTH", True)` — **Default is True (strict mode)**. Set to False only for local development without tokens.
- L11013: `def _extract_auth_token(self) -> str:`
- L11022: `def _resolve_auth_identity(self) -> tuple[str, str | None]:`
- L11023: `token = self._extract_auth_token()`
- L11051: `def _require_authenticated(`
- L11054: `role, identity = self._resolve_auth_identity()`
- L11072: `ok, role, identity = self._require_authenticated(allow_user=allow_user, allow_agent=True)`
- L11080: `def _path_requires_auth_get(self, path: str) -> bool:`
- L11084: `def _path_requires_auth_post(self, path: str) -> bool:`
- L11168: `if BRIDGE_STRICT_AUTH and self._path_requires_auth_get(path):`
- L11169: `ok, _, _ = self._require_authenticated()`
- L13168: `if BRIDGE_STRICT_AUTH:`
- L13169: `ok, role, identity = self._require_authenticated()`
- L13773: `if BRIDGE_STRICT_AUTH and path == "/register":`
- L13786: `if BRIDGE_STRICT_AUTH and self._path_requires_auth_post(path):`
- L13787: `ok, _, _ = self._require_authenticated()`

## 3) HTTP API Endpunkte (`server.py`)

- Erkannt: 206 explizite Pfad-Checks (exact/prefix/regex) innerhalb `do_GET/POST/PATCH/PUT/DELETE`.
- Hinweis: Die Liste unten ist aus dem Quellcode extrahiert (line-basierte Inventarisierung).

| Method | Route-Muster | Typ | Source |
|---|---|---|---|
| `DELETE` | `^/guardrails/([a-zA-Z0-9_-]+)$` | `regex` | `server.py:19668` |
| `DELETE` | `/credentials/` | `prefix` | `server.py:19683` |
| `DELETE` | `^/tools/([a-zA-Z0-9_-]+)$` | `regex` | `server.py:19708` |
| `DELETE` | `^/workflows/([^/]+)$` | `regex` | `server.py:19733` |
| `DELETE` | `^/events/subscriptions/([a-zA-Z0-9_-]+)$` | `regex` | `server.py:19761` |
| `DELETE` | `^/board/projects/([a-z0-9][a-z0-9-]*)$` | `regex` | `server.py:19771` |
| `DELETE` | `^/subscriptions/([a-z0-9_-]+)$` | `regex` | `server.py:19814` |
| `DELETE` | `^/whiteboard/([^/]+)$` | `regex` | `server.py:19856` |
| `DELETE` | `^/teams/([a-z0-9_-]+)$` | `regex` | `server.py:19868` |
| `DELETE` | `^/task/([^/]+)$` | `regex` | `server.py:19907` |
| `DELETE` | `^/automations/([^/]+)$` | `regex` | `server.py:19965` |
| `GET` | `/api/` | `prefix` | `server.py:11160` |
| `GET` | `/status` | `exact` | `server.py:11211` |
| `GET` | `/health` | `exact` | `server.py:11215` |
| `GET` | `/server/restart-status` | `exact` | `server.py:11220` |
| `GET` | `/runtime` | `exact` | `server.py:11260` |
| `GET` | `/onboarding/status` | `exact` | `server.py:11264` |
| `GET` | `/activity` | `exact` | `server.py:11269` |
| `GET` | `/agents` | `exact` | `server.py:11307` |
| `GET` | `/skills` | `exact` | `server.py:11479` |
| `GET` | `^/skills/([^/]+)/content$` | `regex` | `server.py:11485` |
| `GET` | `^/skills/([^/]+)/section$` | `regex` | `server.py:11496` |
| `GET` | `/memory/stats` | `exact` | `server.py:11504` |
| `GET` | `/skills/proposals` | `exact` | `server.py:11527` |
| `GET` | `^/skills/([^/]+)$` | `regex` | `server.py:11538` |
| `GET` | `^/agents/([^/]+)$` | `regex` | `server.py:11558` |
| `GET` | `^/agents/([^/]+)/persistence$` | `regex` | `server.py:11635` |
| `GET` | `^/agents/([^/]+)/next-action$` | `regex` | `server.py:11776` |
| `GET` | `/tasks/summary` | `exact` | `server.py:11879` |
| `GET` | `/task/queue` | `exact` | `server.py:11928` |
| `GET` | `/task/tracker` | `exact` | `server.py:12055` |
| `GET` | `^/task/([^/]+)/history$` | `regex` | `server.py:12215` |
| `GET` | `^/task/([^/]+)$` | `regex` | `server.py:12233` |
| `GET` | `/scope/locks` | `exact` | `server.py:12247` |
| `GET` | `/scope/check` | `exact` | `server.py:12254` |
| `GET` | `/events/subscriptions` | `exact` | `server.py:12311` |
| `GET` | `/n8n/executions` | `exact` | `server.py:12320` |
| `GET` | `/n8n/workflows` | `exact` | `server.py:12334` |
| `GET` | `/workflows/capabilities` | `exact` | `server.py:12347` |
| `GET` | `^/workflows/([^/]+)/definition$` | `regex` | `server.py:12352` |
| `GET` | `/workflows` | `exact` | `server.py:12370` |
| `GET` | `/workflows/templates` | `exact` | `server.py:12383` |
| `GET` | `/workflows/tools` | `exact` | `server.py:12409` |
| `GET` | `/workflows/suggest` | `exact` | `server.py:12415` |
| `GET` | `/metrics/tokens` | `exact` | `server.py:12454` |
| `GET` | `/metrics/costs` | `exact` | `server.py:12464` |
| `GET` | `/metrics/prices` | `exact` | `server.py:12473` |
| `GET` | `/system/status` | `exact` | `server.py:12480` |
| `GET` | `/system/shutdown-status` | `exact` | `server.py:12485` |
| `GET` | `/credentials/` | `prefix` | `server.py:12499` |
| `GET` | `/engines/models` | `exact` | `server.py:12530` |
| `GET` | `/cli/detect` | `exact` | `server.py:12535` |
| `GET` | `/capability-library` | `exact` | `server.py:12593` |
| `GET` | `/capability-library/facets` | `exact` | `server.py:12628` |
| `GET` | `^/capability-library/([^/]+)$` | `regex` | `server.py:12632` |
| `GET` | `/tools` | `exact` | `server.py:12645` |
| `GET` | `^/tools/([a-zA-Z0-9_-]+)$` | `regex` | `server.py:12651` |
| `GET` | `/guardrails` | `exact` | `server.py:12664` |
| `GET` | `/guardrails/catalog` | `exact` | `server.py:12678` |
| `GET` | `/guardrails/presets` | `exact` | `server.py:12688` |
| `GET` | `/guardrails/summary` | `exact` | `server.py:12694` |
| `GET` | `/guardrails/violations` | `exact` | `server.py:12716` |
| `GET` | `/creator/social-presets` | `exact` | `server.py:12739` |
| `GET` | `/execution/summary` | `exact` | `server.py:12749` |
| `GET` | `/execution/metrics` | `exact` | `server.py:12781` |
| `GET` | `/execution/runs` | `exact` | `server.py:12814` |
| `GET` | `^/execution/runs/([A-Za-z0-9._-]+)$` | `regex` | `server.py:12846` |
| `GET` | `^/guardrails/([a-zA-Z0-9_-]+)$` | `regex` | `server.py:12868` |
| `GET` | `/subscriptions` | `exact` | `server.py:12882` |
| `GET` | `^/files/([^/]+)$` | `regex` | `server.py:12921` |
| `GET` | `/whiteboard` | `exact` | `server.py:12959` |
| `GET` | `/teamlead/scope` | `exact` | `server.py:12981` |
| `GET` | `/projects` | `exact` | `server.py:13016` |
| `GET` | `/pick-directory` | `exact` | `server.py:13022` |
| `GET` | `/projects/open` | `exact` | `server.py:13048` |
| `GET` | `/logs` | `exact` | `server.py:13095` |
| `GET` | `/agent/config` | `exact` | `server.py:13107` |
| `GET` | `/history` | `exact` | `server.py:13139` |
| `GET` | `/receive/` | `prefix` | `server.py:13162` |
| `GET` | `/memory/status` | `exact` | `server.py:13243` |
| `GET` | `/memory/read` | `exact` | `server.py:13256` |
| `GET` | `/board/projects` | `exact` | `server.py:13277` |
| `GET` | `^/board/projects/([a-z0-9][a-z0-9-]*)$` | `regex` | `server.py:13289` |
| `GET` | `/board/agents` | `exact` | `server.py:13305` |
| `GET` | `^/board/agents/([^/]+)/projects$` | `regex` | `server.py:13309` |
| `GET` | `/approval/pending` | `exact` | `server.py:13316` |
| `GET` | `^/approval/([^/]+)$` | `regex` | `server.py:13339` |
| `GET` | `/standing-approval/list` | `exact` | `server.py:13354` |
| `GET` | `/team/orgchart` | `exact` | `server.py:13365` |
| `GET` | `/team/projects` | `exact` | `server.py:13406` |
| `GET` | `/mcp-catalog` | `exact` | `server.py:13464` |
| `GET` | `/industry-templates` | `exact` | `server.py:13473` |
| `GET` | `/teams` | `exact` | `server.py:13496` |
| `GET` | `^/teams/([a-z0-9_-]+)$` | `regex` | `server.py:13551` |
| `GET` | `^/team/context/([a-z0-9_-]+)$` | `regex` | `server.py:13633` |
| `GET` | `/automations` | `exact` | `server.py:13704` |
| `GET` | `^/automations/([^/]+)$` | `regex` | `server.py:13711` |
| `GET` | `^/automations/([^/]+)/history$` | `regex` | `server.py:13723` |
| `GET` | `^/automations/([^/]+)/history/([^/]+)$` | `regex` | `server.py:13736` |
| `PATCH` | `^/skills/proposals/([^/]+)$` | `regex` | `server.py:18626` |
| `PATCH` | `^/workflows/([^/]+)/toggle$` | `regex` | `server.py:18683` |
| `PATCH` | `^/task/([^/]+)$` | `regex` | `server.py:18715` |
| `PATCH` | `^/agents/([^/]+)/active$` | `regex` | `server.py:18848` |
| `PATCH` | `^/agents/([^/]+)/mode$` | `regex` | `server.py:18939` |
| `PATCH` | `^/automations/([^/]+)/active$` | `regex` | `server.py:18973` |
| `PATCH` | `^/automations/([^/]+)/pause$` | `regex` | `server.py:18991` |
| `PATCH` | `^/agents/([^/]+)$` | `regex` | `server.py:19006` |
| `PATCH` | `^/agents/([^/]+)/parent$` | `regex` | `server.py:19163` |
| `POST` | `/api/` | `prefix` | `server.py:13765` |
| `POST` | `/stream_chunk` | `exact` | `server.py:13791` |
| `POST` | `/activity` | `exact` | `server.py:13803` |
| `POST` | `/server/restart` | `exact` | `server.py:13941` |
| `POST` | `/server/restart/force` | `exact` | `server.py:13970` |
| `POST` | `/server/restart/cancel` | `exact` | `server.py:13992` |
| `POST` | `/server/restart/reset` | `exact` | `server.py:13997` |
| `POST` | `/teams` | `exact` | `server.py:14004` |
| `POST` | `/mcp-catalog` | `exact` | `server.py:14066` |
| `POST` | `/agents/create` | `exact` | `server.py:14098` |
| `POST` | `/tools/register` | `exact` | `server.py:14233` |
| `POST` | `^/tools/([a-zA-Z0-9_-]+)/execute$` | `regex` | `server.py:14288` |
| `POST` | `/capability-library/search` | `exact` | `server.py:14317` |
| `POST` | `/capability-library/recommend` | `exact` | `server.py:14360` |
| `POST` | `/skills/propose` | `exact` | `server.py:14393` |
| `POST` | `/memory/index` | `exact` | `server.py:14455` |
| `POST` | `/memory/search` | `exact` | `server.py:14514` |
| `POST` | `/memory/delete` | `exact` | `server.py:14564` |
| `POST` | `/media/info` | `exact` | `server.py:14596` |
| `POST` | `/media/convert` | `exact` | `server.py:14624` |
| `POST` | `/media/extract` | `exact` | `server.py:14671` |
| `POST` | `/creator/local-ingest` | `exact` | `server.py:14727` |
| `POST` | `/creator/url-ingest` | `exact` | `server.py:14755` |
| `POST` | `/creator/write-srt` | `exact` | `server.py:14783` |
| `POST` | `/creator/highlights` | `exact` | `server.py:14805` |
| `POST` | `/creator/export-clip` | `exact` | `server.py:14830` |
| `POST` | `/creator/export-social-clip` | `exact` | `server.py:14857` |
| `POST` | `/creator/package-social` | `exact` | `server.py:14891` |
| `POST` | `/system/shutdown` | `exact` | `server.py:14944` |
| `POST` | `/system/resume` | `exact` | `server.py:15002` |
| `POST` | `/credentials/` | `prefix` | `server.py:15032` |
| `POST` | `/metrics/tokens` | `exact` | `server.py:15063` |
| `POST` | `/events/subscribe` | `exact` | `server.py:15086` |
| `POST` | `/workflows/compile` | `exact` | `server.py:15115` |
| `POST` | `/workflows/deploy` | `exact` | `server.py:15143` |
| `POST` | `/workflows/deploy-template` | `exact` | `server.py:15208` |
| `POST` | `/task/create` | `exact` | `server.py:15339` |
| `POST` | `^/task/([^/]+)/claim$` | `regex` | `server.py:15550` |
| `POST` | `^/task/([^/]+)/ack$` | `regex` | `server.py:15609` |
| `POST` | `^/task/([^/]+)/done$` | `regex` | `server.py:15645` |
| `POST` | `^/task/([^/]+)/verify$` | `regex` | `server.py:15771` |
| `POST` | `^/task/([^/]+)/fail$` | `regex` | `server.py:15812` |
| `POST` | `^/task/([^/]+)/checkin$` | `regex` | `server.py:15867` |
| `POST` | `/subscriptions` | `exact` | `server.py:15915` |
| `POST` | `/scope/lock` | `exact` | `server.py:15981` |
| `POST` | `/scope/unlock` | `exact` | `server.py:16059` |
| `POST` | `/whiteboard` | `exact` | `server.py:16114` |
| `POST` | `/whiteboard/post` | `exact` | `server.py:16165` |
| `POST` | `^/escalation/([^/]+)/resolve$` | `regex` | `server.py:16199` |
| `POST` | `^/agents/([^/]+)/start$` | `regex` | `server.py:16224` |
| `POST` | `^/messages/(\d+)/reaction$` | `regex` | `server.py:16318` |
| `POST` | `/send` | `exact` | `server.py:16381` |
| `POST` | `/onboarding/start` | `exact` | `server.py:16522` |
| `POST` | `/skills/assign` | `exact` | `server.py:16541` |
| `POST` | `/register` | `exact` | `server.py:16609` |
| `POST` | `/heartbeat` | `exact` | `server.py:16834` |
| `POST` | `^/state/([^/]+)$` | `regex` | `server.py:16866` |
| `POST` | `/agents/cleanup` | `exact` | `server.py:16894` |
| `POST` | `/runtime/stop` | `exact` | `server.py:16908` |
| `POST` | `/teamlead/activate` | `exact` | `server.py:16931` |
| `POST` | `/teamlead/control` | `exact` | `server.py:16961` |
| `POST` | `/teamlead/scope` | `exact` | `server.py:16999` |
| `POST` | `/runtime/configure` | `exact` | `server.py:17051` |
| `POST` | `/projects/create` | `exact` | `server.py:17350` |
| `POST` | `/projects/save-notes` | `exact` | `server.py:17363` |
| `POST` | `/projects/upload` | `exact` | `server.py:17402` |
| `POST` | `/chat/upload` | `exact` | `server.py:17458` |
| `POST` | `/agent/config` | `exact` | `server.py:17513` |
| `POST` | `/agent/config/generate` | `exact` | `server.py:17572` |
| `POST` | `/memory/scaffold` | `exact` | `server.py:17626` |
| `POST` | `/memory/write` | `exact` | `server.py:17643` |
| `POST` | `/memory/episode` | `exact` | `server.py:17670` |
| `POST` | `/memory/migrate` | `exact` | `server.py:17695` |
| `POST` | `/board/projects` | `exact` | `server.py:17716` |
| `POST` | `^/board/projects/([a-z0-9][a-z0-9-]*)/teams$` | `regex` | `server.py:17732` |
| `POST` | `/approval/request` | `exact` | `server.py:17771` |
| `POST` | `/approval/respond` | `exact` | `server.py:17883` |
| `POST` | `^/approval/([^/]+)/edit$` | `regex` | `server.py:17960` |
| `POST` | `/standing-approval/create` | `exact` | `server.py:18022` |
| `POST` | `^/standing-approval/(SA-[A-Z0-9]+)/revoke$` | `regex` | `server.py:18086` |
| `POST` | `/team/reload` | `exact` | `server.py:18120` |
| `POST` | `^/agents/([^/]+)/restart$` | `regex` | `server.py:18129` |
| `POST` | `^/agents/([^/]+)/avatar$` | `regex` | `server.py:18197` |
| `POST` | `/automations` | `exact` | `server.py:18263` |
| `POST` | `^/automations/([^/]+)/run$` | `regex` | `server.py:18335` |
| `POST` | `^/automations/([^/]+)/webhook$` | `regex` | `server.py:18359` |
| `POST` | `/execution/runs/prune` | `exact` | `server.py:18382` |
| `POST` | `/guardrails/incident-bundle` | `exact` | `server.py:18416` |
| `POST` | `/audit/export` | `exact` | `server.py:18487` |
| `POST` | `^/guardrails/([a-zA-Z0-9_-]+)/apply-preset$` | `regex` | `server.py:18564` |
| `POST` | `/guardrails/evaluate` | `exact` | `server.py:18595` |
| `PUT` | `^/workflows/([^/]+)/definition$` | `regex` | `server.py:19283` |
| `PUT` | `^/guardrails/([a-zA-Z0-9_-]+)$` | `regex` | `server.py:19366` |
| `PUT` | `^/board/projects/([a-z0-9][a-z0-9-]*)$` | `regex` | `server.py:19396` |
| `PUT` | `^/subscriptions/([a-z0-9_-]+)$` | `regex` | `server.py:19434` |
| `PUT` | `^/agents/([^/]+)/subscription$` | `regex` | `server.py:19477` |
| `PUT` | `^/teams/([a-z0-9_-]+)/members$` | `regex` | `server.py:19540` |
| `PUT` | `^/automations/([^/]+)$` | `regex` | `server.py:19588` |

### 3.1 WebSocket-Protokoll

- Entry: `ws_handler(websocket)` (`websocket_server.py`)
- Auth-Handshake: erwartet JSON mit `token` oder Header/Query-Token (strict auth mode).
- Message-Typen: `ping/pong`, agent-spezifische Nutzdaten, serverseitige Push-Events.
- Serverstart: `run_websocket_server()` -> `websockets.asyncio.server.serve(...)` auf `WS_PORT`.

### 3.2 Startup-Orchestrierung

- Startup-Orchestrierung: `start_background_services()` (`server_startup.py`)
- Automation-Scheduler-Bootstrap:
  - `_start_automation_scheduler()`
  - `condition_context_callback=_automation_condition_context`
  - `idle_check_callback=_is_agent_idle`
- Background-Threads:
  - `auto-gen-watcher`
  - `agent-health-checker`
  - `health-monitor`
  - `cli-output-monitor`
  - `rate-limit-resume`
  - `v3-cleanup`
  - `task-timeout-checker`
  - `heartbeat-prompter`
  - `codex-cli-hook`
  - `distillation-daemon`
  - `task-pusher`
  - `auto-assign`
  - `buddy-knowledge`
  - `websocket-server`
- Nachgelagerte Startup-Seitenfolgen:
  - `restart-wake` nur bei realem Wrapper-Restart
  - `supervisor` immer nach dem Thread-/Scheduler-Start

## 4) MCP Tool-API (`bridge_mcp.py`)

- Gesamtanzahl Bridge-MCP-Tools: **172** (`async def bridge_*`).
- Rueckgabeformat: i.d.R. JSON-String (`-> str`), inhaltlich `{ok, error, ...}` je Tool.
- Konvention: Tool-Namen spiegeln HTTP-Bridge-Routen und Feature-Module (tasks, browser, knowledge, automation, etc.).

### 4.1 Tool-Inventar (Signaturen)

| Tool | Signatur | Beschreibung (Kurz) | Source |
|---|---|---|---|
| `bridge_register` | `bridge_register(agent_id: str, role: str = '', capabilities: list[str] | None = None)` | Register this agent with the Bridge server. Must be called once before using other bridge tools. Starts background WebSocket listener and... | `bridge_mcp.py:1561` |
| `bridge_send` | `bridge_send(to: str, content: str, team: str | None = None)` | Send a message to another agent or broadcast. The 'from' field is set automatically from your registration. Valid recipients: user, teaml... | `bridge_mcp.py:1624` |
| `bridge_receive` | `bridge_receive()` | Get buffered messages received via WebSocket push. Returns all messages since last call and clears the buffer. No polling needed — messag... | `bridge_mcp.py:1659` |
| `bridge_heartbeat` | `bridge_heartbeat()` | Manually send a heartbeat to the Bridge server. Note: Heartbeats are also sent automatically every 30 seconds. | `bridge_mcp.py:1675` |
| `bridge_activity` | `bridge_activity(action: str, target: str = '', description: str = '')` | Report your current activity to the Bridge server. Use before file edits to coordinate with other agents. | `bridge_mcp.py:1695` |
| `bridge_check_activity` | `bridge_check_activity()` | Get all current agent activities from the Bridge server. | `bridge_mcp.py:1724` |
| `bridge_history` | `bridge_history(limit: int = 20, team: str | None = None, since: str | None = None)` | Get message history from the Bridge server. Optional team filter returns only messages tagged with that team. Optional since= ISO timesta... | `bridge_mcp.py:1738` |
| `bridge_health` | `bridge_health()` | Get comprehensive health status of all Bridge components. Returns status for server, websocket, agents, watcher, forwarder, and messages. | `bridge_mcp.py:1760` |
| `bridge_task_create` | `bridge_task_create(task_type: str, title: str, description: str, team: str = '', priority: int = 1, labels: list[str] | None = None, assigned_to: str = '', files: list[str] | None = None, ack_deadline_seconds: int = 120, max_retries: int = 2, idempotency_key: str = '', blocker_reason: str = '')` | Create a structured task for an agent. Types: code_change, review, test, research, general, task. Requires title. Optionally assign to a ... | `bridge_mcp.py:1781` |
| `bridge_task_claim` | `bridge_task_claim(task_id: str)` | Claim a task (state: created → claimed). You become the assigned agent. | `bridge_mcp.py:1833` |
| `bridge_task_ack` | `bridge_task_ack(task_id: str)` | Acknowledge task start (state: claimed → acked). Confirms you are actively working on it. | `bridge_mcp.py:1849` |
| `bridge_task_done` | `bridge_task_done(task_id: str, result_summary: str = '', result_code: str = 'success', evidence_type: str = '', evidence_ref: str = '')` | Mark a task as done with result data (state: claimed/acked → done). result_code: success, partial, skipped, error, timeout. PFLICHT bei s... | `bridge_mcp.py:1871` |
| `bridge_task_fail` | `bridge_task_fail(task_id: str, error: str = 'unknown error')` | Mark a task as failed with error message (any active state → failed). | `bridge_mcp.py:1900` |
| `bridge_task_queue` | `bridge_task_queue(state: str = '', agent_id: str = '', team: str = '', limit: int = 0)` | List tasks from the queue. Filter by state (created/claimed/acked/done/failed) and/or agent_id. Supports limit for bounded shared-queue r... | `bridge_mcp.py:1920` |
| `bridge_task_get` | `bridge_task_get(task_id: str)` | Get details of a single task by ID. | `bridge_mcp.py:1953` |
| `bridge_task_update` | `bridge_task_update(task_id: str, title: str = '', priority: int = 0, assigned_to: str = '', labels: list[str] | None = None, team: str = '', description: str = '', blocker_reason: str | None = None)` | Update an existing task. Can change title, priority, assigned_to, labels, team. Only allowed for assigned_to, created_by, or team-lead. | `bridge_mcp.py:1970` |
| `bridge_scope_lock` | `bridge_scope_lock(task_id: str, paths: list[str], lock_type: str = 'file', ttl: int = 1800)` | Acquire scope locks for file/directory paths before editing. Prevents other agents from modifying the same files. Locks expire after TTL ... | `bridge_mcp.py:2023` |
| `bridge_scope_unlock` | `bridge_scope_unlock(task_id: str, paths: list[str] | None = None)` | Release scope locks for a task. If paths are specified, only those paths are unlocked. If no paths specified, all locks for the task are ... | `bridge_mcp.py:2054` |
| `bridge_scope_check` | `bridge_scope_check(paths: list[str])` | Check if file/directory paths are free to lock. Returns which paths are free and which are locked (with lock owner info). | `bridge_mcp.py:2081` |
| `bridge_scope_locks` | `bridge_scope_locks()` | List all currently active scope locks across all agents. | `bridge_mcp.py:2094` |
| `bridge_whiteboard_post` | `bridge_whiteboard_post(type: str, content: str, task_id: str = '', scope_label: str = '', severity: str = 'info', ttl: int = 3600, tags: list[str] | None = None)` | Post or update an entry on the team whiteboard (Live-Board). Types: status, blocker, result, alert, escalation_response. Severity: info, ... | `bridge_mcp.py:2116` |
| `bridge_whiteboard_read` | `bridge_whiteboard_read(agent_id: str = '', type: str = '', severity: str = '', limit: int = 50, priority: int = 0)` | Read entries from the team whiteboard (Live-Board). Filter by agent_id, type, severity, or limit. Use priority=3 to get only critical (St... | `bridge_mcp.py:2156` |
| `bridge_whiteboard_delete` | `bridge_whiteboard_delete(entry_id: str)` | Delete a whiteboard entry by its ID. | `bridge_mcp.py:2184` |
| `bridge_credential_store` | `bridge_credential_store(service: str, key: str, value: str)` | Store a credential (API key, token, password) securely. Encrypted at rest with Fernet. You can only read/delete credentials you created. ... | `bridge_mcp.py:2207` |
| `bridge_credential_get` | `bridge_credential_get(service: str, key: str)` | Retrieve a stored credential by service and key. You can only access credentials you created (or management agents can access all). Valid... | `bridge_mcp.py:2234` |
| `bridge_credential_delete` | `bridge_credential_delete(service: str, key: str)` | Delete a stored credential by service and key. You can only delete credentials you created (or management agents can delete all). Valid s... | `bridge_mcp.py:2259` |
| `bridge_credential_list` | `bridge_credential_list(service: str)` | List credential keys for a service. Only shows keys you have access to. Valid services: google, github, email, wallet, phone, custom. | `bridge_mcp.py:2283` |
| `bridge_task_checkin` | `bridge_task_checkin(task_id: str, note: str = '')` | Send a heartbeat/check-in for a running task. Resets the task timeout timer and optionally updates a status note. Call this periodically ... | `bridge_mcp.py:2311` |
| `bridge_escalation_resolve` | `bridge_escalation_resolve(task_id: str, action: str, reassign_to: str = '', extend_minutes: int = 30)` | Resolve a Stage 3 escalation (Owner-Entscheidung). Actions: extend (give more time), reassign (assign to another agent), cancel (abort tas... | `bridge_mcp.py:2340` |
| `bridge_save_context` | `bridge_save_context(summary: str, open_tasks: list[str] | None = None)` | Save your current context summary and open tasks to the server. Call this after completing a task or before expected context loss. The sa... | `bridge_mcp.py:2370` |
| `bridge_approval_request` | `bridge_approval_request(action: str, target: str, description: str, risk_level: str = 'low', payload: dict[str, Any] | None = None, timeout_seconds: int = 300)` | Request approval for a real-world action (email, phone call, etc.). Returns a request_id. The request is shown to the user in the Bridge ... | `bridge_mcp.py:2403` |
| `bridge_approval_check` | `bridge_approval_check(request_id: str)` | Check the status of an approval request by its request_id. Returns: pending, approved, denied, or expired. | `bridge_mcp.py:2440` |
| `bridge_approval_wait` | `bridge_approval_wait(request_id: str, poll_interval: int = 5, max_wait: int = 300)` | Wait for an approval decision. Polls every 5 seconds until the request is approved, denied, or expired. Returns the final status. Use thi... | `bridge_mcp.py:2458` |
| `bridge_email_send` | `bridge_email_send(to: str, subject: str, body: str)` | Send an email through the Bridge email system. Creates an approval request — the email is only sent after the owner approves. Returns immediate... | `bridge_mcp.py:2814` |
| `bridge_email_execute` | `bridge_email_execute(request_id: str)` | Execute a previously approved email send. Only works if the approval request has status 'approved'. Call this after bridge_approval_wait ... | `bridge_mcp.py:2878` |
| `bridge_email_read` | `bridge_email_read(limit: int = 10, sender: str = '', subject: str = '')` | Read emails from the Bridge email inbox. No approval needed. Returns recent emails with sender, subject, date, and body preview. | `bridge_mcp.py:2941` |
| `bridge_slack_send` | `bridge_slack_send(channel: str, message: str)` | Send a message to a Slack channel through the Bridge. Creates an approval request — the owner must approve before the message is sent. After ap... | `bridge_mcp.py:3058` |
| `bridge_slack_execute` | `bridge_slack_execute(request_id: str)` | Execute a previously approved Slack message send. Only works if the approval request has status 'approved'. | `bridge_mcp.py:3113` |
| `bridge_slack_read` | `bridge_slack_read(channel: str, limit: int = 20)` | Read messages from a Slack channel. No approval needed. Returns recent messages with author, timestamp, and text. | `bridge_mcp.py:3170` |
| `bridge_whatsapp_send` | `bridge_whatsapp_send(to: str, message: str = '', media_path: str = '')` | Send a WhatsApp message (text and/or image) through the Bridge. For images, pass media_path (absolute path to file on disk). Creates an a... | `bridge_mcp.py:3515` |
| `bridge_whatsapp_execute` | `bridge_whatsapp_execute(request_id: str)` | Execute a previously approved WhatsApp message send. Only works if the approval request has status 'approved'. | `bridge_mcp.py:3612` |
| `bridge_whatsapp_read` | `bridge_whatsapp_read(limit: int = 20, contact: str = '')` | Read recent WhatsApp messages. No approval needed. Returns recent messages with sender, timestamp, and text. | `bridge_mcp.py:3679` |
| `bridge_todoist_read` | `bridge_todoist_read(filter: str = 'today', project: str = '', limit: int = 20)` | Read Todoist tasks. No approval needed. Filter options: 'today', 'overdue', 'tomorrow', '7 days', 'priority 1', '#ProjectName', '@label'.... | `bridge_mcp.py:3792` |
| `bridge_todoist_create` | `bridge_todoist_create(content: str, description: str = '', due_string: str = '', priority: int = 1, project_id: str = '', labels: str = '')` | Create a new Todoist task. Requires MEDIUM approval. Provide content (title), optional description, due_string ('today', 'tomorrow', 'nex... | `bridge_mcp.py:3830` |
| `bridge_todoist_execute` | `bridge_todoist_execute(request_id: str)` | Execute a previously approved Todoist action. Works for: todoist_create, todoist_update, todoist_delete. Only works if approval status is... | `bridge_mcp.py:3905` |
| `bridge_todoist_update` | `bridge_todoist_update(task_id: str, content: str = '', description: str = '', due_string: str = '', priority: int = 0)` | Update an existing Todoist task. Requires MEDIUM approval. Provide task_id and fields to change (content, description, due_string, priori... | `bridge_mcp.py:4007` |
| `bridge_todoist_complete` | `bridge_todoist_complete(task_id: str)` | Mark a Todoist task as completed. No approval needed (reversible via reopen). | `bridge_mcp.py:4088` |
| `bridge_todoist_reopen` | `bridge_todoist_reopen(task_id: str)` | Reopen a completed Todoist task. No approval needed (undo of complete). | `bridge_mcp.py:4107` |
| `bridge_todoist_delete` | `bridge_todoist_delete(task_id: str)` | Delete a Todoist task permanently. Requires HIGH approval (irreversible). | `bridge_mcp.py:4126` |
| `bridge_browser_research` | `bridge_browser_research(url: str, question: str)` | Navigate to a URL, capture browser snapshot + screenshot, and return structured research data. No approval required. | `bridge_mcp.py:4219` |
| `bridge_browser_action` | `bridge_browser_action(url: str, action_description: str, risk_level: str = 'medium')` | Create approval request for a browser action with consequence. Captures a screenshot preview before requesting approval. | `bridge_mcp.py:4313` |
| `bridge_stealth_start` | `bridge_stealth_start(proxy: str = '', user_agent: str = '', headless: bool = True, profile: str = '')` | Start a protected-site browser session using Playwright (compatibility mode). Returns session_id for subsequent calls. Max 3 concurrent sessio... | `bridge_mcp.py:4498` |
| `bridge_stealth_goto` | `bridge_stealth_goto(session_id: str, url: str, timeout: int = 30000)` | Navigate to URL in stealth session. Returns page title and content preview. | `bridge_mcp.py:4665` |
| `bridge_stealth_content` | `bridge_stealth_content(session_id: str)` | Get current page HTML content from stealth session. | `bridge_mcp.py:4726` |
| `bridge_stealth_fingerprint_snapshot` | `bridge_stealth_fingerprint_snapshot(session_id: str)` | Capture a browser-level fingerprint snapshot from a stealth session for lab analysis. | `bridge_mcp.py:4760` |
| `bridge_stealth_screenshot` | `bridge_stealth_screenshot(session_id: str, full_page: bool = True)` | Take screenshot of current page in stealth session. Returns file path. | `bridge_mcp.py:4783` |
| `bridge_stealth_click` | `bridge_stealth_click(session_id: str, selector: str)` | Click element by CSS selector in stealth session. | `bridge_mcp.py:4803` |
| `bridge_stealth_fill` | `bridge_stealth_fill(session_id: str, selector: str, value: str)` | Fill input field by CSS selector in stealth session. | `bridge_mcp.py:4827` |
| `bridge_stealth_evaluate` | `bridge_stealth_evaluate(session_id: str, expression: str)` | Execute JavaScript on page in stealth session. Returns result. | `bridge_mcp.py:4846` |
| `bridge_stealth_file_upload` | `bridge_stealth_file_upload(session_id: str, selector: str, file_path: str)` | Upload a file via a file input element in a stealth browser session. Selector should target an <input type='file'> element. | `bridge_mcp.py:4868` |
| `bridge_stealth_close` | `bridge_stealth_close(session_id: str)` | Close stealth browser session and free resources. | `bridge_mcp.py:4896` |
| `bridge_captcha_solve` | `bridge_captcha_solve(captcha_type: str, website_url: str, website_key: str, min_score: float = 0.7, provider: str = 'auto')` | Solve a CAPTCHA using CAPSolver or Anti-Captcha (fallback). Supported types: recaptcha_v2, recaptcha_v3, turnstile, hcaptcha, funcaptcha,... | `bridge_mcp.py:5060` |
| `bridge_cdp_connect` | `bridge_cdp_connect(port: int = 9222)` | Connect to Chrome via CDP (Chrome DevTools Protocol). Auto-starts headless Chrome if no instance found. Returns list of open tabs/pages. | `bridge_mcp.py:5198` |
| `bridge_cdp_tabs` | `bridge_cdp_tabs()` | List all open tabs in the owner's browser with URLs and titles. | `bridge_mcp.py:5221` |
| `bridge_cdp_navigate` | `bridge_cdp_navigate(url: str, tab_index: str = '0:0')` | Navigate a tab in the owner's browser to a URL. Specify tab index (from bridge_cdp_tabs) or uses active tab. | `bridge_mcp.py:5252` |
| `bridge_cdp_screenshot` | `bridge_cdp_screenshot(tab_index: str = '0:0', full_page: bool = False)` | Take a screenshot of a tab in the owner's browser. Returns file path to saved screenshot. | `bridge_mcp.py:5273` |
| `bridge_cdp_click` | `bridge_cdp_click(selector: str, tab_index: str = '0:0')` | Click an element by CSS selector in the owner's browser. | `bridge_mcp.py:5291` |
| `bridge_cdp_fill` | `bridge_cdp_fill(selector: str, value: str, tab_index: str = '0:0')` | Fill an input field by CSS selector in the owner's browser. | `bridge_mcp.py:5308` |
| `bridge_cdp_evaluate` | `bridge_cdp_evaluate(expression: str, tab_index: str = '0:0')` | Execute JavaScript on a page in the owner's browser. Returns result. | `bridge_mcp.py:5325` |
| `bridge_cdp_content` | `bridge_cdp_content(tab_index: str = '0:0')` | Get the HTML content of a page in the owner's browser. | `bridge_mcp.py:5342` |
| `bridge_cdp_disconnect` | `bridge_cdp_disconnect()` | Disconnect from the owner's browser. Does NOT close the browser. | `bridge_mcp.py:5368` |
| `bridge_cdp_new_tab` | `bridge_cdp_new_tab(url: str = 'about:blank')` | Open a new tab in the owner's browser and navigate to a URL. Returns the new tab index. | `bridge_mcp.py:5392` |
| `bridge_cdp_close_tab` | `bridge_cdp_close_tab(tab_index: str)` | Close a specific tab in the owner's browser by index. Use bridge_cdp_tabs to find indices. | `bridge_mcp.py:5417` |
| `bridge_cdp_file_upload` | `bridge_cdp_file_upload(selector: str, file_path: str, tab_index: str = '0:0')` | Upload a file via a file input element in the owner's browser (CDP). Selector should target an <input type='file'> element. | `bridge_mcp.py:5438` |
| `bridge_browser_open` | `bridge_browser_open(url: str = 'about:blank', engine: str = 'auto', headless: bool = True, proxy: str = '', user_agent: str = '', profile: str = '')` | Open a unified browser session. Choose engine: 'stealth' (compatibility-enhanced Playwright), 'cdp' (Chrome DevTools, the user's browser), or 'auto' (... | `bridge_mcp.py:5645` |
| `bridge_browser_nav` | `bridge_browser_nav(session_id: str, url: str)` | Navigate a unified browser session to a URL. Works with any engine (stealth/cdp) transparently. | `bridge_mcp.py:6139` |
| `bridge_browser_observe` | `bridge_browser_observe(session_id: str, max_nodes: int = 50)` | Capture a semantic snapshot of interactive elements in a unified browser session. Returns stable refs that can be used with bridge_browse... | `bridge_mcp.py:6200` |
| `bridge_browser_find_refs` | `bridge_browser_find_refs(session_id: str, query: str = '', tag: str = '', role: str = '', name: str = '', placeholder: str = '', text: str = '', exact: bool = False, max_results: int = 5)` | Resolve semantic browser targets to stable refs using query or explicit field filters. Returns scored candidates that can be used with br... | `bridge_mcp.py:6240` |
| `bridge_browser_clk` | `bridge_browser_clk(session_id: str, selector: str)` | Click an element in a unified browser session by CSS selector. Works with any engine (stealth/cdp) transparently. | `bridge_mcp.py:6339` |
| `bridge_browser_click_ref` | `bridge_browser_click_ref(session_id: str, ref: str)` | Click an observed element in a unified browser session by stable ref. Call bridge_browser_observe first to obtain refs. | `bridge_mcp.py:6398` |
| `bridge_browser_fll` | `bridge_browser_fll(session_id: str, selector: str, value: str)` | Fill an input field in a unified browser session. Works with any engine (stealth/cdp) transparently. | `bridge_mcp.py:6454` |
| `bridge_browser_fill_ref` | `bridge_browser_fill_ref(session_id: str, ref: str, value: str)` | Fill an observed input element in a unified browser session by stable ref. Call bridge_browser_observe first to obtain refs. | `bridge_mcp.py:6502` |
| `bridge_browser_cnt` | `bridge_browser_cnt(session_id: str)` | Get page content (HTML text) from a unified browser session. Works with any engine (stealth/cdp) transparently. | `bridge_mcp.py:6558` |
| `bridge_browser_verify` | `bridge_browser_verify(session_id: str, url_contains: str = '', title_contains: str = '', text_contains: str = '', selector_exists: str = '', selector_missing: str = '', value_selector: str = '', value_contains: str = '', value_equals: str = '', active_selector: str = '')` | Verify a unified browser session against simple postconditions such as url, title, text, or selector presence. Returns structured pass/fa... | `bridge_mcp.py:6603` |
| `bridge_browser_click_ref_verify` | `bridge_browser_click_ref_verify(session_id: str, ref: str, url_contains: str = '', title_contains: str = '', text_contains: str = '', selector_exists: str = '', selector_missing: str = '', active_selector: str = '')` | Click a browser element by ref and immediately verify postconditions such as url, title, text, selector presence, or active element. | `bridge_mcp.py:6731` |
| `bridge_browser_fill_ref_verify` | `bridge_browser_fill_ref_verify(session_id: str, ref: str, value: str, url_contains: str = '', title_contains: str = '', text_contains: str = '', selector_exists: str = '', selector_missing: str = '')` | Fill a browser input by ref and immediately verify the resulting field value plus optional postconditions such as url, title, text, or se... | `bridge_mcp.py:6829` |
| `bridge_browser_fingerprint_snapshot` | `bridge_browser_fingerprint_snapshot(session_id: str)` | Capture a browser-level fingerprint snapshot from a unified browser session. Useful for compatibility lab validation and regression trac... | `bridge_mcp.py:6912` |
| `bridge_browser_scr` | `bridge_browser_scr(session_id: str, full_page: bool = True)` | Take a screenshot of a unified browser session. Works with any engine (stealth/cdp) transparently. Returns path to the saved PNG file. | `bridge_mcp.py:6967` |
| `bridge_browser_eval` | `bridge_browser_eval(session_id: str, expression: str)` | Execute JavaScript in a unified browser session. Works with any engine (stealth/cdp) transparently. | `bridge_mcp.py:7015` |
| `bridge_browser_upl` | `bridge_browser_upl(session_id: str, selector: str, file_path: str)` | Upload a file to an input element in a unified browser session. Works with any engine (stealth/cdp) transparently. | `bridge_mcp.py:7060` |
| `bridge_browser_cls` | `bridge_browser_cls(session_id: str)` | Close a unified browser session. Cleans up the underlying engine session. | `bridge_mcp.py:7108` |
| `bridge_browser_lst` | `bridge_browser_lst()` | List all active unified browser sessions. Shows session IDs, engines, URLs, and age. | `bridge_mcp.py:7169` |
| `bridge_project_create` | `bridge_project_create(config: dict[str, Any])` | Create a new Bridge project from a full project config payload. This wraps POST /projects/create and returns the created project metadata. | `bridge_mcp.py:7217` |
| `bridge_runtime_configure` | `bridge_runtime_configure(config: dict[str, Any])` | Configure and start the Bridge runtime from a full runtime config payload. This wraps POST /runtime/configure. | `bridge_mcp.py:7237` |
| `bridge_runtime_stop` | `bridge_runtime_stop()` | Stop the current Bridge runtime and clear the active runtime state. | `bridge_mcp.py:7254` |
| `bridge_industry_templates` | `bridge_industry_templates(query: str = '')` | Search industry templates for team creation. Optional query parameter filters by keyword (e.g. 'trading', 'marketing'). Returns matching ... | `bridge_mcp.py:7273` |
| `bridge_mcp_register` | `bridge_mcp_register(name: str, transport: str = 'stdio', command: str = '', args: list[str] | None = None, env: dict[str, str] | None = None, url: str = '', headers: dict[str, str] | None = None, include_in_all: bool = False)` | Register a runtime MCP server in the central catalog. For stdio: provide name, transport='stdio', command, args, env. For remote: provide... | `bridge_mcp.py:7296` |
| `bridge_agent_create` | `bridge_agent_create(id: str, description: str = '', role: str = '', name: str = '', engine: str = 'claude', level: int = 3, reports_to: str = 'buddy', mcp_servers: str | list[str] = 'bridge', skills: list[str] | None = None, permissions: list[str] | None = None, scope: list[str] | None = None, project_path: str = '', config_dir: str = '', model: str = '', active: bool = True)` | Create a new agent entry in team.json. Required: id (lowercase, 3-30 chars), description or role. Optional: engine, model, level, reports... | `bridge_mcp.py:7337` |
| `bridge_agent_start` | `bridge_agent_start(agent_id: str)` | Start or nudge a Bridge agent by ID. This wraps POST /agents/{id}/start. | `bridge_mcp.py:7394` |
| `bridge_lesson_add` | `bridge_lesson_add(title: str, content: str, category: str = 'general', confidence: float = 1.0)` | Add a lesson learned to your persistent memory. Categories: general, technical, collaboration, process. Confidence: 0.0-1.0 (how certain ... | `bridge_mcp.py:7421` |
| `bridge_reflect` | `bridge_reflect(session_summary: str = '', tasks_completed: int = 0)` | Generate a self-reflection prompt for session-end review. Provide a brief session summary as context. Returns questions to guide your ref... | `bridge_mcp.py:7467` |
| `bridge_growth_propose` | `bridge_growth_propose(section: str, old_value: str, new_value: str, reason: str)` | Propose a growth update for your soul. Suggest updates to your strengths or growth areas based on experience. Proposals require human app... | `bridge_mcp.py:7502` |
| `bridge_workflow_compile` | `bridge_workflow_compile(definition: dict[str, Any])` | Compile a canonical Bridge workflow definition into the n8n workflow format without deploying it. | `bridge_mcp.py:7547` |
| `bridge_workflow_deploy` | `bridge_workflow_deploy(definition: dict[str, Any], activate: bool = True)` | Compile and deploy a canonical Bridge workflow definition into n8n. Returns workflow metadata, validation, and any registered Bridge inte... | `bridge_mcp.py:7567` |
| `bridge_workflow_deploy_template` | `bridge_workflow_deploy_template(template_id: str, variables: dict[str, Any] | None = None)` | Deploy a named workflow template with variable substitution via POST /workflows/deploy-template. | `bridge_mcp.py:7593` |
| `bridge_team_list` | `bridge_team_list(include_inactive: bool = False)` | List all teams from the Bridge server. Returns team IDs, names, leads, members, online counts, and last activity. | `bridge_mcp.py:7621` |
| `bridge_team_get` | `bridge_team_get(team_id: str)` | Get details of a specific team by ID. Returns team config, members with live status, and recent activity. | `bridge_mcp.py:7641` |
| `bridge_team_create` | `bridge_team_create(name: str, lead: str, members: list[str] | None = None, scope: str = '')` | Create a new team. Requires name and lead. Optionally provide members list and scope description. | `bridge_mcp.py:7658` |
| `bridge_team_update_members` | `bridge_team_update_members(team_id: str, add: list[str] | None = None, remove: list[str] | None = None)` | Add or remove members from a team. Provide add and/or remove lists of agent IDs. | `bridge_mcp.py:7683` |
| `bridge_team_delete` | `bridge_team_delete(team_id: str)` | Delete a team by ID. Soft-deletes by setting active=false. | `bridge_mcp.py:7706` |
| `bridge_phone_call` | `bridge_phone_call(number: str)` | Start an outgoing phone call via the Voice Gateway. Requires the owner's approval before the call is placed. Returns the approval request_id — ... | `bridge_mcp.py:7777` |
| `bridge_phone_speak` | `bridge_phone_speak(text: str)` | Send text to be spoken (TTS) on the active phone call. The Voice Gateway converts text to speech and plays it to the caller. | `bridge_mcp.py:7829` |
| `bridge_phone_listen` | `bridge_phone_listen(wait: int = 0)` | Get the latest speech-to-text transcript from the active phone call. Returns the most recent caller speech converted to text. Use wait pa... | `bridge_mcp.py:7850` |
| `bridge_phone_hangup` | `bridge_phone_hangup()` | End the active phone call. | `bridge_mcp.py:7870` |
| `bridge_phone_status` | `bridge_phone_status()` | Get the current phone call status. Returns: idle, ringing, in_call, or error with details. | `bridge_mcp.py:7890` |
| `bridge_report_usage` | `bridge_report_usage(input_tokens: int, output_tokens: int, model: str = '', engine: str = 'claude', cached_tokens: int = 0)` | Report token usage for cost tracking. Call after significant API calls or at end of task. Data feeds into GET /metrics/costs dashboard. | `bridge_mcp.py:7915` |
| `bridge_vision_analyze` | `bridge_vision_analyze(screenshot_path: str, prompt: str = 'Analyze this screenshot. Identify all UI elements, text, and suggest possible actions.', model: str = '')` | Analyze a screenshot using Claude Vision API. Takes a file path to a screenshot (PNG/JPG) and returns structured analysis: UI elements, t... | `bridge_mcp.py:7970` |
| `bridge_vision_act` | `bridge_vision_act(session_id: str, goal: str, max_steps: int = 10)` | Autonomous vision-action loop: takes a goal and executes browser actions to achieve it. Requires an active automation browser session. Loop:... | `bridge_mcp.py:8250` |
| `bridge_workflow_execute` | `bridge_workflow_execute(workflow_name: str, input_data: dict[str, Any] | None = None, timeout: int = 60)` | Execute an n8n workflow by name via its webhook trigger. Finds the workflow in n8n, extracts the webhook URL, and POSTs input_data to it.... | `bridge_mcp.py:8391` |
| `bridge_skill_list` | `bridge_skill_list()` | List all available skills and your currently assigned skills. Shows skill name, description, and whether it's assigned to you. | `bridge_mcp.py:8506` |
| `bridge_skill_activate` | `bridge_skill_activate(name: str)` | Activate/assign a skill to yourself. The skill must exist in the skills directory. Adds it to your skills list in team.json. Max 20 skill... | `bridge_mcp.py:8558` |
| `bridge_skill_deactivate` | `bridge_skill_deactivate(name: str)` | Deactivate/remove a skill from yourself. Cannot deactivate 'bridge-agent-core' (always required). | `bridge_mcp.py:8607` |
| `bridge_desktop_observe` | `bridge_desktop_observe(window_name: str = '', include_screenshot: bool = True, include_windows: bool = True, include_clipboard: bool = True, ocr: bool = False)` | Capture a structured desktop snapshot with the focused window, optional window list, optional screenshot, clipboard text, and optional OC... | `bridge_mcp.py:8798` |
| `bridge_desktop_verify` | `bridge_desktop_verify(window_name: str = '', expect_focused_window: str = '', expect_focused_name_contains: str = '', expect_window_name_contains: str = '', expect_clipboard_contains: str = '', expect_ocr_contains: str = '', require_screenshot: bool = False)` | Verify desktop postconditions such as focused-window state, window names, clipboard text, screenshot creation, and OCR text. Returns stru... | `bridge_mcp.py:8892` |
| `bridge_desktop_screenshot` | `bridge_desktop_screenshot(window_name: str = '')` | Take a screenshot of the desktop or a specific window. Returns the file path to the saved PNG screenshot. Optional window_name to target ... | `bridge_mcp.py:9050` |
| `bridge_desktop_screenshot_stream` | `bridge_desktop_screenshot_stream(interval_ms: int = 500, duration_s: float = 10.0, max_frames: int = 30, window_name: str = '')` | Take a series of desktop screenshots at regular intervals. Returns a list of screenshot file paths with timestamps. Useful for vision-AI ... | `bridge_mcp.py:9173` |
| `bridge_desktop_type` | `bridge_desktop_type(text: str, delay_ms: int = 12)` | Type text into the currently focused window using xdotool. The text is typed character by character with a short delay. | `bridge_mcp.py:9275` |
| `bridge_desktop_key` | `bridge_desktop_key(combo: str)` | Send a keyboard shortcut/key combination to the focused window via xdotool. Examples: 'ctrl+s', 'alt+F4', 'Return', 'ctrl+shift+t', 'Esca... | `bridge_mcp.py:9308` |
| `bridge_desktop_click` | `bridge_desktop_click(x: int, y: int, button: int = 1)` | Click at specific screen coordinates (x, y) using xdotool. Optional button parameter: 1=left (default), 2=middle, 3=right. | `bridge_mcp.py:9341` |
| `bridge_desktop_scroll` | `bridge_desktop_scroll(direction: str = 'down', clicks: int = 3, x: int = ..., y: int = ...)` | Scroll at current mouse position or specific coordinates. direction: 'up' or 'down'. clicks: number of scroll steps (1-20). Optional x, y... | `bridge_mcp.py:9422` |
| `bridge_desktop_hover` | `bridge_desktop_hover(x: int, y: int)` | Move mouse to specific screen coordinates (x, y) WITHOUT clicking. Useful for triggering hover menus, tooltips, or highlighting elements. | `bridge_mcp.py:9462` |
| `bridge_desktop_clipboard_read` | `bridge_desktop_clipboard_read()` | Read the current clipboard content. Returns text from system clipboard. | `bridge_mcp.py:9489` |
| `bridge_desktop_clipboard_write` | `bridge_desktop_clipboard_write(text: str)` | Write text to the system clipboard. Makes it available for Ctrl+V paste. | `bridge_mcp.py:9517` |
| `bridge_desktop_wait` | `bridge_desktop_wait(window_name: str, timeout: int = 30)` | Wait until a window with given name appears on screen. Polls xdotool search every 500ms until found or timeout. Returns the window ID whe... | `bridge_mcp.py:9553` |
| `bridge_desktop_double_click` | `bridge_desktop_double_click(x: int, y: int, button: int = 1)` | Double-click at specific screen coordinates (x, y) using xdotool. Useful for opening files, selecting words, or activating UI elements. | `bridge_mcp.py:9595` |
| `bridge_desktop_drag` | `bridge_desktop_drag(start_x: int, start_y: int, end_x: int, end_y: int, button: int = 1)` | Drag from one screen position to another. Simulates mouse-down at (start_x, start_y), move to (end_x, end_y), mouse-up. Useful for moving... | `bridge_mcp.py:9629` |
| `bridge_desktop_window_list` | `bridge_desktop_window_list(name_filter: str = '')` | List all open windows with their IDs, names, and geometry. Returns window_id, name, x, y, width, height for each window. | `bridge_mcp.py:9716` |
| `bridge_desktop_window_focus` | `bridge_desktop_window_focus(window_id: str = '', window_name: str = '')` | Focus/activate a window by its window ID (from bridge_desktop_window_list) or by name search. Brings the window to the foreground. | `bridge_mcp.py:9789` |
| `bridge_desktop_window_resize` | `bridge_desktop_window_resize(width: int = 0, height: int = 0, x: int = ..., y: int = ..., window_id: str = '', window_name: str = '')` | Resize and/or move a window. Specify window_id or window_name. width/height set the new size. x/y set the new position (optional). | `bridge_mcp.py:9833` |
| `bridge_desktop_window_minimize` | `bridge_desktop_window_minimize(window_id: str = '', window_name: str = '')` | Minimize a window by ID or name. | `bridge_mcp.py:9896` |
| `bridge_knowledge_read` | `bridge_knowledge_read(note_path: str)` | Read a note from the knowledge vault. Path is relative to vault root (e.g. 'Agents/atlas/SOUL', 'Shared/architecture'). .md extension add... | `bridge_mcp.py:9972` |
| `bridge_knowledge_write` | `bridge_knowledge_write(note_path: str, body: str, frontmatter: str = '', mode: str = 'overwrite')` | Write or update a note in the knowledge vault. mode: 'overwrite' (default), 'append', 'prepend'. frontmatter is optional JSON object (e.g... | `bridge_mcp.py:9988` |
| `bridge_knowledge_delete` | `bridge_knowledge_delete(note_path: str)` | Delete a note from the knowledge vault. Path is relative to vault root. | `bridge_mcp.py:10010` |
| `bridge_knowledge_list` | `bridge_knowledge_list(directory: str = '', pattern: str = '*.md', recursive: bool = True)` | List notes in the knowledge vault. Optional directory filter (e.g. 'Agents/atlas', 'Tasks'). Returns paths and frontmatter for each note. | `bridge_mcp.py:10025` |
| `bridge_knowledge_search` | `bridge_knowledge_search(query: str = '', directory: str = '', frontmatter_filter: str = '')` | Full-text search across knowledge vault notes. Supports regex patterns. Optional frontmatter_filter as JSON (e.g. '{"status": "open", "ag... | `bridge_mcp.py:10045` |
| `bridge_knowledge_frontmatter` | `bridge_knowledge_frontmatter(note_path: str, action: str = 'get', data: str = '')` | Get, set, or delete frontmatter fields on a knowledge note. action: 'get', 'set', 'delete'. data: JSON object with fields to set/delete (... | `bridge_mcp.py:10070` |
| `bridge_knowledge_init` | `bridge_knowledge_init(agent_id: str = '', user_id: str = '', project_id: str = '', team_id: str = '')` | Initialize the knowledge vault structure and optional scoped homes. Call without IDs to create base dirs (Agents/, Users/, Projects/, Tea... | `bridge_mcp.py:10095` |
| `bridge_knowledge_search_replace` | `bridge_knowledge_search_replace(note_path: str, search: str, replace: str, regex: bool = False)` | Search and replace text in a knowledge note's body. regex: set to true for regex patterns. Returns replacement count. | `bridge_mcp.py:10125` |
| `bridge_knowledge_info` | `bridge_knowledge_info()` | Get knowledge vault metadata: path, note count, total size. | `bridge_mcp.py:10141` |
| `bridge_cron_create` | `bridge_cron_create(name: str, cron_expression: str, action_type: str = 'send_message', recipient: str = '', message: str = '', url: str = '', method: str = 'POST')` | Create a scheduled automation (cron job). Use cron_expression for recurring schedules (e.g. '*/30 * * * *' for every 30min). action_type:... | `bridge_mcp.py:10163` |
| `bridge_cron_list` | `bridge_cron_list()` | List all your scheduled automations (cron jobs). | `bridge_mcp.py:10207` |
| `bridge_cron_delete` | `bridge_cron_delete(automation_id: str)` | Delete a scheduled automation by ID. | `bridge_mcp.py:10224` |
| `bridge_loop` | `bridge_loop(prompt: str, interval: str = '10m', assigned_to: str = '', max_runs: int = 0)` | Create a repeating scheduled prompt (like Claude Code /loop). Interval formats: '5m' (5 min), '2h' (2 hours), '1d' (daily), '30s' (rounds... | `bridge_mcp.py:10293` |
| `bridge_capability_library_list` | `bridge_capability_library_list(query: str = '', entry_type: str = '', vendor: str = '', cli: str = '', task_tag: str = '', source_registry: str = '', status: str = '', trust_tier: str = '', official_vendor: str = '', reproducible: str = '', runtime_verified: str = '', limit: int = 20, offset: int = 0)` | List entries from the Bridge capability library of MCPs, CLI plugins, hooks, extensions, and adapters. Supports filtering by type, vendor... | `bridge_mcp.py:10351` |
| `bridge_capability_library_get` | `bridge_capability_library_get(entry_id: str)` | Get the full metadata for one capability library entry by id. | `bridge_mcp.py:10400` |
| `bridge_capability_library_search` | `bridge_capability_library_search(query: str, entry_type: str = '', vendor: str = '', cli: str = '', task_tag: str = '', source_registry: str = '', status: str = '', trust_tier: str = '', official_vendor: str = '', reproducible: str = '', runtime_verified: str = '', limit: int = 10, offset: int = 0)` | Search the Bridge capability library against task text or keywords. Returns ranked matches with filter support. | `bridge_mcp.py:10418` |
| `bridge_capability_library_recommend` | `bridge_capability_library_recommend(task: str, engine: str = '', cli: str = '', top_k: int = 10, official_vendor_only: bool = False)` | Recommend capability library entries for a task. Useful when an agent wants candidate MCPs, extensions, or hooks to pull from the library. | `bridge_mcp.py:10470` |
| `bridge_memory_search` | `bridge_memory_search(query: str, top_k: int = 5, min_score: float = 0.3, scope_type: str = '', scope_id: str = '')` | Search your semantic memory using hybrid Vector+BM25 retrieval. Finds relevant memories even when exact keywords don't match (e.g. search... | `bridge_mcp.py:10509` |
| `bridge_memory_index` | `bridge_memory_index(text: str, source: str = '', chunk_size: int = 500, scope_type: str = '', scope_id: str = '', document_id: str = '')` | Index text into your semantic memory for later retrieval. Use this to store important learnings, decisions, patterns, or facts that you w... | `bridge_mcp.py:10546` |
| `bridge_memory_delete` | `bridge_memory_delete(document_id: str, scope_type: str = '', scope_id: str = '')` | Delete a document from semantic memory. Use with explicit scope_type/scope_id for user/project/team/global scopes, or omit them to delete... | `bridge_mcp.py:10590` |
| `bridge_research` | `bridge_research(url: str, freshness_days: int = 90)` | Fetch a URL and return content with freshness metadata. Automatically extracts publication date and warns if content is stale. | `bridge_mcp.py:10638` |
| `bridge_creator_local_ingest` | `bridge_creator_local_ingest(input_path: str, workspace_dir: str, language: str = 'de', model: str = '', transcribe: bool = True)` | Probe and optionally transcribe a local media file for content creators. Returns media metadata, extracted audio, transcript, chapters, a... | `bridge_mcp.py:10704` |
| `bridge_creator_url_ingest` | `bridge_creator_url_ingest(source_url: str, workspace_dir: str, language: str = 'de', model: str = '', transcribe: bool = True)` | Download and ingest a creator source from a URL or YouTube link into the creator media model. Returns source metadata, local download pat... | `bridge_mcp.py:10737` |
| `bridge_creator_write_srt` | `bridge_creator_write_srt(segments: list[dict[str, Any]], output_path: str)` | Write an SRT subtitle file from transcript segments. | `bridge_mcp.py:10766` |
| `bridge_creator_highlights` | `bridge_creator_highlights(segments: list[dict[str, Any]], max_candidates: int = 3, min_duration_s: float = 2.0)` | Score transcript segments and return highlight candidates for shorts or clips. | `bridge_mcp.py:10782` |
| `bridge_creator_export_clip` | `bridge_creator_export_clip(input_path: str, output_path: str, start_s: float, end_s: float)` | Trim a local media file to a clip between start_s and end_s. | `bridge_mcp.py:10807` |
| `bridge_creator_social_presets` | `bridge_creator_social_presets()` | List platform-native creator export presets such as vertical, square, and landscape. | `bridge_mcp.py:10834` |
| `bridge_creator_export_social_clip` | `bridge_creator_export_social_clip(input_path: str, output_path: str, start_s: float, end_s: float, preset_name: str = 'youtube_short', segments: list[dict[str, Any]] | None = None, burn_subtitles: bool = False)` | Export a creator clip in a platform preset such as youtube_short or square_post, optionally with burned subtitles. | `bridge_mcp.py:10853` |
| `bridge_creator_package_social` | `bridge_creator_package_social(input_path: str, output_dir: str, package_name: str, start_s: float, end_s: float, preset_names: list[str] | None = None, segments: list[dict[str, Any]] | None = None, burn_subtitles: bool = True, write_sidecar_srt: bool = True, default_metadata: dict[str, Any] | None = None, metadata_by_preset: dict[str, Any] | None = None)` | Generate a creator package with multiple platform-ready assets, an optional sidecar SRT, and a manifest JSON from one source clip. | `bridge_mcp.py:10889` |
| `bridge_voice_transcribe` | `bridge_voice_transcribe(audio_path: str, language: str = 'de')` | Transcribe an audio file to text using local Whisper STT. Supports .ogg, .m4a, .mp3, .wav. Returns transcript text. | `bridge_mcp.py:10937` |
| `bridge_voice_quota` | `bridge_voice_quota()` | Check ElevenLabs TTS quota (characters used/remaining). | `bridge_mcp.py:10955` |
| `bridge_whatsapp_voice` | `bridge_whatsapp_voice(to: str, text: str, voice_id: str = '')` | Send a voice message to WhatsApp: converts text to speech (ElevenLabs TTS) and sends the audio via WhatsApp. Goes through approval gate l... | `bridge_mcp.py:10975` |

### 4.2 Beispielaufrufe (repräsentativ)

```json
{"tool": "bridge_register", "args": {"agent_id": "codex", "role": "Senior Coder"}}
{"tool": "bridge_task_queue", "args": {"state": "created", "limit": 50}}
{"tool": "bridge_task_done", "args": {"task_id": "...", "result_summary": "...", "result_code": "success", "evidence_type": "log", "evidence_ref": "..."}}
```

## 5) Watcher / Routing (`bridge_watcher.py`)

- Routing-Basis: `ALLOWED_ROUTES` + dynamische Ableitung aus `team.json`/`runtime_team.json`.
- Persistente Betriebsdateien: `logs/watcher.log`, `pids/watcher.pid`.
- Wichtige Loops: Team-JSON-Reload-Daemon, Runtime-Route-Refresh, resilient WebSocket consume loop.
- Notification-Pattern: Watcher injiziert Kurzauftrag in Agent-Session; Inhaltsdaten kommen ueber `bridge_receive()`.

Ankerstellen:

- `bridge_watcher.py:57` `ALLOWED_ROUTES = {`
- `bridge_watcher.py:128` `def _load_team_routes_and_aliases() -> None:`
- `bridge_watcher.py:236` `ALLOWED_ROUTES = routes`
- `bridge_watcher.py:302` `def _refresh_runtime_registered_routes() -> bool:`
- `bridge_watcher.py:313` `ALLOWED_ROUTES = merged`
- `bridge_watcher.py:317` `_load_team_routes_and_aliases()`
- `bridge_watcher.py:319` `_refresh_runtime_registered_routes()`
- `bridge_watcher.py:336` `async def _team_json_reload_daemon(interval: int = 30) -> None:`
- `bridge_watcher.py:347` `_load_team_routes_and_aliases()`
- `bridge_watcher.py:348` `_refresh_runtime_registered_routes()`
- `bridge_watcher.py:356` `elif _refresh_runtime_registered_routes():`
- `bridge_watcher.py:876` `def format_notification(sender: str, content: str, engine: str = "claude") -> str:`
- `bridge_watcher.py:898` `async def inject_with_retry(agent_id: str, sender: str, content: str, msg_id: str, *, urgent: bool = False) -> bool:`
- `bridge_watcher.py:993` `urgent_notification = format_notification(`
- `bridge_watcher.py:1011` `notification = format_notification(sender, content, engine=engine)`
- `bridge_watcher.py:1065` `notification = format_notification(sender, content)`
- `bridge_watcher.py:2445` `asyncio.create_task(_resilient_task("team_json_reload", _team_json_reload_daemon, 30))`
- `bridge_watcher.py:2616` `injected = await inject_with_retry(target, sender, content, msg_id, urgent=is_urgent)`

## 6) Tmux Session Management (`tmux_manager.py`)

- Kernaufgaben: Session-Erzeugung, Engine-spezifischer Startup, Prompt-Injektion, Interrupt/Kill, Session-Liveness.
- Bridge-relevante Pfade: Runtime-MCP-Config, Agent-Homes, policy-gebundene CLI-Adapter.

API-nahe Funktionen:

- `tmux_manager.py:1126` `def create_agent_session(`
- `tmux_manager.py:1395` `def interrupt_agent(agent_id: str, engine: str = "claude") -> str:`
- `tmux_manager.py:1429` `def interrupt_all_agents(engine_map: dict[str, str] | None = None) -> list[dict[str, str]]:`
- `tmux_manager.py:1462` `def kill_agent_session(agent_id: str) -> bool:`
- `tmux_manager.py:1473` `def list_agent_sessions() -> list:`
- `tmux_manager.py:1517` `def is_session_alive(agent_id: str) -> bool:`
- `tmux_manager.py:1534` `def send_to_session(agent_id: str, text: str) -> bool:`

## 7) Infrastruktur-Threads (Daemon)

| Name | Target | Source |
|---|---|---|
| `supervisor-daemon` | `_supervisor_daemon_loop` | `server.py:7155` |
| `auto-gen-watcher` | `_auto_gen_watcher` | `daemons/auto_gen.py` |
| `agent-health-checker` | `_agent_health_checker` | `daemons/agent_health.py` |
| `health-monitor` | `_health_monitor_loop` | `daemons/health_monitor.py` |
| `cli-output-monitor` | `_cli_output_monitor_loop` | `daemons/cli_monitor.py` |
| `rate-limit-resume` | `_rate_limit_resume_loop` | `daemons/rate_limit_resume.py` |
| `v3-cleanup` | `_v3_cleanup_loop` | `daemons/maintenance.py` |
| `task-timeout-checker` | `_task_timeout_loop` | `daemons/maintenance.py` |
| `heartbeat-prompter` | `_heartbeat_prompt_loop` | `daemons/heartbeat_prompt.py` |
| `distillation-daemon` | `_distillation_daemon_loop` | `daemons/distillation.py` |
| `task-pusher` | `_idle_agent_task_pusher` | `daemons/task_pusher.py` |
| `auto-assign` | `_idle_watchdog_auto_assign` | `daemons/auto_assign.py` |
| `buddy-knowledge` | `_buddy_knowledge_loop` | `daemons/buddy_knowledge.py` |
| `server-bootstrap` | `_create_http_server_with_retry` / `_server_signal_handler` | `server_bootstrap.py` |
| `server-startup` | `start_background_services` / `_start_automation_scheduler` | `server_startup.py` |
| `websocket-server` | `run_websocket_server` | `websocket_server.py` |
| `restart-wake` | `_delayed_restart_wake` | `daemons/restart_wake.py` |
| `restart-control` | `_restart_warn_phase` / `_restart_kill_phase` | `daemons/restart_control.py` |
| `server-sigterm-shutdown` | `_shutdown_server` | `server_bootstrap.py` |

- Erwarteter Kernsatz: `server-bootstrap`, `server-startup`, `websocket-server`, `agent-health-checker`, `health-monitor`, `task-timeout-checker`, `heartbeat-prompter`, `distillation-daemon`, `task-pusher`, `auto-assign`, `buddy-knowledge`, `restart-wake`, `restart-control`, u.a.

## 8) Task-System

- Lifecycle: `created -> claimed -> acked -> done|failed` (`server.py` ~L1653ff).
- Timeout-Logik: Ack-Deadline, Unclaimed-TTL, Lease-Expiry, Offline-Orphan-Recovery.
- Queue-/Transition-Endpunkte: `/task/create`, `/task/queue`, `/task/{id}/claim|ack|done|fail|checkin`, `/task/{id}` (PATCH/DELETE).
- Evidenzmodell bei `done`: `result_summary`, `result_code`, `evidence_type`, `evidence_ref`.

## 9) Knowledge Vault

- Engine: `knowledge_engine.py` + Bridge-Wrapper in `server.py`/`bridge_mcp.py`.
- Hauptoperationen: init, read/write/list/search, frontmatter CRUD, search_replace, info.
- Struktur (typisch): `Knowledge/Agents/*`, `Knowledge/Projects/*`, `Knowledge/Teams/*`, `Knowledge/Shared/*`.

## 10) Automation Engine (`automation_engine.py`)

- Trigger-Typen: `event`, `webhook`, `condition`.
- Action-Typen: `create_task`, `send_message`, `set_mode`, `webhook`, `chain`, `prompt_replay`.
- Scheduler: eigener `AutomationScheduler` Thread (cron, jitter, pause, catch-up).
- HTTP-Integrationen: lokale API-Calls (`/tasks`, `/send`, `/agents/{id}/mode`) und Webhook-Dispatch.

Trigger-/Action-Anker:

- Trigger `event` in `automation_engine.py:149`
- Trigger `webhook` in `automation_engine.py:151`
- Trigger `condition` in `automation_engine.py:155`
- Action `create_task` in `automation_engine.py:917`
- Action `send_message` in `automation_engine.py:919`
- Action `set_mode` in `automation_engine.py:921`
- Action `webhook` in `automation_engine.py:923`
- Action `chain` in `automation_engine.py:925`
- Action `prompt_replay` in `automation_engine.py:927`

## 11) Vergleich mit GitHub-Release-Doku

- Gefundene Markdown-Dateien im Release-Clone (`~/Desktop/bridge-ide-release/BRIDGE`): 1
  - `CLAUDE.md`
- Ergebnis: Backend-/Infrastruktur-Referenzdoku fehlt im Release praktisch vollstaendig.
- Neu in dieser Arbeitskopie: diese technische Referenzdatei als API-/Ops-Basis.

## 12) Offene Punkte / Pflegehinweise

- Die Endpoint-Tabelle ist codebasiert erzeugt; bei neuen Routen Datei neu generieren.
- Einige Endpunkte sind pattern-basiert (`re.match`), inklusive dynamischer IDs.
- `bridge_mcp.py` hat 170+ Tools; fuer externe Integrationen empfiehlt sich zusaetzliche Sub-Doku je Domain (Browser, Desktop, Knowledge, Voice, Workflow).
