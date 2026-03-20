"""Legacy/canonical memory helpers extracted from server.py (Slice 09).

This module owns:
- legacy `.agent` memory migration helpers
- canonical knowledge note sync helpers
- memory scaffold/read/write/status helpers

Anti-circular-import strategy:
  Shared utilities are injected via init().
  This module NEVER imports from server.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


_ensure_parent_dir: Callable[[str], None] | None = None
_normalize_path_fn: Callable[[str, str], str] | None = None
_root_dir_fn: Callable[[], str] | None = None

MEMORY_LOCK = threading.Lock()

_AGENT_FILE_MAP: dict[str, str] = {
    "teamlead": "lead.md",
    "lead": "lead.md",
}


def init(
    *,
    ensure_parent_dir_fn: Callable[[str], None],
    normalize_path_fn: Callable[[str, str], str],
    root_dir_fn: Callable[[], str],
) -> None:
    """Bind injected shared utilities."""
    global _ensure_parent_dir, _normalize_path_fn, _root_dir_fn
    _ensure_parent_dir = ensure_parent_dir_fn
    _normalize_path_fn = normalize_path_fn
    _root_dir_fn = root_dir_fn


def _ensure_parent(path: str) -> None:
    if _ensure_parent_dir is None:
        raise RuntimeError("handlers.memory.init() not called: ensure_parent_dir_fn missing")
    _ensure_parent_dir(path)


def _normalize_project_path(raw_path: str) -> str:
    if _normalize_path_fn is None or _root_dir_fn is None:
        raise RuntimeError(
            "handlers.memory.init() not called: normalize_path_fn/root_dir_fn missing"
        )
    return _normalize_path_fn(raw_path, _root_dir_fn())


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path == "/memory/stats":
        agent_id = query.get("agent_id", [""])[0].strip()
        scope_type = query.get("scope_type", [""])[0].strip().lower()
        scope_id = query.get("scope_id", [""])[0].strip()
        if agent_id and (scope_type or scope_id):
            handler._respond(400, {"error": "use either agent_id or scope_type/scope_id, not both"})
            return True
        try:
            import semantic_memory

            if agent_id:
                stats = semantic_memory.get_stats(agent_id)
            else:
                if not scope_type:
                    handler._respond(
                        400,
                        {"error": "'agent_id' or 'scope_type' query parameter is required"},
                    )
                    return True
                stats = semantic_memory.get_scope_stats(scope_type, scope_id)
        except Exception as exc:
            handler._respond(500, {"error": f"stats failed: {exc}"})
            return True
        handler._respond(200, stats)
        return True

    if path == "/memory/status":
        raw_project_path = (query.get("project_path") or [None])[0]
        if not raw_project_path:
            handler._respond(400, {"error": "project_path query parameter is required"})
            return True
        project_path = _normalize_project_path(raw_project_path)
        if not os.path.isdir(project_path):
            handler._respond(400, {"error": f"project_path does not exist: {project_path}"})
            return True
        result = get_memory_status(project_path)
        agent_id = str((query.get("agent_id") or [""])[0]).strip()
        role = str((query.get("role") or ["senior"])[0]).strip() or "senior"
        if agent_id:
            try:
                import memory_constitution

                result["constitution"] = memory_constitution.memory_status(
                    agent_id,
                    role=role,
                    project_path=project_path,
                )
            except Exception as exc:
                result["constitution_error"] = str(exc)
        handler._respond(200, result)
        return True

    if path == "/memory/read":
        raw_project_path = (query.get("project_path") or [None])[0]
        if not raw_project_path:
            handler._respond(400, {"error": "project_path query parameter is required"})
            return True
        project_path = _normalize_project_path(raw_project_path)
        if not os.path.isdir(project_path):
            handler._respond(400, {"error": f"project_path does not exist: {project_path}"})
            return True
        agent_id = str((query.get("agent_id") or ["teamlead"])[0]).strip()
        raw_max_tokens = (query.get("max_tokens") or [600])[0]
        try:
            max_tokens = int(raw_max_tokens)
        except (ValueError, TypeError):
            max_tokens = 600
        max_tokens = max(200, min(max_tokens, 2000))
        handler._respond(200, read_agent_memory(project_path, agent_id, max_tokens))
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    if path == "/memory/index":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        agent_id = str(data.get("agent_id", "")).strip()
        scope_type = str(data.get("scope_type", "")).strip().lower()
        scope_id = str(data.get("scope_id", "")).strip()
        text = str(data.get("text", "")).strip()
        if not text:
            handler._respond(400, {"error": "'text' is required"})
            return True
        if agent_id and (scope_type or scope_id):
            handler._respond(400, {"error": "use either agent_id or scope_type/scope_id, not both"})
            return True
        if not agent_id and not scope_type:
            handler._respond(400, {"error": "'agent_id' or 'scope_type' is required"})
            return True
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        try:
            chunk_size = int(data.get("chunk_size", 500))
            chunk_overlap = int(data.get("chunk_overlap", 50))
        except (ValueError, TypeError):
            handler._respond(400, {"error": "chunk_size/chunk_overlap must be integers"})
            return True
        document_id = str(data.get("document_id", "")).strip()
        replace_document = bool(data.get("replace_document", bool(document_id)))
        try:
            import semantic_memory

            if agent_id:
                result = semantic_memory.index_text(
                    agent_id,
                    text,
                    metadata=metadata,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
            else:
                result = semantic_memory.index_scoped_text(
                    scope_type,
                    scope_id,
                    text,
                    metadata=metadata,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    document_id=document_id,
                    replace_document=replace_document,
                )
        except Exception as exc:
            handler._respond(500, {"error": f"indexing failed: {exc}"})
            return True
        handler._respond(200 if result.get("ok") else 400, result)
        return True

    if path == "/memory/search":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        agent_id = str(data.get("agent_id", "")).strip()
        scope_type = str(data.get("scope_type", "")).strip().lower()
        scope_id = str(data.get("scope_id", "")).strip()
        query = str(data.get("query", "")).strip()
        if not query:
            handler._respond(400, {"error": "'query' is required"})
            return True
        if agent_id and (scope_type or scope_id):
            handler._respond(400, {"error": "use either agent_id or scope_type/scope_id, not both"})
            return True
        if not agent_id and not scope_type:
            handler._respond(400, {"error": "'agent_id' or 'scope_type' is required"})
            return True
        try:
            top_k = min(int(data.get("top_k", 5)), 50)
            min_score = float(data.get("min_score", 0.3))
            alpha = float(data.get("alpha", 0.7))
        except (ValueError, TypeError):
            handler._respond(400, {"error": "top_k/min_score/alpha must be numeric"})
            return True
        try:
            import semantic_memory

            if agent_id:
                result = semantic_memory.search(
                    agent_id,
                    query,
                    top_k=top_k,
                    min_score=min_score,
                    alpha=alpha,
                )
            else:
                result = semantic_memory.search_scope(
                    scope_type,
                    scope_id,
                    query,
                    top_k=top_k,
                    min_score=min_score,
                    alpha=alpha,
                )
        except Exception as exc:
            handler._respond(500, {"error": f"search failed: {exc}"})
            return True
        handler._respond(200, result)
        return True

    if path == "/memory/delete":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        agent_id = str(data.get("agent_id", "")).strip()
        scope_type = str(data.get("scope_type", "")).strip().lower()
        scope_id = str(data.get("scope_id", "")).strip()
        document_id = str(data.get("document_id", "")).strip()
        if not document_id:
            handler._respond(400, {"error": "'document_id' is required"})
            return True
        if agent_id and (scope_type or scope_id):
            handler._respond(400, {"error": "use either agent_id or scope_type/scope_id, not both"})
            return True
        if not agent_id and not scope_type:
            handler._respond(400, {"error": "'agent_id' or 'scope_type' is required"})
            return True
        try:
            import semantic_memory

            if agent_id:
                result = semantic_memory.delete_document("agent", agent_id, document_id)
            else:
                result = semantic_memory.delete_document(scope_type, scope_id, document_id)
        except Exception as exc:
            handler._respond(500, {"error": f"delete failed: {exc}"})
            return True
        handler._respond(200, result)
        return True

    if path == "/memory/scaffold":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True
        raw_project_path = data.get("project_path")
        if not raw_project_path:
            handler._respond(400, {"error": "project_path is required"})
            return True
        project_path = _normalize_project_path(raw_project_path)
        if not os.path.isdir(project_path):
            handler._respond(400, {"error": f"project_path does not exist: {project_path}"})
            return True
        handler._respond(201, scaffold_agent_memory(project_path))
        return True

    if path == "/memory/write":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True
        raw_project_path = data.get("project_path")
        agent_id = str(data.get("agent_id", "")).strip()
        category = str(data.get("category", "")).strip()
        content = str(data.get("content", ""))
        mode = str(data.get("mode", "append")).strip()
        if not raw_project_path or not agent_id or not category:
            handler._respond(
                400,
                {"error": "project_path, agent_id, and category are required"},
            )
            return True
        project_path = _normalize_project_path(raw_project_path)
        if not os.path.isdir(project_path):
            handler._respond(400, {"error": f"project_path does not exist: {project_path}"})
            return True
        if mode not in ("append", "replace"):
            handler._respond(400, {"error": "mode must be 'append' or 'replace'"})
            return True
        result = write_agent_memory(project_path, agent_id, category, content, mode)
        if "error" in result:
            handler._respond(400, result)
            return True
        handler._respond(201, result)
        return True

    if path == "/memory/episode":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True
        raw_project_path = data.get("project_path")
        agent_id = str(data.get("agent_id", "")).strip()
        summary = str(data.get("summary", "")).strip()
        task = str(data.get("task", "unknown")).strip()
        metadata = data.get("metadata")
        if not raw_project_path or not agent_id or not summary:
            handler._respond(
                400,
                {"error": "project_path, agent_id, and summary are required"},
            )
            return True
        project_path = _normalize_project_path(raw_project_path)
        if not os.path.isdir(project_path):
            handler._respond(400, {"error": f"project_path does not exist: {project_path}"})
            return True
        result = write_episode(
            project_path,
            agent_id,
            summary,
            task,
            metadata if isinstance(metadata, dict) else None,
        )
        if "error" in result:
            handler._respond(400, result)
            return True
        handler._respond(201, result)
        return True

    if path == "/memory/migrate":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True
        raw_project_path = data.get("project_path")
        if not raw_project_path:
            handler._respond(400, {"error": "project_path is required"})
            return True
        project_path = _normalize_project_path(raw_project_path)
        if not os.path.isdir(project_path):
            handler._respond(400, {"error": f"project_path does not exist: {project_path}"})
            return True
        result = migrate_legacy_agent_memory(project_path)
        if "error" in result:
            handler._respond(400, result)
            return True
        handler._respond(200, result)
        return True

    return False


def _safe_knowledge_segment(value: str, fallback: str = "item") -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(value or "").strip())
    return safe or fallback


def _legacy_memory_project_scope(project_path: str) -> str:
    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(project_path)))
    base = os.path.basename(normalized) or "project"
    base_safe = re.sub(r"[^a-z0-9_-]", "-", base.lower()).strip("-") or "project"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
    return f"{base_safe}__{digest}"


def _legacy_memory_knowledge_info(project_path: str, agent_id: str, category: str) -> dict[str, Any]:
    project_scope = _legacy_memory_project_scope(project_path)
    agent_scope = _safe_knowledge_segment(agent_id.lower().strip(), "agent")
    info: dict[str, Any] = {
        "project_scope": project_scope,
        "agent_scope": agent_scope,
        "project_path": os.path.normpath(os.path.abspath(os.path.expanduser(project_path))),
        "category": category,
    }
    if category == "project":
        info["note_path"] = f"Projects/{project_scope}/PROJECT.md"
    elif category == "decisions":
        info["note_path"] = f"Projects/{project_scope}/DECISIONS.md"
    elif category == "glossary":
        info["note_path"] = f"Projects/{project_scope}/GLOSSARY.md"
    elif category == "runbook":
        info["note_path"] = f"Projects/{project_scope}/RUNBOOK.md"
    elif category == "agent_private":
        info["note_path"] = f"Agents/{agent_scope}/PROJECT_MEMORY/{project_scope}.md"
    return info


def _sync_legacy_memory_note(
    project_path: str,
    agent_id: str,
    category: str,
    content: str,
    mode: str = "append",
) -> dict[str, Any] | None:
    try:
        import knowledge_engine as ke
    except ImportError:
        return None

    info = _legacy_memory_knowledge_info(project_path, agent_id, category)
    note_path = str(info.get("note_path", "")).strip()
    if not note_path:
        return None

    ke.init_vault()
    ke.init_project_vault(info["project_scope"])
    if category == "agent_private":
        ke.init_agent_vault(info["agent_scope"])

    frontmatter = {
        "source": "legacy_agent_memory",
        "project_scope": info["project_scope"],
        "project_path": info["project_path"],
        "agent": info["agent_scope"],
        "category": category,
    }
    result = ke.write_note(note_path, content, frontmatter, mode=mode)
    return {
        **info,
        "note_path": note_path,
        "note_file": str(Path(ke._VAULT_DIR) / note_path),
        "result": result,
    }


def _sync_legacy_episode_note(
    project_path: str,
    agent_id: str,
    summary: str,
    task: str,
    episode_filename: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        import knowledge_engine as ke
    except ImportError:
        return None

    project_scope = _legacy_memory_project_scope(project_path)
    agent_scope = _safe_knowledge_segment(agent_id.lower().strip(), "agent")
    episode_name = _safe_knowledge_segment(
        f"{agent_scope}__{Path(episode_filename).name}",
        "episode.md",
    )
    note_path = f"Projects/{project_scope}/EPISODES/{episode_name}"

    ke.init_vault()
    ke.init_project_vault(project_scope)

    frontmatter = {
        "source": "legacy_episode",
        "project_scope": project_scope,
        "project_path": os.path.normpath(os.path.abspath(os.path.expanduser(project_path))),
        "agent": agent_scope,
        "task": task,
        "legacy_episode_file": episode_filename,
    }
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if key not in frontmatter and isinstance(value, (str, int, float, bool)):
                frontmatter[key] = value

    result = ke.write_note(note_path, summary, frontmatter, mode="overwrite")
    return {
        "project_scope": project_scope,
        "agent_scope": agent_scope,
        "note_path": note_path,
        "note_file": str(Path(ke._VAULT_DIR) / note_path),
        "result": result,
    }


def _legacy_shared_memory_defaults() -> dict[str, tuple[str, str]]:
    return {
        "PROJECT.md": ("project", "# Project Context"),
        "DECISIONS.md": ("decisions", "# Decisions"),
        "GLOSSARY.md": ("glossary", "# Glossary"),
        "RUNBOOK.md": ("runbook", "# Runbook"),
    }


def _legacy_agent_default_content(filename: str) -> str | None:
    return {
        "lead.md": "# TeamLead Context",
        "agent_a.md": "# Agent A Context",
        "agent_b.md": "# Agent B Context",
    }.get(filename)


def _legacy_episode_note_path(project_path: str, agent_id: str, episode_filename: str) -> str:
    project_scope = _legacy_memory_project_scope(project_path)
    agent_scope = _safe_knowledge_segment(agent_id.lower().strip(), "agent")
    episode_name = _safe_knowledge_segment(
        f"{agent_scope}__{Path(episode_filename).name}",
        "episode.md",
    )
    return f"Projects/{project_scope}/EPISODES/{episode_name}"


def _load_legacy_memory_candidates(project_path: str) -> dict[str, list[dict[str, Any]]]:
    base = Path(project_path) / ".agent"
    project_candidates: list[dict[str, Any]] = []
    agent_candidates: list[dict[str, Any]] = []
    episode_candidates: list[dict[str, Any]] = []

    project_dir = base / "project"
    for filename, (category, default_body) in _legacy_shared_memory_defaults().items():
        path = project_dir / filename
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not content or content == default_body:
            continue
        info = _legacy_memory_knowledge_info(project_path, "lead", category)
        project_candidates.append(
            {
                "category": category,
                "content": content,
                "source_file": str(path),
                "note_path": str(info.get("note_path", "")),
            }
        )

    agents_dir = base / "agents"
    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.md")):
            try:
                content = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            default_body = _legacy_agent_default_content(path.name)
            if not content or (default_body is not None and content == default_body):
                continue
            agent_id = {
                "lead.md": "lead",
                "agent_a.md": "agent_a",
                "agent_b.md": "agent_b",
            }.get(path.name, path.stem)
            info = _legacy_memory_knowledge_info(project_path, agent_id, "agent_private")
            agent_candidates.append(
                {
                    "agent_id": agent_id,
                    "category": "agent_private",
                    "content": content,
                    "source_file": str(path),
                    "note_path": str(info.get("note_path", "")),
                }
            )

    episodes_dir = base / "episodes"
    index_path = episodes_dir / "index.jsonl"
    if index_path.is_file():
        try:
            raw_lines = index_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            raw_lines = []
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            agent_id = str(entry.get("agent_id", "")).strip() or "agent"
            task = str(entry.get("task", "unknown")).strip() or "unknown"
            summary_file = str(entry.get("summary_file", "")).strip()
            if not summary_file:
                continue
            summary_path = episodes_dir / summary_file
            if summary_path.is_file():
                try:
                    summary = summary_path.read_text(encoding="utf-8").strip()
                except OSError:
                    summary = ""
            else:
                bullets = entry.get("summary_bullets", [])
                summary = "\n".join(str(item).strip() for item in bullets if str(item).strip())
            if not summary:
                continue
            metadata = {
                key: value
                for key, value in entry.items()
                if key not in {"agent_id", "task", "summary_file", "summary_bullets"}
            }
            episode_candidates.append(
                {
                    "agent_id": agent_id,
                    "task": task,
                    "summary": summary,
                    "summary_file": summary_file,
                    "source_file": str(summary_path),
                    "note_path": _legacy_episode_note_path(project_path, agent_id, summary_file),
                    "metadata": metadata,
                }
            )

    return {
        "project_notes": project_candidates,
        "agent_notes": agent_candidates,
        "episodes": episode_candidates,
    }


def migrate_legacy_agent_memory(project_path: str) -> dict[str, Any]:
    """Import existing legacy .agent data into canonical knowledge notes."""
    if not os.path.isdir(project_path):
        return {"error": f"project_path does not exist: {project_path}"}

    candidates = _load_legacy_memory_candidates(project_path)
    project_synced = 0
    agent_synced = 0
    episodes_synced = 0

    for item in candidates["project_notes"]:
        synced = _sync_legacy_memory_note(
            project_path,
            "lead",
            str(item["category"]),
            str(item["content"]),
            mode="replace",
        )
        if synced:
            project_synced += 1

    for item in candidates["agent_notes"]:
        synced = _sync_legacy_memory_note(
            project_path,
            str(item["agent_id"]),
            "agent_private",
            str(item["content"]),
            mode="replace",
        )
        if synced:
            agent_synced += 1

    for item in candidates["episodes"]:
        synced = _sync_legacy_episode_note(
            project_path,
            str(item["agent_id"]),
            str(item["summary"]),
            str(item["task"]),
            str(item["summary_file"]),
            item.get("metadata") if isinstance(item.get("metadata"), dict) else None,
        )
        if synced:
            episodes_synced += 1

    project_scope = _legacy_memory_project_scope(project_path)
    knowledge_sync = {
        "project_scope": project_scope,
        "legacy_candidates": (
            len(candidates["project_notes"])
            + len(candidates["agent_notes"])
            + len(candidates["episodes"])
        ),
    }
    try:
        import knowledge_engine as ke

        knowledge_sync["vault_path"] = ke._VAULT_DIR
    except ImportError:
        pass

    return {
        "ok": True,
        "project_notes_synced": project_synced,
        "agent_notes_synced": agent_synced,
        "episodes_synced": episodes_synced,
        "knowledge_sync": knowledge_sync,
    }


def _canonical_memory_note(
    note_path: str,
    *,
    default_body: str | None = None,
) -> tuple[str, str] | None:
    """Read a canonical knowledge note, skipping untouched default scaffolds."""
    try:
        import knowledge_engine as ke
    except ImportError:
        return None

    note = ke.read_note(note_path)
    if not note.get("exists"):
        return None

    body = str(note.get("body", "")).strip()
    if not body:
        return None
    if default_body is not None and body == default_body.strip():
        return None

    resolved = Path(ke._VAULT_DIR) / f"{note_path}.md"
    return body, str(resolved)


def _canonical_episode_entries(project_scope: str, limit: int = 5) -> tuple[list[str], list[str]]:
    """Load recent canonical episode notes for a project scope."""
    try:
        import knowledge_engine as ke
    except ImportError:
        return [], []

    listing = ke.list_notes(f"Projects/{project_scope}/EPISODES")
    notes = listing.get("notes", []) if isinstance(listing, dict) else []
    ranked: list[tuple[str, str, dict[str, Any], str]] = []
    for entry in notes:
        note_path = str(entry.get("path", "")).strip()
        if not note_path:
            continue
        note = ke.read_note(note_path)
        if not note.get("exists"):
            continue
        body = str(note.get("body", "")).strip()
        if not body:
            continue
        frontmatter = note.get("frontmatter", {}) if isinstance(note.get("frontmatter"), dict) else {}
        ts = str(frontmatter.get("updated") or frontmatter.get("created") or Path(note_path).stem)
        ranked.append((ts, note_path, frontmatter, body))

    ranked.sort(key=lambda item: item[0], reverse=True)

    episode_parts: list[str] = []
    files_read: list[str] = []
    for ts, note_path, frontmatter, body in ranked[:limit]:
        task = str(frontmatter.get("task") or Path(note_path).stem).strip()
        bullet_lines = [line.strip() for line in body.splitlines() if line.strip()]
        bullets = "\n".join(f"  - {line}" for line in bullet_lines[:5])
        entry = f"- [{ts}] {task}"
        if bullets:
            entry += "\n" + bullets
        episode_parts.append(entry)
        files_read.append(str(Path(ke._VAULT_DIR) / note_path))

    return episode_parts, files_read


def _resolve_agent_file(agent_id: str) -> str:
    """Map an agent_id to its private memory file name."""
    aid = agent_id.lower().strip()
    if aid in _AGENT_FILE_MAP:
        return _AGENT_FILE_MAP[aid]
    if aid == "a" or aid.endswith("_a"):
        return "agent_a.md"
    if aid == "b" or aid.endswith("_b"):
        return "agent_b.md"
    safe = re.sub(r"[^a-z0-9_-]", "_", aid)
    return f"{safe}.md"


def scaffold_agent_memory(project_path: str) -> dict[str, Any]:
    """Create the .agent/ directory structure if not present."""
    if not os.path.isdir(project_path):
        return {"error": f"project_path does not exist: {project_path}"}

    base = os.path.join(project_path, ".agent")
    dirs = [
        os.path.join(base, "project"),
        os.path.join(base, "agents"),
        os.path.join(base, "episodes"),
    ]
    files = {
        os.path.join(base, "project", "PROJECT.md"): "# Project Context\n",
        os.path.join(base, "project", "DECISIONS.md"): "# Decisions\n",
        os.path.join(base, "project", "GLOSSARY.md"): "# Glossary\n",
        os.path.join(base, "project", "RUNBOOK.md"): "# Runbook\n",
        os.path.join(base, "agents", "lead.md"): "# TeamLead Context\n",
        os.path.join(base, "agents", "agent_a.md"): "# Agent A Context\n",
        os.path.join(base, "agents", "agent_b.md"): "# Agent B Context\n",
        os.path.join(base, "episodes", "index.jsonl"): "",
    }

    created: list[str] = []
    already_exists: list[str] = []

    with MEMORY_LOCK:
        for directory in dirs:
            os.makedirs(directory, exist_ok=True)

        for file_path, default_content in files.items():
            if os.path.exists(file_path):
                already_exists.append(file_path)
            else:
                Path(file_path).write_text(default_content, encoding="utf-8")
                created.append(file_path)

    knowledge_sync = None
    try:
        import knowledge_engine as ke

        ke.init_vault()
        project_scope = _legacy_memory_project_scope(project_path)
        project_result = ke.init_project_vault(project_scope)
        knowledge_sync = {
            "project_scope": project_scope,
            "project": project_result,
            "vault_path": ke._VAULT_DIR,
        }
    except ImportError:
        knowledge_sync = None

    return {
        "ok": True,
        "base": base,
        "created": created,
        "already_exists": already_exists,
        "created_count": len(created),
        "existing_count": len(already_exists),
        "knowledge_sync": knowledge_sync,
    }


def read_agent_memory(project_path: str, agent_id: str, max_tokens: int = 600) -> dict[str, Any]:
    """Read shared + private context and recent episodes into a memory packet."""
    if not os.path.isdir(project_path):
        return {"error": f"project_path does not exist: {project_path}"}

    base = os.path.join(project_path, ".agent")
    project_scope = _legacy_memory_project_scope(project_path)
    agent_scope = _safe_knowledge_segment(agent_id.lower().strip(), "agent")
    files_read: list[str] = []
    sections: list[str] = []

    shared_files = [
        ("PROJECT.md", "Project Context", f"Projects/{project_scope}/PROJECT", f"# {project_scope} — Project"),
        ("DECISIONS.md", "Decisions", f"Projects/{project_scope}/DECISIONS", None),
        ("GLOSSARY.md", "Glossary", f"Projects/{project_scope}/GLOSSARY", None),
        ("RUNBOOK.md", "Runbook", f"Projects/{project_scope}/RUNBOOK", None),
    ]
    shared_parts: list[str] = []
    for filename, label, canonical_note, default_body in shared_files:
        canonical = _canonical_memory_note(canonical_note, default_body=default_body)
        if canonical:
            content, note_file = canonical
            shared_parts.append(content)
            files_read.append(note_file)
            continue
        file_path = os.path.join(base, "project", filename)
        if os.path.isfile(file_path):
            try:
                content = Path(file_path).read_text(encoding="utf-8").strip()
                if content and content not in (f"# {label}", f"# {label}\n"):
                    shared_parts.append(content)
                    files_read.append(file_path)
            except OSError:
                pass
    if shared_parts:
        sections.append("## Shared Context\n\n" + "\n\n---\n\n".join(shared_parts))

    canonical_private = _canonical_memory_note(f"Agents/{agent_scope}/PROJECT_MEMORY/{project_scope}")
    if canonical_private:
        content, note_file = canonical_private
        sections.append(f"## Agent Context ({agent_id})\n\n{content}")
        files_read.append(note_file)
    else:
        agent_file = _resolve_agent_file(agent_id)
        agent_path = os.path.join(base, "agents", agent_file)
        if os.path.isfile(agent_path):
            try:
                content = Path(agent_path).read_text(encoding="utf-8").strip()
                if content:
                    sections.append(f"## Agent Context ({agent_id})\n\n{content}")
                    files_read.append(agent_path)
            except OSError:
                pass

    canonical_episode_parts, canonical_episode_files = _canonical_episode_entries(project_scope)
    if canonical_episode_parts:
        sections.append("## Recent Episodes\n\n" + "\n".join(canonical_episode_parts))
        files_read.extend(canonical_episode_files)
    else:
        index_path = os.path.join(base, "episodes", "index.jsonl")
        if os.path.isfile(index_path):
            try:
                lines = Path(index_path).read_text(encoding="utf-8").strip().splitlines()
                recent = lines[-5:] if len(lines) > 5 else lines
                episode_parts: list[str] = []
                for line in recent:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = entry.get("timestamp", "?")
                    task = entry.get("task", "?")
                    bullets = entry.get("summary_bullets", [])
                    bullet_str = "\n".join(f"  - {b}" for b in bullets) if bullets else ""
                    episode_entry = f"- [{ts}] {task}"
                    if bullet_str:
                        episode_entry += "\n" + bullet_str
                    episode_parts.append(episode_entry)
                if episode_parts:
                    sections.append("## Recent Episodes\n\n" + "\n".join(episode_parts))
                    files_read.append(index_path)
            except OSError:
                pass

    packet = "\n\n".join(sections)
    words = packet.split()
    if len(words) > max_tokens:
        packet = " ".join(words[:max_tokens]) + "\n\n[...truncated]"

    return {
        "packet": packet,
        "files_read": files_read,
        "token_estimate": len(packet.split()),
        "knowledge_sync": {
            "project_scope": project_scope,
            "agent_scope": agent_scope,
        },
    }


def write_episode(
    project_path: str,
    agent_id: str,
    summary: str,
    task: str = "unknown",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write an episode summary file and append to index.jsonl."""
    if not os.path.isdir(project_path):
        return {"error": f"project_path does not exist: {project_path}"}

    base = os.path.join(project_path, ".agent", "episodes")
    os.makedirs(base, exist_ok=True)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    safe_task = re.sub(r"[^a-z0-9_-]", "_", task.lower().strip())[:40]
    summary_slug = re.sub(r"[^a-z0-9_-]", "_", summary.lower().strip()[:30])
    episode_filename = f"{date_str}__{safe_task}__{summary_slug}.md"
    episode_path = os.path.join(base, episode_filename)

    summary_lines = [line.strip() for line in summary.strip().splitlines() if line.strip()]
    summary_bullets = summary_lines[:5]

    index_entry: dict[str, Any] = {
        "timestamp": now.isoformat(),
        "agent_id": agent_id,
        "task": task,
        "summary_file": episode_filename,
        "summary_bullets": summary_bullets,
    }
    if metadata and isinstance(metadata, dict):
        for key, value in metadata.items():
            if key not in index_entry:
                index_entry[key] = value

    index_path = os.path.join(base, "index.jsonl")

    with MEMORY_LOCK:
        Path(episode_path).write_text(summary, encoding="utf-8")
        with open(index_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(index_entry, ensure_ascii=False) + "\n")

    knowledge_sync = _sync_legacy_episode_note(
        project_path,
        agent_id,
        summary,
        task,
        episode_filename,
        metadata if isinstance(metadata, dict) else None,
    )

    return {
        "ok": True,
        "episode_file": episode_path,
        "index_file": index_path,
        "knowledge_sync": knowledge_sync,
    }


