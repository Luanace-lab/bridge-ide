from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable

_PROCESS_SUPERVISOR_STATE: dict[str, dict[str, Any]] = {}
_SUPERVISOR_INTERVAL = 30  # Sekunden

_BACKEND_DIR = ""
_AGENT_LOG_DIR = ""
_read_pid_file_cb: Callable[[str], int | None] | None = None
_pid_alive_cb: Callable[[int], bool] | None = None
_pgrep_cb: Callable[[str], int | None] | None = None
_resolve_forwarder_session_name_cb: Callable[[], str] | None = None
_tmux_session_name_exists_cb: Callable[[str], bool] | None = None
_send_health_alert_cb: Callable[..., None] | None = None
_append_message_cb: Callable[[str, str, str], Any] | None = None
_system_status_getter: Callable[[], dict[str, Any]] | None = None


def init(
    *,
    pid_dir: str,
    backend_dir: str,
    agent_log_dir: str,
    read_pid_file: Callable[[str], int | None],
    pid_alive: Callable[[int], bool],
    pgrep: Callable[[str], int | None],
    resolve_forwarder_session_name: Callable[[], str],
    tmux_session_name_exists: Callable[[str], bool],
    send_health_alert: Callable[..., None],
    append_message: Callable[[str, str, str], Any],
    system_status_getter: Callable[[], dict[str, Any]],
) -> None:
    global _BACKEND_DIR, _AGENT_LOG_DIR
    global _read_pid_file_cb, _pid_alive_cb, _pgrep_cb
    global _resolve_forwarder_session_name_cb, _tmux_session_name_exists_cb
    global _send_health_alert_cb, _append_message_cb, _system_status_getter

    _BACKEND_DIR = backend_dir
    _AGENT_LOG_DIR = agent_log_dir
    _read_pid_file_cb = read_pid_file
    _pid_alive_cb = pid_alive
    _pgrep_cb = pgrep
    _resolve_forwarder_session_name_cb = resolve_forwarder_session_name
    _tmux_session_name_exists_cb = tmux_session_name_exists
    _send_health_alert_cb = send_health_alert
    _append_message_cb = append_message
    _system_status_getter = system_status_getter

    existing_restart_times = {
        name: list(cfg.get("restart_times", []))
        for name, cfg in _PROCESS_SUPERVISOR_STATE.items()
    }
    new_state = {
        "watcher": {
            "pid_file": os.path.join(pid_dir, "watcher.pid"),
            "command": ["python3", "-u", os.path.join(backend_dir, "bridge_watcher.py")],
            "max_restarts": 5,
            "restart_window": 3600,
            "restart_times": existing_restart_times.get("watcher", []),
        },
        "forwarder": {
            "pid_file": os.path.join(pid_dir, "output_forwarder.pid"),
            "command": ["python3", "-u", os.path.join(backend_dir, "output_forwarder.py")],
            "max_restarts": 5,
            "restart_window": 3600,
            "restart_times": existing_restart_times.get("forwarder", []),
        },
    }
    _PROCESS_SUPERVISOR_STATE.clear()
    _PROCESS_SUPERVISOR_STATE.update(new_state)


def _system_status() -> dict[str, Any]:
    if _system_status_getter is None:
        return {}
    return _system_status_getter()


def _send_health_alert(
    key: str, severity: str, message: str, now: float, *, force: bool = False
) -> None:
    if _send_health_alert_cb is None:
        return
    _send_health_alert_cb(key, severity, message, now, force=force)


def _append_message(sender: str, target: str, message: str) -> None:
    if _append_message_cb is None:
        return
    _append_message_cb(sender, target, message)


def _supervisor_check_and_restart() -> None:
    """Check watcher/forwarder processes, auto-restart if dead."""
    if (
        _read_pid_file_cb is None
        or _pid_alive_cb is None
        or _pgrep_cb is None
        or _resolve_forwarder_session_name_cb is None
        or _tmux_session_name_exists_cb is None
    ):
        raise RuntimeError("daemons.supervisor not initialized")

    now = time.time()
    for name, cfg in _PROCESS_SUPERVISOR_STATE.items():
        pid = _read_pid_file_cb(cfg["pid_file"])

        if not pid or not _pid_alive_cb(pid):
            pid = _pgrep_cb(os.path.basename(cfg["command"][-1]))

        if pid and _pid_alive_cb(pid):
            stored_pid = _read_pid_file_cb(cfg["pid_file"])
            if stored_pid != pid:
                try:
                    with open(cfg["pid_file"], "w") as f:
                        f.write(str(pid))
                except Exception:
                    pass
            continue

        cfg["restart_times"] = [
            t for t in cfg["restart_times"]
            if now - t < cfg["restart_window"]
        ]

        if len(cfg["restart_times"]) >= cfg["max_restarts"]:
            _send_health_alert(
                f"supervisor:{name}",
                "critical",
                f"[CRITICAL] {name} ist {cfg['max_restarts']}x in "
                f"{cfg['restart_window']//60} Min gestorben. "
                f"Kein weiterer Auto-Restart. Manueller Eingriff noetig.",
                now,
                force=True,
            )
            try:
                _append_message(
                    "system",
                    "user",
                    f"[CRITICAL] {name} Supervisor: Max Restarts erreicht. Manuell eingreifen.",
                )
            except Exception:
                pass
            continue

        try:
            log_path = os.path.join(_AGENT_LOG_DIR, f"{name}.log")
            log_fh = open(log_path, "a")
            popen_env = None
            command = cfg["command"]
            if name == "forwarder":
                forwarder_session = _resolve_forwarder_session_name_cb()
                if not _tmux_session_name_exists_cb(forwarder_session):
                    log_fh.write(
                        f"[forwarder {time.strftime('%H:%M:%S')}] "
                        f"supervisor skip: tmux session '{forwarder_session}' missing\n"
                    )
                    log_fh.flush()
                    log_fh.close()
                    continue
                popen_env = dict(os.environ)
                popen_env["FORWARDER_SESSION"] = forwarder_session
            proc = subprocess.Popen(
                command,
                cwd=_BACKEND_DIR,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                env=popen_env,
            )
            log_fh.close()
            with open(cfg["pid_file"], "w") as f:
                f.write(str(proc.pid))

            cfg["restart_times"].append(now)
            restart_count = len(cfg["restart_times"])

            msg = (
                f"[AUTO-RESTART] {name} war down. "
                f"Automatisch neu gestartet (PID {proc.pid}). "
                f"Neustart #{restart_count} in der letzten Stunde."
            )
            try:
                _append_message("system", "user", msg)
            except Exception:
                pass
            print(f"[supervisor] {name} restarted, PID={proc.pid}")

        except Exception as exc:
            try:
                _append_message(
                    "system",
                    "user",
                    f"[CRITICAL] {name} Neustart GESCHEITERT: {exc}",
                )
            except Exception:
                pass


def _supervisor_daemon_loop() -> None:
    """Periodically check watcher/forwarder and auto-restart when needed."""
    time.sleep(10)
    while True:
        try:
            if _system_status().get("shutting_down"):
                break
            _supervisor_check_and_restart()
        except Exception as exc:
            print(f"[supervisor-daemon] Error: {exc}", file=sys.stderr)
        time.sleep(_SUPERVISOR_INTERVAL)


def _start_supervisor_daemon() -> None:
    """Start the watchdog/forwarder supervisor daemon thread."""
    t = threading.Thread(target=_supervisor_daemon_loop, daemon=True, name="supervisor-daemon")
    t.start()
    print(f"[supervisor-daemon] Gestartet (interval={_SUPERVISOR_INTERVAL}s)")
