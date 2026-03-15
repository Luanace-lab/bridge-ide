"""Tests for creator batch workflows — batch ingest and batch publish."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch


class TestCreatorBatch(unittest.TestCase):
    """Test batch ingest and batch publish."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_batch_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_batch_reg_")
        import creator_job

        self._orig_registry_path = creator_job._REGISTRY_PATH
        creator_job._REGISTRY_PATH = os.path.join(
            self.registry_dir, "creator_job_registry.json"
        )
        creator_job._reset_worker_state()

    def tearDown(self) -> None:
        import creator_job

        creator_job.stop_worker()
        time.sleep(0.2)  # let worker thread finish pending writes
        creator_job._REGISTRY_PATH = self._orig_registry_path
        shutil.rmtree(self.workspace, ignore_errors=True)
        shutil.rmtree(self.registry_dir, ignore_errors=True)

    def _make_video(self, name: str) -> str:
        path = os.path.join(self.workspace, name)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=5",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
             "-c:a", "aac", "-b:a", "32k", "-shortest", path],
            capture_output=True, timeout=15, check=True,
        )
        return path

    def test_batch_ingest_creates_multiple_jobs(self) -> None:
        """Batch ingest with 3 sources creates 3 individual jobs."""
        import creator_job
        from creator_job_stages import register_ingest_stages

        register_ingest_stages()
        creator_job.start_worker(max_concurrent=2)

        v1 = self._make_video("a.mp4")
        v2 = self._make_video("b.mp4")
        v3 = self._make_video("c.mp4")

        from handlers.creator import handle_post

        ws = self.workspace

        class MockHandler:
            def __init__(self) -> None:
                self.path = "/creator/jobs/batch-ingest"
                self.response_code = None
                self.response_body = None

            def _parse_json_body(self):
                return {
                    "workspace_dir": ws,
                    "sources": [
                        {"input_path": v1},
                        {"input_path": v2},
                        {"input_path": v3},
                    ],
                    "transcribe": False,
                }

            def _respond(self, code, body):
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_post(handler, "/creator/jobs/batch-ingest")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 202)
        self.assertIn("batch_id", handler.response_body)
        self.assertEqual(len(handler.response_body["job_ids"]), 3)

        # Wait for all to complete
        for _ in range(100):
            all_done = True
            for jid in handler.response_body["job_ids"]:
                loaded = creator_job.load_job(jid, self.workspace)
                if not loaded or loaded["status"] not in ("completed", "failed"):
                    all_done = False
                    break
            if all_done:
                break
            time.sleep(0.1)

        for jid in handler.response_body["job_ids"]:
            loaded = creator_job.load_job(jid, self.workspace)
            self.assertEqual(loaded["status"], "completed", f"Job {jid} failed: {loaded.get('error')}")

    def test_batch_publish_creates_multiple_publish_jobs(self) -> None:
        """Batch publish creates N publish jobs with schedules."""
        import creator_job
        from creator_job_stages import register_publish_stages

        register_publish_stages()
        creator_job.start_worker(max_concurrent=2)

        ws = self.workspace

        class MockHandler:
            def __init__(self) -> None:
                self.path = "/creator/jobs/publish-batch"
                self.response_code = None
                self.response_body = None

            def _parse_json_body(self):
                return {
                    "workspace_dir": ws,
                    "publishes": [
                        {"source_job_id": "cj_fake1", "clip_path": "/tmp/c1.mp4",
                         "channels": [{"type": "telegram", "target": "@t", "caption": "Day 1"}]},
                        {"source_job_id": "cj_fake2", "clip_path": "/tmp/c2.mp4",
                         "channels": [{"type": "telegram", "target": "@t", "caption": "Day 2"}]},
                    ],
                }

            def _respond(self, code, body):
                self.response_code = code
                self.response_body = body

        from handlers.creator import handle_post

        handler = MockHandler()
        with patch("common.http_post_json") as mock_post:
            mock_post.return_value = {"status": "sent"}
            result = handle_post(handler, "/creator/jobs/publish-batch")

        self.assertTrue(result)
        self.assertEqual(handler.response_code, 202)
        self.assertEqual(len(handler.response_body["job_ids"]), 2)

    def test_batch_status_endpoint(self) -> None:
        """GET /creator/jobs/batch/{batch_id} returns aggregated status."""
        import creator_job
        import json

        # Create batch file manually
        batch_id = "batch_test123"
        batch_dir = os.path.join(self.workspace, "creator_batches")
        os.makedirs(batch_dir, exist_ok=True)

        j1 = creator_job.create_job("local_ingest", {"input_path": "/tmp/a.mp4"}, self.workspace)
        j1["status"] = "completed"
        creator_job.save_job(j1)

        j2 = creator_job.create_job("local_ingest", {"input_path": "/tmp/b.mp4"}, self.workspace)
        j2["status"] = "failed"
        j2["error"] = "test error"
        creator_job.save_job(j2)

        batch_data = {"batch_id": batch_id, "job_ids": [j1["job_id"], j2["job_id"]]}
        with open(os.path.join(batch_dir, f"{batch_id}.json"), "w") as f:
            json.dump(batch_data, f)

        from handlers.creator import handle_get

        ws = self.workspace

        class MockHandler:
            def __init__(self) -> None:
                self.path = f"/creator/jobs/batch/{batch_id}?workspace_dir={ws}"
                self.response_code = None
                self.response_body = None

            def _respond(self, code, body):
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_get(handler, f"/creator/jobs/batch/{batch_id}")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 200)
        self.assertEqual(handler.response_body["completed"], 1)
        self.assertEqual(handler.response_body["failed"], 1)
        self.assertEqual(handler.response_body["total"], 2)


if __name__ == "__main__":
    unittest.main()
