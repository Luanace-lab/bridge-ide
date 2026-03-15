#!/usr/bin/env python3
"""
test_multi_agent.py — Multi-Agent Conversation Scenario Tests.

Simulates realistic multi-agent workflows:
- Manager delegates tasks
- Agents respond and coordinate
- Cross-agent communication
- Broadcast scenarios

Run: python3 test_multi_agent.py

Prerequisites: Bridge Server must be running on http://127.0.0.1:9111
"""

import json
import os
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
    """POST request to API."""
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
    """GET request to API."""
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except Exception:
        return 0, None


def _send(from_id: str, to_id: str, content: str) -> dict | None:
    """Send a message, return message dict."""
    _, data = _api_post("/send", {"from": from_id, "to": to_id, "content": content})
    if data and data.get("ok"):
        return data.get("message")
    return None


def _receive(agent_id: str, limit: int = 10) -> list:
    """Receive messages for agent."""
    _, data = _api_get(f"/receive/{agent_id}?limit={limit}")
    if data and "messages" in data:
        return data["messages"]
    return []


def test_scenario_1_task_delegation():
    """Scenario: Manager delegates task to frontend, frontend reports back."""
    print("\n=== Scenario 1: Task Delegation ===")
    tag = f"s1_{int(time.time())}"

    # Step 1: Manager sends task to frontend
    msg1 = _send("s1_manager", "s1_frontend", f"{tag}: Implementiere Button X")
    test("Manager→Frontend: Task gesendet", msg1 is not None)

    # Step 2: Frontend acknowledges
    msg2 = _send("s1_frontend", "s1_manager", f"{tag}: Verstanden, starte mit Button X")
    test("Frontend→Manager: Bestaetigung", msg2 is not None)

    # Step 3: Frontend reports progress
    msg3 = _send("s1_frontend", "s1_manager", f"{tag}: Button X implementiert, 0 Errors")
    test("Frontend→Manager: Fortschritt", msg3 is not None)

    # Step 4: Manager confirms
    msg4 = _send("s1_manager", "s1_frontend", f"{tag}: Code-Review bestanden")
    test("Manager→Frontend: Bestaetigung", msg4 is not None)

    # Verify chronological order in history
    _, data = _api_get("/history?limit=20")
    if data and "messages" in data:
        tag_msgs = [m for m in data["messages"] if m.get("content", "").startswith(tag)]
        ids = [m["id"] for m in tag_msgs]
        test("Messages in chronological order", ids == sorted(ids),
             f"IDs: {ids}")
        test("All 4 messages in history", len(tag_msgs) == 4,
             f"Found {len(tag_msgs)}/4")
    else:
        test("History accessible", False)


def test_scenario_2_cross_agent_coordination():
    """Scenario: Agent A needs something from Agent B, coordination via manager."""
    print("\n=== Scenario 2: Cross-Agent Coordination ===")
    tag = f"s2_{int(time.time())}"

    # Register test agents
    _api_post("/register", {"agent_id": "s2_agent_a", "role": "Implementation"})
    _api_post("/register", {"agent_id": "s2_agent_b", "role": "API"})
    _api_post("/register", {"agent_id": "s2_manager", "role": "Koordination"})

    # Step 1: Agent A reports blocker
    _send("s2_agent_a", "s2_manager", f"{tag}: Brauche API-Endpoint /users von Agent B")

    # Step 2: Manager delegates to Agent B
    _send("s2_manager", "s2_agent_b", f"{tag}: Bitte /users Endpoint erstellen fuer Agent A")

    # Step 3: Agent B implements and reports
    _send("s2_agent_b", "s2_manager", f"{tag}: /users Endpoint fertig")

    # Step 4: Manager informs Agent A
    _send("s2_manager", "s2_agent_a", f"{tag}: Agent B hat /users implementiert, du kannst weitermachen")

    # Step 5: Agent A directly thanks Agent B
    _send("s2_agent_a", "s2_agent_b", f"{tag}: Danke, funktioniert perfekt")

    # Verify Agent B received Agent A's direct message
    msgs_b = _receive("s2_agent_b", limit=10)
    direct_msgs = [m for m in msgs_b if m.get("from") == "s2_agent_a" and tag in m.get("content", "")]
    test("Agent A→Agent B direct message received", len(direct_msgs) >= 1)

    # Verify all messages in history
    _, data = _api_get("/history?limit=30")
    if data and "messages" in data:
        tag_msgs = [m for m in data["messages"] if tag in m.get("content", "")]
        test("All 5 coordination messages in history", len(tag_msgs) == 5,
             f"Found {len(tag_msgs)}/5")


def test_scenario_3_broadcast_and_response():
    """Scenario: Manager broadcasts, multiple agents respond."""
    print("\n=== Scenario 3: Broadcast + Responses ===")
    tag = f"s3_{int(time.time())}"

    # Register test agents
    for a in ["s3_alpha", "s3_beta", "s3_gamma"]:
        _api_post("/register", {"agent_id": a, "role": "Worker"})

    # Step 1: Manager broadcasts
    msg = _send("s3_manager", "all", f"{tag}: Status-Report bitte")
    test("Broadcast sent", msg is not None)

    # Step 2: All agents respond individually
    for a in ["s3_alpha", "s3_beta", "s3_gamma"]:
        _send(a, "s3_manager", f"{tag}: {a} reporting — alles OK")

    # Verify manager received all 3 responses
    msgs = _receive("s3_manager", limit=20)
    responses = [m for m in msgs if tag in m.get("content", "") and m.get("from", "").startswith("s3_")]
    test("Manager received 3 responses", len(responses) >= 3,
         f"Got {len(responses)}/3")


