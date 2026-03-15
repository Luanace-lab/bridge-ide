#!/usr/bin/env python3
"""
Knowledge Engine — Obsidian-inspired knowledge backend for Bridge IDE.

Provides vault-based knowledge management for AI agents. Each agent can
read, write, search, and organize markdown notes with YAML frontmatter.

Vault structure:
    BRIDGE/Knowledge/
    ├── Agents/{agent_id}/
    │   ├── SOUL.md
    │   ├── GROW.md
    │   ├── SKILLS.md
    │   └── DAILY/YYYY-MM-DD.md
    ├── Tasks/
    ├── Decisions/
    └── Shared/

No external dependencies beyond Python stdlib + pyyaml (optional).
"""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_VAULT_DIR = os.environ.get(
    "BRIDGE_KNOWLEDGE_VAULT",
    str(Path(__file__).resolve().parent.parent / "Knowledge"),
)

_MAX_NOTE_SIZE = 1_000_000  # 1 MB
_MAX_SEARCH_RESULTS = 50
_VAULT_LOCK = threading.Lock()
_SYNCABLE_SCOPE_DIRS = {
    "Agents": "agent",
    "Users": "user",
    "Projects": "project",
    "Teams": "team",
}


def _atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content atomically via temp file + os.replace()."""
    import tempfile
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# YAML frontmatter parsing (stdlib fallback if pyyaml not available)
try:
    import yaml as _yaml

    def _parse_yaml(text: str) -> dict[str, Any]:
        return _yaml.safe_load(text) or {}

    def _dump_yaml(data: dict[str, Any]) -> str:
        return _yaml.dump(data, default_flow_style=False, allow_unicode=True).rstrip()

except ImportError:
    _yaml = None  # type: ignore[assignment]

    def _parse_yaml(text: str) -> dict[str, Any]:
        """Minimal YAML parser for simple key: value frontmatter."""
        result: dict[str, Any] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                val = val.strip()
                # Handle simple lists: [a, b, c]
                if val.startswith("[") and val.endswith("]"):
                    val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]  # type: ignore[assignment]
                elif val.lower() in ("true", "false"):
                    val = val.lower() == "true"  # type: ignore[assignment]
                elif val.isdigit():
                    val = int(val)  # type: ignore[assignment]
                else:
                    val = val.strip("'\"")
                result[key.strip()] = val
        return result

    def _dump_yaml(data: dict[str, Any]) -> str:
        lines = []
        for k, v in data.items():
            if isinstance(v, list):
                lines.append(f"{k}: [{', '.join(str(i) for i in v)}]")
            elif isinstance(v, bool):
                lines.append(f"{k}: {'true' if v else 'false'}")
            else:
                lines.append(f"{k}: {v}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Vault helpers
# ---------------------------------------------------------------------------


def _vault_path() -> Path:
    """Return vault root, creating it if needed."""
    p = Path(_VAULT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_note_path(note_path: str) -> Path:
    """Resolve a note path relative to vault root. Prevents path traversal."""
    vault = _vault_path()
    resolved = (vault / note_path).resolve()
    try:
        resolved.relative_to(vault.resolve())
    except ValueError as exc:
        raise ValueError(f"Path traversal blocked: {note_path}") from exc
    if resolved.suffix != ".md":
        resolved = resolved.with_suffix(".md")
    return resolved


def _resolve_directory_path(directory: str) -> Path:
    """Resolve a directory below the vault root. Prevents path traversal."""
    vault = _vault_path()
    if not directory:
        return vault
    resolved = (vault / directory).resolve()
    try:
        resolved.relative_to(vault.resolve())
    except ValueError as exc:
        raise ValueError(f"Path traversal blocked: {directory}") from exc
    return resolved


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split markdown content into frontmatter dict and body text."""
    if not content.startswith("---"):
        return {}, content
    end = content.find("---", 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end].strip()
    body = content[end + 3:].lstrip("\n")
    return _parse_yaml(fm_text), body


