"""E2E long-run tests for Creator Platform.

These tests use real media and may take minutes to complete.
Skipped by default. Run with: CREATOR_E2E=1 pytest tests/test_creator_e2e_longrun.py -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

CREATOR_E2E = os.environ.get("CREATOR_E2E", "")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

try:
    import faster_whisper  # noqa: F401
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False


@unittest.skipUnless(CREATOR_E2E, "Set CREATOR_E2E=1 to run long E2E tests")
@unittest.skipUnless(HAS_FASTER_WHISPER, "faster-whisper not installed")
class TestCreatorE2ELongRun(unittest.TestCase):
    """End-to-end tests with real media of various durations."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_e2e_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_e2e_reg_")
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

    def _make_video(self, duration_s: float, name: str = "test.mp4") -> str:
        path = os.path.join(self.workspace, name)
        subprocess.run(
            ["ffmpeg", "-y",
             "-f", "lavfi", "-i", f"testsrc=duration={duration_s}:size=320x240:rate=10",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_s}",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
             "-c:a", "aac", "-b:a", "64k", "-shortest", path],
            capture_output=True, timeout=60, check=True,
        )
        return path

    def _make_speech_video(self, text: str, name: str = "speech.mp4") -> str:
        path = os.path.join(self.workspace, name)
        wav = os.path.join(self.workspace, "speech.wav")
        try:
            subprocess.run(["flite", "-t", text, "-o", wav],
                           capture_output=True, timeout=30, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                 "-ar", "16000", "-ac", "1", wav],
                capture_output=True, timeout=30, check=True,
            )
        subprocess.run(
            ["ffmpeg", "-y",
             "-f", "lavfi", "-i", "testsrc=duration=5:size=320x240:rate=10",
             "-i", wav,
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
             "-c:a", "aac", "-b:a", "64k", "-shortest", path],
            capture_output=True, timeout=30, check=True,
        )
        return path

    def test_30s_video_full_pipeline_no_transcription(self) -> None:
        """30s video through full ingest pipeline without STT."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()
        creator_job.start_worker(max_concurrent=1)

        video = self._make_video(30, "short_30s.mp4")
        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": video},
            workspace_dir=self.workspace,
            config={"transcribe": False},
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        for _ in range(300):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed", f"Failed: {loaded.get('error')}")
        self.assertEqual(loaded["progress_pct"], 100)

    def test_speech_video_with_transcription(self) -> None:
        """Short speech video with chunked STT transcription."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()
        creator_job.start_worker(max_concurrent=1)

        video = self._make_speech_video("Hello world. This is a test of the creator platform.")
        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": video},
            workspace_dir=self.workspace,
            config={"language": "en", "model_size": "tiny", "transcribe": True},
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        for _ in range(300):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed", f"Failed: {loaded.get('error')}")

        transcript = loaded["artifacts"].get("transcript_merge", {})
        self.assertIn("text", transcript)
        self.assertIn("segments", transcript)

    def test_stage_failure_produces_clear_error(self) -> None:
        """Ingest with nonexistent file produces clear stage-specific error."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()
        creator_job.start_worker(max_concurrent=1)

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/nonexistent/video.mp4"},
            workspace_dir=self.workspace,
            config={"transcribe": False},
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        for _ in range(50):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] == "failed":
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "failed")
        self.assertIn("not found", loaded["error"].lower())
        self.assertEqual(loaded["stages"][0]["status"], "failed")

    def test_retry_after_failure(self) -> None:
        """Failed job can be retried and succeeds on second attempt."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()
        creator_job.start_worker(max_concurrent=1)

        # First attempt: file doesn't exist
        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": os.path.join(self.workspace, "missing.mp4")},
            workspace_dir=self.workspace,
            config={"transcribe": False},
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        for _ in range(50):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] == "failed":
                break
            time.sleep(0.1)

        self.assertEqual(
            creator_job.load_job(job["job_id"], self.workspace)["status"], "failed"
        )

        # Now create the file and retry
        self._make_video(2, "missing.mp4")
        creator_job.retry_job(job["job_id"], self.workspace)

        for _ in range(100):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed", f"Retry failed: {loaded.get('error')}")


if __name__ == "__main__":
    unittest.main()
