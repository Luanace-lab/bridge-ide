"""Tests for creator job lifecycle — resume, retry, cancel, backpressure."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch


class TestCreatorJobLifecycle(unittest.TestCase):
    """Test resume, retry, cancel and lifecycle edge cases."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_lifecycle_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_lifecycle_reg_")
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

    def test_retry_reexecutes_from_failed_stage(self) -> None:
        """POST retry on a failed job re-executes from the failed stage."""
        import creator_job

        call_log: list[str] = []

        def ok_stage(job: dict) -> dict:
            call_log.append("ok")
            return {"result": "ok"}

        def fail_once_stage(job: dict) -> dict:
            if job["attempt_count"] <= 1:
                raise RuntimeError("first attempt fails")
            call_log.append("retry_ok")
            return {"result": "retry_ok"}

        creator_job.register_stages(
            "local_ingest",
            [("s1", ok_stage), ("s2", ok_stage), ("s3", fail_once_stage)],
        )
        creator_job.start_worker(max_concurrent=1)

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        # Wait for failure
        for _ in range(50):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] == "failed":
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "failed")
        self.assertEqual(loaded["stages"][2]["status"], "failed")

        # Clear call log, retry
        call_log.clear()
        creator_job.retry_job(job["job_id"], self.workspace)

        # Wait for completion
        for _ in range(50):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed")
        # s1 and s2 should NOT have been re-executed (already completed)
        self.assertNotIn("ok", call_log)
        self.assertIn("retry_ok", call_log)

    def test_resume_after_simulated_crash(self) -> None:
        """Jobs with status=running on reload are detected as interrupted."""
        import creator_job

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        # Simulate: stages 1-2 completed, stage 3 was running when crash happened
        job["status"] = "running"
        job["stage"] = "s3"
        job["stages"] = [
            {"name": "s1", "status": "completed", "started_at": None, "completed_at": None, "error": None, "artifacts": {}},
            {"name": "s2", "status": "completed", "started_at": None, "completed_at": None, "error": None, "artifacts": {}},
            {"name": "s3", "status": "running", "started_at": None, "completed_at": None, "error": None, "artifacts": {}},
        ]
        creator_job.save_job(job)

        interrupted = creator_job.find_interrupted_jobs(self.workspace)
        self.assertEqual(len(interrupted), 1)
        self.assertEqual(interrupted[0]["job_id"], job["job_id"])
        self.assertEqual(interrupted[0]["resume_from_stage"], "s3")

    def test_job_get_endpoint_recovers_interrupted_jobs_once(self) -> None:
        """GET /creator/jobs/{id} triggers one-time recovery for interrupted jobs."""
        import creator_job
        import handlers.creator as creator_routes

        creator_routes._RECOVERED_INTERRUPTED_JOBS.clear()

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        job["status"] = "running"
        job["stage"] = "source_resolve"
        job["stages"] = [
            {"name": "source_resolve", "status": "running", "started_at": None, "completed_at": None, "error": None, "artifacts": {}},
            {"name": "probe", "status": "queued", "started_at": None, "completed_at": None, "error": None, "artifacts": {}},
        ]
        creator_job.save_job(job)

        ws = self.workspace

        class MockHandler:
            def __init__(self) -> None:
                self.path = f"/creator/jobs/{job['job_id']}?workspace_dir={ws}"
                self.response_code: int | None = None
                self.response_body: dict | None = None

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        with patch("creator_job.resume_job", return_value=True) as mock_resume:
            result = creator_routes.handle_get(handler, f"/creator/jobs/{job['job_id']}")
            self.assertTrue(result)
            self.assertEqual(handler.response_code, 200)
            mock_resume.assert_called_once_with(job["job_id"], self.workspace)

            handler2 = MockHandler()
            result2 = creator_routes.handle_get(handler2, f"/creator/jobs/{job['job_id']}")
            self.assertTrue(result2)
            self.assertEqual(handler2.response_code, 200)
            mock_resume.assert_called_once()

    def test_resume_job_normalizes_incomplete_stage_list(self) -> None:
        """Resume must tolerate persisted jobs with incomplete stage lists."""
        import creator_job

        creator_job._reset_worker_state()

        def ok_stage(job: dict) -> dict:
            return {"ok": True}

        creator_job.register_stages(
            "local_ingest",
            [("s1", ok_stage), ("s2", ok_stage), ("s3", ok_stage)],
        )
        creator_job.start_worker(max_concurrent=1)

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        job["status"] = "running"
        job["stage"] = "s1"
        job["stages"] = [
            {"name": "s1", "status": "running", "started_at": None, "completed_at": None, "error": None, "artifacts": {}},
        ]
        creator_job.save_job(job)

        self.assertTrue(creator_job.resume_job(job["job_id"], self.workspace))

        for _ in range(50):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed")
        self.assertEqual([stage["name"] for stage in loaded["stages"]], ["s1", "s2", "s3"])

    def test_cancel_via_api(self) -> None:
        """cancel_job prevents remaining stages from executing."""
        import creator_job

        stage_calls: list[str] = []

        def slow_stage(job: dict) -> dict:
            stage_calls.append(job["stage"])
            time.sleep(0.4)
            return {"result": "ok"}

        creator_job.register_stages(
            "local_ingest",
            [("s1", slow_stage), ("s2", slow_stage), ("s3", slow_stage), ("s4", slow_stage)],
        )
        creator_job.start_worker(max_concurrent=1)

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        # Wait for first stage to start
        time.sleep(0.2)
        creator_job.cancel_job(job["job_id"])

        for _ in range(30):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("cancelled", "completed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "cancelled")
        self.assertLess(len(stage_calls), 4)

    def test_retry_http_endpoint(self) -> None:
        """POST /creator/jobs/{job_id}/retry re-enqueues a failed job."""
        import creator_job

        def ok_stage(job: dict) -> dict:
            return {"result": "ok"}

        def fail_stage(job: dict) -> dict:
            if job["attempt_count"] <= 1:
                raise RuntimeError("fail first")
            return {"result": "ok"}

        creator_job.register_stages(
            "local_ingest",
            [("s1", ok_stage), ("s2", fail_stage)],
        )
        creator_job.start_worker(max_concurrent=1)

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        # Wait for failure
        for _ in range(50):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] == "failed":
                break
            time.sleep(0.1)

        # Call retry via handler
        from handlers.creator import handle_post

        ws = self.workspace  # capture for closure

        class MockHandler:
            def __init__(self) -> None:
                self.path = f"/creator/jobs/{job['job_id']}/retry"
                self.response_code: int | None = None
                self.response_body: dict | None = None
                self._body: dict = {"workspace_dir": ws}

            def _parse_json_body(self) -> dict:
                return self._body

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_post(handler, f"/creator/jobs/{job['job_id']}/retry")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 200)

        # Wait for completion
        for _ in range(50):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] == "completed":
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed")


if __name__ == "__main__":
    unittest.main()
