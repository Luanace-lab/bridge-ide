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
 | - 37 HTTP handler modules               |
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
- `engine_backend.py` — Dual CLI+API backend abstraction (5 providers: Anthropic, OpenAI, Google, xAI, Alibaba)
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
│   ├── handlers/             # 37 HTTP handler modules
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
- **Lock ordering:** `AGENT_STATE_LOCK` -> `TEAM_CONFIG_LOCK` -> `TASK_LOCK`. This order must never be reversed. Additional locks: `SCOPE_LOCK_LOCK`, `WHITEBOARD_LOCK`, `CLI_SETUP_STATE_LOCK`, `TEAM_LEAD_LOCK`, `RUNTIME_LOCK`, `_GRACEFUL_SHUTDOWN_LOCK`, `_AGENT_STATE_WRITE_LOCK`.
- **Auth:** Token-based. Token sources: `X-Bridge-Token` header or `Authorization: Bearer <token>`. Token types: user token, UI session token, agent session token (with grace-token window). GET requests are public by default; POST/PATCH/DELETE are authenticated per tier/path. Sensitive endpoints use `_require_platform_operator()`.
- **Frontend serving:** `server_frontend_serve.py` injects `window.__BRIDGE_UI_TOKEN` into HTML responses so the browser can authenticate subsequent API calls.
- **Handler modules:** 37 modules in `Backend/handlers/` — agents, approvals, automation, boards, capabilities, chat files, CLI, credentials, data, domain, events, execution, federation, git locks, guardrails, health, logs, MCP catalog, media, memory, messages, meta, metrics, onboarding, projects, runtime, scope locks, shared tools, skills, subscriptions, system status, tasks, team lead scope, teams, whiteboard, workflows.
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
  - **Browser/Desktop:** Full browser automation, desktop control, protected-site access
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

#### Engine-Specific CLI Commands (tmux_engine_policy.py)

Each engine is defined as a `TmuxEngineSpec` dataclass with 5 fields: `engine`, `instruction_filename`, `start_shell`, `ready_prompt_regex`, `submit_enter_count`. The `tmux_engine_spec()` function returns the spec for a given engine name.

| Engine | `start_shell` (base command) | `ready_prompt_regex` | `submit_enter_count` |
|--------|------------------------------|---------------------|---------------------|
| claude | `unset CLAUDECODE CODEX_MANAGED_BY_NPM CODEX_THREAD_ID CODEX_CI CODEX_SANDBOX_NETWORK_DISABLED && claude` | `^\s*[>⏵❯]\s*(?!\d+\.)` | 2 |
| codex | `unset CLAUDECODE CODEX_MANAGED_BY_NPM CODEX_THREAD_ID CODEX_CI CODEX_SANDBOX_NETWORK_DISABLED && codex --no-alt-screen` | `^\s*›\s*(?!\d+\.)` | 1 |
| qwen | `qwen` | `^\s*(?:[>⏵❯]\s*(?!\d+\.)|\*\s+Type your message)` | 2 |
| gemini | `gemini` | `^\s*(?:[>⏵❯]\s*(?!\d+\.)|\*\s+Type your message)` | 2 |

The base `start_shell` is extended at runtime with engine-specific flags. The full command construction flow in `create_agent_session()` (line 2100+) is:

1. **Resume flag:** Claude appends `--resume {id}`. Codex replaces `codex --no-alt-screen` with `codex resume {id} --no-alt-screen`. Gemini appends `--resume latest` if `~/.gemini/projects/{mangled}/` contains `.jsonl` files. Qwen appends `--resume {id}`.
2. **Model flag:** `--model` (claude), `-m` (codex/gemini/qwen) with the model string from team.json.
3. **Permission mode:** Claude uses `--permission-mode {mode}`. Codex uses `-s {sandbox_mode} -a {approval_policy}` (mapped via `codex_runtime_policy()`). Qwen uses `--approval-mode`. Gemini uses `--approval-mode`.
4. **Environment exports:** `_bridge_cli_identity_exports()` prepends `export BRIDGE_CLI_AGENT_ID=... BRIDGE_CLI_ENGINE=... && ` to the entire command string.
5. **Engine-specific env:** Claude prepends `CLAUDE_CONFIG_DIR=... BROWSER=false`. Codex prepends `CODEX_HOME=...`. Qwen prepends `QWEN_CODE_TRUSTED_FOLDERS_PATH=...`. Gemini prepends `GEMINI_CLI_TRUSTED_FOLDERS_PATH=...`.
6. **Include directories:** Qwen and Gemini append `--include-directories {project_path},{bridge_root}`.

