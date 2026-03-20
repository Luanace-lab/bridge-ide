from __future__ import annotations

import hashlib
import subprocess
import time
from typing import Any, Callable, Iterable

_AGENT_OUTPUT_HASHES: dict[str, dict[str, Any]] = {}
_CLI_STUCK_THRESHOLD = 600
_CLI_KILL_THRESHOLD = 900
_CLI_CHECK_INTERVAL = 60
_CLI_STUCK_ALERTED: set[str] = set()
_CLI_STARTUP_PROMPTS = (
    "press enter to continue",
    "paste code here",
    "login successful",
    "sign in",
    "choose a theme",
    "select a theme",
    "syntax theme",
    "ctrl+t to disable",
)
_CLI_AUTH_ALERTED: set[str] = set()
_THINKING_PATTERNS = (
    "thinking", "Tinkering", "Waddling", "Contemplating",
    "Crunching", "Generating", "Hullaballooing", "Whirring",
    "Pondering", "Reasoning", "Rambling", "Mulling",
    "Reflecting", "Cogitating",
)
_CLI_HEARTBEAT_GRACE = 120

_agent_state_lock: Any = None
_registered_agents: dict[str, dict[str, Any]] | None = None
_agent_rate_limited: dict[str, dict[str, Any]] | None = None
_tmux_session_for_cb: Callable[[str], str] | None = None
_check_tmux_session_cb: Callable[[str], bool] | None = None
_append_message_cb: Callable[[str, str, str], Any] | None = None
_ws_broadcast_cb: Callable[[str, dict[str, Any]], Any] | None = None
_rate_limit_patterns: tuple[str, ...] = ()
_is_agent_at_prompt_cb: Callable[[str], bool] | None = None


def init(
    *,
    agent_state_lock: Any,
    registered_agents: dict[str, dict[str, Any]],
    agent_rate_limited: dict[str, dict[str, Any]],
    tmux_session_for: Callable[[str], str],
    check_tmux_session: Callable[[str], bool],
    append_message: Callable[[str, str, str], Any],
    ws_broadcast: Callable[[str, dict[str, Any]], Any],
    rate_limit_patterns: Iterable[str],
    is_agent_at_prompt: Callable[[str], bool],
) -> None:
    global _agent_state_lock, _registered_agents, _agent_rate_limited
    global _tmux_session_for_cb, _check_tmux_session_cb
    global _append_message_cb, _ws_broadcast_cb
    global _rate_limit_patterns, _is_agent_at_prompt_cb
    global _CLI_STUCK_THRESHOLD, _CLI_KILL_THRESHOLD, _CLI_CHECK_INTERVAL

    _agent_state_lock = agent_state_lock
    _registered_agents = registered_agents
    _agent_rate_limited = agent_rate_limited
    _tmux_session_for_cb = tmux_session_for
    _check_tmux_session_cb = check_tmux_session
    _append_message_cb = append_message
    _ws_broadcast_cb = ws_broadcast
    _rate_limit_patterns = tuple(str(p).lower() for p in rate_limit_patterns)
    _is_agent_at_prompt_cb = is_agent_at_prompt


def _append_message(sender: str, target: str, message: str) -> None:
    if _append_message_cb is None:
        return
    _append_message_cb(sender, target, message)


def _ws_broadcast(event_type: str, payload: dict[str, Any]) -> None:
    if _ws_broadcast_cb is None:
        return
    _ws_broadcast_cb(event_type, payload)


def _cli_output_monitor_loop() -> None:
    """Background thread: detects stuck CLIs via tmux output hash comparison."""
    time.sleep(30)
    while True:
        try:
            _cli_output_monitor_tick()
        except Exception as exc:
            print(f"[cli-monitor] Error: {exc}")
        time.sleep(_CLI_CHECK_INTERVAL)


