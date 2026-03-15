from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.memory as memory_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestMemoryRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="memory_routes_contract_")
        self._project_path = os.path.join(self._tmpdir, "project")
        os.makedirs(self._project_path, exist_ok=True)
        memory_mod.init(
            ensure_parent_dir_fn=lambda path: os.makedirs(os.path.dirname(path), exist_ok=True),
            normalize_path_fn=lambda raw, _root: os.path.normpath(
                os.path.abspath(os.path.expanduser(str(raw)))
            ),
            root_dir_fn=lambda: self._tmpdir,
        )
        scaffold = memory_mod.scaffold_agent_memory(self._project_path)
        assert scaffold.get("ok"), scaffold
        write = memory_mod.write_agent_memory(
            self._project_path,
            "codex",
            "agent_private",
            "Slice71 private note.",
            mode="replace",
        )
        assert write.get("ok"), write

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_handle_get_status_and_read(self) -> None:
        status_handler = _DummyHandler()
        self.assertTrue(
            memory_mod.handle_get(
                status_handler,
                "/memory/status",
                {"project_path": [self._project_path], "agent_id": ["codex"], "role": ["backend"]},
            )
        )
        status_code, status_body = status_handler.responses[0]
        self.assertEqual(status_code, 200)
        self.assertTrue(status_body["initialized"])
        self.assertGreaterEqual(status_body["file_count"], 1)
        self.assertIn("constitution", status_body)
        self.assertEqual(status_body["constitution"]["agent_id"], "codex")
        self.assertEqual(status_body["constitution"]["role"], "backend")

        read_handler = _DummyHandler()
        self.assertTrue(
            memory_mod.handle_get(
                read_handler,
                "/memory/read",
                {
                    "project_path": [self._project_path],
                    "agent_id": ["codex"],
                    "max_tokens": ["600"],
                },
            )
        )
        read_code, read_body = read_handler.responses[0]
        self.assertEqual(read_code, 200)
        self.assertIn("Slice71 private note.", read_body["packet"])
        self.assertEqual(read_body["knowledge_sync"]["agent_scope"], "codex")

    def test_handle_get_stats_supports_agent_and_scope_modes(self) -> None:
        with mock.patch("semantic_memory.get_stats", return_value={"mode": "agent", "count": 2}), mock.patch(
            "semantic_memory.get_scope_stats",
            return_value={"mode": "scope", "count": 3},
        ):
            agent_handler = _DummyHandler()
            self.assertTrue(
                memory_mod.handle_get(
                    agent_handler,
                    "/memory/stats",
                    {"agent_id": ["codex"]},
                )
            )
            self.assertEqual(agent_handler.responses[0], (200, {"mode": "agent", "count": 2}))

            scope_handler = _DummyHandler()
            self.assertTrue(
                memory_mod.handle_get(
                    scope_handler,
                    "/memory/stats",
                    {"scope_type": ["project"], "scope_id": ["bridge"]},
                )
            )
            self.assertEqual(scope_handler.responses[0], (200, {"mode": "scope", "count": 3}))


if __name__ == "__main__":
    unittest.main()
