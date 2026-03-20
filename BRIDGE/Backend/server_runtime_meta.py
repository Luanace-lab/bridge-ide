"""Runtime layout/profile/capability helpers extracted from server.py (Slice 36)."""

from __future__ import annotations

from typing import Any, Callable

import runtime_layout

_RUNTIME_GETTER: Callable[[], dict[str, Any]] = lambda: {}
_RUNTIME_LOCK: Any = None
_REGISTERED_AGENTS_GETTER: Callable[[], dict[str, dict[str, Any]]] = lambda: {}
_DETECT_AVAILABLE_ENGINES_FN: Callable[[], set[str]] = lambda: set()
_KNOWN_ENGINES_GETTER: Callable[[], set[str]] = lambda: set()
_TEAM_LEAD_ID_GETTER: Callable[[], str] = lambda: ""


def init(
    *,
    runtime_getter: Callable[[], dict[str, Any]],
    runtime_lock: Any,
    registered_agents_getter: Callable[[], dict[str, dict[str, Any]]],
    detect_available_engines_fn: Callable[[], set[str]],
    known_engines_getter: Callable[[], set[str]],
    team_lead_id_getter: Callable[[], str],
) -> None:
    """Bind shared runtime state and callbacks from server.py."""
    global _RUNTIME_GETTER
    global _RUNTIME_LOCK
    global _REGISTERED_AGENTS_GETTER
    global _DETECT_AVAILABLE_ENGINES_FN
    global _KNOWN_ENGINES_GETTER
    global _TEAM_LEAD_ID_GETTER

    _RUNTIME_GETTER = runtime_getter
    _RUNTIME_LOCK = runtime_lock
    _REGISTERED_AGENTS_GETTER = registered_agents_getter
    _DETECT_AVAILABLE_ENGINES_FN = detect_available_engines_fn
    _KNOWN_ENGINES_GETTER = known_engines_getter
    _TEAM_LEAD_ID_GETTER = team_lead_id_getter


def _known_engines() -> set[str]:
    raw = _KNOWN_ENGINES_GETTER()
    return set(raw) if isinstance(raw, set) else set(raw or [])


def _team_lead_id() -> str:
    return str(_TEAM_LEAD_ID_GETTER() or "")


def _current_runtime_state() -> dict[str, Any]:
    lock = _RUNTIME_LOCK
    if lock is None:
        raw = _RUNTIME_GETTER()
        return dict(raw) if isinstance(raw, dict) else {}
    with lock:
        raw = _RUNTIME_GETTER()
        return dict(raw) if isinstance(raw, dict) else {}


def _registered_agents() -> dict[str, dict[str, Any]]:
    raw = _REGISTERED_AGENTS_GETTER()
    return raw if isinstance(raw, dict) else {}


def pair_mode_of(agent_a_engine: str, agent_b_engine: str) -> str:
    return runtime_layout.pair_mode_of(agent_a_engine, agent_b_engine)


def resolve_layout(agent_a_engine: str, agent_b_engine: str) -> list[dict[str, str]]:
    return runtime_layout.resolve_layout(
        agent_a_engine,
        agent_b_engine,
        available_engines=_DETECT_AVAILABLE_ENGINES_FN(),
    )


def resolve_runtime_specs(
    agent_a_engine: str,
    agent_b_engine: str,
    *,
    team_lead_cli_enabled: bool = False,
    team_lead_engine: str = "codex",
    team_lead_scope_file: str = "",
) -> list[dict[str, str]]:
    return runtime_layout.resolve_runtime_specs(
        agent_a_engine,
        agent_b_engine,
        team_lead_cli_enabled=team_lead_cli_enabled,
        team_lead_engine=team_lead_engine,
        team_lead_scope_file=team_lead_scope_file,
        available_engines=_DETECT_AVAILABLE_ENGINES_FN(),
        team_lead_id=_team_lead_id(),
    )


def _runtime_layout_is_valid(raw_layout: Any) -> bool:
    return runtime_layout.runtime_layout_is_valid(raw_layout, known_engines=_known_engines())


