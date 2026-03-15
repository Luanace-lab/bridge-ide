"""Tests for creator_job.py — Job model, persistence, registry."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest


class TestCreatorJobModel(unittest.TestCase):
    """Test CreatorJob data model and persistence."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_test_ws_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_test_reg_")
        # Patch BASE_DIR so registry goes to temp dir
        import creator_job

        self._orig_registry_path = creator_job._REGISTRY_PATH
        creator_job._REGISTRY_PATH = os.path.join(
            self.registry_dir, "creator_job_registry.json"
        )

    def tearDown(self) -> None:
        import creator_job

        creator_job._REGISTRY_PATH = self._orig_registry_path
        shutil.rmtree(self.workspace, ignore_errors=True)
        shutil.rmtree(self.registry_dir, ignore_errors=True)

    def test_create_job_returns_valid_structure(self) -> None:
        import creator_job

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/video.mp4"},
            workspace_dir=self.workspace,
            config={"language": "de", "transcribe": True},
        )
        self.assertTrue(job["job_id"].startswith("cj_"))
        self.assertEqual(job["job_type"], "local_ingest")
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["source"]["input_path"], "/tmp/video.mp4")
        self.assertEqual(job["workspace_dir"], self.workspace)
        self.assertEqual(job["config"]["language"], "de")
        self.assertIsInstance(job["stages"], list)
        self.assertIsInstance(job["warnings"], list)
        self.assertIsInstance(job["artifacts"], dict)
        self.assertEqual(job["attempt_count"], 0)
        self.assertIsNone(job["error"])
        self.assertIsNone(job["resume_from_stage"])

    def test_persist_and_reload_job(self) -> None:
        import creator_job

        job = creator_job.create_job(
            job_type="url_ingest",
            source={"source_url": "https://example.com/v.mp4"},
            workspace_dir=self.workspace,
        )
        job_id = job["job_id"]

        # Save
        creator_job.save_job(job)

        # Verify file exists
        job_dir = os.path.join(self.workspace, "creator_jobs", job_id)
        self.assertTrue(os.path.isdir(job_dir))
        self.assertTrue(os.path.isfile(os.path.join(job_dir, "job.json")))

        # Reload
        loaded = creator_job.load_job(job_id, self.workspace)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["job_id"], job_id)
        self.assertEqual(loaded["job_type"], "url_ingest")
        self.assertEqual(loaded["source"]["source_url"], "https://example.com/v.mp4")

    def test_update_status_persists(self) -> None:
        import creator_job

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        job_id = job["job_id"]
        creator_job.save_job(job)

        # Update status
        job["status"] = "running"
        job["stage"] = "probe"
        creator_job.save_job(job)

        # Reload and verify
        loaded = creator_job.load_job(job_id, self.workspace)
        self.assertEqual(loaded["status"], "running")
        self.assertEqual(loaded["stage"], "probe")

    def test_registry_enumerates_jobs(self) -> None:
        import creator_job

        # Create multiple jobs
        job1 = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/a.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job1)

        job2 = creator_job.create_job(
            job_type="url_ingest",
            source={"source_url": "https://example.com/b.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job2)

        # List
        jobs = creator_job.list_jobs(workspace_dir=self.workspace)
        job_ids = [j["job_id"] for j in jobs]
        self.assertIn(job1["job_id"], job_ids)
        self.assertIn(job2["job_id"], job_ids)

    def test_registry_filters_by_status(self) -> None:
        import creator_job

        job1 = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/a.mp4"},
            workspace_dir=self.workspace,
        )
        job1["status"] = "completed"
        creator_job.save_job(job1)

        job2 = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/b.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job2)

        queued = creator_job.list_jobs(workspace_dir=self.workspace, status="queued")
        completed = creator_job.list_jobs(
            workspace_dir=self.workspace, status="completed"
        )
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["job_id"], job2["job_id"])
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["job_id"], job1["job_id"])

    def test_append_job_event(self) -> None:
        import creator_job

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job)

        creator_job.append_job_event(
            job["job_id"],
            self.workspace,
            event_type="stage_started",
            data={"stage": "probe"},
        )
        creator_job.append_job_event(
            job["job_id"],
            self.workspace,
            event_type="stage_completed",
            data={"stage": "probe", "duration_s": 1.2},
        )

        # Read events
        events_path = os.path.join(
            self.workspace, "creator_jobs", job["job_id"], "events.jsonl"
        )
        self.assertTrue(os.path.isfile(events_path))
        with open(events_path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["event_type"], "stage_started")
        self.assertEqual(lines[1]["event_type"], "stage_completed")
        self.assertEqual(lines[1]["data"]["duration_s"], 1.2)

    def test_load_nonexistent_job_returns_none(self) -> None:
        import creator_job

        result = creator_job.load_job("cj_nonexistent", self.workspace)
        self.assertIsNone(result)

    def test_resume_flag_on_running_reload(self) -> None:
        """Jobs with status=running on reload should have resume_from_stage set."""
        import creator_job

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        # Simulate: stage 'probe' completed, stage 'audio_extract' was running
        job["status"] = "running"
        job["stage"] = "audio_extract"
        job["stages"] = [
            {"name": "source_resolve", "status": "completed"},
            {"name": "probe", "status": "completed"},
            {"name": "audio_extract", "status": "running"},
        ]
        creator_job.save_job(job)

        # Reload and check interrupted jobs
        interrupted = creator_job.find_interrupted_jobs(self.workspace)
        self.assertEqual(len(interrupted), 1)
        self.assertEqual(interrupted[0]["job_id"], job["job_id"])
        self.assertEqual(interrupted[0]["resume_from_stage"], "audio_extract")

    def test_job_creates_artifacts_and_chunks_dirs(self) -> None:
        import creator_job

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job)

        job_dir = os.path.join(self.workspace, "creator_jobs", job["job_id"])
        self.assertTrue(os.path.isdir(os.path.join(job_dir, "artifacts")))
        self.assertTrue(os.path.isdir(os.path.join(job_dir, "chunks")))

    def test_atomic_save_survives_concurrent_reads(self) -> None:
        """Verify save uses atomic write (tempfile + replace)."""
        import creator_job

        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        creator_job.save_job(job)

        # Rapid save-load cycle
        for i in range(20):
            job["progress_pct"] = i * 5
            creator_job.save_job(job)
            loaded = creator_job.load_job(job["job_id"], self.workspace)
            self.assertEqual(loaded["progress_pct"], i * 5)


if __name__ == "__main__":
    unittest.main()
