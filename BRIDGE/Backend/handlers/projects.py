"""Project/context helper extraction from server.py (Slice 08).

This module owns:
- project context scan helpers
- project listing
- project name sanitization
- project scaffold document generation
- project creation helper

Anti-circular-import strategy:
  Shared utilities are injected via init().
  This module NEVER imports from server.
  Direct imports only from stable modules: handlers.cli and mcp_catalog.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from handlers.cli import write_file_if_missing
from mcp_catalog import build_client_mcp_config


_get_root_dir: Callable[[], str] | None = None
_get_projects_base_dir: Callable[[], str] | None = None
_normalize_path: Callable[[Any, str], str] | None = None
_parse_bool: Callable[..., bool] | None = None
_is_within_directory: Callable[[str, str], bool] | None = None
_validate_project_path: Callable[[Any, str], str | None] | None = None

_PROJECT_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def init(
    *,
    root_dir_fn: Callable[[], str],
    projects_base_dir_fn: Callable[[], str],
    normalize_path_fn: Callable[[Any, str], str],
    parse_bool_fn: Callable[..., bool],
    is_within_directory_fn: Callable[[str, str], bool],
    validate_project_path_fn: Callable[[Any, str], str | None],
) -> None:
    """Bind shared utility callbacks and lazy path getters."""
    global _get_root_dir, _get_projects_base_dir
    global _normalize_path, _parse_bool, _is_within_directory
    global _validate_project_path

    _get_root_dir = root_dir_fn
    _get_projects_base_dir = projects_base_dir_fn
    _normalize_path = normalize_path_fn
    _parse_bool = parse_bool_fn
    _is_within_directory = is_within_directory_fn
    _validate_project_path = validate_project_path_fn


def _root_dir() -> str:
    if _get_root_dir is None:
        raise RuntimeError("handlers.projects.init() not called: root_dir_fn missing")
    return _get_root_dir()


def _projects_base_dir() -> str:
    if _get_projects_base_dir is None:
        raise RuntimeError("handlers.projects.init() not called: projects_base_dir_fn missing")
    return _get_projects_base_dir()


def _normalize(raw_path: Any, base_dir: str) -> str:
    if _normalize_path is None:
        raise RuntimeError("handlers.projects.init() not called: normalize_path_fn missing")
    return _normalize_path(raw_path, base_dir)


def _parse_bool_value(value: Any, default: bool = False) -> bool:
    if _parse_bool is None:
        raise RuntimeError("handlers.projects.init() not called: parse_bool_fn missing")
    return _parse_bool(value, default=default)


def _within_directory(path: str, base_dir: str) -> bool:
    if _is_within_directory is None:
        raise RuntimeError("handlers.projects.init() not called: is_within_directory_fn missing")
    return _is_within_directory(path, base_dir)


def _validate_project_path_value(raw_path: Any, base_dir: str) -> str | None:
    if _validate_project_path is None:
        raise RuntimeError("handlers.projects.init() not called: validate_project_path_fn missing")
    return _validate_project_path(raw_path, base_dir)


def parent_chain(path: str) -> list[str]:
    cur = os.path.abspath(path)
    out = [cur]
    while True:
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        out.append(parent)
        cur = parent
    out.reverse()
    return out


def stat_entry(path: str, source: str, kind: str = "file") -> dict[str, Any]:
    expanded = os.path.abspath(os.path.expanduser(path))
    exists = os.path.exists(expanded)
    return {
        "path": expanded,
        "source": source,
        "kind": kind,
        "exists": exists,
        "is_file": os.path.isfile(expanded),
        "is_dir": os.path.isdir(expanded),
    }


def existing_chain_entries(directories: list[str], rel_path: str, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory in directories:
        candidate = os.path.join(directory, rel_path)
        if os.path.exists(candidate):
            rows.append(stat_entry(candidate, source))
    return rows


def build_context_map(project_path: str) -> dict[str, Any]:
    project_path = _normalize(project_path, _root_dir())
    home = str(Path.home())
    chain = parent_chain(project_path)

    claude_memory_candidates = [
        stat_entry(os.path.join(home, ".claude", "CLAUDE.md"), "Claude global memory"),
        stat_entry(os.path.join(project_path, "CLAUDE.md"), "Claude project memory"),
        stat_entry(
            os.path.join(project_path, ".claude", "CLAUDE.md"),
            "Claude project memory (.claude)",
        ),
        stat_entry(os.path.join(project_path, "CLAUDE.local.md"), "Claude local memory (non-shared)"),
        stat_entry(
            os.path.join(project_path, ".claude", "CLAUDE.local.md"),
            "Claude local memory (.claude)",
        ),
    ]

    claude_memory_chain = []
    claude_memory_chain.extend(existing_chain_entries(chain, "CLAUDE.md", "Claude parent memory chain"))
    claude_memory_chain.extend(
        existing_chain_entries(chain, os.path.join(".claude", "CLAUDE.md"), "Claude parent memory chain")
    )

    claude_settings = [
        stat_entry(os.path.join(home, ".claude", "settings.json"), "Claude user settings"),
        stat_entry(os.path.join(project_path, ".claude", "settings.json"), "Claude project settings"),
        stat_entry(
            os.path.join(project_path, ".claude", "settings.local.json"),
            "Claude project local settings",
        ),
    ]

    claude_skills = [
        stat_entry(os.path.join(home, ".claude", "skills"), "Claude user skills", kind="dir"),
        stat_entry(os.path.join(project_path, ".claude", "skills"), "Claude project skills", kind="dir"),
    ]

    claude_agents = [
        stat_entry(os.path.join(home, ".claude", "agents"), "Claude user agents", kind="dir"),
        stat_entry(os.path.join(project_path, ".claude", "agents"), "Claude project agents", kind="dir"),
        stat_entry(os.path.join(home, ".claude", "teams"), "Claude teams", kind="dir"),
        stat_entry(os.path.join(project_path, ".claude", "teams"), "Claude project teams", kind="dir"),
    ]

    codex_instruction_chain = existing_chain_entries(chain, "AGENTS.md", "Codex AGENTS parent chain")
    codex_fallback_chain = existing_chain_entries(chain, "CLAUDE.md", "Codex fallback doc chain")

    codex_candidates = [
        stat_entry(os.path.join(project_path, "AGENTS.md"), "Codex project instructions"),
        stat_entry(os.path.join(project_path, "Agents.md"), "Codex alt filename (legacy)"),
        stat_entry(os.path.join(project_path, "CLAUDE.md"), "Codex fallback instruction file"),
    ]

    codex_config = [
        stat_entry(os.path.join(home, ".codex", "config.toml"), "Codex user config"),
        stat_entry(os.path.join(project_path, ".codex", "config.toml"), "Codex project config (.codex)"),
        stat_entry(os.path.join(project_path, ".agents", "config.toml"), "Codex project config (.agents)"),
    ]

    codex_skills = [
        stat_entry(os.path.join(home, ".agents", "skills"), "Codex user skills (.agents)", kind="dir"),
        stat_entry(os.path.join(project_path, ".agents", "skills"), "Codex project skills (.agents)", kind="dir"),
        stat_entry(os.path.join(home, ".codex", "skills"), "Codex user skills (.codex, local runtime)", kind="dir"),
        stat_entry(os.path.join(project_path, ".codex", "skills"), "Codex project skills (.codex)", kind="dir"),
        stat_entry(os.path.join(home, ".codex", "rules"), "Codex user rules", kind="dir"),
    ]

    gemini_candidates = [
        stat_entry(os.path.join(project_path, "GEMINI.md"), "GEMINI.md"),
        stat_entry(os.path.join(project_path, "CLAUDE.md"), "Gemini fallback instruction file"),
    ]
    gemini_settings = [
        stat_entry(os.path.join(home, ".gemini", "settings.json"), "Gemini user settings"),
        stat_entry(os.path.join(project_path, ".gemini", "settings.json"), "Gemini project settings"),
    ]

    qwen_candidates = [
        stat_entry(os.path.join(project_path, "QWEN.md"), "QWEN.md"),
        stat_entry(os.path.join(project_path, "CLAUDE.md"), "Qwen fallback instruction file"),
    ]
    qwen_settings = [
        stat_entry(os.path.join(home, ".qwen", "settings.json"), "Qwen user settings"),
        stat_entry(os.path.join(project_path, ".qwen", "settings.json"), "Qwen project settings"),
    ]

    all_entries: list[tuple[str, dict[str, Any]]] = []
    for label, items in [
        ("claude/memory", claude_memory_candidates),
        ("claude/memory_chain", claude_memory_chain),
        ("claude/settings", claude_settings),
        ("claude/skills", claude_skills),
        ("claude/agents", claude_agents),
        ("codex/instructions", codex_candidates),
        ("codex/instruction_chain", codex_instruction_chain),
        ("codex/fallback_chain", codex_fallback_chain),
        ("codex/config", codex_config),
        ("codex/skills", codex_skills),
        ("gemini/instructions", gemini_candidates),
        ("gemini/settings", gemini_settings),
        ("qwen/instructions", qwen_candidates),
        ("qwen/settings", qwen_settings),
    ]:
        for entry in items:
            all_entries.append((label, entry))

    found = [(group, entry) for group, entry in all_entries if entry.get("exists")]
    summary = {
        "found_count": len(found),
        "total_scanned": len(all_entries),
        "found": [
            {"path": entry["path"], "source": entry["source"], "kind": entry.get("kind", "file"), "group": group}
            for group, entry in found
        ],
    }

    return {
        "project_path": project_path,
        "summary": summary,
        "claude": {
            "memory_candidates": claude_memory_candidates,
            "memory_chain": claude_memory_chain,
            "settings": claude_settings,
            "skills": claude_skills,
            "agents": claude_agents,
        },
        "codex": {
            "instruction_candidates": codex_candidates,
            "instruction_chain": codex_instruction_chain,
            "fallback_chain": codex_fallback_chain,
            "config": codex_config,
            "skills": codex_skills,
        },
        "gemini": {
            "instruction_candidates": gemini_candidates,
            "settings": gemini_settings,
        },
        "qwen": {
            "instruction_candidates": qwen_candidates,
            "settings": qwen_settings,
        },
    }


def list_projects(base_dir: str) -> list[dict[str, Any]]:
    base = _normalize(base_dir, _projects_base_dir())
    if not os.path.isdir(base):
        return []

    rows: list[dict[str, Any]] = []
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        if not os.path.isdir(path):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue

        project_md = os.path.join(path, "PROJECT.md")
        has_project_md = os.path.isfile(project_md)
        preview = ""
        if has_project_md:
            try:
                raw = Path(project_md).read_text(encoding="utf-8")
                preview = raw[:200]
            except OSError:
                preview = ""

        tags: list[str] = []
        tags_file = os.path.join(path, ".bridge", "tags.json")
        if os.path.isfile(tags_file):
            try:
                raw_tags = json.loads(Path(tags_file).read_text(encoding="utf-8"))
                if isinstance(raw_tags, list):
                    tags = [str(tag) for tag in raw_tags]
            except (json.JSONDecodeError, OSError):
                tags = []

        rows.append(
            {
                "name": name,
                "path": path,
                "mtime": stat.st_mtime,
                "has_project_md": has_project_md,
                "tags": tags,
                "preview": preview,
            }
        )
    rows.sort(key=lambda item: item["mtime"], reverse=True)
    return rows


def handle_get(handler: Any, path: str, query_string: str) -> bool:
    query = parse_qs(query_string, keep_blank_values=False)

    if path == "/projects":
        base_dir = _normalize((query.get("base_dir") or [None])[0], _projects_base_dir())
        projects = list_projects(base_dir)
        handler._respond(200, {"base_dir": base_dir, "projects": projects, "count": len(projects)})
        return True

    if path == "/projects/open":
        raw_path = (query.get("project_path") or [None])[0]
        if not raw_path:
            handler._respond(400, {"error": "project_path is required"})
            return True
        project_path = _validate_project_path_value(raw_path, _projects_base_dir())
        if not project_path:
            handler._respond(403, {"error": "path outside allowed directory"})
            return True
        if not os.path.isdir(project_path):
            handler._respond(404, {"error": f"project not found: {project_path}"})
            return True
        name = os.path.basename(project_path)
        notes = ""
        project_md = os.path.join(project_path, "PROJECT.md")
        if os.path.isfile(project_md):
            try:
                notes = Path(project_md).read_text(encoding="utf-8")
            except OSError:
                notes = ""
        tags: list[str] = []
        tags_file = os.path.join(project_path, ".bridge", "tags.json")
        if os.path.isfile(tags_file):
            try:
                raw_tags = json.loads(Path(tags_file).read_text(encoding="utf-8"))
                if isinstance(raw_tags, list):
                    tags = [str(tag) for tag in raw_tags]
            except (json.JSONDecodeError, OSError):
                tags = []
        handler._respond(200, {
            "ok": True,
            "project_path": project_path,
            "name": name,
            "notes": notes,
            "tags": tags,
        })
        return True

    if path in {"/context", "/context/scan"}:
        project_path = _validate_project_path_value((query.get("project_path") or [None])[0], _projects_base_dir())
        if not project_path:
            handler._respond(403, {"error": "path outside allowed directory"})
            return True
        handler._respond(200, build_context_map(project_path))
        return True

    return False


def sanitize_project_name(name: str) -> str:
    raw = name.strip()
    if not raw:
        raise ValueError("project_name is required")
    cleaned = _PROJECT_SAFE_NAME_RE.sub("-", raw).strip("-._")
    if not cleaned:
        raise ValueError("project_name is invalid")
    return cleaned


def _generate_claude_md(project_name: str, leader: dict, agents: list) -> str:
    lines = [f"# {project_name}\n"]

    lines.append("## DU BIST TEIL DER BRIDGE (PFLICHT)\n")
    lines.append(
        "Du bist Teil eines Multi-Agent-Systems namens **Bridge IDE**. "
        "Mehrere KI-Agents arbeiten zusammen — und du bist einer davon.\n"
    )
    lines.append(
        "- **Kommunikation NUR ueber Bridge MCP.** Terminal-Output sieht NIEMAND.\n"
        "- **ERSTE AKTION nach Start:** `bridge_register(agent_id=\"DEIN_NAME\", role=\"DEINE_ROLLE\")`\n"
        "- **Danach:** `bridge_receive()` — Nachrichten pruefen\n"
        "- **Nach JEDER Aufgabe:** `bridge_send(to=AUFTRAGGEBER, content=ERGEBNIS)` + `bridge_receive()`\n"
        "- **Idle?** `bridge_task_queue(state='created')` pruefen — Arbeit suchen\n"
        "- **Verboten:** Aufgabe bestaetigen ohne sie auszufuehren. Terminal als Kommunikation nutzen.\n"
    )

    if leader and leader.get("prompt"):
        lines.append("## Projektleitung\n")
        leader_name = str(leader.get("name", "Leader")).strip()
        leader_role = str(leader.get("role", leader.get("position", ""))).strip()
        lines.append(f"**{leader_name}**" + (f" — {leader_role}" if leader_role else "") + "\n")
        lines.append(str(leader["prompt"]).strip() + "\n")

    if agents:
        lines.append("## Team\n")
        lines.append("| Agent | Rolle | Model |")
        lines.append("|-------|-------|-------|")
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            name = str(agent.get("name", "")).strip()
            role = str(agent.get("role", agent.get("position", ""))).strip()
            model = str(agent.get("model", "")).strip()
            lines.append(f"| {name} | {role} | {model} |")
        lines.append("")

    for agent in agents:
        if not isinstance(agent, dict):
            continue
        name = str(agent.get("name", "")).strip()
        prompt = str(agent.get("prompt", "")).strip()
        if name and prompt:
            lines.append(f"### {name}\n")
            scope = str(agent.get("scope", "")).strip()
            team = str(agent.get("teamAssignment", "")).strip()
            reports_to = str(agent.get("reportsTo", "")).strip()
            level = str(agent.get("hierarchyLevel", "")).strip()
            permission_mode = str(agent.get("permission", "")).strip()
            capabilities = [
                str(item).strip()
                for item in (agent.get("permissions") if isinstance(agent.get("permissions"), list) else [])
                if str(item).strip()
            ]
            if level:
                lines.append(f"**Level:** {level}")
            if team:
                lines.append(f"**Team:** {team}")
            if reports_to:
                lines.append(f"**Reports-to:** {reports_to}")
            if scope:
                lines.append(f"**Scope:** {scope}")
            if permission_mode:
                lines.append(f"**Permission-Mode:** {permission_mode}")
            if capabilities:
                lines.append(f"**Capabilities:** {', '.join(capabilities)}")
            if any((level, team, reports_to, scope, permission_mode, capabilities)):
                lines.append("")
            lines.append(f"{prompt}\n")

    return "\n".join(lines) + "\n"


def _generate_agents_md(project_name: str, leader: dict, agents: list) -> str:
    lines = [f"# AGENTS — {project_name}\n"]
    lines.append("Projektregeln fuer Codex-Agenten.\n")

    lines.append("## DU BIST TEIL DER BRIDGE (PFLICHT)\n")
    lines.append(
        "Du bist kein isoliertes Tool. Du bist Teil eines Multi-Agent-Systems "
        "namens **Bridge IDE**. Mehrere KI-Agents arbeiten zusammen — und du bist einer davon.\n"
    )
    lines.append("### Kommunikationsregeln (UNVERHANDELBAR)\n")
    lines.append(
        "- **Dein einziger Kommunikationskanal ist die Bridge.** Es gibt KEINEN anderen Weg.\n"
        "- Was du in dein Terminal schreibst, sieht NIEMAND. Nicht der User, nicht andere Agents.\n"
        "- Kommunikation existiert NUR durch `bridge_send()`. Ohne bridge_send bist du stumm.\n"
        "- Nachrichten erhaeltst du NUR durch `bridge_receive()`. Ohne bridge_receive bist du taub.\n"
    )
    lines.append("### Bei Start (ERSTE AKTION — keine Ausnahme)\n")
    lines.append(
        "```\n"
        "bridge_register(agent_id=\"DEIN_NAME\", role=\"DEINE_ROLLE\")\n"
        "```\n"
        "Danach sofort `bridge_receive()` aufrufen.\n"
    )
    lines.append("### Arbeitsschleife (ENDLOS)\n")
    lines.append(
        "1. `bridge_receive()` — Nachrichten pruefen\n"
        "2. Nachrichten da? → AUSFUEHREN (nicht nur bestaetigen!)\n"
        "3. `bridge_task_queue(state='created')` — offene Tasks pruefen\n"
        "4. Task da? → `bridge_task_claim` → bearbeiten → `bridge_task_done`\n"
        "5. Ergebnis melden: `bridge_send(to=AUFTRAGGEBER, content=ERGEBNIS)`\n"
        "6. Zurueck zu Schritt 1\n"
    )
    lines.append("### Verboten\n")
    lines.append(
        "- Aufgabe bestaetigen ohne sie auszufuehren\n"
        "- Terminal-Output als Kommunikation betrachten\n"
        "- Idle sein ohne `bridge_task_queue` zu pruefen\n"
        "- `bridge_send` vergessen nach erledigter Aufgabe\n"
    )

    all_agents = []
    if leader and leader.get("name"):
        all_agents.append(leader)
    for agent in agents:
        if isinstance(agent, dict) and agent.get("name"):
            all_agents.append(agent)

    if all_agents:
        lines.append("## Rollen\n")
        for agent in all_agents:
            name = str(agent.get("name", "")).strip()
            role = str(agent.get("role", agent.get("position", ""))).strip()
            model = str(agent.get("model", "")).strip()
            prompt = str(agent.get("prompt", "")).strip()
            level = str(agent.get("hierarchyLevel", "")).strip()
            team = str(agent.get("teamAssignment", "")).strip()
            reports_to = str(agent.get("reportsTo", "")).strip()
            scope = str(agent.get("scope", "")).strip()
            permission_mode = str(agent.get("permission", "")).strip()
            capabilities = [
                str(item).strip()
                for item in (agent.get("permissions") if isinstance(agent.get("permissions"), list) else [])
                if str(item).strip()
            ]
            lines.append(f"### {name}\n")
            if role:
                lines.append(f"**Role:** {role}")
            if model:
                lines.append(f"**Model:** {model}")
            if level:
                lines.append(f"**Level:** {level}")
            if team:
                lines.append(f"**Team:** {team}")
            if reports_to:
                lines.append(f"**Reports-to:** {reports_to}")
            if scope:
                lines.append(f"**Scope:** {scope}")
            if permission_mode:
                lines.append(f"**Permission-Mode:** {permission_mode}")
            if capabilities:
                lines.append(f"**Capabilities:** {', '.join(capabilities)}")
            if prompt:
                lines.append(f"\n{prompt}")
            lines.append("")

    return "\n".join(lines) + "\n"


def _generate_engine_md(engine_name: str, project_name: str, engine_agents: list) -> str:
    lines = [f"# {engine_name.upper()} — {project_name}\n"]
    lines.append(f"Projektkontext fuer {engine_name}.\n")

    lines.append("## DU BIST TEIL DER BRIDGE (PFLICHT)\n")
    lines.append(
        "Du bist Teil eines Multi-Agent-Systems namens **Bridge IDE**.\n"
        "- **Kommunikation NUR ueber Bridge MCP.** Terminal-Output sieht NIEMAND.\n"
        "- **ERSTE AKTION:** `bridge_register(agent_id=\"DEIN_NAME\", role=\"DEINE_ROLLE\")`\n"
        "- **Danach:** `bridge_receive()` — Nachrichten pruefen\n"
        "- **Nach JEDER Aufgabe:** `bridge_send(to=AUFTRAGGEBER, content=ERGEBNIS)` + `bridge_receive()`\n"
        "- **Idle?** `bridge_task_queue(state='created')` pruefen\n"
    )

    if engine_agents:
        lines.append("## Agents\n")
        for agent in engine_agents:
            if not isinstance(agent, dict):
                continue
            name = str(agent.get("name", "")).strip()
            model = str(agent.get("model", "")).strip()
            prompt = str(agent.get("prompt", "")).strip()
            lines.append(f"### {name}\n")
            if model:
                lines.append(f"**Model:** {model}")
            if prompt:
                lines.append(f"\n{prompt}")
            lines.append("")

    return "\n".join(lines) + "\n"


def _derive_permission_allow_list(leader: dict, agents: list) -> list[str]:
    perm_map: dict[str, list[str]] = {
        "bypassPermissions": ["*"],
        "acceptEdits": ["Edit", "Write", "Read"],
        "dontAsk": ["Edit", "Write", "Read", "Bash", "Glob", "Grep"],
    }
    allow_set: set[str] = set()

    all_agents = []
    if leader and isinstance(leader, dict):
        all_agents.append(leader)
    for agent in agents:
        if isinstance(agent, dict):
            all_agents.append(agent)

    for agent in all_agents:
        perm = str(agent.get("permission", "")).strip()
        if perm in perm_map:
            for tool in perm_map[perm]:
                allow_set.add(tool)

    if "*" in allow_set:
        return ["*"]
    return sorted(allow_set)


def create_project(data: dict[str, Any]) -> dict[str, Any]:
    project_name = sanitize_project_name(str(data.get("project_name", "")))
    base_dir = _normalize(data.get("base_dir"), _projects_base_dir())
    overwrite = _parse_bool_value(data.get("overwrite"), default=False)

    if not _within_directory(base_dir, _projects_base_dir()):
        raise ValueError("base_dir outside allowed projects directory")

    project_path = os.path.abspath(os.path.join(base_dir, project_name))
    base_abs = os.path.abspath(base_dir)
    if not project_path.startswith(base_abs + os.sep) and project_path != base_abs:
        raise ValueError("project path escapes base_dir")

    os.makedirs(project_path, exist_ok=True)

    scaffold = data.get("scaffold")
    scaffold_dict = scaffold if isinstance(scaffold, dict) else {}

    created: list[dict[str, Any]] = []
    leader_data = data.get("leader") if isinstance(data.get("leader"), dict) else {}
    agents_data = data.get("agents") if isinstance(data.get("agents"), list) else []

    if _parse_bool_value(scaffold_dict.get("agents_md"), True):
        path = os.path.join(project_path, "AGENTS.md")
        agents_md_content = _generate_agents_md(project_name, leader_data, agents_data)
        ok, state = write_file_if_missing(path, agents_md_content, overwrite=overwrite)
        created.append({"path": path, "state": state, "changed": ok})

    if _parse_bool_value(scaffold_dict.get("teamlead_md"), True):
        path = os.path.join(os.path.dirname(project_path), "teamlead.md")
        ok, state = write_file_if_missing(
            path,
            "# TeamLead Scope\n\n",
            overwrite=overwrite,
        )
        created.append({"path": path, "state": state, "changed": ok})

    if _parse_bool_value(scaffold_dict.get("claude_md"), True):
        path = os.path.join(project_path, "CLAUDE.md")
        claude_md_content = _generate_claude_md(project_name, leader_data, agents_data)
        ok, state = write_file_if_missing(path, claude_md_content, overwrite=overwrite)
        created.append({"path": path, "state": state, "changed": ok})

    gemini_agents = [
        agent for agent in agents_data
        if isinstance(agent, dict) and str(agent.get("model", "")).startswith("gemini")
    ]
    qwen_agents = [
        agent for agent in agents_data
        if isinstance(agent, dict) and str(agent.get("model", "")).startswith("qwen")
    ]

    if _parse_bool_value(scaffold_dict.get("gemini_md"), True):
        path = os.path.join(project_path, "GEMINI.md")
        gemini_content = _generate_engine_md("Gemini", project_name, gemini_agents)
        ok, state = write_file_if_missing(path, gemini_content, overwrite=overwrite)
        created.append({"path": path, "state": state, "changed": ok})

    if _parse_bool_value(scaffold_dict.get("qwen_md"), True):
        path = os.path.join(project_path, "QWEN.md")
        qwen_content = _generate_engine_md("Qwen", project_name, qwen_agents)
        ok, state = write_file_if_missing(path, qwen_content, overwrite=overwrite)
        created.append({"path": path, "state": state, "changed": ok})

    if _parse_bool_value(scaffold_dict.get("claude_local_md"), False):
        path = os.path.join(project_path, ".claude", "CLAUDE.local.md")
        ok, state = write_file_if_missing(
            path,
            "# CLAUDE LOCAL\n\nLokale, nicht geteilte Hinweise.\n",
            overwrite=overwrite,
        )
        created.append({"path": path, "state": state, "changed": ok})

    if _parse_bool_value(scaffold_dict.get("claude_agents_dir"), True):
        path = os.path.join(project_path, ".claude", "agents")
        os.makedirs(path, exist_ok=True)
        created.append({"path": path, "state": "ensured", "changed": True})

    if _parse_bool_value(scaffold_dict.get("claude_skills_dir"), True):
        path = os.path.join(project_path, ".claude", "skills")
        os.makedirs(path, exist_ok=True)
        created.append({"path": path, "state": "ensured", "changed": True})

    if _parse_bool_value(scaffold_dict.get("codex_skills_dir"), True):
        path = os.path.join(project_path, ".codex", "skills")
        os.makedirs(path, exist_ok=True)
        created.append({"path": path, "state": "ensured", "changed": True})

    if _parse_bool_value(scaffold_dict.get("codex_config"), True):
        path = os.path.join(project_path, ".codex", "config.toml")
        codex_model = str(leader_data.get("model", "")).strip() if leader_data else ""
        codex_agents = [
            agent
            for agent in agents_data
            if isinstance(agent, dict) and str(agent.get("model", "")).startswith(("o4", "codex", "o3"))
        ]
        if codex_agents:
            codex_model = str(codex_agents[0].get("model", codex_model))
        config_toml = f'model = "{codex_model}"\n' if codex_model else 'model = "o4-mini"\n'
        ok, state = write_file_if_missing(path, config_toml, overwrite=overwrite)
        created.append({"path": path, "state": state, "changed": ok})

    if _parse_bool_value(scaffold_dict.get("claude_settings"), True):
        path = os.path.join(project_path, ".claude", "settings.json")
        allow_list = _derive_permission_allow_list(leader_data, agents_data)
        settings_content = json.dumps({"permissions": {"allow": allow_list}}, indent=2, ensure_ascii=False) + "\n"
        ok, state = write_file_if_missing(path, settings_content, overwrite=overwrite)
        created.append({"path": path, "state": state, "changed": ok})

    if _parse_bool_value(scaffold_dict.get("mcp_json"), True):
        path = os.path.join(project_path, ".mcp.json")
        mcp_content = json.dumps(build_client_mcp_config(""), indent=2, ensure_ascii=False) + "\n"
        ok, state = write_file_if_missing(path, mcp_content, overwrite=overwrite)
        created.append({"path": path, "state": state, "changed": ok})

    project_notes = data.get("project_notes")
    if isinstance(project_notes, str) and project_notes.strip():
        notes_content = project_notes
    else:
        notes_content = f"# {project_name}\n"
    path = os.path.join(project_path, "PROJECT.md")
    ok, state = write_file_if_missing(path, notes_content, overwrite=True)
    created.append({"path": path, "state": state, "changed": ok})

    raw_tags = data.get("tags")
    if isinstance(raw_tags, list) and raw_tags:
        tags_list = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
        if tags_list:
            tags_dir = os.path.join(project_path, ".bridge")
            os.makedirs(tags_dir, exist_ok=True)
            tags_path = os.path.join(tags_dir, "tags.json")
            Path(tags_path).write_text(
                json.dumps(tags_list, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            created.append({"path": tags_path, "state": "written", "changed": True})
    elif isinstance(raw_tags, str) and raw_tags.strip():
        tags_list = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
        if tags_list:
            tags_dir = os.path.join(project_path, ".bridge")
            os.makedirs(tags_dir, exist_ok=True)
            tags_path = os.path.join(tags_dir, "tags.json")
            Path(tags_path).write_text(
                json.dumps(tags_list, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            created.append({"path": tags_path, "state": "written", "changed": True})

    all_agents = []
    if leader_data and leader_data.get("name"):
        all_agents.append(leader_data)
    for agent in agents_data:
        if isinstance(agent, dict) and agent.get("name"):
            all_agents.append(agent)
    for agent in all_agents:
        agent_name = str(agent.get("name", "")).strip()
        if not agent_name:
            continue
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", agent_name).strip("_")
        if not safe_name:
            continue
        agent_dir = os.path.join(project_path, ".agents", safe_name)
        os.makedirs(agent_dir, exist_ok=True)
        agent_claude_path = os.path.join(agent_dir, "CLAUDE.md")
        agent_prompt = str(agent.get("prompt", "")).strip()
        agent_role = str(agent.get("role", agent.get("position", ""))).strip()
        agent_model = str(agent.get("model", "")).strip()
        agent_level = str(agent.get("hierarchyLevel", "")).strip()
        agent_team = str(agent.get("teamAssignment", "")).strip()
        agent_reports_to = str(agent.get("reportsTo", "")).strip()
        agent_scope = str(agent.get("scope", "")).strip()
        agent_permission = str(agent.get("permission", "")).strip()
        agent_capabilities = [
            str(item).strip()
            for item in (agent.get("permissions") if isinstance(agent.get("permissions"), list) else [])
            if str(item).strip()
        ]
        agent_md = f"# Agent: {agent_name}\n\n"
        if agent_role:
            agent_md += f"**Role:** {agent_role}\n"
        if agent_model:
            agent_md += f"**Model:** {agent_model}\n"
        if agent_level:
            agent_md += f"**Level:** {agent_level}\n"
        if agent_team:
            agent_md += f"**Team:** {agent_team}\n"
        if agent_reports_to:
            agent_md += f"**Reports-to:** {agent_reports_to}\n"
        if agent_scope:
            agent_md += f"**Scope:** {agent_scope}\n"
        if agent_permission:
            agent_md += f"**Permission-Mode:** {agent_permission}\n"
        if agent_capabilities:
            agent_md += f"**Capabilities:** {', '.join(agent_capabilities)}\n"
        agent_md += "\n"
        if agent_prompt:
            agent_md += f"## Instruktionen\n\n{agent_prompt}\n"
        else:
            agent_md += "## Instruktionen\n\nKeine spezifischen Instruktionen.\n"
        ok, state = write_file_if_missing(agent_claude_path, agent_md, overwrite=overwrite)
        created.append({"path": agent_claude_path, "state": state, "changed": ok})

    return {
        "ok": True,
        "project_name": project_name,
        "project_path": project_path,
        "base_dir": base_dir,
        "created": created,
    }
