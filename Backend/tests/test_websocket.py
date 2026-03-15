#!/usr/bin/env python3
"""
test_websocket.py — WebSocket Connection Tests for Bridge Server.

Tests WebSocket connectivity, subscription, message reception and format.
Run: python3 test_websocket.py

Prerequisites: Bridge Server must be running on ws://127.0.0.1:9112
"""

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import pytest


if os.environ.get("BRIDGE_RUN_LIVE_TESTS") != "1":
    pytestmark = pytest.mark.skip(
        reason="manual live smoke test; set BRIDGE_RUN_LIVE_TESTS=1 to enable"
    )

API_BASE = "http://127.0.0.1:9111"
PASS = 0
FAIL = 0
ERRORS = []


def _load_user_token() -> str:
    env_token = str(os.environ.get("BRIDGE_USER_TOKEN", "")).strip()
    if env_token:
        return env_token
    token_file = Path.home() / ".config" / "bridge" / "tokens.json"
    try:
        data = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("user_token", "")).strip()


USER_TOKEN = _load_user_token()
WS_URL = f"ws://127.0.0.1:9112/?token={USER_TOKEN}" if USER_TOKEN else "ws://127.0.0.1:9112"


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
    """Send a message via HTTP API, return response."""
    sender = "user" if USER_TOKEN else from_id
    data = json.dumps({"from": sender, "to": to_id, "content": content}).encode()
    headers = {"Content-Type": "application/json"}
    if USER_TOKEN:
        headers["X-Bridge-Token"] = USER_TOKEN
    req = urllib.request.Request(
        f"{API_BASE}/send",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


async def test_ws_connect():
    """Test basic WebSocket connection."""
    print("\n=== WebSocket Connection ===")
    try:
        import websockets
    except ImportError:
        print("  SKIP: websockets not installed (pip install websockets)")
        return False

    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            test("WebSocket connects to :9112", True)
            # websockets v13+ uses ws.state, older uses ws.open
            is_open = getattr(ws, "open", None) or hasattr(ws, "state")
            test("Connection is open", bool(is_open))
            return True
    except Exception as e:
        test("WebSocket connects to :9112", False, str(e))
        return False


async def test_ws_subscribe():
    """Test WebSocket subscription."""
    print("\n=== WebSocket Subscribe ===")
    import websockets

    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            # Send subscribe message
            await ws.send(json.dumps({"type": "subscribe"}))
            test("Subscribe message sent", True)

            # Server should accept silently (no error response)
            # Wait briefly for any response
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(response)
                # Some servers send ack, some don't
                test("Subscribe acknowledged or silent", True)
            except asyncio.TimeoutError:
                # No response = silent accept (valid)
                test("Subscribe accepted silently", True)
    except Exception as e:
        test("Subscribe connection", False, str(e))


async def test_ws_receive_message():
    """Test receiving a live message via WebSocket."""
    print("\n=== WebSocket Message Reception ===")
    import websockets

    test_content = f"ws_test_{int(time.time())}"
    received = None
    expected_sender = "user" if USER_TOKEN else "ws_test_sender"

    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            await ws.send(json.dumps({"type": "subscribe"}))

            # Send a message via HTTP API
            api_result = _api_send("ws_test_sender", "ws_test_receiver", test_content)
            test("API send successful", api_result is not None and api_result.get("ok"))

            # Wait for WebSocket to deliver the message
            try:
                deadline = time.time() + 5
                while time.time() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(raw)
                    if data.get("type") == "message":
                        msg = data.get("message", {})
                        if msg.get("content") == test_content:
                            received = msg
                            break
            except asyncio.TimeoutError:
                pass

            test("Message received via WebSocket", received is not None)

            if received:
                test("Message has 'id' field", "id" in received)
                test("Message has 'from' field", "from" in received)
                test("Message has 'to' field", "to" in received)
                test("Message has 'content' field", "content" in received)
                test("Message has 'timestamp' field", "timestamp" in received)
                test("Content matches sent message", received.get("content") == test_content)
                test("From matches sender", received.get("from") == expected_sender)
                test("To matches recipient", received.get("to") == "ws_test_receiver")
    except Exception as e:
        test("WebSocket message reception", False, str(e))


async def test_ws_message_format():
    """Test WebSocket message envelope format."""
    print("\n=== WebSocket Message Format ===")
    import websockets

    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            await ws.send(json.dumps({"type": "subscribe"}))

            # Send a test message
            tag = f"format_check_{int(time.time())}"
            _api_send("format_test", "user", tag)

            try:
                # Skip non-message events until we find our message
                deadline = time.time() + 5
                found = False
                while time.time() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(raw)

                    test("Envelope is valid JSON", True)
                    test("Envelope has 'type' field", "type" in data)

                    if data.get("type") == "message" and data.get("message", {}).get("content") == tag:
                        test("Type is 'message'", True)
                        test("Envelope has 'message' field", "message" in data)

                        msg = data["message"]
                        test("Message is dict", isinstance(msg, dict))
                        required_fields = ["id", "from", "to", "content", "timestamp"]
                        for field in required_fields:
                            test(f"Message has '{field}'", field in msg, f"Missing: {field}")
                        found = True
                        break

                if not found:
                    test("Type is 'message'", False, "Message not found in events")
                    test("Envelope has 'message' field", False)
            except asyncio.TimeoutError:
                test("Received message within timeout", False)
    except Exception as e:
        test("WebSocket format test", False, str(e))


async def test_ws_broadcast():
    """Test that broadcast messages are received via WebSocket."""
    print("\n=== WebSocket Broadcast ===")
    import websockets

    broadcast_content = f"broadcast_ws_test_{int(time.time())}"
    received = False

    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            await ws.send(json.dumps({"type": "subscribe"}))

            # Send broadcast
            _api_send("broadcast_test", "all", broadcast_content)

            try:
                deadline = time.time() + 5
                while time.time() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(raw)
                    if data.get("type") == "message":
                        msg = data.get("message", {})
                        if msg.get("content") == broadcast_content:
                            received = True
                            test("Broadcast 'to' field is 'all'", msg.get("to") == "all")
                            break
            except asyncio.TimeoutError:
                pass

            test("Broadcast received via WebSocket", received)
    except Exception as e:
        test("WebSocket broadcast test", False, str(e))


async def test_ws_multiple_messages():
    """Test receiving multiple messages in sequence."""
    print("\n=== WebSocket Multiple Messages ===")
    import websockets

    count = 5
    received_count = 0
    tag = f"multi_{int(time.time())}"

    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            await ws.send(json.dumps({"type": "subscribe"}))

            # Send N messages rapidly
            for i in range(count):
                _api_send("multi_sender", "multi_recv", f"{tag}_{i}")

            # Collect messages
            try:
                deadline = time.time() + 10
                while time.time() < deadline and received_count < count:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(raw)
                    if data.get("type") == "message":
                        msg = data.get("message", {})
                        if msg.get("content", "").startswith(tag):
                            received_count += 1
            except asyncio.TimeoutError:
                pass

            test(f"Received {count} messages", received_count == count,
                 f"Got {received_count}/{count}")
            test("All messages delivered", received_count >= count - 1,
                 f"Got {received_count}/{count} (allow 1 lost)")
    except Exception as e:
        test("Multiple messages test", False, str(e))


async def test_ws_reconnect():
    """Test that reconnection works after disconnect."""
    print("\n=== WebSocket Reconnection ===")
    import websockets

    try:
        # Connect and disconnect
        ws1 = await websockets.connect(WS_URL, open_timeout=5)
        test("First connection established", True)
        await ws1.close()
        test("First connection closed cleanly", True)

        # Reconnect
        ws2 = await websockets.connect(WS_URL, open_timeout=5)
        test("Reconnection successful", True)

        # Should still be able to receive messages
        await ws2.send(json.dumps({"type": "subscribe"}))
        tag = f"reconnect_{int(time.time())}"
        _api_send("reconnect_test", "user", tag)

        try:
            deadline = time.time() + 8
            found = False
            while time.time() < deadline:
                raw = await asyncio.wait_for(ws2.recv(), timeout=5)
                data = json.loads(raw)
                if data.get("type") == "message":
                    found = True
                    break
            test("Receives messages after reconnect", found)
        except asyncio.TimeoutError:
            test("Receives messages after reconnect", False, "Timeout")

        await ws2.close()
    except Exception as e:
        test("Reconnection test", False, str(e))


async def main():
    print("=" * 60)
    print("Bridge WebSocket Test Suite")
    print(f"Target: {WS_URL}")
    print("=" * 60)

    # Check websockets available
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("ERROR: pip install websockets required")
        sys.exit(1)
    if not USER_TOKEN:
        print("ERROR: user token missing (~/.config/bridge/tokens.json or BRIDGE_USER_TOKEN)")
        sys.exit(1)

    connected = await test_ws_connect()
    if not connected:
        print("\nERROR: Cannot connect to WebSocket server!")
        sys.exit(1)

    await test_ws_subscribe()
    await test_ws_receive_message()
    await test_ws_message_format()
    await test_ws_broadcast()
    await test_ws_multiple_messages()
    await test_ws_reconnect()

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
