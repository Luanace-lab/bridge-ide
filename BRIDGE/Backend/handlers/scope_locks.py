"""Scope lock acquisition, release, validation, and audit extracted from server.py (Slice 06).

This module owns:
- _persist_scope_locks / _load_scope_locks_from_disk
- _normalize_scope_path / _scope_label_for_path / _parse_scope_tokens
- _candidate_scope_paths / _resolve_agent_scope_entries
- _is_edit_activity / _check_activity_scope_violation
- _lock_scope_path / _unlock_scope_paths
- _cleanup_expired_scope_locks / _refresh_scope_locks_for_task
- _log_scope_event

Anti-circular-import strategy:
  All shared state and cross-domain functions are injected via init().
  This module NEVER imports from server.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Module-local constants
# ---------------------------------------------------------------------------
SCOPE_LOCK_DEFAULT_TTL = 1800  # 30 min auto-expire (seconds)

_SCOPE_EDIT_ACTION_KEYWORDS = (
    "edit",
    "editing",
    "write",
    "patch",
    "modify",
    "refactor",
    "create",
    "delete",
    "rename",
    "move",
)

# Paths — set by init()
_SCOPE_LOCK_LOG: str = ""
_SCOPE_LOCKS_PERSIST_FILE: str = ""

# ---------------------------------------------------------------------------
# Injected shared state (set by init())
# ---------------------------------------------------------------------------
_SCOPE_LOCKS: dict[str, dict[str, Any]] = {}
_SCOPE_LOCK_LOCK: Any = None
_TEAM_CONFIG: dict[str, Any] | None = None
_TEAM_CONFIG_LOCK: Any = None
_ROOT_DIR: str = ""
_BASE_DIR: str = ""


def init(
    *,
    scope_locks: dict[str, dict[str, Any]],
    scope_lock_lock: Any,
    team_config: dict[str, Any],
    team_config_lock: Any,
    root_dir: str,
    base_dir: str,
    agent_log_dir: str,
) -> None:
    """Bind shared state references. Must be called once before any other function."""
    global _SCOPE_LOCKS, _SCOPE_LOCK_LOCK
    global _TEAM_CONFIG, _TEAM_CONFIG_LOCK
    global _ROOT_DIR, _BASE_DIR
    global _SCOPE_LOCK_LOG, _SCOPE_LOCKS_PERSIST_FILE

    _SCOPE_LOCKS = scope_locks
    _SCOPE_LOCK_LOCK = scope_lock_lock
    _TEAM_CONFIG = team_config
    _TEAM_CONFIG_LOCK = team_config_lock
    _ROOT_DIR = root_dir
    _BASE_DIR = base_dir
    _SCOPE_LOCK_LOG = os.path.join(agent_log_dir, "scope_locks.jsonl")
    _SCOPE_LOCKS_PERSIST_FILE = os.path.join(base_dir, "scope_locks.json")


# ===================================================================
# Persistence
# ===================================================================

def _persist_scope_locks() -> None:
    """Atomically persist SCOPE_LOCKS to disk. Call while holding SCOPE_LOCK_LOCK."""
    data = json.dumps(_SCOPE_LOCKS, indent=2, ensure_ascii=False) + "\n"
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_SCOPE_LOCKS_PERSIST_FILE), suffix=".tmp")
        try:
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            os.replace(tmp, _SCOPE_LOCKS_PERSIST_FILE)
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


def _load_scope_locks_from_disk() -> None:
    """Load persisted scope locks on startup, discarding already-expired entries."""
    if not os.path.exists(_SCOPE_LOCKS_PERSIST_FILE):
        return
    try:
        with open(_SCOPE_LOCKS_PERSIST_FILE) as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            return
        now_iso = _utc_now_iso()
        valid = {}
        for path, lock in loaded.items():
            try:
                if datetime.fromisoformat(lock.get("expires_at", "")) > datetime.fromisoformat(now_iso):
                    valid[path] = lock
            except (ValueError, KeyError, TypeError):
                pass  # Skip malformed or expired entries
        with _SCOPE_LOCK_LOCK:
            _SCOPE_LOCKS.update(valid)
        print(f"[scope_locks] Loaded {len(valid)} active locks from disk ({len(loaded) - len(valid)} expired dropped)")
    except Exception as exc:
        print(f"[scope_locks] WARNING: Failed to load scope locks: {exc}")


# ===================================================================
# Path normalization & resolution
# ===================================================================

def _normalize_scope_path(path: str) -> str:
    """Normalize a scope path to absolute form for consistent lock keys."""
    return os.path.normpath(os.path.abspath(os.path.expanduser(path.strip())))


def _scope_label_for_path(path: str) -> str:
    """Resolve user-friendly label for a path from team.json scope_labels.

    V3: scope_labels live inside projects[].scope_labels (per project).
    Fallback: top-level scope_labels (v2 compat).
    """
    if _TEAM_CONFIG is None:
        return os.path.basename(path) or path
    # Collect scope_labels from all projects (v3) + top-level fallback (v2)
    all_labels: dict[str, str] = {}
    for proj in _TEAM_CONFIG.get("projects", []):
        all_labels.update(proj.get("scope_labels", {}))
    all_labels.update(_TEAM_CONFIG.get("scope_labels", {}))
    if not all_labels:
        return os.path.basename(path) or path
    # Longest prefix match
    best_label = ""
    best_len = 0
    for prefix, label in all_labels.items():
        norm_prefix = os.path.normpath(os.path.abspath(os.path.expanduser(prefix)))
        if path.startswith(norm_prefix) and len(norm_prefix) > best_len:
            best_label = label
            best_len = len(norm_prefix)
    return best_label or os.path.basename(path) or path


def _parse_scope_tokens(value: Any) -> list[str]:
    """Extract scope tokens from string/list style scope fields."""
    if isinstance(value, str):
        parts = re.split(r"[,\n;]", value)
        return [p.strip() for p in parts if p and p.strip()]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                token = item.strip()
                if token:
                    out.append(token)
        return out
    return []


def _candidate_scope_paths(raw_value: str, project_roots: list[str]) -> list[str]:
    """Return possible absolute paths for a raw target/scope string."""
    value = raw_value.strip().strip("`").strip("\"").strip("'")
    if not value:
        return []
    # Support file refs like /abs/path/file.py:42[:7]
    line_ref_match = re.match(r"^(/[^:]+):\d+(?::\d+)?$", value)
    if line_ref_match:
        value = line_ref_match.group(1)

    candidates: list[str] = []
    if os.path.isabs(value):
        return [_normalize_scope_path(value)]

    bases: list[str] = []
    for root in project_roots + [_ROOT_DIR, _BASE_DIR, os.path.dirname(_ROOT_DIR)]:
        norm_root = _normalize_scope_path(root)
        if norm_root not in bases:
            bases.append(norm_root)

    for base in bases:
        candidates.append(_normalize_scope_path(os.path.join(base, value)))
    # Also allow BRIDGE-relative targets without explicit BRIDGE/ prefix.
    candidates.append(_normalize_scope_path(os.path.join(_ROOT_DIR, value)))

    # Deduplicate preserving order.
    deduped: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        if path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped


def _resolve_agent_scope_entries(agent_id: str) -> list[dict[str, Any]]:
    """Resolve allowed file/directory scope entries for an agent from team.json."""
    with _TEAM_CONFIG_LOCK:
        team_snapshot = dict(_TEAM_CONFIG) if isinstance(_TEAM_CONFIG, dict) else {}

    if not team_snapshot:
        return []

    project_roots: list[str] = []
    labeled_paths: list[dict[str, Any]] = []
    for project in team_snapshot.get("projects", []):
        raw_root = str(project.get("path", "")).strip()
        if raw_root:
            project_roots.append(_normalize_scope_path(raw_root))
        for raw_path in (project.get("scope_labels", {}) or {}).keys():
            if not isinstance(raw_path, str):
                continue
            token = raw_path.strip()
            if not token:
                continue
            is_prefix = token.endswith("/")
            candidates = _candidate_scope_paths(token, project_roots)
            if not candidates:
                continue
            labeled_paths.append(
                {
                    "raw": token,
                    "path": candidates[0],
                    "is_prefix": is_prefix,
                }
            )

    agent_cfg = None
    for agent in team_snapshot.get("agents", []):
        if agent.get("id") == agent_id:
            agent_cfg = agent
            break

    raw_scopes: list[str] = []
    if isinstance(agent_cfg, dict):
        raw_scopes.extend(_parse_scope_tokens(agent_cfg.get("scope")))
        raw_scopes.extend(_parse_scope_tokens(agent_cfg.get("scope_paths")))
        home_dir = str(agent_cfg.get("home_dir", "")).strip()
        if home_dir:
            raw_scopes.append(home_dir.rstrip("/") + "/")

    # Team-level scope fallback for current config schema (team.members + team.scope)
    for team in team_snapshot.get("teams", []):
        members = set(team.get("members", []) or [])
        lead = str(team.get("lead", "")).strip()
        if lead:
            members.add(lead)
        if agent_id in members:
            raw_scopes.extend(_parse_scope_tokens(team.get("scope")))

    resolved: list[dict[str, Any]] = []
    seen: set[tuple[str, bool]] = set()

    for scope_token in raw_scopes:
        token = scope_token.strip()
        if not token:
            continue
        token_lower = token.lower()
        matched_label = False
        for label in labeled_paths:
            raw = str(label["raw"]).lower()
            abs_path = str(label["path"]).lower()
            basename = os.path.basename(str(label["path"])).lower()
            if (
                token_lower == basename
                or raw.endswith(token_lower)
                or abs_path.endswith(token_lower)
            ):
                key = (str(label["path"]), bool(label["is_prefix"]))
                if key not in seen:
                    resolved.append({"path": key[0], "is_prefix": key[1]})
                    seen.add(key)
                matched_label = True
        if matched_label:
            continue

        looks_path_like = (
            "/" in token
            or "\\" in token
            or token.startswith("~")
            or token.startswith(".")
            or bool(re.search(r"\.[A-Za-z0-9]{1,8}$", token))
        )
        if not looks_path_like:
            continue

        is_prefix = token.endswith("/") or token.endswith("\\")
        for candidate in _candidate_scope_paths(token, project_roots):
            key = (candidate, is_prefix)
            if key in seen:
                continue
            resolved.append({"path": candidate, "is_prefix": is_prefix})
            seen.add(key)

    return resolved


# ===================================================================
# Scope violation checking
# ===================================================================

def _is_edit_activity(action: str) -> bool:
    action_lower = action.strip().lower()
    return any(keyword in action_lower for keyword in _SCOPE_EDIT_ACTION_KEYWORDS)


def _check_activity_scope_violation(
    agent_id: str,
    action: str,
    target: str,
) -> tuple[bool, dict[str, Any]]:
    """Return (blocked, details) for scope checks on file-edit activities."""
    if not _is_edit_activity(action):
        return False, {"reason": "action_not_scope_checked"}

    target_clean = target.strip()
    if not target_clean:
        return False, {"reason": "empty_target"}

    with _TEAM_CONFIG_LOCK:
        team_snapshot = dict(_TEAM_CONFIG) if isinstance(_TEAM_CONFIG, dict) else {}
    project_roots = [
        _normalize_scope_path(str(project.get("path", "")).strip())
        for project in team_snapshot.get("projects", [])
        if str(project.get("path", "")).strip()
    ]

    candidates = _candidate_scope_paths(target_clean, project_roots)
    if not candidates:
        return False, {"reason": "target_not_resolved"}

    allowed_entries = _resolve_agent_scope_entries(agent_id)
    if not allowed_entries:
        return False, {"reason": "no_scope_rules_configured"}

    for candidate in candidates:
        for entry in allowed_entries:
            scope_path = str(entry.get("path", ""))
            if not scope_path:
                continue
            is_prefix = bool(entry.get("is_prefix", False))
            if candidate == scope_path:
                return False, {"reason": "in_scope_exact", "matched_scope": scope_path}
            if is_prefix and candidate.startswith(scope_path + os.sep):
                return False, {"reason": "in_scope_prefix", "matched_scope": scope_path}

    allowed_preview = [str(e.get("path", "")) for e in allowed_entries[:5] if e.get("path")]
    details = (
        f"target '{target_clean}' resolved to '{candidates[0]}' is outside allowed scope "
        f"for agent '{agent_id}'"
    )
    return True, {
        "reason": "scope_violation",
        "details": details,
        "candidate": candidates[0],
        "allowed_preview": allowed_preview,
    }


# ===================================================================
# Lock acquisition & release
# ===================================================================

def _lock_scope_path(
    path: str,
    task_id: str,
    agent_id: str,
    lock_type: str = "file",
    ttl: int | None = None,
) -> dict[str, Any] | str:
    """Acquire a scope lock. Returns lock dict on success, error string on conflict."""
    norm = _normalize_scope_path(path)
    now_iso = _utc_now_iso()
    expire_seconds = ttl if ttl is not None else SCOPE_LOCK_DEFAULT_TTL
    expires_at = (datetime.fromisoformat(now_iso) + timedelta(seconds=expire_seconds)).isoformat()

    with _SCOPE_LOCK_LOCK:
        # Check existing lock
        existing = _SCOPE_LOCKS.get(norm)
        if existing:
            # Same task extending lock — allow
            if existing["task_id"] == task_id:
                existing["ttl_seconds"] = expire_seconds
                existing["expires_at"] = expires_at
                return existing
            # Check if expired
            try:
                exp = datetime.fromisoformat(existing["expires_at"])
                if datetime.fromisoformat(now_iso) > exp:
                    # Expired — remove and allow
                    del _SCOPE_LOCKS[norm]
                else:
                    return f"locked by agent '{existing['agent_id']}' (task: {existing['task_id']}, label: {existing['label']})"
            except (ValueError, KeyError):
                return f"locked by agent '{existing['agent_id']}'"

        # Check directory-file overlap
        for locked_path, lock_info in list(_SCOPE_LOCKS.items()):
            # Skip expired
            try:
                exp = datetime.fromisoformat(lock_info["expires_at"])
                if datetime.fromisoformat(now_iso) > exp:
                    del _SCOPE_LOCKS[locked_path]
                    continue
            except (ValueError, KeyError):
                pass
            # Same task — skip
            if lock_info["task_id"] == task_id:
                continue
            # Directory lock blocks files underneath (prefix match)
            if lock_info["lock_type"] == "directory" and norm.startswith(locked_path + os.sep):
                return f"directory locked by agent '{lock_info['agent_id']}' (label: {lock_info['label']})"
            # New directory lock vs existing file underneath
            if lock_type == "directory" and locked_path.startswith(norm + os.sep):
                return f"file '{locked_path}' locked by agent '{lock_info['agent_id']}' (label: {lock_info['label']})"

        label = _scope_label_for_path(norm)
        lock_entry: dict[str, Any] = {
            "path": norm,
            "label": label,
            "task_id": task_id,
            "agent_id": agent_id,
            "locked_at": now_iso,
            "lock_type": lock_type,
            "ttl_seconds": expire_seconds,
            "expires_at": expires_at,
        }
        _SCOPE_LOCKS[norm] = lock_entry
        _persist_scope_locks()

    # Log
    _log_scope_event("locked", lock_entry)
    return lock_entry


def _unlock_scope_paths(task_id: str, paths: list[str] | None = None) -> list[dict[str, Any]]:
    """Release scope locks for a task. If paths is None, release ALL locks for the task."""
    released: list[dict[str, Any]] = []
    with _SCOPE_LOCK_LOCK:
        if paths:
            for p in paths:
                norm = _normalize_scope_path(p)
                lock = _SCOPE_LOCKS.get(norm)
                if lock and lock["task_id"] == task_id:
                    released.append(_SCOPE_LOCKS.pop(norm))
        else:
            # Release all locks for this task
            to_remove = [p for p, l in _SCOPE_LOCKS.items() if l["task_id"] == task_id]
            for p in to_remove:
                released.append(_SCOPE_LOCKS.pop(p))
        if released:
            _persist_scope_locks()
    for lock in released:
        _log_scope_event("unlocked", lock)
    return released


# ===================================================================
# Maintenance & expiration
# ===================================================================

def _cleanup_expired_scope_locks() -> int:
    """Remove expired scope locks. Returns count removed."""
    now_iso = _utc_now_iso()
    removed = 0
    with _SCOPE_LOCK_LOCK:
        expired = []
        for path, lock in _SCOPE_LOCKS.items():
            try:
                exp = datetime.fromisoformat(lock["expires_at"])
                if datetime.fromisoformat(now_iso) > exp:
                    expired.append(path)
            except (ValueError, KeyError):
                expired.append(path)
        for path in expired:
            lock = _SCOPE_LOCKS.pop(path)
            _log_scope_event("expired", lock)
            removed += 1
        if removed:
            _persist_scope_locks()
    return removed


def _refresh_scope_locks_for_task(task_id: str) -> list[dict[str, Any]]:
    """Extend all active scope locks for a task based on their configured TTL."""
    now_iso = _utc_now_iso()
    refreshed: list[dict[str, Any]] = []
    with _SCOPE_LOCK_LOCK:
        for lock in _SCOPE_LOCKS.values():
            if lock.get("task_id") != task_id:
                continue
            ttl_seconds = int(lock.get("ttl_seconds", SCOPE_LOCK_DEFAULT_TTL))
            lock["expires_at"] = (
                datetime.fromisoformat(now_iso) + timedelta(seconds=ttl_seconds)
            ).isoformat()
            refreshed.append(dict(lock))
        if refreshed:
            _persist_scope_locks()
    for lock in refreshed:
        _log_scope_event("refreshed", lock)
    return refreshed


# ===================================================================
# Audit logging
# ===================================================================

def _log_scope_event(event: str, lock: dict[str, Any]) -> None:
    """Append scope lock event to audit log."""
    try:
        entry = {
            "event": event,
            "path": lock.get("path", ""),
            "label": lock.get("label", ""),
            "task_id": lock.get("task_id", ""),
            "agent_id": lock.get("agent_id", ""),
            "timestamp": _utc_now_iso(),
        }
        with open(_SCOPE_LOCK_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
