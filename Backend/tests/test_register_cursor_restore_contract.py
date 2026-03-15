from __future__ import annotations

import copy
import os
import sys
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestRegisterCursorRestoreContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_messages = copy.deepcopy(srv.MESSAGES)
        self._orig_cursors = dict(srv.CURSORS)
        self._orig_runtime = copy.deepcopy(srv.RUNTIME)

    def tearDown(self) -> None:
        srv.MESSAGES[:] = self._orig_messages
        srv.CURSORS.clear()
        srv.CURSORS.update(self._orig_cursors)
        srv.RUNTIME.clear()
        srv.RUNTIME.update(self._orig_runtime)

    def _load_messages(self, ids: list[int]) -> None:
        srv.MESSAGES[:] = [
            {
                "id": msg_id,
                "from": "system",
                "to": "buddy",
                "content": f"m-{msg_id}",
                "timestamp": "2026-03-15T00:00:00Z",
            }
            for msg_id in ids
        ]

    def test_restore_receive_cursor_uses_last_received_message_id(self) -> None:
        self._load_messages([100, 101, 102, 103])

        srv.CURSORS.clear()
        srv._restore_receive_cursor_from_state(
            "buddy",
            {"last_message_id_received": 101},
        )

        self.assertEqual(srv.CURSORS.get("buddy"), 2)

    def test_restore_receive_cursor_never_moves_existing_cursor_backwards(self) -> None:
        self._load_messages([100, 101, 102, 103])

        srv.CURSORS.clear()
        srv.CURSORS["buddy"] = 3
        srv._restore_receive_cursor_from_state(
            "buddy",
            {"last_message_id_received": 101},
        )

        self.assertEqual(srv.CURSORS.get("buddy"), 3)

    def test_restore_receive_cursor_respects_runtime_keep_history(self) -> None:
        self._load_messages([100, 101, 102])

        srv.CURSORS.clear()
        srv.RUNTIME["keep_history"] = True
        with mock.patch.object(srv, "current_runtime_agent_ids", return_value={"buddy"}):
            srv._restore_receive_cursor_from_state(
                "buddy",
                {"last_message_id_received": 101},
            )

        self.assertNotIn("buddy", srv.CURSORS)


if __name__ == "__main__":
    unittest.main()
