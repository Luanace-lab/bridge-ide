from __future__ import annotations

import os
import signal
import threading
from pathlib import Path
from typing import Any, Callable

RESTART_STATE: dict[str, Any] = {
    "phase": None,
    "started_at": None,
    "checkpoints": {},
    "warn_seconds": 60,
    "stop_seconds": 30,
    "reason": "",
    "restart_id": None,
    "agents_mode": "restart",
}
RESTART_LOCK = threading.Lock()
RESTART_MARKER = "/tmp/bridge_restart_requested"
_RESTART_WARN_MARKER = "/tmp/bridge_restart_warn"
_RESTART_TIMERS: dict[str, threading.Timer] = {}

_REFLECTION_PROMPT = (
    "[SESSION-END REFLECTION] Server-Restart steht bevor. "
    "Bevor du deinen Kontext sicherst, reflektiere kurz: "
    "Rufe bridge_reflect() auf und speichere wichtige Erkenntnisse mit bridge_lesson_add(). "
    "Was hast du heute gelernt? Was wuerdest du naechstes Mal anders machen?"
)

_registered_agents_snapshot_cb: Callable[[], dict[str, Any]] | None = None
_agent_is_live_cb: Callable[[str], bool] | None = None
_get_agent_engine_cb: Callable[[str], str] | None = None
_append_message_cb: Callable[..., Any] | None = None
_ws_broadcast_cb: Callable[[str, dict[str, Any]], None] | None = None
_utc_now_iso_cb: Callable[[], str] | None = None
_interrupt_agent_cb: Callable[[str, str], Any] | None = None
_team_config_getter: Callable[[], dict[str, Any] | None] | None = None


def init(
    *,
    registered_agents_snapshot: Callable[[], dict[str, Any]],
    agent_is_live: Callable[[str], bool],
    get_agent_engine: Callable[[str], str],
    append_message: Callable[..., Any],
    ws_broadcast: Callable[[str, dict[str, Any]], None],
    utc_now_iso: Callable[[], str],
    interrupt_agent: Callable[[str, str], Any],
    team_config_getter: Callable[[], dict[str, Any] | None],
) -> None:
    global _registered_agents_snapshot_cb, _agent_is_live_cb, _get_agent_engine_cb
    global _append_message_cb, _ws_broadcast_cb, _utc_now_iso_cb
    global _interrupt_agent_cb, _team_config_getter

    _registered_agents_snapshot_cb = registered_agents_snapshot
    _agent_is_live_cb = agent_is_live
    _get_agent_engine_cb = get_agent_engine
    _append_message_cb = append_message
    _ws_broadcast_cb = ws_broadcast
    _utc_now_iso_cb = utc_now_iso
    _interrupt_agent_cb = interrupt_agent
    _team_config_getter = team_config_getter


def _get_active_agent_ids() -> set[str]:
    if _registered_agents_snapshot_cb is None or _agent_is_live_cb is None:
        raise RuntimeError("daemons.restart_control not initialized")
    return {
        agent_id
        for agent_id in _registered_agents_snapshot_cb().keys()
        if _agent_is_live_cb(agent_id)
    }


def _cancel_restart_timers() -> None:
    for _name, timer in list(_RESTART_TIMERS.items()):
        timer.cancel()
    _RESTART_TIMERS.clear()


def _trigger_session_end_reflection(active_agents: set[str]) -> None:
    if _append_message_cb is None or _get_agent_engine_cb is None:
        raise RuntimeError("daemons.restart_control not initialized")
    for agent_id in active_agents:
        _ = _get_agent_engine_cb(agent_id)
        try:
            _append_message_cb(
                "system",
                agent_id,
                _REFLECTION_PROMPT,
                meta={"type": "reflection_trigger"},
            )
        except Exception as exc:
            print(f"[reflection] Error sending to {agent_id}: {exc}")
    if active_agents:
        print(f"[reflection] Session-end reflection triggered for {len(active_agents)} agents")


def _restart_warn_phase(reason: str, warn_seconds: int, stop_seconds: int) -> None:
    required = [_append_message_cb, _ws_broadcast_cb, _utc_now_iso_cb]
    if any(item is None for item in required):
        raise RuntimeError("daemons.restart_control not initialized")

    with RESTART_LOCK:
        RESTART_STATE["phase"] = "warn"
        RESTART_STATE["started_at"] = _utc_now_iso_cb()
        RESTART_STATE["checkpoints"] = {}
        RESTART_STATE["reason"] = reason
        RESTART_STATE["warn_seconds"] = warn_seconds
        RESTART_STATE["stop_seconds"] = stop_seconds

    try:
        Path(_RESTART_WARN_MARKER).write_text(f"{warn_seconds}", encoding="utf-8")
    except OSError:
        pass

    active = _get_active_agent_ids()
    _append_message_cb(
        "system",
        "all",
        f"[RESTART WARN] Server-Restart in {warn_seconds} Sekunden. "
        f"Grund: {reason}. "
        "PFLICHT: Sichert euren Zustand (CONTEXT_BRIDGE.md / Memory). "
        "Bestaetigt mit bridge_activity(action='checkpoint_saved').",
        meta={"type": "restart_warn", "seconds": warn_seconds, "reason": reason},
    )
    _ws_broadcast_cb(
        "restart_warn",
        {"seconds": warn_seconds, "reason": reason, "active_agents": sorted(active)},
    )
    print(f"[restart] WARN phase started: {warn_seconds}s, reason={reason}, active={sorted(active)}")

    _trigger_session_end_reflection(active)

    timer = threading.Timer(warn_seconds, _restart_stop_phase, args=[stop_seconds])
    timer.daemon = True
    timer.start()
    _RESTART_TIMERS["warn_to_stop"] = timer


