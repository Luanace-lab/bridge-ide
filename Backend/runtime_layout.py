from __future__ import annotations

import re
import shutil
from typing import Any


KNOWN_ENGINES = ["claude", "codex", "gemini", "qwen"]
DEFAULT_TEAM_LEAD_ID = "teamlead"
_RUNTIME_CLASSIC_SLOTS = {"a", "b", "lead"}
_RUNTIME_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


def detect_available_engines(known_engines: list[str] | None = None) -> set[str]:
    """Probe PATH for supported CLI binaries."""
    found = {engine for engine in (known_engines or KNOWN_ENGINES) if shutil.which(engine)}
    found.add("echo")  # always available for tests
    return found


def pair_mode_of(agent_a_engine: str, agent_b_engine: str) -> str:
    return f"{agent_a_engine}-{agent_b_engine}"


def resolve_layout(
    agent_a_engine: str,
    agent_b_engine: str,
    *,
    available_engines: set[str] | None = None,
) -> list[dict[str, str]]:
    live_engines = available_engines or detect_available_engines()
    a = agent_a_engine.strip().lower()
    b = agent_b_engine.strip().lower()
    if a not in live_engines or b not in live_engines:
        raise ValueError(
            f"unsupported engine selection: agent_a={agent_a_engine}, agent_b={agent_b_engine}"
        )

    if a == b:
        id_a = f"{a}_a"
        id_b = f"{b}_b"
    else:
        id_a = a
        id_b = b

    return [
        {
            "slot": "a",
            "name": f"{id_a}_agent",
            "id": id_a,
            "engine": a,
            "peer": id_b,
        },
        {
            "slot": "b",
            "name": f"{id_b}_agent",
            "id": id_b,
            "engine": b,
            "peer": id_a,
        },
    ]


def resolve_runtime_specs(
    agent_a_engine: str,
    agent_b_engine: str,
    *,
    team_lead_cli_enabled: bool = False,
    team_lead_engine: str = "codex",
    team_lead_scope_file: str = "",
    available_engines: set[str] | None = None,
    team_lead_id: str = DEFAULT_TEAM_LEAD_ID,
) -> list[dict[str, str]]:
    specs = resolve_layout(
        agent_a_engine,
        agent_b_engine,
        available_engines=available_engines,
    )
    if not team_lead_cli_enabled:
        return specs

    live_engines = available_engines or detect_available_engines()
    lead_engine = team_lead_engine.strip().lower() or "codex"
    if lead_engine not in live_engines:
        lead_engine = "codex"
    lead_peer = specs[0]["id"] if specs else "codex"
    lead_spec: dict[str, str] = {
        "slot": "lead",
        "name": "teamlead_agent",
        "id": team_lead_id,
        "engine": lead_engine,
        "peer": lead_peer,
    }
    if team_lead_scope_file:
        lead_spec["scope_file"] = team_lead_scope_file
    specs.append(lead_spec)
    return specs


def runtime_layout_is_valid(raw_layout: Any, *, known_engines: list[str] | None = None) -> bool:
    allowed_engines = set(known_engines or KNOWN_ENGINES)
    if not isinstance(raw_layout, list) or not raw_layout:
        return False
    seen_ids: set[str] = set()
    for item in raw_layout:
        if not isinstance(item, dict):
            return False
        agent_id = str(item.get("id", "")).strip()
        engine = str(item.get("engine", "")).strip().lower()
        slot = str(item.get("slot", "")).strip()
        if not agent_id or not _RUNTIME_AGENT_ID_RE.match(agent_id):
            return False
        if not slot:
            return False
        if not engine or engine not in allowed_engines:
            return False
        if agent_id in seen_ids:
            return False
        seen_ids.add(agent_id)
    return True


def clone_runtime_layout(raw_layout: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in raw_layout if isinstance(item, dict)]


def runtime_pair_mode_for_layout(
    layout: list[dict[str, Any]],
    *,
    known_engines: list[str] | None = None,
) -> str:
    if not runtime_layout_is_valid(layout, known_engines=known_engines):
        return "codex-claude"
    slots = {str(spec.get("slot", "")).strip() for spec in layout}
    if slots.issubset(_RUNTIME_CLASSIC_SLOTS):
        by_slot = {str(spec.get("slot", "")).strip(): spec for spec in layout}
        if "a" in by_slot and "b" in by_slot:
            return pair_mode_of(
                str(by_slot["a"].get("engine", "codex")).strip().lower() or "codex",
                str(by_slot["b"].get("engine", "claude")).strip().lower() or "claude",
            )
    return "multi"


