from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.execution_routes as execution_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.headers = {}
        self.response_code = None
        self.response_payload = None

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload


class TestExecutionRoutesContract(unittest.TestCase):
    def test_server_uses_extracted_execution_get_handler(self) -> None:
        self.assertIs(srv._handle_execution_get, execution_mod.handle_get)
        self.assertIs(srv._handle_execution_post, execution_mod.handle_post)

    def test_execution_handler_returns_false_for_non_execution_route(self) -> None:
        dummy = _DummyHandler()
        self.assertFalse(execution_mod.handle_get(dummy, "/not-execution", ""))
        self.assertFalse(execution_mod.handle_post(dummy, "/not-execution"))
        self.assertIsNone(dummy.response_code)


if __name__ == "__main__":
    unittest.main()
