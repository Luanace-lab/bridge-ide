"""Tests for multimodal video analysis — frame extraction + vision API."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock


def _make_video(path: str, duration: float = 3.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=10",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "32k", "-shortest", path],
        capture_output=True, timeout=30, check=True,
    )


class TestFrameExtraction(unittest.TestCase):
    """Test keyframe extraction from video."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="cj_vision_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_extract_keyframes_produces_images(self) -> None:
        from creator_media import extract_keyframes

        video = os.path.join(self.tmpdir, "test.mp4")
        _make_video(video, duration=3.0)

        frames = extract_keyframes(video, interval_s=1.0, max_frames=10, output_dir=self.tmpdir)
        self.assertGreater(len(frames), 0)
        for frame_path in frames:
            self.assertTrue(os.path.isfile(frame_path))
            self.assertGreater(os.path.getsize(frame_path), 100)  # not empty

    def test_extract_keyframes_respects_max(self) -> None:
        from creator_media import extract_keyframes

        video = os.path.join(self.tmpdir, "test.mp4")
        _make_video(video, duration=10.0)

        frames = extract_keyframes(video, interval_s=1.0, max_frames=3, output_dir=self.tmpdir)
        self.assertLessEqual(len(frames), 3)

    def test_extract_keyframes_nonexistent_file(self) -> None:
        from creator_media import extract_keyframes, CreatorMediaError

        with self.assertRaises(CreatorMediaError):
            extract_keyframes("/nonexistent.mp4", output_dir=self.tmpdir)

    def test_frames_are_valid_jpeg(self) -> None:
        from creator_media import extract_keyframes

        video = os.path.join(self.tmpdir, "test.mp4")
        _make_video(video, duration=3.0)

        frames = extract_keyframes(video, interval_s=2.0, max_frames=5, output_dir=self.tmpdir)
        for frame_path in frames:
            with open(frame_path, "rb") as f:
                header = f.read(3)
            # JPEG starts with FF D8 FF
            self.assertEqual(header[:2], b'\xff\xd8')


class TestVisionAnalysis(unittest.TestCase):
    """Test vision-enhanced clip analysis."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="cj_vision_analysis_")
        self.workspace = tempfile.mkdtemp(prefix="cj_vision_ws_")
        self.registry_dir = tempfile.mkdtemp(prefix="cj_vision_reg_")
        import creator_job
        self._orig_registry_path = creator_job._REGISTRY_PATH
        creator_job._REGISTRY_PATH = os.path.join(self.registry_dir, "creator_job_registry.json")
        creator_job._reset_worker_state()

    def tearDown(self) -> None:
        import creator_job
        creator_job.stop_worker()
        creator_job._REGISTRY_PATH = self._orig_registry_path
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.workspace, ignore_errors=True)
        shutil.rmtree(self.registry_dir, ignore_errors=True)

    def test_vision_analysis_with_mock_api(self) -> None:
        """Vision analysis extracts frames and sends to API."""
        import creator_job
        from creator_job_stages import register_analysis_stages

        register_analysis_stages()
        creator_job.start_worker(max_concurrent=1)

        video = os.path.join(self.tmpdir, "test.mp4")
        _make_video(video, duration=3.0)

        job = creator_job.create_job(
            job_type="analyze_content",
            source={"input_path": video},
            workspace_dir=self.workspace,
            config={
                "analysis_mode": "vision_api",
                "target_platforms": ["youtube_short"],
            },
        )
        job["artifacts"]["transcript_merge"] = {
            "text": "Hello world. This is amazing content.",
            "segments": [
                {"start": 0.0, "end": 1.5, "text": "Hello world."},
                {"start": 1.5, "end": 3.0, "text": "This is amazing content."},
            ],
            "duration_s": 3.0,
        }
        creator_job.save_job(job)

        mock_response = {
            "clips": [{
                "start_s": 0.0, "end_s": 3.0, "title": "Visual Hook",
                "reason": "Strong visual + text hook",
                "caption": "Amazing!", "hashtags": ["#test"],
                "engagement_score": 0.9, "platforms": ["youtube_short"],
            }]
        }

        with patch("creator_job_stages._call_vision_api") as mock_vision:
            mock_vision.return_value = mock_response
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
        self.assertFalse(analysis.get("fallback", True))

    def test_vision_fallback_to_text_when_no_api_key(self) -> None:
        """Without API key, falls back to text-only analysis."""
        import creator_job
        from creator_job_stages import register_analysis_stages

        register_analysis_stages()
        creator_job.start_worker(max_concurrent=1)

        job = creator_job.create_job(
            job_type="analyze_content",
            source={"input_path": "/tmp/fake.mp4"},
            workspace_dir=self.workspace,
            config={
                "analysis_mode": "vision_api",
                "target_platforms": ["youtube_short"],
            },
        )
        job["artifacts"]["transcript_merge"] = {
            "text": "Test content for fallback.",
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Test content for fallback analysis here."},
            ],
            "duration_s": 5.0,
        }
        creator_job.save_job(job)

        with patch("creator_job_stages._call_vision_api") as mock_vision:
            mock_vision.side_effect = RuntimeError("No API key")
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

    def test_text_mode_skips_frames(self) -> None:
        """analysis_mode=text does not extract frames."""
        import creator_job
        from creator_job_stages import register_analysis_stages

        register_analysis_stages()
        creator_job.start_worker(max_concurrent=1)

        job = creator_job.create_job(
            job_type="analyze_content",
            source={"input_path": "/tmp/fake.mp4"},
            workspace_dir=self.workspace,
            config={
                "analysis_mode": "text",
                "target_platforms": ["youtube_short"],
            },
        )
        job["artifacts"]["transcript_merge"] = {
            "text": "Some text content here for analysis.",
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Some text content here for analysis."},
            ],
            "duration_s": 5.0,
        }
        creator_job.save_job(job)

        with patch("creator_job_stages._request_agent_analysis") as mock_agent:
            mock_agent.side_effect = ConnectionError("No agent")
            creator_job.submit_job(job["job_id"], self.workspace)

            for _ in range(50):
                loaded = creator_job.load_job(job["job_id"], self.workspace)
                if loaded and loaded["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)

        loaded = creator_job.load_job(job["job_id"], self.workspace)
        self.assertEqual(loaded["status"], "completed")
        # Should have used heuristic fallback, no vision
        analysis = loaded["artifacts"].get("analysis_execute", {})
        self.assertTrue(analysis.get("fallback", False))
        self.assertNotEqual(analysis.get("source"), "vision")


if __name__ == "__main__":
    unittest.main()
