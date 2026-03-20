"""Task CRUD, WAL, lease management, and escalation extracted from server.py (Slice 05).

This module owns:
- _persist_tasks / _load_tasks_from_disk / _count_agent_active_tasks
- _rotate_wal_if_needed / _append_task_transition_wal / _log_task_event
- _clear_task_lease / _refresh_task_lease
- _check_task_timeouts (timeout enforcement + escalation trigger)
- _escalate_stage_1/2/3 / _resolve_escalation / _persist_escalation_state
- _whiteboard_delete_by_task
- _task_required_capabilities

Anti-circular-import strategy:
  All shared state and cross-domain functions are injected via init().
  This module NEVER imports from server.
  Direct imports only from: handlers.messages, handlers.agents.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Module-local globals (fully owned here)
# ---------------------------------------------------------------------------
_TASK_WAL_LOCK = threading.Lock()
_TASK_WAL_MAX_BYTES = 10 * 1024 * 1024  # 10 MB — rotate beyond this

ESCALATION_CONFIG = {
    "reminder_timeout": 120,      # seconds after task timeout → Stage 1
    "direct_timeout": 120,        # seconds after Stage 1 → Stage 2
    "owner_timeout": 0,            # 0 = wait indefinitely for Owner decision at Stage 3
}
ESCALATION_STATE: dict[str, dict[str, Any]] = {}  # task_id → {stage, started_at, ...}
ESCALATION_LOCK = threading.Lock()

# Paths — set by init()
_TASK_PERSIST_FILE: str = ""
_TASK_TRANSITION_WAL_FILE: str = ""
_TASK_LIFECYCLE_LOG: str = ""
_ESCALATION_PERSIST_FILE: str = ""
_TASK_DEFAULT_ACK_DEADLINE: int = 300
_TASK_DEFAULT_MAX_RETRIES: int = 2

# ---------------------------------------------------------------------------
# Injected shared state (set by init())
# ---------------------------------------------------------------------------
_TASKS: dict[str, dict[str, Any]] = {}
_TASK_LOCK: Any = None
_WHITEBOARD: dict[str, dict[str, Any]] = {}
_WHITEBOARD_LOCK: Any = None

# ---------------------------------------------------------------------------
# Injected callbacks (set by init())
# ---------------------------------------------------------------------------
_ws_broadcast: Callable[..., Any] | None = None
_whiteboard_post: Callable[..., Any] | None = None
_refresh_scope_locks_for_task: Callable[[str], list] | None = None
_unlock_scope_paths: Callable[[str], list] | None = None
_log_whiteboard_event: Callable[..., Any] | None = None
_persist_whiteboard: Callable[..., Any] | None = None


def init(
    *,
    tasks: dict[str, dict[str, Any]],
    task_lock: Any,
    whiteboard: dict[str, dict[str, Any]],
    whiteboard_lock: Any,
    base_dir: str,
    agent_log_dir: str,
    task_default_ack_deadline: int,
    ws_broadcast_fn: Callable[..., Any],
    whiteboard_post_fn: Callable[..., Any],
    refresh_scope_locks_for_task_fn: Callable[[str], list],
    unlock_scope_paths_fn: Callable[[str], list],
    log_whiteboard_event_fn: Callable[..., Any],
    persist_whiteboard_fn: Callable[..., Any],
) -> None:
    """Bind shared state and cross-domain callbacks.  Must be called once
    before any other function in this module is used."""
    global _TASKS, _TASK_LOCK, _WHITEBOARD, _WHITEBOARD_LOCK
    global _TASK_PERSIST_FILE, _TASK_TRANSITION_WAL_FILE, _TASK_LIFECYCLE_LOG
    global _ESCALATION_PERSIST_FILE, _TASK_DEFAULT_ACK_DEADLINE, _TASK_DEFAULT_MAX_RETRIES
    global _ws_broadcast, _whiteboard_post
    global _refresh_scope_locks_for_task, _unlock_scope_paths
    global _log_whiteboard_event, _persist_whiteboard

    _TASKS = tasks
    _TASK_LOCK = task_lock
    _WHITEBOARD = whiteboard
    _WHITEBOARD_LOCK = whiteboard_lock

    _TASK_PERSIST_FILE = os.path.join(base_dir, "tasks.json")
    _TASK_TRANSITION_WAL_FILE = os.path.join(base_dir, "task_transition_wal.jsonl")
    _TASK_LIFECYCLE_LOG = os.path.join(agent_log_dir, "task_lifecycle.jsonl")
    _ESCALATION_PERSIST_FILE = os.path.join(base_dir, "escalation_state.json")
    _TASK_DEFAULT_ACK_DEADLINE = task_default_ack_deadline

    _ws_broadcast = ws_broadcast_fn
    _whiteboard_post = whiteboard_post_fn
    _refresh_scope_locks_for_task = refresh_scope_locks_for_task_fn
    _unlock_scope_paths = unlock_scope_paths_fn
    _log_whiteboard_event = log_whiteboard_event_fn
    _persist_whiteboard = persist_whiteboard_fn


# ===================================================================
# WAL (Write-Ahead Log)
# ===================================================================

def _rotate_wal_if_needed() -> None:
    """Rotate WAL file if it exceeds _TASK_WAL_MAX_BYTES. Caller must hold _TASK_WAL_LOCK."""
    try:
        if not os.path.exists(_TASK_TRANSITION_WAL_FILE):
            return
        size = os.path.getsize(_TASK_TRANSITION_WAL_FILE)
        if size < _TASK_WAL_MAX_BYTES:
            return
        ts = _utc_now_iso().replace(":", "-").replace("+", "z")[:19]
        archive = _TASK_TRANSITION_WAL_FILE + f".{ts}"
        os.rename(_TASK_TRANSITION_WAL_FILE, archive)
        print(f"[task-wal] Rotated WAL: {archive} ({size // 1024}KB)")
    except Exception as exc:
        print(f"[task-wal] WARNING: WAL rotation failed: {exc}")


def _append_task_transition_wal(
    task_id: str,
    event: str,
    actor: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append a task state transition to the WAL (Write-Ahead Log).

    Each line is a JSON record. Used for crash recovery and audit.
    Must be called AFTER _persist_tasks() so WAL is always at-least-as-new as snapshot.
    Thread-safe via _TASK_WAL_LOCK. Rotates file at _TASK_WAL_MAX_BYTES.
    """
    record = {
        "ts": _utc_now_iso(),
        "task_id": task_id,
        "event": event,
        "actor": actor,
        "before_state": before.get("state") if before else None,
        "after_state": after.get("state") if after else None,
        "meta": meta or {},
    }
    line = json.dumps(record, ensure_ascii=False) + "\n"
    try:
        with _TASK_WAL_LOCK:
            _rotate_wal_if_needed()
            with open(_TASK_TRANSITION_WAL_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as exc:
        print(f"[task-wal] WARNING: Failed to write WAL entry: {exc}")


# ===================================================================
# Task capabilities
# ===================================================================

def _task_required_capabilities(task: dict) -> list[str]:
    """Extract required_capabilities from a task dict, normalized to list[str]."""
    raw = task.get("required_capabilities")
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(c) for c in raw if c]
    if isinstance(raw, str):
        return [raw]
    return []


