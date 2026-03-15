from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

_AUTO_ASSIGN_INTERVAL = 120

_graceful_shutdown_pending_cb: Callable[[], bool] | None = None
_system_shutdown_active_cb: Callable[[], bool] | None = None
_agent_state_lock: Any = None
_registered_agents: dict[str, dict[str, Any]] | None = None
_agent_is_live_cb: Callable[..., bool] | None = None
_load_agent_state_cb: Callable[[str], dict[str, Any]] | None = None
_agent_activities: dict[str, dict[str, Any]] | None = None
_task_lock: Any = None
_tasks: dict[str, dict[str, Any]] | None = None
_persist_tasks_cb: Callable[[], None] | None = None
_append_message_cb: Callable[..., Any] | None = None


def init(
    *,
    graceful_shutdown_pending: Callable[[], bool],
    system_shutdown_active: Callable[[], bool],
    agent_state_lock: Any,
    registered_agents: dict[str, dict[str, Any]],
    agent_is_live: Callable[..., bool],
    load_agent_state: Callable[[str], dict[str, Any]],
    agent_activities: dict[str, dict[str, Any]],
    task_lock: Any,
    tasks: dict[str, dict[str, Any]],
    persist_tasks: Callable[[], None],
    append_message: Callable[..., Any],
) -> None:
    global _graceful_shutdown_pending_cb, _system_shutdown_active_cb
    global _agent_state_lock, _registered_agents, _agent_is_live_cb
    global _load_agent_state_cb, _agent_activities, _task_lock, _tasks
    global _persist_tasks_cb, _append_message_cb

    _graceful_shutdown_pending_cb = graceful_shutdown_pending
    _system_shutdown_active_cb = system_shutdown_active
    _agent_state_lock = agent_state_lock
    _registered_agents = registered_agents
    _agent_is_live_cb = agent_is_live
    _load_agent_state_cb = load_agent_state
    _agent_activities = agent_activities
    _task_lock = task_lock
    _tasks = tasks
    _persist_tasks_cb = persist_tasks
    _append_message_cb = append_message


def _role_match_score(role: str, description: str, labels_blob: str) -> int:
    score = 0
    for word in role.split():
        if len(word) > 3 and (word in description or word in labels_blob):
            score += 1
    return score


def _auto_assign_tick() -> list[str]:
    if (
        _graceful_shutdown_pending_cb is None
        or _system_shutdown_active_cb is None
        or _agent_state_lock is None
        or _registered_agents is None
        or _agent_is_live_cb is None
        or _load_agent_state_cb is None
        or _agent_activities is None
        or _task_lock is None
        or _tasks is None
        or _persist_tasks_cb is None
        or _append_message_cb is None
    ):
        raise RuntimeError("daemons.auto_assign not initialized")

    if _system_shutdown_active_cb():
        return []
    if _graceful_shutdown_pending_cb():
        return []

    idle_agents: list[tuple[str, str]] = []
    with _agent_state_lock:
        for agent_id, reg in _registered_agents.items():
            if not reg or not _agent_is_live_cb(agent_id, stale_seconds=120.0, reg=reg):
                continue

            agent_state = _load_agent_state_cb(agent_id)
            mode = agent_state.get("mode", "normal")
            if mode not in ("auto", "normal"):
                continue

            activity = _agent_activities.get(agent_id, {})
            ts_str = activity.get("timestamp", "")
            if ts_str:
                try:
                    age = (
                        datetime.now(timezone.utc) - datetime.fromisoformat(ts_str)
                    ).total_seconds()
                    if age < 120:
                        continue
                except (ValueError, TypeError):
                    pass

            role = str(reg.get("role", "")).lower()
            idle_agents.append((agent_id, role))

    if not idle_agents:
        return []

    unassigned_tasks: list[dict[str, Any]] = []
    with _task_lock:
        for task in _tasks.values():
            if task.get("state") != "created":
                continue
            if task.get("assigned_to"):
                continue
            unassigned_tasks.append(dict(task))

    if not unassigned_tasks:
        return []

    assigned: list[str] = []
    for task in unassigned_tasks:
        description = str(task.get("description", "")).lower()
        labels_blob = " ".join(str(label).lower() for label in task.get("labels", []))
        task_id = str(task.get("task_id", ""))
        title = str(task.get("title", ""))[:200]

        best_agent = None
        best_score = 0
        for agent_id, role in idle_agents:
            score = _role_match_score(role, description, labels_blob)
            if score > best_score:
                best_score = score
                best_agent = agent_id

        if not best_agent or best_score <= 0:
            continue

        with _task_lock:
            live_task = _tasks.get(task_id)
            if live_task is None:
                continue
            if live_task.get("state") != "created" or live_task.get("assigned_to"):
                continue
            live_task["assigned_to"] = best_agent
            _persist_tasks_cb()

        _append_message_cb(
            "system",
            best_agent,
            f"[AUTO-ASSIGNED] Task '{title}' (ID: {task_id}) wurde dir automatisch zugewiesen.\n"
            f"SOFORT: bridge_task_claim(task_id='{task_id}') -> ack -> bearbeiten -> done",
            meta={"type": "auto_assign", "task_id": task_id},
        )
        idle_agents = [(aid, role) for aid, role in idle_agents if aid != best_agent]
        assigned.append(task_id)
        print(
            f"[auto-assign] Assigned task '{task_id}' to idle agent '{best_agent}' "
            f"(score={best_score})"
        )

    if assigned:
        print(f"[auto-assign] Auto-assigned {len(assigned)} task(s)")

    return assigned


def _idle_watchdog_auto_assign() -> None:
    time.sleep(60)
    while True:
        time.sleep(_AUTO_ASSIGN_INTERVAL)
        try:
            _auto_assign_tick()
        except Exception as exc:
            print(f"[auto-assign] Error: {exc}")
