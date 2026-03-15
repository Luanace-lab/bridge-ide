"""Read-only team route extraction from server.py."""

from __future__ import annotations

import re
from typing import Any, Callable


_TEAM_CONFIG_GETTER: Callable[[], dict[str, Any] | None] | None = None
_TEAM_CONFIG_SNAPSHOT_FN: Callable[[], dict[str, Any] | None] | None = None
_CURRENT_RUNTIME_OVERLAY_FN: Callable[[], dict[str, Any] | None] | None = None
_RUNTIME_OVERLAY_ORGCHART_RESPONSE_FN: Callable[[dict[str, Any]], dict[str, Any]] | None = None
_RUNTIME_OVERLAY_TEAM_PROJECTS_RESPONSE_FN: Callable[[dict[str, Any]], dict[str, Any]] | None = None
_RUNTIME_OVERLAY_TEAMS_RESPONSE_FN: Callable[[dict[str, Any]], dict[str, Any]] | None = None
_RUNTIME_OVERLAY_TEAM_DETAIL_FN: Callable[[dict[str, Any], str], dict[str, Any] | None] | None = None
_RUNTIME_OVERLAY_TEAM_CONTEXT_FN: Callable[[dict[str, Any], str], dict[str, Any] | None] | None = None
_REGISTERED_AGENTS_GETTER: Callable[[], dict[str, Any]] | None = None
_AGENT_ACTIVITIES_GETTER: Callable[[], dict[str, Any]] | None = None
_AGENT_CONNECTION_STATUS_FN: Callable[[str], str] | None = None
_TEAM_CONFIG_LOCK: Any = None
_ATOMIC_WRITE_TEAM_JSON_FN: Callable[[], None] | None = None
_UTC_NOW_ISO_FN: Callable[[], str] | None = None
_WS_BROADCAST_FN: Callable[[str, dict[str, Any]], None] | None = None
_NOTIFY_TEAM_CHANGE_FN: Callable[[str, str], None] | None = None
_HOT_RELOAD_TEAM_CONFIG_FN: Callable[[], dict[str, Any] | None] | None = None


