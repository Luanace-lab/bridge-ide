from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import server_agent_files as files_mod  # noqa: E402


class TestServerAgentFilesContract(unittest.TestCase):
    def test_server_reexports_agent_file_helpers(self) -> None:
        self.assertIs(srv.agent_instruction_file, files_mod.agent_instruction_file)
        self.assertIs(srv._update_instruction_roles, files_mod._update_instruction_roles)
        self.assertIs(srv.agent_config_file, files_mod.agent_config_file)
        self.assertIs(srv.read_agent_permissions, files_mod.read_agent_permissions)
        self.assertIs(srv.write_agent_permission, files_mod.write_agent_permission)

    def test_instruction_file_mapping_uses_engine_specific_filenames(self) -> None:
        base = "/tmp/project"
        self.assertEqual(srv.agent_instruction_file(base, "claude"), "/tmp/project/CLAUDE.md")
        self.assertEqual(srv.agent_instruction_file(base, "codex"), "/tmp/project/AGENTS.md")
        self.assertEqual(srv.agent_instruction_file(base, "gemini"), "/tmp/project/GEMINI.md")
        self.assertEqual(srv.agent_instruction_file(base, "qwen"), "/tmp/project/QWEN.md")

    def test_update_instruction_roles_replaces_existing_role_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "AGENTS.md"
            path.write_text("# Codex\n\n## Rolle: Alt\n\nText\n", encoding="utf-8")
            srv._update_instruction_roles(str(path), [("Agent A", "Implementer"), ("Agent B", "Reviewer")])
            content = path.read_text(encoding="utf-8")
            self.assertIn("## Rollen", content)
            self.assertIn("- Agent A: Implementer", content)
            self.assertIn("- Agent B: Reviewer", content)
            self.assertNotIn("## Rolle: Alt", content)

    def test_claude_permission_roundtrip_uses_json_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            srv.write_agent_permission(tmpdir, "claude", "auto_approve", True)
            srv.write_agent_permission(tmpdir, "claude", "full_filesystem", True)
            srv.write_agent_permission(tmpdir, "claude", "file_write", True)

            perms = srv.read_agent_permissions(tmpdir, "claude")
            self.assertTrue(perms["auto_approve"])
            self.assertTrue(perms["full_filesystem"])
            self.assertTrue(perms["file_write"])

            raw = json.loads(Path(tmpdir, ".claude", "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["permissions"]["defaultMode"], "acceptEdits")
            self.assertIn("/", raw["permissions"]["additionalDirectories"])
            self.assertIn("Edit(**)", raw["permissions"]["allow"])

    def test_codex_permission_roundtrip_uses_toml_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            srv.write_agent_permission(tmpdir, "codex", "web_search", True)
            srv.write_agent_permission(tmpdir, "codex", "file_write", True)
            srv.write_agent_permission(tmpdir, "codex", "auto_approve", True)

            perms = srv.read_agent_permissions(tmpdir, "codex")
            self.assertTrue(perms["web_search"])
            self.assertTrue(perms["file_write"])
            self.assertTrue(perms["auto_approve"])

            raw = Path(tmpdir, ".codex", "config.toml").read_text(encoding="utf-8")
            self.assertIn('web_search = "live"', raw)
            self.assertIn('sandbox_mode = "workspace-write"', raw)
            self.assertIn('approval_policy = "never"', raw)


if __name__ == "__main__":
    unittest.main()