# ===================================================================
# Task persistence
# ===================================================================

def _persist_tasks() -> None:
    """Atomically persist TASKS dict to tasks.json.

    Must be called while holding TASK_LOCK.
    Persists ALL tasks including done/failed/verified/deleted — these may
    receive post-completion mutations (verify, delete metadata) that must
    survive restarts.
    """
    data = json.dumps(_TASKS, indent=2, ensure_ascii=False) + "\n"
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_TASK_PERSIST_FILE), suffix=".tmp")
        try:
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            os.replace(tmp, _TASK_PERSIST_FILE)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        pass  # Best-effort persistence — don't crash server


def _count_agent_active_tasks(agent_id: str, *, exclude_task_id: str | None = None) -> int:
    """Count claimed/acked tasks currently held by one agent.

    Caller must hold TASK_LOCK.
    """
    return sum(
        1
        for task_id, task in _TASKS.items()
        if task_id != exclude_task_id
        and task.get("assigned_to") == agent_id
        and task.get("state") in ("claimed", "acked")
    )


def _load_tasks_from_disk() -> None:
    """Load persisted tasks from tasks.json on server startup."""
    if not os.path.exists(_TASK_PERSIST_FILE):
        return
    try:
        with open(_TASK_PERSIST_FILE) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            _TASKS.update(loaded)
            print(f"[tasks] Loaded {len(loaded)} tasks from {_TASK_PERSIST_FILE}")
    except Exception as exc:
        print(f"[tasks] WARNING: Failed to load tasks from {_TASK_PERSIST_FILE}: {exc}")


