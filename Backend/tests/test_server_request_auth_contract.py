from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import server_request_auth as auth_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, token: str):
        self.headers = {"X-Bridge-Token": token}
        self.response_code = None
        self.response_payload = None

    _extract_auth_token = srv.BridgeHandler._extract_auth_token
    _resolve_auth_identity = srv.BridgeHandler._resolve_auth_identity
    _require_authenticated = srv.BridgeHandler._require_authenticated
    _require_platform_operator = srv.BridgeHandler._require_platform_operator

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload


class TestServerRequestAuthContract(unittest.TestCase):
    def test_bridge_handler_reexports_extracted_auth_methods(self):
        self.assertIs(srv.BridgeHandler._extract_auth_token, auth_mod._extract_auth_token)
        self.assertIs(srv.BridgeHandler._resolve_auth_identity, auth_mod._resolve_auth_identity)
        self.assertIs(srv.BridgeHandler._require_authenticated, auth_mod._require_authenticated)
        self.assertIs(srv.BridgeHandler._require_platform_operator, auth_mod._require_platform_operator)
        self.assertIs(srv.BridgeHandler._path_requires_auth_get, auth_mod._path_requires_auth_get)
        self.assertIs(srv.BridgeHandler._path_requires_auth_post, auth_mod._path_requires_auth_post)

    def test_ui_token_getter_remains_live_after_extraction(self):
        old = srv._UI_SESSION_TOKEN
        try:
            srv._UI_SESSION_TOKEN = "slice40-ui-token"
            handler = _DummyHandler("slice40-ui-token")
            role, identity = srv.BridgeHandler._resolve_auth_identity(handler)
        finally:
            srv._UI_SESSION_TOKEN = old

        self.assertEqual(role, "user")
        self.assertEqual(identity, "ui")

    def test_platform_operator_uses_live_server_operator_set(self):
        old = set(srv.PLATFORM_OPERATOR_AGENTS)
        old_tokens = dict(srv.SESSION_TOKENS)
        try:
            srv.PLATFORM_OPERATOR_AGENTS.clear()
            srv.PLATFORM_OPERATOR_AGENTS.add("buddy")
            srv.SESSION_TOKENS["slice40-buddy"] = "buddy"
            handler = _DummyHandler("slice40-buddy")
            ok, role, identity = srv.BridgeHandler._require_platform_operator(handler)
        finally:
            srv.PLATFORM_OPERATOR_AGENTS.clear()
            srv.PLATFORM_OPERATOR_AGENTS.update(old)
            srv.SESSION_TOKENS.clear()
            srv.SESSION_TOKENS.update(old_tokens)

        self.assertTrue(ok)
        self.assertEqual(role, "agent")
        self.assertEqual(identity, "buddy")
        self.assertIsNone(handler.response_code)
