from __future__ import annotations

import subprocess
import sys
import time
from typing import Any, Callable

_CODEX_HOOK_INTERVAL = 15
_CODEX_HOOK_COOLDOWN: dict[str, float] = {}
_CODEX_HOOK_MIN_GAP = 20.0

_graceful_shutdown_pending_cb: Callable[[], bool] | None = None
_system_shutdown_active_cb: Callable[[], bool] | None = None
_team_config_getter_cb: Callable[[], dict[str, Any] | None] | None = None
_tmux_session_for_cb: Callable[[str], str] | None = None
_msg_lock: Any = None
_cursors: dict[str, int] | None = None
_messages: list[dict[str, Any]] | None = None
_task_lock: Any = None
_tasks: dict[str, dict[str, Any]] | None = None


def init(
    *,
    graceful_shutdown_pending: Callable[[], bool],
    system_shutdown_active: Callable[[], bool],
    team_config_getter: Callable[[], dict[str, Any] | None],
    tmux_session_for: Callable[[str], str],
    msg_lock: Any,
    cursors: dict[str, int],
    messages: list[dict[str, Any]],
    task_lock: Any,
    tasks: dict[str, dict[str, Any]],
) -> None:
    global _graceful_shutdown_pending_cb, _system_shutdown_active_cb
    global _team_config_getter_cb, _tmux_session_for_cb
    global _msg_lock, _cursors, _messages, _task_lock, _tasks

    _graceful_shutdown_pending_cb = graceful_shutdown_pending
    _system_shutdown_active_cb = system_shutdown_active
    _team_config_getter_cb = team_config_getter
    _tmux_session_for_cb = tmux_session_for
    _msg_lock = msg_lock
    _cursors = cursors
    _messages = messages
    _task_lock = task_lock
    _tasks = tasks


def _codex_hook_tick() -> list[str]:
    if (
        _graceful_shutdown_pending_cb is None
        or _system_shutdown_active_cb is None
        or _team_config_getter_cb is None
        or _tmux_session_for_cb is None
        or _msg_lock is None
        or _cursors is None
        or _messages is None
        or _task_lock is None
        or _tasks is None
    ):
        raise RuntimeError("daemons.codex_hook not initialized")

    if _system_shutdown_active_cb():
        return []
    if _graceful_shutdown_pending_cb():
        return []

    tc = _team_config_getter_cb()
    if not tc:
        return []

    codex_agents = []
    for agent in tc.get("agents", []):
        if str(agent.get("engine", "")).strip().lower() == "codex" and agent.get("active", False):
            codex_agents.append(agent.get("id", ""))
    if not codex_agents:
        return []

    injected: list[str] = []
    now = time.time()
    busy_indicators = [
        "thinking",
        "running",
        "writing",
        "reading",
        "searching",
        "editing",
        "executing",
        "analyzing",
        "bridge_receive",
        "bridge_send",
        "bridge_task",
    ]
    prompt = (
        "\nbridge_receive und weiterarbeiten. "
        "Rufe bridge_receive() auf, lies Nachrichten, "
        "pruefe bridge_task_queue(state='created'). Starte JETZT.\n"
    )

    for agent_id in codex_agents:
        if not agent_id:
            continue
        last_inject = _CODEX_HOOK_COOLDOWN.get(agent_id, 0.0)
        if now - last_inject < _CODEX_HOOK_MIN_GAP:
            continue

        session_name = _tmux_session_for_cb(agent_id)
        try:
            chk = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True,
                timeout=3,
            )
            if chk.returncode != 0:
                continue
        except Exception:
            continue

        try:
            cap = subprocess.run(
                ["tmux", "capture-pane", "-t", session_name, "-p", "-l", "5"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if cap.returncode != 0:
                continue
            pane_text = cap.stdout.strip()
        except Exception:
            continue
        if not pane_text:
            continue

        last_lines = pane_text.splitlines()[-3:]
        combined = " ".join(last_lines).lower()
        if any(indicator in combined for indicator in busy_indicators):
            continue

        has_work = False
        with _msg_lock:
            cursor = _cursors.get(agent_id, 0)
            for msg in _messages[cursor:]:
                if msg.get("to") in (agent_id, "all") and msg.get("from") != agent_id:
                    has_work = True
                    break

        if not has_work:
            with _task_lock:
                for task in _tasks.values():
                    if task.get("state") == "created":
                        if not task.get("assigned_to") or task.get("assigned_to") == agent_id:
                            has_work = True
                            break

        if not has_work:
            continue

        _CODEX_HOOK_COOLDOWN[agent_id] = now
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, "-l", prompt],
                capture_output=True,
                timeout=3,
            )
            injected.append(agent_id)
        except Exception:
            pass

    return injected


def _codex_hook_loop() -> None:
    time.sleep(20)
    while True:
        time.sleep(_CODEX_HOOK_INTERVAL)
        try:
            _codex_hook_tick()
        except Exception as exc:
            print(f"[codex-hook] Error: {exc}", file=sys.stderr)
