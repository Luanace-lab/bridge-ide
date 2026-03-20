from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable


_REGISTERED_AGENTS: dict[str, dict[str, Any]] = {}
_AGENT_BUSY: dict[str, bool] = {}
_AGENT_ACTIVITIES: dict[str, dict[str, Any]] = {}
_AGENT_STATE_LOCK: Any = threading.RLock()
_TASKS: dict[str, dict[str, Any]] = {}
_TASK_LOCK: Any = threading.RLock()
_PORT_GETTER: Callable[[], int] = lambda: 9111
_AGENT_IS_LIVE_FN: Callable[[str, float, dict[str, Any] | None], bool] = lambda _agent_id, _stale_seconds=120.0, _reg=None: False
_AUTO_GEN_WATCHER: Callable[[], None] = lambda: None
_AGENT_HEALTH_CHECKER: Callable[[], None] = lambda: None
_HEALTH_MONITOR_LOOP: Callable[[], None] = lambda: None
_CLI_OUTPUT_MONITOR_LOOP: Callable[[], None] = lambda: None
_RATE_LIMIT_RESUME_LOOP: Callable[[], None] = lambda: None
_V3_CLEANUP_LOOP: Callable[[], None] = lambda: None
_TASK_TIMEOUT_LOOP: Callable[[], None] = lambda: None
_HEARTBEAT_PROMPT_LOOP: Callable[[], None] = lambda: None
_CODEX_HOOK_LOOP: Callable[[], None] = lambda: None
_DISTILLATION_DAEMON_LOOP: Callable[[], None] = lambda: None
_IDLE_AGENT_TASK_PUSHER: Callable[[], None] = lambda: None
_IDLE_WATCHDOG_AUTO_ASSIGN: Callable[[], None] = lambda: None
_BUDDY_KNOWLEDGE_LOOP: Callable[[], None] = lambda: None
_RUN_WEBSOCKET_SERVER: Callable[[], None] = lambda: None
_RESTART_WAKE_ENABLED: Callable[[], bool] = lambda: False
_START_RESTART_WAKE_THREAD: Callable[[], None] = lambda: None
_START_SUPERVISOR_DAEMON: Callable[[], None] = lambda: None


def init(
    *,
    registered_agents: dict[str, dict[str, Any]],
    agent_busy: dict[str, bool],
    agent_activities: dict[str, dict[str, Any]],
    agent_state_lock: Any,
    tasks: dict[str, dict[str, Any]],
    task_lock: Any,
    port_getter: Callable[[], int],
    agent_is_live_fn: Callable[[str, float, dict[str, Any] | None], bool],
    auto_gen_watcher_fn: Callable[[], None],
    agent_health_checker_fn: Callable[[], None],
    health_monitor_loop_fn: Callable[[], None],
    cli_output_monitor_loop_fn: Callable[[], None],
    rate_limit_resume_loop_fn: Callable[[], None],
    v3_cleanup_loop_fn: Callable[[], None],
    task_timeout_loop_fn: Callable[[], None],
    heartbeat_prompt_loop_fn: Callable[[], None],
    codex_hook_loop_fn: Callable[[], None],
    distillation_daemon_loop_fn: Callable[[], None],
    idle_agent_task_pusher_fn: Callable[[], None],
    idle_watchdog_auto_assign_fn: Callable[[], None],
    buddy_knowledge_loop_fn: Callable[[], None],
    run_websocket_server_fn: Callable[[], None],
    restart_wake_enabled_fn: Callable[[], bool],
    start_restart_wake_thread_fn: Callable[[], None],
    start_supervisor_daemon_fn: Callable[[], None],
) -> None:
    global _REGISTERED_AGENTS, _AGENT_BUSY, _AGENT_ACTIVITIES, _AGENT_STATE_LOCK
    global _TASKS, _TASK_LOCK, _PORT_GETTER, _AGENT_IS_LIVE_FN
    global _AUTO_GEN_WATCHER, _AGENT_HEALTH_CHECKER, _HEALTH_MONITOR_LOOP
    global _CLI_OUTPUT_MONITOR_LOOP, _RATE_LIMIT_RESUME_LOOP, _V3_CLEANUP_LOOP
    global _TASK_TIMEOUT_LOOP, _HEARTBEAT_PROMPT_LOOP, _CODEX_HOOK_LOOP
    global _DISTILLATION_DAEMON_LOOP, _IDLE_AGENT_TASK_PUSHER
    global _IDLE_WATCHDOG_AUTO_ASSIGN, _BUDDY_KNOWLEDGE_LOOP
    global _RUN_WEBSOCKET_SERVER, _RESTART_WAKE_ENABLED
    global _START_RESTART_WAKE_THREAD, _START_SUPERVISOR_DAEMON

    _REGISTERED_AGENTS = registered_agents
    _AGENT_BUSY = agent_busy
    _AGENT_ACTIVITIES = agent_activities
    _AGENT_STATE_LOCK = agent_state_lock
    _TASKS = tasks
    _TASK_LOCK = task_lock
    _PORT_GETTER = port_getter
    _AGENT_IS_LIVE_FN = agent_is_live_fn
    _AUTO_GEN_WATCHER = auto_gen_watcher_fn
    _AGENT_HEALTH_CHECKER = agent_health_checker_fn
    _HEALTH_MONITOR_LOOP = health_monitor_loop_fn
    _CLI_OUTPUT_MONITOR_LOOP = cli_output_monitor_loop_fn
    _RATE_LIMIT_RESUME_LOOP = rate_limit_resume_loop_fn
    _V3_CLEANUP_LOOP = v3_cleanup_loop_fn
    _TASK_TIMEOUT_LOOP = task_timeout_loop_fn
    _HEARTBEAT_PROMPT_LOOP = heartbeat_prompt_loop_fn
    _CODEX_HOOK_LOOP = codex_hook_loop_fn
    _DISTILLATION_DAEMON_LOOP = distillation_daemon_loop_fn
    _IDLE_AGENT_TASK_PUSHER = idle_agent_task_pusher_fn
    _IDLE_WATCHDOG_AUTO_ASSIGN = idle_watchdog_auto_assign_fn
    _BUDDY_KNOWLEDGE_LOOP = buddy_knowledge_loop_fn
    _RUN_WEBSOCKET_SERVER = run_websocket_server_fn
    _RESTART_WAKE_ENABLED = restart_wake_enabled_fn
    _START_RESTART_WAKE_THREAD = start_restart_wake_thread_fn
    _START_SUPERVISOR_DAEMON = start_supervisor_daemon_fn


