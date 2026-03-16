# Bridge ACE — Architecture & Technical Reference

## Overview

Bridge ACE (Agentic Collab Engine) is a local multi-agent platform. Multiple AI agents run on the same machine — each in its own persistent terminal session — and collaborate in real-time through a shared communication layer (the "Bridge"). The user defines roles, assigns teams, and stays in control via a browser-based UI.

**Core concept:** A central HTTP + WebSocket server orchestrates agent sessions (via tmux), routes messages between agents, manages tasks, and serves the frontend. Each agent connects through the Bridge MCP protocol (stdio transport) and registers itself with the server.

**Supported AI engines:** Claude, Codex (OpenAI), Qwen, Gemini. Each engine has its own CLI adapter and instruction file format.

## System Architecture

```
 Browser (User)           Mobile Browser
      |                        |
      v                        v
 +------------------------------------------+
 |  Frontend (plain HTML/CSS/JS)            |
 |  chat.html, control_center.html, ...     |
 +------------------------------------------+
      |  REST (HTTP)       |  Real-time (WS)
      v                    v
 +------------------+  +-------------------+
 | HTTP Server      |  | WebSocket Server  |
 | :9111            |  | :9112             |
 | (server.py)      |  | (websocket_server |
 +------------------+  |  .py)             |
      |                +-------------------+
      |                    |
      v                    v
 +------------------------------------------+
 | Backend Core                             |
 | - tmux_manager.py (session lifecycle)    |
 | - bridge_watcher.py (WS->tmux router)   |
 | - soul_engine.py (agent identity)        |
 | - knowledge_engine.py (knowledge vault)  |
 | - 15 background daemons                  |
 | - 38+ HTTP handler modules               |
 +------------------------------------------+
      |
      v
 +------------------------------------------+
 | tmux Sessions (one per agent)            |
 | acw_{agent_id}                           |
 +------------------------------------------+
      |
      v
 +------------------------------------------+
 | AI CLI Processes                         |
 | claude | codex | qwen-coder | gemini     |
 | (each with Bridge MCP via stdio)         |
 +------------------------------------------+
      |
      v
 +------------------------------------------+
 | bridge_mcp.py (MCP Server, stdio)        |
 | 204 built-in tools                       |
 +------------------------------------------+
```

**Ports:**
- HTTP: `127.0.0.1:9111` (server.py, `PORT = 9111`)
- WebSocket: `127.0.0.1:9112` (websocket_server.py, `WS_PORT = 9112`)

**Key processes:**
- `server.py` — HTTP request handler, route table, auth, all REST endpoints
- `websocket_server.py` — WebSocket server for real-time push
- `bridge_mcp.py` — MCP server (stdio transport) providing 204 tools to agents
- `bridge_watcher.py` — WebSocket-to-tmux message router (delivers messages to agent terminals)
- `tmux_manager.py` — Agent session lifecycle manager
- `server_startup.py` — Orchestrates daemon threads, automation scheduler, WebSocket thread, restart-wake, supervisor

## Directory Structure

