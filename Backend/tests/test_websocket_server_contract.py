from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import websocket_server


class _DummyFuture:
    def result(self, timeout: float | None = None) -> None:
        return None


class _DummyWS:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


class TestWebsocketServerContract(unittest.TestCase):
    def tearDown(self) -> None:
        import server as srv

        websocket_server.init(
            bridge_user_token_getter=lambda: srv.BRIDGE_USER_TOKEN,
            ui_session_token_getter=lambda: srv._UI_SESSION_TOKEN,
            strict_auth_getter=lambda: srv.BRIDGE_STRICT_AUTH,
            agent_state_lock=srv.AGENT_STATE_LOCK,
            session_tokens=srv.SESSION_TOKENS,
            grace_tokens=srv.GRACE_TOKENS,
            append_message_fn=lambda *args, **kwargs: srv.append_message(*args, **kwargs),
            is_federation_target_fn=srv._is_federation_target,
            federation_send_outbound_fn=srv._federation_send_outbound,
            update_agent_status_fn=srv.update_agent_status,
            agent_busy=srv.AGENT_BUSY,
            agent_last_seen=srv.AGENT_LAST_SEEN,
            cond=srv.COND,
            messages=srv.MESSAGES,
            runtime_snapshot_fn=srv.runtime_snapshot,
            get_team_members_fn=srv.get_team_members,
            ws_host_getter=lambda: srv.WS_HOST,
            ws_port_getter=lambda: srv.WS_PORT,
            allowed_origins_getter=lambda: srv.ALLOWED_ORIGINS,
        )
        with websocket_server.WS_LOCK:
            websocket_server.WS_CLIENTS.clear()
        websocket_server.WS_LOOP = None

    def _init_test_state(self) -> None:
        lock = mock.Mock()
        cond = mock.MagicMock()
        websocket_server.init(
            bridge_user_token_getter=lambda: "user-token",
            ui_session_token_getter=lambda: "ui-token",
            strict_auth_getter=lambda: True,
            agent_state_lock=lock,
            session_tokens={"agent-token": "agent_a"},
            grace_tokens={},
            append_message_fn=mock.Mock(),
            is_federation_target_fn=lambda recipient: recipient.startswith("inst:"),
            federation_send_outbound_fn=lambda sender, recipient, content: {"relay": "ok"},
            update_agent_status_fn=mock.Mock(),
            agent_busy={},
            agent_last_seen={},
            cond=cond,
            messages=[],
            runtime_snapshot_fn=lambda: {"configured": True},
            get_team_members_fn=lambda team_id: ["agent_team"] if team_id == "bridge" else [],
            ws_host_getter=lambda: "127.0.0.1",
            ws_port_getter=lambda: 9112,
            allowed_origins_getter=lambda: ["http://127.0.0.1:9111"],
        )
        with websocket_server.WS_LOCK:
            websocket_server.WS_CLIENTS.clear()
        websocket_server.WS_LOOP = object()  # any non-None loop marker

    def test_ws_broadcast_pushes_json_event_to_clients(self) -> None:
        self._init_test_state()
        dummy = _DummyWS()
        with websocket_server.WS_LOCK:
            websocket_server.WS_CLIENTS[dummy] = {"agent_id": "ui", "role": "ui"}

        def _run_now(coro, _loop):
            asyncio.run(coro)
            return _DummyFuture()

        with mock.patch("asyncio.run_coroutine_threadsafe", side_effect=_run_now):
            websocket_server.ws_broadcast("runtime", {"configured": True})

        self.assertEqual(dummy.sent, [{"type": "runtime", "configured": True}])

    def test_ws_broadcast_message_targets_ui_and_team_members(self) -> None:
        self._init_test_state()
        ui_ws = _DummyWS()
        team_ws = _DummyWS()
        sender_ws = _DummyWS()
        other_ws = _DummyWS()
        with websocket_server.WS_LOCK:
            websocket_server.WS_CLIENTS.update(
                {
                    ui_ws: {"agent_id": "ui", "role": "ui"},
                    team_ws: {"agent_id": "agent_team", "role": "agent"},
                    sender_ws: {"agent_id": "agent_sender", "role": "agent"},
                    other_ws: {"agent_id": "agent_other", "role": "agent"},
                }
            )

        def _run_now(coro, _loop):
            asyncio.run(coro)
            return _DummyFuture()

        with mock.patch("asyncio.run_coroutine_threadsafe", side_effect=_run_now):
            websocket_server.ws_broadcast_message(
                {
                    "id": 1,
                    "from": "agent_sender",
                    "to": "team:bridge",
                    "content": "hello",
                    "timestamp": "2026-03-14T00:00:00+00:00",
                }
            )

        self.assertEqual(len(ui_ws.sent), 1)
        self.assertEqual(len(team_ws.sent), 1)
        self.assertEqual(len(sender_ws.sent), 0)
        self.assertEqual(len(other_ws.sent), 0)
        self.assertEqual(ui_ws.sent[0]["type"], "message")
        self.assertEqual(team_ws.sent[0]["message"]["content"], "hello")

    def test_run_websocket_server_returns_cleanly_when_library_missing(self) -> None:
        self._init_test_state()
        with mock.patch.object(websocket_server, "HAS_WEBSOCKETS", False):
            websocket_server.run_websocket_server()


if __name__ == "__main__":
    unittest.main()
