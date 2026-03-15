from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import server_context_restore as restore_mod  # noqa: E402


class TestServerContextRestoreContract(unittest.TestCase):
    def test_server_reexports_context_restore_helpers(self) -> None:
        self.assertIs(srv._build_context_restore_message, restore_mod.build_context_restore_message)
        self.assertIs(srv._should_send_context_restore, restore_mod.should_send_context_restore)
        self.assertIs(srv._resolve_context_restore_artifacts, restore_mod.resolve_context_restore_artifacts)

    def test_should_send_context_restore_respects_nonce_and_cooldown(self) -> None:
        original_nonces = dict(srv.AGENT_NONCES)
        original_last_restore = dict(srv.AGENT_LAST_CONTEXT_RESTORE)
        try:
            srv.AGENT_NONCES.clear()
            srv.AGENT_LAST_CONTEXT_RESTORE.clear()

            self.assertTrue(srv._should_send_context_restore("codex_contract", "nonce-a", False))

            srv.AGENT_NONCES["codex_contract"] = "nonce-a"
            self.assertFalse(srv._should_send_context_restore("codex_contract", "nonce-a", False))
            self.assertTrue(srv._should_send_context_restore("codex_contract", "nonce-b", False))

            srv.AGENT_LAST_CONTEXT_RESTORE["codex_contract"] = time.time()
            self.assertFalse(srv._should_send_context_restore("codex_contract", "nonce-a", True))

            srv.AGENT_LAST_CONTEXT_RESTORE["codex_contract"] = time.time() - (srv.CONTEXT_RESTORE_COOLDOWN + 5)
            self.assertTrue(srv._should_send_context_restore("codex_contract", "nonce-a", True))
        finally:
            srv.AGENT_NONCES.clear()
            srv.AGENT_NONCES.update(original_nonces)
            srv.AGENT_LAST_CONTEXT_RESTORE.clear()
            srv.AGENT_LAST_CONTEXT_RESTORE.update(original_last_restore)

    def test_resolve_context_restore_artifacts_prefers_runtime_workspace_paths(self) -> None:
        original_team = srv.TEAM_CONFIG
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                project = Path(tmpdir) / "project"
                workspace = project / ".agent_sessions" / "codex_contract"
                workspace.mkdir(parents=True, exist_ok=True)
                (workspace / "AGENTS.md").write_text("# Codex\n", encoding="utf-8")
                (workspace / "CONTEXT_BRIDGE.md").write_text("CTX", encoding="utf-8")
                (workspace / "SOUL.md").write_text("SOUL", encoding="utf-8")
                (workspace / "MEMORY.md").write_text("MEM", encoding="utf-8")
                srv.TEAM_CONFIG = {"agents": []}

                artifacts = srv._resolve_context_restore_artifacts(
                    "codex_contract",
                    {
                        "workspace": str(workspace),
                        "project_root": str(project),
                        "instruction_path": str(workspace / "AGENTS.md"),
                    },
                )

            self.assertEqual(artifacts["instruction_path"], str(workspace / "AGENTS.md"))
            self.assertEqual(artifacts["context_bridge_path"], str(workspace / "CONTEXT_BRIDGE.md"))
            self.assertEqual(artifacts["soul_path"], str(workspace / "SOUL.md"))
            self.assertEqual(artifacts["memory_path"], str(workspace / "MEMORY.md"))
            self.assertEqual(artifacts["instruction_filename"], "AGENTS.md")
        finally:
            srv.TEAM_CONFIG = original_team


if __name__ == "__main__":
    unittest.main()
