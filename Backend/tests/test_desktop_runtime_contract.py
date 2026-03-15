from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import execution_journal as journal  # noqa: E402


class TestDesktopRuntimeContracts(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        self.mod = bridge_mcp
        self.tmpdir = tempfile.mkdtemp(prefix="bridge_desktop_contract_")
        self._orig_runs_base_dir = journal.RUNS_BASE_DIR
        journal.RUNS_BASE_DIR = self.tmpdir
        self._orig_agent_id = self.mod._agent_id
        self.mod._agent_id = "codex"

    def tearDown(self) -> None:
        journal.RUNS_BASE_DIR = self._orig_runs_base_dir
        self.mod._agent_id = self._orig_agent_id
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_desktop_observe_returns_structured_snapshot(self) -> None:
        focused = {"available": True, "window_id": "123", "name": "Browser", "x": 10, "y": 20, "width": 800, "height": 600}
        screenshot = {"ok": True, "status": "ok", "path": "/tmp/desktop.png", "size_bytes": 123}
        windows = {"ok": True, "count": 1, "windows": [focused]}
        clipboard = {"ok": True, "content": "creator notes", "length": 13}
        ocr = {"available": True, "ok": True, "text": "OCR text", "length": 8, "engine": "tesseract"}

        with patch.object(self.mod, "_desktop_get_focused_window_state", AsyncMock(return_value=focused)), \
             patch.object(self.mod, "bridge_desktop_screenshot", AsyncMock(return_value=json.dumps(screenshot))), \
             patch.object(self.mod, "bridge_desktop_window_list", AsyncMock(return_value=json.dumps(windows))), \
             patch.object(self.mod, "bridge_desktop_clipboard_read", AsyncMock(return_value=json.dumps(clipboard))), \
             patch.object(self.mod, "_desktop_ocr_available", return_value=True), \
             patch.object(self.mod, "_desktop_ocr_image", AsyncMock(return_value=ocr)):
            raw = asyncio.run(
                self.mod.bridge_desktop_observe(
                    include_screenshot=True,
                    include_windows=True,
                    include_clipboard=True,
                    ocr=True,
                )
            )

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["focused_window"]["name"], "Browser")
        self.assertEqual(data["screenshot"]["path"], "/tmp/desktop.png")
        self.assertEqual(data["windows"]["count"], 1)
        self.assertEqual(data["clipboard"]["content"], "creator notes")
        self.assertEqual(data["ocr"]["text"], "OCR text")

    def test_desktop_observe_reports_ocr_unavailable_without_error(self) -> None:
        focused = {"available": False, "error": "no focused window"}

        with patch.object(self.mod, "_desktop_get_focused_window_state", AsyncMock(return_value=focused)), \
             patch.object(self.mod, "_desktop_ocr_available", return_value=False):
            raw = asyncio.run(
                self.mod.bridge_desktop_observe(
                    include_screenshot=False,
                    include_windows=False,
                    include_clipboard=False,
                    ocr=False,
                )
            )

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertFalse(data["ocr"]["available"])
        self.assertFalse(data["focused_window"]["available"])

    def test_desktop_verify_returns_structured_match_state(self) -> None:
        screenshot_path = os.path.join(self.tmpdir, "desktop.png")
        with open(screenshot_path, "wb") as handle:
            handle.write(b"png")

        observe = {
            "ok": True,
            "status": "ok",
            "run_id": "desktop-run-1",
            "focused_window": {
                "available": True,
                "window_id": "123",
                "name": "Creator Studio",
                "x": 10,
                "y": 20,
                "width": 1440,
                "height": 900,
            },
            "screenshot": {"ok": True, "status": "ok", "path": screenshot_path, "size_bytes": 3},
            "windows": {
                "ok": True,
                "count": 2,
                "windows": [
                    {"window_id": "123", "name": "Creator Studio"},
                    {"window_id": "456", "name": "Notes"},
                ],
            },
            "clipboard": {"ok": True, "content": "creator workflow notes", "length": 22},
            "ocr": {"available": True, "ok": True, "text": "Headline Hook", "length": 13, "engine": "tesseract"},
        }

        with patch.object(self.mod, "bridge_desktop_observe", AsyncMock(return_value=json.dumps(observe))):
            raw = asyncio.run(
                self.mod.bridge_desktop_verify(
                    expect_focused_window="present",
                    expect_focused_name_contains="studio",
                    expect_window_name_contains="notes",
                    expect_clipboard_contains="workflow",
                    expect_ocr_contains="headline",
                    require_screenshot=True,
                )
            )

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertTrue(data["verified"])
        self.assertTrue(data["matches"]["focused_window"])
        self.assertTrue(data["matches"]["screenshot_created"])
        self.assertEqual(data["focused_window"]["name"], "Creator Studio")

    def test_desktop_verify_returns_mismatch_for_failed_conditions(self) -> None:
        observe = {
            "ok": True,
            "status": "ok",
            "run_id": "desktop-run-2",
            "focused_window": {"available": False, "error": "no focused window"},
            "screenshot": None,
            "windows": {"ok": True, "count": 0, "windows": []},
            "clipboard": {"ok": True, "content": "draft", "length": 5},
            "ocr": {"available": False, "text": "", "engine": None},
        }

        with patch.object(self.mod, "bridge_desktop_observe", AsyncMock(return_value=json.dumps(observe))):
            raw = asyncio.run(
                self.mod.bridge_desktop_verify(
                    expect_focused_window="present",
                    expect_clipboard_contains="publish",
                )
            )

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertFalse(data["verified"])
        self.assertEqual(data["status"], "mismatch")
        self.assertFalse(data["matches"]["focused_window"])
        self.assertFalse(data["matches"]["clipboard_contains"])

    def test_desktop_verify_requires_at_least_one_condition(self) -> None:
        raw = asyncio.run(self.mod.bridge_desktop_verify())
        data = json.loads(raw)
        self.assertFalse(data["ok"])
        self.assertEqual(data["status"], "error")
        self.assertIn("at least one verify condition", data["error"])


if __name__ == "__main__":
    unittest.main()
