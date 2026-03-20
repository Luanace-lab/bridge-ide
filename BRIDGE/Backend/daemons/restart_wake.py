from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

_RESTART_WAKE_DELAY_SECONDS = 3.0

_team_config_getter: Callable[[], dict[str, Any] | None] | None = None
_team_config_lock_getter: Callable[[], Any] | None = None
_is_session_alive_cb: Callable[[str], bool] | None = None
_tmux_session_for_cb: Callable[[str], str] | None = None
_is_agent_at_prompt_inline_cb: Callable[[str], bool] | None = None
_nudge_idle_agent_cb: Callable[[str, str], bool] | None = None
_agent_last_nudge_getter: Callable[[], dict[str, float]] | None = None
_role_description_for_cb: Callable[[dict[str, Any], str], str] | None = None
_team_members_for_cb: Callable[[str], list[dict[str, str]]] | None = None
_create_agent_session_cb: Callable[..., bool] | None = None
_port_getter: Callable[[], int] | None = None
_append_message_cb: Callable[..., Any] | None = None
_ws_broadcast_cb: Callable[[str, dict[str, Any]], None] | None = None


def init(
    *,
    team_config_getter: Callable[[], dict[str, Any] | None],
    team_config_lock_getter: Callable[[], Any],
    is_session_alive: Callable[[str], bool],
    tmux_session_for: Callable[[str], str],
    is_agent_at_prompt_inline: Callable[[str], bool],
    nudge_idle_agent: Callable[[str, str], bool],
    agent_last_nudge_getter: Callable[[], dict[str, float]],
    role_description_for: Callable[[dict[str, Any], str], str],
    team_members_for: Callable[[str], list[dict[str, str]]],
    create_agent_session: Callable[..., bool],
    port_getter: Callable[[], int],
    append_message: Callable[..., Any],
    ws_broadcast: Callable[[str, dict[str, Any]], None],
) -> None:
    global _team_config_getter, _team_config_lock_getter, _is_session_alive_cb
    global _tmux_session_for_cb, _is_agent_at_prompt_inline_cb, _nudge_idle_agent_cb
    global _agent_last_nudge_getter, _role_description_for_cb, _team_members_for_cb
    global _create_agent_session_cb, _port_getter, _append_message_cb, _ws_broadcast_cb

    _team_config_getter = team_config_getter
    _team_config_lock_getter = team_config_lock_getter
    _is_session_alive_cb = is_session_alive
    _tmux_session_for_cb = tmux_session_for
    _is_agent_at_prompt_inline_cb = is_agent_at_prompt_inline
    _nudge_idle_agent_cb = nudge_idle_agent
    _agent_last_nudge_getter = agent_last_nudge_getter
    _role_description_for_cb = role_description_for
    _team_members_for_cb = team_members_for
    _create_agent_session_cb = create_agent_session
    _port_getter = port_getter
    _append_message_cb = append_message
    _ws_broadcast_cb = ws_broadcast


