"""Tests for creator_fish_audio — TTS, voice cloning, voiceover jobs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock


def _make_wav(path: str, duration: float = 3.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-ar", "16000", "-ac", "1", path],
        capture_output=True, timeout=15, check=True,
    )


def _make_video(path: str, duration: float = 3.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=10",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "32k", "-shortest", path],
        capture_output=True, timeout=15, check=True,
    )


class TestCreatorFishAudio(unittest.TestCase):

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="cj_fish_")
        self.creds_dir = os.path.join(self.tmpdir, "creds")
        os.makedirs(self.creds_dir)
        import creator_fish_audio
        self._orig_creds = creator_fish_audio.CREDENTIALS_DIR
        creator_fish_audio.CREDENTIALS_DIR = self.creds_dir

    def tearDown(self) -> None:
        import creator_fish_audio
        creator_fish_audio.CREDENTIALS_DIR = self._orig_creds
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _store_creds(self, data: dict) -> None:
        with open(os.path.join(self.creds_dir, "fish_audio.json"), "w") as f:
            json.dump(data, f)

    def test_no_api_key_returns_error(self) -> None:
        from creator_fish_audio import generate_voiceover
        result = generate_voiceover("Hello", "voice_123", os.path.join(self.tmpdir, "out.wav"))
        self.assertEqual(result["status"], "error")
        self.assertIn("No credentials", result["error"])

    def test_generate_voiceover_mock(self) -> None:
        from creator_fish_audio import generate_voiceover
        self._store_creds({"api_key": "test_key"})

        output = os.path.join(self.tmpdir, "voiceover.wav")
        mock_audio = b"\x00" * 4096

        with patch("creator_fish_audio._call_fish_tts") as mock_tts:
            mock_tts.return_value = mock_audio
            result = generate_voiceover("Hello world", "voice_123", output)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(os.path.isfile(output))
        self.assertEqual(os.path.getsize(output), 4096)

    def test_clone_voice_mock(self) -> None:
        from creator_fish_audio import clone_voice
        self._store_creds({"api_key": "test_key"})

        wav = os.path.join(self.tmpdir, "sample.wav")
        _make_wav(wav)

        with patch("creator_fish_audio._call_fish_clone") as mock_clone:
            mock_clone.return_value = {"voice_id": "cloned_abc123", "name": "MyVoice"}
            result = clone_voice(wav, "MyVoice")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["voice_id"], "cloned_abc123")

    def test_list_voices_mock(self) -> None:
        from creator_fish_audio import list_voices
        self._store_creds({"api_key": "test_key"})

        with patch("creator_fish_audio._call_fish_list_voices") as mock_list:
            mock_list.return_value = [
                {"id": "v1", "name": "Voice 1"},
                {"id": "v2", "name": "Voice 2"},
            ]
            result = list_voices()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "v1")

    def test_merge_audio_into_video(self) -> None:
        from creator_fish_audio import merge_audio_into_video

        video = os.path.join(self.tmpdir, "input.mp4")
        audio = os.path.join(self.tmpdir, "voiceover.wav")
        output = os.path.join(self.tmpdir, "output.mp4")
        _make_video(video)
        _make_wav(audio)

        result = merge_audio_into_video(video, audio, output)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(os.path.isfile(output))
        self.assertGreater(os.path.getsize(output), 0)

    def test_voiceover_job_completes(self) -> None:
        """Full voiceover job via job pipeline."""
        import creator_job
        from creator_job_stages import register_voiceover_stages

        ws = tempfile.mkdtemp(prefix="cj_fish_ws_")
        reg_dir = tempfile.mkdtemp(prefix="cj_fish_reg_")
        orig = creator_job._REGISTRY_PATH
        creator_job._REGISTRY_PATH = os.path.join(reg_dir, "reg.json")
        creator_job._reset_worker_state()

        self._store_creds({"api_key": "test_key"})

        try:
            register_voiceover_stages()
            creator_job.start_worker(max_concurrent=1)

            video = os.path.join(self.tmpdir, "source.mp4")
            _make_video(video)

            job = creator_job.create_job(
                job_type="voiceover",
                source={"video_path": video},
                workspace_dir=ws,
                config={
                    "text": "Welcome to my channel",
                    "voice_id": "test_voice",
                },
            )
            creator_job.save_job(job)

            # Generate real WAV for merge test (mock TTS returns file path instead of bytes)
            mock_wav_path = os.path.join(ws, "mock_voiceover.wav")
            _make_wav(mock_wav_path, duration=2.0)
            with open(mock_wav_path, "rb") as f:
                mock_audio = f.read()
            with patch("creator_fish_audio._call_fish_tts", return_value=mock_audio):
                creator_job.submit_job(job["job_id"], ws)
                for _ in range(50):
                    loaded = creator_job.load_job(job["job_id"], ws)
                    if loaded and loaded["status"] in ("completed", "failed"):
                        break
                    time.sleep(0.1)

            loaded = creator_job.load_job(job["job_id"], ws)
            self.assertEqual(loaded["status"], "completed", f"Failed: {loaded.get('error')}")
        finally:
            creator_job.stop_worker()
            creator_job._REGISTRY_PATH = orig
            shutil.rmtree(ws, ignore_errors=True)
            shutil.rmtree(reg_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
