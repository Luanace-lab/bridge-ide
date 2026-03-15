from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

AUTO_GEN_PENDING: dict[str, dict[str, Any]] = {}
AUTO_GEN_LOCK = threading.Lock()

_msg_lock: threading.Lock | None = None
_messages: list[dict[str, Any]] | None = None
_team_lead_id = "teamlead"
_ensure_parent_dir_cb: Callable[[str], None] | None = None


def init(
    *,
    msg_lock: threading.Lock,
    messages: list[dict[str, Any]],
    team_lead_id: str,
    ensure_parent_dir: Callable[[str], None],
) -> None:
    global _msg_lock, _messages, _team_lead_id, _ensure_parent_dir_cb
    _msg_lock = msg_lock
    _messages = messages
    _team_lead_id = team_lead_id
    _ensure_parent_dir_cb = ensure_parent_dir


def _auto_gen_tick(now: float | None = None) -> list[str]:
    if _msg_lock is None or _messages is None or _ensure_parent_dir_cb is None:
        raise RuntimeError("daemons.auto_gen not initialized")

    with AUTO_GEN_LOCK:
        if not AUTO_GEN_PENDING:
            return []
        pending = dict(AUTO_GEN_PENDING)
    with _msg_lock:
        msgs = list(_messages)

    now_ts = now if now is not None else time.time()
    written: list[str] = []
    for key, req in list(pending.items()):
        trigger_id = int(req["msg_id"])
        file_path = str(req["file_path"])
        ts = float(req["ts"])
        if now_ts - ts > 120:
            with AUTO_GEN_LOCK:
                AUTO_GEN_PENDING.pop(key, None)
            continue
        for msg in msgs:
            if int(msg.get("id", -1)) <= trigger_id:
                continue
            if str(msg.get("from", "")).strip() != _team_lead_id:
                continue
            msg_to = str(msg.get("to", "")).strip()
            if msg_to and msg_to not in ("user", "all", "system"):
                continue
            content = str(msg.get("content", "")).strip()
            if not content or len(content) < 50:
                continue
            try:
                _ensure_parent_dir_cb(file_path)
                Path(file_path).write_text(content, encoding="utf-8")
                print(f"[auto-gen] written: {file_path}")
                written.append(file_path)
            except OSError as exc:
                print(f"[auto-gen] error writing {file_path}: {exc}")
            with AUTO_GEN_LOCK:
                AUTO_GEN_PENDING.pop(key, None)
            break
    return written


def _auto_gen_watcher() -> None:
    """Background thread: watches for teamlead responses to auto-generate requests, writes file."""
    while True:
        time.sleep(1.5)
        _auto_gen_tick()
