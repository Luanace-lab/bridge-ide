from __future__ import annotations

import glob
import os
from pathlib import Path

INSTRUCTION_FILES_BY_ENGINE: dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
    "qwen": "QWEN.md",
}

KNOWN_INSTRUCTION_FILES = tuple(dict.fromkeys(INSTRUCTION_FILES_BY_ENGINE.values()))


def _mangle_cwd(cwd: str) -> str:
    return cwd.replace("/", "-").replace(".", "-").replace("_", "-")


def instruction_filename_for_engine(engine: str = "") -> str:
    return INSTRUCTION_FILES_BY_ENGINE.get((engine or "claude").strip().lower(), "CLAUDE.md")


def resolve_agent_cli_layout(agent_home: str, agent_id: str) -> dict[str, str]:
    """Resolve canonical CLI paths for an agent.

    The CLI workspace is the source of truth for per-agent artifacts.
    Legacy callers may pass either the project/home root or the workspace
    itself (`.../.agent_sessions/{agent_id}`); both normalize to the same
    layout.
    """
    home_dir = str(agent_home or "").strip()
    if not home_dir:
        return {"home_dir": "", "workspace": "", "project_root": ""}

    home_path = Path(home_dir).expanduser()
    if home_path.name == agent_id and home_path.parent.name == ".agent_sessions":
        workspace = home_path
        project_root = home_path.parent.parent
    else:
        workspace = home_path / ".agent_sessions" / agent_id
        project_root = home_path

    return {
        "home_dir": str(home_path),
        "workspace": str(workspace),
        "project_root": str(project_root),
    }


