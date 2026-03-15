"""Pure utility helpers extracted from server.py (Slice 34)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

_MAX_WAIT_SECONDS = 60.0
_MAX_LIMIT = 1000


def init(*, max_wait_seconds: float, max_limit: int) -> None:
    global _MAX_WAIT_SECONDS, _MAX_LIMIT
    _MAX_WAIT_SECONDS = float(max_wait_seconds)
    _MAX_LIMIT = int(max_limit)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_within_directory(path: str, base_dir: str) -> bool:
    abs_path = os.path.abspath(path)
    abs_base = os.path.abspath(base_dir)
    return abs_path == abs_base or abs_path.startswith(abs_base + os.sep)


def normalize_path(value: str | None, fallback: str) -> str:
    raw = value.strip() if isinstance(value, str) else ""
    candidate = raw or fallback
    return os.path.abspath(os.path.expanduser(candidate))


def validate_project_path(raw_path: str | None, base_dir: str) -> str | None:
    if not raw_path:
        return None
    path = normalize_path(raw_path, base_dir)
    if not is_within_directory(path, base_dir):
        return None
    return path


def resolve_team_lead_scope_file(project_path: str, raw_path: Any) -> str:
    parent_dir = os.path.dirname(project_path)
    default_path = os.path.join(parent_dir, "teamlead.md")
    if isinstance(raw_path, str) and raw_path.strip():
        candidate_raw = raw_path.strip()
        if os.path.isabs(candidate_raw):
            candidate = os.path.abspath(os.path.expanduser(candidate_raw))
        else:
            candidate = os.path.abspath(os.path.join(project_path, candidate_raw))
    else:
        candidate = os.path.abspath(default_path)

    if not is_within_directory(candidate, parent_dir):
        candidate = os.path.abspath(default_path)
    return candidate


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def parse_wait(value: str | None) -> float:
    if value is None:
        return 20.0
    try:
        wait = float(value)
    except ValueError:
        return 20.0
    if wait < 0:
        return 0.0
    if wait > _MAX_WAIT_SECONDS:
        return _MAX_WAIT_SECONDS
    return wait


def parse_limit(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        limit = int(value)
    except ValueError:
        return 50
    if limit <= 0:
        return 50
    return min(limit, _MAX_LIMIT)


def parse_after_id(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        after_id = int(value)
    except ValueError:
        return None
    if after_id < -1:
        return None
    return after_id


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def parse_non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)
