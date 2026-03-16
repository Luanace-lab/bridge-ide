#!/usr/bin/env python3
"""
start_agents.py — Auto-start agents from team.json (Single Source of Truth).

Reads team.json and starts each agent where active=true and auto_start=true.
Falls back to agents.conf if team.json is missing.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

BRIDGE_DIR = Path(__file__).parent
sys.path.insert(0, str(BRIDGE_DIR))

SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:9111")
TOKEN_CONFIG_FILE = Path.home() / ".config" / "bridge" / "tokens.json"


def _load_user_token(token_file: Path | None = None) -> str:
    token = os.environ.get("BRIDGE_USER_TOKEN", "").strip()
    if token:
        return token
    path = token_file or TOKEN_CONFIG_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("user_token", "")).strip()


def _auth_headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Bridge-Agent": "system",
    }
    token = _load_user_token()
    if token:
        headers["X-Bridge-Token"] = token
    return headers


def _should_auto_start(agent: dict) -> bool:
    return bool(agent.get("active", False)) and bool(agent.get("auto_start", False)) and bool(agent.get("id"))


def _load_auto_start_agents() -> list[dict]:
    """Load agents with active=true and auto_start=true from team.json."""
    team_path = BRIDGE_DIR / "team.json"
    if not team_path.exists():
        print("[start_agents] WARN: team.json not found", file=sys.stderr)
        return []
    data = json.loads(team_path.read_text(encoding="utf-8"))
    agents = []
    for a in data.get("agents", []):
        if not _should_auto_start(a):
            continue
        agents.append(a)
    return agents


def _start_via_api(agent: dict) -> bool:
    """Start agent via POST /agents/{id}/start."""
    agent_id = agent["id"]
    import urllib.request
    import urllib.error

    url = f"{SERVER_URL}/agents/{agent_id}/start"
    payload = json.dumps({"from": "system"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers=_auth_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok") or body.get("status") in ("starting", "already_running"):
                return True
            print(f"[start_agents] WARN: {agent_id} response: {body}", file=sys.stderr)
            return False
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[start_agents] ERROR starting {agent_id}: HTTP {exc.code} — {body}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"[start_agents] ERROR starting {agent_id}: {exc}", file=sys.stderr)
        return False


def _is_agent_running(agent_id: str) -> bool:
    """Check if agent's tmux session exists."""
    session_name = f"acw_{agent_id}"
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
    )
    return result.returncode == 0


def _runtime_is_configured() -> tuple[bool, str]:
    """Check whether the server reports a configured runtime."""
    import urllib.request
    import urllib.error

    url = f"{SERVER_URL}/runtime"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, f"runtime probe failed: HTTP {exc.code}"
    except Exception as exc:
        return False, f"runtime probe failed: {exc}"

    if body.get("configured") is True:
        return True, ""

    pair_mode = body.get("pair_mode", "")
    project_path = body.get("project_path", "")
    return False, f"runtime not configured (pair_mode={pair_mode}, project_path={project_path})"


def main() -> int:
    runtime_ok, runtime_reason = _runtime_is_configured()
    if not runtime_ok:
        print(f"[start_agents] ERROR: {runtime_reason}", file=sys.stderr)
        return 1

    agents = _load_auto_start_agents()
    if not agents:
        print("[start_agents] No auto_start agents in team.json.")
        return 0

    # Buddy first: ensure the onboarding agent starts before all others
    agents.sort(key=lambda a: (0 if a.get("role") == "buddy" or a.get("id") == "buddy" else 1))

    print(f"[start_agents] Found {len(agents)} auto_start agents in team.json.")

    started = 0
    skipped = 0
    failed = 0

    for agent in agents:
        agent_id = agent["id"]

        # Skip if already running
        if _is_agent_running(agent_id):
            print(f"[start_agents] {agent_id}: already running — skip")
            skipped += 1
            continue

        print(f"[start_agents] Starting {agent_id} (engine={agent.get('engine', 'claude')}) ...")
        if _start_via_api(agent):
            started += 1
            time.sleep(2)  # Stagger starts to avoid resource spikes
        else:
            failed += 1

    print(f"[start_agents] Done: {started} started, {skipped} already running, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
