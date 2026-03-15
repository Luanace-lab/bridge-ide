"""Tests for agent-based clip analysis in creator job pipeline."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch


class TestCreatorJobAnalysis(unittest.TestCase):
    """Test agent-based content analysis and captioning."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_analysis_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_analysis_reg_")
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

    def _create_job_with_transcript(self) -> dict:
        """Create a job that already has a transcript (simulates post-ingest)."""
        import creator_job

        job = creator_job.create_job(
            job_type="analyze_content",
            source={"input_path": "/tmp/video.mp4"},
            workspace_dir=self.workspace,
            config={"target_platforms": ["youtube_short", "instagram_reel"]},
        )
        # Inject transcript as if ingest+STT already ran
        job["artifacts"]["transcript_merge"] = {
            "text": "Welcome to this video. Today we will discuss something amazing. "
                    "The first key insight is that AI changes everything. "
                    "Here is a surprising fact that nobody expected. "
                    "Let me show you the results of our experiment. "
                    "In conclusion, this changes how we think about technology.",
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Welcome to this video."},
                {"start": 5.0, "end": 12.0, "text": "Today we will discuss something amazing."},
                {"start": 12.0, "end": 20.0, "text": "The first key insight is that AI changes everything."},
                {"start": 20.0, "end": 30.0, "text": "Here is a surprising fact that nobody expected."},
                {"start": 30.0, "end": 42.0, "text": "Let me show you the results of our experiment."},
                {"start": 42.0, "end": 50.0, "text": "In conclusion, this changes how we think about technology."},
            ],
            "duration_s": 50.0,
        }
        creator_job.save_job(job)
        return job

    def test_analysis_with_mock_agent_returns_clips(self) -> None:
        """Analysis job creates a task and parses agent response."""
        import creator_job
        from creator_job_stages import register_analysis_stages

        register_analysis_stages()
        creator_job.start_worker(max_concurrent=1)

        job = self._create_job_with_transcript()

        # Mock the agent interaction (HTTP calls to task system)
        mock_task_result = {
            "clips": [
                {
                    "start_s": 20.0,
                    "end_s": 42.0,
                    "title": "Surprising AI Results",
                    "reason": "Strong hook + unexpected reveal",
                    "caption": "You won't believe what AI can do #AI #tech",
                    "hashtags": ["#AI", "#tech", "#experiment"],
                    "engagement_score": 0.85,
                    "platforms": ["youtube_short", "instagram_reel"],
                }
            ]
        }

        with patch("creator_job_stages._request_agent_analysis") as mock_agent:
            mock_agent.return_value = mock_task_result
            creator_job.submit_job(job["job_id"], self.workspace)

            for _ in range(50):
                loaded = creator_job.load_job(job["job_id"], self.workspace)
                if loaded and loaded["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed", f"Failed: {loaded.get('error')}")

        # Verify analysis artifacts
        analysis = loaded["artifacts"].get("analysis_execute", {})
        self.assertIn("clips", analysis)
        self.assertEqual(len(analysis["clips"]), 1)
        clip = analysis["clips"][0]
        self.assertEqual(clip["start_s"], 20.0)
        self.assertEqual(clip["end_s"], 42.0)
        self.assertIn("caption", clip)
        self.assertIn("hashtags", clip)

    def test_analysis_fallback_when_agent_unavailable(self) -> None:
        """When agent is unavailable, fall back to heuristic highlight selection."""
        import creator_job
        from creator_job_stages import register_analysis_stages

        register_analysis_stages()
        creator_job.start_worker(max_concurrent=1)

        job = self._create_job_with_transcript()

        with patch("creator_job_stages._request_agent_analysis") as mock_agent:
            mock_agent.side_effect = ConnectionError("Agent unavailable")
            creator_job.submit_job(job["job_id"], self.workspace)

            for _ in range(50):
                loaded = creator_job.load_job(job["job_id"], self.workspace)
                if loaded and loaded["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed", f"Failed: {loaded.get('error')}")

        analysis = loaded["artifacts"].get("analysis_execute", {})
        self.assertIn("clips", analysis)
        self.assertTrue(analysis.get("fallback", False))

    def test_analysis_fallback_on_invalid_json(self) -> None:
        """When agent returns invalid JSON, fall back to heuristic."""
        import creator_job
        from creator_job_stages import register_analysis_stages

        register_analysis_stages()
        creator_job.start_worker(max_concurrent=1)

        job = self._create_job_with_transcript()

        with patch("creator_job_stages._request_agent_analysis") as mock_agent:
            mock_agent.return_value = "not a dict"
            creator_job.submit_job(job["job_id"], self.workspace)

            for _ in range(50):
                loaded = creator_job.load_job(job["job_id"], self.workspace)
                if loaded and loaded["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed")

        analysis = loaded["artifacts"].get("analysis_execute", {})
        self.assertTrue(analysis.get("fallback", False))

    def test_analysis_http_endpoint(self) -> None:
        """POST /creator/jobs/analyze returns 202."""
        import creator_job
        from creator_job_stages import register_analysis_stages
        from handlers.creator import handle_post

        register_analysis_stages()
        creator_job.start_worker(max_concurrent=1)

        job = self._create_job_with_transcript()

        class MockHandler:
            def __init__(self) -> None:
                self.path = "/creator/jobs/analyze"
                self.response_code: int | None = None
                self.response_body: dict | None = None

            def _parse_json_body(self) -> dict:
                return {
                    "job_id": job["job_id"],
                    "workspace_dir": self.ws,
                }

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        handler.ws = self.workspace
        result = handle_post(handler, "/creator/jobs/analyze")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 202)

    def test_analysis_http_endpoint_accepts_source_job_id_alias(self) -> None:
        """POST /creator/jobs/analyze accepts source_job_id for usability symmetry."""
        import creator_job
        from creator_job_stages import register_analysis_stages
        from handlers.creator import handle_post

        register_analysis_stages()
        creator_job.start_worker(max_concurrent=1)

        job = self._create_job_with_transcript()

        class MockHandler:
            def __init__(self) -> None:
                self.path = "/creator/jobs/analyze"
                self.response_code: int | None = None
                self.response_body: dict | None = None

            def _parse_json_body(self) -> dict:
                return {
                    "source_job_id": job["job_id"],
                    "workspace_dir": self.ws,
                }

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        handler.ws = self.workspace
        result = handle_post(handler, "/creator/jobs/analyze")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 202)


if __name__ == "__main__":
    unittest.main()
