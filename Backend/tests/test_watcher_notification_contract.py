from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from bridge_watcher import format_notification  # noqa: E402


class TestWatcherNotificationContract(unittest.TestCase):
    def test_codex_notification_names_explicit_reply_target(self) -> None:
        notification = format_notification("system", "[HEARTBEAT_CHECK]", engine="codex")
        self.assertIn("bridge_receive()", notification)
        self.assertIn("bridge_send(to='system'", notification)

    def test_qwen_notification_names_explicit_reply_target(self) -> None:
        notification = format_notification("buddy", "Hallo", engine="qwen")
        self.assertIn("bridge_send(to='buddy'", notification)

    def test_claude_notification_stays_short(self) -> None:
        notification = format_notification("system", "[HEARTBEAT_CHECK]", engine="claude")
        self.assertIn("Pruefe bridge_receive() fuer Details.", notification)
        self.assertNotIn("bridge_send(to=", notification)


if __name__ == "__main__":
    unittest.main()
