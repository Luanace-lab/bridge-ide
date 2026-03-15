from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import runtime_layout


def _resolve_requested_engines(pair_mode: str, agent_a_engine: str, agent_b_engine: str) -> tuple[str, str]:
    a = agent_a_engine.strip().lower()
    b = agent_b_engine.strip().lower()
    if a and b:
        return a, b
    left, sep, right = pair_mode.strip().lower().partition("-")
    if sep:
        if not a:
            a = left
        if not b:
            b = right
    return a, b


def _load_team_agents(team_path: str) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(Path(team_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    agents = payload.get("agents")
    if not isinstance(agents, list):
        return {}
    return {
        str(agent.get("id", "")).strip(): agent
        for agent in agents
        if isinstance(agent, dict) and str(agent.get("id", "")).strip()
    }


def _explicit_runtime_agent(spec: dict[str, str], agent_conf: dict[str, Any]) -> dict[str, Any]:
    description = (
        str(agent_conf.get("description", "")).strip()
        or str(agent_conf.get("role", "")).strip()
        or spec["name"]
    )
    return {
        "id": spec["id"],
        "name": spec["name"],
        "engine": spec["engine"],
        "role": str(agent_conf.get("role", "")).strip() or spec["slot"],
        "description": description,
        "model": str(agent_conf.get("model", "")).strip(),
    }


def build_runtime_configure_payload(
    *,
    team_path: str,
    pair_mode: str,
    agent_a_engine: str,
    agent_b_engine: str,
    project_path: str,
    allow_peer_auto: bool,
    peer_auto_require_flag: bool,
    max_peer_hops: int,
    max_turns: int,
    process_all: bool,
    keep_history: bool,
    timeout: int,
    stabilize_seconds: float,
) -> dict[str, Any]:
    resolved_a_engine, resolved_b_engine = _resolve_requested_engines(
        pair_mode,
        agent_a_engine,
        agent_b_engine,
    )

    payload: dict[str, Any] = {
        "pair_mode": pair_mode,
        "project_path": project_path,
        "allow_peer_auto": allow_peer_auto,
        "peer_auto_require_flag": peer_auto_require_flag,
        "max_peer_hops": max_peer_hops,
        "max_turns": max_turns,
        "process_all": process_all,
        "keep_history": keep_history,
        "timeout": timeout,
        "stabilize_seconds": stabilize_seconds,
    }

    if resolved_a_engine:
        payload["agent_a_engine"] = resolved_a_engine
    if resolved_b_engine:
        payload["agent_b_engine"] = resolved_b_engine

    if not resolved_a_engine or not resolved_b_engine:
        return payload

    try:
        layout = runtime_layout.resolve_layout(
            resolved_a_engine,
            resolved_b_engine,
            available_engines=set(runtime_layout.KNOWN_ENGINES) | {"echo"},
        )
    except ValueError:
        return payload

    team_agents = _load_team_agents(team_path)
    if not team_agents:
        return payload

    active_specs: list[tuple[dict[str, str], dict[str, Any]]] = []
    inactive_count = 0
    for spec in layout:
        agent_conf = team_agents.get(spec["id"])
        if agent_conf is None:
            return payload
        if bool(agent_conf.get("active", False)):
            active_specs.append((spec, agent_conf))
        else:
            inactive_count += 1

    if active_specs and inactive_count:
        payload.pop("agent_a_engine", None)
        payload.pop("agent_b_engine", None)
        payload["agents"] = [
            _explicit_runtime_agent(spec, agent_conf)
            for spec, agent_conf in active_specs
        ]

    return payload
