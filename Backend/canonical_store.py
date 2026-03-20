"""canonical_store.py — Canonical Agent Store at ~/.bridge/agents/{id}/

Single Source of Truth for agent identity, soul, memory, and context.
All writes are atomic (tempfile + os.replace). Memory appends use fcntl.flock().

Directory layout per agent:
    ~/.bridge/agents/{agent_id}/
    ├── identity.json        # From team.json (id, role, engine, level, skills)
    ├── soul.md              # One canonical SOUL.md
    ├── .soul_meta.json      # Parsed SoulConfig for fast access
    ├── .soul_proposals.jsonl # Growth proposals (pending/approved)
    ├── memory.jsonl          # Backend-owned append-only memory
    ├── context_bridge.md     # Last working context
    └── meta.json             # Timestamps, session info
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

CANONICAL_BASE = Path.home() / ".bridge" / "agents"

_MAX_MEMORY_ENTRIES = 500


# ---------------------------------------------------------------------------
# Directory management
# ---------------------------------------------------------------------------

def canonical_dir(agent_id: str) -> Path:
    """Return canonical directory for an agent."""
    return CANONICAL_BASE / agent_id


def init_canonical_dir(agent_id: str) -> Path:
    """Create canonical directory. Idempotent."""
    d = canonical_dir(agent_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically via tempfile + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Identity (from team.json — overwritten on every sync)
# ---------------------------------------------------------------------------

def sync_identity_from_team(agent_id: str, team_config: dict) -> dict:
    """Extract agent identity from team.json and write identity.json.

    Returns the identity dict. Always overwrites (identity is team-owned).
    """
    agents = team_config.get("agents", [])
    agent = None
    for a in agents:
        if a.get("id") == agent_id:
            agent = a
            break
    if not agent:
        return {}

    identity = {
        "id": agent.get("id", ""),
        "name": agent.get("name", ""),
        "role": agent.get("role", ""),
        "level": agent.get("level", 3),
        "engine": agent.get("engine", "claude"),
        "model": agent.get("model", ""),
        "skills": agent.get("skills", []),
        "reports_to": agent.get("reports_to", ""),
        "description": agent.get("description", ""),
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    d = init_canonical_dir(agent_id)
    _atomic_write(d / "identity.json", json.dumps(identity, indent=2, ensure_ascii=False) + "\n")
    _update_meta(agent_id, identity_synced=identity["synced_at"])
    return identity


def read_identity(agent_id: str) -> dict:
    """Read identity.json. Returns empty dict if not found."""
    path = canonical_dir(agent_id) / "identity.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Soul (persistent, write-once unless approved update)
# ---------------------------------------------------------------------------

def read_canonical_soul(agent_id: str) -> str | None:
    """Read soul.md from canonical dir. Returns None if not found."""
    path = canonical_dir(agent_id) / "soul.md"
    try:
        content = path.read_text(encoding="utf-8").strip()
        return content if content else None
    except OSError:
        return None


def write_canonical_soul(agent_id: str, content: str) -> None:
    """Atomic write soul.md to canonical dir."""
    d = init_canonical_dir(agent_id)
    _atomic_write(d / "soul.md", content)
    _update_meta(agent_id, soul_updated=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# ---------------------------------------------------------------------------
# Memory (append-only jsonl, backend-owned)
# ---------------------------------------------------------------------------

def read_canonical_memory(agent_id: str) -> list[dict]:
    """Read memory.jsonl. Returns list of entries (newest last)."""
    path = canonical_dir(agent_id) / "memory.jsonl"
    entries: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return entries


def append_canonical_memory(agent_id: str, entry: dict) -> None:
    """Append single entry to memory.jsonl. Thread-safe via flock."""
    d = init_canonical_dir(agent_id)
    path = d / "memory.jsonl"

    if "ts" not in entry:
        entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if "agent_id" not in entry:
        entry["agent_id"] = agent_id

    line = json.dumps(entry, ensure_ascii=False) + "\n"

    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode("utf-8"))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    _rotate_memory_if_needed(agent_id)


def _rotate_memory_if_needed(agent_id: str) -> None:
    """Keep memory.jsonl under _MAX_MEMORY_ENTRIES."""
    entries = read_canonical_memory(agent_id)
    if len(entries) <= _MAX_MEMORY_ENTRIES:
        return
    # Keep newest entries
    trimmed = entries[-_MAX_MEMORY_ENTRIES:]
    path = canonical_dir(agent_id) / "memory.jsonl"
    content = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in trimmed)
    _atomic_write(path, content)


def get_memory_stats(agent_id: str) -> dict:
    """Return memory statistics."""
    entries = read_canonical_memory(agent_id)
    if not entries:
        return {"count": 0, "oldest": None, "newest": None, "sections": []}
    sections = list(set(e.get("section", "") for e in entries if e.get("section")))
    return {
        "count": len(entries),
        "oldest": entries[0].get("ts"),
        "newest": entries[-1].get("ts"),
        "sections": sorted(sections),
    }


# ---------------------------------------------------------------------------
# Context Bridge
# ---------------------------------------------------------------------------

def write_canonical_context_bridge(agent_id: str, content: str) -> None:
    """Atomic write context_bridge.md."""
    d = init_canonical_dir(agent_id)
    _atomic_write(d / "context_bridge.md", content)
    _update_meta(agent_id, context_bridge_updated=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def read_canonical_context_bridge(agent_id: str) -> str | None:
    """Read context_bridge.md from canonical dir."""
    path = canonical_dir(agent_id) / "context_bridge.md"
    try:
        content = path.read_text(encoding="utf-8").strip()
        return content if content else None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

def _update_meta(agent_id: str, **kwargs: Any) -> None:
    """Update meta.json with provided fields."""
    d = init_canonical_dir(agent_id)
    path = d / "meta.json"
    meta: dict[str, Any] = {}
    try:
        with open(path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    meta["agent_id"] = agent_id
    meta.update(kwargs)
    meta["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic_write(path, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


def read_meta(agent_id: str) -> dict:
    """Read meta.json."""
    path = canonical_dir(agent_id) / "meta.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

def list_canonical_agents() -> list[str]:
    """Return list of agent IDs that have canonical directories."""
    if not CANONICAL_BASE.is_dir():
        return []
    return sorted(d.name for d in CANONICAL_BASE.iterdir() if d.is_dir() and (d / "identity.json").is_file())


def canonical_store_summary() -> dict:
    """Return summary of canonical store state."""
    agents = list_canonical_agents()
    return {
        "base_dir": str(CANONICAL_BASE),
        "agent_count": len(agents),
        "agents": {
            aid: {
                "has_soul": (canonical_dir(aid) / "soul.md").is_file(),
                "has_memory": (canonical_dir(aid) / "memory.jsonl").is_file(),
                "has_context_bridge": (canonical_dir(aid) / "context_bridge.md").is_file(),
                "memory_stats": get_memory_stats(aid),
            }
            for aid in agents
        },
    }