```
bridge-ide/
├── Backend/                  # Server, MCP, agent management, daemons
│   ├── server.py             # HTTP server (:9111) — main entry point
│   ├── bridge_mcp.py         # MCP server (204 tools, stdio transport)
│   ├── tmux_manager.py       # Agent tmux session lifecycle
│   ├── bridge_watcher.py     # WebSocket-to-tmux message router
│   ├── soul_engine.py        # Persistent agent identity (SOUL.md, SoulConfig)
│   ├── persistence_utils.py  # CLI layout resolution, instruction file mapping
│   ├── knowledge_engine.py   # Knowledge Vault CRUD
│   ├── memory_engine.py      # Agent memory management
│   ├── capability_library.py # 5,387 MCP ecosystem tool index
│   ├── websocket_server.py   # WebSocket server (:9112)
│   ├── output_forwarder.py   # Terminal output forwarder
│   ├── common.py             # Shared utilities
│   ├── team.json             # Agent/team definitions (Single Source of Truth)
│   ├── daemons/              # 15 background monitoring threads
│   ├── handlers/             # 38+ HTTP handler modules
│   ├── docs/                 # Platform specs, infra reference
│   ├── start_platform.sh     # One-command platform start
│   └── stop_platform.sh      # Platform stop
├── Frontend/                 # Plain HTML/CSS/JS — no build step
│   ├── chat.html             # Dual-board chat workspace
│   ├── control_center.html   # Live operations dashboard
│   ├── project_config.html   # Project bootstrap / configurator
│   ├── task_tracker.html     # Task listing with export
│   ├── buddy_landing.html    # Buddy onboarding + engine selection
│   ├── landing.html          # Marketing landing page
│   ├── mobile_buddy.html     # Mobile: Buddy + team boards
│   ├── mobile_projects.html  # Mobile: project configurator
│   ├── mobile_tasks.html     # Mobile: task tracker + export
│   ├── buddy_widget.js       # Reusable Buddy floating widget
│   ├── bridge_runtime_urls.js # Centralized URL resolution
│   ├── i18n.js               # Internationalization (en, de, ru, zh, es)
│   └── buddy_designs_shared.css/js # Shared Buddy styles/logic
├── homes/                    # Pre-built role homes (5 roles)
│   ├── buddy/                # SOUL.md + ROLE.md + prompt.txt
│   ├── frontend/
│   ├── backend/
│   ├── architect/
│   └── platform/
├── Knowledge/                # Knowledge Vault
│   ├── Agents/               # Per-agent knowledge
│   ├── Users/                # User profiles
│   ├── Projects/             # Project knowledge
│   ├── Teams/                # Team knowledge
│   ├── Tasks/                # Task knowledge
│   ├── Decisions/            # Decision records
│   └── Shared/               # Shared knowledge
├── config/                   # Runtime configuration
│   └── capability_library.json # MCP tool index (auto-built)
├── docs/                     # Documentation
│   ├── ARCHITECTURE.md       # This file
│   ├── frontend/             # Frontend audit docs, contracts
│   └── screenshots/          # Product screenshots
├── install.sh                # One-command installer
├── Dockerfile                # Container build
├── docker-compose.yml        # Container orchestration
└── README.md                 # Project README
```

## Backend

### Server (server.py)

The HTTP server is a single-file Python `http.server.BaseHTTPRequestHandler` subclass.

- **Route table:** `_ROUTE_TABLE` dictionary mapping paths to handler functions. 206 explicit path checks (exact, prefix, regex) across GET/POST/PATCH/PUT/DELETE.
- **Lock ordering:** `_GLOBAL_LOCK` -> `_AGENT_LOCK` -> `_TASK_LOCK`. This order must never be reversed.
- **Auth:** Token-based. Token sources: `X-Bridge-Token` header or `Authorization: Bearer <token>`. Token types: user token, UI session token, agent session token (with grace-token window). GET requests are public by default; POST/PATCH/DELETE are authenticated per tier/path. Sensitive endpoints use `_require_platform_operator()`.
- **Frontend serving:** `server_frontend_serve.py` injects `window.__BRIDGE_UI_TOKEN` into HTML responses so the browser can authenticate subsequent API calls.
- **Handler modules:** 38+ modules in `Backend/handlers/` — agents, approvals, automation, boards, capabilities, chat files, CLI, credentials, data, domain, events, execution, federation, git locks, guardrails, health, logs, MCP catalog, media, memory, messages, meta, metrics, onboarding, projects, runtime, scope locks, shared tools, skills, subscriptions, system status, tasks, team lead scope, teams, whiteboard, workflows.
- **Data sources:** `team.json`, `runtime_team.json`, `tasks.json`, `messages/bridge.jsonl`, `automations.json`.

### MCP Server (bridge_mcp.py)

