from __future__ import annotations

import threading
import time
from typing import Any, Callable

_DISTILLATION_INITIAL_DELAY = 600
_DISTILLATION_INTERVAL = 4 * 3600  # 4 hours
_DISTILLATION_PROMPT = (
    "[AUTO-DISTILLATION] Periodische Wissens-Destillation. "
    "Pruefe dein MEMORY.md und deine Erfahrungen seit der letzten Reflexion. "
    "Rufe bridge_reflect() auf. Extrahiere wichtige Patterns mit bridge_lesson_add(). "
    "Schlage Verbesserungen vor mit bridge_growth_propose()."
)

_system_shutdown_active_cb: Callable[[], bool] | None = None
_agent_state_lock: threading.Lock | None = None
_registered_agents: dict[str, Any] | None = None
_agent_is_live_cb: Callable[..., bool] | None = None
_append_message_cb: Callable[..., Any] | None = None


def init(
    *,
    system_shutdown_active: Callable[[], bool],
    agent_state_lock: threading.Lock,
    registered_agents: dict[str, Any],
    agent_is_live: Callable[..., bool],
    append_message: Callable[..., Any],
) -> None:
    global _system_shutdown_active_cb, _agent_state_lock, _registered_agents
    global _agent_is_live_cb, _append_message_cb

    _system_shutdown_active_cb = system_shutdown_active
    _agent_state_lock = agent_state_lock
    _registered_agents = registered_agents
    _agent_is_live_cb = agent_is_live
    _append_message_cb = append_message


def _distillation_tick() -> list[str]:
    if (
        _system_shutdown_active_cb is None
        or _agent_state_lock is None
        or _registered_agents is None
        or _agent_is_live_cb is None
        or _append_message_cb is None
    ):
        raise RuntimeError("daemons.distillation not initialized")

    if _system_shutdown_active_cb():
        return []

    with _agent_state_lock:
        online_agents = [
            aid for aid, reg in _registered_agents.items()
            if reg and _agent_is_live_cb(aid, stale_seconds=120.0, reg=reg)
        ]

    for aid in online_agents:
        try:
            _append_message_cb("system", aid, _DISTILLATION_PROMPT, meta={"type": "distillation_trigger"})
        except Exception:
            pass
    if online_agents:
        print(f"[distillation] Auto-distillation triggered for {len(online_agents)} agents: {online_agents}")
    return online_agents


def _distillation_daemon_loop() -> None:
    """Background thread: periodically prompt agents for knowledge distillation."""
    time.sleep(_DISTILLATION_INITIAL_DELAY)
    while True:
        time.sleep(_DISTILLATION_INTERVAL)
        try:
            _distillation_tick()
        except Exception as exc:
            print(f"[distillation] Error: {exc}")