#### tmux Environment Variables (_bridge_cli_identity_env, line 1711)

Every agent session exports these variables into the tmux environment and as shell exports before the CLI command. These are read by `bridge_mcp.py` during agent registration to identify which agent it is serving.

| Variable | Value | Purpose |
|----------|-------|---------|
| `BRIDGE_CLI_AGENT_ID` | agent_id | Agent identifier for MCP registration |
| `BRIDGE_CLI_ENGINE` | claude/codex/qwen/gemini | Engine type |
| `BRIDGE_CLI_HOME_DIR` | workspace path | Agent workspace absolute path |
| `BRIDGE_CLI_WORKSPACE` | workspace path | Same as HOME_DIR (canonical) |
| `BRIDGE_CLI_PROJECT_ROOT` | project root path | Parent of `.agent_sessions/` |
| `BRIDGE_CLI_INSTRUCTION_PATH` | full path to instruction file | e.g. `.../CLAUDE.md` |
| `BRIDGE_CLI_SESSION_NAME` | `acw_{agent_id}` | tmux session name |
| `BRIDGE_CLI_INCARNATION_ID` | UUID-based ID | Unique per session start (distinguishes restarts) |
| `BRIDGE_CLI_RESUME_SOURCE` | source string | How the resume ID was determined |
| `BRIDGE_RESUME_ID` | session UUID or empty | Resume ID for session continuity |

Additionally, `_bridge_runtime_env()` injects server-level variables (port, auth tokens, etc.) that are merged into the same export block.

#### Startup Stabilization

After `tmux send-keys` launches the CLI, engine-specific stabilization functions handle interactive dialogs that block autonomous startup. Each function polls the tmux pane content with a 20-second timeout:

**Claude** (`_stabilize_claude_startup`, line 698):
- "Quick safety check" + "Yes, I trust this folder" dialog: Presses Enter to confirm.
- "Bypass Permissions mode" + "Yes, I accept" dialog (only in bypassPermissions mode): Presses Down then Enter to accept.
- Waits for the ready prompt regex match.

**Codex** (`_stabilize_codex_startup`, line 761):
- "Update available!" + "Skip until next version" dialog: Presses Down twice then Enter to skip.
- "Select Reasoning Level" dialog: Presses Enter to confirm default.
- Waits for ready prompt regex.

**Gemini** (`_stabilize_gemini_startup`, line 731):
- "Usage limit reached for all Pro models." + "Switch to gemini-2.5-flash" dialog: Presses Enter to accept the fallback model.
- Waits for ready prompt regex (with additional check that the usage-limit message is gone).

**Qwen:** No dedicated stabilization function. Uses the generic ready-prompt wait via the initial prompt script.

After stabilization, Claude sessions with a resume ID additionally check for a usage-limit screen. If detected, the resume ID is blocked via `_block_resume_id()`, the session is killed, and `create_agent_session()` is called recursively with `_skip_resume_once=True` to start fresh.

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

### Persistence & Context Lifecycle