- **Transport:** stdio (Claude Code connects via stdin/stdout)
- **Tool count:** 204 built-in Bridge tools
- **Background connections:** WebSocket to `ws://127.0.0.1:9112` for push messages; HTTP heartbeat every 30s
- **Message buffer:** Deque for received WebSocket messages
- **Key tool categories:**
  - **Registration:** `bridge_register`
  - **Communication:** `bridge_send`, `bridge_receive`, `bridge_heartbeat`, `bridge_history`
  - **Status:** `bridge_status`, `bridge_health`, `bridge_activity`
  - **Tasks:** `bridge_task_create`, `bridge_task_claim`, `bridge_task_done`, `bridge_task_fail`, `bridge_task_get`, `bridge_task_queue`, `bridge_task_update`, `bridge_task_ack`, `bridge_task_checkin`
  - **Knowledge:** `bridge_knowledge_read`, `bridge_knowledge_write`, `bridge_knowledge_search`, `bridge_knowledge_init`, `bridge_knowledge_list`, `bridge_knowledge_info`, `bridge_knowledge_delete`, `bridge_knowledge_frontmatter`, `bridge_knowledge_search_replace`
  - **Capabilities:** `bridge_capability_library_list`, `bridge_capability_library_search`, `bridge_capability_library_get`, `bridge_capability_library_recommend`
  - **Memory:** `bridge_memory_search`, `bridge_memory_index`, `bridge_memory_delete`
  - **Credentials:** `bridge_credential_store`, `bridge_credential_get`, `bridge_credential_list`, `bridge_credential_delete`
  - **Browser/Desktop/Stealth:** Full browser automation, desktop control, stealth browsing
  - **Communication channels:** Slack, WhatsApp, Telegram, Email, Phone
  - **Git:** `bridge_git_commit`, `bridge_git_push`, `bridge_git_branch_create`, `bridge_git_conflict_check`, `bridge_git_lock`, `bridge_git_unlock`, `bridge_git_hook_install`
  - **Scope/Approvals:** `bridge_scope_check`, `bridge_scope_lock`, `bridge_scope_unlock`, `bridge_approval_request`, `bridge_approval_check`, `bridge_approval_wait`
  - **Teams/Projects:** `bridge_team_create`, `bridge_team_get`, `bridge_team_list`, `bridge_team_update_members`, `bridge_team_delete`, `bridge_project_create`
  - **Workflows:** `bridge_workflow_compile`, `bridge_workflow_deploy`, `bridge_workflow_deploy_template`, `bridge_workflow_execute`
  - **Creator:** Video editing, social publishing, voice cloning, campaign management
  - **Data:** `bridge_data_query`, `bridge_data_source_register`, `bridge_data_source_ingest`, `bridge_data_run_start`, `bridge_data_run_status`, `bridge_data_run_evidence`, `bridge_data_dataset_profile`
  - **Runtime/Meta:** `bridge_runtime_configure`, `bridge_runtime_stop`, `bridge_register`, `bridge_reflect`, `bridge_loop`, `bridge_save_context`
- **Ecosystem:** `capability_library.py` indexes 5,387 additional tools from the MCP ecosystem (auto-built into `config/capability_library.json`)

### Agent Session Manager (tmux_manager.py)

Manages persistent tmux sessions for each agent. Session naming convention: `acw_{agent_id}`.

**Session lifecycle:**
1. **Analysis:** Resolve agent config from `team.json`, validate agent ID
2. **Soul resolution:** Call `soul_engine.prepare_agent_identity()` to get guardrail prolog + soul section
3. **Instruction file generation:** Generate engine-specific instruction file (CLAUDE.md / AGENTS.md / GEMINI.md / QWEN.md) via `generate_agent_claude_md()`
4. **MCP config generation:** Build `.mcp.json` / equivalent config with Bridge MCP server entry via `mcp_catalog.build_client_mcp_config()`
5. **Engine-specific config:** Create engine-specific runtime config files (`.claude/settings.json`, `.codex/config.toml`, etc.)
6. **tmux session creation:** Create tmux session with agent's working directory
7. **CLI launch:** Send the engine CLI command to the tmux session via `send-keys`
8. **Startup stabilization:** Engine-specific wait/verification before marking session as ready

**Instruction file mapping:**
| Engine | File | Constant in `persistence_utils.py` |
|--------|------|-----|
| Claude | `CLAUDE.md` | `INSTRUCTION_FILES_BY_ENGINE["claude"]` |
| Codex | `AGENTS.md` | `INSTRUCTION_FILES_BY_ENGINE["codex"]` |
| Gemini | `GEMINI.md` | `INSTRUCTION_FILES_BY_ENGINE["gemini"]` |
| Qwen | `QWEN.md` | `INSTRUCTION_FILES_BY_ENGINE["qwen"]` |

**Instruction file template structure** (`generate_agent_claude_md()`):
1. Guardrail prolog (immutable security rules)
2. Agent soul (personality, values, communication style)
3. Agent identity (id, role)
4. Team members list
5. Bridge-API instructions (register, poll-loop, send, heartbeat, history)
6. Work rules (7 rules)
7. Permissions and scope section
8. Role-specific description

