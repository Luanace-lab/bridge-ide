"""Tests for creator job ingest pipeline — real media through job stages."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest


def _build_sample_video(path: str, duration: float = 2.0) -> None:
    """Generate a short test video with audio using ffmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=10",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "64k",
            "-shortest", path,
        ],
        capture_output=True,
        timeout=30,
        check=True,
    )


class TestCreatorJobIngest(unittest.TestCase):
    """Test the job-based ingest pipeline with real media."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_ingest_test_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_ingest_reg_")
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

    def test_local_ingest_job_completes(self) -> None:
        """Local ingest job with 2s video: all stages complete, artifacts exist."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()

        video_path = os.path.join(self.workspace, "sample.mp4")
        _build_sample_video(video_path)

        creator_job.start_worker(max_concurrent=1)
        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": video_path},
            workspace_dir=self.workspace,
            config={"transcribe": False},
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        # Wait for completion
        for _ in range(100):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed", f"Job failed: {loaded.get('error')}")

        # Verify stages
        stage_names = [s["name"] for s in loaded["stages"]]
        self.assertIn("source_resolve", stage_names)
        self.assertIn("probe", stage_names)
        self.assertIn("audio_extract", stage_names)

        for stage in loaded["stages"]:
            self.assertEqual(stage["status"], "completed", f"Stage {stage['name']} not completed")

        # Verify artifacts
        self.assertIn("probe", loaded["artifacts"])
        self.assertIn("audio_extract", loaded["artifacts"])
        probe_result = loaded["artifacts"]["probe"]
        self.assertGreater(probe_result.get("duration_s", 0), 0)

    def test_local_ingest_nonexistent_file_fails(self) -> None:
        """Ingest with nonexistent file fails at source_resolve."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()

        creator_job.start_worker(max_concurrent=1)
        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/nonexistent_video_12345.mp4"},
            workspace_dir=self.workspace,
            config={"transcribe": False},
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        for _ in range(50):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "failed")
        self.assertEqual(loaded["stages"][0]["name"], "source_resolve")
        self.assertEqual(loaded["stages"][0]["status"], "failed")

    def test_job_events_logged(self) -> None:
        """Events are logged during job execution."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()

        video_path = os.path.join(self.workspace, "sample.mp4")
        _build_sample_video(video_path)

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

        events = creator_job.load_job_events(job["job_id"], self.workspace)
        event_types = [e["event_type"] for e in events]
        self.assertIn("job_started", event_types)
        self.assertIn("job_completed", event_types)
        self.assertIn("stage_started", event_types)
        self.assertIn("stage_completed", event_types)

    def test_http_job_endpoint_returns_202(self) -> None:
        """POST /creator/jobs/local-ingest returns 202 with job_id."""
        # This test verifies the endpoint contract via the handler directly
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()
        creator_job.start_worker(max_concurrent=1)

        video_path = os.path.join(self.workspace, "sample.mp4")
        _build_sample_video(video_path)

        # Simulate handler call
        from handlers.creator import handle_post

        class MockHandler:
            """Minimal handler mock for testing."""

            def __init__(self) -> None:
                self.response_code: int | None = None
                self.response_body: dict | None = None
                self._body_data: dict = {
                    "input_path": video_path,
                    "workspace_dir": self.workspace if hasattr(self, "workspace") else "",
                }

            def _parse_json_body(self) -> dict | None:
                return self._body_data

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        handler._body_data = {
            "input_path": video_path,
            "workspace_dir": self.workspace,
            "transcribe": False,
        }
        result = handle_post(handler, "/creator/jobs/local-ingest")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 202)
        self.assertIn("job_id", handler.response_body)
        self.assertEqual(handler.response_body["status"], "queued")

        # Wait for job to complete
        job_id = handler.response_body["job_id"]
        for _ in range(100):
            loaded = creator_job.load_job(job_id, self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job_id, self.workspace)
        self.assertEqual(loaded["status"], "completed")

    def test_http_job_status_endpoint(self) -> None:
        """GET /creator/jobs/{job_id} returns job state."""
        import creator_job

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job)

        from handlers.creator import handle_get

        class MockHandler:
            def __init__(self, raw_path: str) -> None:
                self.path = raw_path  # raw path with query string
                self.response_code: int | None = None
                self.response_body: dict | None = None

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        raw_path = f"/creator/jobs/{job['job_id']}?workspace_dir={self.workspace}"
        handler = MockHandler(raw_path)
        # server.py passes path without query string
        path = f"/creator/jobs/{job['job_id']}"
        result = handle_get(handler, path)
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 200)
        self.assertEqual(handler.response_body["job_id"], job["job_id"])


if __name__ == "__main__":
    unittest.main()
