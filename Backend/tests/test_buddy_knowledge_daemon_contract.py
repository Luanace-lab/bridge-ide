from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.buddy_knowledge as bk


class TestBuddyKnowledgeDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.backend_dir = self.root / "Backend"
        self.knowledge_root = self.root / "Knowledge"
        self.home_root = self.root / "home"
        self.buddy_home = self.root / "Buddy"
        self.agent_state_dir = self.root / "agent_state"
        self.log_file = self.root / "messages.jsonl"
        self.backend_dir.mkdir()
        self.knowledge_root.mkdir()
        self.home_root.mkdir()
        self.buddy_home.mkdir()
        self.agent_state_dir.mkdir()
        self.log_file.write_text("", encoding="utf-8")
        (self.backend_dir / "team.json").write_text("{}", encoding="utf-8")
        self.shutdown_active = False
        self.team_config = {
            "agents": [
                {
                    "id": "buddy",
                    "home_dir": str(self.buddy_home),
                    "description": "Concierge",
                    "engine": "codex",
                    "level": 3,
                    "reports_to": "user",
                    "active": True,
                }
            ]
        }
        bk.init(
            system_shutdown_active=lambda: self.shutdown_active,
            team_config_getter=lambda: self.team_config,
            backend_dir=str(self.backend_dir),
            agent_state_dir=str(self.agent_state_dir),
            log_file=str(self.log_file),
            port=9111,
            ws_port=9112,
            bridge_strict_auth=True,
        )

    def _expanduser(self, value: str) -> str:
        if value == "~":
            return str(self.home_root)
        return value

    def test_tick_skips_generation_when_system_shutdown_is_active(self) -> None:
        self.shutdown_active = True
        with patch("daemons.buddy_knowledge._generate_buddy_knowledge") as generate_mock:
            ran = bk._buddy_knowledge_tick()

        self.assertFalse(ran)
        generate_mock.assert_not_called()

    def test_generate_creates_reference_files_for_buddy(self) -> None:
        memory_dir = self.home_root / ".claude-agent-alpha"
        memory_dir.mkdir()
        daily_dir = self.knowledge_root / "Agents" / "alpha" / "DAILY"
        daily_dir.mkdir(parents=True)
        (daily_dir / "2026-03-14.md").write_text("log", encoding="utf-8")

        with patch("daemons.buddy_knowledge.os.path.expanduser", side_effect=self._expanduser):
            bk._generate_buddy_knowledge()

        idx_path = self.buddy_home / "knowledge" / "KNOWLEDGE_INDEX.md"
        sysmap_path = self.buddy_home / "knowledge" / "SYSTEM_MAP.md"
        sot_path = self.buddy_home / "knowledge" / "BUDDY_SYSTEM_SOT.md"
        self.assertTrue(idx_path.exists())
        self.assertTrue(sysmap_path.exists())
        self.assertTrue(sot_path.exists())
        idx_raw = idx_path.read_text(encoding="utf-8")
        sys_raw = sysmap_path.read_text(encoding="utf-8")
        sot_raw = sot_path.read_text(encoding="utf-8")
        self.assertIn("# Knowledge Index", idx_raw)
        self.assertIn("Knowledge Vault", idx_raw)
        self.assertIn("alpha", idx_raw)
        self.assertIn(str(self.agent_state_dir), idx_raw)
        self.assertIn("# System Map", sys_raw)
        self.assertIn("127.0.0.1:9111", sys_raw)
        self.assertIn("buddy: Concierge", sys_raw)
        self.assertIn("# Buddy System SoT", sot_raw)
        self.assertIn("PERSISTENZ_SYSTEM.md", sot_raw)
        self.assertIn(str(self.buddy_home), sot_raw)

    def test_generate_removes_deprecated_live_status_file(self) -> None:
        knowledge_dir = self.buddy_home / "knowledge"
        knowledge_dir.mkdir()
        live_path = knowledge_dir / "LIVE_STATUS.md"
        live_path.write_text("deprecated", encoding="utf-8")

        with patch("daemons.buddy_knowledge.os.path.expanduser", side_effect=self._expanduser):
            bk._generate_buddy_knowledge()

        self.assertFalse(live_path.exists())

    def test_is_up_to_date_requires_file_newer_than_reference(self) -> None:
        target = self.root / "probe.md"
        target.write_text("ok", encoding="utf-8")
        current_mtime = target.stat().st_mtime

        self.assertTrue(bk._is_up_to_date(str(target), current_mtime - 1))
        self.assertFalse(bk._is_up_to_date(str(target), current_mtime + 1))
