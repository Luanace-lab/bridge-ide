from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))
KNOWLEDGE_PATH = os.path.join(BACKEND_DIR, "knowledge_engine.py")
SERVER_PATH = os.path.join(BACKEND_DIR, "server.py")
BUDDY_CLAUDE_PATH = os.path.join(REPO_ROOT, "Buddy", "CLAUDE.md")
BUDDY_PROMPT_PATH = os.path.join(REPO_ROOT, "Buddy", "prompts", "buddy.txt")
BUDDY_GUIDE_PATH = os.path.join(REPO_ROOT, "Buddy", "BRIDGE_OPERATOR_GUIDE.md")
BUDDY_AGENTS_PATH = os.path.join(REPO_ROOT, "Buddy", "AGENTS.md")
BUDDY_GEMINI_PATH = os.path.join(REPO_ROOT, "Buddy", "GEMINI.md")
BUDDY_QWEN_PATH = os.path.join(REPO_ROOT, "Buddy", "QWEN.md")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestBuddyUserScopeContract(unittest.TestCase):
    def setUp(self):
        self._orig_ke = sys.modules.get("knowledge_engine")
        self._orig_sm = sys.modules.get("semantic_memory")
        if self._orig_sm is None:
            import semantic_memory
            self._orig_sm = semantic_memory
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def tearDown(self):
        if self._orig_ke is not None:
            sys.modules["knowledge_engine"] = self._orig_ke
        elif "knowledge_engine" in sys.modules:
            del sys.modules["knowledge_engine"]
        # Always restore the real semantic_memory module
        sys.modules["semantic_memory"] = self._orig_sm

    def _load_isolated_ke(self):
        import importlib.util
        import types

        fake_sm = types.SimpleNamespace(
            index_scoped_text=lambda *args, **kwargs: {"ok": True, "chunks_added": 1},
            delete_document=lambda *args, **kwargs: {"ok": True, "deleted_chunks": 1},
        )
        sys.modules["semantic_memory"] = fake_sm

        spec = importlib.util.spec_from_file_location("knowledge_engine", KNOWLEDGE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        module._VAULT_DIR = str(Path(self._tmpdir.name) / "Knowledge")
        sys.modules["knowledge_engine"] = module
        return module

    def test_seed_buddy_user_scope_migrates_local_legacy_json(self):
        ke = self._load_isolated_ke()

        legacy_dir = Path(self._tmpdir.name) / "Buddy"
        (legacy_dir / "memory").mkdir(parents=True, exist_ok=True)
        legacy_payload = {
            "user_id": "testuser",
            "display_name": "Testuser",
            "persona": "non-tech",
            "guidance_mode": "uebernehmen",
            "autonomy_preference": "hoch",
            "preferred_channels": ["bridge", "whatsapp"],
            "active_projects": ["launch"],
            "open_loops": ["welcome"],
            "trust_notes": "Prefers direct language.",
        }
        (legacy_dir / "memory" / "user_model.json").write_text(
            json.dumps(legacy_payload),
            encoding="utf-8",
        )

        result = srv._seed_buddy_user_scope("testuser", buddy_home=str(legacy_dir))

        self.assertTrue(result["ok"])
        self.assertEqual(result["scope_path"], "Users/testuser/USER")
        self.assertTrue(result["migrated_legacy"])

        note = ke.read_note("Users/testuser/USER")
        self.assertTrue(note["exists"])
        self.assertEqual(note["frontmatter"]["user"], "testuser")
        self.assertEqual(note["frontmatter"]["display_name"], "Testuser")
        self.assertEqual(note["frontmatter"]["persona"], "non-tech")
        self.assertIn("Guidance mode: uebernehmen", note["body"])
        self.assertIn("Preferred channels: bridge, whatsapp", note["body"])
        self.assertIn("Trust notes: Prefers direct language.", note["body"])

    def test_seed_buddy_user_scope_preserves_existing_canonical_note(self):
        ke = self._load_isolated_ke()
        ke.init_vault()
        ke.init_user_vault("testuser")
        ke.write_note(
            "Users/testuser/USER",
            "Canonical relationship state.",
            {"user": "testuser", "persona": "hybrid", "display_name": "Testuser"},
        )

        legacy_dir = Path(self._tmpdir.name) / "Buddy"
        (legacy_dir / "memory").mkdir(parents=True, exist_ok=True)
        (legacy_dir / "memory" / "user_model.json").write_text(
            json.dumps({"user_id": "testuser", "persona": "non-tech", "display_name": "Legacy"}),
            encoding="utf-8",
        )

        result = srv._seed_buddy_user_scope("testuser", buddy_home=str(legacy_dir))

        self.assertTrue(result["ok"])
        self.assertFalse(result["migrated_legacy"])
        note = ke.read_note("Users/testuser/USER")
        self.assertIn("Canonical relationship state.", note["body"])
        self.assertEqual(note["frontmatter"]["persona"], "hybrid")

    def test_buddy_docs_reference_canonical_user_scope(self):
        claude_raw = Path(BUDDY_CLAUDE_PATH).read_text(encoding="utf-8")
        prompt_raw = Path(BUDDY_PROMPT_PATH).read_text(encoding="utf-8")

        self.assertIn("Users/<user_id>/USER.md", claude_raw)
        self.assertIn("bridge_knowledge_init(user_id=", claude_raw)
        self.assertIn("bridge_knowledge_read", claude_raw)
        self.assertIn("Users/<user_id>/USER.md", prompt_raw)

    def test_buddy_has_engine_neutral_operator_guide_and_wrappers(self):
        buddy_home = Path(self._tmpdir.name) / "Buddy"
        result = srv._materialize_agent_setup_home(
            "buddy",
            {"id": "buddy", "name": "Buddy", "home_dir": str(buddy_home)},
            engine="claude",
            overwrite=True,
        )

        guide_raw = Path(result["guide_path"]).read_text(encoding="utf-8")
        claude_raw = Path(buddy_home / "CLAUDE.md").read_text(encoding="utf-8")
        agents_raw = Path(buddy_home / "AGENTS.md").read_text(encoding="utf-8")
        gemini_raw = Path(buddy_home / "GEMINI.md").read_text(encoding="utf-8")
        qwen_raw = Path(buddy_home / "QWEN.md").read_text(encoding="utf-8")

        self.assertIn("Bridge Operator Guide", guide_raw)
        self.assertIn("Knowledge Vault", guide_raw)
        self.assertIn("GET /cli/detect", guide_raw)

        for raw in (claude_raw, agents_raw, gemini_raw, qwen_raw):
            self.assertIn("BRIDGE_OPERATOR_GUIDE.md", raw)
            self.assertIn("SOUL.md", raw)


if __name__ == "__main__":
    unittest.main()
