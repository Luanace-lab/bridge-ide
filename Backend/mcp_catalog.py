from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_BACKEND_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BACKEND_DIR.parent
_CATALOG_PATH = _ROOT_DIR / "config" / "mcp_catalog.json"


def catalog_path() -> Path:
    """Return the repository-local MCP catalog path."""
    return _CATALOG_PATH


def _read_catalog() -> dict[str, Any]:
    with open(_CATALOG_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"invalid MCP catalog at {_CATALOG_PATH}: root must be an object")
    return data


def _placeholder_values() -> dict[str, str]:
    home = str(Path.home())
    return {
        "backend_dir": str(_BACKEND_DIR),
        "root_dir": str(_ROOT_DIR),
        "home": home,
        "aase_mcp_path": os.environ.get(
            "AASE_MCP_PATH",
            str(Path.home() / "Desktop" / "ACE_SEC" / "aase_mcp.py"),
        ),
        "ghost_mcp_path": os.environ.get(
            "GHOST_MCP_PATH",
            str(Path.home() / "Desktop" / "ghost" / "ghost_mcp_server.py"),
        ),
        "playwright_mcp_package": os.environ.get(
            "PLAYWRIGHT_MCP_PACKAGE",
            "@playwright/mcp@0.0.68",
        ),
    }


def _resolve_template(value: str) -> str:
    try:
        return value.format(**_placeholder_values())
    except KeyError as exc:
        raise ValueError(f"unknown MCP catalog placeholder in {value!r}: {exc}") from exc


def _resolve_runtime_entry(spec: dict[str, Any]) -> dict[str, Any]:
    transport = str(spec.get("transport", "stdio")).strip() or "stdio"
    if transport == "streamable-http":
        url = str(spec.get("url", "")).strip()
        if not url:
            raise ValueError("streamable-http MCP entry requires 'url'")
        headers = {
            str(k): str(v)
            for k, v in dict(spec.get("headers", {}) or {}).items()
            if str(k).strip()
        }
        entry: dict[str, Any] = {"type": "streamable-http", "url": url}
        if headers:
            entry["headers"] = headers
        return entry
    if transport != "stdio":
        raise ValueError(f"unsupported runtime MCP transport in catalog: {transport!r}")
    command = _resolve_template(str(spec.get("command", "")).strip())
    args = [
        _resolve_template(str(arg))
        for arg in list(spec.get("args", []) or [])
    ]
    env = {
        str(key): _resolve_template(str(value))
        for key, value in dict(spec.get("env", {}) or {}).items()
        if str(key).strip()
    }
    return {
        "type": "stdio",
        "command": command,
        "args": args,
        "env": env,
    }


def runtime_mcp_specs() -> dict[str, dict[str, Any]]:
    """Return raw runtime MCP specs from the catalog."""
    data = _read_catalog()
    specs = data.get("runtime_servers", {})
    if not isinstance(specs, dict):
        raise ValueError("invalid MCP catalog: runtime_servers must be an object")
    return {
        str(name): dict(spec)
        for name, spec in specs.items()
        if isinstance(spec, dict)
    }


def runtime_mcp_registry() -> dict[str, dict[str, Any]]:
    """Return resolved MCP client config for runtime-usable servers."""
    registry: dict[str, dict[str, Any]] = {}
    for name, spec in runtime_mcp_specs().items():
        registry[name] = _resolve_runtime_entry(spec)
    return registry


def planned_mcp_specs() -> dict[str, dict[str, Any]]:
    """Return metadata-only planned MCP specs from the catalog."""
    data = _read_catalog()
    specs = data.get("planned_servers", {})
    if not isinstance(specs, dict):
        raise ValueError("invalid MCP catalog: planned_servers must be an object")
    return {
        str(name): dict(spec)
        for name, spec in specs.items()
        if isinstance(spec, dict)
    }


def requested_runtime_mcp_names(mcp_servers: str) -> list[str]:
    """Resolve requested runtime MCP names, honoring catalog include_in_all."""
    specs = runtime_mcp_specs()
    if mcp_servers == "all":
        requested = [
            name
            for name, spec in specs.items()
            if bool(spec.get("include_in_all", False))
        ]
    elif mcp_servers:
        requested = ["bridge"] + [s.strip() for s in mcp_servers.split(",") if s.strip()]
    else:
        requested = ["bridge"]
    seen: set[str] = set()
    resolved: list[str] = []
    for name in requested:
        if name in seen or name not in specs:
            continue
        seen.add(name)
        resolved.append(name)
    return resolved