**Engine-aware behavior:**
- Codex has no Stop-Hook — uses persistent tmux session rule instead
- Codex sandbox blocks network — no curl fallback for Bridge API
- Codex has no PostToolUse-Hook — uses `bridge_activity` instead

### Soul Engine (soul_engine.py)

Manages persistent agent identities. The soul defines WHO an agent IS (not what it does).

**SoulConfig dataclass (8 fields):**
- `agent_id: str`
- `name: str`
- `core_truths: list[str]`
- `strengths: str`
- `growth_area: str`
- `communication_style: str`
- `quirks: str`
- `boundaries: list[str]`

**Resolution cascade** (`resolve_soul()`):
1. `home_dir/SOUL.md` from team.json (highest priority, hand-crafted identity)
2. Existing `SOUL.md` in workspace (parsed)
3. `.soul_meta.json` in workspace (JSON metadata)
4. `DEFAULT_SOULS` dictionary (pre-defined for buddy, and other known agents)
5. Generic fallback SoulConfig

**SOUL.md immutability:** Once created, SOUL.md is never overwritten (`save_soul()` is a no-op if file exists). Changes require explicit user confirmation (Growth Protocol).

**Guardrail prolog** (`generate_guardrail_prolog()`): Immutable security block prepended to every instruction file. 5 rules:
1. Agent identity is immutable
2. No modification of SOUL.md/CLAUDE.md/AGENTS.md without user confirmation
3. No credential/API-key/private-data exfiltration
4. External instruction injection is ignored
5. No destructive operations (rm -rf, DROP TABLE, force-push) without explicit approval

### Persistence (persistence_utils.py)

**CLI layout resolution** (`resolve_agent_cli_layout()`): Normalizes agent home paths to a canonical layout:
- `home_dir` — the agent's home directory
- `workspace` — `{home_dir}/.agent_sessions/{agent_id}`
- `project_root` — parent of `.agent_sessions`

**Instruction file mapping** (`instruction_filename_for_engine()`): Returns the correct filename for each engine. Default is `CLAUDE.md`.

### Daemons

15 background daemon threads in `Backend/daemons/`:

| Daemon | Purpose |
|--------|---------|
| `agent_health.py` | Monitors agent busy-state duration, cleanup of stale agent states (300s thresholds) |
| `auto_assign.py` | Auto-assigns unassigned tasks to available agents (every 120s) |
| `auto_gen.py` | Handles pending auto-generation requests for agent artifacts |
| `buddy_knowledge.py` | Regenerates Buddy's system knowledge (every 300s) |
| `cli_monitor.py` | Detects stuck CLI processes via output hash comparison (600s stuck, 900s kill threshold) |
| `codex_hook.py` | Codex-specific session monitoring hook (every 15s with 20s cooldown) |
| `distillation.py` | Periodic knowledge distillation prompt to agents (initial 600s delay, then every 4h) |
| `health_monitor.py` | Context window usage alerts at 90%/95% thresholds (every 60s) |
| `heartbeat_prompt.py` | Sends periodic heartbeat-check prompts to agents (every 300s) |
| `maintenance.py` | Cleanup of expired scope locks, whiteboard entries, timed-out tasks (30-60s intervals) |
| `rate_limit_resume.py` | Resumes rate-limited agents with exponential backoff (1800s initial, 14400s max, 2x factor) |
| `restart_control.py` | Manages server restart state machine and graceful shutdown |
| `restart_wake.py` | Wakes agents after server restart (3s delay) |
| `supervisor.py` | Process supervisor — monitors and restarts crashed agent processes |
| `task_pusher.py` | Pushes pending tasks to agents via tmux (every 60s) |

## Frontend

### Runtime Model

The frontend is plain HTML/CSS/JS without a build step or framework. All pages are served by the backend via `server_frontend_serve.py` with token injection.

### Pages