def _dedupe_paths(paths: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        clean = str(path or "").strip()
        if clean and clean not in seen:
            deduped.append(clean)
            seen.add(clean)
    return deduped


def context_bridge_candidates(agent_home: str, agent_id: str) -> list[str]:
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    return _dedupe_paths(
        [
            os.path.join(layout["workspace"], "CONTEXT_BRIDGE.md"),
        ]
    )


def soul_candidates(agent_home: str, agent_id: str) -> list[str]:
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    return _dedupe_paths(
        [
            os.path.join(layout["workspace"], "SOUL.md"),
            os.path.join(layout["project_root"], "SOUL.md"),
            os.path.join(layout["home_dir"], "SOUL.md"),
        ]
    )


def instruction_candidates(agent_home: str, agent_id: str, engine: str = "") -> list[str]:
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    filename = instruction_filename_for_engine(engine)
    return _dedupe_paths(
        [
            os.path.join(layout["workspace"], filename),
            os.path.join(layout["home_dir"], filename),
            os.path.join(layout["project_root"], filename),
        ]
    )


def newest_existing_path(paths: list[str]) -> str:
    best_path = ""
    best_mtime = -1.0
    for candidate in _dedupe_paths(paths):
        try:
            mtime = os.path.getmtime(candidate)
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best_path = candidate
    return best_path


def first_existing_path(paths: list[str]) -> str:
    for candidate in _dedupe_paths(paths):
        if os.path.isfile(candidate):
            return candidate
    return ""


def detect_instruction_filename(agent_home: str, agent_id: str, engine: str = "") -> str:
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    preferred = instruction_filename_for_engine(engine)
    search_dirs = _dedupe_paths(
        [layout["workspace"], layout["home_dir"], layout["project_root"]]
    )

    for directory in search_dirs:
        existing: list[str] = []
        for filename in KNOWN_INSTRUCTION_FILES:
            candidate = os.path.join(directory, filename)
            if os.path.isfile(candidate):
                existing.append(filename)
        if not existing:
            continue
        if preferred in existing:
            return preferred
        return existing[0]
    return preferred


def memory_cwd_candidates(agent_home: str, agent_id: str) -> list[str]:
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    candidates = [
        layout["workspace"],
    ]
    return _dedupe_paths(candidates)


def memory_file_candidates(agent_home: str, agent_id: str) -> list[str]:
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    return _dedupe_paths(
        [
            os.path.join(layout["workspace"], "MEMORY.md"),
        ]
    )


def memory_search_bases(agent_id: str, config_dir: str = "") -> list[str]:
    candidates = [config_dir] if config_dir else [
        str(Path.home() / f".claude-agent-{agent_id}"),
        str(Path.home() / ".claude-sub2"),
        str(Path.home() / ".claude"),
    ]

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


def find_agent_memory_path(
    agent_id: str,
    agent_home: str,
    config_dir: str = "",
    *,
    include_glob_fallback: bool = True,
) -> str:
    if not agent_home:
        return ""

    workspace_memory = first_existing_path(memory_file_candidates(agent_home, agent_id))
    if workspace_memory:
        return workspace_memory

    for cwd in memory_cwd_candidates(agent_home, agent_id):
        mangled = _mangle_cwd(cwd)
        for base in memory_search_bases(agent_id, config_dir):
            mem_path = os.path.join(base, "projects", mangled, "memory", "MEMORY.md")
            if os.path.isfile(mem_path):
                return mem_path

    if not include_glob_fallback:
        return ""

    for base in memory_search_bases(agent_id, config_dir):
        projects_dir = os.path.join(base, "projects")
        if not os.path.isdir(projects_dir):
            continue
        pattern = os.path.join(projects_dir, f"*-{agent_id}", "memory", "MEMORY.md")
        matches = [path for path in glob.glob(pattern) if os.path.isfile(path)]
        if not matches:
            continue
        matches.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        return matches[0]

    return ""


def memory_template_text(agent_id: str, agent_role: str) -> str:
    role_text = agent_role or "unknown"
    return (
        f"# {agent_id} — Persistent Memory\n\n"
        "## Architektur-Wissen\n"
        "(Dateien, Strukturen, Abhaengigkeiten die du kennst)\n\n"
        "## Leo-Entscheidungen\n"
        "(Was Leo will, was er ablehnt)\n\n"
        "## Patterns\n"
        "(Wie wir Dinge tun — wiederkehrende Muster)\n\n"
        "## Fehler + Fixes\n"
        "(Was schiefging und warum)\n\n"
        "## Rolle\n"
        f"{role_text}\n"
    )


def ensure_agent_memory_file(
    agent_id: str,
    agent_role: str,
    agent_home: str,
    config_dir: str = "",
) -> str:
    existing = find_agent_memory_path(agent_id, agent_home, config_dir)
    if existing:
        return existing

    workspace_memory_candidates = memory_file_candidates(agent_home, agent_id)
    if workspace_memory_candidates:
        workspace_memory = workspace_memory_candidates[0]
        try:
            os.makedirs(os.path.dirname(workspace_memory), exist_ok=True)
            with open(workspace_memory, "w", encoding="utf-8") as fh:
                fh.write(memory_template_text(agent_id, agent_role))
            return workspace_memory
        except OSError:
            pass

    cwd_candidates = memory_cwd_candidates(agent_home, agent_id)
    if not cwd_candidates:
        return ""
    target_cwd = cwd_candidates[0]
    mangled = _mangle_cwd(target_cwd)

    for base in memory_search_bases(agent_id, config_dir):
        mem_dir = os.path.join(base, "projects", mangled, "memory")
        mem_path = os.path.join(mem_dir, "MEMORY.md")
        try:
            os.makedirs(mem_dir, exist_ok=True)
            if os.path.isfile(mem_path):
                return mem_path
            with open(mem_path, "w", encoding="utf-8") as fh:
                fh.write(memory_template_text(agent_id, agent_role))
            return mem_path
        except OSError:
            continue

    return ""


def memory_backup_target(agent_id: str, agent_home: str) -> str:
    session_dir = os.path.join(agent_home, ".agent_sessions", agent_id)
    if os.path.isdir(session_dir):
        return os.path.join(session_dir, "MEMORY_BACKUP.md")
    return os.path.join(agent_home, "MEMORY_BACKUP.md")


def find_memory_backup_path(agent_id: str, agent_home: str) -> str:
    candidates = [
        os.path.join(agent_home, ".agent_sessions", agent_id, "MEMORY_BACKUP.md"),
        os.path.join(agent_home, "MEMORY_BACKUP.md"),
    ]

    best_path = ""
    best_mtime = 0.0
    for candidate in candidates:
        try:
            mtime = os.path.getmtime(candidate)
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best_path = candidate
    return best_path