def test_scenario_4_message_routing_isolation():
    """Scenario: Messages between A-B don't appear in C's receive."""
    print("\n=== Scenario 4: Routing Isolation ===")
    tag = f"s4_{int(time.time())}"

    # Register agents
    _api_post("/register", {"agent_id": "s4_alice", "role": "Worker"})
    _api_post("/register", {"agent_id": "s4_bob", "role": "Worker"})
    _api_post("/register", {"agent_id": "s4_charlie", "role": "Worker"})

    # Drain Charlie's queue
    _receive("s4_charlie", limit=100)

    # Alice sends to Bob (NOT Charlie)
    _send("s4_alice", "s4_bob", f"{tag}: Geheime Nachricht nur fuer Bob")

    time.sleep(0.5)

    # Charlie should NOT receive Alice's message to Bob
    charlie_msgs = _receive("s4_charlie", limit=10)
    leaked = [m for m in charlie_msgs if tag in m.get("content", "") and m.get("from") == "s4_alice"]
    test("Charlie did NOT receive Alice→Bob message", len(leaked) == 0,
         f"Leaked {len(leaked)} messages")

    # But Bob should have it
    bob_msgs = _receive("s4_bob", limit=10)
    bob_got = [m for m in bob_msgs if tag in m.get("content", "") and m.get("from") == "s4_alice"]
    test("Bob received Alice's message", len(bob_got) >= 1)


def test_scenario_5_agent_status_lifecycle():
    """Scenario: Agent registers, sends heartbeat, status updates."""
    print("\n=== Scenario 5: Agent Status Lifecycle ===")
    tag = f"s5_{int(time.time())}"
    agent = f"s5_lifecycle_{tag}"

    # Step 1: Not registered — should not appear
    _, data = _api_get("/agents")
    if data and "agents" in data:
        existing = [a for a in data["agents"] if a.get("agent_id") == agent]
        test("Agent not in list before registration", len(existing) == 0)

    # Step 2: Register
    status, _ = _api_post("/register", {"agent_id": agent, "role": "Lifecycle Test"})
    test("Registration successful", status == 200)

    # Step 3: Verify in list
    _, data = _api_get("/agents")
    if data and "agents" in data:
        existing = [a for a in data["agents"] if a.get("agent_id") == agent]
        test("Agent in list after registration", len(existing) >= 1)
        if existing:
            test("Agent has role", existing[0].get("role") == "Lifecycle Test")

    # Step 4: Heartbeat
    status, _ = _api_post("/heartbeat", {"agent_id": agent})
    test("Heartbeat successful", status == 200)

    # Step 5: Agent activity
    status, _ = _api_post("/activity", {
        "agent_id": agent,
        "action": "testing",
        "target": "lifecycle_flow",
        "description": "Running lifecycle test",
    })
    test("Activity report successful", status == 200)

    # Step 6: Verify activity
    _, data = _api_get(f"/activity?agent_id={agent}")
    if data and "activities" in data:
        test("Activity recorded", len(data["activities"]) >= 1)


def test_scenario_6_rapid_conversation():
    """Scenario: Fast back-and-forth conversation between 2 agents."""
    print("\n=== Scenario 6: Rapid Conversation ===")
    tag = f"s6_{int(time.time())}"
    exchanges = 10

    for i in range(exchanges):
        # Alice sends
        _send("s6_alice", "s6_bob", f"{tag}: Alice msg #{i}")
        # Bob responds
        _send("s6_bob", "s6_alice", f"{tag}: Bob response #{i}")

    # Verify all messages in history
    _, data = _api_get(f"/history?limit={exchanges * 2 + 10}")
    if data and "messages" in data:
        tag_msgs = [m for m in data["messages"] if m.get("content", "").startswith(tag)]
        test(f"All {exchanges * 2} conversation messages stored",
             len(tag_msgs) == exchanges * 2,
             f"Found {len(tag_msgs)}/{exchanges * 2}")

    # Verify Alice got all Bob's messages
    alice_msgs = _receive("s6_alice", limit=exchanges + 5)
    from_bob = [m for m in alice_msgs if m.get("from") == "s6_bob" and tag in m.get("content", "")]
    test(f"Alice received all {exchanges} responses from Bob",
         len(from_bob) >= exchanges,
         f"Got {len(from_bob)}/{exchanges}")


def main():
    print("=" * 60)
    print("Multi-Agent Conversation Scenario Tests")
    print(f"Target: {API_BASE}")
    print("=" * 60)

    # Check server
    status, _ = _api_get("/status")
    if status == 0:
        print("ERROR: Bridge Server nicht erreichbar!")
        sys.exit(1)
    print(f"Server erreichbar (Status: {status})")

    test_scenario_1_task_delegation()
    test_scenario_2_cross_agent_coordination()
    test_scenario_3_broadcast_and_response()
    test_scenario_4_message_routing_isolation()
    test_scenario_5_agent_status_lifecycle()
    test_scenario_6_rapid_conversation()

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