def _start_named_thread(target: Callable[[], None], name: str) -> threading.Thread:
    thread = threading.Thread(target=target, daemon=True, name=name)
    thread.start()
    return thread


def _is_agent_idle(agent_id: str) -> bool | None:
    """Check if agent is idle for automation scheduling.

    Returns True (idle), False (busy), None (offline).
    """
    if agent_id not in _REGISTERED_AGENTS:
        return None
    if _AGENT_BUSY.get(agent_id, False):
        return False
    activity = _AGENT_ACTIVITIES.get(agent_id)
    if not activity:
        return True
    ts_str = activity.get("timestamp", "")
    if not ts_str:
        return True
    try:
        last_ts = datetime.fromisoformat(ts_str)
        age = (datetime.now(timezone.utc) - last_ts).total_seconds()
        if age > 120:
            return True
        if activity.get("action") == "idle":
            return True
        return False
    except (ValueError, TypeError):
        return True


def _automation_condition_context() -> dict[str, Any]:
    agents: dict[str, dict[str, Any]] = {}
    with _AGENT_STATE_LOCK:
        registered = dict(_REGISTERED_AGENTS)
        activities = dict(_AGENT_ACTIVITIES)
        busy_map = dict(_AGENT_BUSY)
    for aid, reg in registered.items():
        online = bool(reg) and _AGENT_IS_LIVE_FN(aid, stale_seconds=120.0, reg=reg)
        last_activity_seconds: float | None = None
        activity = activities.get(aid) or {}
        ts_str = str(activity.get("timestamp", "") or "").strip()
        if ts_str:
            try:
                last_ts = datetime.fromisoformat(ts_str)
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                last_activity_seconds = (datetime.now(timezone.utc) - last_ts).total_seconds()
            except (ValueError, TypeError):
                last_activity_seconds = None
        agents[aid] = {
            "online": online,
            "busy": bool(busy_map.get(aid, False)),
            "last_activity_seconds": last_activity_seconds,
        }
    with _TASK_LOCK:
        tasks_snapshot = [dict(task) for task in _TASKS.values()]
    return {"agents": agents, "tasks": tasks_snapshot}


def _start_automation_scheduler() -> None:
    try:
        import automation_engine

        automation_engine.init_automations(
            server_port=_PORT_GETTER(),
            idle_check_callback=_is_agent_idle,
            condition_context_callback=_automation_condition_context,
        )
        print(f"[automation] Scheduler started (port={_PORT_GETTER()}, idle_check=ON)")
    except Exception as exc:
        print(f"[automation] WARNING: Failed to start scheduler: {exc}")


def start_background_services() -> list[threading.Thread]:
    threads = [
        _start_named_thread(_AUTO_GEN_WATCHER, "auto-gen-watcher"),
        _start_named_thread(_AGENT_HEALTH_CHECKER, "agent-health-checker"),
        _start_named_thread(_HEALTH_MONITOR_LOOP, "health-monitor"),
        _start_named_thread(_CLI_OUTPUT_MONITOR_LOOP, "cli-output-monitor"),
        _start_named_thread(_RATE_LIMIT_RESUME_LOOP, "rate-limit-resume"),
        _start_named_thread(_V3_CLEANUP_LOOP, "v3-cleanup"),
        _start_named_thread(_TASK_TIMEOUT_LOOP, "task-timeout-checker"),
    ]

    _start_automation_scheduler()

    threads.extend(
        [
            _start_named_thread(_HEARTBEAT_PROMPT_LOOP, "heartbeat-prompter"),
            _start_named_thread(_CODEX_HOOK_LOOP, "codex-cli-hook"),
            _start_named_thread(_DISTILLATION_DAEMON_LOOP, "distillation-daemon"),
            _start_named_thread(_IDLE_AGENT_TASK_PUSHER, "task-pusher"),
            _start_named_thread(_IDLE_WATCHDOG_AUTO_ASSIGN, "auto-assign"),
            _start_named_thread(_BUDDY_KNOWLEDGE_LOOP, "buddy-knowledge"),
            _start_named_thread(_RUN_WEBSOCKET_SERVER, "websocket-server"),
        ]
    )

    print("[codex-cli-hook] Gestartet (interval=15s, cooldown=20s)")
    print("[distillation-daemon] Gestartet (interval=4h, initial_delay=10min)")

    if _RESTART_WAKE_ENABLED():
        _START_RESTART_WAKE_THREAD()
    else:
        print("[restart] WAKE skipped: cold start / no restart marker propagated")

    _START_SUPERVISOR_DAEMON()
    return threads
