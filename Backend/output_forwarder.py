#!/usr/bin/env python3
"""
output_forwarder.py — Stream Ordo Terminal Output → Bridge

Uses tmux pipe-pane to stream terminal output line-by-line.
No polling, no delta detection — every line arrives immediately.

Sends only meta.type="status" (typing indicator) to avoid
prose duplication with Ordo's own bridge_send messages.

Usage:
    python3 output_forwarder.py
    FORWARDER_SESSION=acw_ordo python3 output_forwarder.py
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import stat
import sys
import time
import urllib.request

from common import build_bridge_auth_headers, load_bridge_agent_session_token

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# FORWARDER_SESSION supports comma-separated list: "acw_ordo,acw_codex"
_RAW_SESSIONS = os.environ.get("FORWARDER_SESSION", "acw_ordo")
TMUX_SESSIONS: list[str] = [s.strip() for s in _RAW_SESSIONS.split(",") if s.strip()]
TMUX_SESSION = TMUX_SESSIONS[0]  # Primary session (backwards compat)
BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:9111")
STATUS_COOLDOWN = float(os.environ.get("STATUS_COOLDOWN", "10.0"))
RELAY_FLUSH_DELAY = float(os.environ.get("RELAY_FLUSH_DELAY", "5.0"))

# Message relay: forward agent text output as bridge messages
# Format: "ordo:user,codex:viktor" — agent_id:recipient
_RELAY_RAW = os.environ.get("RELAY_AGENTS", "")
RELAY_AGENTS: dict[str, str] = {}
for _pair in _RELAY_RAW.split(","):
    _pair = _pair.strip()
    if ":" in _pair:
        _src, _dst = _pair.split(":", 1)
        if _src.strip() and _dst.strip():
            RELAY_AGENTS[_src.strip()] = _dst.strip()

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PID_DIR = os.path.join(_SCRIPT_DIR, "pids")
PID_FILE = os.path.join(PID_DIR, "output_forwarder.pid")
FIFO_PATH = os.environ.get("FORWARDER_FIFO", f"/tmp/bridge_forwarder_{TMUX_SESSION}.fifo")

# ---------------------------------------------------------------------------
# ANSI / terminal escape stripping
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(
    r"\x1b\[[0-9;]*[a-zA-Z]"   # CSI sequences
    r"|\x1b\].*?\x07"           # OSC sequences
    r"|\x1b[()][AB012]"         # charset switching
    r"|\x1b\[[\?]?\d*[hl]"     # mode set/reset
    r"|\r"                       # carriage returns
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# Spinner words (Claude Code thinking/processing status)
# ---------------------------------------------------------------------------

_SPINNER_WORDS = {
    # Claude Code spinners
    "Fermenting", "Brewing", "Actualizing", "Thinking", "Reasoning",
    "Orbiting", "Pondering", "Computing", "Leavening", "Wandering",
    "Brewed", "Crunched", "Metamorphosing",
    # Codex CLI spinners (empirically observed)
    "Running", "Executing", "Processing", "Generating", "Analyzing",
    "Searching", "Loading", "Compiling", "Indexing", "Resolving",
}
# Lowercase set for case-insensitive matching
_SPINNER_WORDS_LOWER = {w.lower() for w in _SPINNER_WORDS}

_SPINNER_RE = re.compile(
    r"^(?:" + "|".join(_SPINNER_WORDS) + r")"
)

_SPINNER_DURATION_RE = re.compile(
    r"(?:" + "|".join(_SPINNER_WORDS) + r") for \d"
)


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------

def _is_spinner(stripped: str) -> bool:
    """True if line is a Claude Code spinner/thinking status."""
    if not stripped:
        return False
    # Special spinner prefix chars: ✻ ✽ ✦ ✶
    if stripped[0] in ("✻", "✽", "✦", "✶"):
        return True
    # Regular asterisk: "* Orbiting…", "* Brewing…"
    if stripped.startswith("*") and not stripped.startswith("**"):
        rest = stripped.lstrip("* ").rstrip("…. ")
        if rest and rest.split()[0] in _SPINNER_WORDS:
            return True
    # Bare spinner word at start: "Brewing for 3s", "Orbiting…"
    if _SPINNER_RE.match(stripped):
        return True
    if _SPINNER_DURATION_RE.search(stripped):
        return True
    # "(thought for Xs)" pattern
    if re.search(r"\(thought for \d+s?\)", stripped):
        return True
    # Token counter: "(39s · ↑ 552 tokens)" — always chrome
    if re.search(r"\d+s\s*·\s*[↑↓]\s*[\d,]+ tokens", stripped):
        return True
    # Generic catch-all: Line is ONLY a capitalized word (possibly hyphenated) + …
    # Must be the entire line to avoid false positives on German prose
    if re.match(r"^[A-Z][a-z]+(?:-[A-Za-z]+)*…\.{0,3}$", stripped):
        return True
    # Case-insensitive spinner word check (catches "thinking", "metamorphosing" etc.)
    first_word = stripped.split()[0].rstrip("…. ").lower() if stripped else ""
    if first_word in _SPINNER_WORDS_LOWER:
        return True
    # Bare "thinking" repeated (Claude Code terminal noise)
    if stripped.lower() in ("thinking", "thinking…"):
        return True
    # Model status bar: "[Opus 4.6] 🟣🟣 43% | $6.60"
    if re.search(r"\[(?:Opus|Sonnet|Haiku|Claude)\s*[\d.]+\]", stripped):
        return True
    if re.search(r"\d+%\s*\|\s*\$[\d.]+", stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Message relay — tool chrome & prompt detection
# ---------------------------------------------------------------------------

_TOOL_CHROME_RE = re.compile(
    r"^[├│─╭╰┌└┐┘┬┴┤╮╯─]+\s*"  # Box drawing characters
    r"|^❯\s*$"                     # Claude prompt
    r"|^>\s*$"                     # Generic prompt
    r"|^\$\s*$"                    # Shell prompt
    r"|^%\s*$"                     # Zsh prompt
    r"|^#\s*$"                     # Root prompt
)


def _is_tool_chrome(stripped: str) -> bool:
    """True if line is tool call decoration, prompt, or system chrome."""
    if _TOOL_CHROME_RE.match(stripped):
        return True
    # Pure separator lines
    if re.match(r'^[-=~_]{3,}$', stripped):
        return True
    # Claude Code status line: "X% context used" etc.
    if re.search(r'\d+%\s*context', stripped, re.IGNORECASE):
        return True
    # Permission prompts (with or without spaces — ANSI stripping may remove them)
    if re.search(r'bypass\s*permissions|esc\s*to\s*interrupt', stripped, re.IGNORECASE):
        return True
    # Status bar with cost: "[Model] X% | $Y.YY" or "⏵⏵ bypass permissions"
    if stripped.startswith("⏵"):
        return True
    # Claude Code MCP tool chrome: "● bridge -" or "● Bash("
    if stripped.startswith("●") or stripped.startswith("⎿"):
        return True
    # Short fragments of garbled ANSI output (< 4 chars, not prose)
    if len(stripped) <= 3 and not stripped[0].isalpha():
        return True
    return False


def _is_prompt(stripped: str) -> bool:
    """True if line is a CLI prompt — marks end of response block."""
    if re.match(r'^\s*❯\s*$', stripped):
        return True
    if re.match(r'^\s*[>$%#]\s*$', stripped):
        return True
    # Claude Code prompt with path: "/path/to/dir ❯"
    if stripped.endswith('❯'):
        return True
    return False


from collections import deque
import hashlib

# Dedup: last 20 relay content hashes
_relay_sent_hashes: deque[str] = deque(maxlen=20)


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def send_relay_message(
    from_agent: str,
    to_agent: str,
    content: str,
    *,
    session_name: str | None = None,
) -> bool:
    """Send accumulated text output as bridge message via POST /send."""
    h = _content_hash(content)
    if h in _relay_sent_hashes:
        _log(f"Relay dedup skip: {from_agent}→{to_agent}")
        return False
    _relay_sent_hashes.append(h)

    payload = json.dumps({
        "from": from_agent,
        "to": to_agent,
        "content": content,
        "meta": {"type": "relay", "source": "output_forwarder", "agent_id": from_agent},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BRIDGE_URL}/send",
        data=payload,
        headers=_bridge_headers_for_agent_session(
            agent_id=from_agent,
            session_name=session_name,
            content_type="application/json; charset=utf-8",
        ),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 201)
    except Exception as exc:
        _log(f"Relay send failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# FIFO management
# ---------------------------------------------------------------------------

def _create_fifo() -> None:
    """Create named pipe (FIFO) if it doesn't exist."""
    if os.path.exists(FIFO_PATH):
        # Check if it's actually a FIFO
        if stat.S_ISFIFO(os.stat(FIFO_PATH).st_mode):
            return
        # Not a FIFO — remove and recreate
        os.remove(FIFO_PATH)
    os.mkfifo(FIFO_PATH)
    _log(f"Created FIFO: {FIFO_PATH}")