def build_client_mcp_config(mcp_servers: str) -> dict[str, Any]:
    """Build a repo-local .mcp.json payload from the central catalog."""
    registry = runtime_mcp_registry()
    return {
        "mcpServers": {
            name: registry[name]
            for name in requested_runtime_mcp_names(mcp_servers)
            if name in registry
        }
    }


def register_runtime_server(
    name: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Register a new runtime MCP server in the catalog (persistent).

    spec must contain either:
      - transport=stdio: command, args, env
      - transport=streamable-http: url, headers (optional)

    Returns the full updated runtime_servers section.
    """
    import tempfile as _tmpfile

    name = str(name).strip()
    if not name:
        raise ValueError("MCP server name is required")
    transport = str(spec.get("transport", "stdio")).strip() or "stdio"
    if transport not in ("stdio", "streamable-http"):
        raise ValueError(f"unsupported transport: {transport!r}")
    if transport == "streamable-http" and not str(spec.get("url", "")).strip():
        raise ValueError("streamable-http requires 'url'")
    if transport == "stdio" and not str(spec.get("command", "")).strip():
        raise ValueError("stdio requires 'command'")
    # Read current catalog
    data = _read_catalog()
    runtime = data.setdefault("runtime_servers", {})
    # Merge spec into catalog
    runtime[name] = dict(spec)
    runtime[name]["transport"] = transport
    # Atomic write
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = _tmpfile.mkstemp(
        dir=str(_CATALOG_PATH.parent), suffix=".tmp"
    )
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, str(_CATALOG_PATH))
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return dict(runtime)


# ---------------------------------------------------------------------------
# Skill → MCP Resolution
# ---------------------------------------------------------------------------

_SKILL_MCP_MAP_PATH = _ROOT_DIR / "config" / "skill_mcp_map.json"
_SKILL_MCP_CACHE: dict[str, Any] | None = None
_SKILL_MCP_CACHE_MTIME: float = 0.0


def _load_skill_mcp_map() -> dict[str, Any]:
    """Load skill_mcp_map.json with mtime-based caching."""
    global _SKILL_MCP_CACHE, _SKILL_MCP_CACHE_MTIME
    if not _SKILL_MCP_MAP_PATH.is_file():
        return {}
    mtime = _SKILL_MCP_MAP_PATH.stat().st_mtime
    if _SKILL_MCP_CACHE is not None and mtime == _SKILL_MCP_CACHE_MTIME:
        return _SKILL_MCP_CACHE
    with open(_SKILL_MCP_MAP_PATH, encoding="utf-8") as f:
        data = json.load(f)
    _SKILL_MCP_CACHE = {k: v for k, v in data.items() if k != "_meta"}
    _SKILL_MCP_CACHE_MTIME = mtime
    return _SKILL_MCP_CACHE


def resolve_mcps_for_skills(skills: list[str]) -> list[str]:
    """Derive required MCPs from agent skills via skill_mcp_map.json.

    Only returns MCPs that are:
    - Listed in preferred_mcps for the skill
    - Marked as auto_attach: true
    - Available in the runtime catalog

    Returns sorted, deduplicated list of MCP names.
    """
    skill_map = _load_skill_mcp_map()
    registry = runtime_mcp_specs()
    mcps: set[str] = set()

    for skill_id in skills:
        entry = skill_map.get(skill_id)
        if not entry:
            continue
        if not entry.get("auto_attach", False):
            continue
        for mcp_name in entry.get("preferred_mcps", []):
            if mcp_name in registry:
                mcps.add(mcp_name)

    return sorted(mcps)


def suggest_mcps_for_task(
    task_text: str,
    agent_skills: list[str],
) -> dict[str, Any]:
    """Suggest MCPs for a task based on agent skills and task keywords.

    Returns: {relevant_skills, attached_mcps, discovery_suggestions}
    """
    skill_map = _load_skill_mcp_map()
    registry = runtime_mcp_specs()
    task_lower = task_text.lower()

    relevant_skills: list[str] = []
    attached_mcps: set[str] = set()

    for skill_id in agent_skills:
        entry = skill_map.get(skill_id)
        if not entry:
            continue
        keywords = entry.get("task_keywords", [])
        if any(kw in task_lower for kw in keywords):
            relevant_skills.append(skill_id)
            for mcp in entry.get("preferred_mcps", []):
                if mcp in registry:
                    attached_mcps.add(mcp)

    return {
        "relevant_skills": relevant_skills,
        "attached_mcps": sorted(attached_mcps),
        "native_available": True,
        "discovery_suggestions": [],
    }
