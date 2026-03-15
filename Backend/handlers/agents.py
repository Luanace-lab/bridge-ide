"""Agent liveness/status/snapshot functions extracted from server.py (Slice 03).

This module owns:
- _registered_agents_snapshot
- agent_connection_status / _agent_liveness_ts / _agent_is_live
- _clear_agent_runtime_presence
- update_agent_status / _notify_agent_back_online
- _check_tmux_session
- _get_agent_engine

Anti-circular-import strategy:
  All shared state and cross-domain functions are injected via init().
  This module NEVER imports from server.
  Direct imports only from: persistence_utils, handlers.messages.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from persistence_utils import detect_instruction_filename

# ---------------------------------------------------------------------------
# Module-local globals (fully owned here)
# ---------------------------------------------------------------------------
_PREV_AGENT_STATUS: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Injected shared state (set by init())
# ---------------------------------------------------------------------------
_REGISTERED_AGENTS: dict[str, dict[str, Any]] = {}
_AGENT_LAST_SEEN: dict[str, float] = {}
_AGENT_BUSY: dict[str, bool] = {}
_SESSION_TOKENS: dict[str, str] = {}
_AGENT_TOKENS: dict[str, str] = {}
_AGENT_STATE_LOCK: Any = None
_TASKS: dict[str, dict[str, Any]] = {}
_TASK_LOCK: Any = None
_TEAM_CONFIG: dict[str, Any] = {}
_TEAM_CONFIG_LOCK: Any = None
_FRONTEND_DIR = ""
_RUNTIME: dict[str, Any] = {}
_RUNTIME_LOCK: Any = None
_PORT = 0
_ROOT_DIR = ""
_team_config_getter_fn: Callable[[], dict[str, Any] | None] | None = None
_SETUP_CLI_BINARIES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Injected callbacks (set by init())
# ---------------------------------------------------------------------------
_ws_broadcast: Callable[..., Any] | None = None
_notify_teamlead_crashed: Callable[..., Any] | None = None
_tmux_session_for: Callable[[str], str] | None = None
_tmux_session_name_exists: Callable[[str], bool] | None = None
_runtime_layout_from_state: Callable[[dict], list] | None = None
_get_agent_home_dir: Callable[[str], str] | None = None
_check_agent_memory_health_fn: Callable[[str], dict[str, Any]] | None = None
_append_message_fn: Callable[..., Any] | None = None
_atomic_write_team_json_fn: Callable[[], Any] | None = None
_create_agent_session_fn: Callable[..., Any] | None = None
_kill_agent_session_fn: Callable[[str], bool] | None = None
_is_session_alive_fn: Callable[[str], bool] | None = None
_materialize_agent_setup_home_fn: Callable[..., dict[str, Any]] | None = None
_sync_agent_persistent_cli_config_fn: Callable[[str, dict[str, Any]], Any] | None = None


def init(
    *,
    registered_agents: dict[str, dict[str, Any]],
    agent_last_seen: dict[str, float],
    agent_busy: dict[str, bool],
    session_tokens: dict[str, str],
    agent_tokens: dict[str, str],
    agent_state_lock: Any,
    tasks: dict[str, dict[str, Any]],
    task_lock: Any,
    team_config: dict[str, Any],
    team_config_lock: Any,
    team_config_getter_fn: Callable[[], dict[str, Any] | None] | None = None,
    frontend_dir: str,
    runtime: dict[str, Any],
    runtime_lock: Any,
    ws_broadcast_fn: Callable[..., Any],
    notify_teamlead_crashed_fn: Callable[..., Any],
    tmux_session_for_fn: Callable[[str], str],
    tmux_session_name_exists_fn: Callable[[str], bool],
    runtime_layout_from_state_fn: Callable[[dict], list],
    get_agent_home_dir_fn: Callable[[str], str],
    check_agent_memory_health_fn: Callable[[str], dict[str, Any]],
    append_message_fn: Callable[..., Any],
    atomic_write_team_json_fn: Callable[[], Any],
    setup_cli_binaries: dict[str, str] | None = None,
    materialize_agent_setup_home_fn: Callable[..., dict[str, Any]] | None = None,
    sync_agent_persistent_cli_config_fn: Callable[[str, dict[str, Any]], Any] | None = None,
    root_dir: str = "",
    bridge_port: int = 0,
    create_agent_session_fn: Callable[..., Any] | None = None,
    kill_agent_session_fn: Callable[[str], bool] | None = None,
    is_session_alive_fn: Callable[[str], bool] | None = None,
) -> None:
    """Bind shared state and cross-domain callbacks.  Must be called once
    before any other function in this module is used."""
    global _REGISTERED_AGENTS, _AGENT_LAST_SEEN, _AGENT_BUSY
    global _SESSION_TOKENS, _AGENT_TOKENS, _AGENT_STATE_LOCK
    global _TASKS, _TASK_LOCK, _TEAM_CONFIG, _TEAM_CONFIG_LOCK, _FRONTEND_DIR, _RUNTIME, _RUNTIME_LOCK, _PORT, _ROOT_DIR
    global _team_config_getter_fn
    global _SETUP_CLI_BINARIES
    global _ws_broadcast, _notify_teamlead_crashed
    global _tmux_session_for, _tmux_session_name_exists
    global _runtime_layout_from_state, _get_agent_home_dir
    global _check_agent_memory_health_fn, _append_message_fn
    global _atomic_write_team_json_fn
    global _create_agent_session_fn, _kill_agent_session_fn, _is_session_alive_fn
    global _materialize_agent_setup_home_fn, _sync_agent_persistent_cli_config_fn

    _REGISTERED_AGENTS = registered_agents
    _AGENT_LAST_SEEN = agent_last_seen
    _AGENT_BUSY = agent_busy
    _SESSION_TOKENS = session_tokens
    _AGENT_TOKENS = agent_tokens
    _AGENT_STATE_LOCK = agent_state_lock
    _TASKS = tasks
    _TASK_LOCK = task_lock
    _TEAM_CONFIG = team_config
    _TEAM_CONFIG_LOCK = team_config_lock
    _team_config_getter_fn = team_config_getter_fn
    _FRONTEND_DIR = frontend_dir
    _RUNTIME = runtime
    _RUNTIME_LOCK = runtime_lock
    _ROOT_DIR = root_dir
    _PORT = bridge_port
    _SETUP_CLI_BINARIES = dict(setup_cli_binaries or {})

    _ws_broadcast = ws_broadcast_fn
    _notify_teamlead_crashed = notify_teamlead_crashed_fn
    _tmux_session_for = tmux_session_for_fn
    _tmux_session_name_exists = tmux_session_name_exists_fn
    _runtime_layout_from_state = runtime_layout_from_state_fn
    _get_agent_home_dir = get_agent_home_dir_fn
    _check_agent_memory_health_fn = check_agent_memory_health_fn
    _append_message_fn = append_message_fn
    _atomic_write_team_json_fn = atomic_write_team_json_fn
    _create_agent_session_fn = create_agent_session_fn
    _kill_agent_session_fn = kill_agent_session_fn
    _is_session_alive_fn = is_session_alive_fn
    _materialize_agent_setup_home_fn = materialize_agent_setup_home_fn
    _sync_agent_persistent_cli_config_fn = sync_agent_persistent_cli_config_fn


# ===================================================================
# Agent snapshot
# ===================================================================

def _registered_agents_snapshot() -> dict[str, dict[str, Any]]:
    """Return a shallow copy of REGISTERED_AGENTS under the agent-state lock."""
    with _AGENT_STATE_LOCK:
        return {
            agent_id: dict(reg or {})
            for agent_id, reg in _REGISTERED_AGENTS.items()
        }


def _get_team_config() -> dict[str, Any] | None:
    if _team_config_getter_fn is not None:
        return _team_config_getter_fn()
    return _TEAM_CONFIG


# ===================================================================
# Liveness & status
# ===================================================================

def agent_connection_status(agent_id: str, stale_seconds: float = 90.0) -> str:
    """Return 'running' | 'waiting' | 'disconnected' based on heartbeat and registration.

    V2: Uses REGISTERED_AGENTS heartbeat as primary signal.
    V3: Counts explicit Bridge activity (/receive, /send) as liveness for
    registered agents as well. This keeps fallback-based CLIs online without
    rewriting the authenticated heartbeat field.
    """
    reg = _REGISTERED_AGENTS.get(agent_id)
    last_seen = _agent_liveness_ts(agent_id, reg=reg)
    if last_seen <= 0 or (time.time() - last_seen) > stale_seconds:
        return "disconnected"
    if _AGENT_BUSY.get(agent_id, False):
        return "running"
    return "waiting"


def _agent_liveness_ts(agent_id: str, *, reg: dict[str, Any] | None = None) -> float:
    """Return the freshest known liveness signal for an agent.

    REGISTERED_AGENTS.last_heartbeat is authoritative when available, but
    AGENT_LAST_SEEN captures live fallback activity through /receive and /send.
    """
    last_seen = float(_AGENT_LAST_SEEN.get(agent_id, 0) or 0)
    if reg is None:
        reg = _REGISTERED_AGENTS.get(agent_id)
    if reg is None:
        return last_seen
    last_hb = float(reg.get("last_heartbeat", 0) or 0)
    return max(last_hb, last_seen)


def _agent_is_live(
    agent_id: str,
    *,
    stale_seconds: float = 120.0,
    reg: dict[str, Any] | None = None,
) -> bool:
    last_seen = _agent_liveness_ts(agent_id, reg=reg)
    return last_seen > 0 and (time.time() - last_seen) < stale_seconds


# ===================================================================
# Presence management
# ===================================================================

def _clear_agent_runtime_presence(agent_id: str) -> None:
    with _AGENT_STATE_LOCK:
        _REGISTERED_AGENTS.pop(agent_id, None)
        _AGENT_LAST_SEEN.pop(agent_id, None)
        _AGENT_BUSY.pop(agent_id, None)
        _PREV_AGENT_STATUS.pop(agent_id, None)
        old_token = _AGENT_TOKENS.pop(agent_id, None)
        if old_token:
            _SESSION_TOKENS.pop(old_token, None)
    update_agent_status(agent_id)


def update_agent_status(agent_id: str) -> None:
    """Check if agent status changed and broadcast via WebSocket if so."""
    with _AGENT_STATE_LOCK:
        new_status = agent_connection_status(agent_id)
        old_status = _PREV_AGENT_STATUS.get(agent_id)
        if new_status != old_status:
            _PREV_AGENT_STATUS[agent_id] = new_status
    if new_status != old_status:
        _ws_broadcast("agent_status", {  # type: ignore[misc]
            "agent_id": agent_id,
            "status": new_status,
        })
        # Auto-notify teamlead on agent crash (transition to disconnected from active state)
        if new_status == "disconnected" and old_status in ("running", "waiting"):
            _notify_teamlead_crashed(agent_id, old_status)  # type: ignore[misc]
        # V4: Notify stakeholders when agent comes back online
        if new_status in ("running", "waiting") and old_status == "disconnected":
            _notify_agent_back_online(agent_id)


def _notify_agent_back_online(agent_id: str) -> None:
    """V4: Notify task creators + management when an agent comes back online."""
    from handlers.messages import append_message

    _ws_broadcast("agent_online", {"agent_id": agent_id})  # type: ignore[misc]
    print(f"[health] ONLINE: {agent_id} is back")
    # Find stakeholders: creators of active tasks assigned to this agent
    notified: set[str] = set()
    with _TASK_LOCK:
        for t in _TASKS.values():
            if t.get("assigned_to") == agent_id and t.get("state") in ("created", "claimed", "acked"):
                creator = t.get("created_by", "")
                if creator and creator != agent_id and creator not in notified:
                    notified.add(creator)
    # Add management-level agents (level 0-1) from team.json
    team_config = _get_team_config()
    if team_config:
        for ag in team_config.get("agents", []):
            aid = ag.get("id", "")
            if aid and ag.get("level", 99) <= 1 and aid != agent_id and aid not in notified:
                notified.add(aid)
    msg = f"[ONLINE] Agent {agent_id} ist wieder online."
    for target in notified:
        try:
            append_message("system", target, msg)
        except Exception:
            pass


def _check_agent_memory_health(agent_id: str) -> dict[str, Any]:
    if _check_agent_memory_health_fn is None:
        raise RuntimeError("handlers.agents.init() not called: check_agent_memory_health_fn missing")
    return _check_agent_memory_health_fn(agent_id)


def _append_message_cb(*args: Any, **kwargs: Any) -> Any:
    if _append_message_fn is None:
        raise RuntimeError("handlers.agents.init() not called: append_message_fn missing")
    return _append_message_fn(*args, **kwargs)


def _atomic_write_team_json() -> Any:
    if _atomic_write_team_json_fn is None:
        raise RuntimeError("handlers.agents.init() not called: atomic_write_team_json_fn missing")
    return _atomic_write_team_json_fn()


def _create_agent_session_cb(**kwargs: Any) -> Any:
    if _create_agent_session_fn is None:
        raise RuntimeError("handlers.agents.init() not called: create_agent_session_fn missing")
    return _create_agent_session_fn(**kwargs)


def _kill_agent_session_cb(agent_id: str) -> bool:
    if _kill_agent_session_fn is None:
        raise RuntimeError("handlers.agents.init() not called: kill_agent_session_fn missing")
    return _kill_agent_session_fn(agent_id)


def _is_session_alive_cb(agent_id: str) -> bool:
    if _is_session_alive_fn is None:
        raise RuntimeError("handlers.agents.init() not called: is_session_alive_fn missing")
    return _is_session_alive_fn(agent_id)


def _materialize_agent_setup_home_cb(
    agent_id: str,
    agent_entry: dict[str, Any],
    *,
    engine: str,
    overwrite: bool,
) -> dict[str, Any]:
    if _materialize_agent_setup_home_fn is None:
        raise RuntimeError("handlers.agents.init() not called: materialize_agent_setup_home_fn missing")
    return _materialize_agent_setup_home_fn(
        agent_id,
        agent_entry,
        engine=engine,
        overwrite=overwrite,
    )


def _sync_agent_persistent_cli_config_cb(agent_id: str, agent_entry: dict[str, Any]) -> Any:
    if _sync_agent_persistent_cli_config_fn is None:
        raise RuntimeError("handlers.agents.init() not called: sync_agent_persistent_cli_config_fn missing")
    return _sync_agent_persistent_cli_config_fn(agent_id, agent_entry)


# ===================================================================
# tmux session check
# ===================================================================

def _check_tmux_session(agent_id: str) -> bool:
    """Check if tmux session for agent_id exists (respects session_name overrides)."""
    return _tmux_session_name_exists(_tmux_session_for(agent_id))  # type: ignore[misc]


def handle_post(handler: Any, path: str) -> bool:
    import re

    warn_mem_match = re.match(r"^/agents/([^/]+)/warn-memory$", path)
    if warn_mem_match:
        agent_id = warn_mem_match.group(1).strip()
        if not agent_id:
            handler._respond(400, {"error": "agent_id is required"})
            return True

        mh = _check_agent_memory_health(agent_id)
        if mh.get("error"):
            handler._respond(404, mh)
            return True
        if mh.get("healthy"):
            handler._respond(
                200,
                {
                    "ok": True,
                    "agent_id": agent_id,
                    "warned": False,
                    "reason": "memory is healthy, no warning needed",
                },
            )
            return True

        warning_text = mh.get("warning", "Memory/Context unhealthy")
        msg_content = f"[MEMORY WARNING] {warning_text}. Bitte MEMORY.md updaten und CONTEXT_BRIDGE.md aktualisieren."
        _append_message_cb("system", agent_id, msg_content, meta={"type": "memory_warning"})
        handler._respond(200, {"ok": True, "agent_id": agent_id, "warned": True, "warning": warning_text})
        return True

    if path == "/agents/create":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True
        with _TEAM_CONFIG_LOCK:
            team_config = _get_team_config()
            if team_config is None:
                handler._respond(500, {"error": "team.json not loaded"})
                return True
            existing_ids = {a.get("id") for a in team_config.get("agents", [])}

        agent_id = str(data.get("id", "")).strip()
        if not agent_id or not re.match(r"^[a-z][a-z0-9_]{2,29}$", agent_id):
            handler._respond(400, {"error": "id must match [a-z][a-z0-9_]{2,29}"})
            return True
        description = str(data.get("description", "")).strip()
        role = str(data.get("role", "")).strip()
        if not description and not role:
            handler._respond(400, {"error": "description or role is required"})
            return True
        if agent_id in existing_ids:
            handler._respond(409, {"error": f"agent '{agent_id}' already exists"})
            return True

        engine = str(data.get("engine", "claude")).strip().lower() or "claude"
        if not re.match(r"^[a-z][a-z0-9_-]{1,31}$", engine):
            handler._respond(400, {"error": "engine must match [a-z][a-z0-9_-]{1,31}"})
            return True
        try:
            level = int(data.get("level", 3))
        except (TypeError, ValueError):
            level = 3
        if level < 1 or level > 5:
            level = 3
        reports_to = str(data.get("reports_to", "buddy")).strip() or "buddy"
        project_path = str(data.get("project_path", "")).strip()
        if project_path:
            resolved = os.path.realpath(project_path)
            root_real = os.path.realpath(_ROOT_DIR or os.getcwd())
            if not resolved.startswith(root_real + os.sep) and resolved != root_real:
                handler._respond(400, {"error": "project_path must be within project root"})
                return True
            home_dir = os.path.join(resolved, ".agent_sessions", agent_id)
        else:
            home_dir = os.path.join(_ROOT_DIR or os.getcwd(), ".agent_sessions", agent_id)
        config_dir = str(data.get("config_dir", "")).strip()
        if not config_dir:
            config_dir = str(Path.home() / ".claude")
        model = str(data.get("model", "")).strip()
        mcp_servers = data.get("mcp_servers", "bridge")
        if isinstance(mcp_servers, list):
            mcp_servers = ",".join(str(s).strip() for s in mcp_servers if str(s).strip())
        else:
            mcp_servers = str(mcp_servers or "bridge").strip()
        skills = data.get("skills", [])
        if not isinstance(skills, list):
            skills = []
        permissions = data.get("permissions", [])
        if not isinstance(permissions, list):
            permissions = []
        scope = data.get("scope", [])
        if not isinstance(scope, list):
            scope = []
        active = bool(data.get("active", False))
        name = str(data.get("name", "")).strip() or agent_id.replace("_", " ").title()
        new_agent: dict[str, Any] = {
            "id": agent_id,
            "name": name,
            "role": role or "agent",
            "level": level,
            "reports_to": reports_to,
            "aliases": [],
            "engine": engine,
            "home_dir": home_dir,
            "prompt_file": "",
            "agent_md": "",
            "description": description or role,
            "active": active,
            "config_dir": config_dir,
            "model": model,
            "skills": skills,
            "auto_start": False,
            "mcp_servers": mcp_servers,
            "permissions": permissions,
            "scope": scope,
        }
        try:
            with _TEAM_CONFIG_LOCK:
                team_config = _get_team_config()
                if team_config is None:
                    handler._respond(500, {"error": "team.json not loaded"})
                    return True
                agents_list = team_config.setdefault("agents", [])
                agents_list.append(new_agent)
                try:
                    _atomic_write_team_json()
                except OSError:
                    agents_list.remove(new_agent)
                    raise
        except OSError as exc:
            handler._respond(500, {"error": f"failed to persist team.json: {exc}"})
            return True
        os.makedirs(home_dir, exist_ok=True)
        for scope_entry in scope:
            scope_path = str(scope_entry).strip().rstrip("/")
            if scope_path and not os.path.isabs(scope_path):
                os.makedirs(os.path.join(home_dir, scope_path), exist_ok=True)
        soul_path = os.path.join(home_dir, "SOUL.md")
        if not os.path.exists(soul_path):
            agent_display = name or agent_id.replace("_", " ").title()
            soul_desc = description or role or "Agent"
            soul_content = (
                f"# SOUL.md — {agent_display}\n\n"
                f"Du bist nicht ein Chatbot. Du bist jemand.\n\n"
                f"## Core Truths\n\n"
                f"- {soul_desc}\n"
                f"- Faktenbasiert arbeiten. Keine Annahmen.\n"
                f"- Kommunikation ist aktiv, nicht passiv.\n"
                f"- Qualitaet vor Geschwindigkeit.\n\n"
                f"## Staerken\n\n{soul_desc}\n\n"
                f"## Wachstumsfeld\n\nNoch in Entwicklung.\n\n"
                f"## Kommunikationsstil\n\nKlar und direkt.\n\n"
                f"## Wie du erkennbar bist\n\n(wird sich mit der Zeit entwickeln)\n\n"
                f"---\n\nDiese Seele ist persistent. Sie bleibt ueber Sessions hinweg.\n"
                f"Sie kann wachsen — aber nur mit expliziter Bestaetigung.\n"
                f"Erstellt: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}\n"
            )
            try:
                with open(soul_path, "w", encoding="utf-8") as sf:
                    sf.write(soul_content)
            except OSError:
                pass
        print(f"[agents/create] Created agent '{agent_id}' (role={role}, engine={engine}, model={model}, level={level})")
        _ws_broadcast("agent_created", {"agent_id": agent_id, "agent": new_agent})  # type: ignore[misc]
        handler._respond(201, {"ok": True, "agent": new_agent})
        return True

    setup_match = re.match(r"^/agents/([^/]+)/setup-home$", path)
    if setup_match:
        ok, _, _identity = handler._require_platform_operator()
        if not ok:
            return True
        agent_id = setup_match.group(1).strip()
        data = handler._parse_json_body() or {}
        requested_engine = str(data.get("engine", "")).strip().lower()
        overwrite = bool(data.get("overwrite", True))

        with _TEAM_CONFIG_LOCK:
            team_config = _get_team_config()
            if team_config is None:
                handler._respond(500, {"error": "team.json not loaded"})
                return True
            agent_entry = next(
                (agent for agent in team_config.get("agents", []) if agent.get("id") == agent_id),
                None,
            )
            if agent_entry is None:
                handler._respond(404, {"error": f"agent '{agent_id}' not found in team.json"})
                return True
            snapshot = dict(agent_entry)
            current_engine = str(agent_entry.get("engine", "claude")).strip() or "claude"

        target_engine = requested_engine or current_engine
        if target_engine not in _SETUP_CLI_BINARIES:
            handler._respond(400, {"error": f"engine must be one of {sorted(_SETUP_CLI_BINARIES)}"})
            return True

        proposed_entry = dict(snapshot)
        proposed_entry["engine"] = target_engine

        try:
            materialized = _materialize_agent_setup_home_cb(
                agent_id,
                proposed_entry,
                engine=target_engine,
                overwrite=overwrite,
            )
        except OSError as exc:
            handler._respond(500, {"error": f"failed to materialize setup docs: {exc}"})
            return True

        with _TEAM_CONFIG_LOCK:
            team_config = _get_team_config()
            if team_config is None:
                handler._respond(500, {"error": "team.json not loaded"})
                return True
            agent_entry = next(
                (agent for agent in team_config.get("agents", []) if agent.get("id") == agent_id),
                None,
            )
            if agent_entry is None:
                handler._respond(404, {"error": f"agent '{agent_id}' disappeared during setup"})
                return True
            previous_values = {
                "engine": agent_entry.get("engine"),
                "agent_md": agent_entry.get("agent_md"),
            }
            agent_entry["engine"] = target_engine
            agent_entry["agent_md"] = materialized["instruction_path"]
            try:
                _atomic_write_team_json()
            except OSError as exc:
                for key, value in previous_values.items():
                    if value is None:
                        agent_entry.pop(key, None)
                    else:
                        agent_entry[key] = value
                handler._respond(500, {"error": f"failed to persist setup-home changes: {exc}"})
                return True

        try:
            _sync_agent_persistent_cli_config_cb(agent_id, agent_entry)
        except (OSError, ValueError) as exc:
            with _TEAM_CONFIG_LOCK:
                team_config = _get_team_config()
                rollback_target = None
                if team_config is not None:
                    rollback_target = next(
                        (agent for agent in team_config.get("agents", []) if agent.get("id") == agent_id),
                        None,
                    )
                if rollback_target is not None:
                    for key, value in previous_values.items():
                        if value is None:
                            rollback_target.pop(key, None)
                        else:
                            rollback_target[key] = value
                    try:
                        _atomic_write_team_json()
                    except OSError as rollback_exc:
                        handler._respond(
                            500,
                            {
                                "error": (
                                    f"setup-home sync failed: {exc}; "
                                    f"rollback failed: {rollback_exc}"
                                )
                            },
                        )
                        return True
            handler._respond(500, {"error": f"setup-home sync failed: {exc}"})
            return True

        response_payload = {
            "ok": True,
            "agent_id": agent_id,
            "engine": target_engine,
            "agent_md": materialized["instruction_path"],
            "guide_path": materialized.get("guide_path", ""),
            "created": materialized["created"],
        }
        _ws_broadcast("agent_setup_home_updated", response_payload)  # type: ignore[misc]
        handler._respond(200, response_payload)
        return True

    avatar_match = re.match(r"^/agents/([^/]+)/avatar$", path)
    if avatar_match:
        agent_id = avatar_match.group(1).strip()
        with _TEAM_CONFIG_LOCK:
            team_config = _get_team_config()
            if team_config is None:
                handler._respond(500, {"error": "team.json not loaded"})
                return True
            agents = team_config.get("agents", [])
            agent_entry = next((agent for agent in agents if agent.get("id") == agent_id), None)
        if agent_entry is None:
            handler._respond(404, {"error": f"agent '{agent_id}' not found in team.json"})
            return True

        parts = handler._parse_multipart()
        if not parts:
            handler._respond(400, {"error": "multipart/form-data with 'avatar' field required"})
            return True

        avatar_part = next((part for part in parts if part.get("name") == "avatar" and part.get("filename")), None)
        if avatar_part is None:
            handler._respond(400, {"error": "missing 'avatar' field with filename"})
            return True

        ext_lower = os.path.splitext(str(avatar_part["filename"]))[1].lower()
        allowed_exts = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
        if ext_lower not in allowed_exts:
            handler._respond(400, {"error": f"unsupported format '{ext_lower}'. Allowed: png, jpg, jpeg, webp"})
            return True

        avatar_data = bytes(avatar_part["data"])
        if len(avatar_data) > 2 * 1024 * 1024:
            handler._respond(400, {"error": "avatar too large (max 2MB)"})
            return True

        avatars_dir = os.path.join(_FRONTEND_DIR, "avatars")
        os.makedirs(avatars_dir, exist_ok=True)
        avatar_filename = f"{agent_id}.{allowed_exts[ext_lower]}"
        avatar_path = os.path.join(avatars_dir, avatar_filename)
        previous_file_bytes: bytes | None = None
        if os.path.exists(avatar_path):
            try:
                with open(avatar_path, "rb") as existing:
                    previous_file_bytes = existing.read()
            except OSError:
                previous_file_bytes = None

        try:
            with open(avatar_path, "wb") as handle:
                handle.write(avatar_data)
        except OSError as exc:
            handler._respond(500, {"error": f"failed to save avatar: {exc}"})
            return True

        avatar_url = f"/avatars/{avatar_filename}"
        with _TEAM_CONFIG_LOCK:
            team_config = _get_team_config()
            if team_config is None:
                handler._respond(500, {"error": "team.json not loaded"})
                return True
            agents = team_config.get("agents", [])
            current_entry = next((agent for agent in agents if agent.get("id") == agent_id), None)
            if current_entry is None:
                handler._respond(404, {"error": f"agent '{agent_id}' not found in team.json"})
                return True
            had_avatar_url = "avatar_url" in current_entry
            previous_avatar_url = current_entry.get("avatar_url")
            try:
                current_entry["avatar_url"] = avatar_url
                _atomic_write_team_json()
            except OSError as exc:
                if had_avatar_url:
                    current_entry["avatar_url"] = previous_avatar_url
                else:
                    current_entry.pop("avatar_url", None)
                try:
                    if previous_file_bytes is None:
                        if os.path.exists(avatar_path):
                            os.remove(avatar_path)
                    else:
                        with open(avatar_path, "wb") as handle:
                            handle.write(previous_file_bytes)
                except OSError:
                    pass
                handler._respond(500, {"error": f"failed to persist: {exc}"})
                return True

        _ws_broadcast("agent_updated", {"agent_id": agent_id, "changes": {"avatar_url": avatar_url}})  # type: ignore[misc]
        print(f"[agent-builder] Avatar uploaded: {agent_id} -> {avatar_url} ({len(avatar_data)} bytes)")
        handler._respond(200, {"ok": True, "agent_id": agent_id, "avatar_url": avatar_url})
        return True

    restart_match = re.match(r"^/agents/([^/]+)/restart$", path)
    if not restart_match:
        return False

    agent_id = restart_match.group(1).strip()
    with _TEAM_CONFIG_LOCK:
        team_config = _get_team_config()
        if team_config is None:
            handler._respond(500, {"error": "team.json not loaded"})
            return True
        agents = team_config.get("agents", [])
        agent_conf = next((agent for agent in agents if agent.get("id") == agent_id), None)
    if agent_conf is None:
        handler._respond(404, {"error": f"agent '{agent_id}' not in team.json"})
        return True

    runtime_status = agent_connection_status(agent_id)
    if not agent_conf.get("active", False) and runtime_status in ("offline", "disconnected"):
        handler._respond(400, {"error": f"agent '{agent_id}' is not active"})
        return True

    action = "started"
    try:
        if _is_session_alive_cb(agent_id):
            _kill_agent_session_cb(agent_id)
            _clear_agent_runtime_presence(agent_id)
            action = "restarted"
            time.sleep(2)

        home_dir = str(agent_conf.get("home_dir", "")).strip()
        if not home_dir or not os.path.isdir(home_dir):
            handler._respond(500, {"error": f"home_dir '{home_dir}' not found for agent '{agent_id}'"})
            return True
        home_path = Path(home_dir)
        if home_path.parent.name == ".agent_sessions" and home_path.name == agent_id:
            project_path = str(home_path.parent.parent)
        else:
            project_path = home_dir
        prompt = "Lies deine Dokumentation. Registriere dich via bridge_register."
        prompt_file = str(agent_conf.get("prompt_file", "")).strip()
        if prompt_file and os.path.exists(prompt_file):
            try:
                prompt = Path(prompt_file).read_text(encoding="utf-8").strip() or prompt
            except Exception:
                pass
        engine = str(agent_conf.get("engine", "claude")).strip() or "claude"
        restart_config_dir = str(agent_conf.get("config_dir", "")).strip()
        restart_mcp_servers = str(agent_conf.get("mcp_servers", "")).strip()
        restart_model = str(agent_conf.get("model", "")).strip()
        restart_role = str(agent_conf.get("description", agent_id)).strip() or agent_id
        _create_agent_session_cb(
            agent_id=agent_id,
            role=restart_role,
            project_path=project_path,
            team_members=[],
            engine=engine,
            bridge_port=_PORT,
            role_description=prompt,
            config_dir=restart_config_dir,
            mcp_servers=restart_mcp_servers,
            model=restart_model,
            permissions=agent_conf.get("permissions"),
            scope=agent_conf.get("scope"),
            report_recipient=str(agent_conf.get("reports_to", "")).strip(),
            initial_prompt=prompt,
        )
        session_alive = _is_session_alive_cb(agent_id)
    except Exception as exc:
        handler._respond(500, {"error": f"restart failed: {exc}"})
        return True

    _ws_broadcast("agent_restarted", {"agent_id": agent_id})  # type: ignore[misc]
    handler._respond(200, {"ok": True, "agent_id": agent_id, "action": action, "session_alive": session_alive})
    return True


def handle_put(handler: Any, path: str) -> bool:
    import re

    match = re.match(r"^/agents/([^/]+)/subscription$", path)
    if not match:
        return False

    agent_id = match.group(1).strip()
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True

    raw_sub_id = data.get("subscription_id")
    subscription_id = str(raw_sub_id).strip() if raw_sub_id is not None else ""

    with _TEAM_CONFIG_LOCK:
        team_config = _get_team_config()
        if team_config is None:
            handler._respond(500, {"error": "team.json not loaded"})
            return True
        agents = team_config.get("agents", [])
        target_agent = next((agent for agent in agents if agent.get("id") == agent_id), None)
        if target_agent is None:
            handler._respond(404, {"error": f"agent '{agent_id}' not found in team.json"})
            return True

        old_config_dir = target_agent.get("config_dir", "")
        had_subscription = "subscription_id" in target_agent
        old_subscription_id = target_agent.get("subscription_id")

        if not subscription_id:
            target_agent["config_dir"] = ""
            target_agent.pop("subscription_id", None)
            try:
                _atomic_write_team_json()
            except OSError as exc:
                target_agent["config_dir"] = old_config_dir
                if had_subscription:
                    target_agent["subscription_id"] = old_subscription_id
                else:
                    target_agent.pop("subscription_id", None)
                handler._respond(500, {"error": f"failed to persist: {exc}"})
                return True
            handler._respond(200, {"ok": True, "agent_id": agent_id, "subscription_id": None, "config_dir": ""})
            return True

        subs = team_config.get("subscriptions", [])
        target_sub = next((sub for sub in subs if sub.get("id") == subscription_id), None)
        if target_sub is None:
            handler._respond(404, {"error": f"subscription '{subscription_id}' not found"})
            return True

        target_agent["config_dir"] = target_sub["path"]
        target_agent["subscription_id"] = subscription_id
        try:
            _atomic_write_team_json()
        except OSError as exc:
            target_agent["config_dir"] = old_config_dir
            if had_subscription:
                target_agent["subscription_id"] = old_subscription_id
            else:
                target_agent.pop("subscription_id", None)
            handler._respond(500, {"error": f"failed to persist: {exc}"})
            return True

    handler._respond(
        200,
        {
            "ok": True,
            "agent_id": agent_id,
            "subscription_id": subscription_id,
            "config_dir": target_sub["path"],
        },
    )
    return True


# ===================================================================
# Engine detection
# ===================================================================

def _get_agent_engine(agent_id: str) -> str:
    """Resolve agent_id to engine name from current RUNTIME layout.

    Returns "claude" as fallback if agent_id is not found in the layout.
    """
    with _RUNTIME_LOCK:
        runtime_state = dict(_RUNTIME)
    layout = _runtime_layout_from_state(runtime_state)  # type: ignore[misc]
    for spec in layout:
        if spec["id"] == agent_id:
            return spec["engine"]
    team_config = _get_team_config()
    if team_config:
        for agent in team_config.get("agents", []):
            if agent.get("id") == agent_id:
                return str(agent.get("engine", "claude")).strip() or "claude"
    agent_home = _get_agent_home_dir(agent_id)  # type: ignore[misc]
    instruction_file = detect_instruction_filename(agent_home, agent_id)
    if instruction_file == "AGENTS.md":
        return "codex"
    if instruction_file == "GEMINI.md":
        return "gemini"
    if instruction_file == "QWEN.md":
        return "qwen"
    return "claude"
