from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from creator_media import ingest_local_media, write_srt  # noqa: E402


class TestCreatorSttIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="creator_stt_integration_")
        self.audio_path = os.path.join(self.tmpdir, "speech.wav")
        self.video_path = os.path.join(self.tmpdir, "speech.mp4")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, cmd: list[str]) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:500])

    def test_local_creator_ingest_transcribes_real_speech(self) -> None:
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

        result = ingest_local_media(self.video_path, self.tmpdir, language="en", model="base", transcribe=True)
        transcript = result["transcript"]["text"].lower()
        segments = result["transcript"]["segments"]
        srt_path = os.path.join(self.tmpdir, "speech.srt")
        srt = write_srt(segments, srt_path)

        self.assertIn("bridge creator test", transcript)
        self.assertIn("subtitles", transcript)
        self.assertGreaterEqual(len(segments), 1)
        self.assertGreaterEqual(len(result["chapters"]), 1)
        self.assertTrue(os.path.isfile(srt["output_path"]))


if __name__ == "__main__":
    unittest.main()
