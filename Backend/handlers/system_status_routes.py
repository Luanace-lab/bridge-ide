"""Read-only system/restart status route extraction from server.py."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Callable


_RESTART_STATE_GETTER: Callable[[], dict[str, Any]] | None = None
_RESTART_LOCK: Any = None
_GRACEFUL_SHUTDOWN_GETTER: Callable[[], dict[str, Any]] | None = None
_GRACEFUL_SHUTDOWN_LOCK: Any = None
_SYSTEM_STATUS_GETTER: Callable[[], dict[str, Any]] | None = None
_START_TS_GETTER: Callable[[], float] | None = None
_TEAM_CONFIG_GETTER: Callable[[], dict[str, Any] | None] | None = None
_REGISTERED_AGENTS_GETTER: Callable[[], dict[str, Any]] | None = None
_AGENT_IS_LIVE_FN: Callable[[str], bool] | None = None
_ROOT_DIR_FN: Callable[[], str] | None = None
_ACTIVE_AGENT_IDS_GETTER: Callable[[], list[str] | set[str]] | None = None


def init(
    *,
    restart_state_getter: Callable[[], dict[str, Any]],
    restart_lock: Any,
    graceful_shutdown_getter: Callable[[], dict[str, Any]],
    graceful_shutdown_lock: Any,
    system_status_getter: Callable[[], dict[str, Any]],
    start_ts_getter: Callable[[], float],
    team_config_getter: Callable[[], dict[str, Any] | None],
    registered_agents_getter: Callable[[], dict[str, Any]],
    agent_is_live_fn: Callable[[str], bool],
    root_dir_fn: Callable[[], str],
    active_agent_ids_getter: Callable[[], list[str] | set[str]],
) -> None:
    global _RESTART_STATE_GETTER, _RESTART_LOCK
    global _GRACEFUL_SHUTDOWN_GETTER, _GRACEFUL_SHUTDOWN_LOCK
    global _SYSTEM_STATUS_GETTER, _START_TS_GETTER
    global _TEAM_CONFIG_GETTER, _REGISTERED_AGENTS_GETTER, _AGENT_IS_LIVE_FN, _ROOT_DIR_FN
    global _ACTIVE_AGENT_IDS_GETTER
    _RESTART_STATE_GETTER = restart_state_getter
    _RESTART_LOCK = restart_lock
    _GRACEFUL_SHUTDOWN_GETTER = graceful_shutdown_getter
    _GRACEFUL_SHUTDOWN_LOCK = graceful_shutdown_lock
    _SYSTEM_STATUS_GETTER = system_status_getter
    _START_TS_GETTER = start_ts_getter
    _TEAM_CONFIG_GETTER = team_config_getter
    _REGISTERED_AGENTS_GETTER = registered_agents_getter
    _AGENT_IS_LIVE_FN = agent_is_live_fn
    _ROOT_DIR_FN = root_dir_fn
    _ACTIVE_AGENT_IDS_GETTER = active_agent_ids_getter


def _restart_state() -> dict[str, Any]:
    if _RESTART_STATE_GETTER is None:
        raise RuntimeError("handlers.system_status_routes.init() not called: restart_state_getter missing")
    return _RESTART_STATE_GETTER()


def _graceful_shutdown() -> dict[str, Any]:
    if _GRACEFUL_SHUTDOWN_GETTER is None:
        raise RuntimeError(
            "handlers.system_status_routes.init() not called: graceful_shutdown_getter missing"
        )
    return _GRACEFUL_SHUTDOWN_GETTER()


def _system_status() -> dict[str, Any]:
    if _SYSTEM_STATUS_GETTER is None:
        raise RuntimeError("handlers.system_status_routes.init() not called: system_status_getter missing")
    return _SYSTEM_STATUS_GETTER()


def _start_ts() -> float:
    if _START_TS_GETTER is None:
        raise RuntimeError("handlers.system_status_routes.init() not called: start_ts_getter missing")
    return _START_TS_GETTER()


def _team_config() -> dict[str, Any] | None:
    if _TEAM_CONFIG_GETTER is None:
        raise RuntimeError("handlers.system_status_routes.init() not called: team_config_getter missing")
    return _TEAM_CONFIG_GETTER()


def _registered_agents() -> dict[str, Any]:
    if _REGISTERED_AGENTS_GETTER is None:
        raise RuntimeError("handlers.system_status_routes.init() not called: registered_agents_getter missing")
    return _REGISTERED_AGENTS_GETTER()


def _agent_is_live(agent_id: str) -> bool:
    if _AGENT_IS_LIVE_FN is None:
        raise RuntimeError("handlers.system_status_routes.init() not called: agent_is_live_fn missing")
    return _AGENT_IS_LIVE_FN(agent_id)


def _root_dir() -> str:
    if _ROOT_DIR_FN is None:
        raise RuntimeError("handlers.system_status_routes.init() not called: root_dir_fn missing")
    return _ROOT_DIR_FN()


def _active_agent_ids() -> list[str] | set[str]:
    if _ACTIVE_AGENT_IDS_GETTER is None:
        raise RuntimeError(
            "handlers.system_status_routes.init() not called: active_agent_ids_getter missing"
        )
    return _ACTIVE_AGENT_IDS_GETTER()


def _tmux_running(name: str) -> bool:
    return subprocess.run(["tmux", "has-session", "-t", name], capture_output=True).returncode == 0


def _pid_alive(pid_file: str) -> bool:
    try:
        pid_path = os.path.join(_root_dir(), "Backend", "pids", pid_file)
        with open(pid_path, "r", encoding="utf-8") as handle:
            pid = int(handle.read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path == "/server/restart-status":
        with _RESTART_LOCK:
            state = _restart_state()
            phase = state["phase"]
            started_at = state["started_at"]
            reason = state["reason"]
            checkpoints = dict(state["checkpoints"])
            warn_seconds = state["warn_seconds"]
            stop_seconds = state["stop_seconds"]
            agents_mode = state.get("agents_mode", "restart")

        active = sorted(_active_agent_ids())
        missing = sorted(set(active) - set(checkpoints.keys()))

        remaining = 0
        if phase and started_at:
            try:
                from datetime import datetime, timezone

                started = datetime.fromisoformat(started_at)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if phase == "warn":
                    remaining = max(0, warn_seconds - elapsed)
                elif phase == "stop":
                    remaining = max(0, stop_seconds - elapsed)
            except (ValueError, TypeError):
                pass

        handler._respond(
            200,
            {
                "phase": phase,
                "started_at": started_at,
                "reason": reason,
                "remaining_seconds": round(remaining, 1),
                "agents_mode": agents_mode,
                "checkpoints": checkpoints,
                "active_agents": active,
                "missing_checkpoints": missing,
            },
        )
        return True

    if path == "/system/status":
        handler._respond(200, {"system": _system_status()})
        return True

    if path == "/system/shutdown-status":
        with _GRACEFUL_SHUTDOWN_LOCK:
            graceful = dict(_graceful_shutdown())
            graceful["acked_agents"] = list(graceful["acked_agents"])
            graceful["expected_agents"] = list(graceful["expected_agents"])
            missing = [a for a in graceful["expected_agents"] if a not in graceful["acked_agents"]]
        graceful["missing_agents"] = missing
        handler._respond(200, {"graceful_shutdown": graceful, "system": _system_status()})
        return True

    if path == "/platform/status":
        agent_statuses: list[dict[str, Any]] = []
        team = _team_config()
        registered = _registered_agents()
        if team:
            for agent in team.get("agents", []):
                if not agent.get("active", False):
                    continue
                agent_id = agent.get("id", "")
                running = _tmux_running(f"acw_{agent_id}")
                online = agent_id in registered and _agent_is_live(agent_id)
                agent_statuses.append(
                    {
                        "id": agent_id,
                        "engine": agent.get("engine", "claude"),
                        "tmux_running": running,
                        "bridge_online": online,
                    }
                )
        handler._respond(
            200,
            {
                "ok": True,
                "server": {"running": True, "uptime_seconds": round(time.time() - _start_ts(), 3)},
                "wrapper": {"running": _pid_alive("restart_wrapper.pid") or _pid_alive("server.pid")},
                "watcher": {"running": _pid_alive("watcher.pid")},
                "forwarder": {"running": _pid_alive("output_forwarder.pid")},
                "agents": agent_statuses,
                "system": _system_status(),
            },
        )
        return True

    return False