def _join_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Join frontmatter dict and body into markdown content."""
    if not frontmatter:
        return body
    fm_text = _dump_yaml(frontmatter)
    return f"---\n{fm_text}\n---\n\n{body}"


def _semantic_memory_module():
    try:
        import semantic_memory
    except ImportError:
        return None
    return semantic_memory


def _note_scope(note_path: str) -> tuple[str, str]:
    normalized = note_path.replace("\\", "/").strip("/")
    parts = normalized.split("/")
    if len(parts) >= 2 and parts[0] in _SYNCABLE_SCOPE_DIRS:
        return _SYNCABLE_SCOPE_DIRS[parts[0]], parts[1]
    return "global", "global"


def _sync_note_to_semantic_memory(note_path: str, content: str) -> dict[str, Any] | None:
    semantic_memory = _semantic_memory_module()
    if semantic_memory is None:
        return None
    scope_type, scope_id = _note_scope(note_path)
    metadata = {
        "source": "knowledge_vault",
        "note_path": note_path,
    }
    return semantic_memory.index_scoped_text(
        scope_type,
        scope_id,
        content,
        metadata=metadata,
        document_id=note_path,
        replace_document=True,
    )


def _delete_note_from_semantic_memory(note_path: str) -> dict[str, Any] | None:
    semantic_memory = _semantic_memory_module()
    if semantic_memory is None:
        return None
    scope_type, scope_id = _note_scope(note_path)
    return semantic_memory.delete_document(scope_type, scope_id, note_path)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def read_note(note_path: str) -> dict[str, Any]:
    """Read a note and return frontmatter + body.

    Returns: {"path": str, "frontmatter": dict, "body": str, "exists": bool}
    """
    try:
        resolved = _resolve_note_path(note_path)
    except ValueError as exc:
        return {
            "path": note_path,
            "frontmatter": {},
            "body": "",
            "exists": False,
            "error": str(exc),
        }
    if not resolved.exists():
        return {"path": note_path, "frontmatter": {}, "body": "", "exists": False}

    content = resolved.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(content)
    return {"path": note_path, "frontmatter": fm, "body": body, "exists": True}


def write_note(
    note_path: str,
    body: str,
    frontmatter: dict[str, Any] | None = None,
    mode: str = "overwrite",
) -> dict[str, Any]:
    """Write or update a note.

    mode: "overwrite" (default), "append", "prepend"
    Returns: {"path": str, "ok": bool, "size": int}
    """
    try:
        resolved = _resolve_note_path(note_path)
    except ValueError as exc:
        return {"path": note_path, "ok": False, "error": str(exc)}
    resolved.parent.mkdir(parents=True, exist_ok=True)

    with _VAULT_LOCK:
        existing_fm: dict[str, Any] = {}
        existing_body = ""

        if resolved.exists() and mode != "overwrite":
            content = resolved.read_text(encoding="utf-8")
            existing_fm, existing_body = _split_frontmatter(content)

        # Merge frontmatter
        if frontmatter:
            existing_fm.update(frontmatter)

        # Update timestamp
        existing_fm["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if "created" not in existing_fm:
            existing_fm["created"] = existing_fm["updated"]

        # Apply body mode
        if mode == "append":
            final_body = existing_body + "\n" + body if existing_body else body
        elif mode == "prepend":
            final_body = body + "\n" + existing_body if existing_body else body
        else:
            final_body = body

        final_content = _join_frontmatter(existing_fm, final_body)

        if len(final_content.encode("utf-8")) > _MAX_NOTE_SIZE:
            return {"path": note_path, "ok": False, "error": "Note too large (max 1MB)"}

        _atomic_write_text(resolved, final_content)
        semantic_sync = _sync_note_to_semantic_memory(str(resolved.relative_to(_vault_path())), final_content)
        return {"path": note_path, "ok": True, "size": len(final_content), "semantic_sync": semantic_sync}


def delete_note(note_path: str) -> dict[str, Any]:
    """Delete a note. Returns {"path": str, "ok": bool}."""
    try:
        resolved = _resolve_note_path(note_path)
    except ValueError as exc:
        return {"path": note_path, "ok": False, "error": str(exc)}
    if not resolved.exists():
        return {"path": note_path, "ok": False, "error": "Note not found"}
    rel_path = str(resolved.relative_to(_vault_path()))
    with _VAULT_LOCK:
        resolved.unlink()
    semantic_sync = _delete_note_from_semantic_memory(rel_path)
    return {"path": note_path, "ok": True, "semantic_sync": semantic_sync}


def list_notes(
    directory: str = "",
    pattern: str = "*.md",
    recursive: bool = True,
) -> dict[str, Any]:
    """List notes in a directory with optional glob filter.

    Returns: {"directory": str, "notes": [{"path": str, "frontmatter": dict}], "count": int}
    """
    try:
        search_dir = _resolve_directory_path(directory)
    except ValueError as exc:
        return {"directory": directory, "notes": [], "count": 0, "error": str(exc)}
    vault = _vault_path()
    if not search_dir.is_dir():
        return {"directory": directory, "notes": [], "count": 0}

    notes: list[dict[str, Any]] = []
    glob_method = search_dir.rglob if recursive else search_dir.glob
    for f in sorted(glob_method(pattern)):
        if not f.is_file():
            continue
        rel = str(f.relative_to(vault))
        try:
            content = f.read_text(encoding="utf-8")
            fm, _ = _split_frontmatter(content)
        except Exception:
            fm = {}
        notes.append({"path": rel, "frontmatter": fm})
        if len(notes) >= _MAX_SEARCH_RESULTS:
            break

    return {"directory": directory, "notes": notes, "count": len(notes)}


def search_notes(
    query: str,
    directory: str = "",
    frontmatter_filter: dict[str, Any] | None = None,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    """Full-text search across vault notes.

    Optional frontmatter_filter: {"status": "open", "tags": "backend"} — all must match.
    Returns: {"query": str, "results": [{"path": str, "matches": [str], "frontmatter": dict}], "count": int}
    """
    try:
        search_dir = _resolve_directory_path(directory)
    except ValueError as exc:
        return {"query": query, "results": [], "count": 0, "error": str(exc)}
    vault = _vault_path()
    if not search_dir.is_dir():
        return {"query": query, "results": [], "count": 0}

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query, flags)
    except re.error:
        pattern = re.compile(re.escape(query), flags)

    results: list[dict[str, Any]] = []
    for f in sorted(search_dir.rglob("*.md")):
        if not f.is_file():
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue

        fm, body = _split_frontmatter(content)

        # Frontmatter filter
        if frontmatter_filter:
            skip = False
            for fk, fv in frontmatter_filter.items():
                fm_val = fm.get(fk)
                if fm_val is None:
                    skip = True
                    break
                # Handle list membership (e.g. tags contains "backend")
                if isinstance(fm_val, list):
                    if str(fv) not in [str(x) for x in fm_val]:
                        skip = True
                        break
                elif str(fm_val).lower() != str(fv).lower():
                    skip = True
                    break
            if skip:
                continue

        # Text search
        matches: list[str] = []
        for line in body.splitlines():
            if pattern.search(line):
                matches.append(line.strip()[:200])

        if matches or (frontmatter_filter and not query):
            rel = str(f.relative_to(vault))
            results.append({
                "path": rel,
                "matches": matches[:5],
                "frontmatter": fm,
            })
            if len(results) >= _MAX_SEARCH_RESULTS:
                break

    return {"query": query, "results": results, "count": len(results)}


def manage_frontmatter(
    note_path: str,
    action: str = "get",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get, set, or delete frontmatter fields.

    action: "get" | "set" | "delete"
    data: for "set" — fields to set; for "delete" — keys to remove (values ignored)
    Returns: {"path": str, "frontmatter": dict, "ok": bool}
    """
    try:
        resolved = _resolve_note_path(note_path)
    except ValueError as exc:
        return {"path": note_path, "frontmatter": {}, "ok": False, "error": str(exc)}
    if not resolved.exists():
        return {"path": note_path, "frontmatter": {}, "ok": False, "error": "Note not found"}

    with _VAULT_LOCK:
        content = resolved.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(content)

        if action == "get":
            return {"path": note_path, "frontmatter": fm, "ok": True}

        if action == "set" and data:
            fm.update(data)
            fm["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            final_content = _join_frontmatter(fm, body)
            _atomic_write_text(resolved, final_content)
            semantic_sync = _sync_note_to_semantic_memory(str(resolved.relative_to(_vault_path())), final_content)
            return {"path": note_path, "frontmatter": fm, "ok": True, "semantic_sync": semantic_sync}

        if action == "delete" and data:
            for key in data:
                fm.pop(key, None)
            fm["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            final_content = _join_frontmatter(fm, body)
            _atomic_write_text(resolved, final_content)
            semantic_sync = _sync_note_to_semantic_memory(str(resolved.relative_to(_vault_path())), final_content)
            return {"path": note_path, "frontmatter": fm, "ok": True, "semantic_sync": semantic_sync}

        return {"path": note_path, "frontmatter": fm, "ok": False, "error": f"Invalid action: {action}"}


def search_replace(
    note_path: str,
    search: str,
    replace: str,
    regex: bool = False,
) -> dict[str, Any]:
    """Search and replace in a note's body.

    Returns: {"path": str, "ok": bool, "replacements": int}
    """
    try:
        resolved = _resolve_note_path(note_path)
    except ValueError as exc:
        return {"path": note_path, "ok": False, "error": str(exc)}
    if not resolved.exists():
        return {"path": note_path, "ok": False, "error": "Note not found"}

    with _VAULT_LOCK:
        content = resolved.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(content)

        if regex:
            new_body, count = re.subn(search, replace, body)
        else:
            count = body.count(search)
            new_body = body.replace(search, replace)

        if count > 0:
            fm["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            final_content = _join_frontmatter(fm, new_body)
            _atomic_write_text(resolved, final_content)
            semantic_sync = _sync_note_to_semantic_memory(str(resolved.relative_to(_vault_path())), final_content)
        else:
            semantic_sync = None

        return {"path": note_path, "ok": True, "replacements": count, "semantic_sync": semantic_sync}


# ---------------------------------------------------------------------------
# Vault initialization — create default structure
# ---------------------------------------------------------------------------


def init_vault() -> dict[str, Any]:
    """Initialize vault with default directory structure."""
    vault = _vault_path()
    dirs = [
        "Agents",
        "Users",
        "Projects",
        "Teams",
        "Tasks",
        "Decisions",
        "Shared",
    ]
    created = []
    for d in dirs:
        p = vault / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(d)
    return {"vault": str(vault), "created_dirs": created, "ok": True}


def init_agent_vault(agent_id: str) -> dict[str, Any]:
    """Initialize per-agent knowledge structure."""
    vault = _vault_path()
    agent_dir = vault / "Agents" / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    daily_dir = agent_dir / "DAILY"
    daily_dir.mkdir(exist_ok=True)

    # Create default files if they don't exist
    defaults = {
        "SOUL.md": f"---\nagent: {agent_id}\ntype: identity\n---\n\n# {agent_id} — Identity\n",
        "GROW.md": f"---\nagent: {agent_id}\ntype: learnings\n---\n\n# {agent_id} — Learnings\n",
        "SKILLS.md": f"---\nagent: {agent_id}\ntype: skills\n---\n\n# {agent_id} — Skills\n",
    }
    created_files = []
    for name, content in defaults.items():
        fp = agent_dir / name
        if not fp.exists():
            _atomic_write_text(fp, content)
            created_files.append(name)

    return {
        "agent_id": agent_id,
        "path": str(agent_dir.relative_to(vault)),
        "created_files": created_files,
        "ok": True,
    }


def init_user_vault(user_id: str) -> dict[str, Any]:
    """Initialize per-user knowledge structure."""
    vault = _vault_path()
    user_dir = vault / "Users" / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    daily_dir = user_dir / "DAILY"
    daily_dir.mkdir(exist_ok=True)

    profile = user_dir / "USER.md"
    created_files = []
    if not profile.exists():
        _atomic_write_text(
            profile,
            (
                f"---\nuser: {user_id}\ntype: profile\n---\n\n"
                f"# {user_id} — User Profile\n"
            ),
        )
        created_files.append("USER.md")

    return {
        "user_id": user_id,
        "path": str(user_dir.relative_to(vault)),
        "created_files": created_files,
        "ok": True,
    }


def init_project_vault(project_id: str) -> dict[str, Any]:
    """Initialize per-project knowledge structure."""
    vault = _vault_path()
    project_dir = vault / "Projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    project_note = project_dir / "PROJECT.md"
    created_files = []
    if not project_note.exists():
        _atomic_write_text(
            project_note,
            (
                f"---\nproject: {project_id}\ntype: project\n---\n\n"
                f"# {project_id} — Project\n"
            ),
        )
        created_files.append("PROJECT.md")

    return {
        "project_id": project_id,
        "path": str(project_dir.relative_to(vault)),
        "created_files": created_files,
        "ok": True,
    }


def init_team_vault(team_id: str) -> dict[str, Any]:
    """Initialize per-team knowledge structure."""
    vault = _vault_path()
    team_dir = vault / "Teams" / team_id
    team_dir.mkdir(parents=True, exist_ok=True)

    team_note = team_dir / "TEAM.md"
    created_files = []
    if not team_note.exists():
        _atomic_write_text(
            team_note,
            (
                f"---\nteam: {team_id}\ntype: team\n---\n\n"
                f"# {team_id} — Team\n"
            ),
        )
        created_files.append("TEAM.md")

    return {
        "team_id": team_id,
        "path": str(team_dir.relative_to(vault)),
        "created_files": created_files,
        "ok": True,
    }


# ---------------------------------------------------------------------------
# Vault info
# ---------------------------------------------------------------------------


def vault_info() -> dict[str, Any]:
    """Return vault metadata: path, note count, size."""
    vault = _vault_path()
    note_count = 0
    total_size = 0
    for f in vault.rglob("*.md"):
        if f.is_file():
            note_count += 1
            total_size += f.stat().st_size
    return {
        "vault_path": str(vault),
        "note_count": note_count,
        "total_size_bytes": total_size,
        "ok": True,
    }