def _restart_wake_phase() -> None:
    required = [
        _team_config_getter,
        _team_config_lock_getter,
        _is_session_alive_cb,
        _tmux_session_for_cb,
        _is_agent_at_prompt_inline_cb,
        _nudge_idle_agent_cb,
        _agent_last_nudge_getter,
        _role_description_for_cb,
        _team_members_for_cb,
        _create_agent_session_cb,
        _port_getter,
        _append_message_cb,
        _ws_broadcast_cb,
    ]
    if any(item is None for item in required):
        raise RuntimeError("daemons.restart_wake not initialized")

    team_config = _team_config_getter()
    if team_config is None:
        print("[restart] WAKE: No team.json loaded, skipping agent restart")
        return

    started_agents: list[str] = []
    team_config_lock = _team_config_lock_getter()
    with team_config_lock:
        agent_configs = [dict(agent) for agent in team_config.get("agents", [])]

    for agent_conf in agent_configs:
        if not agent_conf.get("active", False):
            continue

        agent_id = str(agent_conf.get("id", "")).strip()
        if not agent_id:
            continue

        try:
            if _is_session_alive_cb(agent_id):
                session_name = _tmux_session_for_cb(agent_id)
                try:
                    subprocess.run(
                        ["tmux", "set-environment", "-t", session_name, "BROWSER", "false"],
                        capture_output=True,
                        timeout=5,
                    )
                except Exception:
                    pass
                if _is_agent_at_prompt_inline_cb(agent_id):
                    _nudge_idle_agent_cb(agent_id, "wake_phase")
                    _agent_last_nudge_getter()[agent_id] = time.time()
                    print(f"[restart] WAKE: {agent_id} at prompt — nudged")
                else:
                    print(f"[restart] WAKE: {agent_id} already running, skipping")
                started_agents.append(agent_id)
                continue
        except Exception:
            pass

        try:
            home_dir = str(agent_conf.get("home_dir", "")).strip()
            if not home_dir or not os.path.isdir(home_dir):
                print(f"[restart] WAKE: {agent_id} has no valid home_dir, skipping")
                continue

            home_path = Path(home_dir)
            if home_path.parent.name == ".agent_sessions" and home_path.name == agent_id:
                project_path = str(home_path.parent.parent)
            else:
                project_path = home_dir

            prompt = "Lies deine Dokumentation. Registriere dich via bridge_register."
            prompt_file = str(agent_conf.get("prompt_file", "")).strip()
            if prompt_file and os.path.exists(prompt_file):
                try:
                    with open(prompt_file, encoding="utf-8") as handle:
                        content = handle.read().strip()
                    if content:
                        prompt = content
                except Exception:
                    pass

            engine = str(agent_conf.get("engine", "claude")).strip() or "claude"
            agent_config_dir = str(agent_conf.get("config_dir", "")).strip()
            agent_model = str(agent_conf.get("model", "")).strip()
            agent_role = str(agent_conf.get("description", agent_id)).strip() or agent_id
            agent_mcp_servers = str(agent_conf.get("mcp_servers", "")).strip()
            wake_role_desc = _role_description_for_cb(agent_conf, fallback=agent_role)
            wake_team_members = _team_members_for_cb(agent_id)
            success = _create_agent_session_cb(
                agent_id=agent_id,
                role=agent_role,
                project_path=project_path,
                team_members=wake_team_members,
                engine=engine,
                bridge_port=_port_getter(),
                role_description=wake_role_desc,
                config_dir=agent_config_dir,
                mcp_servers=agent_mcp_servers,
                model=agent_model,
                permissions=agent_conf.get("permissions"),
                scope=agent_conf.get("scope"),
                report_recipient=str(agent_conf.get("reports_to", "")).strip(),
                initial_prompt=prompt,
            )
            if success:
                started_agents.append(agent_id)
                config_label = " [sub2]" if agent_config_dir else ""
                print(f"[restart] WAKE: Started {agent_id} ({engine}){config_label}")
            else:
                print(f"[restart] WAKE: Failed to start {agent_id}")
        except Exception as exc:
            print(f"[restart] WAKE: Error starting {agent_id}: {exc}")

    if started_agents:
        _append_message_cb(
            "system",
            "all",
            "[RESTART WAKE] Server ist wieder online. "
            "Ladet euren Zustand (CONTEXT_BRIDGE.md / MEMORY.md) und registriert euch.",
            meta={"type": "restart_wake"},
        )
        _ws_broadcast_cb("restart_wake", {"started_agents": started_agents})
        print(f"[restart] WAKE complete: {len(started_agents)} agents started")


def _restart_wake_enabled() -> bool:
    raw = str(os.environ.get("BRIDGE_SERVER_WAKE_ON_START", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _delayed_restart_wake() -> None:
    time.sleep(_RESTART_WAKE_DELAY_SECONDS)
    _restart_wake_phase()


def _start_restart_wake_thread() -> threading.Thread:
    wake_thread = threading.Thread(
        target=_delayed_restart_wake,
        daemon=True,
        name="restart-wake",
    )
    wake_thread.start()
    return wake_thread
