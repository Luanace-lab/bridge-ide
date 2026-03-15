"""Whiteboard CRUD, TTL cleanup, persistence and audit extracted from server.py (Slice 06).

This module owns:
- _whiteboard_post / _whiteboard_delete / _whiteboard_get
- _cleanup_expired_whiteboard
- _persist_whiteboard / _load_whiteboard_from_disk
- _log_whiteboard_event

Anti-circular-import strategy:
  All shared state and cross-domain functions are injected via init().
  This module NEVER imports from server.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Module-local constants
# ---------------------------------------------------------------------------
WHITEBOARD_VALID_SEVERITIES = {"info", "warning", "critical"}

# Paths — set by init()
_WHITEBOARD_LOG: str = ""
_WHITEBOARD_PERSIST_FILE: str = ""

# ---------------------------------------------------------------------------
# Injected shared state (set by init())
# ---------------------------------------------------------------------------
_WHITEBOARD: dict[str, dict[str, Any]] = {}
_WHITEBOARD_LOCK: Any = None
_TEAM_CONFIG: dict[str, Any] | None = None
_WHITEBOARD_VALID_TYPES: set[str] = {"status", "blocker", "result", "alert", "escalation_response"}
_WS_BROADCAST_FN: Callable[[str, dict[str, Any]], None] | None = None


def init(
    *,
    whiteboard: dict[str, dict[str, Any]],
    whiteboard_lock: Any,
    team_config: dict[str, Any],
    base_dir: str,
    agent_log_dir: str,
    whiteboard_valid_types: set[str],
    ws_broadcast_fn: Callable[[str, dict[str, Any]], None],
) -> None:
    """Bind shared state references. Must be called once before any other function."""
    global _WHITEBOARD, _WHITEBOARD_LOCK, _TEAM_CONFIG
    global _WHITEBOARD_LOG, _WHITEBOARD_PERSIST_FILE
    global _WHITEBOARD_VALID_TYPES, _WS_BROADCAST_FN

    _WHITEBOARD = whiteboard
    _WHITEBOARD_LOCK = whiteboard_lock
    _TEAM_CONFIG = team_config
    _WHITEBOARD_LOG = os.path.join(agent_log_dir, "whiteboard.jsonl")
    _WHITEBOARD_PERSIST_FILE = os.path.join(base_dir, "whiteboard.json")
    _WHITEBOARD_VALID_TYPES = set(whiteboard_valid_types)
    _WS_BROADCAST_FN = ws_broadcast_fn


def _ws_broadcast(event: str, payload: dict[str, Any]) -> None:
    if _WS_BROADCAST_FN is not None:
        _WS_BROADCAST_FN(event, payload)


# ===================================================================
# Persistence
# ===================================================================

def _persist_whiteboard() -> None:
    """Atomically persist WHITEBOARD dict to whiteboard.json.

    Must be called while holding WHITEBOARD_LOCK.
    """
    data = json.dumps(_WHITEBOARD, indent=2, ensure_ascii=False) + "\n"
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_WHITEBOARD_PERSIST_FILE), suffix=".tmp")
        try:
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            os.replace(tmp, _WHITEBOARD_PERSIST_FILE)
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


def _load_whiteboard_from_disk() -> None:
    """Load persisted whiteboard entries from whiteboard.json on server startup."""
    if not os.path.exists(_WHITEBOARD_PERSIST_FILE):
        return
    try:
        with open(_WHITEBOARD_PERSIST_FILE) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            _WHITEBOARD.update(loaded)
            print(f"[whiteboard] Loaded {len(loaded)} entries from {_WHITEBOARD_PERSIST_FILE}")
    except Exception as exc:
        print(f"[whiteboard] WARNING: Failed to load whiteboard from {_WHITEBOARD_PERSIST_FILE}: {exc}")


# ===================================================================
# CRUD operations
# ===================================================================

def _whiteboard_post(
    agent_id: str,
    entry_type: str,
    content: str,
    task_id: str | None = None,
    task_title: str | None = None,
    scope_label: str | None = None,
    severity: str = "info",
    ttl_seconds: int = 0,
    tags: list[str] | None = None,
    priority: int = 0,
) -> dict[str, Any]:
    """Create or update a whiteboard entry. Upsert by agent_id + task_id."""
    now_iso = _utc_now_iso()

    # Resolve agent name from team.json
    agent_name = agent_id
    if _TEAM_CONFIG:
        for a in _TEAM_CONFIG.get("agents", []):
            if a.get("id") == agent_id:
                agent_name = a.get("name", agent_id)
                break

    with _WHITEBOARD_LOCK:
        # Upsert: find existing entry by agent_id + task_id
        existing_id = None
        if task_id:
            for eid, entry in _WHITEBOARD.items():
                if entry["agent_id"] == agent_id and entry.get("task_id") == task_id and entry["type"] == entry_type:
                    existing_id = eid
                    break

        entry_id = existing_id or str(uuid.uuid4())
        entry: dict[str, Any] = {
            "id": entry_id,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "type": entry_type,
            "content": content,
            "task_id": task_id,
            "task_title": task_title or "",
            "scope_label": scope_label or "",
            "severity": severity if severity in WHITEBOARD_VALID_SEVERITIES else "info",
            "created_at": _WHITEBOARD.get(entry_id, {}).get("created_at", now_iso),
            "updated_at": now_iso,
            "ttl_seconds": ttl_seconds,
            "tags": tags or [],
            "priority": priority,
        }
        _WHITEBOARD[entry_id] = entry
        _persist_whiteboard()

    # Log
    _log_whiteboard_event("post", entry)
    return entry


def _whiteboard_delete(entry_id: str) -> dict[str, Any] | None:
    """Remove a whiteboard entry by ID."""
    with _WHITEBOARD_LOCK:
        entry = _WHITEBOARD.pop(entry_id, None)
        if entry:
            _persist_whiteboard()
    if entry:
        _log_whiteboard_event("delete", entry)
    return entry


def _whiteboard_get(
    agent_id: str | None = None,
    entry_type: str | None = None,
    severity: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get whiteboard entries with optional filters."""
    with _WHITEBOARD_LOCK:
        entries = list(_WHITEBOARD.values())
    # Filter
    if agent_id:
        entries = [e for e in entries if e["agent_id"] == agent_id]
    if entry_type:
        entries = [e for e in entries if e["type"] == entry_type]
    if severity:
        entries = [e for e in entries if e["severity"] == severity]
    # Sort: newest first
    entries.sort(key=lambda e: e.get("updated_at", ""), reverse=True)
    return entries[:limit]


