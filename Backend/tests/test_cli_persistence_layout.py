from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from persistence_utils import (  # noqa: E402
    context_bridge_candidates,
    detect_instruction_filename,
    first_existing_path,
    memory_cwd_candidates,
    resolve_agent_cli_layout,
)
import tmux_manager  # noqa: E402


class TestCliPersistenceLayout(unittest.TestCase):
    def test_resolve_layout_from_project_home(self) -> None:
        layout = resolve_agent_cli_layout("/tmp/project", "codex")
        self.assertEqual(layout["home_dir"], "/tmp/project")
        self.assertEqual(layout["workspace"], "/tmp/project/.agent_sessions/codex")
        self.assertEqual(layout["project_root"], "/tmp/project")

    def test_resolve_layout_from_workspace_home(self) -> None:
        layout = resolve_agent_cli_layout("/tmp/project/.agent_sessions/codex", "codex")
        self.assertEqual(layout["home_dir"], "/tmp/project/.agent_sessions/codex")
        self.assertEqual(layout["workspace"], "/tmp/project/.agent_sessions/codex")
        self.assertEqual(layout["project_root"], "/tmp/project")

    def test_detect_instruction_filename_prefers_workspace_cli_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir) / "project"
            workspace = project / ".agent_sessions" / "codex"
            workspace.mkdir(parents=True, exist_ok=True)
            (project / "CLAUDE.md").write_text("root", encoding="utf-8")
            (workspace / "AGENTS.md").write_text("workspace", encoding="utf-8")

            detected = detect_instruction_filename(str(project), "codex", "claude")
            self.assertEqual(detected, "AGENTS.md")

    def test_context_bridge_candidates_are_workspace_first(self) -> None:
        candidates = context_bridge_candidates("/tmp/project", "codex")
        self.assertEqual(
            candidates,
            [
                "/tmp/project/.agent_sessions/codex/CONTEXT_BRIDGE.md",
            ],
        )

    def test_memory_candidates_use_canonical_workspace_even_if_missing(self) -> None:
        candidates = memory_cwd_candidates("/tmp/project", "codex")
        self.assertEqual(
            candidates,
            [
                "/tmp/project/.agent_sessions/codex",
            ],
        )


class TestResumeFallback(unittest.TestCase):
    def test_extract_resume_id_reads_workspace_instruction_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir) / "project"
            workspace = project / ".agent_sessions" / "claude"
            workspace.mkdir(parents=True, exist_ok=True)
            session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            (workspace / "CLAUDE.md").write_text(
                f"**Session:** `{session_id}`\n",
                encoding="utf-8",
            )

            with mock.patch.object(tmux_manager, "_load_cached_session_id", return_value=""):
                detected = tmux_manager._extract_resume_id(str(project), "claude", engine="claude")
            self.assertEqual(detected, session_id)

    def test_extract_resume_id_ignores_stale_claude_cache_without_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            project = home / "project"
            workspace = project / ".agent_sessions" / "claude"
            workspace.mkdir(parents=True, exist_ok=True)
            session_ids = Path(tmpdir) / "session_ids.json"
            stale_sid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            scope_key = tmux_manager._session_cache_scope_key("claude", workspace, engine="claude")
            session_ids.write_text(
                json.dumps({"__scoped__": {scope_key: {"session_id": stale_sid}}}),
                encoding="utf-8",
            )

            with (
                mock.patch.object(tmux_manager, "_session_ids_file", return_value=session_ids),
                mock.patch.object(tmux_manager.Path, "home", return_value=home),
            ):
                detected = tmux_manager._extract_resume_id(str(project), "claude", engine="claude")

            self.assertEqual(detected, "")

    def test_extract_resume_id_accepts_claude_cache_with_matching_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            project = home / "project"
            workspace = project / ".agent_sessions" / "claude"
            workspace.mkdir(parents=True, exist_ok=True)
            session_ids = Path(tmpdir) / "session_ids.json"
            session_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            scope_key = tmux_manager._session_cache_scope_key("claude", workspace, engine="claude")
            session_ids.write_text(
                json.dumps({"__scoped__": {scope_key: {"session_id": session_id}}}),
                encoding="utf-8",
            )
            mangled = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in str(workspace))
            project_dir = home / ".claude-test" / "projects" / mangled
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / f"{session_id}.jsonl").write_text("{}", encoding="utf-8")

            with (
                mock.patch.object(tmux_manager, "_session_ids_file", return_value=session_ids),
                mock.patch.object(tmux_manager.Path, "home", return_value=home),
            ):
                detected = tmux_manager._extract_resume_id(str(project), "claude", engine="claude")

            self.assertEqual(detected, session_id)

    def test_validate_local_claude_resume_id_requires_current_config_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace = root / "project" / ".agent_sessions" / "claude"
            workspace.mkdir(parents=True, exist_ok=True)
            session_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
            mangled = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in str(workspace))
            config_dir = root / ".claude-agent-claude"
            project_dir = config_dir / "projects" / mangled
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / f"{session_id}.jsonl").write_text("{}", encoding="utf-8")

            self.assertTrue(
                tmux_manager._validate_local_claude_resume_id(session_id, workspace, config_dir)
            )

    def test_first_existing_path_prefers_workspace_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "project" / ".agent_sessions" / "codex"
            root = workspace.parent.parent
            workspace.mkdir(parents=True, exist_ok=True)
            root.mkdir(parents=True, exist_ok=True)
            workspace_file = workspace / "CONTEXT_BRIDGE.md"
            root_file = root / "CONTEXT_BRIDGE.md"
            root_file.write_text("root", encoding="utf-8")
            workspace_file.write_text("workspace", encoding="utf-8")

            detected = first_existing_path([str(workspace_file), str(root_file)])
            self.assertEqual(detected, str(workspace_file))


if __name__ == "__main__":
    unittest.main()
