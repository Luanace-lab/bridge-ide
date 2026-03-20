from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(BACKEND_DIR)
KNOWLEDGE_PATH = os.path.join(BACKEND_DIR, "knowledge_engine.py")
CHAT_PATH = os.path.join(REPO_ROOT, "Frontend", "chat.html")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestBuddyUiFrontdoorContract(unittest.TestCase):
    def setUp(self):
        self._orig_ke = sys.modules.get("knowledge_engine")
        self._orig_sm = sys.modules.get("semantic_memory")
        # Snapshot: preserve the real semantic_memory module before any test can replace it
        if self._orig_sm is None:
            import semantic_memory
            self._orig_sm = semantic_memory
        self._orig_is_alive = srv.is_session_alive
        self._orig_has_recent_ping = srv._has_recent_buddy_frontdoor_ping
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def tearDown(self):
        srv.is_session_alive = self._orig_is_alive
        srv._has_recent_buddy_frontdoor_ping = self._orig_has_recent_ping
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

    def test_frontdoor_status_autostarts_unknown_user_without_pending_ping(self):
        self._load_isolated_ke()
        srv.is_session_alive = lambda _agent_id: False
        srv._has_recent_buddy_frontdoor_ping = lambda _user_id, within_seconds=30.0: False

        status = srv._get_buddy_frontdoor_status("testuser")

        self.assertEqual(status["user_id"], "testuser")
        self.assertFalse(status["known_user"])
        self.assertFalse(status["buddy_running"])
        self.assertFalse(status["pending_frontdoor"])
        self.assertTrue(status["should_auto_start"])

    def test_frontdoor_status_suppresses_auto_start_for_known_user(self):
        ke = self._load_isolated_ke()
        ke.init_vault()
        ke.init_user_vault("testuser")
        ke.write_note("Users/testuser/USER", "Existing user.", {"user": "testuser", "display_name": "Testuser"})

        srv.is_session_alive = lambda _agent_id: True
        srv._has_recent_buddy_frontdoor_ping = lambda _user_id, within_seconds=30.0: False

        status = srv._get_buddy_frontdoor_status("testuser")

        self.assertTrue(status["known_user"])
        self.assertTrue(status["buddy_running"])
        self.assertFalse(status["should_auto_start"])

    def test_chat_uses_onboarding_status_and_generic_action_handler(self):
        raw = Path(CHAT_PATH).read_text(encoding="utf-8")

        self.assertIn("/onboarding/status", raw)
        self.assertIn("handleMessageAction(action, msg)", raw)
        self.assertNotIn("localStorage.getItem('bridge_onboarded')", raw)
        self.assertNotIn("handleOnboardingAction(action.value, msg)", raw)

    def test_buddy_landing_uses_cli_detect_and_setup_home_before_runtime_start(self):
        raw = Path(os.path.join(REPO_ROOT, "Frontend", "buddy_landing.html")).read_text(encoding="utf-8")

        self.assertIn("/cli/detect", raw)
        self.assertIn("/agents/${BUDDY_ID}", raw)
        self.assertIn("/agents/${BUDDY_ID}/setup-home", raw)
        self.assertIn("configureBuddyHome(", raw)
        self.assertIn("fetchBuddyState(", raw)
        self.assertIn("resolveExistingBuddyEngine(", raw)
        self.assertIn("bootstrapBuddySetup()", raw)


if __name__ == "__main__":
    unittest.main()
