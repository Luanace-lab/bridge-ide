from __future__ import annotations

import time
from typing import Any, Callable

_HEALTH_MONITOR_INTERVAL = 60
_HEALTH_ALERT_COOLDOWN = 300
_CONTEXT_THRESHOLDS = [
    (95, "critical", "EMERGENCY: Context bei {pct}% — Agent faellt gleich aus!"),
    (90, "critical", "CRITICAL: Context bei {pct}% — Compact dringend empfohlen."),
    (80, "warn", "WARN: Context bei {pct}% — Aufmerksamkeit erforderlich."),
]

_health_prev_status: dict[str, str] = {}
_health_last_alert: dict[str, float] = {}
_context_last_alert_level: dict[str, int] = {}

_compute_health_cb: Callable[[], dict[str, Any]] | None = None
_supervisor_check_and_restart_cb: Callable[[], None] | None = None
_append_message_cb: Callable[[str, str, str], Any] | None = None
_ws_broadcast_cb: Callable[[str, dict[str, Any]], Any] | None = None
_agent_state_lock: Any = None
_registered_agents: dict[str, dict[str, Any]] | None = None
_agent_is_live_cb: Callable[..., bool] | None = None


def init(
    *,
    compute_health: Callable[[], dict[str, Any]],
    supervisor_check_and_restart: Callable[[], None],
    append_message: Callable[[str, str, str], Any],
    ws_broadcast: Callable[[str, dict[str, Any]], Any],
    agent_state_lock: Any,
    registered_agents: dict[str, dict[str, Any]],
    agent_is_live: Callable[..., bool],
) -> None:
    global _compute_health_cb, _supervisor_check_and_restart_cb
    global _append_message_cb, _ws_broadcast_cb
    global _agent_state_lock, _registered_agents, _agent_is_live_cb

    _compute_health_cb = compute_health
    _supervisor_check_and_restart_cb = supervisor_check_and_restart
    _append_message_cb = append_message
    _ws_broadcast_cb = ws_broadcast
    _agent_state_lock = agent_state_lock
    _registered_agents = registered_agents
    _agent_is_live_cb = agent_is_live


def _append_message(sender: str, target: str, message: str) -> None:
    if _append_message_cb is None:
        return
    _append_message_cb(sender, target, message)


def _ws_broadcast(event_type: str, payload: dict[str, Any]) -> None:
    if _ws_broadcast_cb is None:
        return
    _ws_broadcast_cb(event_type, payload)


def _health_monitor_loop() -> None:
    """Background thread: runs health checks and sends alerts."""
    time.sleep(15)
    while True:
        try:
            _health_monitor_tick()
        except Exception as exc:
            print(f"[health-monitor] Error: {exc}")
        time.sleep(_HEALTH_MONITOR_INTERVAL)


def _health_monitor_tick() -> None:
    """Single iteration of the health monitor."""
    if _compute_health_cb is None or _supervisor_check_and_restart_cb is None:
        raise RuntimeError("daemons.health_monitor not initialized")

    health = _compute_health_cb()
    components = health.get("components", {})
    now = time.time()

    for comp_name, comp_data in components.items():
        if comp_name == "agents":
            for agent_id, agent_info in comp_data.items():
                key = f"agent:{agent_id}"
                status = agent_info.get("status", "ok")
                _health_check_component(key, status, agent_info, now)
                _check_context_thresholds(agent_id, agent_info.get("context_pct"))
        else:
            status = comp_data.get("status", "ok")
            _health_check_component(comp_name, status, comp_data, now)

    _supervisor_check_and_restart_cb()


def _health_check_component(key: str, status: str, details: dict[str, Any], now: float) -> None:
    """Check a single component, send alert or recovery as needed."""
    prev = _health_prev_status.get(key, "ok")
    _health_prev_status[key] = status

    severity = "critical" if status in ("fail", "critical") else status
    prev_severity = "critical" if prev in ("fail", "critical") else prev

    if prev_severity in ("warn", "critical") and severity == "ok":
        _send_health_alert(
            key,
            "recovery",
            f"[RECOVERY] {key} wieder ok (vorher: {prev}).",
            now,
            force=True,
        )
        _health_last_alert.pop(key, None)
        return

    if severity == "ok":
        return

    if severity != prev_severity:
        detail_str = ", ".join(f"{k}={v}" for k, v in details.items() if k != "status")
        _send_health_alert(
            key,
            severity,
            f"[{severity.upper()}] {key}: {detail_str}",
            now,
            force=True,
        )
        return

    last = _health_last_alert.get(key, 0)
    if now - last >= _HEALTH_ALERT_COOLDOWN:
        detail_str = ", ".join(f"{k}={v}" for k, v in details.items() if k != "status")
        _send_health_alert(key, severity, f"[{severity.upper()}] {key}: {detail_str}", now)


def _send_health_alert(
    key: str, severity: str, message: str, now: float, *, force: bool = False
) -> None:
    """Send alert message from 'system' to Ordo (and user on critical)."""
    if not force:
        last = _health_last_alert.get(key, 0)
        if now - last < _HEALTH_ALERT_COOLDOWN:
            return
    _health_last_alert[key] = now

    try:
        _append_message("system", "ordo", message)
    except Exception as exc:
        print(f"[health-monitor] Failed to alert Ordo: {exc}")

    if severity == "critical":
        try:
            _append_message("system", "user", message)
        except Exception as exc:
            print(f"[health-monitor] Failed to alert user: {exc}")

    print(f"[health-monitor] {message}")


def _check_context_thresholds(agent_id: str, ctx_pct: int | None) -> None:
    """Check context usage and escalate alerts at 80%, 90%, 95%."""
    if ctx_pct is None:
        return
    for threshold, severity, msg_template in _CONTEXT_THRESHOLDS:
        if ctx_pct >= threshold:
            last_level = _context_last_alert_level.get(agent_id, 0)
            if threshold > last_level:
                _context_last_alert_level[agent_id] = threshold
                msg = f"[CONTEXT] {agent_id}: {msg_template.format(pct=ctx_pct)}"
                try:
                    _append_message("system", "ordo", msg)
                except Exception:
                    pass
                try:
                    _append_message("system", agent_id, msg)
                except Exception:
                    pass
                if severity == "critical" and _registered_agents is not None and _agent_state_lock is not None and _agent_is_live_cb is not None:
                    with _agent_state_lock:
                        active_agents = [
                            aid
                            for aid, reg in _registered_agents.items()
                            if aid != agent_id
                            and aid != "ordo"
                            and _agent_is_live_cb(aid, stale_seconds=120.0, reg=reg)
                        ]
                    for target in active_agents:
                        try:
                            _append_message("system", target, msg)
                        except Exception:
                            pass
                _ws_broadcast(
                    "context_alert",
                    {
                        "agent_id": agent_id,
                        "context_pct": ctx_pct,
                        "threshold": threshold,
                        "severity": severity,
                    },
                )
            break
    else:
        _context_last_alert_level.pop(agent_id, None)
