"""Tests for creator video edit — ffmpeg-based template rendering."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest


def _make_video(path: str, duration: float = 5.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=640x480:rate=10",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "64k", "-shortest", path],
        capture_output=True, timeout=30, check=True,
    )


class TestCreatorVideoEdit(unittest.TestCase):
    """Test ffmpeg-based video rendering."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="cj_edit_")
        self.video = os.path.join(self.tmpdir, "source.mp4")
        _make_video(self.video)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_render_clip_with_title(self) -> None:
        from creator_video_edit import render_clip_with_title

        output = os.path.join(self.tmpdir, "titled.mp4")
        result = render_clip_with_title(
            self.video, output, start_s=0, end_s=3,
            title="Test Title", width=1080, height=1920,
        )
        self.assertTrue(os.path.isfile(output))
        self.assertGreater(result["size_bytes"], 0)
        self.assertEqual(result["width"], 1080)
        self.assertEqual(result["height"], 1920)

    def test_render_with_intro(self) -> None:
        from creator_video_edit import render_with_intro

        output = os.path.join(self.tmpdir, "intro.mp4")
        result = render_with_intro(
            self.video, output, start_s=0, end_s=3,
            intro_text="Welcome", intro_duration_s=2.0,
            width=1080, height=1920,  # Real creator resolution
        )
        self.assertTrue(os.path.isfile(output))
        self.assertGreater(result["size_bytes"], 0)
        self.assertEqual(result["width"], 1080)
        self.assertEqual(result["height"], 1920)
        self.assertAlmostEqual(result["duration_s"], 5.0, delta=0.5)

    def test_render_from_template_simple(self) -> None:
        from creator_video_edit import render_from_template

        output = os.path.join(self.tmpdir, "tmpl.mp4")
        result = render_from_template(
            "simple_clip", self.video, output,
            start_s=0, end_s=3,
            params={"title": "Template Test"},
        )
        self.assertTrue(os.path.isfile(output))
        self.assertEqual(result["title"], "Template Test")

    def test_render_from_template_intro(self) -> None:
        from creator_video_edit import render_from_template

        output = os.path.join(self.tmpdir, "intro_tmpl.mp4")
        result = render_from_template(
            "intro_clip", self.video, output,
            start_s=0, end_s=3,
            params={"intro_text": "Episode 1"},  # Uses template default 1080x1920
        )
        self.assertTrue(os.path.isfile(output))
        self.assertIn("intro_text", result)

    def test_list_templates(self) -> None:
        from creator_video_edit import list_templates

        templates = list_templates()
        names = [t["name"] for t in templates]
        self.assertIn("simple_clip", names)
        self.assertIn("intro_clip", names)
        self.assertIn("caption_clip", names)
        self.assertIn("landscape_clip", names)

    def test_nonexistent_input_raises(self) -> None:
        from creator_video_edit import render_clip_with_title, RenderError

        with self.assertRaises(RenderError):
            render_clip_with_title("/nonexistent.mp4", "/tmp/out.mp4", 0, 3)

    def test_nonexistent_template_raises(self) -> None:
        from creator_video_edit import render_from_template, RenderError

        with self.assertRaises(RenderError):
            render_from_template("nonexistent_tmpl", self.video, "/tmp/out.mp4", 0, 3)

    def test_render_job_via_stages(self) -> None:
        """render_template job type works end-to-end."""
        import creator_job
        from creator_job_stages import register_render_stages

        ws = tempfile.mkdtemp(prefix="cj_render_ws_")
        reg_dir = tempfile.mkdtemp(prefix="cj_render_reg_")
        orig = creator_job._REGISTRY_PATH
        creator_job._REGISTRY_PATH = os.path.join(reg_dir, "reg.json")
        creator_job._reset_worker_state()

        try:
            register_render_stages()
            creator_job.start_worker(max_concurrent=1)

            job = creator_job.create_job(
                job_type="clip_export",
                source={"input_path": self.video},
                workspace_dir=ws,
                config={
                    "template": "simple_clip",
                    "start_s": 0,
                    "end_s": 3,
                    "params": {"title": "Render Test"},
                },
            )
            creator_job.save_job(job)
            creator_job.submit_job(job["job_id"], ws)

            for _ in range(100):
                loaded = creator_job.load_job(job["job_id"], ws)
                if loaded and loaded["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)

            loaded = creator_job.load_job(job["job_id"], ws)
            self.assertEqual(loaded["status"], "completed", f"Failed: {loaded.get('error')}")

            render_result = loaded["artifacts"].get("render_execute", {})
            self.assertIn("output_path", render_result)
            self.assertTrue(os.path.isfile(render_result["output_path"]))
        finally:
            creator_job.stop_worker()
            creator_job._REGISTRY_PATH = orig
            shutil.rmtree(ws, ignore_errors=True)
            shutil.rmtree(reg_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