# ===================================================================
# Task lifecycle log
# ===================================================================

def _log_task_event(task_id: str, event: str, agent_id: str = "", extra: dict[str, Any] | None = None) -> None:
    """Append a JSONL line to task lifecycle log."""
    entry: dict[str, Any] = {
        "ts": _utc_now_iso(),
        "task_id": task_id,
        "event": event,
    }
    if agent_id:
        entry["agent_id"] = agent_id
    if extra:
        entry.update(extra)
    try:
        with open(_TASK_LIFECYCLE_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Non-critical, don't fail requests


# ===================================================================
# Escalation persistence
# ===================================================================

def _persist_escalation_state() -> None:
    """Atomically persist ESCALATION_STATE to disk. Call while holding ESCALATION_LOCK."""
    data = json.dumps(ESCALATION_STATE, indent=2, ensure_ascii=False) + "\n"
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_ESCALATION_PERSIST_FILE), suffix=".tmp")
        try:
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            os.replace(tmp, _ESCALATION_PERSIST_FILE)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        pass  # Best-effort — don't crash server


def _load_escalation_state_from_disk() -> None:
    """Load persisted escalation state on server startup."""
    if not os.path.exists(_ESCALATION_PERSIST_FILE):
        return
    try:
        with open(_ESCALATION_PERSIST_FILE) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            with ESCALATION_LOCK:
                ESCALATION_STATE.update(loaded)
            print(f"[escalation] Loaded {len(loaded)} escalation entries from disk")
    except Exception as exc:
        print(f"[escalation] WARNING: Failed to load escalation state: {exc}")


# ===================================================================
# Lease management
# ===================================================================

def _clear_task_lease(task: dict[str, Any]) -> None:
    """Remove derived task-lease metadata without touching semantic task state."""
    task.pop("lease_refreshed_at", None)
    task.pop("lease_expires_at", None)


def _refresh_task_lease(task: dict[str, Any], ref_iso: str | None = None) -> None:
    """Refresh lease timestamps derived from timeout_seconds and a reference timestamp."""
    timeout_seconds = int(task.get("timeout_seconds", 1800) or 1800)
    ref_raw = str(ref_iso or task.get("last_checkin") or task.get("claimed_at") or _utc_now_iso())
    try:
        ref_dt = datetime.fromisoformat(ref_raw)
    except (ValueError, TypeError):
        ref_raw = _utc_now_iso()
        ref_dt = datetime.fromisoformat(ref_raw)
    task["lease_refreshed_at"] = ref_raw
    task["lease_expires_at"] = (ref_dt + timedelta(seconds=timeout_seconds)).isoformat()


# ===================================================================
# Whiteboard helper (task-scoped)
# ===================================================================

def _whiteboard_delete_by_task(task_id: str, entry_type: str = "alert") -> int:
    """Delete all whiteboard entries matching task_id and entry_type. Returns count deleted."""
    deleted = 0
    with _WHITEBOARD_LOCK:
        to_remove = [
            eid for eid, entry in _WHITEBOARD.items()
            if entry.get("task_id") == task_id and entry["type"] == entry_type
        ]
        for eid in to_remove:
            entry = _WHITEBOARD.pop(eid, None)
            if entry:
                _log_whiteboard_event("delete", entry)  # type: ignore[misc]
                deleted += 1
        if deleted:
            _persist_whiteboard()  # type: ignore[misc]
    return deleted


# ===================================================================
# Escalation stages
# ===================================================================

