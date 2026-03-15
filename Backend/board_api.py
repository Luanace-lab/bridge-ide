"""
board_api.py — Team Board API (Project → Team → Agent Management)

V3 Fassade: reads/writes team.json as Single Source of Truth.
Falls back to projects.json if team.json backend not initialized.
Endpoints are mounted under /board/ prefix in server.py.

Data model:
  Project (1) → (n) Team (n) ↔ (m) Agent
  Agent metadata comes from team.json agents[] + REGISTERED_AGENTS at runtime.

Persistence: team.json with atomic write (via server.py injection).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_FILE = os.path.join(BASE_DIR, "projects.json")
_FILE_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# V3 team.json backend (injected by server.py at startup)
# ---------------------------------------------------------------------------

_TEAM_CONFIG: dict[str, Any] | None = None       # reference to server.py's TEAM_CONFIG
_TEAM_LOCK: threading.Lock | None = None          # reference to TEAM_CONFIG_LOCK
_TEAM_WRITE_FN: Callable[[], None] | None = None  # _atomic_write_team_json


def init_team_backend(
    config: dict[str, Any],
    lock: threading.Lock,
    write_fn: Callable[[], None],
) -> None:
    """Initialize team.json backend. Called by server.py at startup.

    Args:
        config: Reference to TEAM_CONFIG dict (shared, mutable)
        lock: Reference to TEAM_CONFIG_LOCK
        write_fn: _atomic_write_team_json() — persists TEAM_CONFIG to disk
    """
    global _TEAM_CONFIG, _TEAM_LOCK, _TEAM_WRITE_FN
    _TEAM_CONFIG = config
    _TEAM_LOCK = lock
    _TEAM_WRITE_FN = write_fn


def _use_team_backend() -> bool:
    """Check if team.json backend is initialized and available."""
    return _TEAM_CONFIG is not None and _TEAM_LOCK is not None and _TEAM_WRITE_FN is not None


def _team_config_to_board_data() -> dict:
    """Transform team.json v3 to board_api data format.

    team.json:
      projects[].team_ids → reference to teams[]
      teams[] → top-level with lead + members
      agents[] → id, name, role

    board format:
      agent_names: {id: name}
      agent_roles: {id: role}
      projects[].teams[].members: flat list (lead + members merged)
    """
    assert _TEAM_CONFIG is not None
    agents = _TEAM_CONFIG.get("agents", [])
    agent_names = {a.get("id", ""): a.get("name", a.get("id", "")) for a in agents}
    agent_roles = {a.get("id", ""): a.get("role", "") for a in agents}

    teams_map = {t.get("id", ""): t for t in _TEAM_CONFIG.get("teams", [])}

    # Synthesize management team from level-1 agents (Kernteam)
    mgmt_members = [a.get("id", "") for a in agents if a.get("level", 99) <= 1 and a.get("id", "")]
    mgmt_team = {"id": "kernteam", "name": "Kernteam", "members": mgmt_members} if mgmt_members else None

    projects = []
    for proj in _TEAM_CONFIG.get("projects", []):
        teams = []
        # Inject management team first (left panel in frontend)
        if mgmt_team:
            teams.append(mgmt_team)
        for tid in proj.get("team_ids", []):
            t = teams_map.get(tid)
            if t:
                # Merge lead into members for board display
                members = list(t.get("members", []))
                lead = t.get("lead", "")
                if lead and lead not in members:
                    members.insert(0, lead)
                teams.append({
                    "id": t["id"],
                    "name": t.get("name", t["id"]),
                    "members": members,
                })
        projects.append({
            "id": proj["id"],
            "name": proj.get("name", proj["id"]),
            "created_at": proj.get("created_at", ""),
            "teams": teams,
        })

    return {
        "agent_names": agent_names,
        "agent_roles": agent_roles,
        "projects": projects,
    }

# Slug validation: lowercase alphanumeric + hyphens, 1-64 chars
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _read_projects_file() -> dict:
    """Read project data. Uses team.json (v3) if initialized, else projects.json."""
    if _use_team_backend():
        return _team_config_to_board_data()
    try:
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "projects" not in data:
            return {"projects": []}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"projects": []}


def _write_projects_file(data: dict) -> None:
    """Persist changes. Uses team.json backend if initialized, else projects.json."""
    if _use_team_backend():
        # V3: team.json is already modified in-place via _TEAM_CONFIG reference.
        # Just persist to disk.
        assert _TEAM_WRITE_FN is not None
        _TEAM_WRITE_FN()
        return
    # Legacy: atomic write to projects.json
    fd, tmp_path = tempfile.mkstemp(dir=BASE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, PROJECTS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _find_project(data: dict, project_id: str) -> dict | None:
    """Find project by id."""
    for p in data["projects"]:
        if p["id"] == project_id:
            return p
    return None


def _find_team(project: dict, team_id: str) -> dict | None:
    """Find team by id within a project."""
    for t in project.get("teams", []):
        if t["id"] == team_id:
            return t
    return None


def _validate_slug(slug: str) -> bool:
    """Validate slug format."""
    return bool(_SLUG_RE.match(slug))


# ---------------------------------------------------------------------------
# Status enrichment
# ---------------------------------------------------------------------------

def _agent_board_status(agent_id: str, registered_agents: dict) -> str:
    """Derive traffic-light status from heartbeat age.

    green:  heartbeat < 30s
    yellow: heartbeat 30-120s
    red:    heartbeat > 120s or not registered
    """
    reg = registered_agents.get(agent_id)
    if reg is None:
        return "red"
    last_hb = reg.get("last_heartbeat", 0)
    age = time.time() - last_hb
    if age < 30:
        return "green"
    if age < 120:
        return "yellow"
    return "red"


def _worst_status(statuses: list[str]) -> str:
    """Return worst status from list (red > yellow > green)."""
    if "red" in statuses:
        return "red"
    if "yellow" in statuses:
        return "yellow"
    return "green"


def _agent_info(
    agent_id: str,
    registered_agents: dict,
    agent_names: dict | None = None,
    agent_roles: dict | None = None,
    agent_activities: dict | None = None,
) -> dict:
    """Build agent info dict from registration data + optional name/role mappings."""
    reg = registered_agents.get(agent_id, {})
    # Name: projects.json mapping > registration > agent_id
    name = agent_id
    if agent_names and agent_id in agent_names:
        name = agent_names[agent_id]
    elif reg.get("name"):
        name = reg["name"]
    # Role: registration (runtime) > projects.json mapping (fallback)
    role = reg.get("role", "")
    if not role and agent_roles and agent_id in agent_roles:
        role = agent_roles[agent_id]
    activity = ""
    if agent_activities and agent_id in agent_activities:
        act = agent_activities.get(agent_id, {})
        if isinstance(act, dict):
            activity = str(act.get("description") or act.get("action") or "")
    return {
        "id": agent_id,
        "name": name,
        "role": role,
        "status": _agent_board_status(agent_id, registered_agents),
        "online_since": reg.get("registered_at", ""),
        "last_seen": reg.get("last_heartbeat_iso", ""),
        "current_activity": activity,
    }


def _compute_also_in(agent_id: str, current_project_id: str, data: dict) -> list[str]:
    """Find other project names where this agent is a member."""
    result = []
    for p in data["projects"]:
        if p["id"] == current_project_id:
            continue
        for t in p.get("teams", []):
            if agent_id in t.get("members", []):
                result.append(p["name"])
                break
    return result


# ---------------------------------------------------------------------------
# API Functions (called by server.py route handlers)
# ---------------------------------------------------------------------------

def get_all_projects(registered_agents: dict, agent_activities: dict | None = None) -> dict:
    """GET /board/projects — all projects with enriched runtime data."""
    if _use_team_backend():
        assert _TEAM_LOCK is not None
        with _TEAM_LOCK:
            data = _read_projects_file()
    else:
        with _FILE_LOCK:
            data = _read_projects_file()

    agent_names = data.get("agent_names", {})
    agent_roles = data.get("agent_roles", {})
    enriched = []
    for p in data["projects"]:
        teams_enriched = []
        team_statuses = []
        for t in p.get("teams", []):
            members_enriched = []
            member_statuses = []
            for mid in t.get("members", []):
                info = _agent_info(mid, registered_agents, agent_names, agent_roles, agent_activities)
                info["also_in"] = _compute_also_in(mid, p["id"], data)
                members_enriched.append(info)
                member_statuses.append(info["status"])
            team_status = _worst_status(member_statuses) if member_statuses else "green"
            teams_enriched.append({
                "id": t["id"],
                "name": t["name"],
                "status": team_status,
                "members": members_enriched,
            })
            team_statuses.append(team_status)
        project_status = _worst_status(team_statuses) if team_statuses else "green"
        enriched.append({
            "id": p["id"],
            "name": p["name"],
            "status": project_status,
            "created_at": p.get("created_at", ""),
            "teams": teams_enriched,
        })

    return {"projects": enriched}


def get_project(
    project_id: str,
    registered_agents: dict,
    agent_activities: dict | None = None,
) -> dict | None:
    """GET /board/projects/{id} — single project with enriched data."""
    result = get_all_projects(registered_agents, agent_activities)
    for p in result["projects"]:
        if p["id"] == project_id:
            return {"project": p}
    return None


def create_project(project_id: str, name: str) -> dict:
    """POST /board/projects — create new project.

    Returns: {"ok": True, "project": {...}}
    Raises: ValueError on invalid input or duplicate id.
    """
    if not _validate_slug(project_id):
        raise ValueError(f"invalid project id (must match {_SLUG_RE.pattern}): {project_id!r}")
    if not name or not name.strip():
        raise ValueError("name is required")

    if _use_team_backend():
        assert _TEAM_CONFIG is not None and _TEAM_LOCK is not None
        with _TEAM_LOCK:
            for p in _TEAM_CONFIG.get("projects", []):
                if p.get("id") == project_id:
                    raise ValueError(f"project already exists: {project_id!r}")
            project_entry = {
                "id": project_id,
                "name": name.strip(),
                "team_ids": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _TEAM_CONFIG.setdefault("projects", []).append(project_entry)
            _write_projects_file({})  # persists team.json
        # Return board-format project (with inline teams)
        return {"ok": True, "project": {
            "id": project_id, "name": name.strip(),
            "created_at": project_entry["created_at"], "teams": [],
        }}

    with _FILE_LOCK:
        data = _read_projects_file()
        if _find_project(data, project_id):
            raise ValueError(f"project already exists: {project_id!r}")
        project = {
            "id": project_id,
            "name": name.strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "teams": [],
        }
        data["projects"].append(project)
        _write_projects_file(data)

    return {"ok": True, "project": project}


def update_project(project_id: str, name: str) -> dict:
    """PUT /board/projects/{id} — rename project.

    Returns: {"ok": True, "project": {...}}
    Raises: ValueError if not found.
    """
    if not name or not name.strip():
        raise ValueError("name is required")

    if _use_team_backend():
        assert _TEAM_CONFIG is not None and _TEAM_LOCK is not None
        with _TEAM_LOCK:
            for p in _TEAM_CONFIG.get("projects", []):
                if p.get("id") == project_id:
                    p["name"] = name.strip()
                    _write_projects_file({})
                    return {"ok": True, "project": {"id": project_id, "name": name.strip()}}
            raise ValueError(f"project not found: {project_id!r}")

    with _FILE_LOCK:
        data = _read_projects_file()
        project = _find_project(data, project_id)
        if not project:
            raise ValueError(f"project not found: {project_id!r}")
        project["name"] = name.strip()
        _write_projects_file(data)

    return {"ok": True, "project": project}


def delete_project(project_id: str) -> dict:
    """DELETE /board/projects/{id} — delete project.

    Returns: {"ok": True, "deleted": project_id}
    Raises: ValueError if not found.
    """
    if _use_team_backend():
        assert _TEAM_CONFIG is not None and _TEAM_LOCK is not None
        with _TEAM_LOCK:
            projects = _TEAM_CONFIG.get("projects", [])
            original_len = len(projects)
            _TEAM_CONFIG["projects"] = [p for p in projects if p.get("id") != project_id]
            if len(_TEAM_CONFIG["projects"]) == original_len:
                raise ValueError(f"project not found: {project_id!r}")
            _write_projects_file({})
        return {"ok": True, "deleted": project_id}

    with _FILE_LOCK:
        data = _read_projects_file()
        original_len = len(data["projects"])
        data["projects"] = [p for p in data["projects"] if p["id"] != project_id]
        if len(data["projects"]) == original_len:
            raise ValueError(f"project not found: {project_id!r}")
        _write_projects_file(data)

    return {"ok": True, "deleted": project_id}


def add_team(project_id: str, team_id: str, name: str) -> dict:
    """POST /board/projects/{id}/teams — add team to project.

    Returns: {"ok": True, "team": {...}}
    Raises: ValueError on invalid input or duplicate.
    """
    if not _validate_slug(team_id):
        raise ValueError(f"invalid team id: {team_id!r}")
    if not name or not name.strip():
        raise ValueError("name is required")

    if _use_team_backend():
        assert _TEAM_CONFIG is not None and _TEAM_LOCK is not None
        with _TEAM_LOCK:
            # Find project
            proj = None
            for p in _TEAM_CONFIG.get("projects", []):
                if p.get("id") == project_id:
                    proj = p
                    break
            if not proj:
                raise ValueError(f"project not found: {project_id!r}")
            # Check if team already exists
            if team_id in proj.get("team_ids", []):
                raise ValueError(f"team already exists: {team_id!r}")
            # Create team in top-level teams[] if not exists
            existing = None
            for t in _TEAM_CONFIG.get("teams", []):
                if t.get("id") == team_id:
                    existing = t
                    break
            if not existing:
                new_team = {"id": team_id, "name": name.strip(), "lead": "", "members": [], "scope": ""}
                _TEAM_CONFIG.setdefault("teams", []).append(new_team)
            # Add team_id to project
            proj.setdefault("team_ids", []).append(team_id)
            _write_projects_file({})
        return {"ok": True, "team": {"id": team_id, "name": name.strip(), "members": []}}

    with _FILE_LOCK:
        data = _read_projects_file()
        project = _find_project(data, project_id)
        if not project:
            raise ValueError(f"project not found: {project_id!r}")
        if _find_team(project, team_id):
            raise ValueError(f"team already exists: {team_id!r}")
        team = {"id": team_id, "name": name.strip(), "members": []}
        project.setdefault("teams", []).append(team)
        _write_projects_file(data)

    return {"ok": True, "team": team}


def update_team(project_id: str, team_id: str, name: str) -> dict:
    """PUT /board/projects/{id}/teams/{tid} — rename team.

    Returns: {"ok": True, "team": {...}}
    Raises: ValueError if not found.
    """
    if not name or not name.strip():
        raise ValueError("name is required")

    if _use_team_backend():
        assert _TEAM_CONFIG is not None and _TEAM_LOCK is not None
        with _TEAM_LOCK:
            # Verify project has this team
            proj = None
            for p in _TEAM_CONFIG.get("projects", []):
                if p.get("id") == project_id:
                    proj = p
                    break
            if not proj:
                raise ValueError(f"project not found: {project_id!r}")
            if team_id not in proj.get("team_ids", []):
                raise ValueError(f"team not found: {team_id!r}")
            # Update team name in top-level teams[]
            for t in _TEAM_CONFIG.get("teams", []):
                if t.get("id") == team_id:
                    t["name"] = name.strip()
                    _write_projects_file({})
                    return {"ok": True, "team": {"id": team_id, "name": name.strip()}}
            raise ValueError(f"team not found: {team_id!r}")

    with _FILE_LOCK:
        data = _read_projects_file()
        project = _find_project(data, project_id)
        if not project:
            raise ValueError(f"project not found: {project_id!r}")
        team = _find_team(project, team_id)
        if not team:
            raise ValueError(f"team not found: {team_id!r}")
        team["name"] = name.strip()
        _write_projects_file(data)

    return {"ok": True, "team": team}


def delete_team(project_id: str, team_id: str) -> dict:
    """DELETE /board/projects/{id}/teams/{tid} — remove team from project.

    In team.json mode: removes team_id from project's team_ids.
    The team entry in teams[] is preserved (may be used by other projects).

    Returns: {"ok": True, "deleted": team_id}
    Raises: ValueError if not found.
    """
    if _use_team_backend():
        assert _TEAM_CONFIG is not None and _TEAM_LOCK is not None
        with _TEAM_LOCK:
            for p in _TEAM_CONFIG.get("projects", []):
                if p.get("id") == project_id:
                    tids = p.get("team_ids", [])
                    if team_id not in tids:
                        raise ValueError(f"team not found: {team_id!r}")
                    tids.remove(team_id)
                    _write_projects_file({})
                    return {"ok": True, "deleted": team_id}
            raise ValueError(f"project not found: {project_id!r}")

    with _FILE_LOCK:
        data = _read_projects_file()
        project = _find_project(data, project_id)
        if not project:
            raise ValueError(f"project not found: {project_id!r}")
        original_len = len(project.get("teams", []))
        project["teams"] = [t for t in project.get("teams", []) if t["id"] != team_id]
        if len(project["teams"]) == original_len:
            raise ValueError(f"team not found: {team_id!r}")
        _write_projects_file(data)

    return {"ok": True, "deleted": team_id}


def add_member(project_id: str, team_id: str, agent_id: str) -> dict:
    """POST /board/projects/{id}/teams/{tid}/members — add agent to team.

    Returns: {"ok": True, "agent_id": ..., "team_id": ...}
    Raises: ValueError if not found or already member.
    """
    if not agent_id or not agent_id.strip():
        raise ValueError("agent_id is required")
    agent_id = agent_id.strip()

    if _use_team_backend():
        assert _TEAM_CONFIG is not None and _TEAM_LOCK is not None
        with _TEAM_LOCK:
            # Verify project has this team
            proj = None
            for p in _TEAM_CONFIG.get("projects", []):
                if p.get("id") == project_id:
                    proj = p
                    break
            if not proj:
                raise ValueError(f"project not found: {project_id!r}")
            if team_id not in proj.get("team_ids", []):
                raise ValueError(f"team not found: {team_id!r}")
            # Find team in top-level teams[]
            for t in _TEAM_CONFIG.get("teams", []):
                if t.get("id") == team_id:
                    if agent_id in t.get("members", []):
                        raise ValueError(f"agent already in team: {agent_id!r}")
                    t.setdefault("members", []).append(agent_id)
                    _write_projects_file({})
                    return {"ok": True, "agent_id": agent_id, "team_id": team_id}
            raise ValueError(f"team not found: {team_id!r}")

    with _FILE_LOCK:
        data = _read_projects_file()
        project = _find_project(data, project_id)
        if not project:
            raise ValueError(f"project not found: {project_id!r}")
        team = _find_team(project, team_id)
        if not team:
            raise ValueError(f"team not found: {team_id!r}")
        if agent_id in team.get("members", []):
            raise ValueError(f"agent already in team: {agent_id!r}")
        team.setdefault("members", []).append(agent_id)
        _write_projects_file(data)

    return {"ok": True, "agent_id": agent_id, "team_id": team_id}


def remove_member(project_id: str, team_id: str, agent_id: str) -> dict:
    """DELETE /board/projects/{id}/teams/{tid}/members/{aid} — remove agent from team.

    Returns: {"ok": True, "removed": agent_id}
    Raises: ValueError if not found.
    """
    if _use_team_backend():
        assert _TEAM_CONFIG is not None and _TEAM_LOCK is not None
        with _TEAM_LOCK:
            # Verify project has this team
            proj = None
            for p in _TEAM_CONFIG.get("projects", []):
                if p.get("id") == project_id:
                    proj = p
                    break
            if not proj:
                raise ValueError(f"project not found: {project_id!r}")
            if team_id not in proj.get("team_ids", []):
                raise ValueError(f"team not found: {team_id!r}")
            for t in _TEAM_CONFIG.get("teams", []):
                if t.get("id") == team_id:
                    if agent_id not in t.get("members", []):
                        raise ValueError(f"agent not in team: {agent_id!r}")
                    t["members"].remove(agent_id)
                    _write_projects_file({})
                    return {"ok": True, "removed": agent_id}
            raise ValueError(f"team not found: {team_id!r}")

    with _FILE_LOCK:
        data = _read_projects_file()
        project = _find_project(data, project_id)
        if not project:
            raise ValueError(f"project not found: {project_id!r}")
        team = _find_team(project, team_id)
        if not team:
            raise ValueError(f"team not found: {team_id!r}")
        if agent_id not in team.get("members", []):
            raise ValueError(f"agent not in team: {agent_id!r}")
        team["members"].remove(agent_id)
        _write_projects_file(data)

    return {"ok": True, "removed": agent_id}


def get_all_agents(registered_agents: dict, agent_activities: dict | None = None) -> dict:
    """GET /board/agents — all agents with project memberships."""
    if _use_team_backend():
        assert _TEAM_LOCK is not None
        with _TEAM_LOCK:
            data = _read_projects_file()
    else:
        with _FILE_LOCK:
            data = _read_projects_file()

    agent_names = data.get("agent_names", {})
    agent_roles = data.get("agent_roles", {})

    # Collect all agent_ids from projects.json
    agent_ids: set[str] = set()
    for p in data["projects"]:
        for t in p.get("teams", []):
            for mid in t.get("members", []):
                agent_ids.add(mid)

    # Also include all registered agents (may not be in any project)
    for aid in registered_agents:
        agent_ids.add(aid)

    agents = []
    for aid in sorted(agent_ids):
        info = _agent_info(aid, registered_agents, agent_names, agent_roles, agent_activities)
        # Find all projects and teams for this agent
        projects = []
        for p in data["projects"]:
            teams_in = []
            for t in p.get("teams", []):
                if aid in t.get("members", []):
                    teams_in.append(t["name"])
            if teams_in:
                projects.append({
                    "id": p["id"],
                    "name": p["name"],
                    "teams": teams_in,
                })
        info["projects"] = projects
        agents.append(info)

    return {"agents": agents}


def get_agent_projects(
    agent_id: str,
    registered_agents: dict,
    agent_activities: dict | None = None,
) -> dict | None:
    """GET /board/agents/{id}/projects — all projects/teams for one agent."""
    if _use_team_backend():
        assert _TEAM_LOCK is not None
        with _TEAM_LOCK:
            data = _read_projects_file()
    else:
        with _FILE_LOCK:
            data = _read_projects_file()

    agent_names = data.get("agent_names", {})
    agent_roles = data.get("agent_roles", {})
    info = _agent_info(agent_id, registered_agents, agent_names, agent_roles, agent_activities)
    projects = []
    for p in data["projects"]:
        teams_in = []
        for t in p.get("teams", []):
            if agent_id in t.get("members", []):
                teams_in.append(t["name"])
        if teams_in:
            projects.append({
                "id": p["id"],
                "name": p["name"],
                "teams": teams_in,
            })
    info["projects"] = projects

    return {"agent": info}
