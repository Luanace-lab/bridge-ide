from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "Frontend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class _DummyHandler:
    def __init__(self, token: str):
        self.headers = {"X-Bridge-Token": token}

    _extract_auth_token = srv.BridgeHandler._extract_auth_token


class TestStrictAuthServerHelpers(unittest.TestCase):
    def test_inject_ui_token_inserts_script_before_head_close(self):
        old = srv._UI_SESSION_TOKEN
        try:
            srv._UI_SESSION_TOKEN = "ui-test-token"
            body = b"<html><head><title>Bridge</title></head><body></body></html>"
            injected = srv._inject_ui_token(body)
        finally:
            srv._UI_SESSION_TOKEN = old

        marker = b'window.__BRIDGE_UI_TOKEN="ui-test-token"'
        self.assertIn(marker, injected)
        self.assertLess(injected.index(marker), injected.lower().index(b"</head>"))

    def test_resolve_auth_identity_accepts_ui_token_as_user(self):
        old = srv._UI_SESSION_TOKEN
        try:
            srv._UI_SESSION_TOKEN = "ui-test-token"
            handler = _DummyHandler("ui-test-token")
            role, identity = srv.BridgeHandler._resolve_auth_identity(handler)
        finally:
            srv._UI_SESSION_TOKEN = old

        self.assertEqual(role, "user")
        self.assertEqual(identity, "ui")

    def test_sensitive_get_paths_require_auth(self):
        handler = _DummyHandler("ignored")
        sensitive_paths = [
            "/agents",
            "/agent/config",
            "/automations",
            "/automations/test-auto",
            "/automations/test-auto/history",
            "/automations/test-auto/history/exec-1",
            "/events/subscriptions",
            "/history",
            "/logs",
            "/messages",
            "/n8n/executions",
            "/n8n/workflows",
            "/task/queue",
            "/workflows/tools",
        ]
        public_paths = [
            "/",
            "/health",
            "/receive/codex",
            "/status",
        ]

        for path in sensitive_paths:
            self.assertTrue(srv.BridgeHandler._path_requires_auth_get(handler, path), path)
        for path in public_paths:
            self.assertFalse(srv.BridgeHandler._path_requires_auth_get(handler, path), path)


class TestFrontendStrictAuthContract(unittest.TestCase):
    def _read(self, filename: str) -> str:
        return Path(os.path.join(FRONTEND_DIR, filename)).read_text(encoding="utf-8")

    def test_chat_references_ui_token_for_fetch_and_websocket(self):
        raw = self._read("chat.html")
        self.assertIn("__BRIDGE_UI_TOKEN", raw)
        self.assertIn("X-Bridge-Token", raw)
        self.assertIn("bridge_runtime_urls.js", raw)
        self.assertIn("BridgeRuntimeUrls.buildWsUrl", raw)
        self.assertIn("BridgeRuntimeUrls.isBridgeHttpTarget", raw)
        self.assertIn("bridgeHandleInvalidSessionToken", raw)
        self.assertIn("invalid session token", raw)
        self.assertIn("err === 'authentication required'", raw)
        self.assertIn("res.status === 401 || res.status === 403", raw)
        self.assertIn("code === 4001", raw)

    def test_control_center_references_ui_token_for_fetch_and_websocket(self):
        raw = self._read("control_center.html")
        self.assertIn("__BRIDGE_UI_TOKEN", raw)
        self.assertIn("X-Bridge-Token", raw)
        self.assertIn("bridge_runtime_urls.js", raw)
        self.assertIn("BridgeRuntimeUrls.buildWsUrl", raw)
        self.assertIn("BridgeRuntimeUrls.isBridgeHttpTarget", raw)
        self.assertIn("bridgeHandleInvalidSessionToken", raw)
        self.assertIn("invalid session token", raw)
        self.assertIn("err === 'authentication required'", raw)
        self.assertIn("res.status === 401 || res.status === 403", raw)
        self.assertIn("code === 4001", raw)

    def test_project_config_references_ui_token_for_authenticated_posts(self):
        raw = self._read("project_config.html")
        self.assertIn("__BRIDGE_UI_TOKEN", raw)
        self.assertIn("X-Bridge-Token", raw)

    def test_buddy_widget_is_not_bare_for_bridge_http_or_websocket(self):
        raw = self._read("buddy_widget.js")
        self.assertIn("__BRIDGE_UI_TOKEN", raw)
        self.assertIn("X-Bridge-Token", raw)
        self.assertIn("searchParams.set('token'", raw)

    def test_buddy_landing_uses_ui_token_for_bridge_http_writes(self):
        raw = self._read("buddy_landing.html")
        self.assertIn("__BRIDGE_UI_TOKEN", raw)
        self.assertIn("X-Bridge-Token", raw)
        self.assertIn("bridgeFetch(`${API_BASE}/agents/${BUDDY_ID}/start`", raw)
        self.assertIn("bridgeFetch(`${API_BASE}/send`", raw)
        self.assertIn("BridgeRuntimeUrls.isBridgeHttpTarget", raw)


if __name__ == "__main__":
    unittest.main()
