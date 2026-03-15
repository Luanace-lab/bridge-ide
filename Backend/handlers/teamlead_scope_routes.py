"""Teamlead scope GET/POST route extraction from server.py."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


_runtime_lock: Any = None
_runtime_state_getter: Callable[[], dict[str, Any]] | None = None
_projects_base_dir_getter: Callable[[], str] | None = None
_validate_project_path_fn: Callable[[Any, str], str | None] | None = None
_resolve_team_lead_scope_file_fn: Callable[[str, Any], str] | None = None
_ensure_parent_dir_fn: Callable[[str], None] | None = None


def init(
    *,
    runtime_lock: Any,
    runtime_state_getter: Callable[[], dict[str, Any]],
    projects_base_dir_getter: Callable[[], str],
    validate_project_path_fn: Callable[[Any, str], str | None],
    resolve_team_lead_scope_file_fn: Callable[[str, Any], str],
    ensure_parent_dir_fn: Callable[[str], None],
) -> None:
    global _runtime_lock, _runtime_state_getter, _projects_base_dir_getter
    global _validate_project_path_fn, _resolve_team_lead_scope_file_fn, _ensure_parent_dir_fn

    _runtime_lock = runtime_lock
    _runtime_state_getter = runtime_state_getter
    _projects_base_dir_getter = projects_base_dir_getter
    _validate_project_path_fn = validate_project_path_fn
    _resolve_team_lead_scope_file_fn = resolve_team_lead_scope_file_fn
    _ensure_parent_dir_fn = ensure_parent_dir_fn


def _runtime_state() -> dict[str, Any]:
    if _runtime_state_getter is None:
        raise RuntimeError("handlers.teamlead_scope_routes.init() not called: runtime_state_getter missing")
    return _runtime_state_getter()


def _projects_base_dir() -> str:
    if _projects_base_dir_getter is None:
        raise RuntimeError("handlers.teamlead_scope_routes.init() not called: projects_base_dir_getter missing")
    return _projects_base_dir_getter()


def _validate_project_path(raw_path: Any, base_dir: str) -> str | None:
    if _validate_project_path_fn is None:
        raise RuntimeError("handlers.teamlead_scope_routes.init() not called: validate_project_path_fn missing")
    return _validate_project_path_fn(raw_path, base_dir)


def _resolve_scope_file(project_path: str, raw_path: Any) -> str:
    if _resolve_team_lead_scope_file_fn is None:
        raise RuntimeError("handlers.teamlead_scope_routes.init() not called: resolve_team_lead_scope_file_fn missing")
    return _resolve_team_lead_scope_file_fn(project_path, raw_path)


def _ensure_parent_dir(path: str) -> None:
    if _ensure_parent_dir_fn is None:
        raise RuntimeError("handlers.teamlead_scope_routes.init() not called: ensure_parent_dir_fn missing")
    _ensure_parent_dir_fn(path)


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path != "/teamlead/scope":
        return False

    with _runtime_lock:
        runtime = _runtime_state()
        runtime_project = str(runtime.get("project_path", _projects_base_dir()))
        runtime_scope_file = str(runtime.get("team_lead_scope_file", ""))
    project_path = _validate_project_path((query.get("project_path") or [None])[0], runtime_project)
    if not project_path:
        handler._respond(403, {"error": "path outside allowed directory"})
        return True
    raw_path = (query.get("path") or [runtime_scope_file])[0]
    try:
        scope_file = _resolve_scope_file(project_path, raw_path)
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True

    exists = os.path.exists(scope_file)
    content = ""
    if exists:
        try:
            content = Path(scope_file).read_text(encoding="utf-8")
        except OSError:
            content = ""

    handler._respond(
        200,
        {
            "ok": True,
            "project_path": project_path,
            "scope_file": scope_file,
            "exists": exists,
            "content": content,
        },
    )
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path != "/teamlead/scope":
        return False

    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True

    with _runtime_lock:
        runtime = _runtime_state()
        runtime_project = str(runtime.get("project_path", _projects_base_dir()))
    project_path = _validate_project_path(data.get("project_path"), runtime_project)
    if not project_path:
        handler._respond(403, {"error": "path outside allowed directory"})
        return True
    if not os.path.isdir(project_path):
        handler._respond(400, {"error": f"project_path does not exist: {project_path}"})
        return True

    try:
        scope_file = _resolve_scope_file(project_path, data.get("scope_file"))
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True

    content = data.get("content", "")
    if not isinstance(content, str):
        content = str(content)

    _ensure_parent_dir(scope_file)
    try:
        Path(scope_file).write_text(content, encoding="utf-8")
    except OSError as exc:
        handler._respond(500, {"error": f"could not write scope file: {exc}"})
        return True

    with _runtime_lock:
        runtime = _runtime_state()
        if str(runtime.get("project_path", "")) == project_path:
            runtime["team_lead_scope_file"] = scope_file

    handler._respond(
        200,
        {
            "ok": True,
            "project_path": project_path,
            "scope_file": scope_file,
            "bytes": len(content.encode("utf-8")),
        },
    )
    return True
