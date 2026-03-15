from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.shared_tools_routes as tools_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.headers = {}
        self.response_code = None
        self.response_payload = None

    def _parse_json_body(self):
        return None

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload


class TestSharedToolsRoutesContract(unittest.TestCase):
    def test_server_uses_extracted_shared_tools_handlers(self) -> None:
        self.assertIs(srv._handle_shared_tools_delete, tools_mod.handle_delete)
        self.assertIs(srv._handle_shared_tools_get, tools_mod.handle_get)
        self.assertIs(srv._handle_shared_tools_post, tools_mod.handle_post)

    def test_shared_tools_handlers_return_false_for_non_matching_route(self) -> None:
        dummy = _DummyHandler()
        self.assertFalse(tools_mod.handle_delete(dummy, "/not-tools"))
        self.assertFalse(tools_mod.handle_get(dummy, "/not-tools"))
        self.assertFalse(tools_mod.handle_post(dummy, "/not-tools"))
        self.assertIsNone(dummy.response_code)


if __name__ == "__main__":
    unittest.main()