The persistence system ensures agent state survives context window compaction (when the LLM's context fills up) and session restarts. Three files form the persistence layer, stored in the agent workspace (`{project}/.agent_sessions/{agent_id}/`):

#### CONTEXT_BRIDGE.md

**What it is:** A machine-generated snapshot of the agent's current state, written by `bridge_watcher.py` (`_write_context_bridge()`, line 1455). It contains:
- `## HANDOFF` — Agent identity, registration command, instruction to read SOUL.md
- `## STATUS` — Server health, agent status, mode, context usage %, last activity
- `## OFFENE TASKS` — Active tasks from `/task/queue` (limit: 10 per `CONTEXT_BRIDGE_TASK_LIMIT`)
- `## LETZTE 5 NACHRICHTEN` — Recent messages from `/messages` or `/history` (limit: 5 per `CONTEXT_BRIDGE_MESSAGE_LIMIT`)
- `## CLI DIARY` — Terminal transcript snapshot (last 120 lines via `_capture_cli_session_log`)
- `## NAECHSTER SCHRITT` — Instruction to call `bridge_receive()` and continue last activity

**When it is written:**
1. **Seed creation:** `_ensure_context_bridge()` (tmux_manager.py line 933) creates a minimal seed at session start if the file does not exist.
2. **Periodic refresh:** `_context_bridge_refresh_daemon()` rewrites it for all agents every 300 seconds (`CONTEXT_BRIDGE_REFRESH_INTERVAL`).
3. **Context pressure stages:** Written at 80% (warning), 85% (bridge save), and 95% (hard stop) context usage by `_context_monitor()`.
4. **Manual compact detection:** Written when `_detect_manual_compact()` observes the agent typing `/compact` or `/compress`.

**What survives compact:** Everything in CONTEXT_BRIDGE.md survives because it is on disk. After compaction clears the LLM's in-context memory, the agent reads CONTEXT_BRIDGE.md to restore awareness of its identity, tasks, and last activity.

#### SOUL.md

Immutable agent identity file. Created once by `save_soul()` (soul_engine.py line 366) — never overwritten (the function returns `False` if the file exists). Contains personality, values, communication style, boundaries. Resolution cascade: `homes/{role}/SOUL.md` (from team.json `home_dir`) > workspace SOUL.md > `.soul_meta.json` > `DEFAULT_SOULS` dict > generic fallback.

#### MEMORY.md

Persistent agent memory managed by `persistence_utils.py`. Contains architecture knowledge, user decisions, patterns, errors/fixes — structured sections the agent updates over time. Location resolution (`find_agent_memory_path()`, line 170) searches:
1. Workspace: `{workspace}/MEMORY.md`
2. Claude config memory: `{config_dir}/projects/{mangled_cwd}/memory/MEMORY.md`
3. Glob fallback: `{config_dir}/projects/*-{agent_id}/memory/MEMORY.md` (newest by mtime)

Cross-account linking: `_ensure_persistent_symlinks()` (tmux_manager.py line 952) symlinks `{alt_config_dir}/projects/` to `~/.claude/projects/` so agents running on different subscription accounts share the same memory directory. Claude Code stores auto-memory under `{config_dir}/projects/{mangled_cwd}/memory/`, so the symlink ensures all accounts see the same data.

#### Compact Cycle (Context Window Full)

The context monitor (`_context_monitor()` in bridge_watcher.py, line 1944) runs every 15 seconds and implements a 4-stage escalation:

| Stage | Threshold | Action |
|-------|-----------|--------|
| 1 | 80% | Warning: write CONTEXT_BRIDGE.md, set activity to `context_warning` |
| 2 | 85% | Save state: write CONTEXT_BRIDGE.md again, set activity to `context_saving` |
| 3 | 90% | Inject message into tmux: "CONTEXT BEI {pct}%. State gesichert. Beende deinen aktuellen Gedanken." |
| 4 | 95% | Hard stop: `_force_context_stop()` sends engine-specific compact command |

`_force_context_stop()` (line 1812) executes the engine compact command:
- Claude: `/compact`
- Gemini: `/compress`
- Codex: no compact available (auto-managed threads)
- Qwen: no compact available

The function polls for 60 seconds (12 x 5s) waiting for the agent to reach a prompt, then sends the compact command via `tmux send-keys`. If the agent is not at a prompt after 60s, it sends Ctrl+C followed by the compact command.

**Auto-resume after compact:** When context drops below 70% (indicating successful compaction), the monitor injects: "Du wurdest compacted. Lies CONTEXT_BRIDGE.md und arbeite an deiner letzten Aktivitaet weiter." and sets activity to `resuming`.

#### Resume Mechanism

Resume IDs allow sessions to continue from where they left off after restart. Each engine handles resume differently:

- **Claude:** UUID-based session ID. Persisted to `pids/session_ids.json` via `_persist_session_id()`. Extracted at next start via `_extract_resume_lineage()` (line 1475). Appended as `--resume {id}` to the CLI command. Validated against `{config_dir}/projects/` before use — invalid IDs are silently dropped.
- **Codex:** UUID-based session ID. Stored in both `pids/session_ids.json` and `CODEX_HOME`. Uses `codex resume {id} --no-alt-screen` subcommand syntax. Validated against local CODEX_HOME directory.
- **Gemini:** Index-based resume (`--resume latest`). No UUID stored. Presence of `.jsonl` files in `~/.gemini/projects/{mangled}/` triggers resume.
- **Qwen:** UUID-based, same pattern as Claude. Appended as `--resume {id}`.

Resume IDs can be blocked via `_block_resume_id()` when they cause errors (e.g., usage limit screens), preventing retry loops.

#### What Survives Restart

| Artifact | Location | Survives Restart | Survives Compact |
|----------|----------|-----------------|-----------------|
| SOUL.md | workspace | Yes | Yes (on disk) |
| CONTEXT_BRIDGE.md | workspace | Yes | Yes (on disk, re-read after compact) |
| MEMORY.md | workspace or config dir | Yes | Yes (on disk) |
| Instruction file (CLAUDE.md etc.) | workspace | Yes (regenerated at start) | Yes (on disk) |
| .mcp.json | workspace | Yes (regenerated at start) | Yes (on disk) |
| Resume ID | pids/session_ids.json | Yes | N/A |
| In-context working state | LLM memory | No (lost on restart) | No (lost on compact) |
| WebSocket message buffer | bridge_mcp.py deque | No (lost on restart) | N/A |
| tmux pane content | tmux scrollback | Yes (survives compact) | Yes |

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
| `landing.html` | Marketing landing page with anchor navigation (serves as `/` entrypoint via server) |
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

**Auth injection:** `chat.html`, `control_center.html`, `project_config.html`, `task_tracker.html`, `mobile_projects.html`, `mobile_tasks.html` override `window.fetch` to attach `X-Bridge-Token` from `window.__BRIDGE_UI_TOKEN`.

**Live update model:**
- `chat.html` and `control_center.html`: hybrid REST + WebSocket
- All other pages: fetch/poll only

**Key API endpoints used by the frontend:**

Platform:
- `GET /status`, `POST /platform/start`, `POST /platform/stop`

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
- 3: Workers (recon, specialists, analysts)

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

### Capability Library & MCP Ecosystem

The capability library is a curated index of 5,387 MCP tools from the broader ecosystem, stored as a JSON file at `config/capability_library.json`. It enables agents to discover and evaluate tools beyond the 204 built-in Bridge tools. **Note:** `config/capability_library.json` is auto-generated at runtime and not shipped in the repo (listed in `.gitignore`).

#### How capability_library.py Builds the Index

`capability_library.py` reads the JSON index from `config/capability_library.json` (default path, overridable via `BRIDGE_CAPABILITY_LIBRARY_PATH` env). The file is loaded with mtime-based caching (`_read_library()`, line 36) — re-read only when the file changes on disk. Each entry contains:
- `id`, `name`, `title`, `vendor`, `owner`, `summary`
- `type` (tool/server/plugin)
- `engine_compatibility` — per-engine compatibility status (`documented`, `inferred`)
- `task_tags` — categorization tags
- `trust_tier` — `official`, `bridge`, `registry`, `legacy` (affects sort priority)
- `install_methods` — how to install/activate the tool
- `official_vendor`, `runtime_verified`, `reproducible` — quality flags

Search uses tokenized matching (`_match_tokens()`, line 142) with weighted scoring: name matches (8.0) > tag matches (6.0) > vendor matches (4.0) > summary matches (2.0) > general matches (1.0). Official vendor and runtime-verified entries get bonus scores.

#### Agent Tool Discovery (MCP Tools)

Agents discover tools through 4 MCP tools exposed by `bridge_mcp.py`, backed by `capability_library.py`:

| MCP Tool | Backend Function | Purpose |
|----------|-----------------|---------|
| `bridge_capability_library_recommend` | `recommend_entries(task, engine, top_k)` | Task-based recommendation: "what tools help with X?" |
| `bridge_capability_library_search` | `search_entries(query, filters...)` | Filtered search with scoring, pagination |
| `bridge_capability_library_list` | `list_entries(filters...)` | Browse with filters (type, vendor, cli, tag, status, trust_tier) |
| `bridge_capability_library_get` | `get_entry(entry_id)` | Retrieve full details for a specific entry |

`recommend_entries()` (line 358) wraps `search_entries()` with the agent's task description as query and engine as CLI filter, returning the top-k matches.

#### Skills to MCPs Mapping (mcp_catalog.py)

The `mcp_catalog.py` module manages the runtime MCP server catalog (`config/mcp_catalog.json`) and maps agent skills to required MCP servers.

**`resolve_mcps_for_skills(skills)`** (line 235): Given a list of skill IDs (from team.json `skills` array), looks up each skill in `config/skill_mcp_map.json`. For skills with `auto_attach: true`, collects their `preferred_mcps` entries. Only MCPs that exist in the runtime catalog are included. Returns a sorted, deduplicated list of MCP names.

This is called during session creation (tmux_manager.py line 2049-2058): agent skills are read from team.json, skill-derived MCPs are resolved, and merged into the `mcp_servers` string. The resulting `.mcp.json` file includes both explicitly configured MCPs and skill-derived MCPs.

**Runtime MCP catalog** (`config/mcp_catalog.json`): Defines available MCP servers with:
- `runtime_servers` — launchable servers (bridge, playwright, ghost, aase, etc.) with `command`, `args`, `env` templates. Placeholders (`{backend_dir}`, `{root_dir}`, `{home}`) are resolved at runtime via `_resolve_template()`.
- `planned_servers` — metadata-only entries for servers not yet available.

`build_client_mcp_config(mcp_servers)` (line 147) produces the `.mcp.json` payload by resolving requested MCP names against the runtime catalog. `mcp_servers="all"` includes all servers with `include_in_all: true`. Empty or `"bridge"` includes bridge only.

#### Capability-Bootstrap-Pflicht (Mandatory Tool Discovery)

Every agent instruction file includes a mandatory work rule (rule 8 in `generate_agent_claude_md()`, tmux_manager.py line 2750):

> "Capability-Bootstrap (PFLICHT): Vor der ersten Aufgabe jeder Session: bridge_capability_library_recommend + bridge_capability_library_search ausfuehren. Eigenes Toolset aktiv verifizieren. Du bist verantwortlich fuer deine eigenen Tools."

The initial activation prompt (line 918-923) also includes step 4: `bridge_capability_library_recommend(task='<deine Rolle>')`. This ensures every agent discovers its available tools at session start, before processing any tasks.

## Platform Specifications

### What a "Platform" Is

A platform in Bridge ACE is a vertical industry solution built on three layers:

1. **Spec document** (`Backend/docs/*_PLATFORM_SPEC.md`): A detailed requirements document defining the domain, user workflows, agent roles, data models, API contracts, and acceptance criteria. Example: `ACCOUNTING_PLATFORM_SPEC.md` (748 lines) defines DATEV-compatible bookkeeping with automatic receipt categorization, dual-agent verification, and UStVA reporting. Specs are authored by agents/users and marked with revision status (e.g., "FREIGEGEBEN — Implementierungsgrundlage").

2. **Backend modules** (`Backend/data_platform/`, `Backend/handlers/`): Python modules implementing the platform's data layer and API endpoints. The `data_platform/` module provides the reference implementation:
   - `source_registry.py` — Data source CRUD (register, ingest, profile, query). Supports CSV, Excel, JSON, SQLite, Parquet. Uses two-phase DuckDB: privileged ingestion into canonical Parquet format, then sandboxed read-only queries. Storage under `~/.bridge/data_platform/`.
   - `analysis_pipeline.py` — 10-stage analysis run engine. Creates runs with questions against dataset versions, executes deterministic analysis stages (agents are control-plane only for stages A1, A1B, A9), produces evidence and reports. Uses the `creator_job.py` worker/queue infrastructure.
   - Handler modules in `Backend/handlers/` expose these as REST endpoints (e.g., `bridge_data_query`, `bridge_data_source_register`).

3. **Frontend components**: Platform-specific UI elements in the frontend pages (e.g., platform start/stop controls in `chat.html`).

### How a User Activates a Platform

- **Start:** `POST /platform/start` (server.py line 5912). Starts all agents with `auto_start: true` in team.json, launches the bridge_watcher, and starts the output_forwarder. The `platform_status_snapshot()` function (line 3988) provides current state.
- **Stop:** `POST /platform/stop` (server.py line 6006). Gracefully stops all agents, watcher, forwarder, and optionally the server itself.
- **Status:** `GET /status` returns agent states, health, and runtime info.

Both endpoints require platform operator auth (`_require_platform_operator()`, level 0-1).

### Platform Spec Structure

Spec documents follow a consistent format (visible in ACCOUNTING_PLATFORM_SPEC.md):
- Section 1: Goal, product differentiation, target audience, 6-month vision
- Section 2+: Domain-specific workflows, data models, agent roles, API contracts, error handling, acceptance criteria
- Metadata header: date, author, revision history, approval status

9 pre-built industry platform specs:

| Platform | File | Lines |
|----------|------|-------|
| Accounting (DATEV) | `Backend/docs/ACCOUNTING_PLATFORM_SPEC.md` | 748 |
| Big Data Analysis | `Backend/docs/BIG_DATA_ANALYSIS_PLATFORM_SPEC.md` | 817 |
| Customer Support | `Backend/docs/CUSTOMER_SUPPORT_PLATFORM_SPEC.md` | 244 |
| DevOps & Incident | `Backend/docs/DEVOPS_INCIDENT_PLATFORM_SPEC.md` | 468 |
| Finance & Investment | `Backend/docs/FINANCE_ANALYSIS_PLATFORM_SPEC.md` | 670 |
| Legal & Contract | `Backend/docs/LEGAL_CONTRACT_PLATFORM_SPEC.md` | 287 |
| Marketing & Campaign | `Backend/docs/MARKETING_CAMPAIGN_PLATFORM_SPEC.md` | 266 |
| Voice & Secretary | `Backend/docs/VOICE_SECRETARY_PLATFORM_SPEC.md` | 517 |
| **Total** | | **4,726** |

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