def write_agent_memory(
    project_path: str,
    agent_id: str,
    category: str,
    content: str,
    mode: str = "append",
) -> dict[str, Any]:
    """Write content to a specific memory category."""
    if not os.path.isdir(project_path):
        return {"error": f"project_path does not exist: {project_path}"}

    if category == "episode":
        return write_episode(project_path, agent_id, content)

    base = os.path.join(project_path, ".agent")
    category_map = {
        "project": os.path.join(base, "project", "PROJECT.md"),
        "decisions": os.path.join(base, "project", "DECISIONS.md"),
        "glossary": os.path.join(base, "project", "GLOSSARY.md"),
        "runbook": os.path.join(base, "project", "RUNBOOK.md"),
        "agent_private": os.path.join(base, "agents", _resolve_agent_file(agent_id)),
    }

    if category not in category_map:
        return {"error": f"unknown category: {category}"}

    target = category_map[category]
    _ensure_parent(target)

    with MEMORY_LOCK:
        if mode == "replace":
            Path(target).write_text(content, encoding="utf-8")
            bytes_written = len(content.encode("utf-8"))
        else:
            separator = "\n" if os.path.exists(target) and os.path.getsize(target) > 0 else ""
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(separator + content)
                bytes_written = len((separator + content).encode("utf-8"))

    knowledge_sync = _sync_legacy_memory_note(project_path, agent_id, category, content, mode=mode)

    return {
        "ok": True,
        "file": target,
        "bytes_written": bytes_written,
        "knowledge_sync": knowledge_sync,
    }


