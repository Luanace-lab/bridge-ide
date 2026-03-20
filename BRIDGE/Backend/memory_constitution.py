"""Memory Constitution — Unified rules for persistence, retrieval, and precedence.

Defines:
- 3 Memory Classes (Agent Local, Shared Coordination, Durable Knowledge)
- Source Precedence (6-level priority for conflict resolution)
- Role Persistence Profiles (per-role retrieval weights and TTL)
- Unified Memory Retrieval (queries all classes with role-aware ranking)

This module does NOT replace the 4 existing memory systems.
It provides a unified query layer ON TOP of them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from persistence_utils import find_agent_memory_path

# ---------------------------------------------------------------------------
# Memory Classes
# ---------------------------------------------------------------------------

MEMORY_CLASS_AGENT_LOCAL = "agent_local"
MEMORY_CLASS_SHARED_COORDINATION = "shared_coordination"
MEMORY_CLASS_DURABLE_KNOWLEDGE = "durable_knowledge"

MEMORY_CLASSES = {
    MEMORY_CLASS_AGENT_LOCAL: {
        "description": "Agent-specific continuity: preferences, work patterns, local TODOs",
        "systems": ["memory_engine", "cli_memory"],
        "default_ttl_days": 90,
    },
    MEMORY_CLASS_SHARED_COORDINATION: {
        "description": "Team coordination: who does what, handoffs, blockers, decisions",
        "systems": ["shared_memory"],
        "default_ttl_days": 30,
    },
    MEMORY_CLASS_DURABLE_KNOWLEDGE: {
        "description": "Verified project facts: ADRs, API contracts, findings, artifacts",
        "systems": ["knowledge_engine"],
        "default_ttl_days": None,  # No expiry
    },
}

# Semantic Memory is a RETRIEVAL MECHANISM, not a class.
# It indexes content from all 3 classes.


# ---------------------------------------------------------------------------
# Source Precedence (conflict resolution)
# ---------------------------------------------------------------------------

# When multiple sources provide conflicting information,
# higher precedence wins. Lower number = higher priority.

SOURCE_PRECEDENCE = [
    {"level": 1, "source": "human_explicit", "description": "Explicit human instruction or override"},
    {"level": 2, "source": "cli_runtime", "description": "Current CLI session reality (files, logs, state)"},
    {"level": 3, "source": "project_team_decision", "description": "Active project/team decisions (shared coordination)"},
    {"level": 4, "source": "agent_local_memory", "description": "Agent's own persistent memory"},
    {"level": 5, "source": "durable_knowledge", "description": "Verified knowledge vault entries"},
    {"level": 6, "source": "semantic_recall", "description": "Semantic search results (booster, not truth)"},
]


def precedence_level(source: str) -> int:
    """Get precedence level for a source. Lower = higher priority."""
    for entry in SOURCE_PRECEDENCE:
        if entry["source"] == source:
            return entry["level"]
    return 99  # Unknown sources have lowest priority


# ---------------------------------------------------------------------------
# Role Persistence Profiles
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_ROLE_PROFILES_PATH = _CONFIG_DIR / "role_memory_profiles.json"

_DEFAULT_ROLE_PROFILES: dict[str, dict[str, Any]] = {
    "backend": {
        "description": "Backend/Server/API development",
        "retrieval_weights": {
            "agent_local": 0.3,
            "shared_coordination": 0.2,
            "durable_knowledge": 0.5,
        },
        "preferred_kinds": ["api_contract", "data_model", "migration", "service_boundary", "code_artifact"],
        "ttl_tendency": "long",
        "semantic_boost": 0.3,
    },
    "frontend": {
        "description": "Frontend/UI/CSS development",
        "retrieval_weights": {
            "agent_local": 0.3,
            "shared_coordination": 0.3,
            "durable_knowledge": 0.4,
        },
        "preferred_kinds": ["decision", "ui_state", "component_contract", "design_token", "user_flow"],
        "ttl_tendency": "medium",
        "semantic_boost": 0.4,
    },
    "coordinator": {
        "description": "Orchestration/Onboarding/Delegation",
        "retrieval_weights": {
            "agent_local": 0.1,
            "shared_coordination": 0.6,
            "durable_knowledge": 0.3,
        },
        "preferred_kinds": ["task_assignment", "handoff", "blocker", "priority", "open_loop"],
        "ttl_tendency": "short",
        "semantic_boost": 0.5,
    },
    "security": {
        "description": "Security Assessment",
        "retrieval_weights": {
            "agent_local": 0.2,
            "shared_coordination": 0.2,
            "durable_knowledge": 0.6,
        },
        "preferred_kinds": ["finding", "risk", "vulnerability", "exception", "sensitive_boundary"],
        "ttl_tendency": "until_resolved",
        "semantic_boost": 0.2,
    },
    "architect": {
        "description": "System architecture/Design/Standards",
        "retrieval_weights": {
            "agent_local": 0.1,
            "shared_coordination": 0.2,
            "durable_knowledge": 0.7,
        },
        "preferred_kinds": ["adr", "invariant", "module_boundary", "principle", "long_term_decision"],
        "ttl_tendency": "very_long",
        "semantic_boost": 0.2,
    },
    "senior": {
        "description": "General senior developer",
        "retrieval_weights": {
            "agent_local": 0.3,
            "shared_coordination": 0.3,
            "durable_knowledge": 0.4,
        },
        "preferred_kinds": [],
        "ttl_tendency": "medium",
        "semantic_boost": 0.4,
    },
    "junior": {
        "description": "Junior developer/assistant",
        "retrieval_weights": {
            "agent_local": 0.4,
            "shared_coordination": 0.3,
            "durable_knowledge": 0.3,
        },
        "preferred_kinds": [],
        "ttl_tendency": "medium",
        "semantic_boost": 0.5,
    },
}


def load_role_profiles() -> dict[str, dict[str, Any]]:
    """Load role memory profiles from config or defaults."""
    if _ROLE_PROFILES_PATH.is_file():
        try:
            with open(_ROLE_PROFILES_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {
                    str(key): value
                    for key, value in data.items()
                    if not str(key).startswith("_") and isinstance(value, dict)
                }
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_ROLE_PROFILES)


def get_role_profile(role: str) -> dict[str, Any]:
    """Get memory profile for a role. Falls back to 'senior' if unknown."""
    profiles = load_role_profiles()
    role_lower = role.strip().lower()
    # Direct match
    if role_lower in profiles:
        return profiles[role_lower]
    # Partial match
    for key in profiles:
        if key in role_lower or role_lower in key:
            return profiles[key]
    return profiles.get("senior", _DEFAULT_ROLE_PROFILES["senior"])


# ---------------------------------------------------------------------------
# Unified Memory Retrieval
# ---------------------------------------------------------------------------


def retrieve_for_agent(
    agent_id: str,
    query: str,
    role: str = "senior",
    project_path: str = "",
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Unified memory retrieval across all 3 classes with role-aware ranking.

    Queries all memory systems, applies precedence rules and role weights,
    returns ranked results.

    Each result: {content, source, class, score, kind, metadata}
    """
    profile = get_role_profile(role)
    weights = profile.get("retrieval_weights", {})
    preferred_kinds = set(profile.get("preferred_kinds", []))
    semantic_boost = profile.get("semantic_boost", 0.4)

    results: list[dict[str, Any]] = []

    # 1. Agent Local Memory (Memory Engine + CLI MEMORY.md)
    agent_local_weight = weights.get("agent_local", 0.3)
    try:
        agent_local_results = _query_agent_local(agent_id, query, project_path)
        for r in agent_local_results:
            r["class"] = MEMORY_CLASS_AGENT_LOCAL
            r["source"] = "agent_local_memory"
            r["precedence"] = precedence_level("agent_local_memory")
            r["weight"] = agent_local_weight
            results.append(r)
    except Exception:
        pass

    # 2. Shared Coordination Memory (Shared Memory / Blackboard)
    shared_weight = weights.get("shared_coordination", 0.3)
    try:
        shared_results = _query_shared_coordination(query, project_path)
        for r in shared_results:
            r["class"] = MEMORY_CLASS_SHARED_COORDINATION
            r["source"] = "project_team_decision"
            r["precedence"] = precedence_level("project_team_decision")
            r["weight"] = shared_weight
            results.append(r)
    except Exception:
        pass

    # 3. Durable Knowledge (Knowledge Engine / Vault)
    durable_weight = weights.get("durable_knowledge", 0.4)
    try:
        durable_results = _query_durable_knowledge(query)
        for r in durable_results:
            r["class"] = MEMORY_CLASS_DURABLE_KNOWLEDGE
            r["source"] = "durable_knowledge"
            r["precedence"] = precedence_level("durable_knowledge")
            r["weight"] = durable_weight
            results.append(r)
    except Exception:
        pass

    # 4. Semantic Recall (boost, not truth)
    try:
        semantic_results = _query_semantic(agent_id, query)
        for r in semantic_results:
            r["class"] = "semantic_recall"
            r["source"] = "semantic_recall"
            r["precedence"] = precedence_level("semantic_recall")
            r["weight"] = semantic_boost
            results.append(r)
    except Exception:
        pass

    # Score: base_score * class_weight * (1 + kind_bonus) / precedence
    for r in results:
        base = r.get("score", 0.5)
        kind_bonus = 0.3 if r.get("kind", "") in preferred_kinds else 0.0
        prec_factor = 1.0 / max(r.get("precedence", 5), 1)
        r["final_score"] = round(base * r["weight"] * (1 + kind_bonus) * prec_factor, 4)

    # Sort by final_score descending, then by precedence ascending
    results.sort(key=lambda r: (-r["final_score"], r.get("precedence", 99)))

    return results[:top_k]


