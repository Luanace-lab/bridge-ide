"""Tests for creator publisher — multi-channel dispatch."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock


class TestCreatorPublisher(unittest.TestCase):
    """Test publishing dispatcher and publish job stages."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_pub_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_pub_reg_")
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

    def test_publish_to_mock_telegram(self) -> None:
        """publish_to_channel dispatches correct HTTP call for telegram."""
        from creator_publisher import publish_to_channel

        with patch("common.http_post_json") as mock_post:
            mock_post.return_value = {"status": "sent", "message_id": "123"}
            result = publish_to_channel("telegram", "@test_channel", "Test caption")

        self.assertEqual(result["channel"], "telegram")
        self.assertEqual(result["status"], "sent")
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("/telegram/send", call_args[0][0])

    def test_publish_unknown_channel_returns_error(self) -> None:
        """Unknown channel type returns error without HTTP call."""
        from creator_publisher import publish_to_channel

        result = publish_to_channel("fax", "+49123", "Hello")
        self.assertEqual(result["status"], "error")
        self.assertIn("Unknown channel", result["error"])

    def test_schedule_publish_creates_automation(self) -> None:
        """schedule_publish creates a one-shot automation."""
        from creator_publisher import schedule_publish

        with patch("common.http_post_json") as mock_post:
            mock_post.return_value = {"automation_id": "auto_123"}
            result = schedule_publish(
                "telegram", "@test", "Scheduled post",
                "2026-03-16T09:00:00Z",
            )

        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["schedule"], "2026-03-16T09:00:00Z")
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("/automation/create", call_args[0][0])

    def test_multi_channel_publish(self) -> None:
        """publish_multi_channel dispatches to multiple channels."""
        from creator_publisher import publish_multi_channel

        with patch("common.http_post_json") as mock_post:
            mock_post.return_value = {"status": "sent"}
            results = publish_multi_channel([
                {"type": "telegram", "target": "@ch1", "caption": "Cap1"},
                {"type": "slack", "target": "#general", "caption": "Cap2"},
            ])

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["channel"], "telegram")
        self.assertEqual(results[1]["channel"], "slack")
        self.assertEqual(mock_post.call_count, 2)

    def test_publish_job_completes(self) -> None:
        """Publish job type runs through stages and produces per-channel results."""
        import creator_job
        from creator_job_stages import register_publish_stages

        register_publish_stages()
        creator_job.start_worker(max_concurrent=1)

        # Create a source job with an artifact
        source_job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": "/tmp/v.mp4"},
            workspace_dir=self.workspace,
        )
        source_job["status"] = "completed"
        source_job["artifacts"]["clip_export"] = {
            "output_path": "/tmp/creator_realtest/clip.mp4",
        }
        creator_job.save_job(source_job)

        # Create publish job
        pub_job = creator_job.create_job(
            job_type="publish",
            source={
                "source_job_id": source_job["job_id"],
                "clip_path": "/tmp/creator_realtest/clip.mp4",
            },
            workspace_dir=self.workspace,
            config={
                "channels": [
                    {"type": "telegram", "target": "@test", "caption": "Test clip"},
                ],
            },
        )
        creator_job.save_job(pub_job)

        with patch("common.http_post_json") as mock_post:
            mock_post.return_value = {"status": "sent"}
            creator_job.submit_job(pub_job["job_id"], self.workspace)

            for _ in range(50):
                loaded = creator_job.load_job(pub_job["job_id"], self.workspace)
                if loaded and loaded["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)

        loaded = creator_job.load_job(pub_job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed", f"Failed: {loaded.get('error')}")

        pub_result = loaded["artifacts"].get("publish_execute", {})
        self.assertIn("results", pub_result)
        self.assertEqual(len(pub_result["results"]), 1)

    def test_publish_http_endpoint(self) -> None:
        """POST /creator/jobs/publish returns 202."""
        import creator_job
        from creator_job_stages import register_publish_stages
        from handlers.creator import handle_post

        register_publish_stages()
        creator_job.start_worker(max_concurrent=1)

        ws = self.workspace

        class MockHandler:
            def __init__(self) -> None:
                self.path = "/creator/jobs/publish"
                self.response_code: int | None = None
                self.response_body: dict | None = None

            def _parse_json_body(self) -> dict:
                return {
                    "source_job_id": "cj_fake123",
                    "clip_path": "/tmp/clip.mp4",
                    "workspace_dir": ws,
                    "channels": [
                        {"type": "telegram", "target": "@test", "caption": "Test"},
                    ],
                }

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_post(handler, "/creator/jobs/publish")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 202)

    def test_publish_job_without_channels_fails_closed(self) -> None:
        """Publish job must fail if no channels are configured."""
        import creator_job
        from creator_job_stages import register_publish_stages

        register_publish_stages()
        creator_job.start_worker(max_concurrent=1)

        pub_job = creator_job.create_job(
            job_type="publish",
            source={"clip_path": "/tmp/creator_realtest/clip.mp4"},
            workspace_dir=self.workspace,
            config={"channels": []},
        )
        creator_job.save_job(pub_job)
        creator_job.submit_job(pub_job["job_id"], self.workspace)

        for _ in range(50):
            loaded = creator_job.load_job(pub_job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(pub_job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "failed")
        self.assertIn("No channels configured", loaded.get("error", ""))

    def test_publish_job_all_channel_errors_fails_closed(self) -> None:
        """Publish job must fail if every target channel fails."""
        import creator_job
        from creator_job_stages import register_publish_stages

        register_publish_stages()
        creator_job.start_worker(max_concurrent=1)

        pub_job = creator_job.create_job(
            job_type="publish",
            source={"clip_path": "/tmp/creator_realtest/clip.mp4"},
            workspace_dir=self.workspace,
            config={"channels": [{"type": "fax", "target": "+49123", "caption": "Nope"}]},
        )
        creator_job.save_job(pub_job)
        creator_job.submit_job(pub_job["job_id"], self.workspace)

        for _ in range(50):
            loaded = creator_job.load_job(pub_job["job_id"], self.workspace)
            if loaded and loaded["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        loaded = creator_job.load_job(pub_job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "failed")
        self.assertIn("All publish channels failed", loaded.get("error", ""))


if __name__ == "__main__":
    unittest.main()