def _escalate_stage_1(task_id: str, task: dict[str, Any]) -> None:
    """Stage 1: Send reminder via Bridge message (invisible to the owner)."""
    from handlers.messages import append_message

    agent_id = task.get("assigned_to", "")
    title = task.get("title", task_id)
    print(f"[escalation] Stage 1 REMINDER for task '{title}' → agent '{agent_id}'")
    # Whiteboard: warning (the owner sees nothing per spec — but internal warning)
    _whiteboard_post("system", "alert", f"Ueberfaellig: {title}", task_id=task_id, task_title=title, severity="warning", ttl_seconds=600)  # type: ignore[misc]
    # Send bridge message to agent
    append_message("system", agent_id, f"[REMINDER] Aufgabe '{title}' ist ueberfaellig. Bitte melde Status via bridge_task_checkin.", meta={"type": "escalation_stage_1", "task_id": task_id})
    _ws_broadcast("task_timeout", {"task_id": task_id, "agent_id": agent_id, "stage": 1, "title": title})  # type: ignore[misc]


def _escalate_stage_2(task_id: str, task: dict[str, Any]) -> None:
    """Stage 2: Direct contact (invisible to the owner)."""
    from handlers.messages import append_message

    agent_id = task.get("assigned_to", "")
    title = task.get("title", task_id)
    print(f"[escalation] Stage 2 DIRECT CONTACT for task '{title}' → agent '{agent_id}'")
    _whiteboard_post("system", "alert", f"Ueberfaellig (Stufe 2): {title}", task_id=task_id, task_title=title, severity="warning", ttl_seconds=600)  # type: ignore[misc]
    append_message("system", agent_id, f"[DRINGEND] Aufgabe '{title}' ist ueberfaellig. Zweite Erinnerung. Reagiere jetzt.", meta={"type": "escalation_stage_2", "task_id": task_id})
    _ws_broadcast("task_timeout", {"task_id": task_id, "agent_id": agent_id, "stage": 2, "title": title})  # type: ignore[misc]


def _escalate_stage_3(task_id: str, task: dict[str, Any]) -> None:
    """Stage 3: the owner decides (critical alert in UI)."""
    agent_id = task.get("assigned_to", "")
    title = task.get("title", task_id)
    print(f"[escalation] Stage 3 OWNER DECIDES for task '{title}' → agent '{agent_id}'")
    _whiteboard_post("system", "alert", f"Aktion erforderlich: {agent_id} reagiert nicht auf '{title}'", task_id=task_id, task_title=title, severity="critical", priority=3, ttl_seconds=3600)  # type: ignore[misc]
    _ws_broadcast("escalation_stage_3", {  # type: ignore[misc]
        "task_id": task_id,
        "agent_id": agent_id,
        "title": title,
        "message": f"{agent_id} reagiert nicht auf '{title}'",
        "options": ["extend", "reassign", "cancel"],
    })


# ===================================================================
# Resolve escalation
# ===================================================================

