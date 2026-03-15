from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.teamlead_scope_routes as scope_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.response_code = None
        self.response_payload = None

    def _parse_json_body(self):
        return None

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload


class TestTeamleadScopeRoutesContract(unittest.TestCase):
    def test_server_uses_extracted_teamlead_scope_handlers(self) -> None:
        self.assertIs(srv._handle_teamlead_scope_get, scope_mod.handle_get)
        self.assertIs(srv._handle_teamlead_scope_post, scope_mod.handle_post)

    def test_teamlead_scope_handlers_return_false_for_non_matching_route(self) -> None:
        dummy = _DummyHandler()
        self.assertFalse(scope_mod.handle_get(dummy, "/not-teamlead-scope", {}))
        self.assertFalse(scope_mod.handle_post(dummy, "/not-teamlead-scope"))
        self.assertIsNone(dummy.response_code)


if __name__ == "__main__":
    unittest.main()
