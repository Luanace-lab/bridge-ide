from __future__ import annotations

import time
from typing import Callable

_V3_CLEANUP_INTERVAL = 60
_TASK_TIMEOUT_INTERVAL = 30

_cleanup_expired_scope_locks_cb: Callable[[], int] | None = None
_cleanup_expired_whiteboard_cb: Callable[[], int] | None = None
_check_task_timeouts_cb: Callable[[], None] | None = None


def init(
    *,
    cleanup_expired_scope_locks: Callable[[], int],
    cleanup_expired_whiteboard: Callable[[], int],
    check_task_timeouts: Callable[[], None],
) -> None:
    global _cleanup_expired_scope_locks_cb
    global _cleanup_expired_whiteboard_cb
    global _check_task_timeouts_cb

    _cleanup_expired_scope_locks_cb = cleanup_expired_scope_locks
    _cleanup_expired_whiteboard_cb = cleanup_expired_whiteboard
    _check_task_timeouts_cb = check_task_timeouts


def _maintenance_cleanup_tick() -> tuple[int, int]:
    if _cleanup_expired_scope_locks_cb is None or _cleanup_expired_whiteboard_cb is None:
        raise RuntimeError("daemons.maintenance cleanup not initialized")
    sl_removed = _cleanup_expired_scope_locks_cb()
    wb_removed = _cleanup_expired_whiteboard_cb()
    return sl_removed, wb_removed


def _v3_cleanup_loop() -> None:
    while True:
        time.sleep(_V3_CLEANUP_INTERVAL)
        try:
            sl_removed, wb_removed = _maintenance_cleanup_tick()
            if sl_removed or wb_removed:
                print(f"[v3-cleanup] Removed {sl_removed} scope-lock(s), {wb_removed} whiteboard entry/ies")
        except Exception as exc:
            print(f"[v3-cleanup] Error: {exc}")


def _task_timeout_tick() -> None:
    if _check_task_timeouts_cb is None:
        raise RuntimeError("daemons.maintenance task timeout not initialized")
    _check_task_timeouts_cb()


def _task_timeout_loop() -> None:
    while True:
        time.sleep(_TASK_TIMEOUT_INTERVAL)
        try:
            _task_timeout_tick()
        except Exception as exc:
            print(f"[task-timeout] Error: {exc}")
