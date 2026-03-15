from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.data as data_mod  # noqa: E402
import server as srv  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.parsed_body = None
        self.response_code = None
        self.response_payload = None

    def _parse_json_body(self):
        return self.parsed_body

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload


class TestServerDataContract(unittest.TestCase):
    def test_server_uses_extracted_data_handlers(self) -> None:
        self.assertIs(srv._handle_data_get, data_mod.handle_get)
        self.assertIs(srv._handle_data_post, data_mod.handle_post)

    def test_data_handler_returns_false_for_non_data_route(self) -> None:
        dummy = _DummyHandler()
        self.assertFalse(data_mod.handle_get(dummy, "/not-data"))
        self.assertFalse(data_mod.handle_post(dummy, "/not-data"))
        self.assertIsNone(dummy.response_code)


if __name__ == "__main__":
    unittest.main()
