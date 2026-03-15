from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestCreatorHttpE2EIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="creator_http_e2e_")
        self.audio_path = os.path.join(self.tmpdir, "speech.wav")
        self.video_path = os.path.join(self.tmpdir, "speech.mp4")
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, cmd: list[str]) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:500])

    def _frame_has_visible_bottom_pixels(self, video_path: str, *, timestamp_s: float) -> bool:
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{timestamp_s:.3f}",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-vf",
            "crop=iw:ih/3:0:2*ih/3,format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[:500])
        return any(byte > 0 for byte in result.stdout)

    def _start_server(self) -> str:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_creator_http_e2e_with_real_transcription(self) -> None:
        text = "This is a bridge creator test. We create subtitles and short clips from one video."
        self._run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"flite=text={text}:voice=slt",
                "-t",
                "8",
                self.audio_path,
            ]
        )
        self._run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=640x360:d=8",
                "-i",
                self.audio_path,
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                self.video_path,
            ]
        )

        base_url = self._start_server()
        status_ingest, body_ingest = self._post(
            base_url,
            "/creator/local-ingest",
            {
                "input_path": self.video_path,
                "workspace_dir": self.tmpdir,
                "language": "en",
                "model": "base",
                "transcribe": True,
            },
        )
        self.assertEqual(status_ingest, 200)
        transcript = body_ingest["result"]["transcript"]["text"].lower()
        segments = body_ingest["result"]["transcript"]["segments"]
        highlights = body_ingest["result"]["highlights"]
        self.assertIn("bridge creator test", transcript)
        self.assertGreaterEqual(len(segments), 1)
        self.assertGreaterEqual(len(highlights), 1)

        srt_path = os.path.join(self.tmpdir, "speech.srt")
        status_srt, body_srt = self._post(
            base_url,
            "/creator/write-srt",
            {"output_path": srt_path, "segments": segments},
        )
        self.assertEqual(status_srt, 200)
        self.assertTrue(os.path.isfile(body_srt["result"]["output_path"]))

        clip_path = os.path.join(self.tmpdir, "speech_clip.mp4")
        status_clip, body_clip = self._post(
            base_url,
            "/creator/export-clip",
            {
                "input_path": self.video_path,
                "output_path": clip_path,
                "start_s": highlights[0]["start"],
                "end_s": highlights[0]["end"],
            },
        )
        self.assertEqual(status_clip, 200)
        self.assertTrue(os.path.isfile(body_clip["result"]["output_path"]))
        self.assertGreater(body_clip["result"]["size_bytes"], 0)

        social_path = os.path.join(self.tmpdir, "speech_short.mp4")
        social_end = min(float(segments[0]["end"]), float(segments[0]["start"]) + 2.0)
        status_social, body_social = self._post(
            base_url,
            "/creator/export-social-clip",
            {
                "input_path": self.video_path,
                "output_path": social_path,
                "start_s": segments[0]["start"],
                "end_s": social_end,
                "preset_name": "youtube_short",
                "segments": segments,
                "burn_subtitles": True,
            },
        )
        self.assertEqual(status_social, 200)
        self.assertTrue(os.path.isfile(body_social["result"]["output_path"]))
        self.assertEqual(body_social["result"]["width"], 1080)
        self.assertEqual(body_social["result"]["height"], 1920)
        self.assertTrue(body_social["result"]["burned_subtitles"])
        self.assertTrue(
            self._frame_has_visible_bottom_pixels(body_social["result"]["output_path"], timestamp_s=0.8)
        )

        status_package, body_package = self._post(
            base_url,
            "/creator/package-social",
            {
                "input_path": self.video_path,
                "output_dir": self.tmpdir,
                "package_name": "speech_creator_bundle",
                "start_s": segments[0]["start"],
                "end_s": social_end,
                "preset_names": ["youtube_short", "square_post"],
                "segments": segments,
                "burn_subtitles": True,
                "write_sidecar_srt": True,
            },
        )
        self.assertEqual(status_package, 200)
        self.assertTrue(os.path.isfile(body_package["result"]["manifest_path"]))
        self.assertEqual(len(body_package["result"]["assets"]), 2)
        self.assertTrue(os.path.isfile(body_package["result"]["sidecar_srt"]["output_path"]))
        self.assertTrue(
            self._frame_has_visible_bottom_pixels(body_package["result"]["assets"][0]["output_path"], timestamp_s=0.8)
        )


if __name__ == "__main__":
    unittest.main()
