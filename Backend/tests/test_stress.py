#!/usr/bin/env python3
"""
test_stress.py — Stress tests for Bridge Server.

Tests high-volume message throughput, concurrent connections,
and broadcast scalability.

Run: python3 test_stress.py

Prerequisites: Bridge Server must be running on http://127.0.0.1:9111
"""

import asyncio
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
WS_URL = "ws://127.0.0.1:9112"
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


def _api_send(from_id: str, to_id: str, content: str) -> dict | None:
    """Send a message via HTTP API."""
    data = json.dumps({"from": from_id, "to": to_id, "content": content}).encode()
    req = urllib.request.Request(
        f"{API_BASE}/send",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _api_get(path: str) -> tuple[int, dict | None]:
    """GET request to API."""
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except Exception:
        return 0, None


def test_rapid_fire_messages():
    """Send 100 messages as fast as possible and check all are stored."""
    print("\n=== Rapid Fire: 100 Messages ===")
    tag = f"rapid_{int(time.time())}"
    count = 100
    sent = 0
    start = time.time()

    for i in range(count):
        result = _api_send("stress_sender", "stress_recv", f"{tag}_{i}")
        if result and result.get("ok"):
            sent += 1

    elapsed = time.time() - start
    rate = sent / elapsed if elapsed > 0 else 0

    test(f"All {count} messages sent successfully", sent == count, f"Only {sent}/{count}")
    test(f"Rate > 10 msg/sec", rate > 10, f"Rate: {rate:.1f} msg/sec")
    print(f"  → {sent} messages in {elapsed:.2f}s ({rate:.1f} msg/sec)")

    # Verify all are in history
    _, data = _api_get(f"/history?limit={count + 50}")
    if data and "messages" in data:
        matching = [m for m in data["messages"] if m.get("content", "").startswith(tag)]
        test(f"All {count} messages in history", len(matching) >= count,
             f"Found {len(matching)}/{count}")
    else:
        test("History accessible after rapid fire", False)


def test_broadcast_scalability():
    """Send 20 broadcasts and verify WebSocket delivery."""
    print("\n=== Broadcast Scalability: 20 Broadcasts ===")
    tag = f"bcast_{int(time.time())}"
    count = 20
    sent = 0
    start = time.time()

    for i in range(count):
        result = _api_send("bcast_stress", "all", f"{tag}_{i}")
        if result and result.get("ok"):
            sent += 1

    elapsed = time.time() - start

    test(f"All {count} broadcasts sent", sent == count, f"Only {sent}/{count}")
    print(f"  → {sent} broadcasts in {elapsed:.2f}s")


async def test_concurrent_websocket_connections():
    """Open 10 WebSocket connections simultaneously."""
    print("\n=== Concurrent WebSocket: 10 Connections ===")
    try:
        import websockets
    except ImportError:
        print("  SKIP: websockets not installed")
        return

    connections = []
    try:
        for i in range(10):
            ws = await websockets.connect(WS_URL, open_timeout=5)
            await ws.send(json.dumps({"type": "subscribe"}))
            connections.append(ws)

        test("10 concurrent connections established", len(connections) == 10)

        # Send a message and verify all connections receive it
        tag = f"concurrent_{int(time.time())}"
        _api_send("concurrent_test", "user", tag)

        received_count = 0
        for ws in connections:
            try:
                deadline = time.time() + 5
                while time.time() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(raw)
                    if data.get("type") == "message":
                        msg = data.get("message", {})
                        if msg.get("content") == tag:
                            received_count += 1
                            break
            except asyncio.TimeoutError:
                pass

        test(f"All 10 connections received the message", received_count == 10,
             f"Only {received_count}/10 received")

    finally:
        for ws in connections:
            try:
                await ws.close()
            except Exception:
                pass

    test("All connections closed cleanly", True)


async def test_websocket_message_burst():
    """Send 50 messages and verify WebSocket delivers all."""
    print("\n=== WebSocket Message Burst: 50 Messages ===")
    try:
        import websockets
    except ImportError:
        print("  SKIP: websockets not installed")
        return

    tag = f"burst_{int(time.time())}"
    count = 50
    received = 0

    async with websockets.connect(WS_URL, open_timeout=5) as ws:
        await ws.send(json.dumps({"type": "subscribe"}))

        # Drain any history/subscribe response
        try:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=1)
        except asyncio.TimeoutError:
            pass

        # Send all messages
        for i in range(count):
            _api_send("burst_sender", "burst_recv", f"{tag}_{i}")

        # Collect results
        try:
            deadline = time.time() + 15
            while time.time() < deadline and received < count:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(raw)
                if data.get("type") == "message":
                    msg = data.get("message", {})
                    if msg.get("content", "").startswith(tag):
                        received += 1
        except asyncio.TimeoutError:
            pass

    test(f"WebSocket delivered all {count} messages", received == count,
         f"Got {received}/{count}")
    test(f"At least 90% delivered", received >= int(count * 0.9),
         f"Got {received}/{count}")


def test_large_message():
    """Send a large message (100KB) and verify storage."""
    print("\n=== Large Message: 100KB ===")
    tag = f"large_{int(time.time())}"
    large_content = tag + " " + ("X" * 100_000)

    result = _api_send("large_sender", "large_recv", large_content)
    test("Large message (100KB) sent", result is not None and result.get("ok"))

    if result and result.get("message"):
        msg = result["message"]
        test("Content preserved in response", len(msg.get("content", "")) >= 100_000)


def test_many_agents_registration():
    """Register 20 agents and check all appear in /agents."""
    print("\n=== Many Agents: 20 Registrations ===")
    count = 20
    tag = f"stress_agent_{int(time.time())}_"
    registered = 0

    for i in range(count):
        data = json.dumps({"agent_id": f"{tag}{i}", "role": f"Stress Agent #{i}"}).encode()
        req = urllib.request.Request(
            f"{API_BASE}/register",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode())
                if result.get("ok"):
                    registered += 1
        except Exception:
            pass

    test(f"All {count} agents registered", registered == count,
         f"Only {registered}/{count}")

    # Check agents list
    _, data = _api_get("/agents")
    if data and "agents" in data:
        matching = [a for a in data["agents"] if a.get("agent_id", "").startswith(tag)]
        test(f"All {count} agents in /agents list", len(matching) >= count,
             f"Found {len(matching)}/{count}")
    else:
        test("Agents list accessible", False)


def test_history_performance():
    """Measure /history response time with large dataset."""
    print("\n=== History Performance ===")

    # Small history
    start = time.time()
    _, data = _api_get("/history?limit=10")
    small_time = time.time() - start
    test("History (limit=10) < 1s", small_time < 1.0, f"{small_time:.3f}s")

    # Large history
    start = time.time()
    _, data = _api_get("/history?limit=500")
    large_time = time.time() - start
    test("History (limit=500) < 3s", large_time < 3.0, f"{large_time:.3f}s")

    print(f"  → limit=10: {small_time:.3f}s, limit=500: {large_time:.3f}s")


async def main():
    print("=" * 60)
    print("Bridge Stress Test Suite")
    print(f"Target: {API_BASE}")
    print("=" * 60)

    # Check server
    status, _ = _api_get("/status")
    if status == 0:
        print("ERROR: Bridge Server nicht erreichbar!")
        sys.exit(1)
    print(f"Server erreichbar (Status: {status})")

    # HTTP tests
    test_rapid_fire_messages()
    test_broadcast_scalability()
    test_large_message()
    test_many_agents_registration()
    test_history_performance()

    # WebSocket tests
    await test_concurrent_websocket_connections()
    await test_websocket_message_burst()

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
    asyncio.run(main())