def get_memory_status(project_path: str) -> dict[str, Any]:
    """Check .agent/ existence and list all files with size and mtime."""
    if not os.path.isdir(project_path):
        return {"error": f"project_path does not exist: {project_path}"}

    base = os.path.join(project_path, ".agent")
    if not os.path.isdir(base):
        return {
            "initialized": False,
            "base": base,
            "files": [],
            "episode_count": 0,
            "knowledge_sync": {
                "project_scope": _legacy_memory_project_scope(project_path),
            },
        }

    file_list: list[dict[str, Any]] = []
    for root, _dirs, filenames in os.walk(base):
        for filename in filenames:
            file_path = os.path.join(root, filename)
            try:
                stat = os.stat(file_path)
            except OSError:
                continue
            file_list.append(
                {
                    "path": file_path,
                    "relative": os.path.relpath(file_path, base),
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )

    index_path = os.path.join(base, "episodes", "index.jsonl")
    episode_count = 0
    if os.path.isfile(index_path):
        try:
            raw = Path(index_path).read_text(encoding="utf-8").strip()
            if raw:
                episode_count = len(raw.splitlines())
        except OSError:
            pass

    knowledge_sync = None
    try:
        import knowledge_engine as ke

        project_scope = _legacy_memory_project_scope(project_path)
        project_note = Path(ke._VAULT_DIR) / "Projects" / project_scope / "PROJECT.md"
        candidates = _load_legacy_memory_candidates(project_path)
        all_candidates = (
            candidates["project_notes"]
            + candidates["agent_notes"]
            + candidates["episodes"]
        )
        missing_targets = [
            item
            for item in all_candidates
            if item.get("note_path")
            and not (Path(ke._VAULT_DIR) / str(item["note_path"])).exists()
        ]
        knowledge_sync = {
            "project_scope": project_scope,
            "vault_path": ke._VAULT_DIR,
            "project_note_exists": project_note.exists(),
            "legacy_candidates": len(all_candidates),
            "migration_required": bool(missing_targets),
        }
    except ImportError:
        knowledge_sync = None

    return {
        "initialized": True,
        "base": base,
        "files": file_list,
        "file_count": len(file_list),
        "episode_count": episode_count,
        "knowledge_sync": knowledge_sync,
    }
