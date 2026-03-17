"""Runtime config/overlay/snapshot functions extracted from server.py (Slice 04).

This module owns:
- Runtime profile normalization and building
- Runtime overlay build/persist/restore/query
- Runtime overlay response formatters
- Runtime snapshot
- Team lead state management
- Runtime agent queries

Anti-circular-import strategy:
  All shared state and cross-domain functions are injected via init().
  This module NEVER imports from server.
  Direct imports only from: runtime_layout, handlers.agents, board_api, tmux_manager.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable

import runtime_layout
from handlers.agents import agent_connection_status, _PREV_AGENT_STATUS
import board_api
from tmux_manager import is_session_alive

# ---------------------------------------------------------------------------
# Constants (owned by this module — not injected)
# ---------------------------------------------------------------------------
_RUNTIME_LEVELS = {"owner": 0, "lead": 1, "senior": 2, "worker": 3}
_RUNTIME_CAPABILITIES = {"code", "review", "strategy", "marketing", "finance", "ops", "design", "qa"}
_RUNTIME_PERMISSION_MODES = {"default", "acceptEdits", "dontAsk", "bypassPermissions", "plan"}

# ---------------------------------------------------------------------------
# Injected shared state (set by init())
# ---------------------------------------------------------------------------
_RUNTIME: dict[str, Any] = {}
_RUNTIME_LOCK: Any = None
_TEAM_LEAD_STATE: dict[str, Any] = {}
_TEAM_LEAD_LOCK: Any = None
_REGISTERED_AGENTS: dict[str, dict[str, Any]] = {}
_AGENT_STATE_LOCK: Any = None
_AGENT_LAST_SEEN: dict[str, float] = {}
_AGENT_BUSY: dict[str, bool] = {}
_AGENT_ACTIVITIES: dict[str, dict[str, Any]] = {}
_get_runtime_team_path: Callable[[], str] | None = None
_TEAM_LEAD_ID: str = ""
_KNOWN_ENGINES: set[str] = set()
_ROOT_DIR: str = ""

# ---------------------------------------------------------------------------
# Injected callbacks (set by init())
# ---------------------------------------------------------------------------
_ws_broadcast: Callable[..., Any] | None = None
_tmux_session_for: Callable[[str], str] | None = None
_agent_log_path: Callable[[str], str] | None = None
_parse_scope_tokens: Callable[..., Any] | None = None
_parse_non_negative_int: Callable[..., Any] | None = None
_parse_bool: Callable[..., Any] | None = None
_derive_routes: Callable[..., Any] | None = None


def init(
    *,
    runtime: dict,
    runtime_lock: Any,
    team_lead_state: dict,
    team_lead_lock: Any,
    registered_agents: dict,
    agent_state_lock: Any,
    agent_last_seen: dict,
    agent_busy: dict,
    agent_activities: dict,
    runtime_team_path_fn: Callable[[], str],
    team_lead_id: str,
    known_engines: set,
    root_dir: str,
    ws_broadcast_fn: Callable,
    tmux_session_for_fn: Callable,
    agent_log_path_fn: Callable,
    parse_scope_tokens_fn: Callable,
    parse_non_negative_int_fn: Callable,
    parse_bool_fn: Callable,
    derive_routes_fn: Callable,
) -> None:
    """Bind shared state and cross-domain callbacks.  Must be called once
    before any other function in this module is used."""
    global _RUNTIME, _RUNTIME_LOCK, _TEAM_LEAD_STATE, _TEAM_LEAD_LOCK
    global _REGISTERED_AGENTS, _AGENT_STATE_LOCK
    global _AGENT_LAST_SEEN, _AGENT_BUSY, _AGENT_ACTIVITIES
    global _get_runtime_team_path, _TEAM_LEAD_ID, _KNOWN_ENGINES, _ROOT_DIR
    global _ws_broadcast, _tmux_session_for, _agent_log_path
    global _parse_scope_tokens, _parse_non_negative_int, _parse_bool
    global _derive_routes

    _RUNTIME = runtime
    _RUNTIME_LOCK = runtime_lock
    _TEAM_LEAD_STATE = team_lead_state
    _TEAM_LEAD_LOCK = team_lead_lock
    _REGISTERED_AGENTS = registered_agents
    _AGENT_STATE_LOCK = agent_state_lock
    _AGENT_LAST_SEEN = agent_last_seen
    _AGENT_BUSY = agent_busy
    _AGENT_ACTIVITIES = agent_activities
    _get_runtime_team_path = runtime_team_path_fn
    _TEAM_LEAD_ID = team_lead_id
    _KNOWN_ENGINES = known_engines
    _ROOT_DIR = root_dir

    _ws_broadcast = ws_broadcast_fn
    _tmux_session_for = tmux_session_for_fn
    _agent_log_path = agent_log_path_fn
    _parse_scope_tokens = parse_scope_tokens_fn
    _parse_non_negative_int = parse_non_negative_int_fn
    _parse_bool = parse_bool_fn
    _derive_routes = derive_routes_fn


# ===================================================================
# Team lead state management
# ===================================================================

def reset_team_lead_state(reason: str = "reset") -> None:
    with _TEAM_LEAD_LOCK:
        _TEAM_LEAD_STATE.update(
            {
                "active": False,
                "stopped": False,
                "kickoff_id": None,
                "kickoff_to": "",
                "peer_count": 0,
                "stop_reason": reason,
                "last_event_at": datetime.now(timezone.utc).isoformat(),
            }
        )


# ===================================================================
# Runtime agent queries
# ===================================================================

def current_runtime_agent_ids() -> list[str]:
    with _RUNTIME_LOCK:
        runtime_state = dict(_RUNTIME)
    layout = runtime_layout.runtime_layout_from_state(
        runtime_state,
        known_engines=_KNOWN_ENGINES,
        available_engines=runtime_layout.detect_available_engines(_KNOWN_ENGINES),
        team_lead_id=_TEAM_LEAD_ID,
    )
    return [spec["id"] for spec in layout]


def current_runtime_slot_map() -> dict[str, str]:
    """Fast agent_id -> slot map derived directly from RUNTIME config."""
    with _RUNTIME_LOCK:
        runtime_state = dict(_RUNTIME)
    layout = runtime_layout.runtime_layout_from_state(
        runtime_state,
        known_engines=_KNOWN_ENGINES,
        available_engines=runtime_layout.detect_available_engines(_KNOWN_ENGINES),
        team_lead_id=_TEAM_LEAD_ID,
    )
    return {
        str(spec.get("id", "")).strip(): str(spec.get("slot", "")).strip()
        for spec in layout
        if str(spec.get("id", "")).strip()
    }


def _get_runtime_agent_role(agent_id: str) -> str:
    """Best-effort role/slot from current runtime layout."""
    with _RUNTIME_LOCK:
        runtime_state = dict(_RUNTIME)
    layout = runtime_layout.runtime_layout_from_state(
        runtime_state,
        known_engines=_KNOWN_ENGINES,
        available_engines=runtime_layout.detect_available_engines(_KNOWN_ENGINES),
        team_lead_id=_TEAM_LEAD_ID,
    )
    for spec in layout:
        if spec["id"] == agent_id:
            return str(spec.get("slot", ""))
    return ""


# ===================================================================
# Runtime profile normalization
# ===================================================================

def _runtime_project_id(project_name: str, project_path: str) -> str:
    raw = str(project_name or "").strip() or os.path.basename(project_path.rstrip("/")) or "runtime-project"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "runtime-project"


def _runtime_team_name(team_id: str) -> str:
    cleaned = re.sub(r"[-_]+", " ", str(team_id or "").strip())
    return cleaned.title() if cleaned else "Runtime Team"


def _normalize_runtime_permission_mode(value: Any) -> str:
    mode = str(value or "").strip()
    return mode if mode in _RUNTIME_PERMISSION_MODES else "default"


def _normalize_runtime_level(value: Any, slot: str) -> tuple[str, int]:
    raw = str(value or "").strip().lower()
    if raw not in _RUNTIME_LEVELS:
        raw = "lead" if slot == "lead" else "worker"
    return raw, _RUNTIME_LEVELS[raw]


def _normalize_runtime_capabilities(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        cap = str(item or "").strip().lower()
        if not cap or cap not in _RUNTIME_CAPABILITIES or cap in seen:
            continue
        seen.add(cap)
        out.append(cap)
    return out


def _normalize_runtime_tools(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        tool = str(item or "").strip()
        if not tool or tool in seen:
            continue
        seen.add(tool)
        out.append(tool)
    return out


def _normalize_runtime_profile(
    raw_profile: dict[str, Any],
    spec: dict[str, str],
    *,
    lead_agent_id: str,
    project_id: str,
) -> dict[str, Any]:
    slot = str(spec.get("slot", "")).strip()
    role_default = {
        "lead": "Team Lead",
        "a": "Agent A",
        "b": "Agent B",
    }.get(slot, spec.get("name", spec.get("id", "Agent")))
    role = str(
        raw_profile.get("role")
        or raw_profile.get("position")
        or role_default
    ).strip() or role_default
    name = str(raw_profile.get("name") or spec.get("name") or spec.get("id") or role_default).strip() or str(spec.get("id", "agent"))
    prompt = str(raw_profile.get("prompt") or "").strip()
    level_label, level = _normalize_runtime_level(raw_profile.get("hierarchyLevel"), slot)
    default_team = "management" if level <= 1 else f"{project_id}-team"
    team_id = str(raw_profile.get("teamAssignment") or "").strip() or default_team
    team_id = re.sub(r"[^a-z0-9_-]+", "-", team_id.lower()).strip("-") or default_team
    reports_to = str(raw_profile.get("reportsTo") or "").strip()
    if reports_to in {"", "none", "niemand"}:
        reports_to = ""
    if level <= 1 or slot == "lead":
        reports_to = "user"
    elif not reports_to:
        reports_to = lead_agent_id or "user"
    scope_raw = raw_profile.get("scope", "")
    scope_text = str(scope_raw).strip()
    scope_entries = _parse_scope_tokens(scope_raw)  # type: ignore[misc]
    capabilities = _normalize_runtime_capabilities(raw_profile.get("permissions"))
    permission_mode = _normalize_runtime_permission_mode(raw_profile.get("permission"))
    tools = _normalize_runtime_tools(raw_profile.get("tools"))
    return {
        "id": str(spec.get("id", "")).strip(),
        "slot": slot,
        "name": name,
        "display_name": name,
        "engine": str(spec.get("engine", "")).strip(),
        "role": role,
        "description": prompt or role,
        "prompt": prompt,
        "model": str(raw_profile.get("model") or "").strip(),
        "permission_mode": permission_mode,
        "max_turns": _parse_non_negative_int(raw_profile.get("maxTurns"), 0),  # type: ignore[misc]
        "plan_approval": _parse_bool(raw_profile.get("planApproval"), False),  # type: ignore[misc]
        "isolation": str(raw_profile.get("isolation") or "none").strip() or "none",
        "tools": tools,
        "capabilities": capabilities,
        "scope": scope_entries,
        "scope_text": scope_text,
        "level_label": level_label,
        "level": level,
        "team": team_id,
        "reports_to": reports_to,
        "active": True,
    }


# ===================================================================
# Runtime agent profile building
# ===================================================================

def _build_runtime_agent_profiles(
    data: dict[str, Any],
    layout: list[dict[str, str]],
    *,
    project_name: str,
    project_path: str,
) -> list[dict[str, Any]]:
    leader = data.get("leader") if isinstance(data.get("leader"), dict) else {}
    raw_agents = [a for a in (data.get("agents") if isinstance(data.get("agents"), list) else []) if isinstance(a, dict)]
    slot_payloads: dict[str, dict[str, Any]] = {"lead": leader}
    if len(raw_agents) >= 1:
        slot_payloads["a"] = raw_agents[0]
    if len(raw_agents) >= 2:
        slot_payloads["b"] = raw_agents[1]
    by_id = {
        str(agent.get("id", "")).strip(): agent
        for agent in raw_agents
        if str(agent.get("id", "")).strip()
    }
    by_slot = {
        str(agent.get("slot", "")).strip(): agent
        for agent in raw_agents
        if str(agent.get("slot", "")).strip()
    }
    project_id = _runtime_project_id(project_name, project_path)
    lead_agent_id = next((str(spec.get("id", "")).strip() for spec in layout if spec.get("slot") == "lead"), "")
    profiles: list[dict[str, Any]] = []
    for spec in layout:
        slot = str(spec.get("slot", "")).strip()
        source_index = spec.get("source_index")
        raw_profile: dict[str, Any] = {}
        if slot == "lead":
            raw_profile = leader or by_id.get(str(spec.get("id", "")).strip(), {}) or by_slot.get("lead", {})
        else:
            raw_profile = (
                by_id.get(str(spec.get("id", "")).strip(), {})
                or by_slot.get(slot, {})
            )
            if not raw_profile and isinstance(source_index, int) and 0 <= source_index < len(raw_agents):
                raw_profile = raw_agents[source_index]
            if not raw_profile:
                raw_profile = slot_payloads.get(slot, {})
        profiles.append(
            _normalize_runtime_profile(
                raw_profile,
                spec,
                lead_agent_id=lead_agent_id,
                project_id=project_id,
            )
        )
    return profiles


def _runtime_team_members_for_profiles(agent_id: str, profiles: list[dict[str, Any]]) -> list[dict[str, str]]:
    my_team = ""
    my_level = 99
    for profile in profiles:
        if profile.get("id") == agent_id:
            my_team = str(profile.get("team", "")).strip()
            my_level = int(profile.get("level", 99))
            break
    members: list[dict[str, str]] = []
    for profile in profiles:
        aid = str(profile.get("id", "")).strip()
        if not aid or aid == agent_id:
            continue
        same_team = my_team and str(profile.get("team", "")).strip() == my_team
        if my_level > 1 and not same_team:
            continue
        members.append({
            "id": aid,
            "role": str(profile.get("description") or profile.get("role") or aid).strip(),
        })
    return members


# ===================================================================
# Runtime overlay build / persist / restore / query
# ===================================================================

def _build_runtime_overlay(
    project_name: str,
    project_path: str,
    profiles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not profiles:
        return None
    project_id = _runtime_project_id(project_name, project_path)
    teams_map: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        team_id = str(profile.get("team", "")).strip()
        if not team_id:
            continue
        teams_map.setdefault(team_id, {
            "id": team_id,
            "name": _runtime_team_name(team_id),
            "lead": "",
            "members": [],
            "scope": "",
        })
    for team in teams_map.values():
        members = [p for p in profiles if str(p.get("team", "")).strip() == team["id"]]
        if not members:
            continue
        members_sorted = sorted(members, key=lambda p: (int(p.get("level", 99)), str(p.get("id", ""))))
        team["lead"] = str(members_sorted[0].get("id", "")).strip()
        team["members"] = [
            str(p.get("id", "")).strip()
            for p in members_sorted[1:]
            if str(p.get("id", "")).strip()
        ]
        scopes = [str(p.get("scope_text", "")).strip() for p in members_sorted if str(p.get("scope_text", "")).strip()]
        if scopes:
            team["scope"] = "; ".join(scopes)
    route_seed = {
        "agents": profiles,
        "teams": list(teams_map.values()),
    }
    routes = _derive_routes(route_seed)  # type: ignore[misc]
    routes.setdefault("user", set()).update(str(p.get("id", "")).strip() for p in profiles if str(p.get("id", "")).strip())
    return {
        "active": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": {
            "id": project_id,
            "name": project_name or project_id,
            "path": project_path,
        },
        "agents": profiles,
        "teams": list(teams_map.values()),
        "routes": {sender: sorted(targets) for sender, targets in routes.items()},
    }


def _persist_runtime_overlay(overlay: dict[str, Any] | None) -> None:
    if not overlay:
        try:
            os.unlink(_get_runtime_team_path())
        except OSError:
            pass
        return
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(_get_runtime_team_path()), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(overlay, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_path, _get_runtime_team_path())
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_runtime_overlay_from_disk() -> dict[str, Any] | None:
    try:
        with open(_get_runtime_team_path(), "r", encoding="utf-8") as handle:
            overlay = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(overlay, dict) or not overlay.get("active"):
        return None
    return overlay


def _restore_runtime_from_overlay(overlay: dict[str, Any] | None) -> bool:
    if not isinstance(overlay, dict) or not overlay.get("active"):
        return False

    project = overlay.get("project") if isinstance(overlay.get("project"), dict) else {}
    profiles = [
        json.loads(json.dumps(agent))
        for agent in overlay.get("agents", [])
        if isinstance(agent, dict)
    ]
    if not profiles:
        return False

    by_slot = {
        str(profile.get("slot", "")).strip(): profile
        for profile in profiles
        if str(profile.get("slot", "")).strip()
    }
    runtime_specs = runtime_layout.runtime_layout_from_profiles(profiles, known_engines=_KNOWN_ENGINES)
    agent_a_engine = str(by_slot.get("a", {}).get("engine", "codex")).strip() or "codex"
    agent_b_engine = str(by_slot.get("b", {}).get("engine", "claude")).strip() or "claude"
    team_lead_profile = by_slot.get("lead", {})
    restored_overlay = json.loads(json.dumps(overlay))

    with _RUNTIME_LOCK:
        _RUNTIME["pair_mode"] = runtime_layout.runtime_pair_mode_for_layout(runtime_specs, known_engines=_KNOWN_ENGINES) if runtime_specs else runtime_layout.pair_mode_of(agent_a_engine, agent_b_engine)
        _RUNTIME["agent_a_engine"] = agent_a_engine
        _RUNTIME["agent_b_engine"] = agent_b_engine
        _RUNTIME["project_name"] = str(project.get("name", project.get("id", ""))).strip()
        _RUNTIME["project_path"] = str(project.get("path", _ROOT_DIR)).strip() or _ROOT_DIR
        _RUNTIME["agent_profiles"] = profiles
        _RUNTIME["runtime_specs"] = runtime_specs
        _RUNTIME["runtime_overlay"] = restored_overlay
        _RUNTIME["last_start_at"] = overlay.get("generated_at")
        team_lead_enabled = bool(team_lead_profile) and len(runtime_specs) <= 3
        _RUNTIME["team_lead_enabled"] = team_lead_enabled
        _RUNTIME["team_lead_cli_enabled"] = team_lead_enabled
        if team_lead_enabled:
            _RUNTIME["team_lead_engine"] = str(team_lead_profile.get("engine", _RUNTIME.get("team_lead_engine", "codex"))).strip() or "codex"
            scope_file = str(team_lead_profile.get("scope_file", "")).strip()
            if scope_file:
                _RUNTIME["team_lead_scope_file"] = scope_file
    return True


def _current_runtime_overlay() -> dict[str, Any] | None:
    with _RUNTIME_LOCK:
        overlay = _RUNTIME.get("runtime_overlay")
    if overlay:
        return json.loads(json.dumps(overlay))

    overlay = _load_runtime_overlay_from_disk()
    if not overlay:
        return None
    _restore_runtime_from_overlay(overlay)
    return json.loads(json.dumps(overlay))


# ===================================================================
# Runtime overlay response formatters
# ===================================================================

def _runtime_overlay_orgchart_response(overlay: dict[str, Any]) -> dict[str, Any]:
    enriched_agents = []
    for agent in overlay.get("agents", []):
        agent_id = str(agent.get("id", "")).strip()
        if not agent_id:
            continue
        status = agent_connection_status(agent_id)
        online = status not in ("disconnected", "offline")
        activity = _AGENT_ACTIVITIES.get(agent_id)
        reg = _REGISTERED_AGENTS.get(agent_id)
        enriched_agents.append({
            "id": agent_id,
            "name": agent.get("name", agent_id),
            "role": agent.get("role", ""),
            "level": agent.get("level", 99),
            "reports_to": agent.get("reports_to", ""),
            "active": bool(agent.get("active", True)),
            "online": online,
            "auto_start": bool(agent.get("auto_start", False)),
            "status": status,
            "activity": activity.get("description", "") if activity else "",
            "context_pct": reg.get("context_pct") if reg else None,
        })
    return {
        "version": 1,
        "owner": {"id": "user", "name": "Owner", "role": "owner", "status": "online"},
        "agents": enriched_agents,
    }


def _runtime_overlay_team_projects_response(overlay: dict[str, Any]) -> dict[str, Any]:
    teams = []
    for team in overlay.get("teams", []):
        lead = str(team.get("lead", "")).strip()
        members = []
        member_ids = []
        if lead:
            member_ids.append(lead)
        member_ids.extend([str(mid).strip() for mid in team.get("members", []) if str(mid).strip()])
        for member_id in member_ids:
            agent = next((a for a in overlay.get("agents", []) if a.get("id") == member_id), {})
            members.append({
                "id": member_id,
                "name": agent.get("name", member_id),
                "role": agent.get("role", ""),
                "status": agent_connection_status(member_id),
                "active": bool(agent.get("active", False)),
            })
        teams.append({
            "id": team.get("id", ""),
            "name": team.get("name", team.get("id", "")),
            "lead": lead,
            "members": members,
            "scope": team.get("scope", ""),
        })
    project = overlay.get("project", {})
    return {
        "projects": [{
            "id": project.get("id", "runtime-project"),
            "name": project.get("name", "Runtime Project"),
            "path": project.get("path", ""),
            "description": "Runtime overlay",
            "teams": teams,
            "scope_labels": {},
            "created_at": overlay.get("generated_at", ""),
        }]
    }


def _runtime_overlay_board_projects_response(overlay: dict[str, Any]) -> dict[str, Any]:
    runtime_projects = _runtime_overlay_team_projects_response(overlay).get("projects", [])
    projects: list[dict[str, Any]] = []
    for project in runtime_projects:
        teams = []
        team_statuses = []
        for team in project.get("teams", []):
            members = []
            member_statuses = []
            for member in team.get("members", []):
                agent_id = str(member.get("id", "")).strip()
                activity = _AGENT_ACTIVITIES.get(agent_id, {})
                board_status = board_api._agent_board_status(agent_id, _REGISTERED_AGENTS)
                info = {
                    "id": agent_id,
                    "name": member.get("name", agent_id),
                    "role": member.get("role", ""),
                    "status": board_status,
                    "online_since": _REGISTERED_AGENTS.get(agent_id, {}).get("registered_at", ""),
                    "last_seen": _REGISTERED_AGENTS.get(agent_id, {}).get("last_heartbeat_iso", ""),
                    "current_activity": str(activity.get("description") or activity.get("action") or ""),
                    "also_in": [],
                }
                members.append(info)
                member_statuses.append(info["status"])
            team_status = board_api._worst_status(member_statuses) if member_statuses else "green"
            teams.append({
                "id": team.get("id", ""),
                "name": team.get("name", team.get("id", "")),
                "status": team_status,
                "members": members,
            })
            team_statuses.append(team_status)
        project_status = board_api._worst_status(team_statuses) if team_statuses else "green"
        projects.append({
            "id": project.get("id", "runtime-project"),
            "name": project.get("name", "Runtime Project"),
            "status": project_status,
            "created_at": project.get("created_at", ""),
            "teams": teams,
        })
    return {"projects": projects}


def _runtime_overlay_teams_response(overlay: dict[str, Any]) -> dict[str, Any]:
    teams_list = []
    for team in overlay.get("teams", []):
        member_ids = set(team.get("members", []))
        lead = str(team.get("lead", "")).strip()
        if lead:
            member_ids.add(lead)
        online_count = sum(1 for mid in member_ids if agent_connection_status(mid) == "online")
        last_activity = None
        last_activity_ts = ""
        for mid in member_ids:
            act = _AGENT_ACTIVITIES.get(mid)
            if act:
                ts = act.get("timestamp", "")
                if ts > last_activity_ts:
                    last_activity_ts = ts
                    last_activity = act
        teams_list.append({
            "id": team.get("id", ""),
            "name": team.get("name", team.get("id", "")),
            "lead": lead,
            "members": sorted(member_ids),
            "member_count": len(member_ids),
            "online_count": online_count,
            "scope": team.get("scope", ""),
            "active": True,
            "last_activity": last_activity,
        })
    return {"teams": teams_list}


def _runtime_overlay_team_detail(overlay: dict[str, Any], team_id: str) -> dict[str, Any] | None:
    team = next((t for t in overlay.get("teams", []) if t.get("id") == team_id), None)
    if team is None:
        return None
    member_ids = set(team.get("members", []))
    lead = str(team.get("lead", "")).strip()
    if lead:
        member_ids.add(lead)
    enriched_members = []
    for member_id in sorted(member_ids):
        agent = next((a for a in overlay.get("agents", []) if a.get("id") == member_id), {})
        status = agent_connection_status(member_id)
        activity = _AGENT_ACTIVITIES.get(member_id)
        reg = _REGISTERED_AGENTS.get(member_id)
        enriched_members.append({
            "id": member_id,
            "name": agent.get("name", member_id),
            "role": agent.get("role", ""),
            "is_lead": member_id == lead,
            "status": status,
            "activity": activity,
            "context_pct": reg.get("context_pct") if reg else None,
        })
    return {
        "id": team_id,
        "name": team.get("name", team_id),
        "lead": lead,
        "scope": team.get("scope", ""),
        "active": True,
        "members": enriched_members,
    }


def _runtime_overlay_team_context(overlay: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    agent_conf = next((a for a in overlay.get("agents", []) if a.get("id") == agent_id), None)
    if agent_conf is None:
        return None
    my_team = next((t for t in overlay.get("teams", []) if agent_id == t.get("lead") or agent_id in set(t.get("members", []))), None)
    teammates = []
    team_info: dict[str, Any] = {}
    if my_team:
        team_info = {
            "id": my_team.get("id", ""),
            "name": my_team.get("name", ""),
            "lead": my_team.get("lead", ""),
            "scope": my_team.get("scope", ""),
        }
        member_ids = []
        lead = str(my_team.get("lead", "")).strip()
        if lead:
            member_ids.append(lead)
        member_ids.extend([str(mid).strip() for mid in my_team.get("members", []) if str(mid).strip()])
        for member_id in member_ids:
            if member_id == agent_id:
                continue
            teammate_conf = next((a for a in overlay.get("agents", []) if a.get("id") == member_id), {})
            teammates.append({
                "id": member_id,
                "name": teammate_conf.get("name", member_id),
                "role": teammate_conf.get("role", ""),
                "status": agent_connection_status(member_id),
            })
    return {
        "agent": {
            "id": agent_id,
            "name": agent_conf.get("name", agent_id),
            "role": agent_conf.get("role", ""),
            "description": agent_conf.get("description", ""),
            "level": agent_conf.get("level", 99),
            "reports_to": agent_conf.get("reports_to", ""),
            "team": agent_conf.get("team", ""),
            "model": agent_conf.get("model", ""),
            "engine": agent_conf.get("engine", ""),
        },
        "team": team_info,
        "teammates": teammates,
    }


# ===================================================================
# Runtime agents for layout
# ===================================================================

def runtime_agents_for_layout(
    layout: list[dict[str, str]],
    profiles: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    profile_by_id: dict[str, dict[str, Any]] = {}
    for profile in profiles or []:
        agent_id = str(profile.get("id", "")).strip()
        if agent_id:
            profile_by_id[agent_id] = profile
    out: list[dict[str, Any]] = []
    for spec in layout:
        agent_id = spec["id"]
        status = agent_connection_status(agent_id)
        tmux_alive = is_session_alive(agent_id)
        # If tmux session is gone, agent is definitely disconnected
        if not tmux_alive and status != "disconnected":
            status = "disconnected"
        reg = _REGISTERED_AGENTS.get(agent_id, {})
        profile = profile_by_id.get(agent_id, {})
        out.append(
            {
                "slot": profile.get("slot", spec.get("slot", "")),
                "name": str(profile.get("display_name") or profile.get("name") or spec["name"]),
                "id": agent_id,
                "engine": str(profile.get("engine") or spec["engine"]),
                "peer": spec["peer"],
                "tmux_session": _tmux_session_for(agent_id),  # type: ignore[misc]
                "tmux_alive": tmux_alive,
                "running": status != "disconnected",
                "status": status,
                "last_heartbeat": reg.get("last_heartbeat_iso", ""),
                "registered_at": reg.get("registered_at", ""),
                "log_file": _agent_log_path(spec["name"]),  # type: ignore[misc]
                "role": str(profile.get("role") or ""),
                "description": str(profile.get("description") or ""),
                "model": str(profile.get("model") or ""),
                "team": str(profile.get("team") or ""),
                "reports_to": str(profile.get("reports_to") or ""),
                "level": profile.get("level"),
                "phantom": bool(reg.get("phantom", False)),  # AUDIT-7: True if auto-registered but no real bridge_register()
            }
        )
    return out


# ===================================================================
# Wait for agent registration
# ===================================================================

def _wait_for_agent_registration(agent_ids: list[str], timeout_seconds: float) -> bool:
    """V2: Wait for agents to register via POST /register.

    Agents start in tmux, read CLAUDE.md, and POST /register.
    This replaces the old PID-stabilization wait.
    """
    if timeout_seconds <= 0:
        return False
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        registered = all(agent_id in _REGISTERED_AGENTS for agent_id in agent_ids)
        if registered:
            return True
        time.sleep(0.5)
    # Log which agents failed to register
    missing = [aid for aid in agent_ids if aid not in _REGISTERED_AGENTS]
    if missing:
        print(f"[runtime] WARNING: Agents did not register within {timeout_seconds}s: {missing}")
    return False


# ===================================================================
# Clear runtime configuration
# ===================================================================

def _clear_runtime_configuration(
    *,
    clear_presence: bool = True,
    team_lead_reason: str = "runtime_reset",
) -> None:
    """Reset configured runtime state back to an unconfigured baseline."""
    try:
        _persist_runtime_overlay(None)
    except Exception as exc:
        print(f"[ERROR] _persist_runtime_overlay(None) failed: {exc}")
    try:
        reset_team_lead_state(team_lead_reason)
    except Exception as exc:
        print(f"[ERROR] reset_team_lead_state failed: {exc}")
    if clear_presence:
        with _AGENT_STATE_LOCK:
            _AGENT_LAST_SEEN.clear()
            _AGENT_BUSY.clear()
            _REGISTERED_AGENTS.clear()
            _PREV_AGENT_STATUS.clear()
    with _RUNTIME_LOCK:
        _RUNTIME["project_name"] = ""
        _RUNTIME["agent_profiles"] = []
        _RUNTIME["runtime_specs"] = []
        _RUNTIME["runtime_overlay"] = None
        _RUNTIME["last_start_at"] = None


# ===================================================================
# Runtime snapshot
# ===================================================================

def runtime_snapshot() -> dict[str, Any]:
    _current_runtime_overlay()
    with _RUNTIME_LOCK:
        runtime_state = dict(_RUNTIME)
        project_name = str(runtime_state.get("project_name", "")).strip()
        project_path = str(runtime_state.get("project_path", _ROOT_DIR))
        team_lead_cli_enabled = bool(runtime_state.get("team_lead_cli_enabled", True))
        team_lead_engine = str(runtime_state.get("team_lead_engine", "codex"))
        team_lead_scope_file = str(runtime_state.get("team_lead_scope_file", ""))
        agent_profiles = json.loads(json.dumps(runtime_state.get("agent_profiles", [])))
        runtime_specs = json.loads(json.dumps(runtime_state.get("runtime_specs", [])))
        runtime_overlay = runtime_state.get("runtime_overlay")
        last_start_at = runtime_state.get("last_start_at")
        pair_mode = str(runtime_state.get("pair_mode", "")).strip()
        configured = bool(project_name or agent_profiles or runtime_overlay or last_start_at or runtime_specs)
        payload = {
            "pair_mode": pair_mode,
            "agent_a_engine": str(runtime_state.get("agent_a_engine", "codex")),
            "agent_b_engine": str(runtime_state.get("agent_b_engine", "claude")),
            "project_name": project_name,
            "project_path": project_path,
            "allow_peer_auto": bool(runtime_state.get("allow_peer_auto", False)),
            "peer_auto_require_flag": bool(runtime_state.get("peer_auto_require_flag", True)),
            "max_peer_hops": int(runtime_state.get("max_peer_hops", 20)),
            "max_turns": int(runtime_state.get("max_turns", 0)),
            "process_all": bool(runtime_state.get("process_all", False)),
            "keep_history": bool(runtime_state.get("keep_history", False)),
            "timeout": int(runtime_state.get("timeout", 90)),
            "team_lead_enabled": bool(runtime_state.get("team_lead_enabled", True)),
            "team_lead_max_peer_messages": int(runtime_state.get("team_lead_max_peer_messages", 40)),
            "team_lead_cli_enabled": team_lead_cli_enabled,
            "team_lead_engine": team_lead_engine,
            "team_lead_scope_file": team_lead_scope_file,
            "agent_profiles": agent_profiles,
            "runtime_specs": runtime_specs,
            "last_start_at": last_start_at,
            "configured": configured,
        }

    layout = runtime_layout.runtime_layout_from_state(
        runtime_state,
        known_engines=_KNOWN_ENGINES,
        available_engines=runtime_layout.detect_available_engines(_KNOWN_ENGINES),
        team_lead_id=_TEAM_LEAD_ID,
    )
    if not payload["pair_mode"]:
        payload["pair_mode"] = runtime_layout.runtime_pair_mode_for_layout(layout, known_engines=_KNOWN_ENGINES)
    agents = runtime_agents_for_layout(layout, agent_profiles)
    payload["agents"] = agents
    payload["agent_ids"] = [a["id"] for a in agents]
    payload["running_count"] = sum(1 for a in agents if a["running"])
    payload["agents_total"] = len(agents)
    payload["available_engines"] = sorted(runtime_layout.detect_available_engines(_KNOWN_ENGINES) - {"echo"})
    with _TEAM_LEAD_LOCK:
        payload["team_lead_state"] = dict(_TEAM_LEAD_STATE)
    return payload
