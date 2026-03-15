from __future__ import annotations

import os
import sys
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class _DummySendHandler:
    def __init__(self, body: dict, token: str):
        self.path = "/send"
        self.headers = {"X-Bridge-Token": token}
        self._body = body
        self.response_code = None
        self.response_payload = None
        self.client_address = ("127.0.0.1", 0)

    _extract_auth_token = srv.BridgeHandler._extract_auth_token
    _resolve_auth_identity = srv.BridgeHandler._resolve_auth_identity
    _require_authenticated = srv.BridgeHandler._require_authenticated
    _path_requires_auth_post = srv.BridgeHandler._path_requires_auth_post
    _check_rate_limit = srv.BridgeHandler._check_rate_limit
    _handle_post = srv.BridgeHandler._handle_post

    def _parse_json_body(self):
        return self._body

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload


class TestSendSystemRecipientContract(unittest.TestCase):
    def setUp(self) -> None:
        self.old_strict_auth = srv.BRIDGE_STRICT_AUTH
        self.old_session_tokens = dict(srv.SESSION_TOKENS)
        self.old_agent_busy = dict(srv.AGENT_BUSY)
        self.old_agent_last_seen = dict(srv.AGENT_LAST_SEEN)

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self.old_strict_auth
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS.update(self.old_session_tokens)
        srv.AGENT_BUSY.clear()
        srv.AGENT_BUSY.update(self.old_agent_busy)
        srv.AGENT_LAST_SEEN.clear()
        srv.AGENT_LAST_SEEN.update(self.old_agent_last_seen)

    def test_agent_may_send_internal_report_to_system(self) -> None:
        srv.BRIDGE_STRICT_AUTH = True
        srv.SESSION_TOKENS["slice47-codex-token"] = "codex"
        handler = _DummySendHandler(
            {"from": "codex", "to": "system", "content": "interner Bericht"},
            token="slice47-codex-token",
        )

        with (
            mock.patch.object(
                srv,
                "append_message",
                return_value={"id": 47001, "from": "codex", "to": "system", "content": "interner Bericht"},
            ) as append_message_mock,
            mock.patch.object(srv.event_bus, "emit_message_sent"),
            mock.patch.object(srv.event_bus, "emit_message_received"),
            mock.patch.object(srv, "update_agent_status"),
            mock.patch.object(srv, "_save_agent_state"),
        ):
            srv.BridgeHandler.do_POST(handler)

        self.assertEqual(handler.response_code, 201)
        self.assertIsInstance(handler.response_payload, dict)
        self.assertTrue(handler.response_payload.get("ok"))
        self.assertFalse(handler.response_payload.get("suppressed", False))
        append_message_mock.assert_called_once()
        self.assertEqual(append_message_mock.call_args.args[1], "system")

    def test_agent_to_watcher_stays_suppressed(self) -> None:
        srv.BRIDGE_STRICT_AUTH = True
        srv.SESSION_TOKENS["slice47-codex-token"] = "codex"
        handler = _DummySendHandler(
            {"from": "codex", "to": "watcher", "content": "interner Bericht"},
            token="slice47-codex-token",
        )

        with mock.patch.object(srv, "append_message") as append_message_mock:
            srv.BridgeHandler.do_POST(handler)

        self.assertEqual(handler.response_code, 200)
        self.assertTrue(handler.response_payload.get("suppressed"))
        self.assertIn("watcher", handler.response_payload.get("reason", ""))
        append_message_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