def _remove_fifo() -> None:
    """Remove the FIFO."""
    try:
        os.remove(FIFO_PATH)
    except OSError:
        pass


def _tmux_session_exists(session: str) -> bool:
    """Check if a tmux session exists."""
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _tmux_session_env_value(session: str, key: str) -> str:
    try:
        result = subprocess.run(
            ["tmux", "show-environment", "-t", session, key],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    line = result.stdout.strip()
    if not line or line.startswith("-") or "=" not in line:
        return ""
    env_key, _, env_value = line.partition("=")
    if env_key.strip() != key:
        return ""
    return env_value.strip()


def _bridge_headers_for_agent_session(
    *,
    agent_id: str,
    session_name: str | None,
    content_type: str,
) -> dict[str, str]:
    if session_name:
        workspace = (
            _tmux_session_env_value(session_name, "BRIDGE_CLI_WORKSPACE")
            or _tmux_session_env_value(session_name, "BRIDGE_CLI_HOME_DIR")
        )
        session_token = load_bridge_agent_session_token(workspace, agent_id=agent_id)
        if session_token:
            return {
                "Content-Type": content_type,
                "X-Bridge-Agent": agent_id,
                "X-Bridge-Token": session_token,
            }
    return build_bridge_auth_headers(
        agent_id=agent_id,
        content_type=content_type,
    )


def _start_pipe_pane() -> bool:
    """Attach tmux pipe-pane to stream output to our FIFO.

    Returns True on success, False on failure (no sys.exit).
    """
    if not _tmux_session_exists(TMUX_SESSION):
        _log(f"tmux session '{TMUX_SESSION}' does not exist — waiting...")
        return False

    # First stop any existing pipe-pane on this session
    subprocess.run(
        ["tmux", "pipe-pane", "-t", TMUX_SESSION],
        capture_output=True, timeout=5,
    )
    # Start pipe-pane writing to our FIFO
    # -o flag: only output (not input)
    result = subprocess.run(
        ["tmux", "pipe-pane", "-t", TMUX_SESSION, "-o",
         f"cat >> {FIFO_PATH}"],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        _log(f"pipe-pane failed: {result.stderr}")
        return False
    _log(f"pipe-pane attached to {TMUX_SESSION} → {FIFO_PATH}")
    return True


def _stop_pipe_pane() -> None:
    """Detach tmux pipe-pane."""
    try:
        subprocess.run(
            ["tmux", "pipe-pane", "-t", TMUX_SESSION],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Bridge HTTP sender
# ---------------------------------------------------------------------------

def send_activity(agent_id: str, action: str = "typing") -> bool:
    """Update agent activity via /activity endpoint (in-place, no history entry)."""
    payload = json.dumps(
        {
            "agent_id": agent_id,
            "action": action,
            "description": "Agent is working",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{BRIDGE_URL}/activity",
        data=payload,
        headers=_bridge_headers_for_agent_session(
            agent_id=agent_id,
            session_name=f"acw_{agent_id}",
            content_type="application/json; charset=utf-8",
        ),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 201)
    except Exception as exc:
        _log(f"activity update failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# PID management
# ---------------------------------------------------------------------------

def _kill_existing_forwarders() -> None:
    """Kill any existing forwarder processes (not just PID file)."""
    my_pid = os.getpid()
    try:
        result = subprocess.run(
            ["pgrep", "-f", "output_forwarder.py"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            pid = int(line.strip())
            if pid != my_pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    _log(f"Killed old forwarder PID {pid}")
                except OSError:
                    pass
    except Exception:
        pass


def _write_pid() -> None:
    os.makedirs(PID_DIR, exist_ok=True)
    with open(PID_FILE, "w") as fh:
        fh.write(str(os.getpid()))


def _cleanup(*_args: object) -> None:
    _log("Shutting down...")
    _stop_pipe_pane()
    _remove_fifo()
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    sys.exit(0)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[forwarder {ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Main loop — reads FIFO line by line
# ---------------------------------------------------------------------------

def _fifo_path_for_session(session: str) -> str:
    """Return FIFO path for a specific tmux session."""
    return f"/tmp/bridge_forwarder_{session}.fifo"


def _create_fifo_for(path: str) -> None:
    """Create named pipe (FIFO) at path if it doesn't exist."""
    if os.path.exists(path):
        if stat.S_ISFIFO(os.stat(path).st_mode):
            return
        os.remove(path)
    os.mkfifo(path)
    _log(f"Created FIFO: {path}")


def _start_pipe_pane_for(session: str, fifo_path: str) -> bool:
    """Attach tmux pipe-pane for a specific session to a specific FIFO.

    Returns True on success, False if session doesn't exist or pipe-pane fails.
    """
    if not _tmux_session_exists(session):
        _log(f"tmux session '{session}' does not exist — skipping")
        return False

    subprocess.run(
        ["tmux", "pipe-pane", "-t", session],
        capture_output=True, timeout=5,
    )
    result = subprocess.run(
        ["tmux", "pipe-pane", "-t", session, "-o", f"cat >> {fifo_path}"],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        _log(f"pipe-pane failed for {session}: {result.stderr}")
        return False
    _log(f"pipe-pane attached: {session} → {fifo_path}")
    return True


def _stop_pipe_pane_for(session: str) -> None:
    """Detach tmux pipe-pane for a specific session."""
    try:
        subprocess.run(
            ["tmux", "pipe-pane", "-t", session],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _read_fifo_thread(fifo_path: str, session: str, state: dict) -> None:
    """Thread target: read one FIFO, forward spinner status + relay messages.

    state dict is shared (thread-safe via GIL for simple float reads/writes).
    """
    import threading

    agent_id = session.removeprefix("acw_") if session.startswith("acw_") else session
    relay_target = RELAY_AGENTS.get(agent_id)

    # Relay buffer state (protected by lock for thread safety)
    relay_lock = threading.Lock()
    relay_buffer: list[str] = []
    relay_state = {"last_line_time": 0.0}

    def _flush_relay() -> None:
        """Send buffered lines as a bridge message."""
        with relay_lock:
            if not relay_buffer:
                return
            content = "\n".join(relay_buffer)
            relay_buffer.clear()
            relay_state["last_line_time"] = 0.0
        content = content.strip()
        if relay_target and content and len(content) > 5:
            if send_relay_message(agent_id, relay_target, content, session_name=session):
                _log(f"Relay: {agent_id}→{relay_target} ({len(content)} chars)")

    # Background flush checker: sends buffered content after silence
    if relay_target:
        def _flush_checker() -> None:
            while True:
                time.sleep(2.0)
                llt = relay_state["last_line_time"]
                if relay_buffer and llt > 0:
                    if time.time() - llt > RELAY_FLUSH_DELAY:
                        _flush_relay()
        t = threading.Thread(target=_flush_checker, daemon=True, name=f"relay-flush-{session}")
        t.start()
        _log(f"Relay active: {agent_id}→{relay_target}")

    while True:
        try:
            with open(fifo_path, "r", errors="replace") as fifo:
                for raw_line in fifo:
                    line = _strip_ansi(raw_line)
                    stripped = line.strip()
                    if not stripped:
                        continue

                    if _is_spinner(stripped):
                        now = time.time()
                        if now - state["last_status_sent"] >= STATUS_COOLDOWN:
                            send_activity(agent_id, "typing")
                            state["last_status_sent"] = now
                            _log(f"Sent activity: typing (from {session})")
                        continue

                    # Message relay logic
                    if relay_target:
                        if _is_prompt(stripped):
                            _flush_relay()
                        elif not _is_tool_chrome(stripped):
                            with relay_lock:
                                relay_buffer.append(stripped)
                                relay_state["last_line_time"] = time.time()

            _log(f"FIFO EOF ({session}) — reopening...")
            # Flush remaining buffer on EOF
            if relay_target:
                _flush_relay()
            # Wait for session to exist before re-opening FIFO
            # (otherwise open() blocks forever with no writer)
            while not _tmux_session_exists(session):
                _log(f"Waiting for tmux session '{session}'...")
                time.sleep(30)
            time.sleep(1.0)
            _start_pipe_pane_for(session, fifo_path)
        except OSError as exc:
            _log(f"FIFO read error ({session}): {exc}, retrying in 30s...")
            time.sleep(30)
            _create_fifo_for(fifo_path)
            # Wait for session before re-attaching
            while not _tmux_session_exists(session):
                _log(f"Waiting for tmux session '{session}'...")
                time.sleep(30)
            _start_pipe_pane_for(session, fifo_path)


def main() -> None:
    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    # Kill any zombie forwarder processes before starting
    _kill_existing_forwarders()

    _write_pid()

    sessions = TMUX_SESSIONS
    _log(f"Started PID={os.getpid()} sessions={sessions}")

    # Shared state across threads
    state = {"last_status_sent": 0.0}

    if len(sessions) == 1:
        # Single session — use original FIFO path (backwards compat)
        _create_fifo()
        # Wait for tmux session to become available (don't exit on failure)
        while not _start_pipe_pane():
            time.sleep(30)
        _log(f"Reading from FIFO (blocking): {FIFO_PATH}")
        _read_fifo_thread(FIFO_PATH, sessions[0], state)
    else:
        # Multi-session: one thread per session
        import threading
        threads: list[threading.Thread] = []
        for session in sessions:
            fifo_path = _fifo_path_for_session(session)
            _create_fifo_for(fifo_path)
            _start_pipe_pane_for(session, fifo_path)
            t = threading.Thread(
                target=_read_fifo_thread,
                args=(fifo_path, session, state),
                daemon=True,
                name=f"fifo-{session}",
            )
            t.start()
            threads.append(t)
            _log(f"Started FIFO reader thread for {session}")

        # Main thread: wait forever (threads are daemon, will exit with process)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
