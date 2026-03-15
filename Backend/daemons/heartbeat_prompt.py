from __future__ import annotations

import time
from typing import Any, Callable

_HEARTBEAT_PROMPT_INTERVAL = 300

# Agents that should NOT receive HEARTBEAT_CHECK (noise reduction).
# Concierge/buddy agents, non-Claude engines, and agents with limited
# context windows shouldn't be interrupted by periodic checks.
_HEARTBEAT_EXCLUDE_ROLES = {"concierge", "legal"}

_graceful_shutdown_lock: Any = None
_graceful_shutdown: dict[str, Any] | None = None
_system_status: dict[str, Any] | None = None
_agent_state_lock: Any = None
_registered_agents: dict[str, dict[str, Any]] | None = None
_agent_is_live_cb: Callable[..., bool] | None = None
_append_message_cb: Callable[..., Any] | None = None
_team_config: dict[str, Any] | None = None
_team_config_getter: Callable[[], dict[str, Any] | None] | None = None


def init(
    *,
    graceful_shutdown_lock: Any,
    graceful_shutdown: dict[str, Any],
    system_status: dict[str, Any],
    agent_state_lock: Any,
    registered_agents: dict[str, dict[str, Any]],
    agent_is_live: Callable[..., bool],
    append_message: Callable[..., Any],
    team_config: dict[str, Any] | None = None,
    team_config_getter: Callable[[], dict[str, Any] | None] | None = None,
) -> None:
    global _graceful_shutdown_lock, _graceful_shutdown, _system_status
    global _agent_state_lock, _registered_agents, _agent_is_live_cb, _append_message_cb
    global _team_config, _team_config_getter

    _graceful_shutdown_lock = graceful_shutdown_lock
    _graceful_shutdown = graceful_shutdown
    _system_status = system_status
    _agent_state_lock = agent_state_lock
    _registered_agents = registered_agents
    _agent_is_live_cb = agent_is_live
    _append_message_cb = append_message
    _team_config = team_config
    _team_config_getter = team_config_getter


def _heartbeat_prompt_tick() -> list[str]:
    if (
        _graceful_shutdown_lock is None
        or _graceful_shutdown is None
        or _system_status is None
        or _agent_state_lock is None
        or _registered_agents is None
        or _agent_is_live_cb is None
        or _append_message_cb is None
    ):
        raise RuntimeError("daemons.heartbeat_prompt not initialized")

    with _graceful_shutdown_lock:
        if _graceful_shutdown.get("pending"):
            return []

    if _system_status.get("shutdown_active"):
        return []

    # Build exclude set from team.json roles
    exclude_agents: set[str] = set()
    tc = _team_config_getter() if _team_config_getter else _team_config
    if tc:
        for agent_def in tc.get("agents", []):
            agent_role = (agent_def.get("role") or "").lower()
            agent_engine = (agent_def.get("engine") or "").lower()
            if agent_role in _HEARTBEAT_EXCLUDE_ROLES:
                exclude_agents.add(agent_def.get("id", ""))
            # Non-Claude engines (codex, qwen, gemini) don't benefit from heartbeat checks
            if agent_engine in ("codex", "qwen", "gemini"):
                exclude_agents.add(agent_def.get("id", ""))

    with _agent_state_lock:
        online_agents = [
            aid for aid, reg in _registered_agents.items()
            if reg and _agent_is_live_cb(aid, stale_seconds=120.0, reg=reg)
            and aid not in exclude_agents
        ]

    for aid in online_agents:
        _append_message_cb(
            "system",
            aid,
            "[HEARTBEAT_CHECK] Periodische Pruefung. Bitte checke: "
            "1) Bin ich auf meiner Aufgabe? "
            "2) Habe ich ungelesene Nachrichten? "
            "3) Gibt es offene Tasks in der Queue? "
            "4) Ist mein Memory aktuell? "
            "5) Sende das Ergebnis NUR an system, NICHT an user.",
            meta={"type": "heartbeat_check"},
        )

    return online_agents


def _heartbeat_prompt_loop() -> None:
    time.sleep(300)
    while True:
        time.sleep(_HEARTBEAT_PROMPT_INTERVAL)
        try:
            online_agents = _heartbeat_prompt_tick()
            if online_agents:
                print(f"[heartbeat-prompt] Sent check to {len(online_agents)} agents: {online_agents}")
        except Exception as exc:
            print(f"[heartbeat-prompt] Error: {exc}")
