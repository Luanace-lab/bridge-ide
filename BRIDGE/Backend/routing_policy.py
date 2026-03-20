from __future__ import annotations

from typing import Any, Mapping


def _safe_level(value: Any, default: int = 99) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _collect_agents(team_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    for raw in team_config.get("agents", []) or []:
        if not isinstance(raw, Mapping):
            continue
        aid = str(raw.get("id", "")).strip()
        if not aid:
            continue
        agents.append(
            {
                "id": aid,
                "level": _safe_level(raw.get("level", 99)),
                "reports_to": str(raw.get("reports_to", "")).strip(),
                "extra_routes": list(raw.get("extra_routes", []) or []),
                "aliases": list(raw.get("aliases", []) or []),
            }
        )
    return agents


def _get_all_subordinates(agent_id: str, agents: list[dict[str, Any]]) -> set[str]:
    """Recursively collect all subordinate IDs of an agent."""
    subs: set[str] = set()
    direct = [agent["id"] for agent in agents if agent.get("reports_to") == agent_id]
    for child_id in direct:
        if child_id in subs:
            continue
        subs.add(child_id)
        subs.update(_get_all_subordinates(child_id, agents))
    return subs


def derive_team_routes(team_config: Mapping[str, Any]) -> dict[str, set[str]]:
    """Derive intra-team routes from team definitions (lead + members)."""
    routes: dict[str, set[str]] = {}
    for team in team_config.get("teams", []) or []:
        if not isinstance(team, Mapping):
            continue
        team_members = {
            str(member).strip()
            for member in team.get("members", []) or []
            if str(member).strip()
        }
        lead = str(team.get("lead", "")).strip()
        if lead:
            team_members.add(lead)
        for member in team_members:
            routes.setdefault(member, set()).update(team_members - {member})
    return routes


def derive_aliases(
    team_config: Mapping[str, Any],
    *,
    default_aliases: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Derive alias map from team config, merged over optional defaults."""
    aliases: dict[str, str] = {
        str(alias).strip().lower(): str(target).strip()
        for alias, target in (default_aliases or {}).items()
        if str(alias).strip() and str(target).strip()
    }
    for agent in _collect_agents(team_config):
        aid = agent["id"]
        for alias in agent.get("aliases", []) or []:
            alias_key = str(alias).strip().lower()
            if alias_key:
                aliases[alias_key] = aid
    return aliases


def derive_routes(
    team_config: Mapping[str, Any],
    *,
    include_team_routes: bool = True,
) -> dict[str, set[str]]:
    """Derive V2.1 hierarchy routes from team config.

    Rules:
    - L0 (Owner): can reach all agents
    - L1 (Lead): can reach all other agents
    - L2 (Senior): own lead + same-lead L2 peers + recursive subordinates
    - L3+ (Worker): own lead only
    - Everyone can reach `user` and explicit `extra_routes`
    - `user` can reach all agents
    - Optional: merge intra-team routes from teams[]
    """
    agents = _collect_agents(team_config)
    routes: dict[str, set[str]] = {}

    for agent in agents:
        aid = agent["id"]
        level = agent["level"]
        reports_to = agent["reports_to"]
        allowed: set[str] = {"user"}
        if reports_to:
            allowed.add(reports_to)

        if level == 0:
            allowed = {other["id"] for other in agents}
        elif level == 1:
            allowed.update(other["id"] for other in agents if other["id"] != aid)
        elif level == 2:
            if reports_to:
                allowed.update(
                    other["id"]
                    for other in agents
                    if other["id"] != aid
                    and other.get("level") == 2
                    and other.get("reports_to") == reports_to
                )
            allowed.update(_get_all_subordinates(aid, agents))

        for extra in agent.get("extra_routes", []) or []:
            extra_id = str(extra).strip()
            if extra_id:
                allowed.add(extra_id)

        routes[aid] = allowed

    routes["user"] = {agent["id"] for agent in agents}

    if include_team_routes:
        for sender, targets in derive_team_routes(team_config).items():
            routes.setdefault(sender, set()).update(targets)

    return routes