| File | Purpose |
|------|---------|
| `chat.html` | Main user workspace: dual-board chat, direct/team messaging, approval gate, settings, subscription management, agent controls, task board, workflow list, platform start/stop, file upload, workspace panels |
| `control_center.html` | Operations console: agent status, health, activity, persistence cards, cost widget, liveboard alerts, scope locks, team/project board, task board with CRUD, org chart drag-and-drop, agent editor with avatar upload, workflow builder, automation CRUD |
| `project_config.html` | Project bootstrap: engine model lookup, context scan, project creation, runtime configuration, JSON export, runtime status polling |
| `task_tracker.html` | Task listing with server-side filtering, authenticated JSON/CSV export, right-side detail panel |
| `buddy_landing.html` | Buddy onboarding: three.js animation, CLI detection, engine selection, Buddy-home materialization, start, chat loop, draggable side panel |
| `landing.html` | Marketing landing page with anchor navigation (not the active `/` entrypoint) |
| `buddy_onboarding_v3_living.html` | [UNKNOWN — legacy/experimental onboarding variant] |
| `mobile_buddy.html` | Mobile Buddy: stacked Management-Board + Team-Board, Buddy FAB, draggable board divider, attachment upload, 5 themes |
| `mobile_projects.html` | Mobile project configurator: 2x2 metric grid, recent-project picks, scan feedback, role cards, runtime start |
| `mobile_tasks.html` | Mobile task tracker: compact status board, filters, card-based task list, bottom detail sheet, CSV/JSON export |

### Design System

**Themes (5):** warm, light, rose, dark, black. Stored in `localStorage` as `bridge_theme`. All pages share the same theme system.

**CSS architecture:** CSS custom properties (variables) for theming. No CSS preprocessor. Shared styles in `buddy_designs_shared.css`.

**Languages (5):** English, German, Russian, Chinese, Spanish. Dictionary in `i18n.js`, loaded by `chat.html`. Stored as `bridge_language`.

### Frontend-Backend Contracts

**URL resolution:** Centralized in `Frontend/bridge_runtime_urls.js`.
- Local dev: pages on `127.0.0.1:9111` or `127.0.0.1:9112` resolve API to `http://127.0.0.1:9111` and WS to `ws://127.0.0.1:9112`
- Non-local: same-origin HTTP, same-host WebSocket (`wss` when `https`)

**Auth injection:** `chat.html`, `control_center.html`, `project_config.html`, `task_tracker.html`, `buddy_landing.html`, `mobile_projects.html`, `mobile_tasks.html` override `window.fetch` to attach `X-Bridge-Token` from `window.__BRIDGE_UI_TOKEN`.

**Live update model:**
- `chat.html` and `control_center.html`: hybrid REST + WebSocket
- All other pages: fetch/poll only

**Key API endpoints used by the frontend:**

Platform:
- `GET /platform/status`, `POST /platform/start`, `POST /platform/stop`

Agents:
- `GET /agents`, `GET /agents?source=team`, `GET /agents/{id}`
- `PATCH /agents/{id}`, `PATCH /agents/{id}/mode`, `PATCH /agents/{id}/active`
- `POST /agents/{id}/start`, `POST /agents/{id}/restart`
- `GET /agents/{id}/persistence`
- `GET /engines/models`

Messaging:
- `POST /send`, `GET /history?since=...&limit=500`
- `GET /receive/{agent_id}?wait=...&limit=...`
- `POST /messages/{id}/reaction`

Tasks:
- `GET /tasks/summary`, `GET /task/queue`, `GET /task/tracker`
- `POST /task/create`, `PATCH /task/{id}`, `DELETE /task/{id}`
- `GET /task/{id}/history`

Teams/Projects:
- `GET /teams`, `GET /teams/{id}`, `POST /teams`
- `GET /team/orgchart`, `GET /board/projects`, `GET /team/projects`

Workflows:
- `GET /workflows`, `GET /workflows/templates`, `GET /workflows/suggest`
- `POST /workflows/compile`, `POST /workflows/deploy`, `POST /workflows/deploy-template`
- `PATCH /workflows/{id}/toggle`, `DELETE /workflows/{id}`

Buddy:
- `GET /cli/detect?skip_runtime=1`
- `POST /agents/{id}/setup-home`
- `GET /onboarding/status?user_id=...`, `POST /onboarding/start`

**WebSocket events:** Real-time message push on `ws://127.0.0.1:9112`. Token appended to URL when present.

