from __future__ import annotations

import os
import unittest
from pathlib import Path


FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "Frontend",
)


class TestBuddyWidgetAuthContract(unittest.TestCase):
    def test_buddy_widget_is_self_authenticated_for_http_and_websocket(self):
        raw = Path(os.path.join(FRONTEND_DIR, "buddy_widget.js")).read_text(encoding="utf-8")
        self.assertIn("window.__BRIDGE_UI_TOKEN", raw)
        self.assertIn("X-Bridge-Token", raw)
        self.assertIn("searchParams.set('token'", raw)
        self.assertIn("bridgeFetch(API + '/send'", raw)
        self.assertIn("new WebSocket(buildBridgeWsUrl(WS_URL))", raw)
        self.assertIn("data?.cli?.available", raw)


if __name__ == "__main__":
    unittest.main()
