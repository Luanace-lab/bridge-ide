#!/usr/bin/env python3
"""
test_lifecycle.py — Agent Lifecycle and Reconnect Tests.

Tests agent spawn/kill/reconnect scenarios via tmux and Bridge API.
Tests server resilience during agent churn.

Run: python3 test_lifecycle.py

Prerequisites:
- Bridge Server on http://127.0.0.1:9111
- tmux installed
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

import pytest


if os.environ.get("BRIDGE_RUN_LIVE_TESTS") != "1":
    pytestmark = pytest.mark.skip(
        reason="manual live smoke test; set BRIDGE_RUN_LIVE_TESTS=1 to enable"
    )

API_BASE = "http://127.0.0.1:9111"
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


def _api_post(path: str, body: dict) -> tuple[int, dict | None]:
    """POST request."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None
    except Exception:
        return 0, None


def _api_get(path: str) -> tuple[int, dict | None]:
    """GET request."""
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except Exception:
        return 0, None


def _tmux_session_exists(name: str) -> bool:
    """Check if tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def test_register_and_status():
    """Test: Register agent, verify in /agents, send heartbeat."""
    print("\n=== Register + Status ===")
    agent = f"lc_test_{int(time.time())}"

    # Register
    status, data = _api_post("/register", {"agent_id": agent, "role": "Lifecycle Test"})
    test("Register returns 200", status == 200)
    test("Register returns ok", data is not None and data.get("ok"))

    # Verify in agents list
    _, data = _api_get("/agents")
    found = False
    if data and "agents" in data:
        for a in data["agents"]:
            if a.get("agent_id") == agent:
                found = True
                test("Agent has correct role", a.get("role") == "Lifecycle Test")
                test("Agent has status field", "status" in a)
                test("Agent has last_heartbeat field", "last_heartbeat" in a)
                break
    test("Agent found in /agents", found)

    # Heartbeat
    status, data = _api_post("/heartbeat", {"agent_id": agent})
    test("Heartbeat returns 200", status == 200)

    # Second heartbeat
    time.sleep(0.5)
    status, data = _api_post("/heartbeat", {"agent_id": agent})
    test("Second heartbeat returns 200", status == 200)


def test_re_registration():
    """Test: Re-registering same agent updates data."""
    print("\n=== Re-Registration ===")
    agent = f"lc_rereg_{int(time.time())}"

    # First registration
    _api_post("/register", {"agent_id": agent, "role": "Role v1"})

    # Re-register with different role
    status, data = _api_post("/register", {"agent_id": agent, "role": "Role v2"})
    test("Re-registration returns 200", status == 200)

    # Verify role updated
    _, data = _api_get("/agents")
    if data and "agents" in data:
        for a in data["agents"]:
            if a.get("agent_id") == agent:
                test("Role updated to v2", a.get("role") == "Role v2")
                break


def test_messaging_after_register():
    """Test: Agent can send/receive messages immediately after registration."""
    print("\n=== Messaging After Register ===")
    agent = f"lc_msg_{int(time.time())}"
    tag = f"msg_{int(time.time())}"

    # Register
    _api_post("/register", {"agent_id": agent, "role": "Messenger"})

    # Send message
    _, data = _api_post("/send", {"from": agent, "to": "user", "content": f"{tag}: Hello from new agent"})
    test("New agent can send immediately", data is not None and data.get("ok"))

    # Receive message (send one to self first)
    _api_post("/send", {"from": "system", "to": agent, "content": f"{tag}: Welcome"})
    time.sleep(0.3)

    _, data = _api_get(f"/receive/{agent}?limit=5")
    if data and "messages" in data:
        found = [m for m in data["messages"] if tag in m.get("content", "")]
        test("New agent receives messages", len(found) >= 1)
    else:
        test("New agent receives messages", False)


def test_unregistered_agent_messaging():
    """Test: Unregistered agents can still send/receive via /send and /receive."""
    print("\n=== Unregistered Agent Messaging ===")
    agent = f"lc_unreg_{int(time.time())}"
    tag = f"unreg_{int(time.time())}"

    # Send WITHOUT registration
    _, data = _api_post("/send", {"from": agent, "to": "user", "content": f"{tag}: Unreg send"})
    test("Unregistered agent can send", data is not None and data.get("ok"))

    # Receive WITHOUT registration
    _api_post("/send", {"from": "system", "to": agent, "content": f"{tag}: For unreg"})
    time.sleep(0.3)

    _, data = _api_get(f"/receive/{agent}?limit=5")
    if data and "messages" in data:
        found = [m for m in data["messages"] if tag in m.get("content", "")]
        test("Unregistered agent can receive", len(found) >= 1)
    else:
        test("Unregistered agent can receive", False)


def test_tmux_session_detection():
    """Test: is_session_alive correctly detects existing sessions."""
    print("\n=== tmux Session Detection ===")
    sys.path.insert(0, "/home/leo/Desktop/CC/BRIDGE/Backend")
    from tmux_manager import is_session_alive

    # Known sessions
    if _tmux_session_exists("acw_assi"):
        test("is_session_alive('assi') = True", is_session_alive("assi"))
    if _tmux_session_exists("acw_frontend"):
        test("is_session_alive('frontend') = True", is_session_alive("frontend"))

    # Non-existent
    test("is_session_alive('nonexistent') = False",
         not is_session_alive("nonexistent_xyz_test"))


def test_activity_tracking():
    """Test: Agent activity reports are tracked and retrievable."""
    print("\n=== Activity Tracking ===")
    agent = f"lc_act_{int(time.time())}"

    # Register
    _api_post("/register", {"agent_id": agent, "role": "Activity Tester"})

    # Report activity
    status, data = _api_post("/activity", {
        "agent_id": agent,
        "action": "editing",
        "target": "test_file.py",
        "description": "Testing activity tracking",
    })
    test("Activity POST returns 200", status == 200)

    # Retrieve activity
    _, data = _api_get(f"/activity?agent_id={agent}")
    if data and "activities" in data:
        test("Activity retrievable", len(data["activities"]) >= 1)
        if data["activities"]:
            act = data["activities"][0]
            test("Activity has action", act.get("action") == "editing")
            test("Activity has target", act.get("target") == "test_file.py")
    else:
        test("Activity retrievable", False)


def test_cursor_persistence():
    """Test: Cursor correctly tracks which messages agent has read."""
    print("\n=== Cursor Persistence ===")
    agent = f"lc_cursor_{int(time.time())}"
    tag = f"cursor_{int(time.time())}"

    # Send 3 messages to agent
    for i in range(3):
        _api_post("/send", {"from": "system", "to": agent, "content": f"{tag}_{i}"})
    time.sleep(0.3)

    # First receive — should get all 3
    _, data = _api_get(f"/receive/{agent}?limit=10")
    if data and "messages" in data:
        first_batch = [m for m in data["messages"] if m.get("content", "").startswith(tag)]
        test("First receive gets all 3 messages", len(first_batch) == 3,
             f"Got {len(first_batch)}/3")

    # Send 2 more
    for i in range(3, 5):
        _api_post("/send", {"from": "system", "to": agent, "content": f"{tag}_{i}"})
    time.sleep(0.3)

    # Second receive — should get only 2 new
    _, data = _api_get(f"/receive/{agent}?limit=10")
    if data and "messages" in data:
        second_batch = [m for m in data["messages"] if m.get("content", "").startswith(tag)]
        test("Second receive gets only 2 new messages", len(second_batch) == 2,
             f"Got {len(second_batch)}/2")


def test_server_stability_during_churn():
    """Test: Server stays stable during rapid agent registration/messaging."""
    print("\n=== Server Stability During Churn ===")
    tag = f"churn_{int(time.time())}"

    # Rapidly register 10 agents and send messages
    for i in range(10):
        agent = f"churn_{i}_{tag}"
        _api_post("/register", {"agent_id": agent, "role": f"Churn #{i}"})
        _api_post("/send", {"from": agent, "to": "user", "content": f"{tag}: churn msg {i}"})
        _api_post("/heartbeat", {"agent_id": agent})

    # Server should still respond
    status, data = _api_get("/status")
    test("Server still responsive after churn", status == 200)

    _, data = _api_get("/agents")
    if data and "agents" in data:
        churn_agents = [a for a in data["agents"] if tag in a.get("agent_id", "")]
        test("All 10 churn agents registered", len(churn_agents) == 10,
             f"Found {len(churn_agents)}/10")

    # History should have all messages
    _, data = _api_get("/history?limit=50")
    if data and "messages" in data:
        churn_msgs = [m for m in data["messages"] if m.get("content", "").startswith(tag)]
        test("All 10 churn messages in history", len(churn_msgs) >= 10,
             f"Found {len(churn_msgs)}/10")


def main():
    print("=" * 60)
    print("Agent Lifecycle & Reconnect Test Suite")
    print(f"Target: {API_BASE}")
    print("=" * 60)

    # Check server
    status, _ = _api_get("/status")
    if status == 0:
        print("ERROR: Bridge Server nicht erreichbar!")
        sys.exit(1)
    print(f"Server erreichbar (Status: {status})")

    test_register_and_status()
    test_re_registration()
    test_messaging_after_register()
    test_unregistered_agent_messaging()
    test_tmux_session_detection()
    test_activity_tracking()
    test_cursor_persistence()
    test_server_stability_during_churn()

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