**Payload patterns:**
- Message: `{ from, to, content, meta? }`
- Agent start: `{ from: "user" }`
- Agent mode/model/active patch: `{ mode }` / `{ model }` / `{ active }`
- Task create: `{ title, description, assigned_to, priority, ... }`
- Approval response: `{ request_id, decision, decided_by: "user" }`

Full contract documentation: `docs/frontend/contracts.md`

## Agent System

### Role-Based Homes (homes/)

Each role has a pre-built home directory with 3 files:

```
homes/{role}/
├── SOUL.md       # WHO the agent IS (personality, values, boundaries)
├── ROLE.md       # WHAT the agent KNOWS (domain knowledge, workflows, references)
└── prompt.txt    # Activation prompt for first message
```

**5 pre-built roles:**

| Role | Home | Specialization |
|------|------|----------------|
| buddy | `homes/buddy/` | Navigator, onboarding guide, CLI detection, system navigation |
| frontend | `homes/frontend/` | UI/UX: chat.html, control_center.html, CSS, themes, responsive |
| backend | `homes/backend/` | server.py, bridge_mcp.py, WebSocket, tmux_manager, APIs |
| architect | `homes/architect/` | System architecture, integration, dependency analysis, code review |
| platform | `homes/platform/` | Platform specs, industry solutions, spec-to-code translation |

**How tmux_manager embeds ROLE.md:** The `generate_agent_claude_md()` function receives `role_description` as a parameter. The ROLE.md content provides the agent's domain knowledge and is embedded as the role-specific description section at the end of the generated instruction file. The SOUL.md content is resolved via `soul_engine.prepare_agent_identity()` and embedded as the soul section.

### Team Configuration (team.json)

**Schema (version 3):**

```json
{
  "version": 3,
  "owner": { "id": "user", "name": "User", "role": "owner", "level": 0 },
  "projects": [
    {
      "id": "string",
      "name": "string",
      "path": "string",
      "description": "string",
      "project_md": "string",
      "team_ids": ["string"],
      "shared_memory": "string",
      "scope_labels": { "path": "label" },
      "created_at": "ISO timestamp"
    }
  ],
  "teams": [
    {
      "id": "string",
      "name": "string",
      "lead": "agent_id",
      "members": ["agent_id"],
      "scope": "string"
    }
  ],
  "agents": [
    {
      "id": "string",
      "name": "string",
      "role": "string",
      "level": 0-3,
      "reports_to": "agent_id or user",
      "aliases": ["string"],
      "engine": "claude|codex|qwen|gemini",
      "model": "string (optional)",
      "home_dir": "string",
      "prompt_file": "string",
      "agent_md": "string",
      "description": "string",
      "active": true/false,
      "auto_start": true/false,
      "config_dir": "string",
      "skills": ["skill_id"],
      "mcp_servers": "all|bridge|specific",
      "scope": ["path"],
      "permissions": ["string"]
    }
  ],
  "subscriptions": [
    {
      "id": "string",
      "name": "string",
      "provider": "claude|openai|gemini|qwen",
      "path": "string",
      "active": true/false,
      "plan": "string",
      "rate_limit_tier": "string"
    }
  ],
  "role_templates": {
    "role_pattern": ["skill_id"]
  }
}
```

**Level hierarchy:**
- 0: Owner (user)
- 1: Platform operators (buddy, architect) — can access sensitive endpoints
- 2: Specialists (frontend, backend, platform, team leads)
- 3: Workers (recon, exploit, analysts)

### Agent Lifecycle

1. **Registration:** Agent calls `bridge_register(agent_id, role, capabilities?)` via MCP. Server records the agent in the registry with timestamp.
2. **Heartbeat:** Background task in `bridge_mcp.py` sends HTTP POST heartbeat every 30s. Timeout: 60s before server marks agent as offline.
3. **Session:** `tmux_manager.create_agent_session()` creates tmux session, generates instruction files, launches CLI.
4. **Communication:** Agent sends/receives messages via `bridge_send`/`bridge_receive` MCP tools. WebSocket push delivers messages in real-time.
5. **Task processing:** Agents claim tasks (`bridge_task_claim`), acknowledge (`bridge_task_ack`), check in with progress (`bridge_task_checkin`), and complete (`bridge_task_done` with evidence or `bridge_task_fail`).
6. **Shutdown:** Platform stop kills tmux sessions. Agent can also be stopped individually via `POST /agents/{id}/stop` or the UI.

