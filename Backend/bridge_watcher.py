#!/usr/bin/env python3
"""
bridge_watcher.py — WebSocket-to-tmux Message Router (Hardened V4)

Hoert den Bridge-WebSocket (:9112) ab und injiziert eingehende
Nachrichten via tmux buffer-paste in die richtige Agent-Session.

Hardened Injection Strategy:
1. Pruefen ob Agent am Prompt ist (bereit fuer Input)
2. Kurze Notification statt voller Nachricht (MCP hat die volle Message)
3. Retry mit Backoff bei Fehlschlag
4. Deduplication — gleiche Nachricht nicht doppelt injizieren

Usage:
    python3 bridge_watcher.py
    python3 bridge_watcher.py --ws ws://127.0.0.1:9112
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import execution_journal
import hashlib
import json
import logging
import os
import random
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from collections import deque
from urllib.parse import quote

from common import (
    build_bridge_auth_headers,
    build_bridge_ws_auth_message,
    http_get_json,
    http_post_json,
    send_message,
)
from persistence_utils import (
    detect_instruction_filename,
    first_existing_path,
    resolve_agent_cli_layout,
)
from routing_policy import derive_aliases as shared_derive_aliases, derive_routes as shared_derive_routes

WS_DEFAULT = "ws://127.0.0.1:9112"


async def _async_run(*args, **kwargs):
    """Run subprocess.run in a thread to avoid blocking the asyncio event loop."""
    return await asyncio.to_thread(subprocess.run, *args, **kwargs)


def _bridge_post_json(
    url: str,
    payload: dict[str, object],
    *,
    agent_id: str = "system",
    timeout: float = 30.0,
) -> dict[str, object]:
    return http_post_json(
        url,
        payload,
        timeout=timeout,
        headers=build_bridge_auth_headers(agent_id=agent_id),
    )


BRIDGE_HTTP = "http://127.0.0.1:9111"
AGENTS_CONF = os.path.join(os.path.dirname(__file__), "agents.conf")
LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "watcher.log")
TMUX_INJECT_BUFFER = "bridge_inject"
PID_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "pids", "watcher.pid"))

# Nachrichten an "user" werden NICHT injiziert — die erscheinen in chat.html.
SKIP_RECIPIENTS = {"user", "system"}

ALLOWED_ROUTES = {
    "user": {"ordo", "lucy", "viktor", "nova", "frontend", "stellexa",
             "codex", "backend", "techwriter", "qwen1", "qwen2", "qwen3",
             "t_research", "t_quant", "t_data", "t_exec",
             "alpha_lead", "alpha_recon", "alpha_exploit",
             "bravo_lead", "bravo_recon", "bravo_exploit",
             "charlie_lead", "charlie_recon", "charlie_exploit"},
    "ordo": {"user", "viktor", "codex", "backend", "techwriter", "nova", "lucy", "frontend", "stellexa",
             "qwen1", "qwen2", "qwen3",
             "t_research", "t_quant", "t_data", "t_exec"},
    "viktor": {"ordo", "codex", "backend", "techwriter", "nova", "qwen1", "qwen2", "qwen3", "user",
               "stellexa", "frontend",
               "t_research", "t_quant", "t_data", "t_exec",
               "alpha_lead", "alpha_recon", "alpha_exploit",
               "bravo_lead", "bravo_recon", "bravo_exploit",
               "charlie_lead", "charlie_recon", "charlie_exploit"},
    "codex": {"ordo", "viktor"},
    "backend": {"ordo", "viktor", "user", "codex", "qwen1", "qwen2", "qwen3"},
    "nova": {"ordo", "viktor", "lucy", "stellexa", "user", "frontend",
             "t_research", "t_quant", "t_data", "t_exec",
             "alpha_lead", "alpha_recon", "alpha_exploit",
             "bravo_lead", "bravo_recon", "bravo_exploit",
             "charlie_lead", "charlie_recon", "charlie_exploit"},
    "lucy": {"ordo", "user", "nova", "viktor"},
    "stellexa": {"ordo", "viktor", "nova"},
    "frontend": {"ordo", "viktor", "user", "nova"},
    "techwriter": {"ordo", "viktor", "backend", "nova", "user"},
    "qwen1": {"viktor", "backend"},
    "qwen2": {"viktor", "backend"},
    "qwen3": {"viktor", "backend"},
    "t_research": {"nova", "t_quant", "t_data", "t_exec", "viktor", "ordo"},
    "t_quant": {"nova", "t_research", "t_data", "t_exec", "viktor", "ordo"},
    "t_data": {"nova", "t_research", "t_quant", "t_exec", "viktor", "ordo"},
    "t_exec": {"nova", "t_research", "t_quant", "t_data", "viktor", "ordo"},
    # Bug-Bounty: Leads -> nova, viktor, user + eigenes Team
    "alpha_lead": {"nova", "viktor", "user", "alpha_recon", "alpha_exploit"},
    "bravo_lead": {"nova", "viktor", "user", "bravo_recon", "bravo_exploit"},
    "charlie_lead": {"nova", "viktor", "user", "charlie_recon", "charlie_exploit"},
    # Bug-Bounty: Recon/Exploit -> nur eigener Lead
    "alpha_recon": {"alpha_lead"},
    "alpha_exploit": {"alpha_lead"},
    "bravo_recon": {"bravo_lead"},
    "bravo_exploit": {"bravo_lead"},
    "charlie_recon": {"charlie_lead"},
    "charlie_exploit": {"charlie_lead"},
}

# Bridge-ID aliases -> tmux session agent_id
# Keep "teamlead" as a compatibility alias because existing bridge senders still use it.
DEFAULT_AGENT_ID_ALIASES = {
    "teamlead": "ordo",
    "manager": "ordo",
    "projektleiter": "ordo",
}
AGENT_ID_ALIASES = dict(DEFAULT_AGENT_ID_ALIASES)

# --- team.json override: load at startup, replace ALLOWED_ROUTES + AGENT_ID_ALIASES ---
_TEAM_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team.json")
_RUNTIME_TEAM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime_team.json")
_DYNAMIC_ROUTE_SKIP = {"", "all", "all_managers", "leads", "system", "user", "ui", "watcher"}


def _load_team_routes_and_aliases() -> None:
    """Load team.json and derive ALLOWED_ROUTES from shared routing_policy."""
    global ALLOWED_ROUTES, AGENT_ID_ALIASES  # noqa: PLW0603
    team: dict = {"agents": [], "teams": []}
    if os.path.exists(_TEAM_JSON_PATH):
        try:
            with open(_TEAM_JSON_PATH) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                team = loaded
        except Exception as exc:
            print(f"[watcher] Failed to load team.json: {exc}", flush=True)

    routes = shared_derive_routes(team)
    aliases = shared_derive_aliases(team, default_aliases=DEFAULT_AGENT_ID_ALIASES)

    # Merge active runtime overlay routes (ephemeral project_config/runtime teams)
    if os.path.exists(_RUNTIME_TEAM_PATH):
        try:
            with open(_RUNTIME_TEAM_PATH) as f:
                runtime_overlay = json.load(f)
        except Exception as exc:
            print(f"[watcher] Failed to load runtime_team.json: {exc}", flush=True)
            runtime_overlay = None
        if isinstance(runtime_overlay, dict) and runtime_overlay.get("active"):
            for sender, targets in dict(runtime_overlay.get("routes", {}) or {}).items():
                routes.setdefault(str(sender), set()).update(
                    str(target) for target in (targets or []) if str(target).strip()
                )
            runtime_agents = runtime_overlay.get("agents", []) or []
            runtime_ids = {
                str(agent.get("id", "")).strip()
                for agent in runtime_agents
                if str(agent.get("id", "")).strip()
            }
            routes.setdefault("user", set()).update(runtime_ids)
            for agent in runtime_agents:
                aid = str(agent.get("id", "")).strip()
                aname = str(agent.get("name", "")).strip().lower()
                if aid and aname and re.match(r"^[a-z0-9_-]+$", aname):
                    aliases.setdefault(aname, aid)

    ALLOWED_ROUTES = routes
    print(f"[watcher] ALLOWED_ROUTES loaded from team.json ({len(routes)} entries, incl. team routes)", flush=True)
    AGENT_ID_ALIASES = aliases
    print(f"[watcher] AGENT_ID_ALIASES loaded from team.json ({len(aliases)} entries)", flush=True)


def _merge_registered_agent_routes(
    routes: dict[str, set[str]],
    registered_agent_ids: set[str],
) -> dict[str, set[str]]:
    """Augment static routes with live runtime-registered agents.

    Agents that exist only in the live runtime should still be reachable via
    Bridge output. We model them as an ephemeral overlay that is reachable from
    every existing sender and can reply to every existing sender.
    """
    merged = {sender: set(targets) for sender, targets in routes.items()}
    known_ids = set(merged)
    for targets in merged.values():
        known_ids.update(targets)

    dynamic_ids = {
        str(agent_id).strip()
        for agent_id in registered_agent_ids
        if str(agent_id).strip() not in _DYNAMIC_ROUTE_SKIP
    }
    runtime_only = dynamic_ids - known_ids
    if not runtime_only:
        return merged

    merged.setdefault("user", set()).update(runtime_only)
    existing_senders = {sender for sender in merged if sender not in _DYNAMIC_ROUTE_SKIP}
    for sender in existing_senders:
        merged.setdefault(sender, set()).update(runtime_only)

    reachable_targets = existing_senders | {"user"} | runtime_only
    for agent_id in runtime_only:
        merged.setdefault(agent_id, set()).update(reachable_targets - {agent_id})

    return merged


def _fetch_registered_agent_ids() -> set[str]:
    """Fetch live registered agent ids from the Bridge server."""
    try:
        payload = http_get_json(
            f"{BRIDGE_HTTP}/agents",
            timeout=5.0,
            headers=build_bridge_auth_headers(agent_id="backend"),
        )
    except Exception:
        return set()
    agents = payload.get("agents", [])
    if not isinstance(agents, list):
        return set()
    result: set[str] = set()
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agent_id", "")).strip()
        if agent_id:
            result.add(agent_id)
    return result


def _refresh_runtime_registered_routes() -> bool:
    """Merge live runtime registrations into ALLOWED_ROUTES.

    Returns True when the route graph changed.
    """
    global ALLOWED_ROUTES  # noqa: PLW0603
    merged = _merge_registered_agent_routes(ALLOWED_ROUTES, _fetch_registered_agent_ids())
    normalized_before = {k: tuple(sorted(v)) for k, v in ALLOWED_ROUTES.items()}
    normalized_after = {k: tuple(sorted(v)) for k, v in merged.items()}
    if normalized_after == normalized_before:
        return False
    ALLOWED_ROUTES = merged
    return True


_load_team_routes_and_aliases()
try:
    _refresh_runtime_registered_routes()
except Exception:
    pass

# W4: Track team.json mtime for dynamic route reload
_team_json_last_mtime: float = 0.0
try:
    _team_json_last_mtime = os.path.getmtime(_TEAM_JSON_PATH)
except OSError:
    pass
_runtime_team_last_mtime: float = 0.0
try:
    _runtime_team_last_mtime = os.path.getmtime(_RUNTIME_TEAM_PATH)
except OSError:
    pass


async def _team_json_reload_daemon(interval: int = 30) -> None:
    """Periodically check team.json for changes and reload routes if modified."""
    global _team_json_last_mtime, _runtime_team_last_mtime  # noqa: PLW0603
    while True:
        await asyncio.sleep(interval)
        try:
            current_mtime = os.path.getmtime(_TEAM_JSON_PATH) if os.path.exists(_TEAM_JSON_PATH) else 0.0
            current_runtime_mtime = os.path.getmtime(_RUNTIME_TEAM_PATH) if os.path.exists(_RUNTIME_TEAM_PATH) else 0.0
            if current_mtime != _team_json_last_mtime or current_runtime_mtime != _runtime_team_last_mtime:
                _team_json_last_mtime = current_mtime
                _runtime_team_last_mtime = current_runtime_mtime
                _load_team_routes_and_aliases()
                _refresh_runtime_registered_routes()
                _flush(f"[watcher] W4: team.json changed — routes reloaded ({len(ALLOWED_ROUTES)} entries)")
                # Notify server to reload TEAM_CONFIG
                try:
                    resp = _bridge_post_json("http://127.0.0.1:9111/team/reload", {}, agent_id="system")
                    _flush(f"[watcher] W4: server TEAM_CONFIG reload: {resp}")
                except Exception as reload_exc:
                    _flush(f"[watcher] W4: server reload failed (non-critical): {reload_exc}")
            elif _refresh_runtime_registered_routes():
                _flush(f"[watcher] runtime routes refreshed ({len(ALLOWED_ROUTES)} entries)")
        except Exception as exc:
            _flush(f"[watcher] W4: team.json reload error: {exc}")


def _get_active_management_agents() -> list[str]:
    """Return IDs of active management-level agents (level <= 1) from team.json.

    Reads team.json fresh each time (active state can change via Agent Toggle).
    """
    result: list[str] = []
    if os.path.exists(_TEAM_JSON_PATH):
        try:
            with open(_TEAM_JSON_PATH) as f:
                team = json.load(f)
        except Exception:
            team = {}
        for agent in team.get("agents", []):
            if not agent.get("active", True):
                continue
            level = agent.get("level", 99)
            if level <= 1:
                result.append(agent["id"])
    if os.path.exists(_RUNTIME_TEAM_PATH):
        try:
            with open(_RUNTIME_TEAM_PATH) as f:
                overlay = json.load(f)
        except Exception:
            overlay = {}
        for agent in overlay.get("agents", []):
            aid = str(agent.get("id", "")).strip()
            if aid and int(agent.get("level", 99)) <= 1 and aid not in result:
                result.append(aid)
    return result


def _get_active_leads() -> list[str]:
    """Return IDs of active Lead-level agents (level == 1) from team.json."""
    result: list[str] = []
    if os.path.exists(_TEAM_JSON_PATH):
        try:
            with open(_TEAM_JSON_PATH) as f:
                team = json.load(f)
        except Exception:
            team = {}
        for agent in team.get("agents", []):
            if not agent.get("active", True):
                continue
            if agent.get("level") == 1:
                result.append(agent["id"])
    if os.path.exists(_RUNTIME_TEAM_PATH):
        try:
            with open(_RUNTIME_TEAM_PATH) as f:
                overlay = json.load(f)
        except Exception:
            overlay = {}
        for agent in overlay.get("agents", []):
            aid = str(agent.get("id", "")).strip()
            if aid and int(agent.get("level", 99)) == 1 and aid not in result:
                result.append(aid)
    return result


def _get_team_members(team_id: str) -> list[str]:
    """Return IDs of all active members of a team (by team id from teams[])."""
    if os.path.exists(_RUNTIME_TEAM_PATH):
        try:
            with open(_RUNTIME_TEAM_PATH) as f:
                overlay = json.load(f)
        except Exception:
            overlay = {}
        for team_def in overlay.get("teams", []):
            if team_def.get("id") == team_id:
                members = set(team_def.get("members", []))
                lead = team_def.get("lead", "")
                if lead:
                    members.add(lead)
                return sorted(m for m in members if m)
    if not os.path.exists(_TEAM_JSON_PATH):
        return []
    try:
        with open(_TEAM_JSON_PATH) as f:
            team = json.load(f)
    except Exception:
        return []
    for team_def in team.get("teams", []):
        if team_def.get("id") == team_id:
            members = set(team_def.get("members", []))
            lead = team_def.get("lead", "")
            if lead:
                members.add(lead)
            # Filter to active agents only
            active_ids = {a["id"] for a in team.get("agents", []) if a.get("active", True)}
            return [m for m in members if m in active_ids]
    return []


# Direct session name overrides: bridge-ID → full tmux session name
# Bypasses the acw_ prefix convention for non-standard session names
SESSION_NAME_OVERRIDES: dict[str, str] = {}

# Extra tmux sessions (currently unused, kept for future multi-session needs)
MULTI_SESSION_MAP: dict[str, list[str]] = {}

# Deduplication: letzte 200 Message-IDs merken (Hardening M6: increased from 50)
_recent_injections: deque[str] = deque(maxlen=200)

# Rate Limiting pro Ziel-Session, nach Prioritaet
# user -> agent (direct): 0.5s, agent -> agent (direct): 1.0s, broadcast(all): 2.0s
_last_injection_time: dict[str, float] = {}
COOLDOWN_USER_DIRECT = 0.5
COOLDOWN_AGENT_DIRECT = 1.0
COOLDOWN_BROADCAST = 2.0
# Backwards-compat for existing tests/importers
INJECTION_COOLDOWN = COOLDOWN_BROADCAST

# Retry config
MAX_RETRIES = 3
RETRY_DELAYS = [0.3, 0.3, 0.4]

# Urgent-Interrupt config
_URGENT_TRIGGERS = {"stop", "stopp", "halt", "!!!", "sofort", "urgent", "notfall"}
_URGENT_COOLDOWN = 10.0  # Max 1 urgent per 10s per agent
_last_urgent_time: dict[str, float] = {}

# Persistent event logger (rotation: 5 MB, 3 backups)
_EVENT_LOGGER: logging.Logger | None = None


# Engine detection cache: agent_id → "claude" | "codex" | "shell"
_ENGINE_CACHE: dict[str, str] = {}

# Engine-specific compact commands (None = no compact available)
ENGINE_COMPACT_CMD: dict[str, str | None] = {
    "claude": "/compact",
    "gemini": "/compress",
    "codex": None,     # auto-managed, thread-based
    "qwen": None,      # kein Compact verfuegbar
    "shell": None,
}

# agents.conf cache: agent_id -> {"engine": str, "home_dir": str, "prompt_file": str}
_AGENT_META_CACHE: dict[str, dict[str, str]] | None = None
_AGENT_META_CACHE_STAMPS: tuple[float, float, float] | None = None

SYSTEM_NOTICE_COOLDOWN_SECONDS = 300
_last_system_notice_ts_by_agent: dict[str, float] = {}


def _resolve_tmux_agent_id(agent_id: str) -> str:
    """Map Bridge agent IDs to tmux session agent IDs."""
    normalized = (agent_id or "").strip()
    if not normalized:
        return normalized
    return AGENT_ID_ALIASES.get(normalized, normalized)


def _same_tmux_agent(a: str, b: str) -> bool:
    """Compare agent IDs after alias resolution."""
    return _resolve_tmux_agent_id(a) == _resolve_tmux_agent_id(b)


def _parse_system_agent_notice(content: str) -> tuple[str, str] | None:
    """Parse system WARN/RECOVERY agent notices.

    Examples:
      [WARN] agent:qwen2: ...
      [RECOVERY] agent:qwen2 ...
    """
    m = re.match(r"^\[(WARN|RECOVERY)\]\s+agent:([a-zA-Z0-9_-]+)\b", (content or ""))
    if not m:
        return None
    return m.group(1).lower(), m.group(2)


def _is_context_stop_message(content: str) -> bool:
    c = (content or "").lower()
    return ("context_stop" in c) or ("hard-stop" in c) or ("context kritisch" in c)


# --- System Message Noise Reduction ---
# Tags that are always delivered (critical system messages)
_SYSTEM_CRITICAL_TAGS = {
    "task_assignment", "task_completion", "mode_change",
    "context_stop", "buddy_frontdoor", "escalation",
}

# System message patterns that are noise for most agents
_SYSTEM_NOISE_PATTERNS = [
    "[HEARTBEAT_CHECK]",
    "[ONLINE]",
    "[RECOVERY]",
    "[WARN]",
    "[CONTEXT]",
    "[HEARTBEAT",
]

# Agent roles that should receive ALL system messages (managers/coordinators)
_SYSTEM_FULLACCESS_ROLES = {"manager", "projektleiter", "coordinator", "lead"}

# Cache: agent_id -> should_receive_all_system (loaded from team.json)
_system_filter_cache: dict[str, bool] = {}
_system_filter_cache_ts: float = 0.0


def _should_skip_system_message(recipient: str, content: str, meta: dict) -> bool:
    """Decide if a system message should be filtered (not delivered).

    Returns True if the message should be SKIPPED (noise reduction).
    Returns False if the message should be DELIVERED.

    Logic:
    - Critical messages (task assignments, mode changes, context stops) always pass
    - HEARTBEAT_CHECK, ONLINE, RECOVERY, WARN, CONTEXT are noise for most agents
    - Managers/coordinators (level <= 1) get everything
    - Workers (level >= 2) and concierge only get critical system messages
    """
    # Critical meta types always pass
    msg_type = (meta.get("type") or "").lower()
    if msg_type in _SYSTEM_CRITICAL_TAGS:
        return False

    # Context stop always passes
    if _is_context_stop_message(content):
        return False

    # Check if this is a noise pattern
    is_noise = False
    for pattern in _SYSTEM_NOISE_PATTERNS:
        if pattern in content:
            is_noise = True
            break

    if not is_noise:
        # Not a recognized noise pattern — deliver
        return False

    # It's a noise message. Should this agent receive it?
    # Check team.json cache (refresh every 60s)
    global _system_filter_cache_ts
    now = time.time()
    if now - _system_filter_cache_ts > 60:
        _refresh_system_filter_cache()
        _system_filter_cache_ts = now

    # Managers/coordinators get everything
    if _system_filter_cache.get(recipient, False):
        return False

    # Everyone else: skip noise
    return True


def _refresh_system_filter_cache() -> None:
    """Refresh the system message filter cache from team.json."""
    global _system_filter_cache
    try:
        if not os.path.exists(_TEAM_JSON_PATH):
            return
        with open(_TEAM_JSON_PATH) as f:
            team = json.load(f)
        cache: dict[str, bool] = {}
        for agent in team.get("agents", []):
            aid = agent.get("id", "")
            level = agent.get("level", 99)
            role = (agent.get("role") or "").lower()
            # Level 0-1 (owner/manager) or manager roles get all system messages
            receives_all = level <= 1 or any(r in role for r in _SYSTEM_FULLACCESS_ROLES)
            cache[aid] = receives_all
        _system_filter_cache = cache
    except Exception:
        pass  # Keep old cache on error


def _get_session_name(agent_id: str) -> str:
    """Get the full tmux session name for a bridge agent ID.

    Checks SESSION_NAME_OVERRIDES first (for non-standard names),
    then falls back to acw_ prefix convention.
    """
    if agent_id in SESSION_NAME_OVERRIDES:
        return SESSION_NAME_OVERRIDES[agent_id]
    tmux_id = _resolve_tmux_agent_id(agent_id)
    if tmux_id in SESSION_NAME_OVERRIDES:
        return SESSION_NAME_OVERRIDES[tmux_id]
    return f"acw_{tmux_id}"


def _detect_session_engine(agent_id: str) -> str:
    """Detect whether a tmux session runs Claude, Codex, or a plain shell.

    Checks capture-pane content for engine-specific structural markers.
    Result is cached per agent_id (engine does not change mid-session).

    IMPORTANT: Use structural patterns (status bars, prompt chars), NOT keyword
    matches. Agents discuss each other by name — "codex" appearing in text
    does NOT mean the session runs Codex.
    """
    tmux_agent_id = _resolve_tmux_agent_id(agent_id)
    cached = _ENGINE_CACHE.get(tmux_agent_id)
    if cached:
        return cached

    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-200"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return "claude"  # default fallback
        content = result.stdout or ""
        # Codex: status bar "gpt-*-codex" OR prompt char › (U+203A) at line start
        if re.search(r'gpt-[\d.]+-codex', content) or re.search(r'codex\s+\w+\s*·\s*\d+%\s*left', content):
            _ENGINE_CACHE[tmux_agent_id] = "codex"
            return "codex"
        # Codex prompt char › (U+203A) at line start — distinct from Claude ❯ (U+276F)
        if re.search(r'(?m)^\s*›', content) and "❯" not in content:
            _ENGINE_CACHE[tmux_agent_id] = "codex"
            return "codex"
        # Qwen: banner ("Qwen Code"/"Qwen OAuth") or persistent markers (✦ response prefix, "? for shortcuts" status bar)
        if re.search(r'Qwen\s+Code', content) or re.search(r'Qwen\s+OAuth', content, re.IGNORECASE) or (re.search(r'(?m)^\s*✦', content) and "❯" not in content and "? for shortcuts" in content):
            _ENGINE_CACHE[tmux_agent_id] = "qwen"
            return "qwen"
        # Gemini CLI markers: "Gemini CLI" banner, or gemini-specific status patterns
        if re.search(r'Gemini\s+CLI', content) or re.search(r'gemini\s+\d+\.\d+', content, re.IGNORECASE) or ("✦" in content and "❯" not in content and "? for shortcuts" not in content and re.search(r'memory', content, re.IGNORECASE)):
            _ENGINE_CACHE[tmux_agent_id] = "gemini"
            return "gemini"
        # Claude CLI markers (structural: prompt char ❯, permission line)
        if "❯" in content or "bypass permissions" in content:
            _ENGINE_CACHE[tmux_agent_id] = "claude"
            return "claude"
        # No CLI markers → plain shell (e.g. Ordo session)
        _ENGINE_CACHE[tmux_agent_id] = "shell"
        return "shell"
    except Exception:
        pass
    _ENGINE_CACHE[tmux_agent_id] = "claude"
    return "claude"


def invalidate_engine_cache(agent_id: str | None = None) -> None:
    """Clear engine cache for one or all agents.

    Call after session restart so re-detection runs on next check.
    """
    if agent_id:
        tmux_id = _resolve_tmux_agent_id(agent_id)
        _ENGINE_CACHE.pop(tmux_id, None)
    else:
        _ENGINE_CACHE.clear()


def is_agent_at_prompt(agent_id: str) -> bool:
    """Check if agent's tmux session shows a prompt (ready for input).

    Engine-aware prompt detection. Checks ALL last non-empty lines (not just
    the last one) because engines may show status bars below the prompt.

    - Claude: "❯" prompt, "bypass permissions", "esc to interrupt"
    - Codex: "›" prompt, status bar with "gpt-*-codex" below prompt
    - Shell: Standard bash/zsh prompt ($, %, #, ➜) for Ordo sessions.
    """
    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False

        lines = (result.stdout or "").strip().splitlines()
        if not lines:
            return False

        # Check last 5 non-empty lines — engines show status bars below prompt
        last_lines = [l.strip() for l in lines[-5:] if l.strip()]
        if not last_lines:
            return False  # Empty screen = crash or loading, NOT prompt

        engine = _detect_session_engine(agent_id)

        if engine == "codex":
            # S2-F3 FIX: Only match › (U+203A), NOT > (too broad — matches shell output)
            # Status line alone is NOT sufficient — agent could be generating with status visible
            for line in last_lines:
                if re.match(r'^\s*›\s*$', line):            # Empty › prompt line
                    return True
                if re.match(r'^\s*›\s+\S', line):           # › prompt with text after
                    return True
            return False

        if engine == "qwen":
            # Qwen prompt: > at line start (simple greater-than)
            for line in last_lines:
                if re.match(r'^\s*>\s*$', line):        # Empty prompt line
                    return True
                if re.match(r'^\s*>\s+\S', line):       # Prompt with text after
                    return True
            return False

        if engine == "shell":
            last = last_lines[-1]
            shell_patterns = [
                bool(re.match(r'^.*[\$%#➜]\s*$', last)),
                bool(re.match(r'^\s*[\$%#➜]\s', last)),
            ]
            return any(shell_patterns)

        # Claude prompt patterns — check ALL last lines (status bar may follow)
        for line in last_lines:
            prompt_patterns = [
                bool(re.match(r'^\s*[❯>]\s*$', line)),
                bool(re.match(r'^\s*❯\s+\S', line)),
                "bypass permissions" in line,
                "What should Claude do" in line,
                # NOTE: "esc to interrupt" = Claude WORKING (spinner). NOT a prompt.
                # Removed — false positive that would nudge active agents.
            ]
            if any(prompt_patterns):
                return True
        return False
    except Exception:
        return False


def _is_agent_at_bash_prompt(agent_id: str) -> bool:
    """Detect if a Claude/Codex agent has crashed to bare bash/zsh prompt.

    When a CLI session exits (context exhaustion, API error), the agent
    lands on a naked shell prompt. Messages injected there get interpreted
    as shell commands → syntax errors. This function detects that state.

    ISSUE-002 V2 Fix.
    """
    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False
        lines = (result.stdout or "").strip().splitlines()
        if not lines:
            return False
        last_lines = [l.strip() for l in lines[-5:] if l.strip()]
        if not last_lines:
            return False
        # Bash/zsh prompt: user@host:path$ or path$ or just $
        for line in last_lines[-2:]:
            if re.match(r'^.*@.*[:~].*\$\s*$', line):
                return True
            # Also match "Resume this session with:" — Claude CLI exit message
            if "Resume this session with:" in line:
                return True
        return False
    except Exception:
        return False


def _is_agent_at_oauth_prompt(agent_id: str) -> bool:
    """Detect if a Claude agent is stuck at the OAuth/onboarding prompt.

    After CLI updates or token expiry, Claude Code shows an OAuth login screen
    with a URL and "Paste code here if prompted >". The agent cannot proceed
    without manual intervention. This state is distinct from both the CLI prompt
    (has ❯) and the bash prompt (has $).

    ISSUE: Health-checker and watcher previously ignored this state entirely,
    leaving agents stuck indefinitely.
    """
    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False
        lines = (result.stdout or "").strip().splitlines()
        if not lines:
            return False
        # Check last 5 non-empty lines for the specific OAuth prompt line.
        # "Paste code here if prompted >" is the definitive indicator — it only
        # appears as an interactive prompt from Claude Code's OAuth flow, never
        # in normal CLI output. Checking the tail avoids false positives from
        # tool output that might contain OAuth-related strings mid-screen.
        last_lines = [l.strip() for l in lines[-5:] if l.strip()]
        for line in last_lines:
            if "Paste code here if prompted" in line:
                return True
        return False
    except Exception:
        return False


def _reset_idle_counter(agent_id: str) -> None:
    """Reset the stop-hook idle counter for an agent (work arrived)."""
    idle_file = f"/tmp/bridge_idle_counter_{agent_id}"
    try:
        with open(idle_file, "w") as f:
            f.write("0")
    except OSError:
        pass


def _inject_into_session(session_name: str, text: str) -> bool:
    """Inject text via tmux buffer paste + Enter.

    Using load-buffer/paste-buffer avoids shell/key escaping issues from send-keys text mode.
    """
    try:
        load = subprocess.run(
            ["tmux", "load-buffer", "-b", TMUX_INJECT_BUFFER, "-"],
            input=text,
            capture_output=True, text=True, timeout=5,
        )
        if load.returncode != 0:
            return False

        paste = subprocess.run(
            ["tmux", "paste-buffer", "-b", TMUX_INJECT_BUFFER, "-t", session_name],
            capture_output=True, text=True, timeout=3,
        )
        if paste.returncode != 0:
            return False

        # Small delay — some CLIs (Qwen, Codex) need time to process pasted text
        time.sleep(0.2)

        enter = subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Enter"],
            capture_output=True, text=True, timeout=5,
        )
        if enter.returncode != 0:
            return False

        # Double-tap Enter for CLIs that buffer the first one
        time.sleep(0.1)
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Enter"],
            capture_output=True, text=True, timeout=5,
        )
        return True
    except Exception:
        return False


def _inject_via_send_keys(session_name: str, text: str) -> bool:
    """Inject text via tmux send-keys -l + Enter.

    Used for CLIs that don't process paste-buffer (e.g., Codex).
    send-keys -l sends text literally, bypassing key interpretation.
    """
    try:
        send = subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "-l", text],
            capture_output=True, text=True, timeout=5,
        )
        if send.returncode != 0:
            return False

        time.sleep(0.2)

        enter = subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Enter"],
            capture_output=True, text=True, timeout=5,
        )
        return enter.returncode == 0
    except Exception:
        return False


def smart_inject(agent_id: str, text: str) -> bool:
    """Inject notification into tmux session.

    Engine-aware: Codex needs send-keys -l (ignores paste-buffer),
    all others use load-buffer + paste-buffer + Enter.
    """
    session_name = _get_session_name(agent_id)
    engine = _detect_session_engine(agent_id)
    if engine == "codex":
        return _inject_via_send_keys(session_name, text)
    return _inject_into_session(session_name, text)


def _confirm_injection_visible(agent_id: str, notification: str) -> bool:
    """Best-effort confirmation: verify notification text appears in pane output."""
    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-200"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False
        pane_text = " ".join((result.stdout or "").split())
        needle = " ".join(notification.split())
        return bool(needle) and needle in pane_text
    except Exception:
        return False


def _escape_for_tmux(text: str) -> str:
    """Escape preview characters for notification readability in tests/UI."""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace("'", "\\'")
    text = text.replace('"', '\\"')
    return text


def format_notification(sender: str, content: str, engine: str = "claude") -> str:
    """Format a SHORT notification for tmux injection.

    IMPORTANT: NO message content in the notification! Content delivery happens
    exclusively via bridge_receive() (MCP). Including content here causes
    dual-delivery: agent responds to the preview AND to bridge_receive() result.

    The notification is a PUSH TRIGGER only — it wakes the agent up so it
    calls bridge_receive() to get the actual message via MCP (single channel).
    """
    sender_hint = str(sender).replace("'", "\\'")
    if engine in ("codex", "qwen"):
        # GPT/Qwen models need explicit imperative instructions to act
        return (
            f"Neue Nachricht von {sender} — "
            f"AUFTRAG: 1) Rufe bridge_receive() auf. "
            f"2) Lies und verarbeite die Nachricht. "
            f"3) Antworte dem Sender via bridge_send(to='{sender_hint}', content='...'). "
            f"Starte JETZT."
        )

    return f"Neue Nachricht von {sender} — Pruefe bridge_receive() fuer Details."


async def inject_with_retry(agent_id: str, sender: str, content: str, msg_id: str, *, urgent: bool = False) -> bool:
    """Inject message notification with smart retry logic.

    Strategy:
    1. Check if agent is at prompt
    2. If yes: inject immediately
    3. If no: wait and retry up to MAX_RETRIES times
    4. Each retry waits longer (exponential backoff)

    Urgent mode (user-only): ESC-interrupt the agent first, wait for prompt,
    then inject. Falls back to normal retry if prompt not available after 5s.
    """
    engine = await asyncio.to_thread(_detect_session_engine, agent_id)

    # ISSUE-003: Check if agent is stuck at OAuth prompt
    if await asyncio.to_thread(_is_agent_at_oauth_prompt, agent_id):
        _flush(f"[watcher] #{msg_id} {agent_id}: STUCK at OAuth prompt. Killing session + triggering restart.")
        invalidate_engine_cache(agent_id)
        session_name = _get_session_name(agent_id)
        try:
            await _async_run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
        try:
            await _async_run(
                ["curl", "-s", "-X", "POST",
                 f"http://127.0.0.1:9111/agents/{agent_id}/start",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"from": "watcher_oauth_recovery"})],
                capture_output=True, timeout=5,
            )
        except Exception as e:
            _flush(f"[watcher] OAuth restart request failed for {agent_id}: {e}")
        return False  # Message stays in queue for after restart

    # ISSUE-002 V2: Check if agent crashed to bash prompt
    if await asyncio.to_thread(_is_agent_at_bash_prompt, agent_id):
        _flush(f"[watcher] #{msg_id} {agent_id}: CRASHED to bash prompt. Killing session + triggering restart.")
        invalidate_engine_cache(agent_id)
        # Kill the dead tmux session FIRST — otherwise POST /start returns "already_running"
        session_name = _get_session_name(agent_id)
        try:
            await _async_run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
        try:
            await _async_run(
                ["curl", "-s", "-X", "POST",
                 f"http://127.0.0.1:9111/agents/{agent_id}/start",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"from": "watcher_recovery"})],
                capture_output=True, timeout=5,
            )
        except Exception as e:
            _flush(f"[watcher] restart request failed for {agent_id}: {e}")
        return False  # Don't inject into bash — message stays in queue for after restart

    started = time.perf_counter()
    last_reason = "not_at_prompt"

    # ── Urgent-Interrupt (Stufe 3): ESC → wait_for_prompt → inject ──
    if urgent and sender == "user":
        # Cooldown: max 1 urgent per 10s per agent
        _now = time.time()
        _last = _last_urgent_time.get(agent_id, 0.0)
        if _now - _last < _URGENT_COOLDOWN:
            _flush(f"[watcher] #{msg_id} URGENT {sender}→{agent_id}: cooldown ({_URGENT_COOLDOWN - (_now - _last):.1f}s remaining)")
            urgent = False  # Fall through to normal delivery
        else:
            _last_urgent_time[agent_id] = _now

    if urgent and sender == "user":
        at_prompt = await asyncio.to_thread(is_agent_at_prompt, agent_id)
        if not at_prompt:
            _flush(f"[watcher] #{msg_id} URGENT {sender}→{agent_id}: ESC-Interrupt")
            try:
                from tmux_manager import interrupt_agent as _interrupt_agent
                await asyncio.to_thread(_interrupt_agent, agent_id, engine or "claude")
            except Exception as exc:
                _flush(f"[watcher] #{msg_id} URGENT interrupt failed: {exc}")
            # Wait up to 5s for prompt
            _urgent_timeout = 5.0
            _urgent_start = time.perf_counter()
            while time.perf_counter() - _urgent_start < _urgent_timeout:
                await asyncio.sleep(0.5)
                at_prompt = await asyncio.to_thread(is_agent_at_prompt, agent_id)
                if at_prompt:
                    break
            if at_prompt:
                urgent_notification = format_notification(
                    sender, content, engine=engine,
                )
                # Override with URGENT prefix so agent knows it was interrupted
                urgent_notification = (
                    "URGENT: Du wurdest unterbrochen. "
                    + urgent_notification
                    + " Setze danach deinen laufenden Task fort."
                )
                ok = await asyncio.to_thread(smart_inject, agent_id, urgent_notification)
                if ok:
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    _reset_idle_counter(agent_id)
                    _flush(f"[watcher] #{msg_id} URGENT {sender}→{agent_id}: injiziert nach ESC-Interrupt")
                    _log_event(msg_id, sender, agent_id, "urgent_interrupted", latency_ms)
                    return True
            _flush(f"[watcher] #{msg_id} URGENT {sender}→{agent_id}: Prompt nicht erreicht nach ESC, Fallback auf normal")

    notification = format_notification(sender, content, engine=engine)

    for attempt in range(MAX_RETRIES):
        at_prompt = await asyncio.to_thread(is_agent_at_prompt, agent_id)

        if at_prompt:
            ok = await asyncio.to_thread(smart_inject, agent_id, notification)
            if ok:
                await asyncio.sleep(0.5)
                confirmed = await asyncio.to_thread(_confirm_injection_visible, agent_id, notification)
                latency_ms = int((time.perf_counter() - started) * 1000)
                _reset_idle_counter(agent_id)  # ISSUE-002: Work arrived, reset idle
                if confirmed:
                    _flush(f"[watcher] #{msg_id} {sender}→{agent_id}: injiziert+confirmed (Versuch {attempt+1})")
                    _log_event(msg_id, sender, agent_id, "confirmed", latency_ms)
                else:
                    _flush(f"[watcher] #{msg_id} {sender}→{agent_id}: injiziert aber unconfirmed (Versuch {attempt+1})")
                    _log_event(msg_id, sender, agent_id, "unconfirmed", latency_ms)
                return True
            else:
                last_reason = "inject_failed"
                _flush(f"[watcher] #{msg_id} {sender}→{agent_id}: inject fehlgeschlagen (Versuch {attempt+1})")
        else:
            last_reason = "not_at_prompt"
            _flush(f"[watcher] #{msg_id} {sender}→{agent_id}: nicht am Prompt (Versuch {attempt+1}/{MAX_RETRIES})")

        if attempt < MAX_RETRIES - 1:
            base_delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            jitter = random.uniform(0.0, 1.0)
            await asyncio.sleep(base_delay + jitter)

    # Agent is not at prompt after all retries.
    # Only Claude with bypassPermissions reliably calls bridge_receive().
    # Codex, Gemini, Qwen and Claude without bypass need force-inject.
    latency_ms = int((time.perf_counter() - started) * 1000)
    if engine == "claude":
        # Claude agents with bypassPermissions reliably use bridge_receive()
        _flush(f"[watcher] #{msg_id} {sender}→{agent_id}: Agent nicht am Prompt — Nachricht bleibt im Buffer (bridge_receive)")
        _log_event(msg_id, sender, agent_id, "buffered_no_force", latency_ms)
        return False

    # Codex/Gemini/Qwen: force-inject is the only reliable delivery path
    ok = await asyncio.to_thread(smart_inject, agent_id, notification)
    if ok:
        _flush(f"[watcher] #{msg_id} {sender}→{agent_id}: FALLBACK force-injiziert ({engine})")
        _log_event(msg_id, sender, agent_id, f"fallback_injected_{engine}", latency_ms)
        return True
    _flush(f"[watcher] #{msg_id} {sender}→{agent_id}: ALLE VERSUCHE FEHLGESCHLAGEN ({engine})")
    _log_event(msg_id, sender, agent_id, f"all_failed_{engine}", latency_ms)
    return False


async def _inject_to_extra_sessions(tmux_target: str, sender: str, content: str, msg_id: str) -> None:
    """Inject notification into additional tmux sessions for a target."""
    extra_sessions = MULTI_SESSION_MAP.get(tmux_target, [])
    for session_name in extra_sessions:
        try:
            r = await _async_run(["tmux", "has-session", "-t", session_name],
                                capture_output=True, timeout=3)
            if r.returncode != 0:
                continue
            notification = format_notification(sender, content)
            started = time.perf_counter()
            ok = await asyncio.to_thread(_inject_into_session, session_name, notification)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if ok:
                _flush(f"[watcher] #{msg_id} {sender}→{session_name}: injiziert (extra-session)")
                _log_event(msg_id, sender, session_name, "extra_injected", latency_ms)
            else:
                _flush(f"[watcher] #{msg_id} {sender}→{session_name}: extra-inject fehlgeschlagen")
                _log_event(msg_id, sender, session_name, "extra_inject_failed", latency_ms)
        except Exception as e:
            _flush(f"[watcher] #{msg_id} {sender}→{session_name}: FEHLER {e}")
            _log_event(msg_id, sender, session_name, "extra_error", 0)


def _cooldown_for_message(sender: str, recipient: str) -> float:
    """Return cooldown by message priority."""
    if recipient in ("all", "all_managers"):
        return COOLDOWN_BROADCAST
    if sender == "user":
        return COOLDOWN_USER_DIRECT
    return COOLDOWN_AGENT_DIRECT


def _is_route_allowed(sender: str, recipient: str) -> bool:
    if sender == "user":
        return True  # Leo-Override: Product Owner kann alle erreichen
    if sender in {"system", "watcher"}:
        return True  # System messages always delivered (context warnings, task notifications, etc.)
    if recipient in ("all", "all_managers", "leads") or recipient.startswith("team:"):
        # Broadcasts erlaubt, aber targets werden in watch() gefiltert
        return True
    allowed = ALLOWED_ROUTES.get(sender)
    if allowed is None:
        # S2-F8 FIX: Default-Deny for unknown senders (was default-allow)
        return False
    return recipient in allowed


def _load_agent_meta_cache() -> dict[str, dict[str, str]]:
    """Load agents.conf once and cache agent metadata."""
    global _AGENT_META_CACHE, _AGENT_META_CACHE_STAMPS

    def _mtime_or_zero(path: str) -> float:
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    current_stamps = (
        _mtime_or_zero(AGENTS_CONF),
        _mtime_or_zero(_TEAM_JSON_PATH),
        _mtime_or_zero(_RUNTIME_TEAM_PATH),
    )
    if _AGENT_META_CACHE is not None and _AGENT_META_CACHE_STAMPS == current_stamps:
        return _AGENT_META_CACHE

    cache: dict[str, dict[str, str]] = {}
    try:
        with open(AGENTS_CONF, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":", maxsplit=4)
                if len(parts) < 4:
                    continue
                agent_id = parts[0].strip()
                engine = parts[1].strip()
                home_dir = parts[2].strip()
                prompt_file = parts[3].strip()
                session_name = parts[4].strip() if len(parts) > 4 else ""
                if not agent_id or not home_dir:
                    continue
                cache[agent_id] = {
                    "engine": engine,
                    "home_dir": home_dir,
                    "prompt_file": prompt_file,
                    "session_name": session_name,
                }
    except OSError as exc:
        _flush(f"[watcher] WARN agents.conf nicht lesbar: {exc}")

    # Fallback: merge home_dir from team.json for agents not in agents.conf
    try:
        if os.path.exists(_TEAM_JSON_PATH):
            with open(_TEAM_JSON_PATH) as f:
                team_data = json.load(f)
            for agent in team_data.get("agents", []):
                aid = str(agent.get("id", "")).strip()
                hd = str(agent.get("home_dir", "")).strip()
                if aid and hd and aid not in cache:
                    cache[aid] = {
                        "engine": str(agent.get("engine", "claude")).strip(),
                        "home_dir": hd,
                        "prompt_file": "",
                        "session_name": "",
                    }
    except Exception as exc:
        _flush(f"[watcher] WARN team.json meta merge failed: {exc}")

    # Active runtime overlay wins for live runtime agents.
    try:
        if os.path.exists(_RUNTIME_TEAM_PATH):
            with open(_RUNTIME_TEAM_PATH) as f:
                runtime_data = json.load(f)
            if isinstance(runtime_data, dict) and runtime_data.get("active"):
                for agent in runtime_data.get("agents", []) or []:
                    aid = str(agent.get("id", "")).strip()
                    hd = str(agent.get("home_dir", "") or agent.get("workspace", "")).strip()
                    if not aid or not hd:
                        continue
                    existing = dict(cache.get(aid, {}))
                    cache[aid] = {
                        "engine": str(agent.get("engine", "")).strip() or existing.get("engine", "claude") or "claude",
                        "home_dir": hd,
                        "prompt_file": str(agent.get("prompt_file", "")).strip() or existing.get("prompt_file", ""),
                        "session_name": str(agent.get("session_name", "")).strip() or existing.get("session_name", ""),
                    }
    except Exception as exc:
        _flush(f"[watcher] WARN runtime_team.json meta merge failed: {exc}")

    _AGENT_META_CACHE = cache
    _AGENT_META_CACHE_STAMPS = current_stamps
    return cache


def _get_agent_home_dir(agent_id: str) -> str | None:
    """Return configured home directory for an agent from agents.conf cache."""
    cache = _load_agent_meta_cache()
    entry = cache.get(agent_id)
    if entry:
        return entry.get("home_dir")

    resolved = _resolve_tmux_agent_id(agent_id)
    entry = cache.get(resolved)
    if entry:
        return entry.get("home_dir")

    try:
        payload = http_get_json(f"{BRIDGE_HTTP}/agents/{quote(resolved)}", timeout=5.0)
    except Exception:
        return None

    for key in ("home_dir", "workspace", "project_root"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            return value
    return None


def _truncate_line(text: str, max_len: int = 220) -> str:
    """Normalize to one line and truncate for markdown logs."""
    compact = " ".join((text or "").split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


CONTEXT_BRIDGE_MESSAGE_LIMIT = 5
CONTEXT_BRIDGE_TASK_LIMIT = 10
CONTEXT_BRIDGE_REFRESH_INTERVAL = 300  # 5 minutes
CLI_DIARY_CAPTURE_LINES = 120
CLI_DIARY_TRANSCRIPT_LIMIT = 5
CLI_DIARY_MESSAGE_PREVIEW_LIMIT = 3
CLI_DIARY_TASK_PREVIEW_LIMIT = 5


def _context_bridge_agent_ids() -> list[str]:
    """Return all agent ids that should receive periodic CONTEXT_BRIDGE refreshes."""
    target_ids: set[str] = set(_load_agent_meta_cache().keys())
    target_ids.update(_fetch_registered_agent_ids())
    try:
        target_ids.update(_find_all_sessions())
    except Exception:
        pass
    return sorted(
        {
            str(agent_id).strip()
            for agent_id in target_ids
            if str(agent_id).strip() and str(agent_id).strip() not in _DYNAMIC_ROUTE_SKIP
        }
    )


def _fetch_recent_agent_messages(agent_id: str, limit: int = CONTEXT_BRIDGE_MESSAGE_LIMIT) -> list[dict[str, object]]:
    """Fetch the latest relevant messages for an agent, preferring /messages with /history fallback."""
    resolved = _resolve_tmux_agent_id(agent_id)
    bounded_limit = max(1, int(limit))
    history_limit = max(30, bounded_limit * 6)
    auth_headers = build_bridge_auth_headers(agent_id=resolved)
    endpoints = [
        f"{BRIDGE_HTTP}/messages?agent_id={quote(resolved)}&limit={bounded_limit}",
        f"{BRIDGE_HTTP}/history?limit={history_limit}",
    ]
    last_exc: Exception | None = None

    for endpoint in endpoints:
        try:
            payload = http_get_json(endpoint, timeout=5.0, headers=auth_headers)
        except Exception as exc:
            last_exc = exc
            continue

        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            return []

        filtered: list[dict[str, object]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            msg_from = str(item.get("from", "")).strip()
            msg_to = str(item.get("to", "")).strip()
            if _same_tmux_agent(msg_from, resolved) or _same_tmux_agent(msg_to, resolved):
                filtered.append(item)
        return filtered[-bounded_limit:]

    if last_exc is not None:
        raise last_exc
    return []


def _set_activity(agent_id: str, action: str, description: str) -> None:
    """Best-effort activity update for board/status visibility."""
    try:
        http_post_json(
            f"{BRIDGE_HTTP}/activity",
            {
                "agent_id": agent_id,
                "action": action,
                "description": description,
            },
            headers=build_bridge_auth_headers(agent_id=agent_id),
            timeout=5.0,
        )
    except Exception:
        pass


def _capture_cli_session_log(agent_id: str, history_lines: int = CLI_DIARY_CAPTURE_LINES) -> str:
    """Capture recent tmux pane output for diary snapshots."""
    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{max(1, int(history_lines))}"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return ""
        return result.stdout or ""
    except Exception:
        return ""


def _message_preview_lines(messages: list[dict[str, object]], limit: int = CLI_DIARY_MESSAGE_PREVIEW_LIMIT) -> list[str]:
    previews: list[str] = []
    for msg in messages[: max(1, int(limit))]:
        if not isinstance(msg, dict):
            continue
        msg_from = str(msg.get("from", "")).strip() or "?"
        msg_to = str(msg.get("to", "")).strip() or "?"
        content = _truncate_line(str(msg.get("content", "")), max_len=140)
        previews.append(f"{msg_from}->{msg_to}: {content}")
    return previews


def _task_preview_lines(tasks: list[dict[str, object]], limit: int = CLI_DIARY_TASK_PREVIEW_LIMIT) -> list[str]:
    previews: list[str] = []
    for task in tasks[: max(1, int(limit))]:
        if not isinstance(task, dict):
            continue
        title = str(task.get("title", "")).strip() or "?"
        state = str(task.get("state", "")).strip() or "?"
        previews.append(f"{title} (state={state})")
    return previews


def _inject_dynamic_claude_block(
    workspace: str, agent_id: str, mode: str,
    tasks: list[dict], action: str, description: str, timestamp: str,
) -> None:
    """Inject/update dynamic context block in the active CLI instruction file."""
    instruction_filename = detect_instruction_filename(workspace, agent_id)
    layout = resolve_agent_cli_layout(workspace, agent_id)
    instruction_path = first_existing_path(
        [
            os.path.join(layout["workspace"], instruction_filename),
            os.path.join(layout["home_dir"], instruction_filename),
            os.path.join(layout["project_root"], instruction_filename),
        ]
    )
    if not instruction_path:
        return

    START_MARKER = "<!-- DYNAMIC_CONTEXT_START -->"
    END_MARKER = "<!-- DYNAMIC_CONTEXT_END -->"

    task_lines = []
    for t in tasks[:10]:
        task_lines.append(f"- {t.get('title', '?')} (state={t.get('state', '?')})")
    if not task_lines:
        task_lines.append("- (keine aktiven Tasks)")

    dynamic_block = "\n".join([
        START_MARKER,
        f"## AKTUELLER KONTEXT (automatisch aktualisiert — NICHT manuell aendern)",
        f"Stand: {timestamp}",
        "",
        "### Aktive Tasks",
        *task_lines,
        "",
        "### Modus",
        mode,
        "",
        "### Letzte Aktivitaet",
        f"{action}: {description}",
        END_MARKER,
    ])

    try:
        existing = open(instruction_path, "r", encoding="utf-8").read()
        if START_MARKER in existing and END_MARKER in existing:
            import re as _re
            updated = _re.sub(
                _re.escape(START_MARKER) + r"[\s\S]*?" + _re.escape(END_MARKER),
                dynamic_block,
                existing,
                count=1,
            )
        else:
            updated = existing.rstrip() + "\n\n" + dynamic_block + "\n"
        with open(instruction_path, "w", encoding="utf-8") as fh:
            fh.write(updated)
        _flush(f"[watcher] {instruction_filename} dynamic block aktualisiert: {instruction_path}")
    except OSError as exc:
        _flush(f"[watcher] WARN {instruction_filename} injection fehlgeschlagen fuer {agent_id}: {exc}")


def _write_context_bridge(agent_id: str, context_pct: int | None = None) -> None:
    """Write CONTEXT_BRIDGE.md for an agent using live bridge status, messages, and tasks."""
    requested_context_pct = context_pct
    session_name = _get_session_name(agent_id)
    home_dir = _get_agent_home_dir(agent_id)
    if not home_dir:
        _flush(f"[watcher] WARN context-bridge: kein home_dir fuer {agent_id}")
        _log_event(f"context_{agent_id}", "watcher", agent_id, "context_bridge_failed", 0)
        return

    resolved_id = _resolve_tmux_agent_id(agent_id)
    role = "unknown"
    agent_mode = "normal"
    agent_status = "unknown"
    server_health = "unknown"
    activity_action = "unknown"
    activity_desc = ""
    activity_target = ""
    engine = "unknown"
    last_heartbeat = ""
    resume_id = ""
    cli_workspace = ""
    cli_project_root = ""
    cli_instruction_path = ""
    cli_identity_source = ""
    recent_messages: list[dict[str, object]] = []
    active_tasks: list[dict[str, object]] = []
    diary_bundle: dict[str, object] = {}

    # Global health snapshot for runtime status context.
    try:
        payload = http_get_json(f"{BRIDGE_HTTP}/health", timeout=5.0)
        server_health = str(payload.get("status", "unknown")).strip() or server_health
    except Exception as exc:
        _flush(f"[watcher] WARN context-bridge health fetch fehlgeschlagen fuer {agent_id}: {exc}")

    # Agent mode/status/details from single-agent endpoint.
    try:
        payload = http_get_json(f"{BRIDGE_HTTP}/agents/{quote(resolved_id)}", timeout=5.0)
        role = str(payload.get("role", "")).strip() or role
        agent_mode = str(payload.get("mode", "normal")).strip() or agent_mode
        agent_status = str(payload.get("status", "unknown")).strip() or agent_status
        engine = str(payload.get("engine", "")).strip() or engine
        last_heartbeat = str(payload.get("last_heartbeat", "")).strip()
        resume_id = str(payload.get("resume_id", "")).strip()
        cli_workspace = str(payload.get("workspace", "")).strip()
        cli_project_root = str(payload.get("project_root", "")).strip()
        cli_instruction_path = str(payload.get("instruction_path", "")).strip()
        cli_identity_source = str(payload.get("cli_identity_source", "")).strip()
        if context_pct is None:
            raw_context = payload.get("context_pct")
            if isinstance(raw_context, (int, float)):
                context_pct = max(0, min(100, int(raw_context)))
        activity = payload.get("activity")
        if isinstance(activity, dict):
            activity_action = str(activity.get("action", "unknown")).strip() or activity_action
            activity_desc = str(activity.get("description", "") or "")
            activity_target = str(activity.get("target", "") or "")
    except Exception as exc:
        _flush(f"[watcher] WARN context-bridge agent fetch fehlgeschlagen fuer {agent_id}: {exc}")

    # Open tasks from /task/queue.
    try:
        payload = http_get_json(
            f"{BRIDGE_HTTP}/task/queue?agent_id={quote(resolved_id)}&limit={CONTEXT_BRIDGE_TASK_LIMIT}",
            timeout=5.0,
            headers=build_bridge_auth_headers(agent_id=resolved_id),
        )
        tasks = payload.get("tasks", [])
        if isinstance(tasks, list):
            for t in tasks:
                if isinstance(t, dict) and t.get("state") not in ("done", "failed", "deleted"):
                    active_tasks.append(t)
    except Exception as exc:
        _flush(f"[watcher] WARN context-bridge tasks fetch fehlgeschlagen fuer {agent_id}: {exc}")

    # Last 5 relevant messages, preferring a dedicated /messages endpoint.
    try:
        recent_messages = _fetch_recent_agent_messages(resolved_id, limit=CONTEXT_BRIDGE_MESSAGE_LIMIT)
    except Exception as exc:
        _flush(f"[watcher] WARN context-bridge messages fetch fehlgeschlagen fuer {agent_id}: {exc}")

    msg_lines: list[str] = []
    for msg in recent_messages:
        ts = str(msg.get("timestamp", ""))
        msg_from = str(msg.get("from", ""))
        msg_to = str(msg.get("to", ""))
        content = _truncate_line(str(msg.get("content", "")))
        msg_lines.append(f"- [{ts}] {msg_from} -> {msg_to}: {content}")
    if not msg_lines:
        msg_lines.append("- (keine relevanten Nachrichten gefunden)")

    role_for_handoff = role or "unknown"
    ts_now = datetime.now(timezone.utc).isoformat()

    # Build task lines
    task_lines: list[str] = []
    for t in active_tasks[:CONTEXT_BRIDGE_TASK_LIMIT]:
        title = str(t.get("title", "?"))
        state = str(t.get("state", "?"))
        prio = str(t.get("priority", "?"))
        blocker = str(t.get("blocker_reason", "") or "").strip()
        blocker_suffix = f", blocker={blocker}" if blocker else ""
        task_lines.append(f"- {title} (state={state}, priority={prio}{blocker_suffix})")
    if not task_lines:
        task_lines.append("- (keine aktiven Tasks)")

    # Context percentage line
    ctx_line = f"- Context-Nutzung: {context_pct}%" if context_pct is not None else "- Context-Nutzung: UNKNOWN"
    activity_summary = f"{activity_action}: {activity_desc}" if activity_desc else activity_action
    if activity_target:
        activity_summary = f"{activity_summary} (Target: {activity_target})"

    cli_layout = resolve_agent_cli_layout(home_dir, resolved_id)
    agent_workspace = cli_workspace or cli_layout["workspace"] or home_dir
    cli_project_root = cli_project_root or cli_layout["project_root"]

    should_record_diary = requested_context_pct is not None
    if not should_record_diary:
        try:
            diary_bundle = execution_journal.build_agent_diary_bundle(agent_id=resolved_id, session_id=session_name)
        except Exception as exc:
            _flush(f"[watcher] WARN diary bundle read fehlgeschlagen fuer {agent_id}: {exc}")
            diary_bundle = {}
        if not diary_bundle:
            should_record_diary = True

    if should_record_diary:
        try:
            diary_event = "pre_compact_snapshot" if requested_context_pct is not None else "context_bridge_snapshot"
            transcript_text = _capture_cli_session_log(agent_id)
            execution_journal.append_cli_session_diary(
                agent_id=resolved_id,
                session_id=session_name,
                engine=engine,
                workspace=agent_workspace,
                project_root=cli_project_root,
                instruction_path=cli_instruction_path,
                resume_id=resume_id,
                cli_identity_source=cli_identity_source,
                event_type=diary_event,
                context_pct=context_pct,
                agent_status=agent_status,
                mode=agent_mode,
                activity_summary=activity_summary,
                task_titles=_task_preview_lines(active_tasks),
                message_previews=_message_preview_lines(recent_messages),
                transcript_text=transcript_text,
            )
        except Exception as exc:
            _flush(f"[watcher] WARN diary snapshot failed fuer {agent_id}: {exc}")

    if not diary_bundle:
        try:
            diary_bundle = execution_journal.build_agent_diary_bundle(agent_id=resolved_id, session_id=session_name)
        except Exception as exc:
            _flush(f"[watcher] WARN diary bundle build fehlgeschlagen fuer {agent_id}: {exc}")
            diary_bundle = {}

    diary_lines: list[str] = []
    if diary_bundle:
        bundle_id = str(diary_bundle.get("context_bundle_id", "") or "").strip()
        bundle_ts = str(diary_bundle.get("timestamp", "") or "").strip()
        bundle_event = str(diary_bundle.get("event_type", "") or "").strip()
        bundle_summary = str(diary_bundle.get("summary", "") or "").strip()
        bundle_resume_id = str(diary_bundle.get("resume_id", "") or "").strip()
        bundle_instruction = str(diary_bundle.get("instruction_path", "") or "").strip()
        bundle_workspace = str(diary_bundle.get("workspace", "") or "").strip()
        transcript_lines = diary_bundle.get("transcript_lines", [])
        if bundle_id:
            diary_lines.append(f"- Context-Bundle: {bundle_id}")
        if bundle_ts or bundle_event:
            diary_lines.append(f"- Letzter CLI-Snapshot: {bundle_ts or 'UNKNOWN'} ({bundle_event or 'snapshot'})")
        if bundle_resume_id:
            diary_lines.append(f"- Resume-ID: {bundle_resume_id}")
        if bundle_workspace:
            diary_lines.append(f"- Workspace: {bundle_workspace}")
        if bundle_instruction:
            diary_lines.append(f"- Instructions: {bundle_instruction}")
        if bundle_summary:
            diary_lines.append(f"- Journal-Zusammenfassung: {bundle_summary}")
        if isinstance(transcript_lines, list):
            for line in transcript_lines[-CLI_DIARY_TRANSCRIPT_LIMIT:]:
                clean = _truncate_line(str(line), max_len=180)
                if clean:
                    diary_lines.append(f"- CLI-Log: {clean}")
    if not diary_lines:
        diary_lines.append("- (kein CLI-Diary-Snapshot vorhanden)")

    bridge_text = "\n".join(
        [
            f"# Context Bridge — {agent_id} ({role_for_handoff})",
            f"Stand: {ts_now}",
            "",
            "## HANDOFF",
            f'Du bist {agent_id} — {role_for_handoff}. Bridge-ID: {agent_id}.',
            f'Registriere dich: bridge_register(agent_id="{agent_id}", role="{role_for_handoff}")',
            "Lies SOUL.md. Dann bridge_receive().",
            "",
            "## STATUS",
            f"- Server-Health: {server_health}",
            f"- Agent-Status: {agent_status}",
            f"- Modus: {agent_mode}",
            f"- Engine: {engine}",
            f"- Letzte Heartbeat: {last_heartbeat or 'UNKNOWN'}",
            ctx_line,
            f"- Letzte Aktivitaet: {activity_summary}",
            "",
            "## OFFENE TASKS",
            *task_lines,
            "",
            "## LETZTE 5 NACHRICHTEN",
            *msg_lines,
            "",
            "## CLI_JOURNAL",
            *diary_lines,
            "",
            "## SESSION",
            f"tmux: {session_name}",
            "",
            "## NAECHSTER SCHRITT",
            "Lies bridge_receive() fuer neue Nachrichten und arbeite weiter an deiner letzten Aktivitaet.",
            "",
        ]
    )

    # The CLI workspace is the canonical persistence target.
    try:
        os.makedirs(agent_workspace, exist_ok=True)
        out_file = os.path.join(agent_workspace, "CONTEXT_BRIDGE.md")
        fd, tmp = tempfile.mkstemp(dir=agent_workspace, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(bridge_text)
            os.replace(tmp, out_file)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        _flush(f"[watcher] context-bridge geschrieben: {out_file}")
        _log_event(f"context_{agent_id}", "watcher", agent_id, "context_bridge_written", 0)
    except OSError as exc:
        _flush(f"[watcher] WARN context-bridge write fehlgeschlagen fuer {agent_id}: {exc}")
        _log_event(f"context_{agent_id}", "watcher", agent_id, "context_bridge_failed", 0)

    # ── M6: Dynamic instruction file block injection ──
    _inject_dynamic_claude_block(agent_workspace, agent_id, agent_mode, active_tasks,
                                  activity_action, activity_desc, ts_now)

    # Fix B: Sync context summary to agent_state JSON so CONTEXT RESTORE is up-to-date
    summary_parts = [
        f"Status: {agent_status}",
        f"Modus: {agent_mode}",
        f"Open tasks: {len(active_tasks)}",
    ]
    if activity_action and activity_action != "unknown":
        summary_parts.append(f"Letzte Aktivitaet: {activity_summary}")
    context_summary = ". ".join(summary_parts) if summary_parts else f"Context-Bridge geschrieben um {ts_now}"
    try:
        http_post_json(
            f"{BRIDGE_HTTP}/state/{quote(resolved_id)}",
            {"context_summary": context_summary},
            headers=build_bridge_auth_headers(agent_id=resolved_id),
            timeout=5.0,
        )
        _flush(f"[watcher] agent_state synced for {agent_id}")
    except Exception as exc:
        _flush(f"[watcher] WARN agent_state sync failed for {agent_id}: {exc}")


def _refresh_context_bridges_once() -> None:
    """Update CONTEXT_BRIDGE.md for all known agents once."""
    for agent_id in _context_bridge_agent_ids():
        try:
            _write_context_bridge(agent_id)
        except Exception as exc:
            _flush(f"[watcher] WARN periodic context-bridge refresh failed fuer {agent_id}: {exc}")


async def _context_bridge_refresh_daemon(interval: int = CONTEXT_BRIDGE_REFRESH_INTERVAL) -> None:
    """Periodic refresh of CONTEXT_BRIDGE.md for all known agents."""
    bounded_interval = max(60, int(interval))
    while True:
        await asyncio.to_thread(_refresh_context_bridges_once)
        await asyncio.sleep(bounded_interval)


def _get_context_usage(agent_id: str) -> int | None:
    """Parse context usage percentage from agent status line."""
    session_name = _get_session_name(agent_id)

    # Primary: read signal file written by context_statusline.sh
    signal_file = f"/tmp/context_pct_{session_name}"
    try:
        with open(signal_file) as f:
            pct = int(f.read().strip())
            return max(0, min(100, pct))
    except (FileNotFoundError, ValueError, OSError):
        pass

    # Fallback: capture-pane (for Qwen/Codex without statusline script)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-200"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return None
        content = result.stdout or ""
    except Exception:
        return None

    engine = _detect_session_engine(agent_id)

    if engine == "codex":
        matches = re.findall(r'(\d+)\s*%\s*left', content, re.IGNORECASE)
        if not matches:
            return None
        pct_left = int(matches[-1])
        return max(0, min(100, 100 - pct_left))

    if engine == "qwen":
        matches = re.findall(r'(\d+(?:\.\d+)?)\s*%\s*context used', content, re.IGNORECASE)
        if not matches:
            return None
        pct_used = int(float(matches[-1]))
        return max(0, min(100, pct_used))

    if engine == "gemini":
        # Gemini: "showMemoryUsage" or "X% memory" or "memory: X%"
        mem_matches = re.findall(r'(\d+(?:\.\d+)?)\s*%\s*(?:memory|mem)', content, re.IGNORECASE)
        if mem_matches:
            pct_used = int(float(mem_matches[-1]))
            return max(0, min(100, pct_used))
        # Fallback: "memory X%" or "X/Y tokens"
        mem_matches2 = re.findall(r'(?:memory|mem)[\s:]+(\d+(?:\.\d+)?)\s*%', content, re.IGNORECASE)
        if mem_matches2:
            return max(0, min(100, int(float(mem_matches2[-1]))))
        return None

    if engine == "claude":
        # Claude zeigt "Context left until auto-compact: X%"
        left_matches = re.findall(r'Context left.*?(\d+)\s*%', content, re.IGNORECASE)
        if left_matches:
            pct_left = int(left_matches[-1])
            return max(0, min(100, 100 - pct_left))
        # Fallback: "X% context used"
        used_matches = re.findall(r'(\d+)\s*%\s*context used', content, re.IGNORECASE)
        if used_matches:
            return max(0, min(100, int(used_matches[-1])))
        return None

    return None


async def _force_context_stop(agent_id: str, pct_used: int) -> None:
    """Hard-stop sequence for critical context usage.

    Deterministic: polls for prompt before sending engine-specific compact command.
    Stage 3 injection already happened at 90% — no additional text injection here.
    """
    session_name = _get_session_name(agent_id)

    # Determine engine-specific compact command
    engine = _detect_session_engine(agent_id)
    compact_cmd = ENGINE_COMPACT_CMD.get(engine)
    if compact_cmd is None:
        # Engine has no compact — only write CONTEXT_BRIDGE.md
        _flush(f"[watcher] {agent_id}: Engine '{engine}' hat keinen Compact-Befehl. Nur CONTEXT_BRIDGE.md geschrieben.")
        await asyncio.to_thread(_write_context_bridge, agent_id, pct_used)
        _log_event(f"context_{agent_id}", "watcher", agent_id, "no_compact_available", 0)
        return

    async def _session_alive() -> bool:
        try:
            r = await _async_run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True, timeout=3,
            )
            return r.returncode == 0
        except Exception:
            return False

    # Phase 2: grace period (agent received Stage 3 injection at 90%)
    await asyncio.sleep(30)
    if not await _session_alive():
        _log_event(f"context_{agent_id}", "watcher", agent_id, "context_stop_session_gone", 0)
        return

    # Phase 3: interrupt current activity
    _flush(f"[watcher] {agent_id}: Ctrl+C (context stop)")
    try:
        await _async_run(
            ["tmux", "send-keys", "-t", session_name, "C-c"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        pass

    # Phase 4: poll for prompt, then send /compact deterministically
    compact_sent = False
    for attempt in range(12):  # 12 × 5s = 60s max
        await asyncio.sleep(5)
        if not await _session_alive():
            break
        if await asyncio.to_thread(is_agent_at_prompt, agent_id):
            try:
                await _async_run(
                    ["tmux", "send-keys", "-t", session_name, "-l", compact_cmd],
                    capture_output=True, text=True, timeout=5,
                )
                await _async_run(
                    ["tmux", "send-keys", "-t", session_name, "Enter"],
                    capture_output=True, text=True, timeout=5,
                )
                compact_sent = True
                _flush(f"[watcher] {agent_id}: {compact_cmd} gesendet (Versuch {attempt + 1})")
            except Exception:
                pass
            break

    # Last resort: second Ctrl+C + forced compact
    if not compact_sent and await _session_alive():
        _flush(f"[watcher] WARN {agent_id}: nicht am Prompt nach 60s, erzwinge {compact_cmd}")
        try:
            await _async_run(
                ["tmux", "send-keys", "-t", session_name, "C-c"],
                capture_output=True, text=True, timeout=5,
            )
            await asyncio.sleep(3)
            await _async_run(
                ["tmux", "send-keys", "-t", session_name, "-l", compact_cmd],
                capture_output=True, text=True, timeout=5,
            )
            await _async_run(
                ["tmux", "send-keys", "-t", session_name, "Enter"],
                capture_output=True, text=True, timeout=5,
            )
            compact_sent = True
        except Exception:
            pass

    status = "compact_sent" if compact_sent else "compact_failed"
    try:
        await asyncio.to_thread(
            send_message,
            BRIDGE_HTTP,
            "watcher",
            "ordo",
            f"Agent {agent_id} bei {pct_used}% Context. Hard-Stop: {status}.",
            10.0,
        )
    except Exception as exc:
        _flush(f"[watcher] WARN context-stop bridge_send failed for {agent_id}: {exc}")

    _log_event(f"context_{agent_id}", "watcher", agent_id, status, 0)


def _detect_manual_compact(agent_id: str) -> bool:
    """Detect if agent manually triggered /compact or /compress in tmux pane.

    Reads last 10 lines of the pane and checks for compact commands.
    """
    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-10"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False
        content = result.stdout or ""
    except Exception:
        return False

    engine = _detect_session_engine(agent_id)
    compact_cmd = ENGINE_COMPACT_CMD.get(engine)
    if not compact_cmd:
        return False

    for line in content.strip().split("\n"):
        stripped = line.strip()
        if stripped.endswith(compact_cmd) or stripped == compact_cmd:
            return True
    return False


async def _context_monitor(interval: int = 15) -> None:
    """Periodic multi-stage monitor for context usage."""
    already_stopped: set[str] = set()
    context_warned: set[str] = set()
    context_bridged: set[str] = set()
    context_injected: set[str] = set()
    recently_compacted: set[str] = set()
    # M1: Pre-Compact Detection dedup — agent_id → last_detection_ts
    _compact_detect_ts: dict[str, float] = {}
    while True:
        await asyncio.sleep(interval)
        for agent_id in await asyncio.to_thread(_find_all_sessions):
            pct_used = await asyncio.to_thread(_get_context_usage, agent_id)
            if pct_used is None:
                continue

            # Reset after compact / context recovery
            if pct_used < 70:
                if agent_id in already_stopped:
                    recently_compacted.add(agent_id)
                context_warned.discard(agent_id)
                context_bridged.discard(agent_id)
                context_injected.discard(agent_id)
                already_stopped.discard(agent_id)
                # Auto-resume: nudge agent after compact
                if agent_id in recently_compacted and await asyncio.to_thread(is_agent_at_prompt, agent_id):
                    await asyncio.to_thread(
                        smart_inject,
                        agent_id,
                        "Du wurdest compacted. Lies CONTEXT_BRIDGE.md und arbeite "
                        "an deiner letzten Aktivitaet weiter.",
                    )
                    recently_compacted.discard(agent_id)
                    await asyncio.to_thread(_set_activity, agent_id, "resuming", "Auto-Resume nach Compact")
                    _flush(f"[watcher] auto-resume: {agent_id}")
                continue

            if agent_id in already_stopped:
                continue

            # M1: Pre-Compact Detection — save state when agent triggers /compact manually
            now = time.time()
            last_detect = _compact_detect_ts.get(agent_id, 0.0)
            if now - last_detect > 60:  # 60s cooldown per agent
                detected = await asyncio.to_thread(_detect_manual_compact, agent_id)
                if detected:
                    _compact_detect_ts[agent_id] = now
                    _flush(f"[watcher] M1 pre-compact detected: {agent_id} bei {pct_used}%")
                    await asyncio.to_thread(_write_context_bridge, agent_id, pct_used)
                    await asyncio.to_thread(
                        _set_activity, agent_id, "pre_compact", f"Manual compact detected — State gesichert"
                    )

            # Stage 1: warning
            if pct_used >= 80 and agent_id not in context_warned:
                context_warned.add(agent_id)
                _flush(f"[watcher] context warning: {agent_id} bei {pct_used}%")
                await asyncio.to_thread(_write_context_bridge, agent_id, pct_used)
                await asyncio.to_thread(_set_activity, agent_id, "context_warning", f"Context bei {pct_used}%")

            # Stage 2: write bridge
            if pct_used >= 85 and agent_id not in context_bridged:
                context_bridged.add(agent_id)
                _flush(f"[watcher] context bridge: {agent_id} bei {pct_used}%")
                await asyncio.to_thread(_write_context_bridge, agent_id, pct_used)
                await asyncio.to_thread(
                    _set_activity,
                    agent_id,
                    "context_saving",
                    f"Context bei {pct_used}% — State wird gesichert",
                )

            # Stage 3: pre-stop injection
            if pct_used >= 90 and agent_id not in context_injected:
                context_injected.add(agent_id)
                _flush(f"[watcher] context inject: {agent_id} bei {pct_used}%")
                await asyncio.to_thread(
                    smart_inject,
                    agent_id,
                    f"CONTEXT BEI {pct_used}%. State gesichert. Beende deinen aktuellen Gedanken.",
                )

            # Stage 4: hard stop
            if pct_used >= 95:
                already_stopped.add(agent_id)
                _flush(f"[watcher] context kritisch: {agent_id} bei {pct_used}%")
                await asyncio.to_thread(_set_activity, agent_id, "context_stop", f"Context bei {pct_used}% — Hard-Stop")
                asyncio.create_task(_force_context_stop(agent_id, pct_used))


# ---------------------------------------------------------------------------
# Codex Poll Daemon — replaces codex_bridge_poll.sh
# ---------------------------------------------------------------------------

CODEX_POLL_INTERVAL = 30  # seconds
CODEX_POLL_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pids", "bridge_codex_poll.json")

_codex_poll_state: dict[str, object] = {
    "running": False,
    "last_tick_ts": 0.0,
    "last_poll_ts": 0.0,
    "last_poll_agent": "",
    "polls_total": 0,
    "polls_injected": 0,
    "polls_skipped_no_work": 0,
    "last_skip_reason": "",
    "last_error": "",
    "last_error_ts": 0.0,
}


def _write_codex_poll_state() -> None:
    """Write poll daemon state atomically for health integration."""
    try:
        state_dir = os.path.dirname(CODEX_POLL_STATE_FILE)
        os.makedirs(state_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(_codex_poll_state, f)
            os.replace(tmp, CODEX_POLL_STATE_FILE)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass


_BUSY_PATTERNS = (
    "Working", "esc to interrupt", "Thinking", "Reading",
    "Editing", "Running", "Searching", "Explored", "Called",
)

# V3: Track last-seen activity per agent to enforce cooldown
_agent_last_activity: dict[str, float] = {}
_IDLE_COOLDOWN_SECONDS = 30  # Must be idle for 30s after last activity


def _is_agent_idle_for_poll(agent_id: str) -> bool:
    """Strict idle check for poll daemon — only true for EMPTY prompts.

    V3: Scans last 20 lines (not 5) and enforces 30s cooldown after
    last detected activity. This prevents poll injections during
    multi-step work where the agent briefly returns to prompt between
    tool calls.
    """
    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False
        lines = (result.stdout or "").strip().splitlines()
        if not lines:
            return False

        # V3: Scan last 20 lines for activity (not just 5)
        scan_lines = [ln.strip() for ln in lines[-20:] if ln.strip()]
        if not scan_lines:
            return False

        # Check for active-work indicators in wider window
        now = time.time()
        for line in scan_lines:
            for pat in _BUSY_PATTERNS:
                if pat in line:
                    _agent_last_activity[agent_id] = now
                    return False  # Agent is actively working

        # V3: Cooldown — even if no busy pattern visible now,
        # if we saw activity recently, don't interrupt
        last_active = _agent_last_activity.get(agent_id, 0.0)
        if now - last_active < _IDLE_COOLDOWN_SECONDS:
            return False  # Recently active, don't interrupt

        # Only check last 5 lines for prompt detection
        last_lines = scan_lines[-5:]

        engine = _detect_session_engine(agent_id)
        if engine == "codex":
            for line in last_lines:
                if re.match(r'^\s*[>›]\s*$', line):  # Empty prompt only
                    return True
            for line in last_lines:
                if re.search(r'codex.*\d+%\s*left', line, re.IGNORECASE):
                    return True
            return False
        if engine == "qwen":
            for line in last_lines:
                if re.match(r'^\s*>\s*$', line):  # Empty prompt only
                    return True
            return False
        return False  # Poll daemon only for codex/qwen
    except Exception:
        return False


def _agent_has_pollable_task_work(agent_id: str) -> bool:
    """Return True when the idle poll should still wake the agent for task work.

    Direct messages already have an event-driven wake path via ws_broadcast +
    watcher/non-MCP notifications. The poll daemon is therefore only needed as a
    safety net for task backlog that is not tied to a direct message.
    """
    auth_headers = build_bridge_auth_headers(agent_id="backend")
    try:
        acked = http_get_json(
            f"{BRIDGE_HTTP}/task/queue?state=acked&agent_id={quote(agent_id)}&limit=1",
            timeout=5.0,
            headers=auth_headers,
        )
        if int(acked.get("count") or 0) > 0:
            return True

        created = http_get_json(
            f"{BRIDGE_HTTP}/task/queue?state=created&check_agent={quote(agent_id)}&limit=20",
            timeout=5.0,
            headers=auth_headers,
        )
        tasks = created.get("tasks", [])
        if isinstance(tasks, list):
            for task in tasks:
                claimability = task.get("_claimability") or {}
                if claimability.get("claimable") is True:
                    return True
        return False
    except Exception:
        # Fail open: preserve the old wake behaviour if the task probe itself is down.
        return True


async def _codex_poll_daemon(interval: int = CODEX_POLL_INTERVAL) -> None:
    """Persistent bridge_receive polling for Codex/Qwen engines.

    Replaces codex_bridge_poll.sh with a Python-based asyncio task
    integrated into the watcher event loop.

    Polls all Codex/Qwen-engine sessions periodically. If they're at an
    EMPTY prompt (idle), injects a bridge_receive trigger.
    """
    _codex_poll_state["running"] = True
    _write_codex_poll_state()
    _flush(f"[codex_poll] Daemon gestartet (interval={interval}s)")

    while True:
        try:
            await asyncio.sleep(interval)

            # Update tick timestamp on every loop iteration (health liveness)
            _codex_poll_state["last_tick_ts"] = time.time()

            for agent_id in await asyncio.to_thread(_find_all_sessions):
                engine = await asyncio.to_thread(_detect_session_engine, agent_id)
                if engine not in ("codex", "qwen"):
                    continue

                if not await asyncio.to_thread(_is_agent_idle_for_poll, agent_id):
                    continue

                if not await asyncio.to_thread(_agent_has_pollable_task_work, agent_id):
                    _codex_poll_state["polls_skipped_no_work"] = int(_codex_poll_state["polls_skipped_no_work"]) + 1
                    _codex_poll_state["last_skip_reason"] = "no_task_backlog"
                    continue

                # S2-F2 FIX: Respect _last_injection_time cooldown (same as main router)
                session_name = _get_session_name(agent_id)
                last_inj = _last_injection_time.get(session_name, 0)
                if time.time() - last_inj < COOLDOWN_AGENT_DIRECT:
                    continue

                trigger = (
                    "Call bridge_receive(). If count > 0, process messages and respond "
                    "via bridge_send to the sender. "
                    f"Then call bridge_task_queue(state='acked', agent_id='{agent_id}', limit=3). "
                    "If you have acked tasks, CONTINUE working on them — they are YOUR active tasks. "
                    "Then call bridge_task_queue(state='created', limit=5). If new tasks exist "
                    "that match your role, claim and work on them (bridge_task_claim → work → bridge_task_done). "
                    "If no messages AND no tasks, do nothing."
                )
                ok = await asyncio.to_thread(smart_inject, agent_id, trigger)
                if ok:
                    _last_injection_time[session_name] = time.time()

                _codex_poll_state["last_poll_ts"] = time.time()
                _codex_poll_state["last_poll_agent"] = agent_id
                _codex_poll_state["polls_total"] = int(_codex_poll_state["polls_total"]) + 1
                _codex_poll_state["last_skip_reason"] = ""
                if ok:
                    _codex_poll_state["polls_injected"] = int(_codex_poll_state["polls_injected"]) + 1
                    _flush(f"[codex_poll] {agent_id}: bridge_receive injiziert")
                else:
                    _flush(f"[codex_poll] {agent_id}: inject fehlgeschlagen")

            _write_codex_poll_state()

        except Exception as exc:
            _codex_poll_state["last_error"] = str(exc)
            _codex_poll_state["last_error_ts"] = time.time()
            _write_codex_poll_state()
            _flush(f"[codex_poll] ERROR: {exc}")
            await asyncio.sleep(5)  # Brief pause before recovery


# ---------------------------------------------------------------------------
# Claude Poll Daemon — idle-wake for Claude-engine agents
# ---------------------------------------------------------------------------

CLAUDE_POLL_INTERVAL = 60  # seconds (slower than Codex — Claude needs more think time)
CLAUDE_POLL_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pids", "bridge_claude_poll.json")
_CLAUDE_IDLE_THRESHOLD = 120  # seconds of inactivity before nudge

_claude_poll_state: dict[str, object] = {
    "running": False,
    "last_tick_ts": 0.0,
    "last_poll_ts": 0.0,
    "last_poll_agent": "",
    "polls_total": 0,
    "polls_injected": 0,
    "last_error": "",
    "last_error_ts": 0.0,
}


def _write_claude_poll_state() -> None:
    """Write Claude poll daemon state atomically."""
    try:
        state_dir = os.path.dirname(CLAUDE_POLL_STATE_FILE)
        os.makedirs(state_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(_claude_poll_state, f)
            os.replace(tmp, CLAUDE_POLL_STATE_FILE)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        pass  # State file is best-effort


def _is_claude_idle_for_poll(agent_id: str) -> bool:
    """Check if a Claude agent is idle and at prompt.

    Uses /activity API for idle duration + tmux capture for prompt detection.
    Returns True only if agent is idle > _CLAUDE_IDLE_THRESHOLD AND at prompt.
    """
    # 1. Check idle via /activity API
    try:
        payload = http_get_json(
            f"{BRIDGE_HTTP}/activity?agent_id={quote(agent_id)}",
            timeout=5.0,
        )
        activities = payload.get("activities", [])
        if isinstance(activities, list) and activities:
            first = activities[0]
            idle_seconds = first.get("idle_since_seconds", 0)
            if idle_seconds < _CLAUDE_IDLE_THRESHOLD:
                return False  # Recently active
        # No activity data = treat as idle
    except Exception:
        return False  # Can't verify, skip

    # 2. Check tmux for Claude prompt (❯)
    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False
        lines = (result.stdout or "").strip().splitlines()
        if not lines:
            return False

        # Check last 10 lines for busy patterns
        scan_lines = [ln.strip() for ln in lines[-10:] if ln.strip()]
        for line in scan_lines:
            for pat in _BUSY_PATTERNS:
                if pat in line:
                    return False  # Agent is working

        # Check last 5 lines for Claude prompt ❯
        last_lines = [ln.strip() for ln in lines[-5:] if ln.strip()]
        for line in last_lines:
            if "❯" in line:
                return True
        return False
    except Exception:
        return False


async def _claude_poll_daemon(interval: int = CLAUDE_POLL_INTERVAL) -> None:
    """Persistent idle-wake polling for Claude and Gemini-engine agents.

    Every 60s, checks all Claude/Gemini-engine agents in auto/normal mode.
    If idle > 120s and at prompt, injects bridge_receive + bridge_task_queue
    nudge via tmux.
    """
    _claude_poll_state["running"] = True
    _write_claude_poll_state()
    _flush(f"[claude_poll] Daemon gestartet (interval={interval}s, engines: claude+gemini)")

    while True:
        try:
            await asyncio.sleep(interval)

            _claude_poll_state["last_tick_ts"] = time.time()

            # Get agent list with engine/mode from API
            try:
                agents_data = await asyncio.to_thread(
                    http_get_json,
                    f"{BRIDGE_HTTP}/agents",
                    5.0,
                    build_bridge_auth_headers(agent_id="backend"),
                )
                agents_list = agents_data.get("agents", [])
            except Exception:
                continue  # Server unreachable, skip this tick

            for agent in agents_list:
                if not isinstance(agent, dict):
                    continue
                aid = agent.get("agent_id", "")
                engine = agent.get("engine", "claude")
                mode = agent.get("mode", "")
                status = agent.get("status", "")

                # Claude and Gemini engines, auto/normal mode, online
                if engine not in ("claude", "gemini"):
                    continue
                if mode not in ("auto", "normal"):
                    continue
                if status != "online":
                    continue

                # Idle + prompt check
                if not await asyncio.to_thread(_is_claude_idle_for_poll, aid):
                    continue

                # Cooldown check
                session_name = _get_session_name(aid)
                last_inj = _last_injection_time.get(session_name, 0)
                if time.time() - last_inj < COOLDOWN_AGENT_DIRECT:
                    continue

                trigger = (
                    "bridge_receive und weiterarbeiten. "
                    "Danach bridge_task_queue(state='created', limit=5) pruefen."
                )
                ok = await asyncio.to_thread(smart_inject, aid, trigger)
                if ok:
                    _last_injection_time[session_name] = time.time()

                _claude_poll_state["last_poll_ts"] = time.time()
                _claude_poll_state["last_poll_agent"] = aid
                _claude_poll_state["polls_total"] = int(_claude_poll_state["polls_total"]) + 1
                if ok:
                    _claude_poll_state["polls_injected"] = int(_claude_poll_state["polls_injected"]) + 1
                    _flush(f"[claude_poll] {aid}: idle-wake injiziert")

            _write_claude_poll_state()

        except Exception as exc:
            _claude_poll_state["last_error"] = str(exc)
            _claude_poll_state["last_error_ts"] = time.time()
            _write_claude_poll_state()
            _flush(f"[claude_poll] ERROR: {exc}")
            await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Codex Behavior Watcher — observe, log, and act on Codex agent behavior
# ---------------------------------------------------------------------------

_BEHAVIOR_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
_BEHAVIOR_MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB
_BEHAVIOR_LAST_OUTPUT: dict[str, str] = {}  # agent_id → hash of last capture
_BEHAVIOR_STUCK_COUNT: dict[str, int] = {}  # agent_id → consecutive stuck count


def _behavior_log_path() -> str:
    """Return current behavior log path (date-rotated, size-capped)."""
    base = os.path.join(
        _BEHAVIOR_LOG_DIR,
        f"codex_behavior_{datetime.now().strftime('%Y-%m-%d')}.jsonl",
    )
    if os.path.exists(base) and os.path.getsize(base) >= _BEHAVIOR_MAX_LOG_SIZE:
        # Rotate: append counter
        for i in range(1, 100):
            rotated = base.replace(".jsonl", f"_{i}.jsonl")
            if not os.path.exists(rotated) or os.path.getsize(rotated) < _BEHAVIOR_MAX_LOG_SIZE:
                return rotated
    return base


def _behavior_capture(agent_id: str) -> list[str]:
    """Capture last 30 lines of tmux pane for agent."""
    session_name = _get_session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-30"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return []
        return [ln for ln in (result.stdout or "").splitlines() if ln.strip()]
    except Exception:
        return []


def _behavior_classify(agent_id: str, lines: list[str]) -> tuple[str, list[str]]:
    """Classify agent state and find patterns.

    Returns (state, patterns_found) where state is one of:
    working, idle, responding, stuck, offline
    """
    if not lines:
        return "offline", []

    patterns_found: list[str] = []
    joined = "\n".join(lines[-10:])

    # Check for communication patterns (GOOD)
    if "bridge_send" in joined:
        patterns_found.append("bridge_send")
    if "bridge_receive" in joined:
        patterns_found.append("bridge_receive")
    if "bridge_task" in joined:
        patterns_found.append("bridge_task")

    # Check for active work (NEUTRAL)
    working_indicators = ("Working", "esc to interrupt", "Thinking", "Reading",
                          "Editing", "Running", "Searching")
    for ind in working_indicators:
        if ind in joined:
            patterns_found.append(f"working:{ind}")

    # Detect stuck: same output as last check
    output_hash = hashlib.md5(joined.encode()).hexdigest()
    prev_hash = _BEHAVIOR_LAST_OUTPUT.get(agent_id, "")
    _BEHAVIOR_LAST_OUTPUT[agent_id] = output_hash

    if prev_hash and prev_hash == output_hash:
        _BEHAVIOR_STUCK_COUNT[agent_id] = _BEHAVIOR_STUCK_COUNT.get(agent_id, 0) + 1
        patterns_found.append(f"stuck_repeat:{_BEHAVIOR_STUCK_COUNT[agent_id]}")
    else:
        _BEHAVIOR_STUCK_COUNT[agent_id] = 0

    # Classify state
    if any(p.startswith("working:") for p in patterns_found):
        state = "working"
    elif "bridge_send" in patterns_found or "bridge_receive" in patterns_found:
        state = "responding"
    elif _BEHAVIOR_STUCK_COUNT.get(agent_id, 0) >= 2:
        state = "stuck"
    else:
        # Check for idle prompt
        last_line = lines[-1].strip() if lines else ""
        if re.match(r'^\s*[>›]\s*$', last_line):
            state = "idle"
        else:
            state = "idle"  # Default to idle if no clear signal

    return state, patterns_found


def _behavior_log_entry(agent_id: str, state: str, lines: list[str], patterns: list[str]) -> None:
    """Write a JSONL log entry."""
    os.makedirs(_BEHAVIOR_LOG_DIR, exist_ok=True)
    path = _behavior_log_path()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": agent_id,
        "state": state,
        "last_lines": lines[-5:] if lines else [],
        "patterns_found": patterns,
    }
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        _flush(f"[behavior_watcher] log write error: {exc}")


def _behavior_check_recent_inbound(agent_id: str, max_age_s: float = 60.0) -> bool:
    """Check if agent received a message recently (via history API, read-only).

    Returns True if there's a recent inbound message the agent may not have processed.
    """
    try:
        payload = http_get_json(
            f"{BRIDGE_HTTP}/history?limit=10",
            timeout=3.0,
            headers=build_bridge_auth_headers(agent_id=agent_id),
        )
        if not payload:
            return False
        messages = payload.get("messages", [])
        now = time.time()
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            to = str(msg.get("to", ""))
            if to != agent_id and to != "all":
                continue
            frm = str(msg.get("from", ""))
            if frm == "system":
                continue  # Ignore system messages
            ts_str = str(msg.get("timestamp", ""))
            if not ts_str:
                continue
            try:
                msg_ts = datetime.fromisoformat(ts_str)
                if msg_ts.tzinfo is None:
                    msg_ts = msg_ts.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - msg_ts).total_seconds()
                if age < max_age_s:
                    return True  # Recent message to this agent
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return False


async def _codex_behavior_watcher(interval: int = 15) -> None:
    """Observe Codex agent behavior, log patterns, and act on problems.

    Runs as a parallel asyncio task alongside the poll daemon.
    Does NOT interfere with polling — separate state and cooldowns.
    """
    _flush(f"[behavior_watcher] Gestartet (interval={interval}s)")
    codex_agents = ("codex", "codex_2")
    # Separate cooldown for behavior-watcher actions (not shared with poll daemon)
    _action_cooldown: dict[str, float] = {}  # agent_id → last action ts
    ACTION_COOLDOWN_SECS = 120  # Don't nag more than once per 2 min

    await asyncio.sleep(10)  # Initial delay to let agents start

    while True:
        try:
            await asyncio.sleep(interval)

            for agent_id in codex_agents:
                session_name = _get_session_name(agent_id)
                # Check if session exists
                try:
                    check = subprocess.run(
                        ["tmux", "has-session", "-t", session_name],
                        capture_output=True, timeout=3,
                    )
                    if check.returncode != 0:
                        continue  # Session doesn't exist, skip
                except Exception:
                    continue

                # 1. Observe
                lines = await asyncio.to_thread(_behavior_capture, agent_id)
                state, patterns = await asyncio.to_thread(
                    _behavior_classify, agent_id, lines
                )

                # 2. Log
                await asyncio.to_thread(
                    _behavior_log_entry, agent_id, state, lines, patterns
                )

                # 3. Act
                now = time.time()
                last_action = _action_cooldown.get(agent_id, 0)
                if now - last_action < ACTION_COOLDOWN_SECS:
                    continue  # Respect cooldown

                if state == "idle":
                    # Check if there are recent inbound messages
                    has_msgs = await asyncio.to_thread(
                        _behavior_check_recent_inbound, agent_id, 60.0
                    )
                    if has_msgs:
                        _flush(f"[behavior_watcher] {agent_id}: idle mit ungelesenen Nachrichten → Reminder")
                        await asyncio.to_thread(
                            send_message, BRIDGE_HTTP, "system", agent_id,
                            f"[BEHAVIOR-WATCH] Du hast ungelesene Nachrichten. "
                            f"Rufe bridge_receive() auf.", 5.0,
                        )
                        _action_cooldown[agent_id] = now

                elif state == "stuck":
                    stuck_count = _BEHAVIOR_STUCK_COUNT.get(agent_id, 0)
                    if stuck_count >= 3:
                        _flush(f"[behavior_watcher] {agent_id}: stuck ({stuck_count}x) → Reminder injiziert")
                        ok = await asyncio.to_thread(
                            smart_inject, agent_id,
                            "You appear stuck. Call bridge_receive() to check for messages, "
                            "then continue your work.",
                        )
                        if ok:
                            _action_cooldown[agent_id] = now
                        # Alert Viktor for persistent stuck
                        if stuck_count >= 5:
                            await asyncio.to_thread(
                                send_message, BRIDGE_HTTP, "system", "viktor",
                                f"[BEHAVIOR-ALERT] Agent {agent_id} ist seit "
                                f"{stuck_count * interval}s stuck. Gleicher Output "
                                f"seit {stuck_count} Checks.", 5.0,
                            )

        except asyncio.CancelledError:
            _flush("[behavior_watcher] cancelled (shutdown)")
            return
        except Exception as exc:
            _flush(f"[behavior_watcher] ERROR: {exc}")
            await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Resilient task wrapper — auto-restart background daemons on crash
# ---------------------------------------------------------------------------

async def _resilient_task(name: str, coro_factory, *args, max_crashes: int = 10, cooldown: float = 5.0) -> None:
    """Run an async coroutine in a crash-recovery loop.

    If the coroutine crashes, log the error, wait, and restart.
    Gives up after max_crashes to prevent infinite loops on fatal errors.
    """
    crashes = 0
    while crashes < max_crashes:
        try:
            await coro_factory(*args)
        except asyncio.CancelledError:
            _flush(f"[watcher] {name}: cancelled (shutdown)")
            return
        except Exception as exc:
            crashes += 1
            _flush(f"[watcher] {name}: CRASH #{crashes}/{max_crashes}: {exc}")
            if crashes >= max_crashes:
                _flush(f"[watcher] {name}: FATAL — max crashes reached, daemon stopped")
                _log_event(f"daemon_{name}", "watcher", name, "fatal_max_crashes", 0)
                return
            await asyncio.sleep(cooldown)
    _flush(f"[watcher] {name}: exited")


# ---------------------------------------------------------------------------
# M5: MEMORY.md Health-Check Daemon
# ---------------------------------------------------------------------------

_MEMORY_HEALTH_LAST_WARN: dict[str, float] = {}  # agent_id → last warn timestamp

async def _memory_health_daemon(interval: int = 300) -> None:
    """Check MEMORY.md staleness and size for active agents every 5 min."""
    import glob as _glob
    while True:
        await asyncio.sleep(interval)
        try:
            payload = http_get_json(
                f"{BRIDGE_HTTP}/agents",
                timeout=5.0,
                headers=build_bridge_auth_headers(agent_id="backend"),
            )
            agents = payload.get("agents", [])
            if not isinstance(agents, list):
                continue
            now = time.time()
            for agent in agents:
                if not isinstance(agent, dict):
                    continue
                aid = str(agent.get("agent_id", "")).strip()
                if not aid or aid in ("user", "system", "codex"):
                    continue
                hb_age = agent.get("last_heartbeat_age")
                if hb_age is None or hb_age > 120:
                    continue  # Not active
                # Find MEMORY.md via glob
                pattern = os.path.expanduser(f"~/.claude/projects/*{aid}*/memory/MEMORY.md")
                matches = _glob.glob(pattern)
                if not matches:
                    pattern2 = os.path.expanduser(f"~/.claude-agent-{aid}/projects/*/memory/MEMORY.md")
                    matches = _glob.glob(pattern2)
                if not matches:
                    continue
                mem_path = matches[0]
                try:
                    st = os.stat(mem_path)
                except OSError:
                    continue
                age_hours = (now - st.st_mtime) / 3600
                lines = 0
                try:
                    with open(mem_path) as f:
                        lines = sum(1 for _ in f)
                except OSError:
                    continue
                # Cooldown: max 1 warning per agent per 30 min
                last_warn = _MEMORY_HEALTH_LAST_WARN.get(aid, 0)
                if now - last_warn < 1800:
                    continue
                warn_msg = None
                if lines > 200:
                    warn_msg = f"[MEMORY] Deine MEMORY.md hat {lines} Zeilen (Limit: 200). Zeilen ab 200 werden abgeschnitten. Bitte komprimieren oder in Topic-Files auslagern."
                elif age_hours > 2:
                    warn_msg = f"[MEMORY] Deine MEMORY.md wurde seit {age_hours:.0f}h nicht aktualisiert. Bitte pruefen und bei Bedarf aktualisieren."
                if warn_msg:
                    _MEMORY_HEALTH_LAST_WARN[aid] = now
                    try:
                        await asyncio.to_thread(send_message, BRIDGE_HTTP, "system", aid, warn_msg, 5.0)
                    except Exception:
                        pass
                    _flush(f"[memory_health] {aid}: {warn_msg[:80]}")
        except Exception as exc:
            _flush(f"[memory_health] ERROR: {exc}")


# ---------------------------------------------------------------------------
# Main watch loop
# ---------------------------------------------------------------------------

# WebSocket reconnect backoff config
_WS_RECONNECT_MIN = 1.0    # Initial reconnect delay
_WS_RECONNECT_MAX = 60.0   # Maximum reconnect delay
_WS_RECONNECT_FACTOR = 2.0 # Exponential backoff multiplier


async def watch(ws_url: str) -> None:
    """Main watch loop — connect to WebSocket, route messages to tmux."""
    try:
        import websockets
    except ImportError:
        _flush("[watcher] FEHLER: websockets nicht installiert (pip install websockets)")
        sys.exit(1)

    # Start background daemons with crash recovery
    asyncio.create_task(_resilient_task("context_monitor", _context_monitor, 15))
    asyncio.create_task(_resilient_task("context_bridge_refresh", _context_bridge_refresh_daemon, CONTEXT_BRIDGE_REFRESH_INTERVAL))
    asyncio.create_task(_resilient_task("team_json_reload", _team_json_reload_daemon, 30))
    _flush("[watcher] W4: team.json reload daemon gestartet (30s interval, resilient)")
    _flush("[watcher] Context-Monitor gestartet (15s interval, resilient)")
    _flush(f"[watcher] Context-Bridge-Refresh gestartet ({CONTEXT_BRIDGE_REFRESH_INTERVAL}s interval, resilient)")

    asyncio.create_task(_resilient_task("codex_poll", _codex_poll_daemon, CODEX_POLL_INTERVAL))
    _flush(f"[watcher] Codex-Poll-Daemon gestartet ({CODEX_POLL_INTERVAL}s interval, resilient)")

    asyncio.create_task(_resilient_task("claude_poll", _claude_poll_daemon, CLAUDE_POLL_INTERVAL))
    _flush(f"[watcher] Claude-Poll-Daemon gestartet ({CLAUDE_POLL_INTERVAL}s interval, resilient)")

    asyncio.create_task(_resilient_task("memory_health", _memory_health_daemon, 300))
    _flush("[watcher] Memory-Health-Daemon gestartet (5min interval, resilient)")

    asyncio.create_task(_resilient_task("behavior_watcher", _codex_behavior_watcher, 15))
    _flush("[watcher] Codex-Behavior-Watcher gestartet (15s interval, resilient)")

    reconnect_delay = _WS_RECONNECT_MIN
    while True:
        try:
            async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
                _flush(f"[watcher] verbunden mit {ws_url}")
                reconnect_delay = _WS_RECONNECT_MIN  # Reset on successful connect
                ws_auth_message = build_bridge_ws_auth_message()
                if ws_auth_message:
                    await ws.send(json.dumps(ws_auth_message))
                else:
                    _flush("[watcher] WARN: no Bridge user token available for WebSocket auth")
                await ws.send(json.dumps({"type": "subscribe"}))

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue

                    if data.get("type") != "message":
                        continue

                    msg = data.get("message", {})
                    sender = msg.get("from", "")
                    recipient = msg.get("to", "")
                    content = msg.get("content", "")
                    msg_id = str(msg.get("id", "?"))
                    meta = msg.get("meta") or {}
                    is_urgent = bool(meta.get("urgent"))
                    # Auto-detect urgent from content triggers (user-only)
                    if not is_urgent and sender == "user":
                        _content_lower = content.strip().lower()
                        if _content_lower in _URGENT_TRIGGERS or any(
                            _content_lower.startswith(t) for t in ("stop ", "stopp ", "!!!")
                        ):
                            is_urgent = True

                    if not sender or not content:
                        continue

                    # Skip: Nachrichten an user/system (chat.html zeigt die)
                    if recipient in SKIP_RECIPIENTS:
                        continue

                    # System-Message-Filter: Nicht-kritische System-Nachrichten
                    # nur an Agents zustellen die sie brauchen.
                    if sender == "system" and recipient != "all":
                        if _should_skip_system_message(recipient, content, meta):
                            _flush(
                                f"[watcher] #{msg_id} system→{recipient}: "
                                f"gefiltert (noise reduction)"
                            )
                            _log_event(msg_id, sender, recipient, "system_noise_filtered", 0)
                            continue

                    # Drosselung: WARN/RECOVERY-Flood an Ordo (5min pro Agent)
                    if sender == "system" and _same_tmux_agent(recipient, "ordo"):
                        parsed = _parse_system_agent_notice(content)
                        if parsed:
                            _kind, affected_agent = parsed
                            now_ts = time.time()
                            last_ts = _last_system_notice_ts_by_agent.get(affected_agent, 0.0)
                            if now_ts - last_ts < SYSTEM_NOTICE_COOLDOWN_SECONDS:
                                _flush(
                                    f"[watcher] #{msg_id} system→{recipient}: gedrosselt "
                                    f"({_kind} {affected_agent})"
                                )
                                _log_event(msg_id, sender, recipient, "system_notice_throttled", 0)
                                continue
                            _last_system_notice_ts_by_agent[affected_agent] = now_ts

                    # Deduplication: gleiche Message-ID nicht doppelt injizieren
                    dedup_key = f"{msg_id}_{recipient}"
                    if dedup_key in _recent_injections:
                        _flush(f"[watcher] #{msg_id} {sender}→{recipient}: uebersprungen (Dedup)")
                        _log_event(msg_id, sender, recipient, "dedup_skip", 0)
                        continue
                    # S2-F6 FIX: Dedup key set AFTER injection (see below), not here.
                    # Setting it before injection caused message loss on failed inject.

                    if not _is_route_allowed(sender, recipient):
                        _flush(f"[watcher] #{msg_id} {sender}→{recipient}: BLOCKED (nicht in ALLOWED_ROUTES)")
                        _log_event(msg_id, sender, recipient, "route_blocked", 0)
                        if sender not in SKIP_RECIPIENTS and sender != "watcher" and recipient != "all":
                            try:
                                await asyncio.to_thread(
                                    send_message, BRIDGE_HTTP, "watcher", sender,
                                    f"Zustellung #{msg_id} an {recipient} fehlgeschlagen: nicht in ALLOWED_ROUTES.",
                                    5.0)
                            except Exception:
                                pass
                        continue

                    # Bestimme Ziel-Sessions
                    if recipient == "all":
                        all_targets = await asyncio.to_thread(_find_all_sessions, sender)
                        # Filter broadcasts against ALLOWED_ROUTES
                        allowed_set = ALLOWED_ROUTES.get(sender)
                        if sender == "user" or allowed_set is None:
                            targets = all_targets
                        else:
                            targets = [t for t in all_targets if t in allowed_set]
                    elif recipient == "all_managers":
                        # Fan out to active management agents (level <= 1, active=true)
                        mgmt_agents = await asyncio.to_thread(_get_active_management_agents)
                        targets = [a for a in mgmt_agents if a != sender]
                        _flush(f"[watcher] #{msg_id} all_managers → {targets}")
                    elif recipient == "leads":
                        # Fan out to active Lead agents (level == 1)
                        lead_agents = await asyncio.to_thread(_get_active_leads)
                        targets = [a for a in lead_agents if a != sender]
                        _flush(f"[watcher] #{msg_id} leads → {targets}")
                    elif recipient.startswith("team:"):
                        # Fan out to all active members of the specified team
                        team_id = recipient[5:]  # strip "team:" prefix
                        team_members = await asyncio.to_thread(_get_team_members, team_id)
                        targets = [a for a in team_members if a != sender]
                        _flush(f"[watcher] #{msg_id} team:{team_id} → {targets}")
                    else:
                        targets = [recipient]

                    cooldown = _cooldown_for_message(sender, recipient)
                    for target in targets:
                        if _same_tmux_agent(target, sender):
                            continue

                        session_name = _get_session_name(target)
                        target_started = time.perf_counter()

                        # Check if session is alive via tmux
                        try:
                            _r = await _async_run(
                                ["tmux", "has-session", "-t", session_name],
                                capture_output=True, timeout=3,
                            )
                            alive = _r.returncode == 0
                        except Exception:
                            alive = False

                        if not alive:
                            _log_event(msg_id, sender, target, "session_dead", 0)
                            if sender not in SKIP_RECIPIENTS and sender != "watcher" and recipient not in ("all", "all_managers", "leads") and not recipient.startswith("team:"):
                                try:
                                    await asyncio.to_thread(
                                        send_message, BRIDGE_HTTP, "watcher", sender,
                                        f"Zustellung #{msg_id} an {target} fehlgeschlagen: Session offline.",
                                        5.0)
                                except Exception:
                                    pass
                            continue

                        # Rate Limiting pro Agent
                        now = time.time()
                        last_time = _last_injection_time.get(session_name, 0)
                        if now - last_time < cooldown:
                            wait = cooldown - (now - last_time)
                            _flush(f"[watcher] #{msg_id} {sender}→{target}: cooldown ({wait:.1f}s)")
                            await asyncio.sleep(wait)

                        # Context-Schutz: ab 85% keine System-Injections (ausser context_stop)
                        if sender == "system" and not _is_context_stop_message(content):
                            pct_used = await asyncio.to_thread(_get_context_usage, target)
                            if pct_used is not None and pct_used >= 85:
                                _flush(
                                    f"[watcher] #{msg_id} system→{target}: blockiert "
                                    f"(context {pct_used}%)"
                                )
                                _log_event(msg_id, sender, target, "system_blocked_high_context", 0)
                                continue

                        # Smart inject with retry — content-free push trigger
                        injected = await inject_with_retry(target, sender, content, msg_id, urgent=is_urgent)
                        if injected:
                            _last_injection_time[session_name] = time.time()
                            # S2-F6 FIX: Set dedup key AFTER successful injection
                            _recent_injections.append(dedup_key)

        except Exception as exc:
            _flush(f"[watcher] verbindung verloren: {exc} — reconnect in {reconnect_delay:.1f}s")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * _WS_RECONNECT_FACTOR, _WS_RECONNECT_MAX)


def _find_all_sessions(exclude: str = "") -> list[str]:
    """Find all acw_* tmux sessions, return agent_ids."""
    exclude_tmux = _resolve_tmux_agent_id(exclude)
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []

        live_sessions = set((result.stdout or "").strip().splitlines())
        agents = []

        # Standard acw_* sessions
        for name in live_sessions:
            if name.startswith("acw_"):
                agent_id = name[4:]
                if agent_id != exclude_tmux:
                    agents.append(agent_id)

        # SESSION_NAME_OVERRIDES: add agents whose override session is alive
        for bridge_id, session_name in SESSION_NAME_OVERRIDES.items():
            tmux_id = _resolve_tmux_agent_id(bridge_id)
            if tmux_id == exclude_tmux or bridge_id == exclude:
                continue
            if session_name in live_sessions and tmux_id not in agents:
                agents.append(tmux_id)

        return agents
    except Exception:
        return []


def _flush(*args: object) -> None:
    """Print and flush immediately."""
    print(*args, flush=True)


def _setup_event_logger() -> None:
    """Initialize persistent rotating watcher log file."""
    global _EVENT_LOGGER
    if _EVENT_LOGGER is not None:
        return

    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        logger = logging.getLogger("bridge_watcher.events")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        _EVENT_LOGGER = logger
    except Exception as exc:
        _flush(f"[watcher] WARN logger setup failed: {exc}")


def _log_event(msg_id: str, sender: str, target: str, result: str, latency_ms: int) -> None:
    """Write structured watcher event to persistent log."""
    if _EVENT_LOGGER is None:
        return
    ts = datetime.now(timezone.utc).isoformat()
    _EVENT_LOGGER.info(f"{ts} | {msg_id} | {sender}→{target} | {result} | {latency_ms}")


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with given PID is a running watcher (not PID reuse)."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # PID exists — verify it's actually a watcher process, not PID reuse
    try:
        cmdline = open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", errors="replace")
        if "bridge_watcher" in cmdline:
            return True
        _flush(f"[watcher] PID {pid} lebt, ist aber kein Watcher (PID-Reuse): {cmdline[:120]}")
        return False
    except (OSError, IOError):
        # /proc not readable — fall back to assuming alive
        return True


def _acquire_pid_lock() -> None:
    """Write PID file. Abort if another watcher is already running."""
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    if os.path.exists(PID_FILE):
        try:
            old_pid = int(open(PID_FILE).read().strip())
            if old_pid == os.getpid():
                _flush(f"[watcher] PID-File enthaelt eigene PID ({old_pid}), ueberschreibe (Supervisor-Race)")
            elif _is_pid_alive(old_pid):
                _flush(f"[watcher] ABBRUCH: Anderer Watcher laeuft bereits (PID {old_pid})")
                _flush(f"[watcher] PID-File: {PID_FILE}")
                sys.exit(1)
            else:
                _flush(f"[watcher] Stale PID-File gefunden (PID {old_pid} tot), ueberschreibe")
        except (ValueError, OSError):
            _flush(f"[watcher] Ungueltiges PID-File, ueberschreibe")

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(_release_pid_lock)


def _release_pid_lock() -> None:
    """Remove PID file on exit."""
    try:
        if os.path.exists(PID_FILE):
            stored_pid = int(open(PID_FILE).read().strip())
            if stored_pid == os.getpid():
                os.remove(PID_FILE)
    except (ValueError, OSError):
        pass


def _warn_missing_agents_conf_sessions(agent_meta: dict[str, dict[str, str]]) -> None:
    """Log WARN for tmux agent sessions without agents.conf entries."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return
    except Exception:
        return

    override_reverse: dict[str, str] = {}
    for bridge_id, session_name in SESSION_NAME_OVERRIDES.items():
        override_reverse[session_name] = _resolve_tmux_agent_id(bridge_id)

    for raw in (result.stdout or "").splitlines():
        session_name = raw.strip()
        if not session_name:
            continue

        candidate_ids: list[str] = []
        if session_name.startswith("acw_"):
            candidate_ids.append(session_name[4:])
        mapped = override_reverse.get(session_name)
        if mapped:
            candidate_ids.append(mapped)

        if not candidate_ids:
            continue

        has_entry = False
        for candidate in candidate_ids:
            if candidate in agent_meta:
                has_entry = True
                break
            resolved = _resolve_tmux_agent_id(candidate)
            if resolved in agent_meta:
                has_entry = True
                break

        if not has_entry:
            _flush(f"[watcher] WARN keine agents.conf fuer Session: {session_name}")


def _signal_handler(signum: int, _frame) -> None:
    """Graceful shutdown on SIGTERM/SIGINT. Clean up PID file."""
    sig_name = signal.Signals(signum).name
    _flush(f"[watcher] {sig_name} empfangen — graceful shutdown")
    _release_pid_lock()
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge WebSocket → tmux Router (Hardened V4)")
    parser.add_argument("--ws", default=WS_DEFAULT, help=f"WebSocket URL (default: {WS_DEFAULT})")
    args = parser.parse_args()

    # Signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    _acquire_pid_lock()
    _setup_event_logger()
    agent_meta = _load_agent_meta_cache()
    # Populate SESSION_NAME_OVERRIDES from agents.conf session_name field
    for aid, meta in agent_meta.items():
        sn = meta.get("session_name", "")
        if sn:
            SESSION_NAME_OVERRIDES[aid] = sn
    if SESSION_NAME_OVERRIDES:
        _flush(f"[watcher] session overrides: {SESSION_NAME_OVERRIDES}")
    _warn_missing_agents_conf_sessions(agent_meta)
    # Warn about agents.conf entries missing from ALLOWED_ROUTES
    for aid in agent_meta:
        if aid not in ALLOWED_ROUTES:
            _flush(f"[watcher] WARN {aid} in agents.conf aber NICHT in ALLOWED_ROUTES (kann nicht senden)")
        # Check if reachable as recipient by at least one sender
        reachable = any(aid in targets for targets in ALLOWED_ROUTES.values())
        if not reachable:
            _flush(f"[watcher] WARN {aid} ist fuer KEINEN Sender erreichbar in ALLOWED_ROUTES")

    _flush(f"[watcher] Bridge Watcher V4 (Hardened) gestartet (PID {os.getpid()})")
    _flush(f"[watcher] WebSocket: {args.ws}")
    _flush(f"[watcher] Features: Smart-Inject, Retry, Dedup, Cooldown, Prompt-Detection, PID-Lock, Resilient-Daemons, Backoff-Reconnect, Signal-Handling")
    _flush(f"[watcher] agents.conf entries: {len(agent_meta)}")
    _flush(f"[watcher] Skip: {SKIP_RECIPIENTS}")

    asyncio.run(watch(args.ws))


if __name__ == "__main__":
    main()