def init(
    *,
    team_config_getter: Callable[[], dict[str, Any] | None],
    team_config_snapshot_fn: Callable[[], dict[str, Any] | None],
    current_runtime_overlay_fn: Callable[[], dict[str, Any] | None],
    runtime_overlay_orgchart_response_fn: Callable[[dict[str, Any]], dict[str, Any]],
    runtime_overlay_team_projects_response_fn: Callable[[dict[str, Any]], dict[str, Any]],
    runtime_overlay_teams_response_fn: Callable[[dict[str, Any]], dict[str, Any]],
    runtime_overlay_team_detail_fn: Callable[[dict[str, Any], str], dict[str, Any] | None],
    runtime_overlay_team_context_fn: Callable[[dict[str, Any], str], dict[str, Any] | None],
    registered_agents_getter: Callable[[], dict[str, Any]],
    agent_activities_getter: Callable[[], dict[str, Any]],
    agent_connection_status_fn: Callable[[str], str],
    team_config_lock: Any,
    atomic_write_team_json_fn: Callable[[], None],
    utc_now_iso_fn: Callable[[], str],
    ws_broadcast_fn: Callable[[str, dict[str, Any]], None],
    notify_team_change_fn: Callable[..., None],
    hot_reload_team_config_fn: Callable[[], dict[str, Any] | None],
) -> None:
    global _TEAM_CONFIG_GETTER
    global _TEAM_CONFIG_SNAPSHOT_FN, _CURRENT_RUNTIME_OVERLAY_FN, _RUNTIME_OVERLAY_ORGCHART_RESPONSE_FN
    global _RUNTIME_OVERLAY_TEAM_PROJECTS_RESPONSE_FN, _RUNTIME_OVERLAY_TEAMS_RESPONSE_FN
    global _RUNTIME_OVERLAY_TEAM_DETAIL_FN, _RUNTIME_OVERLAY_TEAM_CONTEXT_FN
    global _REGISTERED_AGENTS_GETTER, _AGENT_ACTIVITIES_GETTER, _AGENT_CONNECTION_STATUS_FN
    global _TEAM_CONFIG_LOCK, _ATOMIC_WRITE_TEAM_JSON_FN, _UTC_NOW_ISO_FN, _WS_BROADCAST_FN, _NOTIFY_TEAM_CHANGE_FN
    global _HOT_RELOAD_TEAM_CONFIG_FN

    _TEAM_CONFIG_GETTER = team_config_getter
    _TEAM_CONFIG_SNAPSHOT_FN = team_config_snapshot_fn
    _CURRENT_RUNTIME_OVERLAY_FN = current_runtime_overlay_fn
    _RUNTIME_OVERLAY_ORGCHART_RESPONSE_FN = runtime_overlay_orgchart_response_fn
    _RUNTIME_OVERLAY_TEAM_PROJECTS_RESPONSE_FN = runtime_overlay_team_projects_response_fn
    _RUNTIME_OVERLAY_TEAMS_RESPONSE_FN = runtime_overlay_teams_response_fn
    _RUNTIME_OVERLAY_TEAM_DETAIL_FN = runtime_overlay_team_detail_fn
    _RUNTIME_OVERLAY_TEAM_CONTEXT_FN = runtime_overlay_team_context_fn
    _REGISTERED_AGENTS_GETTER = registered_agents_getter
    _AGENT_ACTIVITIES_GETTER = agent_activities_getter
    _AGENT_CONNECTION_STATUS_FN = agent_connection_status_fn
    _TEAM_CONFIG_LOCK = team_config_lock
    _ATOMIC_WRITE_TEAM_JSON_FN = atomic_write_team_json_fn
    _UTC_NOW_ISO_FN = utc_now_iso_fn
    _WS_BROADCAST_FN = ws_broadcast_fn
    _NOTIFY_TEAM_CHANGE_FN = notify_team_change_fn
    _HOT_RELOAD_TEAM_CONFIG_FN = hot_reload_team_config_fn


def _team_config() -> dict[str, Any] | None:
    if _TEAM_CONFIG_GETTER is None:
        raise RuntimeError("handlers.teams_routes.init() not called: team_config_getter missing")
    return _TEAM_CONFIG_GETTER()


def _team_config_snapshot() -> dict[str, Any] | None:
    if _TEAM_CONFIG_SNAPSHOT_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: team_config_snapshot_fn missing")
    return _TEAM_CONFIG_SNAPSHOT_FN()


def _current_runtime_overlay() -> dict[str, Any] | None:
    if _CURRENT_RUNTIME_OVERLAY_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: current_runtime_overlay_fn missing")
    return _CURRENT_RUNTIME_OVERLAY_FN()


def _runtime_overlay_team_projects_response(overlay: dict[str, Any]) -> dict[str, Any]:
    if _RUNTIME_OVERLAY_TEAM_PROJECTS_RESPONSE_FN is None:
        raise RuntimeError(
            "handlers.teams_routes.init() not called: runtime_overlay_team_projects_response_fn missing"
        )
    return _RUNTIME_OVERLAY_TEAM_PROJECTS_RESPONSE_FN(overlay)


def _runtime_overlay_orgchart_response(overlay: dict[str, Any]) -> dict[str, Any]:
    if _RUNTIME_OVERLAY_ORGCHART_RESPONSE_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: runtime_overlay_orgchart_response_fn missing")
    return _RUNTIME_OVERLAY_ORGCHART_RESPONSE_FN(overlay)


def _runtime_overlay_teams_response(overlay: dict[str, Any]) -> dict[str, Any]:
    if _RUNTIME_OVERLAY_TEAMS_RESPONSE_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: runtime_overlay_teams_response_fn missing")
    return _RUNTIME_OVERLAY_TEAMS_RESPONSE_FN(overlay)


