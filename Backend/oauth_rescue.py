#!/usr/bin/env python3
"""oauth_rescue.py — Detect agents stuck at OAuth login and restart with --resume.

Scans all acw_* tmux sessions. If an agent shows the OAuth login prompt
instead of working, kills the session and restarts with claude --resume.

Usage:
    python3 oauth_rescue.py          # One-shot scan + fix
    python3 oauth_rescue.py --watch  # Continuous monitoring (every 30s)
"""
import json
import os
import subprocess
import sys
import time

TEAM_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team.json")
SESSION_IDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pids", "session_ids.json")
CONFIG_DIR_DEFAULT = os.path.expanduser("~/.claude")

OAUTH_PATTERNS = (
    "Paste code here if prompted",
    "oauth/authorize",
    "Browser didn't open",
    "Use the url below to sign in",
)

# Patterns that mean the agent is working fine — do NOT rescue
HEALTHY_PATTERNS = (
    "Working", "Thinking", "Reading", "Editing", "Running",
    "Searching", "esc to interrupt", "bridge_receive",
    "plan mode on", "bypass permissions on", "accept edits on",
)


def _capture_pane(session_name: str, lines: int = 50) -> str:
    try:
        r = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _is_stuck_at_oauth(session_name: str) -> bool:
    """Return True if agent is stuck at OAuth prompt."""
    output = _capture_pane(session_name)
    if not output.strip():
        return False
    # Must match OAuth pattern
    has_oauth = any(p in output for p in OAUTH_PATTERNS)
    if not has_oauth:
        return False
    # Must NOT have healthy patterns (agent is working)
    has_healthy = any(p in output for p in HEALTHY_PATTERNS)
    return not has_healthy


def _load_team_config() -> dict:
    """Load team.json and return {agent_id: config}."""
    try:
        with open(TEAM_JSON) as f:
            data = json.load(f)
    except Exception:
        return {}
    agents = data if isinstance(data, list) else data.get("agents", data.get("team", []))
    result = {}
    for a in agents:
        aid = a.get("id", a.get("agent_id", ""))
        if aid and a.get("engine", "claude") == "claude":
            result[aid] = a
    return result


def _load_session_ids() -> dict:
    """Load resume IDs from session_ids.json."""
    try:
        with open(SESSION_IDS) as f:
            return json.load(f)
    except Exception:
        return {}


def _get_workspace(agent_config: dict) -> str:
    """Determine workspace path for agent."""
    home_dir = agent_config.get("home_dir", "")
    if home_dir and not os.path.isabs(home_dir):
        home_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), home_dir)
    if not home_dir:
        return ""
    # Check for .agent_sessions subdir
    agent_id = agent_config.get("id", "")
    sessions_dir = os.path.join(home_dir, ".agent_sessions", agent_id)
    if os.path.isdir(sessions_dir):
        return sessions_dir
    return home_dir


def _restart_with_resume(agent_id: str, session_name: str, resume_id: str, workspace: str, config_dir: str):
    """Kill tmux session and restart with claude --resume."""
    print(f"[oauth-rescue] Restarting {agent_id}: kill {session_name}, resume {resume_id[:12]}...")

    # Kill old session
    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
    time.sleep(1)

    # Build start command
    config_dir = config_dir or CONFIG_DIR_DEFAULT
    cmd = (
        f"export CLAUDE_CONFIG_DIR={config_dir} BROWSER=false && "
        f"unset CLAUDECODE CODEX_MANAGED_BY_NPM CODEX_THREAD_ID CODEX_CI CODEX_SANDBOX_NETWORK_DISABLED && "
        f"claude --resume {resume_id} --dangerously-skip-permissions"
    )

    # Create new tmux session
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, "-x", "200", "-y", "50", "-c", workspace],
        capture_output=True, timeout=5,
    )
    subprocess.run(
        ["tmux", "send-keys", "-t", session_name, cmd, "Enter"],
        capture_output=True, timeout=5,
    )

    # Verify after 5s
    time.sleep(5)
    output = _capture_pane(session_name, 10)
    still_oauth = any(p in output for p in OAUTH_PATTERNS)
    if still_oauth:
        print(f"[oauth-rescue] WARNING: {agent_id} still at OAuth after restart!")
    else:
        print(f"[oauth-rescue] {agent_id} resumed successfully.")


def scan_and_fix() -> int:
    """Scan all agents, fix stuck ones. Returns number of rescues."""
    team = _load_team_config()
    session_ids = _load_session_ids()
    rescues = 0

    # List tmux sessions
    try:
        r = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"],
                           capture_output=True, text=True, timeout=5)
        sessions = [s.strip() for s in r.stdout.splitlines() if s.strip().startswith("acw_")]
    except Exception:
        print("[oauth-rescue] No tmux sessions found.")
        return 0

    for session_name in sessions:
        agent_id = session_name.replace("acw_", "", 1)

        if not _is_stuck_at_oauth(session_name):
            continue

        print(f"[oauth-rescue] {agent_id} stuck at OAuth login!")

        # Get resume ID
        resume_id = session_ids.get(agent_id, "")
        if not resume_id:
            print(f"[oauth-rescue] No resume ID for {agent_id} — skipping.")
            continue

        # Get config
        config = team.get(agent_id, {})
        workspace = _get_workspace(config) if config else ""
        if not workspace:
            # Fallback: try common paths
            _project_root = os.environ.get("BRIDGE_PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            for p in [
                os.path.join(_project_root, agent_id.capitalize(), ".agent_sessions", agent_id),
                os.path.join(_project_root, "MobileApp", ".agent_sessions", agent_id),
            ]:
                if os.path.isdir(p):
                    workspace = p
                    break
        if not workspace:
            print(f"[oauth-rescue] No workspace for {agent_id} — skipping.")
            continue

        config_dir = config.get("config_dir", "") or CONFIG_DIR_DEFAULT

        _restart_with_resume(agent_id, session_name, resume_id, workspace, config_dir)
        rescues += 1

    if rescues == 0:
        print("[oauth-rescue] No agents stuck at OAuth.")
    else:
        print(f"[oauth-rescue] Rescued {rescues} agent(s).")
    return rescues


def main():
    watch = "--watch" in sys.argv
    if watch:
        print("[oauth-rescue] Watch mode — scanning every 30s. Ctrl+C to stop.")
        while True:
            try:
                scan_and_fix()
                time.sleep(30)
            except KeyboardInterrupt:
                print("\n[oauth-rescue] Stopped.")
                break
    else:
        scan_and_fix()


if __name__ == "__main__":
    main()
