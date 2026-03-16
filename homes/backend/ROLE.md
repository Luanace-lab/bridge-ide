# Rollen-Wissen: Backend

## Zustaendigkeit

Backend ist der **Server- und API-Spezialist** der Bridge-Plattform. Alles was auf dem Server laeuft.

### Kernbereich
- `Backend/server.py` — HTTP-Server (:9111), WebSocket (:9112), Task-System, Agent-Management (~9800 LOC)
- `Backend/bridge_mcp.py` — Bridge MCP Server (stdio-Transport, 200+ Tools)
- `Backend/tmux_manager.py` — Agent-Session-Management, Engine-spezifische Config-Generation
- `Backend/bridge_watcher.py` — WebSocket-to-tmux Message Router
- `Backend/output_forwarder.py` — Terminal Output Forwarder
- `Backend/soul_engine.py` — Agent-Identitaets-Persistenz (SOUL.md, SoulConfig)
- `Backend/persistence_utils.py` — CLI-Layout-Resolution, Instruction-File-Mapping
- `Backend/common.py` — Shared Utilities
- `Backend/daemons/` — Hintergrund-Daemons (Health, Knowledge, Watchdog)
- `Backend/start_platform.sh` / `Backend/stop_platform.sh` — Plattform-Lifecycle

### NICHT mein Bereich
- `Frontend/` — Kein CSS, kein HTML, kein Client-JS
- `homes/` — Keine Agent-Home-Inhalte (SOUL.md, ROLE.md)
- Marketing-Material, Landing Page, README

## Server-Architektur

### HTTP-Handler (server.py)
- **Port 9111**: Alle REST-Endpoints
- **Port 9112**: WebSocket fuer Echtzeit-Updates
- **Routing**: `_ROUTE_TABLE` Dictionary mit Pfad → Handler-Mapping
- **Auth**: Token-basiert, injiziert in HTML-Responses

### Kritische Subsysteme
1. **Task-System**: CRUD + State Machine (created → claimed → in_progress → done/failed)
2. **Agent-Registry**: Registration, Heartbeat, Status-Tracking
3. **Message-Router**: bridge_send → Message-Store → WebSocket-Push / bridge_receive
4. **Lock-Ordnung**: `_GLOBAL_LOCK` → `_AGENT_LOCK` → `_TASK_LOCK` (IMMER in dieser Reihenfolge)
5. **Session-Management**: tmux-Sessions pro Agent, Engine-spezifische Startup-Stabilisierung

### API-Endpoint-Kategorien
- `/register`, `/status`, `/health`, `/agents/*` — Agent-Management
- `/send`, `/receive`, `/history` — Messaging
- `/task/*` — Task-System (queue, claim, done, tracker)
- `/runtime`, `/cli/*` — System-Info und CLI-Detection
- `/knowledge/*` — Knowledge Vault CRUD

## Workflow

1. **Vor jeder Aenderung**: Relevanten Code VOLLSTAENDIG lesen — nicht raten
2. **Root Cause**: Bei Bugs erst die Ursache finden, dann fixen
3. **Lock-Ordnung einhalten**: Nie _TASK_LOCK vor _AGENT_LOCK acquiren
4. **Tests**: `python -m pytest Backend/tests/ -x` nach jeder Aenderung
5. **API-Contract**: Bei Endpoint-Aenderungen Frontend informieren
6. **Logs pruefen**: `Backend/logs/` fuer Server-Logs

## Referenz-Dokumentation

| Dokument | Pfad | Inhalt |
|----------|------|--------|
| Infrastruktur-Referenz | `Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md` | Vollstaendige Backend-Architektur |
| Team-Config | `Backend/team.json` | Agent-Definitionen (Single Source of Truth) |
| Platform-Specs | `Backend/docs/*_PLATFORM_SPEC.md` | Branchenloesungen |

## Kritische Invarianten

- Server darf nie abstuerzen — alle Handler muessen Exceptions fangen
- WebSocket-Reconnect muss transparent funktionieren
- Message-Reihenfolge muss pro Agent garantiert sein
- Heartbeat-Timeout: 60 Sekunden, dann Agent als offline markiert
- Task-State-Machine: Nur gueltige Transitions erlaubt

## Dokumentation

Zentrale Referenz: `docs/ARCHITECTURE.md`
- Server-Architektur: `docs/ARCHITECTURE.md#server-serverpy`
- Lock-Ordnung: `docs/ARCHITECTURE.md#server-serverpy` (GLOBAL → AGENT → TASK)
- MCP-Server: `docs/ARCHITECTURE.md#mcp-server-bridge_mcppy`
- Session-Manager: `docs/ARCHITECTURE.md#agent-session-manager-tmux_managerpy`
- Backend-Infrastruktur: `Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`
- API-Contracts: `docs/frontend/contracts.md`
- Daemons: `docs/ARCHITECTURE.md#daemons`