# ---------------------------------------------------------------------------
# Query adapters for each memory system
# ---------------------------------------------------------------------------


def _query_agent_local(agent_id: str, query: str, project_path: str) -> list[dict[str, Any]]:
    """Query agent-local memory (Memory Engine)."""
    results = []
    try:
        from memory_engine import MemoryEngine
        me = MemoryEngine(project_path or ".")
        hits = me.search(query, agent_id=agent_id, top_k=5)
        for hit in hits:
            results.append({
                "content": getattr(hit, "content", ""),
                "score": float(getattr(hit, "score", 0.5)),
                "kind": "agent_memory",
                "metadata": {
                    "file": getattr(hit, "file", ""),
                    "line_start": getattr(hit, "line_start", 0),
                },
            })
    except (ImportError, Exception):
        pass

    # Also check MEMORY.md if accessible
    memory_md_path = ""
    if project_path:
        agent_home, config_dir = _resolve_agent_storage(agent_id, project_path)
        memory_md_path = find_agent_memory_path(agent_id, agent_home, config_dir)
    if memory_md_path and os.path.isfile(memory_md_path):
        try:
            with open(memory_md_path, encoding="utf-8") as f:
                content = f.read()
            if query.lower() in content.lower():
                results.append({
                    "content": content[:500],
                    "score": 0.7,
                    "kind": "cli_memory",
                    "metadata": {"file": memory_md_path},
                })
        except OSError:
            pass

    return results


