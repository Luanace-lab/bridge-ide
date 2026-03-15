from __future__ import annotations

import os
import sys
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.memory as memory_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload
        self.responses: list[tuple[int, dict]] = []

    def _parse_json_body(self) -> dict | None:
        return None if self._payload is None else dict(self._payload)

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestMemorySemanticRoutesContract(unittest.TestCase):
    def test_index_search_delete_scope_roundtrip(self) -> None:
        with mock.patch(
            "semantic_memory.index_scoped_text",
            return_value={"ok": True, "scope_type": "project", "scope_id": "slice73", "document_id": "doc1"},
        ) as index_mock, mock.patch(
            "semantic_memory.search_scope",
            return_value={"ok": True, "matches": [{"document_id": "doc1"}], "count": 1},
        ) as search_mock, mock.patch(
            "semantic_memory.delete_document",
            return_value={"ok": True, "deleted": 1},
        ) as delete_mock:
            index_handler = _DummyHandler(
                {
                    "scope_type": "project",
                    "scope_id": "slice73",
                    "text": "Semantic memory route test.",
                    "document_id": "doc1",
                    "replace_document": True,
                }
            )
            self.assertTrue(memory_mod.handle_post(index_handler, "/memory/index"))
            self.assertEqual(index_handler.responses[0][0], 200)
            self.assertTrue(index_handler.responses[0][1]["ok"])
            index_mock.assert_called_once()

            search_handler = _DummyHandler(
                {"scope_type": "project", "scope_id": "slice73", "query": "route test"}
            )
            self.assertTrue(memory_mod.handle_post(search_handler, "/memory/search"))
            self.assertEqual(search_handler.responses[0][0], 200)
            self.assertEqual(search_handler.responses[0][1]["count"], 1)
            search_mock.assert_called_once()

            delete_handler = _DummyHandler(
                {"scope_type": "project", "scope_id": "slice73", "document_id": "doc1"}
            )
            self.assertTrue(memory_mod.handle_post(delete_handler, "/memory/delete"))
            self.assertEqual(delete_handler.responses[0][0], 200)
            self.assertTrue(delete_handler.responses[0][1]["ok"])
            delete_mock.assert_called_once_with("project", "slice73", "doc1")


if __name__ == "__main__":
    unittest.main()
