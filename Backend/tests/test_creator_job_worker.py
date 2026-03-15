"""Tests for creator_job.py — Worker, Queue, Backpressure."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import unittest


class TestCreatorJobWorker(unittest.TestCase):
    """Test the job worker daemon thread, queue, and backpressure."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_worker_test_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_worker_reg_")
        import creator_job

        self._orig_registry_path = creator_job._REGISTRY_PATH
        creator_job._REGISTRY_PATH = os.path.join(
            self.registry_dir, "creator_job_registry.json"
        )
        # Reset worker state
        creator_job._reset_worker_state()

    def tearDown(self) -> None:
        import creator_job

        creator_job.stop_worker()
        creator_job._REGISTRY_PATH = self._orig_registry_path
        shutil.rmtree(self.workspace, ignore_errors=True)
        shutil.rmtree(self.registry_dir, ignore_errors=True)

    def test_mock_job_completes(self) -> None:
        """Submit a no-op job, verify it transitions queued -> running -> completed."""
        import creator_job

        # Register no-op stages
        def noop_stage(job: dict) -> dict:
            return {"result": "ok"}

        creator_job.register_stages(
            "local_ingest",
            [("stage_a", noop_stage), ("stage_b", noop_stage)],
        )

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job)
        creator_job.start_worker(max_concurrent=1)
        ok = creator_job.submit_job(job["job_id"], self.workspace)
        self.assertTrue(ok)

        # Wait for completion
        for _ in range(50):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed")
        self.assertEqual(len(loaded["stages"]), 2)
        for stage in loaded["stages"]:
            self.assertEqual(stage["status"], "completed")

    def test_backpressure_limits_concurrency(self) -> None:
        """With max_concurrent=2, only 2 jobs run simultaneously."""
        import creator_job

        running_count = {"current": 0, "max_seen": 0}
        lock = threading.Lock()

        def slow_stage(job: dict) -> dict:
            with lock:
                running_count["current"] += 1
                running_count["max_seen"] = max(
                    running_count["max_seen"], running_count["current"]
                )
            time.sleep(0.3)
            with lock:
                running_count["current"] -= 1
            return {"result": "ok"}

        creator_job.register_stages("local_ingest", [("work", slow_stage)])
        creator_job.start_worker(max_concurrent=2)

        job_ids = []
        for i in range(5):
            job = creator_job.create_job(
                job_type="local_ingest",
                source={"input_path": f"/tmp/{i}.mp4"},
                workspace_dir=self.workspace,
            )
            creator_job.save_job(job)
            creator_job.submit_job(job["job_id"], self.workspace)
            job_ids.append(job["job_id"])

        # Wait for all to complete
        for _ in range(100):
            all_done = True
            for jid in job_ids:
                loaded = creator_job.load_job(jid, self.workspace)
                if loaded and loaded["status"] not in ("completed", "failed"):
                    all_done = False
                    break
            if all_done:
                break
            time.sleep(0.1)

        self.assertLessEqual(running_count["max_seen"], 2)
        for jid in job_ids:
            loaded = creator_job.load_job(jid, self.workspace)
            self.assertEqual(loaded["status"], "completed")

    def test_cancel_stops_between_stages(self) -> None:
        """Cancelling a job prevents subsequent stages from running."""
        import creator_job

        stage_calls = {"count": 0}

        def slow_stage(job: dict) -> dict:
            stage_calls["count"] += 1
            time.sleep(0.5)
            return {"result": "ok"}

        creator_job.register_stages(
            "local_ingest",
            [("s1", slow_stage), ("s2", slow_stage), ("s3", slow_stage)],
        )
        creator_job.start_worker(max_concurrent=1)

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job)
        creator_job.submit_job(job["job_id"], self.workspace)

        # Wait for first stage to start, then cancel
        time.sleep(0.2)
        creator_job.cancel_job(job["job_id"])

        # Wait for job to finish
        for _ in range(30):
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("cancelled", "completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "cancelled")
        # Should not have run all 3 stages
        self.assertLess(stage_calls["count"], 3)

    def test_stage_failure_marks_job_failed(self) -> None:
        """A stage that raises marks the job as failed."""
        import creator_job

        def ok_stage(job: dict) -> dict:
            return {"result": "ok"}

        def fail_stage(job: dict) -> dict:
            raise RuntimeError("intentional failure")

        creator_job.register_stages(
            "local_ingest",
            [("s1", ok_stage), ("s2", ok_stage), ("s3", fail_stage)],
        )
        creator_job.start_worker(max_concurrent=1)

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
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
        self.assertIn("intentional failure", loaded["error"])
        # First two stages should be completed
        self.assertEqual(loaded["stages"][0]["status"], "completed")
        self.assertEqual(loaded["stages"][1]["status"], "completed")
        self.assertEqual(loaded["stages"][2]["status"], "failed")

    def test_queue_full_rejects(self) -> None:
        """When queue is full, submit_job returns False."""
        import creator_job

        def block_stage(job: dict) -> dict:
            time.sleep(10)
            return {}

        creator_job.register_stages("local_ingest", [("block", block_stage)])
        creator_job.start_worker(max_concurrent=1, max_queue_size=3)

        jobs = []
        for i in range(5):
            job = creator_job.create_job(
                job_type="local_ingest",
                source={"input_path": f"/tmp/{i}.mp4"},
                workspace_dir=self.workspace,
            )
            creator_job.save_job(job)
            jobs.append(job)

        results = []
        for job in jobs:
            results.append(creator_job.submit_job(job["job_id"], self.workspace))

        # At least one should be rejected (queue size 3, some may be picked up)
        self.assertIn(False, results)


if __name__ == "__main__":
    unittest.main()