def _resolve_escalation(task_id: str, action: str, reassign_to: str | None = None) -> dict[str, Any] | str:
    """Resolve a Stage 3 escalation. Returns result dict or error string."""
    from handlers.messages import append_message

    with ESCALATION_LOCK:
        esc = ESCALATION_STATE.get(task_id)
        if not esc or esc["stage"] != 3:
            return "no active Stage 3 escalation for this task"

    if action == "extend":
        # Give more time: reset timeout by updating last_checkin
        with _TASK_LOCK:
            task = _TASKS.get(task_id)
            if task:
                before_task = copy.deepcopy(task)
                task["last_checkin"] = _utc_now_iso()
                task["checkin_note"] = "Mehr Zeit (Owner-Entscheidung)"
                _refresh_task_lease(task, ref_iso=task["last_checkin"])
                _persist_tasks()
                _append_task_transition_wal(task_id, "escalation_extend", "user", before_task, task)
        _refresh_scope_locks_for_task(task_id)  # type: ignore[misc]
        with ESCALATION_LOCK:
            ESCALATION_STATE.pop(task_id, None)
            _persist_escalation_state()
        _whiteboard_delete_by_task(task_id, entry_type="alert")  # Cleanup Stage-3 alert
        _whiteboard_post("system", "status", f"Mehr Zeit: {esc.get('task_title', task_id)}", task_id=task_id, severity="info", ttl_seconds=300)  # type: ignore[misc]
        return {"action": "extend", "task_id": task_id}

    elif action == "reassign":
        if not reassign_to:
            return "reassign_to is required for 'reassign' action"
        with _TASK_LOCK:
            task = _TASKS.get(task_id)
            if not task:
                return "task not found"
            before_task = copy.deepcopy(task)
            old_agent = task.get("assigned_to", "")
            task["assigned_to"] = reassign_to
            task["state"] = "created"  # reset to created so new agent can claim
            task["last_checkin"] = None
            task["checkin_note"] = None
            _clear_task_lease(task)
            task["state_history"].append({"state": "reassigned", "at": _utc_now_iso(), "from": old_agent, "to": reassign_to})
            _persist_tasks()
            _append_task_transition_wal(task_id, "escalation_reassign", "user", before_task, task, {"from": old_agent, "to": reassign_to})
        with ESCALATION_LOCK:
            ESCALATION_STATE.pop(task_id, None)
            _persist_escalation_state()
        _whiteboard_delete_by_task(task_id, entry_type="alert")  # Cleanup Stage-3 alert
        _whiteboard_post("system", "status", f"Uebergeben: {esc.get('task_title', task_id)} → {reassign_to}", task_id=task_id, severity="info", ttl_seconds=300)  # type: ignore[misc]
        _ws_broadcast("task_reassigned", {"task_id": task_id, "from": old_agent, "to": reassign_to})  # type: ignore[misc]
        # Auto-Claim: notify new assignee with actionable instructions
        _ra_title = str(task.get("title", ""))[:200]
        _ra_desc = str(task.get("description", ""))[:300]
        _ra_creator = task.get("created_by", "unknown")
        append_message(
            "system", reassign_to,
            f"[TASK — REASSIGNED TO YOU] Aufgabe: '{_ra_title}' (ID: {task_id})\n"
            f"Vorheriger Agent: {old_agent}\n"
            f"Beschreibung: {_ra_desc}\n\n"
            f"SOFORT ausfuehren:\n"
            f"1. bridge_task_claim(task_id='{task_id}')\n"
            f"2. bridge_task_ack(task_id='{task_id}')\n"
            f"3. Task bearbeiten\n"
            f"4. bridge_task_done(task_id='{task_id}', result_summary='...')\n"
            f"5. Ergebnis an {_ra_creator} via bridge_send melden",
            meta={"type": "task_notification", "task_id": task_id},
        )
        return {"action": "reassign", "task_id": task_id, "from": old_agent, "to": reassign_to}

    elif action == "cancel":
        with _TASK_LOCK:
            task = _TASKS.get(task_id)
            if task:
                before_task = copy.deepcopy(task)
                task["state"] = "failed"
                task["failed_at"] = _utc_now_iso()
                _clear_task_lease(task)
                task["error"] = "Abgebrochen (Owner-Entscheidung)"
                task["state_history"].append({"state": "failed", "at": _utc_now_iso(), "by": "user", "error": "cancelled by the owner"})
                _persist_tasks()
                _append_task_transition_wal(task_id, "escalation_cancel", "user", before_task, task)
        with ESCALATION_LOCK:
            ESCALATION_STATE.pop(task_id, None)
            _persist_escalation_state()
        # Release scope locks
        released = _unlock_scope_paths(task_id)  # type: ignore[misc]
        for rl in released:
            _ws_broadcast("scope_unlocked", {"path": rl["path"], "agent_id": rl["agent_id"], "task_id": task_id})  # type: ignore[misc]
        _whiteboard_delete_by_task(task_id, entry_type="alert")  # Cleanup Stage-3 alert
        _whiteboard_post("system", "result", f"Abgebrochen: {esc.get('task_title', task_id)}", task_id=task_id, severity="info", ttl_seconds=300)  # type: ignore[misc]
        _ws_broadcast("task_failed", {"task_id": task_id, "agent_id": esc.get("agent_id", ""), "error": "cancelled by the owner"})  # type: ignore[misc]
        return {"action": "cancel", "task_id": task_id}

    return f"invalid action '{action}', valid: extend, reassign, cancel"


# ===================================================================
# Task timeout enforcement
# ===================================================================

