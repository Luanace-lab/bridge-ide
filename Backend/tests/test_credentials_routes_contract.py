from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.credentials_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, *, headers: dict[str, str] | None = None, body: dict | None = None) -> None:
        self.headers = headers or {}
        self._body = body
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self._body


class TestCredentialsRoutesContract(unittest.TestCase):
    @patch("handlers.credentials_routes.credential_store.list_keys")
    def test_get_list_route(self, mock_list_keys) -> None:
        mock_list_keys.return_value = {"service": "custom", "keys": [{"key": "alpha"}]}
        handler = _DummyHandler(headers={"X-Bridge-Agent": "codex"})
        self.assertTrue(routes_mod.handle_get(handler, "/credentials/custom"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["service"], "custom")

    @patch("handlers.credentials_routes.credential_store.get")
    def test_get_value_route(self, mock_get) -> None:
        mock_get.return_value = {"service": "custom", "key": "alpha", "value": "secret"}
        handler = _DummyHandler(headers={"X-Bridge-Agent": "codex"})
        self.assertTrue(routes_mod.handle_get(handler, "/credentials/custom/alpha"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["key"], "alpha")

    @patch("handlers.credentials_routes.credential_store.store")
    def test_post_store_route(self, mock_store) -> None:
        mock_store.return_value = {"service": "custom", "key": "alpha", "stored": True}
        handler = _DummyHandler(headers={"X-Bridge-Agent": "codex"}, body={"value": "secret"})
        self.assertTrue(routes_mod.handle_post(handler, "/credentials/custom/alpha"))
        self.assertEqual(handler.responses[0][0], 201)
        self.assertTrue(handler.responses[0][1]["stored"])

    @patch("handlers.credentials_routes.credential_store.delete")
    def test_delete_route(self, mock_delete) -> None:
        mock_delete.return_value = {"service": "custom", "key": "alpha", "deleted": True}
        handler = _DummyHandler(headers={"X-Bridge-Agent": "codex"})
        self.assertTrue(routes_mod.handle_delete(handler, "/credentials/custom/alpha"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertTrue(handler.responses[0][1]["deleted"])

    def test_requires_agent_header(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/credentials/custom"))
        self.assertEqual(handler.responses[0][0], 401)

    def test_invalid_post_body_rejected(self) -> None:
        handler = _DummyHandler(headers={"X-Bridge-Agent": "codex"}, body=None)
        self.assertTrue(routes_mod.handle_post(handler, "/credentials/custom/alpha"))
        self.assertEqual(handler.responses[0][0], 400)


if __name__ == "__main__":
    unittest.main()
