#!/usr/bin/env python3
"""
test_watcher.py — Tests for Bridge Watcher V2 components.

Tests the Watcher's internal functions: prompt detection, content escaping,
notification formatting, deduplication, and rate limiting.

Run: python3 test_watcher.py
"""

import sys
import os

import pytest


if os.environ.get("BRIDGE_RUN_LIVE_TESTS") != "1":
    pytestmark = pytest.mark.skip(
        reason="manual live smoke test; set BRIDGE_RUN_LIVE_TESTS=1 to enable"
    )

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = 0
FAIL = 0
ERRORS = []


def test(name: str, condition: bool, detail: str = ""):
    """Record test result."""
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        msg = f"  ✗ {name}" + (f" — {detail}" if detail else "")
        print(msg)
        ERRORS.append(msg)


test.__test__ = False


def test_escape_for_tmux():
    """Test content escaping for tmux send-keys."""
    print("\n=== Content Escaping ===")
    from bridge_watcher import _escape_for_tmux

    # Basic escaping
    test("Backslash escaped", "\\\\" in _escape_for_tmux("test\\path"))
    test("Semicolon escaped", "\\;" in _escape_for_tmux("cmd;rm"))
    test("Single quote escaped", "\\'" in _escape_for_tmux("it's"))
    test("Double quote escaped", '\\"' in _escape_for_tmux('say "hello"'))

    # No-op for safe strings
    safe = "hello world 123"
    test("Safe string unchanged", _escape_for_tmux(safe) == safe)

    # Complex input
    complex_str = 'test;rm -rf / && echo "pwned"'
    escaped = _escape_for_tmux(complex_str)
    test("Semicolon in injection escaped", "\\;" in escaped)
    test("Quotes in injection escaped", '\\"' in escaped)


def test_format_notification():
    """Test notification formatting."""
    print("\n=== Notification Formatting ===")
    from bridge_watcher import format_notification

    # Short message
    notif = format_notification("assi", "Hallo Manager")
    test("Contains sender name", "assi" in notif)
    test("Contains preview", "Hallo Manager" in notif)
    test("Contains bridge_receive hint", "bridge_receive" in notif)

    # Long message (>80 chars)
    long_content = "A" * 200
    notif_long = format_notification("frontend", long_content)
    test("Long message truncated", "..." in notif_long)
    test("Truncated to ~80 char preview", len(notif_long) < 300)

    # Multiline message
    multiline = "Line 1\nLine 2\nLine 3"
    notif_multi = format_notification("backend", multiline)
    test("Newlines removed from preview", "\n" not in notif_multi)

    # Empty content
    notif_empty = format_notification("test", "")
    test("Empty content handled", notif_empty is not None)

    # Special characters in content
    special = 'Alert: file.py;rm -rf / && echo "hacked"'
    notif_special = format_notification("attacker", special)
    test("Special chars in content escaped", "\\;" in notif_special)


def test_deduplication():
    """Test deduplication via _recent_injections deque."""
    print("\n=== Deduplication ===")
    from bridge_watcher import _recent_injections

    # Clear state
    _recent_injections.clear()

    # Add entries
    _recent_injections.append("100_assi")
    test("Entry added to dedup", "100_assi" in _recent_injections)

    # Check membership
    test("Known entry detected", "100_assi" in _recent_injections)
    test("Unknown entry not detected", "999_unknown" not in _recent_injections)

    # Fill to maxlen (50)
    _recent_injections.clear()
    for i in range(60):
        _recent_injections.append(f"{i}_agent")

    test("Dedup deque maxlen enforced", len(_recent_injections) == 50)
    test("Oldest entry evicted", "0_agent" not in _recent_injections)
    test("Newest entry present", "59_agent" in _recent_injections)
    test("Entry at boundary present", "10_agent" in _recent_injections)

    _recent_injections.clear()


def test_rate_limiting():
    """Test rate limiting per agent."""
    print("\n=== Rate Limiting ===")
    import time
    from bridge_watcher import _last_injection_time, INJECTION_COOLDOWN

    # Clear state
    _last_injection_time.clear()

    # No previous injection = no cooldown
    now = time.time()
    last_time = _last_injection_time.get("test_agent", 0)
    test("No previous injection = no cooldown", now - last_time >= INJECTION_COOLDOWN)

    # Set injection time
    _last_injection_time["test_agent"] = now
    last_time = _last_injection_time.get("test_agent", 0)
    test("Recent injection detected", now - last_time < INJECTION_COOLDOWN)

    # Different agents have independent cooldowns
    _last_injection_time["agent_a"] = now
    _last_injection_time["agent_b"] = now - 10  # 10 seconds ago
    test("Agent A in cooldown", now - _last_injection_time["agent_a"] < INJECTION_COOLDOWN)
    test("Agent B past cooldown", now - _last_injection_time["agent_b"] >= INJECTION_COOLDOWN)

    # Cooldown value
    test("Cooldown is 2 seconds", INJECTION_COOLDOWN == 2.0)

    _last_injection_time.clear()


