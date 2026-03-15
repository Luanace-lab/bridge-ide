from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.auto_gen as ag


class TestAutoGenDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.messages: list[dict[str, object]] = []

        with ag.AUTO_GEN_LOCK:
            ag.AUTO_GEN_PENDING.clear()

        ag.init(
            msg_lock=threading.Lock(),
            messages=self.messages,
            team_lead_id="teamlead",
            ensure_parent_dir=lambda path: Path(path).parent.mkdir(parents=True, exist_ok=True),
        )

    def test_tick_expires_pending_requests_older_than_ttl(self) -> None:
        with ag.AUTO_GEN_LOCK:
            ag.AUTO_GEN_PENDING["probe"] = {"msg_id": 1, "file_path": str(self.root / "out.md"), "ts": 10.0}

        written = ag._auto_gen_tick(now=131.0)

        self.assertEqual(written, [])
        with ag.AUTO_GEN_LOCK:
            self.assertEqual(dict(ag.AUTO_GEN_PENDING), {})

    def test_tick_writes_file_for_valid_teamlead_reply(self) -> None:
        target = self.root / "generated" / "AGENTS.md"
        with ag.AUTO_GEN_LOCK:
            ag.AUTO_GEN_PENDING["probe"] = {"msg_id": 5, "file_path": str(target), "ts": 100.0}
        self.messages[:] = [
            {"id": 5, "from": "user", "to": "teamlead", "content": "trigger"},
            {"id": 6, "from": "teamlead", "to": "user", "content": "A" * 60},
        ]

        written = ag._auto_gen_tick(now=101.0)

        self.assertEqual(written, [str(target)])
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "A" * 60)
        with ag.AUTO_GEN_LOCK:
            self.assertEqual(dict(ag.AUTO_GEN_PENDING), {})

    def test_tick_ignores_short_or_wrong_target_replies(self) -> None:
        target = self.root / "generated" / "CLAUDE.md"
        with ag.AUTO_GEN_LOCK:
            ag.AUTO_GEN_PENDING["probe"] = {"msg_id": 7, "file_path": str(target), "ts": 100.0}
        self.messages[:] = [
            {"id": 8, "from": "teamlead", "to": "codex", "content": "B" * 80},
            {"id": 9, "from": "teamlead", "to": "user", "content": "too short"},
        ]

        written = ag._auto_gen_tick(now=101.0)

        self.assertEqual(written, [])
        self.assertFalse(target.exists())
        with ag.AUTO_GEN_LOCK:
            self.assertIn("probe", ag.AUTO_GEN_PENDING)