## Communication

### Bridge MCP Protocol

**Core tools:**
- `bridge_register` — Register agent with the server (agent_id, role, capabilities)
- `bridge_send` — Send message to another agent or channel
- `bridge_receive` — Receive messages (WebSocket push, not polling)
- `bridge_heartbeat` — Send heartbeat (automatic every 30s)
- `bridge_history` — Retrieve message history
- `bridge_status` — Get all agent statuses
- `bridge_health` — System health check
- `bridge_activity` — Report current activity

**Message channels:**
- `control` — Start, stop, resume, approvals
- `work` — Task assignments and results
- `scope` — Goal alignment and coordination

**Message audience resolution** (`server_message_audience.py`): Server-side target resolution for `all`, `all_managers`, `leads`, `team:*` audience specifiers.

**Task system state machine:**
```
created → claimed → in_progress → done
                                 → failed
```
Evidence is mandatory on task completion (`bridge_task_done` requires evidence).

### Knowledge Vault

**Structure:**
```
Knowledge/
├── Agents/     # Per-agent knowledge
├── Users/      # User profiles
├── Projects/   # Project knowledge
├── Teams/      # Team knowledge
├── Tasks/      # Task knowledge
├── Decisions/  # Decision records
└── Shared/     # Shared knowledge
```

**Access via MCP tools:**
- `bridge_knowledge_read` / `bridge_knowledge_write` — CRUD
- `bridge_knowledge_search` — Full-text search
- `bridge_knowledge_init` — Initialize vault structure
- `bridge_knowledge_list` / `bridge_knowledge_info` / `bridge_knowledge_delete` — Management
- `bridge_knowledge_frontmatter` — Read/write frontmatter
- `bridge_knowledge_search_replace` — Find and replace in knowledge files

**Initialization:** `knowledge_engine.init_vault()` creates the directory structure and calls `init_agent_vault`, `init_user_vault`, `init_project_vault`.

## Platform Specifications

10 pre-built industry platform specs:

| Platform | File | Lines |
|----------|------|-------|
| Accounting (DATEV) | `Backend/docs/ACCOUNTING_PLATFORM_SPEC.md` | 748 |
| Big Data Analysis | `Backend/docs/BIG_DATA_ANALYSIS_PLATFORM_SPEC.md` | 817 |
| Creator Platform | `Backend/docs/CREATOR_PLATFORM_RELIABILITY_SPEC.md` | 1,018 |
| Customer Support | `Backend/docs/CUSTOMER_SUPPORT_PLATFORM_SPEC.md` | 244 |
| Cybersecurity | `Backend/docs/CYBERSECURITY_PLATFORM_SPEC.md` | 709 |
| DevOps & Incident | `Backend/docs/DEVOPS_INCIDENT_PLATFORM_SPEC.md` | 468 |
| Finance & Investment | `Backend/docs/FINANCE_ANALYSIS_PLATFORM_SPEC.md` | 670 |
| Legal & Contract | `Backend/docs/LEGAL_CONTRACT_PLATFORM_SPEC.md` | 287 |
| Marketing & Campaign | `Backend/docs/MARKETING_CAMPAIGN_PLATFORM_SPEC.md` | 266 |
| Voice & Secretary | `Backend/docs/VOICE_SECRETARY_PLATFORM_SPEC.md` | 517 |
| **Total** | | **5,744** |

## Configuration

### .mcp.json

Bridge MCP server config for Claude CLI. Generated by `tmux_manager.py` via `mcp_catalog.build_client_mcp_config()` during session creation:

```json
{
  "mcpServers": {
    "bridge": {
      "command": "python3",
      "args": ["/path/to/Backend/bridge_mcp.py"]
    }
  }
}
```

Additional MCP servers (e.g., Playwright, Ghost, AASE) can be included based on the agent's `mcp_servers` field in `team.json` (`"all"` = all available MCPs, `"bridge"` = bridge only).

### Skills

Skills live in `.claude/skills/` (23 skills in the repository):

