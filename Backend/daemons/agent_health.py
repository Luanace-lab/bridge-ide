from __future__ import annotations

import threading
import time
from typing import Any, Callable

_MAX_BUSY_SECONDS = 300.0
_CLEANUP_TTL = 300.0

_system_shutdown_active_cb: Callable[[], bool] | None = None
_current_runtime_slot_map_cb: Callable[[], dict[str, str]] | None = None
_load_agents_conf_cb: Callable[[], dict[str, dict[str, str]]] | None = None
_team_config_getter: Callable[[], dict[str, Any] | None] | None = None
_all_tmux_agent_ids_cb: Callable[[], set[str]] | None = None
_agent_state_lock: threading.Lock | None = None
_registered_agents: dict[str, Any] | None = None
_agent_busy: dict[str, bool] | None = None
_agent_last_seen: dict[str, float] | None = None
_is_session_alive_cb: Callable[[str], bool] | None = None
_get_agent_engine_cb: Callable[[str], str] | None = None
_check_codex_health_cb: Callable[[str], dict[str, Any]] | None = None
_auto_restart_agents_cb: Callable[[], bool] | None = None
_agent_last_restart: dict[str, float] | None = None
_restart_lock: "threading.Lock | None" = None
_restart_cooldown_cb: Callable[[], float] | None = None
_auto_restart_agent_cb: Callable[[str], bool] | None = None
_start_agent_from_conf_cb: Callable[[str], bool] | None = None
_send_health_alert_cb: Callable[..., Any] | None = None
_is_agent_at_oauth_prompt_cb: Callable[[str], bool] | None = None
_agent_auth_blocked: set[str] | None = None
_agent_oauth_failures: dict[str, Any] | None = None
_append_message_cb: Callable[..., Any] | None = None
_plan_mode_rescue_check_cb: Callable[[str], bool] | None = None
_agent_last_auto_register: dict[str, float] | None = None
_auto_register_cooldown_cb: Callable[[], float] | None = None
_runtime_profile_capabilities_cb: Callable[[str], list[str]] | None = None
_seed_phantom_agent_registration_cb: Callable[..., Any] | None = None
_agent_last_nudge: dict[str, float] | None = None
_nudge_cooldown_cb: Callable[[], float] | None = None
_message_cond: threading.Condition | None = None
_cursors: dict[str, int] | None = None
_messages_for_agent_cb: Callable[[int, str], list[dict[str, Any]]] | None = None
_is_agent_at_prompt_inline_cb: Callable[[str], bool] | None = None
_classify_agent_interactive_blocker_cb: Callable[[str], dict[str, str]] | None = None
_nudge_idle_agent_cb: Callable[[str, str], bool] | None = None
_update_agent_status_cb: Callable[[str], Any] | None = None
_auto_cleanup_agents_cb: Callable[[float], None] | None = None
_grace_tokens: dict[str, tuple[Any, float]] | None = None