def _runtime_overlay_team_detail(overlay: dict[str, Any], team_id: str) -> dict[str, Any] | None:
    if _RUNTIME_OVERLAY_TEAM_DETAIL_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: runtime_overlay_team_detail_fn missing")
    return _RUNTIME_OVERLAY_TEAM_DETAIL_FN(overlay, team_id)


def _runtime_overlay_team_context(overlay: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    if _RUNTIME_OVERLAY_TEAM_CONTEXT_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: runtime_overlay_team_context_fn missing")
    return _RUNTIME_OVERLAY_TEAM_CONTEXT_FN(overlay, agent_id)


def _registered_agents() -> dict[str, Any]:
    if _REGISTERED_AGENTS_GETTER is None:
        raise RuntimeError("handlers.teams_routes.init() not called: registered_agents_getter missing")
    return _REGISTERED_AGENTS_GETTER()


def _agent_activities() -> dict[str, Any]:
    if _AGENT_ACTIVITIES_GETTER is None:
        raise RuntimeError("handlers.teams_routes.init() not called: agent_activities_getter missing")
    return _AGENT_ACTIVITIES_GETTER()


def _agent_connection_status(agent_id: str) -> str:
    if _AGENT_CONNECTION_STATUS_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: agent_connection_status_fn missing")
    return _AGENT_CONNECTION_STATUS_FN(agent_id)


def _atomic_write_team_json() -> None:
    if _ATOMIC_WRITE_TEAM_JSON_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: atomic_write_team_json_fn missing")
    _ATOMIC_WRITE_TEAM_JSON_FN()


def _utc_now_iso() -> str:
    if _UTC_NOW_ISO_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: utc_now_iso_fn missing")
    return _UTC_NOW_ISO_FN()


def _ws_broadcast(event: str, payload: dict[str, Any]) -> None:
    if _WS_BROADCAST_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: ws_broadcast_fn missing")
    _WS_BROADCAST_FN(event, payload)


def _notify_team_change(event_type: str, details: str, *, affected_agents: list[str] | None = None) -> None:
    if _NOTIFY_TEAM_CHANGE_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: notify_team_change_fn missing")
    _NOTIFY_TEAM_CHANGE_FN(event_type, details, affected_agents=affected_agents or [])


def _hot_reload_team_config() -> dict[str, Any] | None:
    if _HOT_RELOAD_TEAM_CONFIG_FN is None:
        raise RuntimeError("handlers.teams_routes.init() not called: hot_reload_team_config_fn missing")
    return _HOT_RELOAD_TEAM_CONFIG_FN()


def handle_get(handler: Any, path: str, query: dict[str, list[str]] | None = None) -> bool:
    if path == "/team/orgchart":
        team = _team_config()
        if team is None:
            handler._respond(404, {"error": "team.json not loaded"})
            return True
        owner = dict(team.get("owner", {}))
        owner["status"] = "online"
        enriched_agents = []
        for agent in team.get("agents", []):
            status = _agent_connection_status(agent["id"])
            entry = {
                "id": agent["id"],
                "name": agent.get("name", agent["id"]),
                "role": agent.get("role", ""),
                "level": agent.get("level", 99),
                "reports_to": agent.get("reports_to", ""),
                "active": bool(agent.get("active", False)),
                "online": status not in ("disconnected", "offline"),
                "auto_start": bool(agent.get("auto_start", False)),
                "status": status,
            }
            activity = _agent_activities().get(agent["id"])
            entry["activity"] = activity.get("description", "") if activity else ""
            reg = _registered_agents().get(agent["id"])
            entry["context_pct"] = reg.get("context_pct") if reg else None
            enriched_agents.append(entry)
        base_ids = {agent["id"] for agent in enriched_agents}
        overlay = _current_runtime_overlay()
        if overlay:
            overlay_resp = _runtime_overlay_orgchart_response(overlay)
            for overlay_agent in overlay_resp.get("agents", []):
                if overlay_agent.get("id") not in base_ids:
                    enriched_agents.append(overlay_agent)
        handler._respond(200, {"version": team.get("version", 1), "owner": owner, "agents": enriched_agents})
        return True

    if path == "/team/projects":
        team_snapshot = _team_config_snapshot()
        if team_snapshot is None:
            handler._respond(404, {"error": "team.json not loaded"})
            return True
        agent_map: dict[str, dict[str, Any]] = {}
        for agent in team_snapshot.get("agents", []):
            agent_id = str(agent.get("id", "")).strip()
            if agent_id:
                agent_map[agent_id] = agent
        projects_list = []
        for project in team_snapshot.get("projects", []):
            project_id = str(project.get("id", "")).strip()
            resolved_teams = []
            for team_id in project.get("team_ids", []):
                for team in team_snapshot.get("teams", []):
                    if team.get("id") != team_id:
                        continue
                    members = set(team.get("members", []))
                    lead = str(team.get("lead", "")).strip()
                    if lead:
                        members.add(lead)
                    resolved_members = []
                    for member_id in sorted(members):
                        agent_conf = agent_map.get(member_id, {})
                        resolved_members.append(
                            {
                                "id": member_id,
                                "name": agent_conf.get("name", member_id),
                                "role": agent_conf.get("role", ""),
                                "status": _agent_connection_status(member_id),
                                "active": agent_conf.get("active", False),
                            }
                        )
                    resolved_teams.append(
                        {
                            "id": team_id,
                            "name": team.get("name", team_id),
                            "lead": lead,
                            "members": resolved_members,
                            "scope": team.get("scope", ""),
                        }
                    )
                    break
            projects_list.append(
                {
                    "id": project_id,
                    "name": project.get("name", project_id),
                    "path": project.get("path", ""),
                    "description": project.get("description", ""),
                    "teams": resolved_teams,
                    "scope_labels": project.get("scope_labels", {}),
                    "created_at": project.get("created_at", ""),
                }
            )
        overlay = _current_runtime_overlay()
        if overlay:
            overlay_projects = _runtime_overlay_team_projects_response(overlay).get("projects", [])
            overlay_ids = {project.get("id") for project in overlay_projects}
            projects_list = [project for project in projects_list if project.get("id") not in overlay_ids]
            projects_list = overlay_projects + projects_list
        handler._respond(200, {"projects": projects_list})
        return True

    if path == "/teams":
        include_inactive = (query or {}).get("include_inactive", [None])[0] == "true"
        teams_list = []
        team_snapshot = _team_config_snapshot()
        if team_snapshot is not None:
            for team_def in team_snapshot.get("teams", []):
                if not include_inactive and team_def.get("active") is False:
                    continue
                team_id = str(team_def.get("id", "")).strip()
                all_members = set(team_def.get("members", []))
                lead = str(team_def.get("lead", "")).strip()
                if lead:
                    all_members.add(lead)
                online_count = 0
                last_activity: dict[str, Any] | None = None
                last_activity_ts = ""
                for member_id in all_members:
                    if _agent_connection_status(member_id) == "online":
                        online_count += 1
                    activity = _agent_activities().get(member_id)
                    if activity:
                        timestamp = activity.get("timestamp", "")
                        if timestamp > last_activity_ts:
                            last_activity_ts = timestamp
                            last_activity = activity
                teams_list.append(
                    {
                        "id": team_id,
                        "name": team_def.get("name", team_id),
                        "lead": lead,
                        "members": sorted(all_members),
                        "member_count": len(all_members),
                        "online_count": online_count,
                        "scope": team_def.get("scope", ""),
                        "active": team_def.get("active", False),
                        "last_activity": last_activity,
                    }
                )
        overlay = _current_runtime_overlay()
        if overlay:
            overlay_teams = _runtime_overlay_teams_response(overlay).get("teams", [])
            overlay_ids = {team.get("id") for team in overlay_teams}
            teams_list = [team for team in teams_list if team.get("id") not in overlay_ids]
            teams_list = overlay_teams + teams_list
        if not teams_list and team_snapshot is None:
            handler._respond(404, {"error": "team.json not loaded"})
            return True
        handler._respond(200, {"teams": teams_list})
        return True

    teams_detail_match = re.match(r"^/teams/([a-z0-9_-]+)$", path)
    if teams_detail_match:
        team_id = teams_detail_match.group(1)
        overlay = _current_runtime_overlay()
        overlay_detail = _runtime_overlay_team_detail(overlay, team_id) if overlay else None
        team_snapshot = _team_config_snapshot()
        if team_snapshot is None:
            if overlay_detail is not None:
                handler._respond(200, overlay_detail)
                return True
            handler._respond(404, {"error": "team.json not loaded"})
            return True
        team_def = next((team for team in team_snapshot.get("teams", []) if team.get("id") == team_id), None)
        if team_def is None:
            if overlay_detail is not None:
                handler._respond(200, overlay_detail)
                return True
            handler._respond(404, {"error": f"team '{team_id}' not found"})
            return True
        all_members = set(team_def.get("members", []))
        lead = str(team_def.get("lead", "")).strip()
        if lead:
            all_members.add(lead)
        registered_agents = _registered_agents()
        enriched_members = []
        for member_id in sorted(all_members):
            activity = _agent_activities().get(member_id)
            reg = registered_agents.get(member_id)
            agent_info = next(
                (agent for agent in team_snapshot.get("agents", []) if agent.get("id") == member_id),
                {},
            )
            enriched_members.append(
                {
                    "id": member_id,
                    "name": agent_info.get("name", member_id),
                    "role": agent_info.get("role", ""),
                    "is_lead": member_id == lead,
                    "status": _agent_connection_status(member_id),
                    "activity": activity,
                    "context_pct": reg.get("context_pct") if reg else None,
                }
            )
        detail_response = {
            "id": team_id,
            "name": team_def.get("name", team_id),
            "lead": lead,
            "scope": team_def.get("scope", ""),
            "active": team_def.get("active", False),
            "members": enriched_members,
        }
        if overlay_detail is not None:
            overlay_members = {
                member.get("id"): member for member in overlay_detail.get("members", []) if member.get("id")
            }
            base_member_ids = {member["id"] for member in detail_response["members"]}
            for member in detail_response["members"]:
                overlay_member = overlay_members.get(member["id"])
                if not overlay_member:
                    continue
                member["status"] = overlay_member.get("status", member.get("status"))
                member["activity"] = overlay_member.get("activity", member.get("activity"))
                member["context_pct"] = overlay_member.get("context_pct", member.get("context_pct"))
                member["name"] = member.get("name") or overlay_member.get("name", member["id"])
                member["role"] = member.get("role") or overlay_member.get("role", "")
            for member_id, overlay_member in overlay_members.items():
                if member_id in base_member_ids:
                    continue
                detail_response["members"].append(
                    {
                        "id": member_id,
                        "name": overlay_member.get("name", member_id),
                        "role": overlay_member.get("role", ""),
                        "is_lead": bool(overlay_member.get("is_lead", False)),
                        "status": overlay_member.get("status", "offline"),
                        "activity": overlay_member.get("activity"),
                        "context_pct": overlay_member.get("context_pct"),
                    }
                )
        handler._respond(200, detail_response)
        return True

    team_context_match = re.match(r"^/team/context/([a-z0-9_-]+)$", path)
    if team_context_match:
        agent_id = team_context_match.group(1)
        team_snapshot = _team_config_snapshot()
        agent_conf = None
        if team_snapshot:
            agent_conf = next(
                (agent for agent in team_snapshot.get("agents", []) if agent.get("id") == agent_id),
                None,
            )
        if agent_conf is None:
            overlay = _current_runtime_overlay()
            if overlay:
                detail = _runtime_overlay_team_context(overlay, agent_id)
                if detail is not None:
                    handler._respond(200, detail)
                    return True
            handler._respond(404, {"error": f"agent '{agent_id}' not found in team.json or overlay"})
            return True
        my_teams = []
        for team in team_snapshot.get("teams", []):
            if team.get("active", False) is False:
                continue
            members = set(team.get("members", []) or [])
            lead = str(team.get("lead", "")).strip()
            if lead:
                members.add(lead)
            if agent_id in members:
                my_teams.append(team)
        teammates = []
        team_info: dict[str, Any] = {}
        if my_teams:
            primary_team = my_teams[0]
            team_info = {
                "id": primary_team.get("id", ""),
                "name": primary_team.get("name", ""),
                "lead": primary_team.get("lead", ""),
                "scope": primary_team.get("scope", ""),
            }
            primary_members = set(primary_team.get("members", []) or [])
            lead = str(primary_team.get("lead", "")).strip()
            if lead:
                primary_members.add(lead)
            primary_members.discard(agent_id)
            registered_agents = _registered_agents()
            for member_id in sorted(primary_members):
                agent_info = next(
                    (agent for agent in team_snapshot.get("agents", []) if agent.get("id") == member_id),
                    {},
                )
                teammates.append(
                    {
                        "id": member_id,
                        "name": agent_info.get("name", member_id),
                        "role": agent_info.get("role", ""),
                        "skills": agent_info.get("skills", []),
                        "status": _agent_connection_status(member_id) if member_id in registered_agents else "offline",
                    }
                )
        handler._respond(
            200,
            {
                "agent_id": agent_id,
                "name": agent_conf.get("name", ""),
                "role": agent_conf.get("role", ""),
                "description": agent_conf.get("description", ""),
                "skills": agent_conf.get("skills", []),
                "permissions": agent_conf.get("permissions", {}),
                "team": team_info,
                "teams": [{"id": team.get("id", ""), "name": team.get("name", "")} for team in my_teams],
                "reports_to": agent_conf.get("reports_to", ""),
                "level": agent_conf.get("level"),
                "teammates": teammates,
            },
        )
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    if path == "/team/reload":
        result = _hot_reload_team_config()
        if result is None:
            handler._respond(500, {"error": "team.json could not be loaded"})
            return True
        handler._respond(200, result)
        return True

    if path != "/teams":
        return False
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True
    team_config = _team_config()
    if team_config is None:
        handler._respond(500, {"error": "team.json not loaded"})
        return True
    name = str(data.get("name", "")).strip()
    lead = str(data.get("lead", "")).strip()
    members = data.get("members", [])
    scope = str(data.get("scope", "")).strip()
    if not name or not lead:
        handler._respond(400, {"error": "name and lead are required"})
        return True
    if not isinstance(members, list):
        handler._respond(400, {"error": "members must be a list"})
        return True
    team_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not team_id:
        handler._respond(400, {"error": "invalid team name"})
        return True
    new_team = {
        "id": team_id,
        "name": name,
        "lead": lead,
        "members": [str(member).strip() for member in members if str(member).strip()],
        "scope": scope,
        "active": True,
    }
    with _TEAM_CONFIG_LOCK:
        existing_ids = {team.get("id") for team in team_config.get("teams", [])}
        if team_id in existing_ids:
            handler._respond(409, {"error": f"team '{team_id}' already exists"})
            return True
        teams_list = team_config.setdefault("teams", [])
        teams_list.append(new_team)
        try:
            _atomic_write_team_json()
        except OSError as exc:
            teams_list.pop()
            handler._respond(500, {"error": f"failed to persist team.json: {exc}"})
            return True
    all_team_members = list(dict.fromkeys(new_team["members"] + [lead]))
    print(f"[teams] Created team '{team_id}' (lead={lead}, members={new_team['members']})")
    _ws_broadcast("team_created", {"team": new_team})
    _notify_team_change("team_created", f"Team '{team_id}' erstellt (Lead: {lead})", affected_agents=all_team_members)
    handler._respond(201, {"ok": True, "team": new_team})
    return True


def handle_put(handler: Any, path: str) -> bool:
    teams_members_match = re.match(r"^/teams/([a-z0-9_-]+)/members$", path)
    if not teams_members_match:
        return False
    team_id = teams_members_match.group(1)
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True
    team_config = _team_config()
    if team_config is None:
        handler._respond(500, {"error": "team.json not loaded"})
        return True
    add_members = data.get("add", [])
    remove_members = data.get("remove", [])
    if not isinstance(add_members, list) or not isinstance(remove_members, list):
        handler._respond(400, {"error": "add and remove must be lists"})
        return True
    with _TEAM_CONFIG_LOCK:
        target_team = next((team for team in team_config.get("teams", []) if team.get("id") == team_id), None)
        if not target_team:
            handler._respond(404, {"error": f"team '{team_id}' not found"})
            return True
        old_members = list(target_team.get("members", []))
        members = set(old_members)
        for member in add_members:
            members.add(str(member).strip())
        for member in remove_members:
            members.discard(str(member).strip())
        members.discard("")
        target_team["members"] = sorted(members)
        try:
            _atomic_write_team_json()
        except OSError as exc:
            target_team["members"] = old_members
            handler._respond(500, {"error": f"failed to persist team.json: {exc}"})
            return True
        updated_members = list(target_team["members"])
    print(f"[teams] Updated members of '{team_id}': +{add_members} -{remove_members}")
    _ws_broadcast("team_updated", {"team_id": team_id, "members": updated_members})
    affected_agents = list(set(list(add_members) + list(remove_members)))
    _notify_team_change(
        "team_members_changed",
        f"Team '{team_id}': +{list(add_members)} -{list(remove_members)}",
        affected_agents=affected_agents,
    )
    handler._respond(200, {"ok": True, "team_id": team_id, "members": updated_members})
    return True


def handle_delete(handler: Any, path: str) -> bool:
    teams_delete_match = re.match(r"^/teams/([a-z0-9_-]+)$", path)
    if not teams_delete_match:
        return False
    team_id = teams_delete_match.group(1)
    team_config = _team_config()
    if team_config is None:
        handler._respond(500, {"error": "team.json not loaded"})
        return True
    with _TEAM_CONFIG_LOCK:
        target_team = next((team for team in team_config.get("teams", []) if team.get("id") == team_id), None)
        if not target_team:
            handler._respond(404, {"error": f"team '{team_id}' not found"})
            return True
        if target_team.get("active") is False:
            handler._respond(409, {"error": f"team '{team_id}' is already inactive"})
            return True
        previous_active = target_team.get("active")
        previous_deleted_at = target_team.get("deleted_at")
        target_team["active"] = False
        target_team["deleted_at"] = _utc_now_iso()
        try:
            _atomic_write_team_json()
        except OSError as exc:
            if previous_active is None:
                target_team.pop("active", None)
            else:
                target_team["active"] = previous_active
            if previous_deleted_at is None:
                target_team.pop("deleted_at", None)
            else:
                target_team["deleted_at"] = previous_deleted_at
            handler._respond(500, {"error": f"failed to persist team.json: {exc}"})
            return True
        team_members_list = list(set(target_team.get("members", [])))
        lead = str(target_team.get("lead", "")).strip()
        if lead:
            team_members_list.append(lead)
    print(f"[W5] Team '{team_id}' soft-deleted")
    _ws_broadcast("team_deleted", {"team_id": team_id})
    _notify_team_change("team_deleted", f"Team '{team_id}' wurde deaktiviert", affected_agents=team_members_list)
    handler._respond(200, {"ok": True, "team_id": team_id, "active": False})
    return True
