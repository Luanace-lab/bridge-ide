from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))
CHAT_PATH = os.path.join(REPO_ROOT, "BRIDGE", "Frontend", "chat.html")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestChatReactionServerContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_messages = list(srv.MESSAGES)
        self._orig_ws_broadcast = srv.ws_broadcast
        self._orig_append_message = srv.append_message
        self._orig_ui_session_token = srv._UI_SESSION_TOKEN
        self._ws_events: list[tuple[str, dict]] = []
        self._ui_token = "ui-test-token"

        srv.MESSAGES[:] = []
        srv.ws_broadcast = lambda event_type, payload: self._ws_events.append((event_type, payload))
        srv.append_message = lambda *_args, **_kwargs: None
        srv._UI_SESSION_TOKEN = self._ui_token

    def tearDown(self) -> None:
        srv.MESSAGES[:] = self._orig_messages
        srv.ws_broadcast = self._orig_ws_broadcast
        srv.append_message = self._orig_append_message
        srv._UI_SESSION_TOKEN = self._orig_ui_session_token

    def _start_server(self) -> str:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Bridge-Token": self._ui_token},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_reaction_endpoint_allows_clearing_existing_reaction(self) -> None:
        srv.MESSAGES[:] = [
            {
                "id": 41,
                "from": "viktor",
                "to": "user",
                "content": "Hello",
                "timestamp": srv.utc_now_iso(),
                "reactions": {
                    "user": {"type": "thumbs_up", "at": srv.utc_now_iso()},
                },
            }
        ]

        base_url = self._start_server()
        status, body = self._post(base_url, "/messages/41/reaction", {"reaction": None, "from": "user"})

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["cleared"])
        self.assertIsNone(body["reaction"])
        self.assertNotIn("user", srv.MESSAGES[0].get("reactions", {}))
        self.assertEqual(self._ws_events[0][0], "reaction")
        self.assertEqual(self._ws_events[0][1]["msg_id"], 41)
        self.assertTrue(self._ws_events[0][1]["cleared"])


class TestChatReactionFrontendContract(unittest.TestCase):
    def _read(self) -> str:
        return Path(CHAT_PATH).read_text(encoding="utf-8")

    def test_chat_initializes_reaction_buttons_from_message_state(self) -> None:
        raw = self._read()
        self.assertIn("msg.reactions", raw)
        self.assertIn("applyReactionState", raw)

    def test_chat_handles_reaction_websocket_updates(self) -> None:
        raw = self._read()
        self.assertIn("data.type === 'reaction'", raw)
        self.assertIn("applyReactionEvent", raw)


if __name__ == "__main__":
    unittest.main()