def init(
    *,
    system_shutdown_active: Callable[[], bool],
    current_runtime_slot_map: Callable[[], dict[str, str]],
    load_agents_conf: Callable[[], dict[str, dict[str, str]]],
    team_config_getter: Callable[[], dict[str, Any] | None],
    all_tmux_agent_ids: Callable[[], set[str]],
    agent_state_lock: threading.Lock,
    registered_agents: dict[str, Any],
    agent_busy: dict[str, bool],
    agent_last_seen: dict[str, float],
    is_session_alive: Callable[[str], bool],
    get_agent_engine: Callable[[str], str],
    check_codex_health: Callable[[str], dict[str, Any]],
    auto_restart_agents: Callable[[], bool],
    agent_last_restart: dict[str, float],
    restart_lock: "threading.Lock",
    restart_cooldown: Callable[[], float],
    auto_restart_agent: Callable[[str], bool],
    start_agent_from_conf: Callable[[str], bool],
    send_health_alert: Callable[..., Any],
    is_agent_at_oauth_prompt: Callable[[str], bool],
    agent_auth_blocked: set[str],
    agent_oauth_failures: dict[str, Any],
    append_message: Callable[..., Any],
    plan_mode_rescue_check: Callable[[str], bool],
    agent_last_auto_register: dict[str, float],
    auto_register_cooldown: Callable[[], float],
    runtime_profile_capabilities: Callable[[str], list[str]],
    seed_phantom_agent_registration: Callable[..., Any],
    agent_last_nudge: dict[str, float],
    nudge_cooldown: Callable[[], float],
    message_cond: threading.Condition,
    cursors: dict[str, int],
    messages_for_agent: Callable[[int, str], list[dict[str, Any]]],
    is_agent_at_prompt_inline: Callable[[str], bool],
    classify_agent_interactive_blocker: Callable[[str], dict[str, str]],
    nudge_idle_agent: Callable[[str, str], bool],
    update_agent_status: Callable[[str], Any],
    auto_cleanup_agents: Callable[[float], None],
    grace_tokens: dict[str, tuple[Any, float]],
) -> None:
    global _system_shutdown_active_cb, _current_runtime_slot_map_cb, _load_agents_conf_cb
    global _team_config_getter, _all_tmux_agent_ids_cb, _agent_state_lock
    global _registered_agents, _agent_busy, _agent_last_seen, _is_session_alive_cb
    global _get_agent_engine_cb, _check_codex_health_cb, _auto_restart_agents_cb
    global _agent_last_restart, _restart_lock, _restart_cooldown_cb, _auto_restart_agent_cb
    global _start_agent_from_conf_cb, _send_health_alert_cb, _is_agent_at_oauth_prompt_cb
    global _agent_auth_blocked, _agent_oauth_failures, _append_message_cb
    global _plan_mode_rescue_check_cb, _agent_last_auto_register, _auto_register_cooldown_cb
    global _runtime_profile_capabilities_cb, _seed_phantom_agent_registration_cb
    global _agent_last_nudge, _nudge_cooldown_cb, _message_cond, _cursors
    global _messages_for_agent_cb, _is_agent_at_prompt_inline_cb, _classify_agent_interactive_blocker_cb
    global _nudge_idle_agent_cb, _update_agent_status_cb, _auto_cleanup_agents_cb
    global _grace_tokens

    _system_shutdown_active_cb = system_shutdown_active
    _current_runtime_slot_map_cb = current_runtime_slot_map
    _load_agents_conf_cb = load_agents_conf
    _team_config_getter = team_config_getter
    _all_tmux_agent_ids_cb = all_tmux_agent_ids
    _agent_state_lock = agent_state_lock
    _registered_agents = registered_agents
    _agent_busy = agent_busy
    _agent_last_seen = agent_last_seen
    _is_session_alive_cb = is_session_alive
    _get_agent_engine_cb = get_agent_engine
    _check_codex_health_cb = check_codex_health
    _auto_restart_agents_cb = auto_restart_agents
    _agent_last_restart = agent_last_restart
    _restart_lock = restart_lock
    _restart_cooldown_cb = restart_cooldown
    _auto_restart_agent_cb = auto_restart_agent
    _start_agent_from_conf_cb = start_agent_from_conf
    _send_health_alert_cb = send_health_alert
    _is_agent_at_oauth_prompt_cb = is_agent_at_oauth_prompt
    _agent_auth_blocked = agent_auth_blocked
    _agent_oauth_failures = agent_oauth_failures
    _append_message_cb = append_message
    _plan_mode_rescue_check_cb = plan_mode_rescue_check
    _agent_last_auto_register = agent_last_auto_register
    _auto_register_cooldown_cb = auto_register_cooldown
    _runtime_profile_capabilities_cb = runtime_profile_capabilities
    _seed_phantom_agent_registration_cb = seed_phantom_agent_registration
    _agent_last_nudge = agent_last_nudge
    _nudge_cooldown_cb = nudge_cooldown
    _message_cond = message_cond
    _cursors = cursors
    _messages_for_agent_cb = messages_for_agent
    _is_agent_at_prompt_inline_cb = is_agent_at_prompt_inline
    _classify_agent_interactive_blocker_cb = classify_agent_interactive_blocker
    _nudge_idle_agent_cb = nudge_idle_agent
    _update_agent_status_cb = update_agent_status
    _auto_cleanup_agents_cb = auto_cleanup_agents
    _grace_tokens = grace_tokens


