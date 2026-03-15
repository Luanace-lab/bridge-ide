from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest


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


class TestMemoryWriteRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="memory_write_routes_contract_")
        self._project_path = os.path.join(self._tmpdir, "project")
        os.makedirs(self._project_path, exist_ok=True)
        memory_mod.init(
            ensure_parent_dir_fn=lambda path: os.makedirs(os.path.dirname(path), exist_ok=True),
            normalize_path_fn=lambda raw, _root: os.path.normpath(
                os.path.abspath(os.path.expanduser(str(raw)))
            ),
            root_dir_fn=lambda: self._tmpdir,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_scaffold_write_episode_and_migrate(self) -> None:
        scaffold_handler = _DummyHandler({"project_path": self._project_path})
        self.assertTrue(memory_mod.handle_post(scaffold_handler, "/memory/scaffold"))
        self.assertEqual(scaffold_handler.responses[0][0], 201)

        write_handler = _DummyHandler(
            {
                "project_path": self._project_path,
                "agent_id": "codex",
                "category": "agent_private",
                "content": "Slice72 contract note.",
                "mode": "replace",
            }
        )
        self.assertTrue(memory_mod.handle_post(write_handler, "/memory/write"))
        self.assertEqual(write_handler.responses[0][0], 201)
        self.assertTrue(write_handler.responses[0][1]["file"].endswith("codex.md"))

        episode_handler = _DummyHandler(
            {
                "project_path": self._project_path,
                "agent_id": "codex",
                "summary": "Slice72 episode summary.",
                "task": "memory route contract",
                "metadata": {"kind": "contract"},
            }
        )
        self.assertTrue(memory_mod.handle_post(episode_handler, "/memory/episode"))
        self.assertEqual(episode_handler.responses[0][0], 201)
        self.assertTrue(episode_handler.responses[0][1]["episode_file"].endswith(".md"))

        project_note = os.path.join(self._project_path, ".agent", "project", "PROJECT.md")
        with open(project_note, "w", encoding="utf-8") as handle:
            handle.write("Slice72 migrate content.")

        migrate_handler = _DummyHandler({"project_path": self._project_path})
        self.assertTrue(memory_mod.handle_post(migrate_handler, "/memory/migrate"))
        self.assertEqual(migrate_handler.responses[0][0], 200)
        self.assertTrue(migrate_handler.responses[0][1]["ok"])


if __name__ == "__main__":
    unittest.main()
