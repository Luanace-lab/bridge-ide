#!/usr/bin/env python3
"""
test_bridge_api.py — Automated tests for Bridge Server API endpoints.

Tests all HTTP endpoints on :9111 against a running Bridge Server.
Run: python3 test_bridge_api.py

Prerequisites: Bridge Server must be running on http://127.0.0.1:9111
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

import pytest


if os.environ.get("BRIDGE_RUN_LIVE_TESTS") != "1":
    pytestmark = pytest.mark.skip(
        reason="manual live smoke test; set BRIDGE_RUN_LIVE_TESTS=1 to enable"
    )


BASE_URL = "http://127.0.0.1:9111"
PASS = 0
FAIL = 0
ERRORS = []


def _request(method: str, path: str, body: dict | None = None, timeout: int = 10) -> tuple[int, dict | str]:
    """Make HTTP request, return (status_code, parsed_response)."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if body else {}

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except Exception as e:
        return 0, str(e)


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


def test_server_health():
    """Test GET /status endpoint."""
    print("\n=== Server Health ===")
    status, data = _request("GET", "/status")
    test("GET /status returns 200", status == 200)
    test("Response is dict", isinstance(data, dict))
    if isinstance(data, dict):
        test("Has 'status' field", "status" in data)


def test_agent_registration():
    """Test POST /register endpoint."""
    print("\n=== Agent Registration ===")
    test_id = f"test_agent_{int(time.time())}"

    # Register new agent
    status, data = _request("POST", "/register", {
        "agent_id": test_id,
        "role": "Test Agent",
    })
    test("POST /register returns 200", status == 200)
    test("Response has 'ok' field", isinstance(data, dict) and "ok" in data)

    # Verify in agents list
    status, data = _request("GET", "/agents")
    test("GET /agents returns 200", status == 200)
    if isinstance(data, dict) and "agents" in data:
        agent_ids = [a.get("agent_id") for a in data["agents"]]
        test(f"Registered agent '{test_id}' appears in /agents", test_id in agent_ids)

    # Register with missing fields
    status, data = _request("POST", "/register", {})
    test("Register with empty body returns error", status >= 400 or (isinstance(data, dict) and not data.get("ok", True)))

    return test_id


def test_heartbeat(agent_id: str):
    """Test POST /heartbeat endpoint."""
    print("\n=== Heartbeat ===")
    status, data = _request("POST", "/heartbeat", {"agent_id": agent_id})
    test("POST /heartbeat returns 200", status == 200)

    # Heartbeat with unknown agent
    status, data = _request("POST", "/heartbeat", {"agent_id": "nonexistent_agent_xyz"})
    test("Heartbeat with unknown agent handled", status in [200, 404])


def test_send_message(agent_id: str):
    """Test POST /send endpoint."""
    print("\n=== Send Message ===")

    # Send valid message
    status, data = _request("POST", "/send", {
        "from": agent_id,
        "to": "user",
        "content": "Test message from automated tests",
    })
    test("POST /send returns 201", status == 201)
    test("Response has 'ok' field", isinstance(data, dict) and "ok" in data)
    if isinstance(data, dict) and "message" in data:
        msg = data["message"]
        test("Message has 'id' field", "id" in msg)
        test("Message has 'from' field", "from" in msg)
        test("Message has 'to' field", "to" in msg)
        test("Message has 'content' field", "content" in msg)
        test("Message has 'timestamp' field", "timestamp" in msg)
        return msg.get("id")

    # Send with empty body
    status, data = _request("POST", "/send", {})
    test("Send with empty body returns error", status >= 400 or (isinstance(data, dict) and not data.get("ok", True)))

    return None


def test_receive_messages(agent_id: str):
    """Test GET /receive/<id> endpoint."""
    print("\n=== Receive Messages ===")

    # Send a message TO our test agent first
    _request("POST", "/send", {
        "from": "manager",
        "to": agent_id,
        "content": "Test message for receive endpoint",
    })
    time.sleep(0.5)

    # Receive messages
    status, data = _request("GET", f"/receive/{agent_id}?limit=5")
    test("GET /receive returns 200", status == 200)
    if isinstance(data, dict):
        test("Response has messages", "messages" in data or isinstance(data, list))

    # Receive with unknown agent
    status, data = _request("GET", "/receive/nonexistent_agent_xyz?limit=1")
    test("Receive for unknown agent handled", status in [200, 404])


def test_history():
    """Test GET /history endpoint."""
    print("\n=== History ===")
    status, data = _request("GET", "/history?limit=10")
    test("GET /history returns 200", status == 200)
    if isinstance(data, dict):
        test("Response has messages", "messages" in data)
        if "messages" in data:
            test("Messages is a list", isinstance(data["messages"], list))
            if data["messages"]:
                msg = data["messages"][0]
                test("Message has required fields", all(k in msg for k in ["id", "from", "to", "content"]))


def test_agents_list():
    """Test GET /agents endpoint."""
    print("\n=== Agents List ===")
    status, data = _request("GET", "/agents")
    test("GET /agents returns 200", status == 200)
    test("Response is dict", isinstance(data, dict))
    if isinstance(data, dict) and "agents" in data:
        test("Agents is a list", isinstance(data["agents"], list))
        test("At least 1 agent registered", len(data["agents"]) >= 1)
        if data["agents"]:
            agent = data["agents"][0]
            test("Agent has agent_id", "agent_id" in agent)
            test("Agent has role", "role" in agent)
            test("Agent has status", "status" in agent)
            test("Agent has last_heartbeat", "last_heartbeat" in agent)


def test_broadcast():
    """Test broadcast message (to=all)."""
    print("\n=== Broadcast ===")
    status, data = _request("POST", "/send", {
        "from": "test_broadcast",
        "to": "all",
        "content": "Broadcast test from automated tests",
    })
    test("Broadcast POST /send returns 201", status == 201)
    test("Broadcast has ok field", isinstance(data, dict) and "ok" in data)


def main():
    print("=" * 60)
    print("Bridge API Test Suite")
    print(f"Target: {BASE_URL}")
    print("=" * 60)

    # Check server is running
    try:
        status, _ = _request("GET", "/status")
        if status == 0:
            print("ERROR: Bridge Server nicht erreichbar!")
            sys.exit(1)
    except Exception:
        print("ERROR: Bridge Server nicht erreichbar!")
        sys.exit(1)

    print(f"Server erreichbar (Status: {status})")

    # Run tests
    test_server_health()
    test_id = test_agent_registration()
    test_heartbeat(test_id)
    test_send_message(test_id)
    test_receive_messages(test_id)
    test_history()
    test_agents_list()
    test_broadcast()

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