def _agent_health_tick(cleanup_counter: int) -> int:
    required = [
        _system_shutdown_active_cb,
        _current_runtime_slot_map_cb,
        _load_agents_conf_cb,
        _team_config_getter,
        _all_tmux_agent_ids_cb,
        _agent_state_lock,
        _registered_agents,
        _agent_busy,
        _agent_last_seen,
        _is_session_alive_cb,
        _get_agent_engine_cb,
        _check_codex_health_cb,
        _auto_restart_agents_cb,
        _agent_last_restart,
        _restart_cooldown_cb,
        _auto_restart_agent_cb,
        _start_agent_from_conf_cb,
        _send_health_alert_cb,
        _is_agent_at_oauth_prompt_cb,
        _agent_auth_blocked,
        _agent_oauth_failures,
        _append_message_cb,
        _plan_mode_rescue_check_cb,
        _agent_last_auto_register,
        _auto_register_cooldown_cb,
        _runtime_profile_capabilities_cb,
        _seed_phantom_agent_registration_cb,
        _agent_last_nudge,
        _nudge_cooldown_cb,
        _message_cond,
        _cursors,
        _messages_for_agent_cb,
        _is_agent_at_prompt_inline_cb,
        _classify_agent_interactive_blocker_cb,
        _nudge_idle_agent_cb,
        _update_agent_status_cb,
        _auto_cleanup_agents_cb,
        _grace_tokens,
    ]
    if any(item is None for item in required):
        raise RuntimeError("daemons.agent_health not initialized")

    if _system_shutdown_active_cb():
        return cleanup_counter

    cleanup_counter += 1
    runtime_slot_map = _current_runtime_slot_map_cb()
    runtime_agent_ids = set(runtime_slot_map.keys())
    conf_all = _load_agents_conf_cb()
    conf_ids = set(conf_all.keys())
    team_config = _team_config_getter() or {}
    for agent in team_config.get("agents", []):
        aid = agent.get("id", "")
        if aid and agent.get("active", False) and agent.get("home_dir"):
            conf_ids.add(aid)
    conf_startable = {aid for aid, cfg in conf_all.items() if str(cfg.get("prompt_file", "")).strip()}
    for agent in team_config.get("agents", []):
        aid = agent.get("id", "")
        if aid and agent.get("active", False) and agent.get("home_dir"):
            conf_startable.add(aid)
    tmux_agent_ids = _all_tmux_agent_ids_cb() & conf_ids
    with _agent_state_lock:
        agent_ids = runtime_agent_ids | set(_registered_agents.keys()) | tmux_agent_ids | conf_startable

    for agent_id in agent_ids:
        with _agent_state_lock:
            is_busy = _agent_busy.get(agent_id, False)
            last_hb = 0.0
            if is_busy:
                reg = _registered_agents.get(agent_id)
                last_hb = reg.get("last_heartbeat", 0) if reg else _agent_last_seen.get(agent_id, 0)
        if is_busy and (time.time() - last_hb) > _MAX_BUSY_SECONDS:
            if not _is_session_alive_cb(agent_id):
                with _agent_state_lock:
                    _agent_busy[agent_id] = False

        engine = _get_agent_engine_cb(agent_id)
        if engine == "codex" and _is_session_alive_cb(agent_id):
            health = _check_codex_health_cb(agent_id)
            if health["crashed"] and _auto_restart_agents_cb():
                try:
                    _append_message_cb("system", "user", f"[CRASH] Agent {agent_id} crashed: {health['detail']}")
                except Exception:
                    pass
                _auto_restart_agent_cb(agent_id)

        if not _is_session_alive_cb(agent_id) and agent_id in conf_ids:
            if _auto_restart_agents_cb():
                # Only auto-restart agents with auto_start=true in team.json
                _should_restart = False
                for _ag in team_config.get("agents", []):
                    if _ag.get("id") == agent_id:
                        _should_restart = bool(_ag.get("auto_start", False))
                        break
                if not _should_restart:
                    continue
                with _restart_lock:
                    last_restart = _agent_last_restart.get(agent_id, 0)
                    if (time.time() - last_restart) >= _restart_cooldown_cb():
                        restarted = False
                        if agent_id in runtime_agent_ids:
                            restarted = _auto_restart_agent_cb(agent_id)
                        else:
                            has_config = False
                            for agent in team_config.get("agents", []):
                                if agent.get("id") == agent_id and agent.get("home_dir"):
                                    has_config = True
                                    break
                            if not has_config:
                                conf = _load_agents_conf_cb().get(agent_id, {})
                                has_config = bool(str(conf.get("prompt_file", "")).strip())
                            if has_config:
                                print(f"[health] Auto-restart: {agent_id}")
                                restarted = _start_agent_from_conf_cb(agent_id)
                        if restarted:
                            _agent_last_restart[agent_id] = time.time()

        if _is_session_alive_cb(agent_id):
            with _agent_state_lock:
                reg = _registered_agents.get(agent_id)
                if reg is not None:
                    last_hb = reg.get("last_heartbeat", 0)
                    hb_age = time.time() - last_hb
                    if hb_age > 120:
                        _send_health_alert_cb(
                            f"agent:{agent_id}:no_heartbeat",
                            "warn",
                            f"[WARN] Agent {agent_id}: tmux lebt, aber kein Heartbeat seit {int(hb_age)}s. "
                            f"Moeglicherweise Registrierung verloren.",
                            time.time(),
                        )
                        # Active recovery: nudge agent to re-register after >5min no heartbeat
                        if hb_age > 300:
                            _nudge_key = f"recovery_nudge:{agent_id}"
                            _last_nudge = _agent_last_restart.get(_nudge_key, 0)
                            if (time.time() - _last_nudge) > 120:  # cooldown 2min between nudges
                                _agent_last_restart[_nudge_key] = time.time()
                                session_name = f"acw_{agent_id}"
                                try:
                                    import subprocess as _sp
                                    _sp.run(["tmux", "send-keys", "-t", session_name,
                                             "Lies deine Dokumentation. Registriere dich via bridge_register.",
                                             "Enter"], capture_output=True, timeout=3)
                                    print(f"[health] Recovery-nudge sent to {agent_id} (no heartbeat {int(hb_age)}s)")
                                except Exception:
                                    pass

        if _is_session_alive_cb(agent_id) and agent_id in conf_ids:
            if _is_agent_at_oauth_prompt_cb(agent_id):
                if agent_id not in _agent_auth_blocked:
                    _agent_auth_blocked.add(agent_id)
                    print(f"[health] Auth-blocked: {agent_id} — official Claude login required")
                    try:
                        _append_message_cb(
                            "system",
                            "user",
                            f"[LOGIN-REQUIRED] Agent {agent_id} wartet auf offiziellen Claude-Login in der Session. Kein Auto-Restart.",
                        )
                    except Exception:
                        pass
            elif agent_id in _agent_auth_blocked:
                _agent_auth_blocked.discard(agent_id)
                _agent_oauth_failures.pop(agent_id, None)
                print(f"[health] Auth-unblocked: {agent_id} — recovered")

        if _is_session_alive_cb(agent_id) and agent_id in conf_ids:
            _plan_mode_rescue_check_cb(agent_id)

        if _is_session_alive_cb(agent_id) and agent_id in conf_ids:
            auto_registered = False
            last_auto_reg = _agent_last_auto_register.get(agent_id, 0)
            if time.time() - last_auto_reg >= _auto_register_cooldown_cb():
                auto_role = runtime_slot_map.get(agent_id, "") or "agent"
                auto_caps = _runtime_profile_capabilities_cb(agent_id)
                with _agent_state_lock:
                    needs_phantom = agent_id not in _registered_agents
                if needs_phantom:
                    _seed_phantom_agent_registration_cb(agent_id, role=auto_role, capabilities=auto_caps)
                    auto_registered = True
                    _agent_last_auto_register[agent_id] = time.time()
            if auto_registered:
                print(f"[health] Phantom-registered: {agent_id} (role={auto_role}) — awaiting real bridge_register()")

        if _is_session_alive_cb(agent_id) and _is_agent_at_prompt_inline_cb(agent_id):
            blocker = _classify_agent_interactive_blocker_cb(agent_id)
            if blocker:
                continue
            last_nudge = _agent_last_nudge.get(agent_id, 0)
            if (time.time() - last_nudge) >= _nudge_cooldown_cb():
                with _message_cond:
                    cursor = _cursors.get(agent_id, 0)
                    has_pending = len(_messages_for_agent_cb(cursor, agent_id)) > 0
                agent_info = _registered_agents.get(agent_id, {})
                last_hb = agent_info.get("last_heartbeat", 0)
                hb_stale = (time.time() - last_hb) > 120.0 if last_hb else True
                if has_pending or hb_stale:
                    reason_detail = f"pending={has_pending}, hb_stale={hb_stale}"
                    print(f"[recovery] Detected {agent_id} at prompt ({reason_detail}), nudging...")
                    if _nudge_idle_agent_cb(agent_id, "health_checker"):
                        _agent_last_nudge[agent_id] = time.time()
                else:
                    print(f"[recovery] {agent_id} at prompt but no pending msgs and heartbeat fresh — skipping nudge")

        _update_agent_status_cb(agent_id)

    if cleanup_counter % 30 == 0:
        _auto_cleanup_agents_cb(_CLEANUP_TTL)

    if cleanup_counter % 3 == 0:
        now_gc = time.time()
        expired_grace = [token for token, (_, exp) in _grace_tokens.items() if now_gc >= exp]
        for token in expired_grace:
            _grace_tokens.pop(token, None)

    return cleanup_counter
def _agent_health_checker() -> None:
    """Background thread: periodically checks all known agents for stale/crash status."""
    cleanup_counter = 0
    while True:
        time.sleep(10)
        cleanup_counter = _agent_health_tick(cleanup_counter)