def _restart_stop_phase(stop_seconds: int) -> None:
    required = [_append_message_cb, _ws_broadcast_cb, _utc_now_iso_cb]
    if any(item is None for item in required):
        raise RuntimeError("daemons.restart_control not initialized")

    with RESTART_LOCK:
        RESTART_STATE["phase"] = "stop"
        RESTART_STATE["started_at"] = _utc_now_iso_cb()

    _append_message_cb(
        "system",
        "all",
        f"[RESTART STOP] Server stoppt in {stop_seconds} Sekunden. "
        "Beendet aktuelle Arbeit JETZT.",
        meta={"type": "restart_stop", "seconds": stop_seconds},
    )
    _ws_broadcast_cb("restart_stop", {"seconds": stop_seconds})
    print(f"[restart] STOP phase started: {stop_seconds}s")

    timer = threading.Timer(stop_seconds, _restart_kill_phase)
    timer.daemon = True
    timer.start()
    _RESTART_TIMERS["stop_to_kill"] = timer


def _restart_kill_phase() -> None:
    if _interrupt_agent_cb is None or _team_config_getter is None:
        raise RuntimeError("daemons.restart_control not initialized")

    with RESTART_LOCK:
        RESTART_STATE["phase"] = "kill"
        agents_mode = RESTART_STATE.get("agents_mode", "restart")

    print("[restart] KILL phase started")

    try:
        Path(_RESTART_WARN_MARKER).unlink(missing_ok=True)
    except OSError:
        pass

    if agents_mode != "keep":
        active = _get_active_agent_ids()
        engine_map: dict[str, str] = {}
        team_config = _team_config_getter() or {}
        for agent in team_config.get("agents", []):
            agent_id = agent.get("id", "")
            if agent_id:
                engine_map[agent_id] = agent.get("engine", "claude") or "claude"
        for agent_id in active:
            try:
                engine = engine_map.get(agent_id, "claude")
                result = _interrupt_agent_cb(agent_id, engine=engine)
                print(f"[restart] Interrupted agent {agent_id}: {result}")
            except Exception as exc:
                print(f"[restart] Failed to interrupt {agent_id}: {exc}")

    print("[restart] Watcher/Forwarder bleiben aktiv (auto-reconnect).")

    try:
        Path(RESTART_MARKER).write_text(RESTART_STATE.get("reason", "requested"), encoding="utf-8")
    except OSError as exc:
        print(f"[restart] Failed to write marker: {exc}")

    with RESTART_LOCK:
        RESTART_STATE["phase"] = "restarting"

    print("[restart] Server exiting for restart (wrapper will restart)...")
    os.kill(os.getpid(), signal.SIGTERM)


def _restart_cancel() -> dict[str, Any]:
    required = [_append_message_cb, _ws_broadcast_cb]
    if any(item is None for item in required):
        raise RuntimeError("daemons.restart_control not initialized")

    with RESTART_LOCK:
        phase = RESTART_STATE["phase"]
        if phase not in ("warn", "stop"):
            return {"ok": False, "error": f"cannot cancel in phase '{phase}'"}

        _cancel_restart_timers()
        old_phase = RESTART_STATE["phase"]
        RESTART_STATE["phase"] = None
        RESTART_STATE["started_at"] = None
        RESTART_STATE["checkpoints"] = {}
        RESTART_STATE["reason"] = ""
        RESTART_STATE["restart_id"] = None

    try:
        Path(_RESTART_WARN_MARKER).unlink(missing_ok=True)
    except OSError:
        pass

    _append_message_cb(
        "system",
        "all",
        f"[RESTART ABGEBROCHEN] Restart wurde abgebrochen (war in Phase '{old_phase}').",
        meta={"type": "restart_cancel"},
    )
    _ws_broadcast_cb("restart_cancel", {"cancelled_phase": old_phase})
    print(f"[restart] Cancelled from phase '{old_phase}'")
    return {"ok": True, "cancelled_phase": old_phase}


def _restart_reset() -> dict[str, Any]:
    with RESTART_LOCK:
        old_phase = RESTART_STATE["phase"]
        RESTART_STATE["phase"] = None
        RESTART_STATE["started_at"] = None
        RESTART_STATE["checkpoints"] = {}
        RESTART_STATE["reason"] = ""
        RESTART_STATE["restart_id"] = None
    print(f"[restart] State reset from '{old_phase}' to None")
    return {"ok": True, "previous_phase": old_phase}


def _restart_force(stop_seconds: int) -> dict[str, Any]:
    with RESTART_LOCK:
        phase = RESTART_STATE["phase"]
        if phase in ("kill", "restarting"):
            return {"ok": False, "error": f"already in phase '{phase}'"}
        if phase == "warn":
            _cancel_restart_timers()

    _restart_stop_phase(stop_seconds)
    return {"ok": True, "phase": "stop", "seconds": stop_seconds}


def _check_all_checkpoints_saved() -> bool:
    advance = False
    stop_seconds = 30
    with RESTART_LOCK:
        if RESTART_STATE["phase"] != "warn":
            return False
        active = _get_active_agent_ids()
        saved = set(RESTART_STATE["checkpoints"].keys())
        if active and active.issubset(saved):
            stop_seconds = int(RESTART_STATE.get("stop_seconds", 30))
            _cancel_restart_timers()
            advance = True
    if advance:
        print(f"[restart] All {len(active)} agents checkpointed — advancing to STOP")
        _restart_stop_phase(stop_seconds)
        return True
    return False
