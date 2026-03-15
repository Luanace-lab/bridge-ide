"""Read-only board route extraction from server.py."""

from __future__ import annotations

import re
from typing import Any, Callable

import board_api


_REGISTERED_AGENTS_GETTER: Callable[[], dict[str, Any]] | None = None
_AGENT_ACTIVITIES_GETTER: Callable[[], dict[str, Any]] | None = None
_CURRENT_RUNTIME_OVERLAY_FN: Callable[[], dict[str, Any] | None] | None = None
_RUNTIME_OVERLAY_BOARD_PROJECTS_RESPONSE_FN: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def init(
    *,
    registered_agents_getter: Callable[[], dict[str, Any]],
    agent_activities_getter: Callable[[], dict[str, Any]],
    current_runtime_overlay_fn: Callable[[], dict[str, Any] | None],
    runtime_overlay_board_projects_response_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    global _REGISTERED_AGENTS_GETTER, _AGENT_ACTIVITIES_GETTER
    global _CURRENT_RUNTIME_OVERLAY_FN, _RUNTIME_OVERLAY_BOARD_PROJECTS_RESPONSE_FN
    _REGISTERED_AGENTS_GETTER = registered_agents_getter
    _AGENT_ACTIVITIES_GETTER = agent_activities_getter
    _CURRENT_RUNTIME_OVERLAY_FN = current_runtime_overlay_fn
    _RUNTIME_OVERLAY_BOARD_PROJECTS_RESPONSE_FN = runtime_overlay_board_projects_response_fn


def _registered_agents() -> dict[str, Any]:
    if _REGISTERED_AGENTS_GETTER is None:
        raise RuntimeError("handlers.board_routes.init() not called: registered_agents_getter missing")
    return _REGISTERED_AGENTS_GETTER()


def _agent_activities() -> dict[str, Any]:
    if _AGENT_ACTIVITIES_GETTER is None:
        raise RuntimeError("handlers.board_routes.init() not called: agent_activities_getter missing")
    return _AGENT_ACTIVITIES_GETTER()


def _current_runtime_overlay() -> dict[str, Any] | None:
    if _CURRENT_RUNTIME_OVERLAY_FN is None:
        raise RuntimeError("handlers.board_routes.init() not called: current_runtime_overlay_fn missing")
    return _CURRENT_RUNTIME_OVERLAY_FN()


def _runtime_overlay_board_projects_response(overlay: dict[str, Any]) -> dict[str, Any]:
    if _RUNTIME_OVERLAY_BOARD_PROJECTS_RESPONSE_FN is None:
        raise RuntimeError(
            "handlers.board_routes.init() not called: runtime_overlay_board_projects_response_fn missing"
        )
    return _RUNTIME_OVERLAY_BOARD_PROJECTS_RESPONSE_FN(overlay)


def handle_get(handler: Any, path: str, query: dict[str, list[str]] | None = None) -> bool:
    if path == "/board/projects":
        payload = board_api.get_all_projects(_registered_agents(), _agent_activities())
        overlay = _current_runtime_overlay()
        if overlay:
            runtime_payload = _runtime_overlay_board_projects_response(overlay)
            runtime_projects = runtime_payload.get("projects", [])
            base_projects = payload.get("projects", []) if isinstance(payload, dict) else []
            runtime_ids = {project.get("id") for project in runtime_projects}
            merged = [project for project in base_projects if project.get("id") not in runtime_ids]
            payload = {"projects": runtime_projects + merged}
        if query:
            raw_limit = (query.get("limit") or [None])[0]
            if raw_limit is not None:
                try:
                    limit = max(int(raw_limit), 0)
                    if isinstance(payload, dict) and isinstance(payload.get("projects"), list):
                        payload = dict(payload)
                        payload["projects"] = payload["projects"][:limit]
                except (TypeError, ValueError):
                    pass
        handler._respond(200, payload)
        return True

    project_match = re.match(r"^/board/projects/([a-z0-9][a-z0-9-]*)$", path)
    if project_match:
        project_id = project_match.group(1)
        overlay = _current_runtime_overlay()
        if overlay:
            for project in _runtime_overlay_board_projects_response(overlay).get("projects", []):
                if project.get("id") == project_id:
                    handler._respond(200, {"project": project})
                    return True
        result = board_api.get_project(project_id, _registered_agents(), _agent_activities())
        if result is None:
            handler._respond(404, {"error": f"project not found: {project_id}"})
        else:
            handler._respond(200, result)
        return True

    if path == "/board/agents":
        handler._respond(200, board_api.get_all_agents(_registered_agents(), _agent_activities()))
        return True

    agent_projects_match = re.match(r"^/board/agents/([^/]+)/projects$", path)
    if agent_projects_match:
        agent_id = agent_projects_match.group(1)
        handler._respond(200, board_api.get_agent_projects(agent_id, _registered_agents(), _agent_activities()))
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    if path == "/board/projects":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True
        project_id = str(data.get("id") or data.get("project_id") or "").strip()
        project_name = str(data.get("name", "")).strip()
        try:
            result = board_api.create_project(project_id, project_name)
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        handler._respond(201, result)
        return True

    team_match = re.match(r"^/board/projects/([a-z0-9][a-z0-9-]*)/teams$", path)
    if team_match:
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True
        try:
            result = board_api.add_team(
                team_match.group(1),
                str(data.get("id", "")).strip(),
                str(data.get("name", "")).strip(),
            )
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        handler._respond(201, result)
        return True

    member_match = re.match(
        r"^/board/projects/([a-z0-9][a-z0-9-]*)/teams/([a-z0-9][a-z0-9-]*)/members$",
        path,
    )
    if not member_match:
        return False
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True
    try:
        result = board_api.add_member(
            member_match.group(1),
            member_match.group(2),
            str(data.get("agent_id", "")).strip(),
        )
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True
    handler._respond(201, result)
    return True


def handle_put(handler: Any, path: str) -> bool:
    project_match = re.match(r"^/board/projects/([a-z0-9][a-z0-9-]*)$", path)
    if project_match:
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True
        try:
            result = board_api.update_project(
                project_match.group(1),
                str(data.get("name", "")).strip(),
            )
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        handler._respond(200, result)
        return True

    team_match = re.match(r"^/board/projects/([a-z0-9][a-z0-9-]*)/teams/([a-z0-9][a-z0-9-]*)$", path)
    if not team_match:
        return False
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True
    try:
        result = board_api.update_team(
            team_match.group(1),
            team_match.group(2),
            str(data.get("name", "")).strip(),
        )
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True
    handler._respond(200, result)
    return True


def handle_delete(handler: Any, path: str) -> bool:
    project_match = re.match(r"^/board/projects/([a-z0-9][a-z0-9-]*)$", path)
    if project_match:
        try:
            result = board_api.delete_project(project_match.group(1))
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        handler._respond(200, result)
        return True

    team_match = re.match(r"^/board/projects/([a-z0-9][a-z0-9-]*)/teams/([a-z0-9][a-z0-9-]*)$", path)
    if team_match:
        try:
            result = board_api.delete_team(
                team_match.group(1),
                team_match.group(2),
            )
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        handler._respond(200, result)
        return True

    member_match = re.match(
        r"^/board/projects/([a-z0-9][a-z0-9-]*)/teams/([a-z0-9][a-z0-9-]*)/members/([^/]+)$",
        path,
    )
    if not member_match:
        return False
    try:
        result = board_api.remove_member(
            member_match.group(1),
            member_match.group(2),
            member_match.group(3),
        )
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True
    handler._respond(200, result)
    return True