def test_skip_recipients():
    """Test SKIP_RECIPIENTS set."""
    print("\n=== Skip Recipients ===")
    from bridge_watcher import SKIP_RECIPIENTS

    test("'user' is skipped", "user" in SKIP_RECIPIENTS)
    test("'system' is skipped", "system" in SKIP_RECIPIENTS)
    test("'assi' is NOT skipped", "assi" not in SKIP_RECIPIENTS)
    test("'frontend' is NOT skipped", "frontend" not in SKIP_RECIPIENTS)
    test("'ordo' is NOT skipped", "ordo" not in SKIP_RECIPIENTS)


def test_retry_config():
    """Test retry configuration."""
    print("\n=== Retry Config ===")
    from bridge_watcher import MAX_RETRIES, RETRY_DELAYS

    test("MAX_RETRIES is 10", MAX_RETRIES == 10)
    test("RETRY_DELAYS has 10 entries", len(RETRY_DELAYS) == 10)
    test("Delays match V3 backoff profile", RETRY_DELAYS == [1.0, 2.0, 3.0, 5.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0])
    test("First delay is 1s", RETRY_DELAYS[0] == 1.0)
    test("Last delay is 8s", RETRY_DELAYS[-1] == 8.0)


def test_agent_alias_resolution():
    """Test Bridge agent_id -> tmux session alias mapping."""
    print("\n=== Agent Alias Resolution ===")
    from bridge_watcher import _resolve_tmux_agent_id, _same_tmux_agent

    test("'teamlead' maps to ordo tmux session", _resolve_tmux_agent_id("teamlead") == "ordo")
    test("'ordo' stays ordo", _resolve_tmux_agent_id("ordo") == "ordo")
    test("Unknown agent unchanged", _resolve_tmux_agent_id("viktor") == "viktor")
    test("Alias compare matches teamlead/ordo", _same_tmux_agent("teamlead", "ordo") is True)
    test("Different agents do not match", _same_tmux_agent("ordo", "viktor") is False)


def test_is_session_alive():
    """Test is_session_alive from tmux_manager (quiet mode)."""
    print("\n=== Session Alive Check ===")
    from tmux_manager import is_session_alive

    # Non-existent agent should return False quietly
    result = is_session_alive("nonexistent_test_agent_xyz")
    test("Non-existent agent returns False", result is False)

    # Check real sessions (if any)
    import subprocess
    try:
        r = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            for name in r.stdout.strip().splitlines():
                if name.startswith("acw_"):
                    agent_id = name[4:]
                    result = is_session_alive(agent_id)
                    test(f"Existing agent '{agent_id}' returns True", result is True)
                    break
    except Exception:
        pass

    # Invalid agent ID should raise ValueError
    try:
        is_session_alive("invalid;id")
        test("Invalid agent ID raises error", False)
    except ValueError:
        test("Invalid agent ID raises ValueError", True)


def test_tmux_manager_validate():
    """Test agent_id validation."""
    print("\n=== Agent ID Validation ===")
    from tmux_manager import _validate_agent_id

    # Valid IDs
    for valid_id in ["assi", "frontend", "ordo", "agent_123", "test_agent_1"]:
        try:
            _validate_agent_id(valid_id)
            test(f"Valid ID '{valid_id}' accepted", True)
        except ValueError:
            test(f"Valid ID '{valid_id}' accepted", False)

    # Invalid IDs
    for invalid_id in ["", "agent;rm", "agent name", "agent/path", "agent$var"]:
        try:
            _validate_agent_id(invalid_id)
            test(f"Invalid ID '{invalid_id}' rejected", False)
        except ValueError:
            test(f"Invalid ID '{invalid_id}' rejected", True)


def main():
    print("=" * 60)
    print("Bridge Watcher V2 Test Suite")
    print("=" * 60)

    test_escape_for_tmux()
    test_format_notification()
    test_deduplication()
    test_rate_limiting()
    test_skip_recipients()
    test_retry_config()
    test_agent_alias_resolution()
    test_is_session_alive()
    test_tmux_manager_validate()

    # Summary
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Ergebnis: {PASS}/{total} Tests bestanden")
    if ERRORS:
        print(f"\nFehlgeschlagen ({FAIL}):")
        for e in ERRORS:
            print(e)
    print("=" * 60)

    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
