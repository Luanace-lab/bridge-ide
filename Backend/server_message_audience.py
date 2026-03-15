from __future__ import annotations

from typing import Any, Callable

_team_config_getter: Callable[[], dict[str, Any] | None] = lambda: None
_registered_agents_getter: Callable[[], dict[str, Any]] = lambda: {}
_agent_state_lock: Any = None
_agent_is_live: Callable[..., bool] = lambda _agent_id, stale_seconds=120.0, reg=None: False
_get_team_members: Callable[[str], set[str]] = lambda _team_id: set()
_is_management_agent: Callable[[str], bool] = lambda _agent_id: False


def init(
    *,
    team_config_getter: Callable[[], dict[str, Any] | None],
    registered_agents_getter: Callable[[], dict[str, Any]],
    agent_state_lock: Any,
    agent_is_live_fn: Callable[..., bool],
    get_team_members_fn: Callable[[str], set[str]],
    is_management_agent_fn: Callable[[str], bool],
) -> None:
    global _team_config_getter
    global _registered_agents_getter
    global _agent_state_lock
    global _agent_is_live
    global _get_team_members
    global _is_management_agent

    _team_config_getter = team_config_getter
    _registered_agents_getter = registered_agents_getter
    _agent_state_lock = agent_state_lock
    _agent_is_live = agent_is_live_fn
    _get_team_members = get_team_members_fn
    _is_management_agent = is_management_agent_fn


def _active_team_agents() -> list[dict[str, Any]]:
    team_config = _team_config_getter() or {}
    agents = team_config.get("agents", [])
    if not isinstance(agents, list):
        return []
    return [agent for agent in agents if isinstance(agent, dict) and agent.get("active", False)]


def _dedupe(values: list[str], *, exclude: str = "") -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value or value == exclude or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _is_lead_agent(agent_id: str) -> bool:
    for agent in _active_team_agents():
        if str(agent.get("id", "")).strip() != agent_id:
            continue
        try:
            return int(agent.get("level", 99)) == 1
        except (TypeError, ValueError):
            return False
    return False


def resolve_configured_targets(recipient: str, *, sender: str = "") -> list[str]:
    recipient = str(recipient).strip()
    if not recipient:
        return []

    active_ids = [str(agent.get("id", "")).strip() for agent in _active_team_agents()]
    active_ids = _dedupe(active_ids)

    if recipient == "all":
        return _dedupe(active_ids, exclude=sender)
    if recipient == "all_managers":
        targets = [agent_id for agent_id in active_ids if _is_management_agent(agent_id)]
        return _dedupe(targets, exclude=sender)
    if recipient == "leads":
        targets = [agent_id for agent_id in active_ids if _is_lead_agent(agent_id)]
        return _dedupe(targets, exclude=sender)
    if recipient.startswith("team:"):
        team_id = recipient[len("team:") :]
        team_members = _get_team_members(team_id)
        targets = [agent_id for agent_id in active_ids if agent_id in team_members]
        return _dedupe(targets, exclude=sender)
    return []


def resolve_live_targets(recipient: str, *, sender: str = "") -> list[str]:
    recipient = str(recipient).strip()
    if not recipient:
        return []

    with _agent_state_lock:
        registered_agents = dict(_registered_agents_getter())

    live_ids: list[str] = []
    for agent_id, reg in registered_agents.items():
        if not reg:
            continue
        if _agent_is_live(agent_id, stale_seconds=120.0, reg=reg):
            live_ids.append(str(agent_id).strip())
    live_ids = _dedupe(live_ids)

    if recipient == "all":
        return _dedupe(live_ids, exclude=sender)
    if recipient == "all_managers":
        targets = [agent_id for agent_id in live_ids if _is_management_agent(agent_id)]
        return _dedupe(targets, exclude=sender)
    if recipient == "leads":
        targets = [agent_id for agent_id in live_ids if _is_lead_agent(agent_id)]
        return _dedupe(targets, exclude=sender)
    if recipient.startswith("team:"):
        team_id = recipient[len("team:") :]
        team_members = _get_team_members(team_id)
        targets = [agent_id for agent_id in live_ids if agent_id in team_members]
        return _dedupe(targets, exclude=sender)
    return []
