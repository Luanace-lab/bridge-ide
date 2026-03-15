from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.onboarding_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, body: dict | None = None, *, auth_result: tuple[bool, str, str] = (True, "user", "ui")) -> None:
        self._body = body
        self._auth_result = auth_result
        self.responses: list[tuple[int, dict]] = []

    def _parse_json_body(self) -> dict | None:
        return self._body

    def _require_authenticated(self):
        return self._auth_result

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestOnboardingRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        routes_mod.init(
            strict_auth_getter=lambda: False,
            ensure_buddy_frontdoor_fn=lambda user_id: {"status": "started", "user_id": user_id, "started": True},
            get_buddy_frontdoor_status_fn=lambda user_id: {"user_id": user_id, "known_user": False},
        )

    def test_server_uses_extracted_onboarding_handler(self) -> None:
        self.assertIs(srv._handle_onboarding_post, routes_mod.handle_post)

    def test_onboarding_route_returns_ok_payload(self) -> None:
        handler = _DummyHandler({"user_id": "slice96"})
        self.assertTrue(routes_mod.handle_post(handler, "/onboarding/start"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["user_id"], "slice96")

    def test_onboarding_route_enforces_user_role_when_strict(self) -> None:
        routes_mod.init(
            strict_auth_getter=lambda: True,
            ensure_buddy_frontdoor_fn=lambda user_id: {"status": "started", "user_id": user_id, "started": True},
            get_buddy_frontdoor_status_fn=lambda user_id: {"user_id": user_id, "known_user": False},
        )
        handler = _DummyHandler({"user_id": "slice96"}, auth_result=(True, "agent", "codex"))
        self.assertTrue(routes_mod.handle_post(handler, "/onboarding/start"))
        self.assertEqual(handler.responses[0][0], 403)

    def test_onboarding_status_route_returns_frontdoor_payload(self) -> None:
        routes_mod.init(
            strict_auth_getter=lambda: False,
            ensure_buddy_frontdoor_fn=lambda user_id: {"status": "started", "user_id": user_id, "started": True},
            get_buddy_frontdoor_status_fn=lambda user_id: {"user_id": user_id, "known_user": True, "buddy_running": False},
        )
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/onboarding/status", {"user_id": ["slice97"]}))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["user_id"], "slice97")
        self.assertTrue(handler.responses[0][1]["known_user"])


if __name__ == "__main__":
    unittest.main()
