# Runtime Bring-up Pfad — Evidenz
Stand: 2026-03-10T12:14 UTC
Quelle: codex_1 (Task 7ee317ee), Analyse server.py + tmux_manager.py + bridge_mcp.py

## Pfad: /runtime/configure → open_agent_sessions → create_agent_session → register

### 1. POST /runtime/configure (server.py:16096–16321)
- Validiert Payload/Engines/Projektpfad
- Baut `runtime_layout` + `agent_profiles`
- Stoppt alte Sessions, leert `REGISTERED_AGENTS`
- Ruft `open_agent_sessions(config)` auf (L16303-16304)
- Wartet via `_wait_for_agent_registration(runtime_agent_ids, stabilize_seconds)` (L16315-16321)
  - Helper: server.py:8261-8279

### 2. open_agent_sessions (server.py:5945–6065)
- Iteriert Runtime-Layout
- Mappt pro Agent: Role/Prompt/Capabilities/Scope/Permission-Mode/Tools
- Ruft `create_agent_session(...)` für jeden Eintrag auf (L6041-6056)

### 3. create_agent_session (tmux_manager.py:841–1054)
- Erstellt Workspace `.agent_sessions/{agent_id}`
- Seeded `CONTEXT_BRIDGE.md`
- Schreibt agent-spezifische Instruktionen + Runtime-Config
- Startet tmux-Session + CLI (L963-1028)
- Startet detached `init_agent_prompt.sh` mit `_agent_initial_prompt(...)` (L1034-1049)
- Injizierter Prompt (tmux_manager.py:475-479): "Lies deine <instruction>. Registriere dich SOFORT via bridge_register MCP Tool. Dann pruefe bridge_receive..."

### 4. bridge_register (bridge_mcp.py:1561–1588)
- Läuft asynchron: vom gestarteten Agenten aufgerufen (nicht server-intern)
- POSTet an `/register` mit agent_id, role, capabilities, session_nonce, context_lost

### 5. POST /register Handler (server.py:15667–15770)
- Erzeugt Session-Token
- Aktualisiert `REGISTERED_AGENTS[agent_id]`
- Broadcastet `agent_registered`
- Triggert optional CONTEXT RESTORE

## Kurzfazit
`/runtime/configure` startet Sessions und wartet nur. Der Übergang zu `register` geschieht
**asynchron** über den per tmux injizierten Initial-Prompt + MCP `bridge_register` des Agenten.

## Claim/Ack-Pfad (assi, Task 0351b879, server.py:14608–14701)
### POST /task/{id}/claim (L14608–14664)
1. agent_id aus Body oder X-Bridge-Agent Header
2. TASK_LOCK acquire
3. G9 Idempotent reclaim: state in (claimed,acked) + assigned_to==agent_id → 200 (reclaimed=True)
4. state != "created" → 409
5. pre-assigned check: assigned_to && != agent_id → 403
6. G5 Capability check → 403 wenn fehlend
7. Backpressure: _count_agent_active_tasks() >= TASK_MAX_ACTIVE_PER_AGENT → 429
8. Mutation: state="claimed", assigned_to, claimed_at, state_history.append
9. _persist_tasks() + _append_task_transition_wal()
10. ws_broadcast("task_claimed") + _whiteboard_post

### POST /task/{id}/ack (L14667–14701)
1. state != "claimed" → 409
2. assigned_to != agent_id → 403
3. Backpressure (exclude_task_id)
4. Mutation: state="acked", acked_at, _refresh_task_lease(task)
5. ws_broadcast("task_acked")

**Key:** Idempotenz nur beim Claim (G9), nicht beim Ack. Beide unter TASK_LOCK (thread-safe).

## Backpressure (claude_3, Task 9d4c1b5d)
- TASK_MAX_ACTIVE_PER_AGENT = 3 (server.py:1660)
- TASK_BACKLOG_WARN_THRESHOLD = 5 (server.py:1659)
- GET /task/queue?check_agent=<id> liefert claimability-Annotation pro Task
- 403 bei fehlenden Capabilities, 429 bei Capacity-Overflow, 409 bei Race Condition

**Schwachstelle:** Agents ohne `capabilities`-Parameter bei bridge_register können keine
capability-requirenden Tasks claimen — obwohl CLAUDE.md die Permission hat.