def _cli_output_monitor_tick() -> None:
    """Single tick: check all agent tmux sessions for output changes."""
    if (
        _agent_state_lock is None
        or _registered_agents is None
        or _agent_rate_limited is None
        or _tmux_session_for_cb is None
        or _check_tmux_session_cb is None
    ):
        raise RuntimeError("daemons.cli_monitor not initialized")

    now = time.time()
    with _agent_state_lock:
        agent_ids = list(_registered_agents.keys())
        agent_heartbeats = {
            aid: reg.get("last_heartbeat", 0)
            for aid, reg in _registered_agents.items()
        }

    for agent_id in agent_ids:
        session_name = _tmux_session_for_cb(agent_id)

        if not _check_tmux_session_cb(agent_id):
            _AGENT_OUTPUT_HASHES.pop(agent_id, None)
            _CLI_STUCK_ALERTED.discard(agent_id)
            continue

        last_hb = agent_heartbeats.get(agent_id, 0)
        if last_hb and (now - last_hb) < _CLI_HEARTBEAT_GRACE:
            _AGENT_OUTPUT_HASHES[agent_id] = {"hash": "", "since": now}
            _CLI_STUCK_ALERTED.discard(agent_id)
            continue

        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-50"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.strip()
        except Exception:
            continue

        current_hash = hashlib.sha256(output.encode()).hexdigest()
        prev = _AGENT_OUTPUT_HASHES.get(agent_id)

        if prev is None or prev["hash"] != current_hash:
            _AGENT_OUTPUT_HASHES[agent_id] = {"hash": current_hash, "since": now}
            _CLI_STUCK_ALERTED.discard(agent_id)
            continue

        stuck_seconds = now - prev["since"]

        if stuck_seconds >= _CLI_STUCK_THRESHOLD and _is_agent_at_prompt_cb is not None:
            try:
                if _is_agent_at_prompt_cb(agent_id):
                    continue
            except Exception:
                pass

        if stuck_seconds >= _CLI_STUCK_THRESHOLD:
            if any(p.lower() in output.lower() for p in _THINKING_PATTERNS):
                _CLI_STUCK_ALERTED.discard(agent_id)
                continue

        output_lower = output.lower()
        startup_prompt_detected = any(pattern in output_lower for pattern in _CLI_STARTUP_PROMPTS)
        if startup_prompt_detected:
            if "paste code here" in output_lower or "sign in" in output_lower:
                if agent_id not in _CLI_AUTH_ALERTED:
                    _CLI_AUTH_ALERTED.add(agent_id)
                    msg = (
                        f"[AUTH-FAILURE] {agent_id} haengt an OAuth-Login. "
                        f"Session braucht manuellen Login oder Restart."
                    )
                    try:
                        _append_message("system", "user", msg)
                        _ws_broadcast("agent_auth_failure", {"agent_id": agent_id})
                    except Exception:
                        pass
                    print(f"[cli-monitor] {msg}")
                _CLI_STUCK_ALERTED.discard(agent_id)
                continue
            try:
                subprocess.run(
                    ["tmux", "send-keys", "-t", session_name, "Enter"],
                    timeout=5,
                    capture_output=True,
                )
                print(f"[cli-monitor] Auto-Enter for startup prompt: {agent_id}")
            except Exception:
                pass
            _AGENT_OUTPUT_HASHES[agent_id] = {"hash": "", "since": now}
            _CLI_STUCK_ALERTED.discard(agent_id)
            continue

        if any(p in output_lower for p in _rate_limit_patterns):
            with _agent_state_lock:
                is_new = agent_id not in _agent_rate_limited
                if is_new:
                    _agent_rate_limited[agent_id] = {
                        "since": now,
                        "last_resume_attempt": 0,
                        "resume_attempts": 0,
                    }
            if is_new:
                msg = (
                    f"[RATE-LIMITED] {agent_id} hat API-Usage-Limit erreicht. "
                    f"Session wird geschuetzt (kein Kill). Auto-Resume aktiv."
                )
                try:
                    _append_message("system", "user", msg)
                    _ws_broadcast("agent_rate_limited", {"agent_id": agent_id})
                except Exception:
                    pass
                print(f"[cli-monitor] {msg}")
            _CLI_STUCK_ALERTED.discard(agent_id)
            continue

        with _agent_state_lock:
            is_rate_limited = agent_id in _agent_rate_limited
        if is_rate_limited:
            _CLI_STUCK_ALERTED.discard(agent_id)
            continue

        if stuck_seconds >= _CLI_KILL_THRESHOLD:
            try:
                subprocess.run(
                    ["tmux", "send-keys", "-t", session_name, "C-c"],
                    timeout=5,
                )
            except Exception:
                pass

            msg = (
                f"[AUTO-KILL] {agent_id} war {int(stuck_seconds/60)} Min "
                f"blockiert (kein tmux-Output). Ctrl+C gesendet."
            )
            try:
                _append_message("system", "user", msg)
            except Exception:
                pass
            print(f"[cli-monitor] {msg}")
            _AGENT_OUTPUT_HASHES[agent_id] = {"hash": "", "since": now}
            _CLI_STUCK_ALERTED.discard(agent_id)

        elif stuck_seconds >= _CLI_STUCK_THRESHOLD and agent_id not in _CLI_STUCK_ALERTED:
            msg = (
                f"[WARN] {agent_id} hat seit {int(stuck_seconds/60)} Min "
                f"keinen neuen tmux-Output. Moeglicherweise blockiert."
            )
            try:
                _append_message("system", "user", msg)
            except Exception:
                pass
            print(f"[cli-monitor] {msg}")
            _CLI_STUCK_ALERTED.add(agent_id)
