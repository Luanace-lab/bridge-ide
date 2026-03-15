from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.guardrails_routes as guardrails_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.headers = {}
        self.response_code = None
        self.response_payload = None

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload


class TestGuardrailsRoutesContract(unittest.TestCase):
    def test_server_uses_extracted_guardrails_get_handler(self) -> None:
        self.assertIs(srv._handle_guardrails_delete, guardrails_mod.handle_delete)
        self.assertIs(srv._handle_guardrails_get, guardrails_mod.handle_get)
        self.assertIs(srv._handle_guardrails_post, guardrails_mod.handle_post)
        self.assertIs(srv._handle_guardrails_put, guardrails_mod.handle_put)

    def test_guardrails_handler_returns_false_for_non_guardrails_route(self) -> None:
        dummy = _DummyHandler()
        self.assertFalse(guardrails_mod.handle_delete(dummy, "/not-guardrails"))
        self.assertFalse(guardrails_mod.handle_get(dummy, "/not-guardrails", ""))
        self.assertFalse(guardrails_mod.handle_post(dummy, "/not-guardrails"))
        self.assertFalse(guardrails_mod.handle_put(dummy, "/not-guardrails"))
        self.assertIsNone(dummy.response_code)


if __name__ == "__main__":
    unittest.main()