def _check_task_timeouts() -> None:
    """Check all active tasks for ack-deadline (F-16) and timeout, then trigger escalation."""
    from handlers.agents import agent_connection_status
    from handlers.messages import append_message

    now = datetime.fromisoformat(_utc_now_iso())

    # ── F-16: Ack-Deadline-Enforcement ──────────────────────────
    # Tasks in "claimed" state must be acked within ack_deadline_seconds.
    # If not: re-queue (back to "created") or fail if max_retries exceeded.
    with _TASK_LOCK:
        claimed_tasks = [
            (tid, dict(t)) for tid, t in _TASKS.items()
            if t["state"] == "claimed"
        ]
    for task_id, task in claimed_tasks:
        ack_deadline = task.get("ack_deadline_seconds", _TASK_DEFAULT_ACK_DEADLINE)
        claimed_at_str = task.get("claimed_at")
        if not claimed_at_str:
            continue
        try:
            claimed_at = datetime.fromisoformat(claimed_at_str)
        except (ValueError, TypeError):
            continue
        elapsed = (now - claimed_at).total_seconds()
        if elapsed < ack_deadline:
            continue  # Still within deadline
        # Ack deadline exceeded
        agent_id = task.get("assigned_to", "unknown")
        title = task.get("title", task_id)
        retry_count = task.get("retry_count", 0) + 1
        max_retries = task.get("max_retries", 2)
        with _TASK_LOCK:
            # Re-check state under lock (may have changed)
            live_task = _TASKS.get(task_id)
            if not live_task or live_task["state"] != "claimed":
                continue
            before_task = copy.deepcopy(live_task)
            if retry_count >= max_retries:
                # Max retries exceeded — fail the task
                live_task["state"] = "failed"
                live_task["retry_count"] = retry_count
                _clear_task_lease(live_task)
                live_task["state_history"].append({
                    "state": "failed",
                    "at": _utc_now_iso(),
                    "by": "system",
                    "reason": f"ack deadline ({ack_deadline}s) exceeded, max retries ({max_retries}) reached",
                })
                _persist_tasks()
                _append_task_transition_wal(task_id, "ack_timeout_fail", "system", before_task, live_task, {
                    "retry_count": retry_count,
                    "max_retries": max_retries,
                })
                print(f"[F-16] Task '{title}' FAILED — ack deadline exceeded after {retry_count} retries")
                append_message("system", agent_id, f"[ACK-TIMEOUT] Aufgabe '{title}' ist fehlgeschlagen — Ack-Deadline ({ack_deadline}s) {retry_count}x ueberschritten.", meta={"type": "ack_deadline_failed", "task_id": task_id})
                _ws_broadcast("task_failed", {"task_id": task_id, "reason": "ack_deadline_exceeded", "retries": retry_count})  # type: ignore[misc]
            else:
                # Re-queue: back to "created", clear assignment
                live_task["state"] = "created"
                live_task["assigned_to"] = None
                live_task["retry_count"] = retry_count
                live_task.pop("claimed_at", None)
                _clear_task_lease(live_task)
                live_task["state_history"].append({
                    "state": "created",
                    "at": _utc_now_iso(),
                    "by": "system",
                    "reason": f"ack deadline ({ack_deadline}s) exceeded by {agent_id}, re-queued (retry {retry_count}/{max_retries})",
                })
                _persist_tasks()
                _append_task_transition_wal(task_id, "ack_timeout_requeue", "system", before_task, live_task, {
                    "retry_count": retry_count,
                    "max_retries": max_retries,
                })
                print(f"[F-16] Task '{title}' re-queued — ack deadline exceeded by {agent_id} (retry {retry_count}/{max_retries})")
                append_message("system", agent_id, f"[ACK-TIMEOUT] Aufgabe '{title}' wurde re-queued — Ack-Deadline ({ack_deadline}s) ueberschritten (Retry {retry_count}/{max_retries}).", meta={"type": "ack_deadline_requeue", "task_id": task_id})
                _ws_broadcast("task_requeued", {"task_id": task_id, "reason": "ack_deadline_exceeded", "retry": retry_count, "max_retries": max_retries})  # type: ignore[misc]
            # Clean up escalation state if any
            with ESCALATION_LOCK:
                ESCALATION_STATE.pop(task_id, None)
                _persist_escalation_state()

    # ── Unclaimed Task Expiry (created-state TTL) ──────────────
    # Tasks stuck in "created" state beyond their timeout_seconds are auto-expired.
    # Prevents queue pollution from regression probes or abandoned task creators.
    _UNCLAIMED_TTL_DEFAULT = 3600  # 1h default for unclaimed tasks
    with _TASK_LOCK:
        created_tasks = [
            (tid, dict(t)) for tid, t in _TASKS.items()
            if t["state"] == "created"
        ]
    _expired_ids: list[str] = []
    for task_id, task in created_tasks:
        ttl = task.get("timeout_seconds", _UNCLAIMED_TTL_DEFAULT)
        created_at_str = task.get("created_at")
        if not created_at_str:
            continue
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except (ValueError, TypeError):
            continue
        elapsed = (now - created_at).total_seconds()
        if elapsed < ttl:
            continue
        _expired_ids.append(task_id)
    if _expired_ids:
        with _TASK_LOCK:
            for task_id in _expired_ids:
                live_task = _TASKS.get(task_id)
                if not live_task or live_task["state"] != "created":
                    continue
                before_task = copy.deepcopy(live_task)
                created_at_str = live_task.get("created_at", "")
                try:
                    elapsed = (now - datetime.fromisoformat(created_at_str)).total_seconds()
                except (ValueError, TypeError):
                    elapsed = 0
                ttl = live_task.get("timeout_seconds", _UNCLAIMED_TTL_DEFAULT)
                live_task["state"] = "failed"
                _clear_task_lease(live_task)
                live_task["state_history"].append({
                    "state": "failed",
                    "at": _utc_now_iso(),
                    "by": "system",
                    "reason": f"unclaimed for {int(elapsed)}s (TTL {ttl}s) — auto-expired",
                })
                title = live_task.get("title", task_id)
                print(f"[TASK-TTL] Unclaimed task '{title}' auto-expired after {int(elapsed)}s")
                _append_task_transition_wal(task_id, "unclaimed_expired", "system", before_task, live_task, {
                    "elapsed_seconds": int(elapsed),
                    "ttl_seconds": ttl,
                })
            _persist_tasks()  # Single batch write for all expired tasks

    # ── General timeout + escalation (existing logic) ──────────
    with _TASK_LOCK:
        active_tasks = [
            (tid, dict(t)) for tid, t in _TASKS.items()
            if t["state"] in ("claimed", "acked")
        ]

    for task_id, task in active_tasks:
        timeout_sec = task.get("timeout_seconds", 1800)
        claimed_at_str = task.get("claimed_at")
        last_checkin_str = task.get("last_checkin")

        if not claimed_at_str:
            continue

        try:
            claimed_at = datetime.fromisoformat(claimed_at_str)
        except (ValueError, TypeError):
            continue

        # Reference time: last_checkin if available, else claimed_at
        ref_time = claimed_at
        if last_checkin_str:
            try:
                ref_time = datetime.fromisoformat(last_checkin_str)
            except (ValueError, TypeError):
                pass

        lease_expires_at_str = task.get("lease_expires_at")
        lease_expires_at = None
        if lease_expires_at_str:
            try:
                lease_expires_at = datetime.fromisoformat(lease_expires_at_str)
            except (ValueError, TypeError):
                lease_expires_at = None
        if lease_expires_at is None:
            lease_expires_at = ref_time + timedelta(seconds=timeout_sec)
        elapsed = max(0.0, (now - ref_time).total_seconds())
        if now < lease_expires_at:
            continue  # Not timed out yet

        # ── acked-orphan recovery: auto-requeue if agent is offline ──
        # If the assigned agent is disconnected/offline AND the lease has expired,
        # skip escalation (agent can't respond) and requeue or fail directly.
        assigned_agent = task.get("assigned_to", "")
        if assigned_agent and task.get("state") == "acked":
            agent_status = agent_connection_status(assigned_agent)
            if agent_status == "disconnected":
                retry_count = task.get("retry_count", 0) + 1
                max_retries = task.get("max_retries", 2)
                title = task.get("title", task_id)
                with _TASK_LOCK:
                    live_task = _TASKS.get(task_id)
                    if not live_task or live_task["state"] != "acked":
                        continue
                    before_task = copy.deepcopy(live_task)
                    if retry_count >= max_retries:
                        live_task["state"] = "failed"
                        live_task["retry_count"] = retry_count
                        _clear_task_lease(live_task)
                        live_task["state_history"].append({
                            "state": "failed",
                            "at": _utc_now_iso(),
                            "by": "system",
                            "reason": f"agent {assigned_agent} offline, lease expired, max retries ({max_retries}) reached",
                        })
                        _persist_tasks()
                        _append_task_transition_wal(task_id, "orphan_fail", "system", before_task, live_task, {
                            "retry_count": retry_count, "max_retries": max_retries, "agent_status": "disconnected",
                        })
                        print(f"[ORPHAN-RECOVERY] Task '{title}' FAILED — agent {assigned_agent} offline, retries exhausted")
                        append_message("system", "user", f"[ORPHAN] Task '{title}' fehlgeschlagen — Agent {assigned_agent} offline, Lease abgelaufen, max Retries erreicht.", meta={"type": "orphan_fail", "task_id": task_id})
                        _ws_broadcast("task_failed", {"task_id": task_id, "reason": "orphan_agent_offline", "agent": assigned_agent})  # type: ignore[misc]
                    else:
                        live_task["state"] = "created"
                        live_task["assigned_to"] = None
                        live_task["retry_count"] = retry_count
                        live_task.pop("claimed_at", None)
                        live_task.pop("acked_at", None)
                        _clear_task_lease(live_task)
                        live_task["state_history"].append({
                            "state": "created",
                            "at": _utc_now_iso(),
                            "by": "system",
                            "reason": f"agent {assigned_agent} offline, lease expired — re-queued (retry {retry_count}/{max_retries})",
                        })
                        _persist_tasks()
                        _append_task_transition_wal(task_id, "orphan_requeue", "system", before_task, live_task, {
                            "retry_count": retry_count, "max_retries": max_retries, "agent_status": "disconnected",
                        })
                        print(f"[ORPHAN-RECOVERY] Task '{title}' re-queued — agent {assigned_agent} offline (retry {retry_count}/{max_retries})")
                        append_message("system", "user", f"[ORPHAN] Task '{title}' wurde re-queued — Agent {assigned_agent} offline, Lease abgelaufen (Retry {retry_count}/{max_retries}).", meta={"type": "orphan_requeue", "task_id": task_id})
                        _ws_broadcast("task_requeued", {"task_id": task_id, "reason": "orphan_agent_offline", "agent": assigned_agent, "retry": retry_count})  # type: ignore[misc]
                with ESCALATION_LOCK:
                    ESCALATION_STATE.pop(task_id, None)
                    _persist_escalation_state()
                continue  # Skip normal escalation — already handled

        # Task is overdue — check escalation state
        with ESCALATION_LOCK:
            esc = ESCALATION_STATE.get(task_id)
            if not esc:
                # Start Stage 1: REMINDER
                ESCALATION_STATE[task_id] = {
                    "stage": 1,
                    "started_at": _utc_now_iso(),
                    "task_id": task_id,
                    "agent_id": task.get("assigned_to", ""),
                    "task_title": task.get("title", task_id),
                }
                _persist_escalation_state()
                esc = ESCALATION_STATE[task_id]
                _escalate_stage_1(task_id, task)
            elif esc["stage"] == 1:
                stage_elapsed = (now - datetime.fromisoformat(esc["started_at"])).total_seconds()
                if stage_elapsed >= ESCALATION_CONFIG["reminder_timeout"]:
                    esc["stage"] = 2
                    esc["started_at"] = _utc_now_iso()
                    _persist_escalation_state()
                    _escalate_stage_2(task_id, task)
            elif esc["stage"] == 2:
                stage_elapsed = (now - datetime.fromisoformat(esc["started_at"])).total_seconds()
                if stage_elapsed >= ESCALATION_CONFIG["direct_timeout"]:
                    esc["stage"] = 3
                    esc["started_at"] = _utc_now_iso()
                    _persist_escalation_state()
                    _escalate_stage_3(task_id, task)
            # Stage 3: waiting for the owner — no further automatic action
