from __future__ import annotations

import subprocess
import time
from typing import Any, Callable

_RATE_LIMIT_RESUME_INITIAL = 1800
_RATE_LIMIT_RESUME_MAX = 14400
_RATE_LIMIT_RESUME_FACTOR = 2

_agent_state_lock: Any = None
_agent_rate_limited: dict[str, dict[str, Any]] | None = None
_registered_agents: dict[str, dict[str, Any]] | None = None
_agent_is_live_cb: Callable[..., bool] | None = None
_tmux_session_for_cb: Callable[[str], str] | None = None
_check_tmux_session_cb: Callable[[str], bool] | None = None
_start_agent_from_conf_cb: Callable[[str], bool] | None = None
_append_message_cb: Callable[[str, str, str], Any] | None = None
_ws_broadcast_cb: Callable[[str, dict[str, Any]], Any] | None = None


def init(
    *,
    agent_state_lock: Any,
    agent_rate_limited: dict[str, dict[str, Any]],
    registered_agents: dict[str, dict[str, Any]],
    agent_is_live: Callable[..., bool],
    tmux_session_for: Callable[[str], str],
    check_tmux_session: Callable[[str], bool],
    start_agent_from_conf: Callable[[str], bool],
    append_message: Callable[[str, str, str], Any],
    ws_broadcast: Callable[[str, dict[str, Any]], Any],
) -> None:
    global _agent_state_lock, _agent_rate_limited, _registered_agents
    global _agent_is_live_cb, _tmux_session_for_cb, _check_tmux_session_cb
    global _start_agent_from_conf_cb, _append_message_cb, _ws_broadcast_cb

    _agent_state_lock = agent_state_lock
    _agent_rate_limited = agent_rate_limited
    _registered_agents = registered_agents
    _agent_is_live_cb = agent_is_live
    _tmux_session_for_cb = tmux_session_for
    _check_tmux_session_cb = check_tmux_session
    _start_agent_from_conf_cb = start_agent_from_conf
    _append_message_cb = append_message
    _ws_broadcast_cb = ws_broadcast


def _append_message(sender: str, target: str, message: str) -> None:
    if _append_message_cb is None:
        return
    _append_message_cb(sender, target, message)


def _ws_broadcast(event_type: str, payload: dict[str, Any]) -> None:
    if _ws_broadcast_cb is None:
        return
    _ws_broadcast_cb(event_type, payload)


def _rate_limit_resume_loop() -> None:
    """Background thread: tries to resume rate-limited agents with exponential backoff."""
    time.sleep(60)
    while True:
        try:
            _rate_limit_resume_tick()
        except Exception as exc:
            print(f"[rate-limit-resume] Error: {exc}")
        time.sleep(300)


def _rate_limit_resume_tick() -> None:
    """Single tick: check all rate-limited agents for resume eligibility."""
    if (
        _agent_state_lock is None
        or _agent_rate_limited is None
        or _registered_agents is None
        or _agent_is_live_cb is None
        or _tmux_session_for_cb is None
        or _check_tmux_session_cb is None
        or _start_agent_from_conf_cb is None
    ):
        raise RuntimeError("daemons.rate_limit_resume not initialized")

    now = time.time()
    with _agent_state_lock:
        rl_snapshot = dict(_agent_rate_limited)
    for agent_id in rl_snapshot:
        info = rl_snapshot.get(agent_id)
        if not info:
            continue

        attempts = info.get("resume_attempts", 0)
        interval = min(
            _RATE_LIMIT_RESUME_INITIAL * (_RATE_LIMIT_RESUME_FACTOR ** attempts),
            _RATE_LIMIT_RESUME_MAX,
        )
        last_attempt = info.get("last_resume_attempt", 0)
        if now - last_attempt < interval:
            continue

        with _agent_state_lock:
            reg = _registered_agents.get(agent_id)
            if reg:
                if _agent_is_live_cb(agent_id, stale_seconds=120.0, reg=reg):
                    del _agent_rate_limited[agent_id]
                    msg = f"[RATE-LIMIT CLEARED] {agent_id} ist wieder aktiv (Heartbeat empfangen)."
                    try:
                        _append_message("system", "user", msg)
                        _ws_broadcast("agent_rate_limit_cleared", {"agent_id": agent_id})
                    except Exception:
                        pass
                    print(f"[rate-limit-resume] {msg}")
                    continue

        session_name = _tmux_session_for_cb(agent_id)
        if not _check_tmux_session_cb(agent_id):
            print(f"[rate-limit-resume] {agent_id}: tmux session dead, attempting restart")
            info["last_resume_attempt"] = now
            info["resume_attempts"] = attempts + 1
            with _agent_state_lock:
                _agent_rate_limited.pop(agent_id, None)
            success = _start_agent_from_conf_cb(agent_id)
            if not success:
                with _agent_state_lock:
                    _agent_rate_limited[agent_id] = {
                        "since": info["since"],
                        "last_resume_attempt": now,
                        "resume_attempts": attempts + 1,
                    }
                print(f"[rate-limit-resume] {agent_id}: restart failed, retry in {interval}s")
            else:
                msg = f"[RATE-LIMIT RESUMED] {agent_id} erfolgreich neu gestartet."
                try:
                    _append_message("system", "user", msg)
                    _ws_broadcast("agent_rate_limit_cleared", {"agent_id": agent_id})
                except Exception:
                    pass
                print(f"[rate-limit-resume] {msg}")
            continue

        print(f"[rate-limit-resume] {agent_id}: injecting resume prompt (attempt {attempts + 1})")
        with _agent_state_lock:
            live_info = _agent_rate_limited.get(agent_id)
            if live_info:
                live_info["last_resume_attempt"] = now
                live_info["resume_attempts"] = attempts + 1
        try:
            resume_text = (
                "Dein API-Usage-Limit war ueberschritten. "
                "Versuche dich via bridge_register zu registrieren. "
                "Wenn es funktioniert, arbeite normal weiter."
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, resume_text, "Enter"],
                timeout=5,
            )
        except Exception as exc:
            print(f"[rate-limit-resume] {agent_id}: inject failed: {exc}")
