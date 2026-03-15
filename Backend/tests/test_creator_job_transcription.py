"""Tests for chunked STT wired into the creator job pipeline."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest

try:
    import faster_whisper  # noqa: F401
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False


def _build_speech_video(path: str, text: str = "hello world testing") -> None:
    """Generate a short video with speech audio via flite + ffmpeg."""
    tmpdir = tempfile.mkdtemp(prefix="cj_speech_")
    try:
        wav_path = os.path.join(tmpdir, "speech.wav")
        try:
            subprocess.run(
                ["flite", "-t", text, "-o", wav_path],
                capture_output=True, timeout=30, check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            # Fallback: sine wave
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                 "-ar", "16000", "-ac", "1", wav_path],
                capture_output=True, timeout=30, check=True,
            )

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
                "-i", wav_path,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-b:a", "64k",
                "-shortest", path,
            ],
            capture_output=True, timeout=30, check=True,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@unittest.skipUnless(HAS_FASTER_WHISPER, "faster-whisper not installed")
class TestCreatorJobTranscription(unittest.TestCase):
    """Test the full ingest+transcription job pipeline."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_trans_test_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_trans_reg_")
        import creator_job

        self._orig_registry_path = creator_job._REGISTRY_PATH
        creator_job._REGISTRY_PATH = os.path.join(
            self.registry_dir, "creator_job_registry.json"
        )
        creator_job._reset_worker_state()

    def tearDown(self) -> None:
        import creator_job

        creator_job.stop_worker()
        creator_job._REGISTRY_PATH = self._orig_registry_path
        shutil.rmtree(self.workspace, ignore_errors=True)
        shutil.rmtree(self.registry_dir, ignore_errors=True)

    def test_ingest_with_transcription_completes(self) -> None:
        """Local ingest with transcribe=True runs full pipeline including STT."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()

        video_path = os.path.join(self.workspace, "speech.mp4")
        _build_speech_video(video_path)

        creator_job.start_worker(max_concurrent=1)
        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": video_path},
            workspace_dir=self.workspace,
            config={"language": "en", "model_size": "tiny", "transcribe": True},
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        # Wait — transcription can take ~10s with tiny model
        for _ in range(200):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed", f"Job failed: {loaded.get('error')}")

        # Verify transcription stages ran
        stage_names = [s["name"] for s in loaded["stages"]]
        self.assertIn("transcript_plan", stage_names)
        self.assertIn("transcript_chunks", stage_names)
        self.assertIn("transcript_merge", stage_names)

        # Verify transcript artifact exists
        self.assertIn("transcript_merge", loaded["artifacts"])
        merge_result = loaded["artifacts"]["transcript_merge"]
        self.assertIn("text", merge_result)
        self.assertIn("segments", merge_result)
        self.assertIsInstance(merge_result["segments"], list)

    def test_ingest_without_transcription_skips_stt(self) -> None:
        """Local ingest with transcribe=False does NOT run STT stages."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()

        video_path = os.path.join(self.workspace, "video.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
             "-c:a", "aac", "-b:a", "64k", "-shortest", video_path],
            capture_output=True, timeout=30, check=True,
        )

        creator_job.start_worker(max_concurrent=1)
        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": video_path},
            workspace_dir=self.workspace,
            config={"transcribe": False},
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        for _ in range(100):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed")
        # STT stages are present but skipped (artifacts contain skipped=True)
        for stage_name in ("transcript_plan", "transcript_chunks", "transcript_merge"):
            artifact = loaded["artifacts"].get(stage_name, {})
            self.assertTrue(
                artifact.get("skipped", False),
                f"Stage {stage_name} should be skipped when transcribe=False",
            )


if __name__ == "__main__":
    unittest.main()
