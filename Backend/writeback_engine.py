"""writeback_engine.py — Session-to-Canonical writeback pipeline.

Extracts deltas from agent workspace artifacts (MEMORY.md, CONTEXT_BRIDGE.md,
SOUL.md) and merges them into the canonical store (~/.bridge/agents/{id}/).

Triggered by:
- Agent re-registration (/register)
- Agent stop/restart
- System shutdown
- Distillation daemon
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

import canonical_store
from persistence_utils import find_agent_memory_path, resolve_agent_cli_layout


# ---------------------------------------------------------------------------
# Memory delta extraction
# ---------------------------------------------------------------------------

def _extract_memory_sections(memory_md: str) -> dict[str, list[str]]:
    """Parse MEMORY.md into sections with their entries.

    Returns dict: section_name → list of entry strings.
    """
    sections: dict[str, list[str]] = {}
    current_section = ""
    current_entries: list[str] = []

    for line in memory_md.splitlines():
        if line.startswith("## "):
            if current_section and current_entries:
                sections[current_section] = current_entries
            current_section = line[3:].strip()
            current_entries = []
        elif line.startswith("- ") and current_section:
            current_entries.append(line[2:].strip())
        elif line.startswith("  ") and current_entries:
            # Continuation of previous entry
            current_entries[-1] += " " + line.strip()

    if current_section and current_entries:
        sections[current_section] = current_entries

    return sections


def _entry_fingerprint(text: str) -> str:
    """Short hash for deduplication."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def _diff_against_canonical(
    sections: dict[str, list[str]],
    canonical_entries: list[dict],
) -> list[dict]:
    """Find entries in MEMORY.md that are NOT in canonical memory.jsonl."""
    existing_fingerprints = set()
    for entry in canonical_entries:
        fp = _entry_fingerprint(entry.get("value", ""))
        existing_fingerprints.add(fp)

    new_entries: list[dict] = []
    for section, entries in sections.items():
        for entry_text in entries:
            fp = _entry_fingerprint(entry_text)
            if fp not in existing_fingerprints:
                if _validate_entry(entry_text):
                    new_entries.append({
                        "section": section,
                        "key": entry_text[:60].strip(),
                        "value": entry_text,
                        "source": "writeback",
                        "fingerprint": fp,
                    })
                    existing_fingerprints.add(fp)

    return new_entries


def _validate_entry(text: str) -> bool:
    """Validate a memory entry: not empty, not too long, not trivial."""
    text = text.strip()
    if not text or len(text) < 5:
        return False
    if len(text) > 2000:
        return False
    # Skip template/placeholder entries
    if text.startswith("(") and text.endswith(")"):
        return False
    return True


# ---------------------------------------------------------------------------
# Writeback functions
# ---------------------------------------------------------------------------

def writeback_context_bridge(agent_id: str, agent_home: str) -> bool:
    """Copy workspace CONTEXT_BRIDGE.md → canonical store.

    Returns True if writeback occurred.
    """
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    workspace = layout.get("workspace", "")
    if not workspace:
        return False

    cb_path = os.path.join(workspace, "CONTEXT_BRIDGE.md")
    if not os.path.isfile(cb_path):
        return False

    try:
        with open(cb_path, encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return False
        canonical_store.write_canonical_context_bridge(agent_id, content)
        return True
    except OSError:
        return False


def writeback_soul(agent_id: str, agent_home: str) -> bool:
    """Copy workspace SOUL.md → canonical if newer/larger.

    Only overwrites canonical if workspace version is newer.
    Returns True if writeback occurred.
    """
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    workspace = layout.get("workspace", "")
    if not workspace:
        return False

    ws_soul = os.path.join(workspace, "SOUL.md")
    if not os.path.isfile(ws_soul):
        return False

    canonical_soul = canonical_store.read_canonical_soul(agent_id)
    try:
        with open(ws_soul, encoding="utf-8") as f:
            ws_content = f.read().strip()
    except OSError:
        return False

    if not ws_content:
        return False

    # Only overwrite if workspace is different and non-trivial
    if canonical_soul and _entry_fingerprint(ws_content) == _entry_fingerprint(canonical_soul):
        return False

    # Workspace version wins (it's the one agents actively modify)
    canonical_store.write_canonical_soul(agent_id, ws_content)
    return True


def writeback_memory_delta(
    agent_id: str,
    agent_home: str,
    config_dir: str = "",
) -> int:
    """Extract new entries from MEMORY.md and append to canonical memory.jsonl.

    Returns count of new entries appended.
    """
    memory_path = find_agent_memory_path(agent_id, agent_home, config_dir)
    if not memory_path or not os.path.isfile(memory_path):
        return 0

    try:
        with open(memory_path, encoding="utf-8") as f:
            memory_md = f.read()
    except OSError:
        return 0

    if not memory_md.strip():
        return 0

    sections = _extract_memory_sections(memory_md)
    if not sections:
        return 0

    canonical_entries = canonical_store.read_canonical_memory(agent_id)
    new_entries = _diff_against_canonical(sections, canonical_entries)

    for entry in new_entries:
        canonical_store.append_canonical_memory(agent_id, entry)

    return len(new_entries)


def full_writeback(
    agent_id: str,
    agent_home: str,
    config_dir: str = "",
) -> dict:
    """Execute all writebacks for an agent. Returns summary.

    Safe to call frequently — deduplication prevents duplicate entries.
    """
    canonical_store.init_canonical_dir(agent_id)

    summary: dict = {
        "agent_id": agent_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "context_bridge": False,
        "soul": False,
        "memory_new_entries": 0,
    }

    try:
        summary["context_bridge"] = writeback_context_bridge(agent_id, agent_home)
    except Exception as exc:
        summary["context_bridge_error"] = str(exc)

    try:
        summary["soul"] = writeback_soul(agent_id, agent_home)
    except Exception as exc:
        summary["soul_error"] = str(exc)

    try:
        summary["memory_new_entries"] = writeback_memory_delta(agent_id, agent_home, config_dir)
    except Exception as exc:
        summary["memory_error"] = str(exc)

    canonical_store.read_meta(agent_id)  # Ensure meta exists
    canonical_store._update_meta(agent_id, last_writeback=summary["ts"])

    return summary
