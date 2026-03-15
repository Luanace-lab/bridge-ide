from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.logs_routes as logs_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.response_code = None
        self.response_payload = None

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload


class TestLogsRoutesContract(unittest.TestCase):
    def test_server_uses_extracted_logs_get_handler(self) -> None:
        self.assertIs(srv._handle_logs_get, logs_mod.handle_get)

    def test_logs_handler_returns_false_for_non_matching_route(self) -> None:
        dummy = _DummyHandler()
        self.assertFalse(logs_mod.handle_get(dummy, "/not-logs", {}))
        self.assertIsNone(dummy.response_code)


if __name__ == "__main__":
    unittest.main()
