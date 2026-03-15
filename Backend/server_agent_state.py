"""Persistent agent-state and CLI-identity helpers extracted from server.py (Slice 37)."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

_AGENT_STATE_DIR = ""
_UTC_NOW_ISO_FN: Callable[[], str] = lambda: ""
_TEAM_CONFIG_GETTER: Callable[[], dict[str, Any]] = lambda: {}
_REGISTERED_AGENTS_GETTER: Callable[[], dict[str, Any]] = lambda: {}
_AGENT_STATE_LOCK: Any = None
_RESOLVE_AGENT_CLI_LAYOUT_FN: Callable[[str, str], dict[str, str]] = lambda _path, _agent_id: {
    "home_dir": "",
    "workspace": "",
    "project_root": "",
}

_AGENT_STATE_WRITE_LOCK = None
_AGENT_STATE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_AGENT_STATE_CACHE_TTL = 10.0


def init(
    *,
    agent_state_dir: str,
    utc_now_iso_fn: Callable[[], str],
    team_config_getter: Callable[[], dict[str, Any]],
    registered_agents_getter: Callable[[], dict[str, Any]],
    agent_state_lock: Any,
    resolve_agent_cli_layout_fn: Callable[[str, str], dict[str, str]],
    agent_state_write_lock: Any,
) -> None:
    """Bind shared state and callbacks from server.py."""
    global _AGENT_STATE_DIR
    global _UTC_NOW_ISO_FN
    global _TEAM_CONFIG_GETTER
    global _REGISTERED_AGENTS_GETTER
    global _AGENT_STATE_LOCK
    global _RESOLVE_AGENT_CLI_LAYOUT_FN
    global _AGENT_STATE_WRITE_LOCK

    _AGENT_STATE_DIR = agent_state_dir
    os.makedirs(_AGENT_STATE_DIR, exist_ok=True)
    _UTC_NOW_ISO_FN = utc_now_iso_fn
    _TEAM_CONFIG_GETTER = team_config_getter
    _REGISTERED_AGENTS_GETTER = registered_agents_getter
    _AGENT_STATE_LOCK = agent_state_lock
    _RESOLVE_AGENT_CLI_LAYOUT_FN = resolve_agent_cli_layout_fn
    _AGENT_STATE_WRITE_LOCK = agent_state_write_lock


def _agent_state_path(agent_id: str) -> str:
    """Return file path for an agent's persistent state."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", agent_id)
    return os.path.join(_AGENT_STATE_DIR, f"{safe_id}.json")


def _load_agent_state(agent_id: str) -> dict[str, Any]:
    """Load agent state from disk with TTL cache. Returns empty dict if not found."""
    now = time.monotonic()
    cached = _AGENT_STATE_CACHE.get(agent_id)
    if cached is not None and (now - cached[0]) < _AGENT_STATE_CACHE_TTL:
        return cached[1].copy()
    path = _agent_state_path(agent_id)
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    _AGENT_STATE_CACHE[agent_id] = (now, state)
    return state.copy()


def _save_agent_state(agent_id: str, updates: dict[str, Any]) -> None:
    """Merge updates into agent state and write to disk."""
    with _AGENT_STATE_WRITE_LOCK:
        state = _load_agent_state(agent_id)
        state["agent_id"] = agent_id
        state["updated_at"] = _UTC_NOW_ISO_FN()
        state.update(updates)
        path = _agent_state_path(agent_id)
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            _AGENT_STATE_CACHE.pop(agent_id, None)
        except OSError as exc:
            print(f"[agent_state] ERROR writing {path}: {exc}")


def _normalize_cli_identity_path(path_value: Any) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return str(Path(raw).expanduser())


def _normalize_resume_id_value(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return ""


def _get_agent_home_dir(agent_id: str) -> str:
    """Get canonical home_dir for an agent."""
    team_config = _TEAM_CONFIG_GETTER()
    if isinstance(team_config, dict):
        for agent in team_config.get("agents", []):
            if agent.get("id") == agent_id:
                return str(agent.get("home_dir", "")).strip()

    state = _load_agent_state(agent_id)
    for key in ("home_dir", "workspace", "project_root"):
        candidate = _normalize_cli_identity_path(state.get(key, ""))
        if candidate:
            layout = _RESOLVE_AGENT_CLI_LAYOUT_FN(candidate, agent_id)
            return str(layout.get("home_dir", "")).strip() or candidate

    if _AGENT_STATE_LOCK is None:
        registered = dict(_REGISTERED_AGENTS_GETTER().get(agent_id) or {})
    else:
        with _AGENT_STATE_LOCK:
            registered = dict(_REGISTERED_AGENTS_GETTER().get(agent_id) or {})
    for key in ("home_dir", "workspace", "project_root"):
        candidate = _normalize_cli_identity_path(registered.get(key, ""))
        if candidate:
            layout = _RESOLVE_AGENT_CLI_LAYOUT_FN(candidate, agent_id)
            return str(layout.get("home_dir", "")).strip() or candidate
    return ""


def _cli_identity_bundle(agent_id: str, payload: dict[str, Any] | None = None) -> dict[str, str]:
    payload = payload or {}
    state = _load_agent_state(agent_id)
    workspace = _normalize_cli_identity_path(payload.get("workspace") or state.get("workspace", ""))
    project_root = _normalize_cli_identity_path(payload.get("project_root") or state.get("project_root", ""))
    home_dir = _normalize_cli_identity_path(payload.get("home_dir") or state.get("home_dir", ""))
    instruction_path = _normalize_cli_identity_path(payload.get("instruction_path") or state.get("instruction_path", ""))
    resume_id_raw = str(payload.get("resume_id") or state.get("resume_id", "")).strip()
    explicit_source = str(payload.get("cli_identity_source") or state.get("cli_identity_source", "")).strip()
    team_home = _normalize_cli_identity_path(_get_agent_home_dir(agent_id))

    if workspace:
        layout = _RESOLVE_AGENT_CLI_LAYOUT_FN(workspace, agent_id)
    elif project_root:
        layout = _RESOLVE_AGENT_CLI_LAYOUT_FN(project_root, agent_id)
    elif home_dir:
        layout = _RESOLVE_AGENT_CLI_LAYOUT_FN(home_dir, agent_id)
    elif team_home:
        layout = _RESOLVE_AGENT_CLI_LAYOUT_FN(team_home, agent_id)
    else:
        layout = {"home_dir": "", "workspace": "", "project_root": ""}

    payload_present = any((workspace, project_root, home_dir, instruction_path, resume_id_raw))
    source = explicit_source or ("cli_register" if payload_present else ("team_home_fallback" if team_home else ""))

    return {
        "resume_id": _normalize_resume_id_value(resume_id_raw),
        "workspace": str(layout.get("workspace", "")).strip(),
        "project_root": str(layout.get("project_root", "")).strip(),
        "home_dir": str(layout.get("home_dir", "")).strip() or home_dir or team_home,
        "instruction_path": instruction_path,
        "cli_identity_source": source,
    }
