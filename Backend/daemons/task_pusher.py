from __future__ import annotations

import time
from typing import Any, Callable

_TASK_PUSH_INTERVAL = 60

_graceful_shutdown_pending_cb: Callable[[], bool] | None = None
_system_shutdown_active_cb: Callable[[], bool] | None = None
_agent_state_lock: Any = None
_registered_agents: dict[str, dict[str, Any]] | None = None
_agent_is_live_cb: Callable[..., bool] | None = None
_task_lock: Any = None
_tasks: dict[str, dict[str, Any]] | None = None
_load_agent_state_cb: Callable[[str], dict[str, Any]] | None = None
_save_agent_state_cb: Callable[[str, dict[str, Any]], Any] | None = None
_append_message_cb: Callable[..., Any] | None = None


def init(
    *,
    graceful_shutdown_pending: Callable[[], bool],
    system_shutdown_active: Callable[[], bool],
    agent_state_lock: Any,
    registered_agents: dict[str, dict[str, Any]],
    agent_is_live: Callable[..., bool],
    task_lock: Any,
    tasks: dict[str, dict[str, Any]],
    load_agent_state: Callable[[str], dict[str, Any]],
    save_agent_state: Callable[[str, dict[str, Any]], Any],
    append_message: Callable[..., Any],
) -> None:
    global _graceful_shutdown_pending_cb, _system_shutdown_active_cb
    global _agent_state_lock, _registered_agents, _agent_is_live_cb
    global _task_lock, _tasks, _load_agent_state_cb, _save_agent_state_cb, _append_message_cb

    _graceful_shutdown_pending_cb = graceful_shutdown_pending
    _system_shutdown_active_cb = system_shutdown_active
    _agent_state_lock = agent_state_lock
    _registered_agents = registered_agents
    _agent_is_live_cb = agent_is_live
    _task_lock = task_lock
    _tasks = tasks
    _load_agent_state_cb = load_agent_state
    _save_agent_state_cb = save_agent_state
    _append_message_cb = append_message


def _task_pusher_tick() -> list[str]:
    if (
        _graceful_shutdown_pending_cb is None
        or _system_shutdown_active_cb is None
        or _agent_state_lock is None
        or _registered_agents is None
        or _agent_is_live_cb is None
        or _task_lock is None
        or _tasks is None
        or _load_agent_state_cb is None
        or _save_agent_state_cb is None
        or _append_message_cb is None
    ):
        raise RuntimeError("daemons.task_pusher not initialized")

    if _graceful_shutdown_pending_cb():
        return []
    if _system_shutdown_active_cb():
        return []

    with _agent_state_lock:
        online_agents = {
            aid for aid, reg in _registered_agents.items()
            if reg and _agent_is_live_cb(aid, stale_seconds=120.0, reg=reg)
        }
    if not online_agents:
        return []

    pending_pushes: list[tuple[str, str, str, str, str]] = []
    with _task_lock:
        for task in _tasks.values():
            assignee = task.get("assigned_to", "")
            if not assignee or assignee not in online_agents:
                continue
            if task.get("state") != "created":
                continue
            pending_pushes.append(
                (
                    assignee,
                    task.get("task_id", ""),
                    str(task.get("title", ""))[:200],
                    str(task.get("description", ""))[:300],
                    task.get("created_by", "unknown"),
                )
            )

    pushed: list[str] = []
    for assignee, task_id, title, desc, creator in pending_pushes:
        task_state = _load_agent_state_cb(assignee)
        if task_state.get("mode") == "standby":
            _save_agent_state_cb(assignee, {"mode": "normal"})
            _append_message_cb(
                "system",
                assignee,
                "[MODE CHANGE] Dein Modus wurde auf 'normal' geaendert. "
                "Arbeite aktuelle Aufgabe ab, dann warte auf Input.",
                meta={"type": "mode_change", "mode": "normal"},
            )
        _append_message_cb(
            "system",
            assignee,
            f"[AUTO-CLAIM REQUIRED] Du hast einen zugewiesenen Task der NICHT geclaimed ist:\n"
            f"Task: '{title}' (ID: {task_id})\n"
            f"Beschreibung: {desc}\n\n"
            f"SOFORT ausfuehren:\n"
            f"1. bridge_task_claim(task_id='{task_id}')\n"
            f"2. bridge_task_ack(task_id='{task_id}')\n"
            f"3. Task bearbeiten\n"
            f"4. bridge_task_done(task_id='{task_id}', result_summary='...')\n"
            f"5. Ergebnis an {creator} via bridge_send melden",
            meta={"type": "auto_claim_push", "task_id": task_id},
        )
        pushed.append(task_id)

    return pushed


def _idle_agent_task_pusher() -> None:
    time.sleep(30)
    while True:
        time.sleep(_TASK_PUSH_INTERVAL)
        try:
            pushed = _task_pusher_tick()
            if pushed:
                print(f"[task-pusher] Pushed {len(pushed)} unclaimed task(s) to idle agents")
        except Exception as exc:
            print(f"[task-pusher] Error: {exc}")
