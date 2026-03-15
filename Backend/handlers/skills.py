"""Skills/proposals helpers extracted from server.py (Slice 10).

This module owns:
- skill proposal persistence
- filesystem skill discovery
- full skill lookup and CLAUDE.md/AGENTS.md section generation
- skill suggestion and auto-provisioning

Anti-circular-import strategy:
  Shared team state is injected via init().
  This module NEVER imports from server.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable


_get_team_config: Callable[[], dict[str, Any] | None] | None = None
_atomic_write_team_json: Callable[[], None] | None = None
_ws_broadcast_fn: Callable[[str, dict[str, Any]], None] | None = None
_deploy_agent_skills_fn: Callable[[str, str], str | None] | None = None
_TEAM_CONFIG_LOCK: Any = None

_ROOT_DIR = str(Path(__file__).resolve().parents[2])

_PROPOSALS_FILE = os.path.join(_ROOT_DIR, "skill_proposals.json")
_PROPOSALS_DIR = os.path.join(_ROOT_DIR, "shared_tools", "proposals")
_PROPOSALS_LOCK = threading.Lock()
_SKILL_PROPOSALS: list[dict[str, Any]] = []

SKILLS_DIR = os.environ.get(
    "BRIDGE_SKILLS_DIR",
    os.path.join(os.environ.get("HOME", "/tmp"), ".claude", "skills"),
)
_skills_cache: dict[str, Any] = {"mtime": 0.0, "skills": []}
_skills_cache_lock = threading.Lock()

_yaml: Any = None
try:
    import yaml as _yaml  # type: ignore[no-redef]
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# Skills auto-matching rules: keyword -> suggested skills
_SKILL_MATCH_RULES: list[tuple[list[str], list[str]]] = [
    (["backend", "server", "api", "mcp", "websocket"], ["server-architecture", "mcp-tool-development"]),
    (["frontend", "ui", "css", "design", "theme"], ["bridge-ui-designer", "frontend-design"]),
    (["integration", "e2e", "external", "browser"], ["stealth-browser", "api-integration"]),
    (["strateg", "research", "marketing", "vision"], ["deep-research", "competitors-analysis"]),
    (["koordinat", "orchestr", "onboard", "delegat"], ["superpowers-dispatching-parallel-agents"]),
    (["debug", "test", "qa", "quality"], ["superpowers-systematic-debugging", "qa-expert"]),
    (["architect", "review", "standard", "code-qualit"], ["superpowers-requesting-code-review"]),
    (["bug.bounty", "exploit", "recon", "pentest", "hack"], ["security-scanner", "stealth-browser"]),
]


def init(
    *,
    team_config_getter: Callable[[], dict[str, Any] | None],
    team_config_lock: Any,
    atomic_write_team_json_fn: Callable[[], None],
    ws_broadcast_fn: Callable[[str, dict[str, Any]], None],
    deploy_agent_skills_fn: Callable[[str, str], str | None],
) -> None:
    """Bind shared team state callbacks."""
    global _get_team_config, _TEAM_CONFIG_LOCK, _atomic_write_team_json, _ws_broadcast_fn, _deploy_agent_skills_fn
    _get_team_config = team_config_getter
    _TEAM_CONFIG_LOCK = team_config_lock
    _atomic_write_team_json = atomic_write_team_json_fn
    _ws_broadcast_fn = ws_broadcast_fn
    _deploy_agent_skills_fn = deploy_agent_skills_fn


def _team_config() -> dict[str, Any] | None:
    if _get_team_config is None:
        raise RuntimeError("handlers.skills.init() not called: team_config_getter missing")
    return _get_team_config()


def _team_config_lock() -> Any:
    if _TEAM_CONFIG_LOCK is None:
        raise RuntimeError("handlers.skills.init() not called: team_config_lock missing")
    return _TEAM_CONFIG_LOCK


def _write_team_json() -> None:
    if _atomic_write_team_json is None:
        raise RuntimeError("handlers.skills.init() not called: atomic_write_team_json_fn missing")
    _atomic_write_team_json()


def _ws_broadcast(event: str, payload: dict[str, Any]) -> None:
    if _ws_broadcast_fn is None:
        raise RuntimeError("handlers.skills.init() not called: ws_broadcast_fn missing")
    _ws_broadcast_fn(event, payload)


def _deploy_agent_skills(agent_id: str, base_config_dir: str) -> str | None:
    if _deploy_agent_skills_fn is None:
        raise RuntimeError("handlers.skills.init() not called: deploy_agent_skills_fn missing")
    return _deploy_agent_skills_fn(agent_id, base_config_dir)


def _load_proposals() -> None:
    """Load proposals from disk while preserving the shared list object."""
    _SKILL_PROPOSALS.clear()
    if not os.path.exists(_PROPOSALS_FILE):
        return
    try:
        with open(_PROPOSALS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return
    if isinstance(data, list):
        _SKILL_PROPOSALS.extend(item for item in data if isinstance(item, dict))


def _save_proposals() -> None:
    """Persist proposals to disk (must hold _PROPOSALS_LOCK)."""
    try:
        tmp = _PROPOSALS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_SKILL_PROPOSALS, handle, indent=2, ensure_ascii=False)
        os.replace(tmp, _PROPOSALS_FILE)
    except OSError as exc:
        print(f"[proposals] Save failed: {exc}")


def _parse_skill_frontmatter(skill_md_path: str, include_body: bool = False) -> dict[str, str]:
    """Parse YAML frontmatter from a SKILL.md file."""
    try:
        with open(skill_md_path, encoding="utf-8") as handle:
            content = handle.read() if include_body else handle.read(4096)
    except OSError:
        return {}
    if not content.startswith("---"):
        return {"body": content.strip()} if include_body else {}
    end = content.find("---", 3)
    if end == -1:
        return {"body": content.strip()} if include_body else {}
    raw = content[3:end].strip()
    result: dict[str, str] = {}
    if _HAS_YAML:
        try:
            data = _yaml.safe_load(raw)
            if isinstance(data, dict):
                result = {k: str(v) for k, v in data.items() if isinstance(v, str)}
        except Exception:
            pass
    if not result:
        for line in raw.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip()] = value.strip()
    if include_body:
        result["body"] = content[end + 3:].strip()
    return result


def _scan_skills() -> list[dict[str, str]]:
    """Scan the skills directory and cache summaries."""
    if not os.path.isdir(SKILLS_DIR):
        return []
    try:
        dir_mtime = os.stat(SKILLS_DIR).st_mtime
    except OSError:
        return []
    with _skills_cache_lock:
        if _skills_cache["mtime"] == dir_mtime and _skills_cache["skills"]:
            return _skills_cache["skills"]
    skills: list[dict[str, str]] = []
    try:
        entries = sorted(os.listdir(SKILLS_DIR))
    except OSError:
        return []
    for entry in entries:
        entry_path = os.path.join(SKILLS_DIR, entry)
        if not os.path.isdir(entry_path):
            continue
        skill_md = os.path.join(entry_path, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        frontmatter = _parse_skill_frontmatter(skill_md)
        skills.append(
            {
                "id": entry,
                "name": frontmatter.get("name", entry),
                "description": frontmatter.get("description", ""),
                "allowed_tools": frontmatter.get("allowed-tools", ""),
                "path": entry_path,
            }
        )
    with _skills_cache_lock:
        _skills_cache["mtime"] = dir_mtime
        _skills_cache["skills"] = skills
    return skills


def _get_skill_full(skill_id: str) -> dict[str, str] | None:
    """Get full skill content including markdown body."""
    skill_md = os.path.join(SKILLS_DIR, skill_id, "SKILL.md")
    if not os.path.isfile(skill_md):
        return None
    frontmatter = _parse_skill_frontmatter(skill_md, include_body=True)
    frontmatter["id"] = skill_id
    return frontmatter


def _generate_skills_section(agent_id: str) -> str:
    """Generate the embedded skills section for an agent instruction file."""
    team = _team_config()
    if team is None:
        return ""
    agent_entry = None
    for agent in team.get("agents", []):
        if agent.get("id") == agent_id:
            agent_entry = agent
            break
    if agent_entry is None:
        return ""
    assigned = set(agent_entry.get("skills", []))
    if not assigned:
        return ""

    all_skills = _scan_skills()
    if not all_skills:
        return ""

    lines = ["## Available Skills", ""]
    lines.append("| Skill | Description | Status |")
    lines.append("|-------|-------------|--------|")

    for skill in all_skills:
        status = "ACTIVE" if skill["id"] in assigned else "available"
        lines.append(f"| {skill['name']} | {skill['description'][:80]} | {status} |")

    lines.append("")
    for skill_id in sorted(assigned):
        full = _get_skill_full(skill_id)
        if full and full.get("body"):
            lines.append(f"### Skill: {full.get('name', skill_id)}")
            lines.append("")
            lines.append(full["body"])
            lines.append("")

    return "\n".join(lines)


def _get_role_templates() -> dict[str, list[str]]:
    """Load role_templates from team.json."""
    team = _team_config()
    if team is None:
        return {}
    return team.get("role_templates", {})


def _suggest_skills_for_agent(agent: dict[str, Any]) -> list[str]:
    """Suggest skills based on role_templates first, then keyword fallback."""
    available = {skill["id"] for skill in _scan_skills()}
    suggested: list[str] = []
    if "bridge-agent-core" in available:
        suggested.append("bridge-agent-core")

    role_templates = _get_role_templates()
    if role_templates:
        agent_role = (agent.get("role", "") + " " + agent.get("description", "")).lower()
        for role_key, skill_ids in role_templates.items():
            if role_key.lower() in agent_role:
                for skill_id in skill_ids:
                    if isinstance(skill_id, str) and skill_id in available and skill_id not in suggested:
                        suggested.append(skill_id)
        if len(suggested) > 1:
            return suggested

    text = (agent.get("role", "") + " " + agent.get("description", "")).lower()
    for keywords, skill_ids in _SKILL_MATCH_RULES:
        for keyword in keywords:
            if keyword in text:
                for skill_id in skill_ids:
                    if skill_id in available and skill_id not in suggested:
                        suggested.append(skill_id)
                break
    return suggested


def _auto_provision_skills(agent_id: str) -> list[str] | None:
    """Auto-assign suggested skills to an agent with an empty skills[] list."""
    team = _team_config()
    if team is None:
        return None
    with _team_config_lock():
        agents = team.get("agents", [])
        agent_entry = None
        for agent in agents:
            if agent.get("id") == agent_id:
                agent_entry = agent
                break
        if agent_entry is None:
            return None
        current = agent_entry.get("skills", [])
        if current:
            return None
        suggested = _suggest_skills_for_agent(agent_entry)
        if not suggested:
            return None
        agent_entry["skills"] = suggested
        try:
            _write_team_json()
        except OSError:
            agent_entry["skills"] = []
            return None
    print(f"[skills] Auto-provisioned {agent_id}: {suggested}")
    return suggested


_load_proposals()


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path == "/skills":
        skills = _scan_skills()
        handler._respond(200, {"skills": skills, "count": len(skills)})
        return True

    content_match = re.match(r"^/skills/([^/]+)/content$", path)
    if content_match:
        skill_id = content_match.group(1).strip()
        full = _get_skill_full(skill_id)
        if full is None:
            handler._respond(404, {"error": f"skill '{skill_id}' not found"})
            return True
        handler._respond(200, {"skill": full})
        return True

    section_match = re.match(r"^/skills/([^/]+)/section$", path)
    if section_match:
        agent_id = section_match.group(1).strip()
        section = _generate_skills_section(agent_id)
        handler._respond(200, {"agent_id": agent_id, "section": section})
        return True

    if path == "/skills/proposals":
        status_filter = query.get("status", [""])[0].strip()
        with _PROPOSALS_LOCK:
            if status_filter:
                filtered = [proposal for proposal in _SKILL_PROPOSALS if proposal.get("status") == status_filter]
            else:
                filtered = list(_SKILL_PROPOSALS)
        handler._respond(200, {"proposals": filtered, "count": len(filtered)})
        return True

    agent_match = re.match(r"^/skills/([^/]+)$", path)
    if agent_match:
        agent_id = agent_match.group(1).strip()
        team = _team_config()
        if team is None:
            handler._respond(500, {"error": "team.json not loaded"})
            return True
        agent_entry = None
        for agent in team.get("agents", []):
            if agent.get("id") == agent_id:
                agent_entry = agent
                break
        if agent_entry is None:
            handler._respond(404, {"error": f"agent '{agent_id}' not found in team.json"})
            return True
        assigned = agent_entry.get("skills", [])
        suggested = [skill for skill in _suggest_skills_for_agent(agent_entry) if skill not in assigned]
        handler._respond(200, {"agent_id": agent_id, "skills": assigned, "suggested": suggested})
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    if path != "/skills/assign":
        return False

    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True
    agent_id = str(data.get("agent_id", "")).strip()
    skills_list = data.get("skills", [])
    if not agent_id:
        handler._respond(400, {"error": "field 'agent_id' is required"})
        return True
    if not isinstance(skills_list, list):
        handler._respond(400, {"error": "skills must be a list"})
        return True
    if len(skills_list) > 20:
        handler._respond(400, {"error": "skills max 20 entries"})
        return True
    skills_list = [str(s).strip()[:50] for s in skills_list]
    available = {s["id"] for s in _scan_skills()}
    if "bridge-agent-core" in available and "bridge-agent-core" not in skills_list:
        skills_list.insert(0, "bridge-agent-core")
    invalid = [s for s in skills_list if s not in available]
    valid = [s for s in skills_list if s in available]
    team = _team_config()
    if team is None:
        handler._respond(500, {"error": "team.json not loaded"})
        return True
    agent_entry = None
    for agent in team.get("agents", []):
        if agent.get("id") == agent_id:
            agent_entry = agent
            break
    if agent_entry is None:
        handler._respond(404, {"error": f"agent '{agent_id}' not found in team.json"})
        return True
    with _team_config_lock():
        agent_entry["skills"] = valid
        try:
            _write_team_json()
        except OSError as exc:
            agent_entry["skills"] = []
            handler._respond(500, {"error": f"failed to persist: {exc}"})
            return True
    _ws_broadcast("agent_updated", {"agent_id": agent_id, "changes": {"skills": valid}})
    print(f"[skills] Assigned to {agent_id}: {valid}")
    deploy_result = None
    try:
        base_config = str(agent_entry.get("config_dir", "")).strip() or str(Path.home() / ".claude")
        deploy_result = _deploy_agent_skills(agent_id, base_config)
    except Exception as exc:
        print(f"[skills] WARNING: hot-reload deploy failed for {agent_id}: {exc}")
    if deploy_result and valid:
        try:
            from bridge_watcher import smart_inject

            skill_names = ", ".join(valid[:5])
            if len(valid) > 5:
                skill_names += f" (+{len(valid) - 5} more)"
            smart_inject(agent_id, f"Skills aktualisiert: {skill_names}. Sofort verfuegbar.")
        except Exception:
            pass
    handler._respond(
        200,
        {
            "ok": True,
            "agent_id": agent_id,
            "skills": valid,
            "invalid_skills": invalid,
            "hot_reloaded": deploy_result is not None,
        },
    )
    return True
