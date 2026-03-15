from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.media_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, body: dict | None = None) -> None:
        self.headers: dict[str, str] = {}
        self._body = body
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self._body


class TestMediaRoutesContract(unittest.TestCase):
    def test_server_uses_extracted_media_post_handler(self) -> None:
        self.assertIs(srv._handle_media_post, routes_mod.handle_post)

    def test_media_info_route_uses_ffprobe_payload(self) -> None:
        handler = _DummyHandler({"path": "/tmp/sample.mp4"})
        completed = routes_mod.subprocess.CompletedProcess(
            args=["ffprobe"],
            returncode=0,
            stdout='{"format": {"duration": "1.0"}, "streams": []}',
            stderr="",
        )
        with patch.object(routes_mod.os.path, "isfile", return_value=True), patch.object(
            routes_mod.subprocess, "run", return_value=completed
        ):
            self.assertTrue(routes_mod.handle_post(handler, "/media/info"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertIn("format", handler.responses[0][1]["info"])

    def test_media_convert_route_reports_output(self) -> None:
        handler = _DummyHandler({"input": "/tmp/in.mp4", "output": "/tmp/out.mp4"})
        completed = routes_mod.subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stdout="", stderr="")
        with patch.object(routes_mod.os.path, "isfile", side_effect=lambda path: path in {"/tmp/in.mp4", "/tmp/out.mp4"}), patch.object(
            routes_mod.os.path, "isdir", return_value=True
        ), patch.object(routes_mod.os.path, "getsize", return_value=1234), patch.object(
            routes_mod.subprocess, "run", return_value=completed
        ):
            self.assertTrue(routes_mod.handle_post(handler, "/media/convert"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["size_bytes"], 1234)

    def test_media_extract_frames_rejects_invalid_fps(self) -> None:
        handler = _DummyHandler({"input": "/tmp/in.mp4", "output": "/tmp/frame_%04d.png", "type": "frames", "fps": "abc"})
        with patch.object(routes_mod.os.path, "isfile", return_value=True), patch.object(
            routes_mod.os.path, "isdir", return_value=True
        ):
            self.assertTrue(routes_mod.handle_post(handler, "/media/extract"))
        self.assertEqual(handler.responses[0][0], 400)


if __name__ == "__main__":
    unittest.main()