# ===================================================================
# TTL cleanup
# ===================================================================

def _cleanup_expired_whiteboard() -> int:
    """Remove whiteboard entries past their TTL. Returns count removed."""
    now = datetime.fromisoformat(_utc_now_iso())
    removed = 0
    with _WHITEBOARD_LOCK:
        expired_ids = []
        for eid, entry in _WHITEBOARD.items():
            ttl = entry.get("ttl_seconds", 0)
            if ttl <= 0:
                continue  # permanent
            try:
                created = datetime.fromisoformat(entry["created_at"])
                if now > created + timedelta(seconds=ttl):
                    expired_ids.append(eid)
            except (ValueError, KeyError):
                pass
        for eid in expired_ids:
            entry = _WHITEBOARD.pop(eid)
            _log_whiteboard_event("expired", entry)
            removed += 1
        if removed > 0:
            _persist_whiteboard()
    return removed


# ===================================================================
# Audit logging
# ===================================================================

def _log_whiteboard_event(event: str, entry: dict[str, Any]) -> None:
    """Append whiteboard event to audit log."""
    try:
        log_entry = {
            "event": event,
            "entry_id": entry.get("id", ""),
            "agent_id": entry.get("agent_id", ""),
            "type": entry.get("type", ""),
            "severity": entry.get("severity", ""),
            "content": entry.get("content", "")[:200],
            "timestamp": _utc_now_iso(),
        }
        with open(_WHITEBOARD_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path != "/whiteboard":
        return False

    agent_filter = (query.get("agent") or query.get("agent_id") or [None])[0]
    entry_type_filter = (query.get("type") or [None])[0]
    severity_filter = (query.get("severity") or [None])[0]
    try:
        limit_val = int((query.get("limit") or ["50"])[0])
    except (ValueError, TypeError):
        limit_val = 50
    priority_filter = (query.get("priority") or [None])[0]
    entries = _whiteboard_get(agent_filter, entry_type_filter, severity_filter, limit_val)
    if priority_filter:
        try:
            min_prio = int(priority_filter)
            entries = [e for e in entries if e.get("priority", 0) >= min_prio]
        except (ValueError, TypeError):
            pass
    handler._respond(200, {"entries": entries, "count": len(entries)})
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path not in {"/whiteboard", "/whiteboard/post"}:
        return False

    data = handler._parse_json_body() or {}
    agent_id = str(data.get("agent_id", "")).strip() or str(handler.headers.get("X-Bridge-Agent", "")).strip()
    entry_type = str(data.get("type", "status")).strip()
    content_text = str(data.get("content", "")).strip()

    if path == "/whiteboard":
        task_id = data.get("task_id")
        task_title = data.get("task_title")
        scope_label = data.get("scope_label")
        severity = str(data.get("severity", "info")).strip()
        ttl_seconds = int(data.get("ttl_seconds", 0) or 0)
        tags = data.get("tags", [])
        priority = int(data.get("priority", 0) or 0)

        if not agent_id:
            handler._respond(400, {"error": "agent_id is required"})
            return True
        if not content_text:
            handler._respond(400, {"error": "content is required"})
            return True
        if entry_type not in _WHITEBOARD_VALID_TYPES:
            handler._respond(400, {"error": f"invalid type '{entry_type}', valid: {sorted(_WHITEBOARD_VALID_TYPES)}"})
            return True

        if task_id:
            task_id = str(task_id).strip()
        if task_title:
            task_title = str(task_title).strip()
        if scope_label:
            scope_label = str(scope_label).strip()
        if not isinstance(tags, list):
            tags = []

        entry = _whiteboard_post(
            agent_id=agent_id,
            entry_type=entry_type,
            content=content_text,
            task_id=task_id,
            task_title=task_title,
            scope_label=scope_label,
            severity=severity,
            ttl_seconds=ttl_seconds,
            tags=tags,
            priority=priority,
        )
        _ws_broadcast("whiteboard_updated", {"entry": entry})
        if severity == "critical":
            _ws_broadcast("whiteboard_alert", {"entry": entry})
        handler._respond(200, {"ok": True, "entry": entry})
        return True

    if not agent_id or not content_text:
        handler._respond(400, {"error": "agent_id and content are required"})
        return True
    if entry_type not in _WHITEBOARD_VALID_TYPES:
        entry_type = "status"

    entry = _whiteboard_post(
        agent_id=agent_id,
        entry_type=entry_type,
        content=content_text,
        task_id=data.get("task_id"),
        task_title=data.get("task_title"),
        scope_label=data.get("scope_label"),
        severity=str(data.get("severity", "info")).strip(),
        ttl_seconds=int(data.get("ttl_seconds", 0) or 0),
        tags=data.get("tags") if isinstance(data.get("tags"), list) else [],
        priority=int(data.get("priority", 0) or 0),
    )
    _ws_broadcast("whiteboard_updated", {"entry": entry})
    handler._respond(200, {"ok": True, "entry": entry})
    return True


def handle_delete(handler: Any, path: str) -> bool:
    match = re.match(r"^/whiteboard/([^/]+)$", path)
    if not match:
        return False

    entry_id = match.group(1)
    entry = _whiteboard_delete(entry_id)
    if not entry:
        handler._respond(404, {"error": f"whiteboard entry '{entry_id}' not found"})
        return True
    _ws_broadcast("whiteboard_deleted", {"entry_id": entry_id, "agent_id": entry.get("agent_id", "")})
    handler._respond(200, {"ok": True, "deleted": entry})
    return True
