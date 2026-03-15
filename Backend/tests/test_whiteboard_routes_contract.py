from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.whiteboard as whiteboard_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, payload: dict | None = None, headers: dict[str, str] | None = None):
        self._payload = payload or {}
        self.headers = headers or {}
        self.responses: list[tuple[int, dict]] = []

    def _parse_json_body(self) -> dict:
        return dict(self._payload)

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestWhiteboardRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="whiteboard_routes_contract_")
        self._whiteboard: dict[str, dict] = {}
        self._broadcasts: list[tuple[str, dict]] = []
        self._lock = threading.RLock()
        whiteboard_mod.init(
            whiteboard=self._whiteboard,
            whiteboard_lock=self._lock,
            team_config={"agents": [{"id": "codex", "name": "Codex"}]},
            base_dir=self._tmpdir,
            agent_log_dir=self._tmpdir,
            whiteboard_valid_types={"status", "blocker", "result", "alert", "escalation_response"},
            ws_broadcast_fn=lambda event, payload: self._broadcasts.append((event, payload)),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_handle_get_filters_priority(self) -> None:
        whiteboard_mod._whiteboard_post("codex", "status", "low", priority=1)
        whiteboard_mod._whiteboard_post("codex", "alert", "high", priority=3)
        handler = _DummyHandler()

        handled = whiteboard_mod.handle_get(
            handler,
            "/whiteboard",
            {"priority": ["2"], "limit": ["10"]},
        )

        self.assertTrue(handled)
        self.assertEqual(handler.responses[0][0], 200)
        body = handler.responses[0][1]
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["entries"][0]["content"], "high")

    def test_handle_post_creates_entry_and_broadcasts(self) -> None:
        handler = _DummyHandler(
            payload={
                "agent_id": "codex",
                "type": "status",
                "content": "Slice66 whiteboard",
                "priority": 2,
            }
        )

        handled = whiteboard_mod.handle_post(handler, "/whiteboard")

        self.assertTrue(handled)
        status, body = handler.responses[0]
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["entry"]["content"], "Slice66 whiteboard")
        self.assertEqual(len(self._broadcasts), 1)
        self.assertEqual(self._broadcasts[0][0], "whiteboard_updated")

    def test_handle_post_alias_falls_back_to_status_type(self) -> None:
        handler = _DummyHandler(
            payload={
                "agent_id": "codex",
                "type": "not-valid",
                "content": "Alias entry",
            }
        )

        handled = whiteboard_mod.handle_post(handler, "/whiteboard/post")

        self.assertTrue(handled)
        status, body = handler.responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["entry"]["type"], "status")

    def test_handle_delete_removes_entry(self) -> None:
        entry = whiteboard_mod._whiteboard_post("codex", "status", "delete me")
        handler = _DummyHandler()

        handled = whiteboard_mod.handle_delete(handler, f"/whiteboard/{entry['id']}")

        self.assertTrue(handled)
        status, body = handler.responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["deleted"]["id"], entry["id"])
        self.assertEqual(self._broadcasts[0][0], "whiteboard_deleted")


if __name__ == "__main__":
    unittest.main()