def runtime_layout_from_profiles(
    profiles: list[dict[str, Any]],
    *,
    known_engines: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(profiles, list) or not profiles:
        return []

    specs: list[dict[str, Any]] = []
    profile_slots = {
        str(profile.get("slot", "")).strip()
        for profile in profiles
        if isinstance(profile, dict)
    }
    classic_layout = profile_slots.issubset(_RUNTIME_CLASSIC_SLOTS) and {"a", "b"}.issubset(
        profile_slots
    )
    classic_by_slot = {
        str(profile.get("slot", "")).strip(): profile
        for profile in profiles
        if isinstance(profile, dict) and str(profile.get("slot", "")).strip()
    }
    for index, profile in enumerate(profiles, start=1):
        if not isinstance(profile, dict):
            continue
        agent_id = str(profile.get("id", "")).strip()
        engine = str(profile.get("engine", "")).strip().lower()
        if not agent_id or not engine:
            continue
        slot = str(profile.get("slot", "")).strip() or f"agent_{index}"
        name = (
            str(profile.get("name") or profile.get("display_name") or f"{agent_id}_agent").strip()
            or f"{agent_id}_agent"
        )
        reports_to = str(profile.get("reports_to", "")).strip()
        if classic_layout:
            peer = ""
            if slot == "a":
                peer = str(classic_by_slot.get("b", {}).get("id", "")).strip()
            elif slot == "b":
                peer = str(classic_by_slot.get("a", {}).get("id", "")).strip()
            elif slot == "lead":
                peer = str(classic_by_slot.get("a", {}).get("id", "")).strip()
        else:
            peer = reports_to if reports_to not in {"", "user"} else ""
        specs.append(
            {
                "slot": slot,
                "name": name,
                "id": agent_id,
                "engine": engine,
                "peer": peer,
            }
        )
    return specs if runtime_layout_is_valid(specs, known_engines=known_engines) else []


def runtime_layout_from_state(
    state: dict[str, Any],
    *,
    known_engines: list[str] | None = None,
    available_engines: set[str] | None = None,
    team_lead_id: str = DEFAULT_TEAM_LEAD_ID,
) -> list[dict[str, Any]]:
    stored_layout = state.get("runtime_specs")
    if runtime_layout_is_valid(stored_layout, known_engines=known_engines):
        return clone_runtime_layout(stored_layout)

    profiles = state.get("agent_profiles")
    derived_layout = runtime_layout_from_profiles(
        profiles if isinstance(profiles, list) else [],
        known_engines=known_engines,
    )
    if derived_layout:
        return derived_layout

    configured = bool(
        str(state.get("project_name", "")).strip()
        or state.get("runtime_overlay")
        or state.get("last_start_at")
    )
    if not configured:
        return []

    agent_a_engine = str(state.get("agent_a_engine", "codex"))
    agent_b_engine = str(state.get("agent_b_engine", "claude"))
    team_lead_cli_enabled = bool(state.get("team_lead_cli_enabled", False))
    team_lead_engine = str(state.get("team_lead_engine", "codex"))
    team_lead_scope_file = str(state.get("team_lead_scope_file", ""))
    try:
        return resolve_runtime_specs(
            agent_a_engine,
            agent_b_engine,
            team_lead_cli_enabled=team_lead_cli_enabled,
            team_lead_engine=team_lead_engine,
            team_lead_scope_file=team_lead_scope_file,
            available_engines=available_engines,
            team_lead_id=team_lead_id,
        )
    except ValueError:
        return resolve_layout(
            "codex",
            "claude",
            available_engines=available_engines,
        )


def runtime_profile_map_from_state(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = state.get("agent_profiles")
    if not isinstance(profiles, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        agent_id = str(profile.get("id", "")).strip()
        if agent_id:
            out[agent_id] = dict(profile)
    return out


def build_explicit_runtime_layout(
    raw_agents: list[dict[str, Any]],
    *,
    live_engines: set[str],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_slots: set[str] = set()
    engine_counts: dict[str, int] = {}
    for index, agent in enumerate(raw_agents, start=1):
        engine = str(agent.get("engine", "")).strip().lower()
        if engine not in live_engines:
            raise ValueError(f"invalid runtime agent engine: {engine or 'missing'}")
        raw_id = str(agent.get("id", "")).strip()
        if raw_id:
            agent_id = raw_id
        else:
            engine_counts[engine] = int(engine_counts.get(engine, 0)) + 1
            agent_id = f"{engine}_{engine_counts[engine]}"
        if not _RUNTIME_AGENT_ID_RE.match(agent_id):
            raise ValueError(
                f"invalid runtime agent id: {agent_id!r} (must be alphanumeric + underscore)"
            )
        if agent_id in seen_ids:
            raise ValueError(f"duplicate runtime agent id: {agent_id}")
        seen_ids.add(agent_id)

        slot = str(agent.get("slot", "")).strip() or f"agent_{index}"
        if slot in seen_slots:
            raise ValueError(f"duplicate runtime slot: {slot}")
        seen_slots.add(slot)
        reports_to = str(agent.get("reportsTo") or agent.get("reports_to") or "").strip()
        specs.append(
            {
                "slot": slot,
                "name": str(agent.get("name") or agent_id).strip() or agent_id,
                "id": agent_id,
                "engine": engine,
                "peer": reports_to if reports_to not in {"", "user"} else "",
                "source_index": index - 1,
            }
        )
    return specs
