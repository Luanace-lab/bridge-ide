from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BACKEND_DIR.parent / "Frontend"


class TestFrontendRuntimeUrlContract(unittest.TestCase):
    def _read(self, name: str) -> str:
        return (FRONTEND_DIR / name).read_text(encoding="utf-8")

    def test_shared_runtime_url_helper_exists(self):
        raw = self._read("bridge_runtime_urls.js")
        self.assertIn("resolveConfig", raw)
        self.assertIn("isBridgeHttpTarget", raw)
        self.assertIn("buildWsUrl", raw)

    def test_active_pages_load_shared_runtime_url_helper(self):
        for name in [
            "chat.html",
            "control_center.html",
            "project_config.html",
            "task_tracker.html",
            "buddy_landing.html",
        ]:
            with self.subTest(name=name):
                raw = self._read(name)
                self.assertIn('bridge_runtime_urls.js', raw)

    def test_active_pages_use_shared_runtime_resolution(self):
        pages = {
            "chat.html": ["BridgeRuntimeUrls.resolveConfig", "BridgeRuntimeUrls.isBridgeHttpTarget", "BridgeRuntimeUrls.buildWsUrl"],
            "control_center.html": ["BridgeRuntimeUrls.resolveConfig", "BridgeRuntimeUrls.isBridgeHttpTarget", "BridgeRuntimeUrls.buildWsUrl"],
            "project_config.html": ["BridgeRuntimeUrls.resolveConfig", "BridgeRuntimeUrls.isBridgeHttpTarget"],
            "task_tracker.html": ["BridgeRuntimeUrls.resolveConfig", "BridgeRuntimeUrls.isBridgeHttpTarget"],
            "buddy_landing.html": ["BridgeRuntimeUrls.resolveConfig"],
            "buddy_widget.js": ["BridgeRuntimeUrls.resolveConfig"],
        }
        for name, markers in pages.items():
            raw = self._read(name)
            for marker in markers:
                with self.subTest(name=name, marker=marker):
                    self.assertIn(marker, raw)

    def test_active_pages_do_not_hardcode_local_bridge_endpoints(self):
        forbidden_patterns = [
            r"const API_BASE = 'http://127\.0\.0\.1:9111'",
            r"const API_BASE = 'http://localhost:9111'",
            r"const API_SERVER = 'http://127\.0\.0\.1:9111'",
            r"const WS_URL = 'ws://127\.0\.0\.1:9112'",
            r"const WS_URL = 'ws://localhost:9112'",
            r"fetch\('http://127\.0\.0\.1:9111",
            r'fetch\("http://127\.0\.0\.1:9111',
        ]
        for name in [
            "chat.html",
            "control_center.html",
            "project_config.html",
            "task_tracker.html",
            "buddy_landing.html",
            "buddy_widget.js",
        ]:
            raw = self._read(name)
            for pattern in forbidden_patterns:
                with self.subTest(name=name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, raw))

    def test_landing_page_no_longer_claims_fixed_local_ports(self):
        raw = self._read("landing.html")
        self.assertNotIn("Server running on :9111", raw)
        self.assertNotIn("WebSocket on :9112", raw)


if __name__ == "__main__":
    unittest.main()