def _resolve_agent_storage(agent_id: str, project_path: str) -> tuple[str, str]:
    """Resolve canonical home_dir/config_dir for an agent from team.json when possible."""
    normalized_project = str(Path(project_path or ".").expanduser())
    candidates = [
        Path(normalized_project) / "Backend" / "team.json",
        Path(normalized_project) / "team.json",
    ]
    for team_path in candidates:
        try:
            payload = json.loads(team_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            continue
        for agent in payload.get("agents", []):
            if str(agent.get("id", "")).strip() != agent_id:
                continue
            home_dir = str(agent.get("home_dir", "")).strip() or normalized_project
            config_dir = str(agent.get("config_dir", "")).strip().rstrip("/")
            return home_dir, config_dir
    return normalized_project, ""


def _query_shared_coordination(query: str, project_path: str) -> list[dict[str, Any]]:
    """Query shared coordination memory (Shared Memory / Blackboard)."""
    results = []
    try:
        from shared_memory import SharedMemory
        sm = SharedMemory(Path(project_path or "."))
        hits = sm.search(query, top_k=5)
        for hit in hits:
            results.append({
                "content": getattr(hit, "content", ""),
                "score": float(getattr(hit, "score", 0.5)),
                "kind": "shared_topic",
                "metadata": {
                    "file": getattr(hit, "file", ""),
                    "line_start": getattr(hit, "line_start", 0),
                },
            })
    except (ImportError, Exception):
        pass
    return results


def _query_durable_knowledge(query: str) -> list[dict[str, Any]]:
    """Query durable knowledge (Knowledge Engine / Vault)."""
    results = []
    try:
        from knowledge_engine import search_notes

        response = search_notes(query)
        hits = response.get("results", []) if isinstance(response, dict) else []
        for hit in hits[:5]:
            matches = hit.get("matches", []) if isinstance(hit, dict) else []
            results.append({
                "content": "\n".join(str(item) for item in matches[:3]),
                "score": 0.8,
                "kind": "knowledge_note",
                "metadata": {
                    "path": hit.get("path", "") if isinstance(hit, dict) else "",
                    "frontmatter": hit.get("frontmatter", {}) if isinstance(hit, dict) else {},
                },
            })
    except (ImportError, Exception):
        pass
    return results


def _query_semantic(agent_id: str, query: str) -> list[dict[str, Any]]:
    """Query semantic memory (vector + BM25 hybrid)."""
    results = []
    try:
        from semantic_memory import search

        response = search(agent_id, query, top_k=5)
        hits = response.get("results", []) if isinstance(response, dict) else []
        for hit in hits:
            results.append({
                "content": hit.get("text", hit.get("content", "")),
                "score": float(hit.get("score", hit.get("hybrid_score", 0.3))),
                "kind": "semantic_chunk",
                "metadata": {"chunk_id": hit.get("id", "")},
            })
    except (ImportError, Exception):
        pass
    return results


# ---------------------------------------------------------------------------
# Context Bridge rules
# ---------------------------------------------------------------------------

CONTEXT_BRIDGE_RULES = {
    "purpose": "Compress and orient. Never store original truth.",
    "allowed_content": [
        "HANDOFF — current registration + startup context",
        "LETZTE AKTIVITAET — last observed CLI output, decisions",
        "NAECHSTER SCHRITT — continuation point for next session",
    ],
    "forbidden_content": [
        "Original facts not derivable from CLI state",
        "Competing memory entries",
        "Project-specific knowledge (belongs in Knowledge Vault)",
    ],
    "update_policy": "Server-side only. Agent reads, never writes directly.",
}

SOUL_RULES = {
    "purpose": "Stable identity only. Never project-specific facts.",
    "allowed_content": [
        "Core truths about the agent",
        "Strengths and growth areas",
        "Communication style",
        "Work preferences",
        "Boundaries",
    ],
    "forbidden_content": [
        "Project-specific facts",
        "Temporary roles",
        "Task assignments",
        "Current context",
    ],
    "update_policy": "Growth Protocol: Agent proposes, Human approves. Fail-closed.",
}


# ---------------------------------------------------------------------------
# Summary / Status
# ---------------------------------------------------------------------------


def memory_status(agent_id: str, role: str = "senior", project_path: str = "") -> dict[str, Any]:
    """Get memory system status for an agent."""
    profile = get_role_profile(role)
    agent_home, config_dir = _resolve_agent_storage(agent_id, project_path) if project_path else ("", "")
    resolved_memory_path = ""
    if project_path:
        resolved_memory_path = find_agent_memory_path(agent_id, agent_home, config_dir)
    return {
        "agent_id": agent_id,
        "role": role,
        "profile": profile,
        "memory_classes": list(MEMORY_CLASSES.keys()),
        "precedence_levels": len(SOURCE_PRECEDENCE),
        "context_bridge_rules": CONTEXT_BRIDGE_RULES["purpose"],
        "soul_rules": SOUL_RULES["purpose"],
        "agent_home": agent_home,
        "config_dir": config_dir,
        "resolved_memory_path": resolved_memory_path,
        "resolved_memory_exists": bool(resolved_memory_path and os.path.isfile(resolved_memory_path)),
    }
