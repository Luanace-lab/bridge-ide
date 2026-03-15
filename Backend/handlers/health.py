"""Health and memory-health helpers extracted from server.py (Slice 11).

This module owns:
- _check_agent_memory_health
- _compute_health

Anti-circular-import strategy:
  Shared state and cross-domain helpers are injected via init().
  This module NEVER imports from server.
  Direct imports only from: persistence_utils.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, TypeVar

from persistence_utils import context_bridge_candidates, find_agent_memory_path


# ---------------------------------------------------------------------------
# Injected shared state (set by init())
# ---------------------------------------------------------------------------
_REGISTERED_AGENTS: dict[str, dict[str, Any]] = {}
_AGENT_STATE_LOCK: Any = None
_WS_CLIENTS: dict[Any, dict[str, str]] = {}
_MESSAGES: list[dict[str, Any]] = []

# ---------------------------------------------------------------------------
# Injected callbacks / config getters (set by init())
# ---------------------------------------------------------------------------
_get_agent_home_dir: Callable[[str], str] | None = None
_get_runtime_config_dir: Callable[[str], str] | None = None
_get_start_ts: Callable[[], float] | None = None
_get_port: Callable[[], int] | None = None
_get_ws_port: Callable[[], int] | None = None
_get_pid_dir: Callable[[], str] | None = None
_get_log_file: Callable[[], str] | None = None
_check_tmux_session: Callable[[str], bool] | None = None
_resolve_forwarder_session_name: Callable[[], str] | None = None
_tmux_session_name_exists: Callable[[str], bool] | None = None
_get_agent_context_pct: Callable[[str], int | None] | None = None
_read_pid_file: Callable[[str], int | None] | None = None
_pid_alive: Callable[[int], bool] | None = None
_pgrep: Callable[[str], int | None] | None = None
_federation_runtime_health: Callable[[], dict[str, Any]] | None = None
_log: Any = logging.getLogger("bridge.health")

_T = TypeVar("_T")


def init(
    *,
    registered_agents: dict[str, dict[str, Any]],
    agent_state_lock: Any,
    ws_clients: dict[Any, dict[str, str]],
    messages: list[dict[str, Any]],
    get_agent_home_dir_fn: Callable[[str], str],
    get_runtime_config_dir_fn: Callable[[str], str],
    get_start_ts_fn: Callable[[], float],
    get_port_fn: Callable[[], int],
    get_ws_port_fn: Callable[[], int],
    get_pid_dir_fn: Callable[[], str],
    get_log_file_fn: Callable[[], str],
    check_tmux_session_fn: Callable[[str], bool],
    resolve_forwarder_session_name_fn: Callable[[], str],
    tmux_session_name_exists_fn: Callable[[str], bool],
    get_agent_context_pct_fn: Callable[[str], int | None],
    read_pid_file_fn: Callable[[str], int | None],
    pid_alive_fn: Callable[[int], bool],
    pgrep_fn: Callable[[str], int | None],
    federation_runtime_health_fn: Callable[[], dict[str, Any]],
) -> None:
    """Bind shared state and callbacks before using module functions."""
    global _REGISTERED_AGENTS, _AGENT_STATE_LOCK, _WS_CLIENTS, _MESSAGES
    global _get_agent_home_dir, _get_runtime_config_dir
    global _get_start_ts, _get_port, _get_ws_port, _get_pid_dir, _get_log_file
    global _check_tmux_session, _resolve_forwarder_session_name, _tmux_session_name_exists
    global _get_agent_context_pct
    global _read_pid_file, _pid_alive, _pgrep
    global _federation_runtime_health

    _REGISTERED_AGENTS = registered_agents
    _AGENT_STATE_LOCK = agent_state_lock
    _WS_CLIENTS = ws_clients
    _MESSAGES = messages

    _get_agent_home_dir = get_agent_home_dir_fn
    _get_runtime_config_dir = get_runtime_config_dir_fn
    _get_start_ts = get_start_ts_fn
    _get_port = get_port_fn
    _get_ws_port = get_ws_port_fn
    _get_pid_dir = get_pid_dir_fn
    _get_log_file = get_log_file_fn
    _check_tmux_session = check_tmux_session_fn
    _resolve_forwarder_session_name = resolve_forwarder_session_name_fn
    _tmux_session_name_exists = tmux_session_name_exists_fn
    _get_agent_context_pct = get_agent_context_pct_fn
    _read_pid_file = read_pid_file_fn
    _pid_alive = pid_alive_fn
    _pgrep = pgrep_fn
    _federation_runtime_health = federation_runtime_health_fn


def _require_callback(callback: _T | None, name: str) -> _T:
    if callback is None:
        raise RuntimeError(f"handlers.health.init() not called: {name} missing")
    return callback


def _require_lock() -> Any:
    if _AGENT_STATE_LOCK is None:
        raise RuntimeError("handlers.health.init() not called: agent_state_lock missing")
    return _AGENT_STATE_LOCK


def _check_agent_memory_health(agent_id: str) -> dict[str, Any]:
    """Check memory/context health for a single agent."""
    get_agent_home_dir = _require_callback(_get_agent_home_dir, "get_agent_home_dir_fn")
    get_runtime_config_dir = _require_callback(_get_runtime_config_dir, "get_runtime_config_dir_fn")

    agent_home = get_agent_home_dir(agent_id)
    if not agent_home:
        return {"error": f"agent '{agent_id}' has no home_dir"}

    result: dict[str, Any] = {"agent_id": agent_id}
    now = time.time()

    has_memory = False
    memory_size = 0
    config_dir = get_runtime_config_dir(agent_id)
    result["config_dir_source"] = "runtime" if config_dir else "none"
    result["config_dir"] = config_dir

    memory_path = find_agent_memory_path(agent_id, agent_home, config_dir)
    if memory_path:
        has_memory = True
        try:
            memory_size = os.path.getsize(memory_path)
        except OSError:
            pass
    result["has_memory"] = has_memory
    result["memory_path"] = memory_path
    result["memory_size"] = memory_size

    context_bridge_age_minutes = -1
    context_bridge_path = ""
    best_mtime = 0.0
    for candidate in context_bridge_candidates(agent_home, agent_id):
        try:
            if os.path.isfile(candidate):
                mtime = os.path.getmtime(candidate)
                if mtime > best_mtime:
                    best_mtime = mtime
                    context_bridge_path = candidate
        except OSError:
            pass
    if best_mtime > 0:
        context_bridge_age_minutes = round((now - best_mtime) / 60, 1)

    result["context_bridge_path"] = context_bridge_path
    result["context_bridge_age_minutes"] = context_bridge_age_minutes

    cb_fresh = 0 < context_bridge_age_minutes <= 60
    result["healthy"] = has_memory and cb_fresh
    if not has_memory:
        result["warning"] = "no MEMORY.md found"
    elif context_bridge_age_minutes < 0:
        result["warning"] = "no CONTEXT_BRIDGE.md found"
    elif context_bridge_age_minutes > 60:
        result["warning"] = f"CONTEXT_BRIDGE.md is {context_bridge_age_minutes} minutes old"

    return result


def _compute_health() -> dict[str, Any]:
    """Compute full system health status (same logic as GET /health, reusable)."""
    get_start_ts = _require_callback(_get_start_ts, "get_start_ts_fn")
    get_port = _require_callback(_get_port, "get_port_fn")
    get_ws_port = _require_callback(_get_ws_port, "get_ws_port_fn")
    get_pid_dir = _require_callback(_get_pid_dir, "get_pid_dir_fn")
    get_log_file = _require_callback(_get_log_file, "get_log_file_fn")
    check_tmux_session = _require_callback(_check_tmux_session, "check_tmux_session_fn")
    resolve_forwarder_session_name = _require_callback(
        _resolve_forwarder_session_name, "resolve_forwarder_session_name_fn"
    )
    tmux_session_name_exists = _require_callback(
        _tmux_session_name_exists, "tmux_session_name_exists_fn"
    )
    get_agent_context_pct = _require_callback(_get_agent_context_pct, "get_agent_context_pct_fn")
    read_pid_file = _require_callback(_read_pid_file, "read_pid_file_fn")
    pid_alive = _require_callback(_pid_alive, "pid_alive_fn")
    pgrep = _require_callback(_pgrep, "pgrep_fn")
    federation_runtime_health = _require_callback(
        _federation_runtime_health, "federation_runtime_health_fn"
    )
    agent_state_lock = _require_lock()

    now = time.time()
    components: dict[str, Any] = {}

    components["server"] = {
        "status": "ok",
        "uptime": round(now - get_start_ts()),
        "port": get_port(),
    }

    ws_count = len(_WS_CLIENTS)
    components["websocket"] = {
        "status": "ok" if ws_count > 0 else "warn",
        "port": get_ws_port(),
        "connections": ws_count,
    }

    agents_health: dict[str, Any] = {}
    stale_agents: list[str] = []
    with agent_state_lock:
        for agent_id, reg in _REGISTERED_AGENTS.items():
            last_hb = reg.get("last_heartbeat", 0)
            hb_age = round(now - last_hb) if last_hb else -1
            tmux_alive = check_tmux_session(agent_id)
            ctx_pct = get_agent_context_pct(agent_id) if tmux_alive else None
            if (hb_age < 0 or hb_age > 600) and not tmux_alive:
                stale_agents.append(agent_id)
                continue
            if hb_age < 0 or hb_age > 300:
                agent_status = "fail"
            elif hb_age > 60:
                agent_status = "warn"
            elif ctx_pct is not None and ctx_pct >= 90:
                agent_status = "critical" if ctx_pct >= 95 else "warn"
            else:
                agent_status = "ok"
            info: dict[str, Any] = {
                "status": agent_status,
                "last_heartbeat_age": hb_age,
                "tmux": tmux_alive,
                "role": reg.get("role", ""),
            }
            if ctx_pct is not None:
                info["context_pct"] = ctx_pct
            agents_health[agent_id] = info
        for agent_id in stale_agents:
            del _REGISTERED_AGENTS[agent_id]
            _log.info("health_check auto-cleanup: removed stale agent %s", agent_id)
    components["agents"] = agents_health

    memory_health: dict[str, Any] = {}
    for agent_id in list(agents_health.keys()):
        memory_result = _check_agent_memory_health(agent_id)
        if memory_result.get("error"):
            memory_health[agent_id] = {
                "memory_exists": False,
                "context_bridge_fresh": False,
            }
        else:
            cb_age = memory_result.get("context_bridge_age_minutes", -1)
            memory_health[agent_id] = {
                "memory_exists": memory_result.get("has_memory", False),
                "context_bridge_fresh": 0 < cb_age <= 60 if isinstance(cb_age, (int, float)) else False,
            }
            if not memory_result.get("has_memory") or not memory_health[agent_id]["context_bridge_fresh"]:
                memory_health[agent_id]["warning"] = memory_result.get("warning", "unhealthy")
    components["memory_health"] = memory_health

    pid_dir = get_pid_dir()
    watcher_pid = read_pid_file(os.path.join(pid_dir, "watcher.pid"))
    components["watcher"] = {
        "status": "ok" if watcher_pid and pid_alive(watcher_pid) else "fail",
        "pid": watcher_pid,
    }

    codex_poll_state_file = os.path.join(pid_dir, "bridge_codex_poll.json")
    try:
        if os.path.exists(codex_poll_state_file):
            with open(codex_poll_state_file, "r", encoding="utf-8") as handle:
                codex_poll = json.load(handle)
            poll_running = codex_poll.get("running", False)
            tick_age = time.time() - float(codex_poll.get("last_tick_ts", 0))
            poll_age = time.time() - float(codex_poll.get("last_poll_ts", 0))
            components["codex_poll"] = {
                "status": "ok" if poll_running and tick_age < 120 else "warn",
                "running": poll_running,
                "last_tick_age": round(tick_age, 1),
                "last_poll_age": round(poll_age, 1),
                "polls_total": codex_poll.get("polls_total", 0),
                "polls_injected": codex_poll.get("polls_injected", 0),
                "last_error": codex_poll.get("last_error", ""),
            }
        else:
            components["codex_poll"] = {"status": "warn", "running": False}
    except Exception:
        components["codex_poll"] = {"status": "warn", "running": False}

    forwarder_pid = read_pid_file(os.path.join(pid_dir, "output_forwarder.pid"))
    if not forwarder_pid or not pid_alive(forwarder_pid):
        forwarder_pid = pgrep("output_forwarder.py")
    forwarder_running = bool(forwarder_pid and pid_alive(forwarder_pid))
    forwarder_session = str(resolve_forwarder_session_name()).strip()
    forwarder_required = bool(forwarder_session) and tmux_session_name_exists(forwarder_session)
    components["forwarder"] = {
        "status": "ok" if forwarder_running or not forwarder_required else "warn",
        "pid": forwarder_pid,
        "running": forwarder_running,
        "required": forwarder_required,
        "session": forwarder_session,
    }
    if not forwarder_running and not forwarder_required:
        components["forwarder"]["reason"] = "no active manager/lead session"
    elif not forwarder_running:
        components["forwarder"]["reason"] = "forwarder missing for active manager/lead session"

    log_file = get_log_file()
    msg_writable = os.access(log_file, os.W_OK) if os.path.exists(log_file) else False
    components["messages"] = {
        "status": "ok" if msg_writable else "fail",
        "total": len(_MESSAGES),
        "file_writable": msg_writable,
    }

    federation_health = federation_runtime_health()
    federation_status = "ok" if federation_health.get("enabled") else "warn"
    if federation_health.get("reason") == "disabled by config":
        federation_status = "ok"
    relay_state = federation_health.get("relay")
    if isinstance(relay_state, dict):
        if relay_state.get("last_error"):
            federation_status = "warn"
        if relay_state.get("relay_url") and not relay_state.get("connected"):
            federation_status = "warn"
    federation_health["status"] = federation_status
    components["federation"] = federation_health

    all_statuses: list[str] = []
    for component in components.values():
        if isinstance(component, dict) and "status" in component:
            all_statuses.append(component["status"])
        elif isinstance(component, dict):
            for subcomponent in component.values():
                if isinstance(subcomponent, dict) and "status" in subcomponent:
                    all_statuses.append(subcomponent["status"])

    if "fail" in all_statuses or "critical" in all_statuses:
        overall = "critical"
    elif "warn" in all_statuses:
        overall = "degraded"
    else:
        overall = "ok"

    return {"status": overall, "components": components}