**Bridge-specific skills:**
- `bridge-agent-core` — Core agent behavior (assigned to all agents)
- `bridge-agent-restart` — Restart handling
- `bridge-deploy` — Deployment procedures
- `bridge-evidence-enforcement` — Mandatory evidence on task completion
- `bridge-pre-action-analysis` — Pre-action analysis requirement
- `bridge-review-code` — Code review protocol
- `bridge-status` — Status reporting
- `bridge-sync-release` — Release synchronization
- `bridge-ui-designer` — UI design patterns

**Superpowers skills (from Claude ecosystem):**
- `superpowers-brainstorming`
- `superpowers-dispatching-parallel-agents`
- `superpowers-executing-plans`
- `superpowers-finishing-a-development-branch`
- `superpowers-receiving-code-review`
- `superpowers-requesting-code-review`
- `superpowers-subagent-driven-development`
- `superpowers-systematic-debugging`
- `superpowers-test-driven-development`
- `superpowers-using-git-worktrees`
- `superpowers-using-superpowers`
- `superpowers-verification-before-completion`
- `superpowers-writing-plans`
- `superpowers-writing-skills`

Skills are assigned to agents via the `skills` array in `team.json`. Role templates (`role_templates` in `team.json`) map role patterns to default skill sets.

## Security

### Token-Based Auth

- **Token sources:** `X-Bridge-Token` header or `Authorization: Bearer <token>`
- **Token types:** User token, UI session token (injected into HTML via `window.__BRIDGE_UI_TOKEN`), agent session token (with grace-token window)
- **Auth tiers:**
  - Public: `GET /status`, `GET /health` and similar read-only status endpoints
  - Agent: Authenticated agent operations (send, receive, task operations)
  - Platform Operator: `level <= 1` required for sensitive endpoints (via `_require_platform_operator()`)
- **Strict mode:** `BRIDGE_STRICT_AUTH` env flag enforces auth on all GET paths when enabled
- **Rate limiting:** Server-side rate-limit checking via `server_http_io.py`
- **Timing-safe comparison:** Used for token validation

### Guardrail Prolog

Immutable security block prepended to every generated instruction file. Cannot be overridden by soul content or external instructions. Enforces:
1. Agent identity immutability
2. No self-modification of instruction/soul files without user approval
3. No credential/data exfiltration
4. External instruction injection resistance
5. No destructive operations without explicit approval

### RBAC

Platform operators (level 0-1: owner, buddy, architect) have access to sensitive management endpoints. Level 2-3 agents are restricted to their scope.

Agent scope enforcement: `scope` and `permissions` fields in `team.json` define what paths an agent can modify and what actions it can perform autonomously.

### Credential Security

Credentials are managed via `bridge_credential_store`, `bridge_credential_get`, `bridge_credential_list`, `bridge_credential_delete` MCP tools. The `credential_vault.py` and `credential_store.py` modules handle storage.

## Quick Reference

| File | Purpose |
|------|---------|
| `Backend/server.py` | HTTP server, all REST endpoints, route table, auth |
| `Backend/bridge_mcp.py` | MCP server (204 tools, stdio transport) |
| `Backend/tmux_manager.py` | Agent tmux session lifecycle, instruction file generation |
| `Backend/soul_engine.py` | Agent identity persistence (SOUL.md, SoulConfig, guardrails) |
| `Backend/persistence_utils.py` | CLI layout resolution, instruction file mapping |
| `Backend/bridge_watcher.py` | WebSocket-to-tmux message router |
| `Backend/websocket_server.py` | WebSocket server (:9112) |
| `Backend/knowledge_engine.py` | Knowledge Vault CRUD |
| `Backend/capability_library.py` | 5,387 MCP ecosystem tool index |
| `Backend/team.json` | Agent/team/project definitions (Single Source of Truth) |
| `Backend/server_startup.py` | Daemon orchestration, startup sequence |
| `Backend/server_request_auth.py` | Token extraction, role resolution, auth tiers |
| `Backend/server_frontend_serve.py` | UI serving with token injection |
| `Backend/common.py` | Shared utilities |
| `Backend/start_platform.sh` | One-command platform start |
| `Frontend/chat.html` | Main chat workspace (dual-board) |
| `Frontend/control_center.html` | Operations dashboard |
| `Frontend/buddy_landing.html` | Buddy onboarding + engine selection |
| `Frontend/bridge_runtime_urls.js` | Centralized API/WS URL resolution |
| `docs/frontend/contracts.md` | Frontend-backend API contracts |