def _clone_runtime_layout(raw_layout: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return runtime_layout.clone_runtime_layout(raw_layout)


def _runtime_pair_mode_for_layout(layout: list[dict[str, Any]]) -> str:
    return runtime_layout.runtime_pair_mode_for_layout(layout, known_engines=_known_engines())


def _runtime_layout_from_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return runtime_layout.runtime_layout_from_profiles(profiles, known_engines=_known_engines())


def _runtime_layout_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    return runtime_layout.runtime_layout_from_state(
        state,
        known_engines=_known_engines(),
        available_engines=_DETECT_AVAILABLE_ENGINES_FN(),
        team_lead_id=_team_lead_id(),
    )


def _runtime_profile_map_from_state(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return runtime_layout.runtime_profile_map_from_state(state)


def _runtime_profile_for_agent(agent_id: str) -> dict[str, Any]:
    runtime_state = _current_runtime_state()
    return _runtime_profile_map_from_state(runtime_state).get(agent_id, {})


def _build_explicit_runtime_layout(
    raw_agents: list[dict[str, Any]],
    *,
    live_engines: set[str],
) -> list[dict[str, Any]]:
    return runtime_layout.build_explicit_runtime_layout(raw_agents, live_engines=live_engines)


def _normalize_capability_list(value: Any) -> list[str]:
    """Normalize a capability list to lowercase unique strings."""
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        cap = str(item or "").strip().lower()
        if not cap or cap in seen:
            continue
        seen.add(cap)
        out.append(cap)
    return out


def _runtime_profile_capabilities(agent_id: str) -> list[str]:
    """Return runtime-profile capabilities for one agent, normalized."""
    runtime_profile = _runtime_profile_for_agent(agent_id)
    if not isinstance(runtime_profile, dict):
        return []
    return _normalize_capability_list(runtime_profile.get("capabilities", []))


def _capabilities_for_response(agent_id: str, reg: dict | None) -> Any:
    """Return response-facing capabilities.

    For managed runtime agents, the runtime profile is authoritative. For all
    other agents, fall back to the registered capabilities first.
    """
    runtime_profile = _runtime_profile_for_agent(agent_id)
    if isinstance(runtime_profile, dict) and runtime_profile:
        return _runtime_profile_capabilities(agent_id)
    raw = (reg or {}).get("capabilities", [])
    if isinstance(raw, dict):
        return raw or _runtime_profile_capabilities(agent_id)
    normalized = _normalize_capability_list(raw)
    if normalized:
        return normalized
    return _runtime_profile_capabilities(agent_id)


def _get_registered_agent_capabilities(agent_id: str) -> tuple[bool, list[str]]:
    """Return (is_registered, capabilities_list) for an agent."""
    reg = _registered_agents().get(agent_id)
    if not reg:
        return False, []
    runtime_profile = _runtime_profile_for_agent(agent_id)
    if isinstance(runtime_profile, dict) and runtime_profile:
        return True, _runtime_profile_capabilities(agent_id)
    caps = _normalize_capability_list(reg.get("capabilities", []))
    if caps:
        return True, caps
    runtime_caps = _runtime_profile_capabilities(agent_id)
    if runtime_caps:
        return True, runtime_caps
    return True, []


def _capability_match(
    required: list[str], agent_caps: list[str], *, agent_registered: bool = True
) -> tuple[bool, list[str]]:
    """Check if agent capabilities satisfy required capabilities."""
    if not required:
        return True, []
    if not agent_registered:
        return False, list(required)
    agent_set = set(c.lower() for c in agent_caps)
    missing = [r for r in required if r.lower() not in agent_set]
    return (len(missing) == 0), missing


def build_runtime_configure_payload_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Summarize runtime.configure payloads for durable audit without logging the full request body."""
    raw_agents = [
        agent for agent in (data.get("agents") if isinstance(data.get("agents"), list) else [])
        if isinstance(agent, dict)
    ]
    leader = data.get("leader") if isinstance(data.get("leader"), dict) else {}
    return {
        "project_name": str(data.get("project_name", "")).strip(),
        "project_path": str(data.get("project_path", "")).strip(),
        "agent_a_engine": str(data.get("agent_a_engine", "")).strip().lower(),
        "agent_b_engine": str(data.get("agent_b_engine", "")).strip().lower(),
        "team_lead_engine": str(data.get("team_lead_engine", "")).strip().lower(),
        "team_lead_enabled": bool(data.get("team_lead_enabled", False)),
        "team_lead_cli_enabled": bool(data.get("team_lead_cli_enabled", False)),
        "leader": {
            "name": str(leader.get("name", "")).strip(),
            "model": str(leader.get("model", "")).strip(),
            "role": str(leader.get("role") or leader.get("position") or "").strip(),
        } if leader else {},
        "agents": [
            {
                "name": str(agent.get("name", "")).strip(),
                "model": str(agent.get("model", "")).strip(),
                "role": str(agent.get("role") or agent.get("position") or "").strip(),
                "engine": str(agent.get("engine", "")).strip().lower(),
            }
            for agent in raw_agents[:5]
        ],
        "agent_count": len(raw_agents),
    }
