"""Tests for creator_embeddings — Gemini Embedding 2 + ChromaDB."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock


def _make_video(path: str, duration: float = 5.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=10",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-c:a", "aac", "-b:a", "32k", "-shortest", path],
        capture_output=True, timeout=30, check=True,
    )


class TestCreatorEmbeddings(unittest.TestCase):

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="cj_embed_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_api_key_raises(self) -> None:
        from creator_embeddings import embed_video
        # Clear env
        env_backup = os.environ.pop("GOOGLE_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                embed_video("/tmp/fake.mp4")
            self.assertIn("GOOGLE_API_KEY", str(ctx.exception))
        finally:
            if env_backup:
                os.environ["GOOGLE_API_KEY"] = env_backup

    def test_chunk_video(self) -> None:
        from creator_embeddings import _chunk_video

        video = os.path.join(self.tmpdir, "test.mp4")
        _make_video(video, duration=10.0)

        chunks = _chunk_video(video, chunk_duration_s=4)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertTrue(os.path.isfile(chunk["chunk_path"]))

    def test_embed_video_mock(self) -> None:
        from creator_embeddings import embed_video

        video = os.path.join(self.tmpdir, "test.mp4")
        _make_video(video, duration=3.0)

        mock_vector = [0.1] * 768

        with patch("creator_embeddings._get_google_api_key", return_value="test_key"), \
             patch("creator_embeddings._embed_video_chunk", return_value=mock_vector):
            result = embed_video(video, chunk_duration_s=120)

        self.assertEqual(result["embedded_count"], 1)
        self.assertEqual(len(result["embeddings"]), 1)
        self.assertEqual(len(result["embeddings"][0]["vector"]), 768)

    def test_store_and_search_chromadb(self) -> None:
        from creator_embeddings import store_embeddings, list_embedded_videos
        import chromadb

        # Use ephemeral client for test isolation
        embeddings = [
            {"chunk_index": 0, "start_s": 0, "end_s": 5, "vector": [0.1] * 768},
            {"chunk_index": 1, "start_s": 5, "end_s": 10, "vector": [0.2] * 768},
        ]

        collection_name = f"test_collection_{os.getpid()}"
        count = store_embeddings(collection_name, embeddings, "/tmp/test_video.mp4")
        self.assertEqual(count, 2)

        # Cleanup
        client = chromadb.Client()
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass

    def test_embed_job_completes(self) -> None:
        """Full embed job via job pipeline."""
        import creator_job
        from creator_job_stages import register_embed_stages

        ws = tempfile.mkdtemp(prefix="cj_embed_ws_")
        reg_dir = tempfile.mkdtemp(prefix="cj_embed_reg_")
        orig = creator_job._REGISTRY_PATH
        creator_job._REGISTRY_PATH = os.path.join(reg_dir, "reg.json")
        creator_job._reset_worker_state()

        try:
            register_embed_stages()
            creator_job.start_worker(max_concurrent=1)

            video = os.path.join(self.tmpdir, "embed_test.mp4")
            _make_video(video, duration=3.0)

            job = creator_job.create_job(
                job_type="embed_content",
                source={"video_path": video},
                workspace_dir=ws,
                config={"chunk_duration_s": 120},
            )
            creator_job.save_job(job)

            mock_vector = [0.1] * 768
            with patch("creator_embeddings._get_google_api_key", return_value="test_key"), \
                 patch("creator_embeddings._embed_video_chunk", return_value=mock_vector):
                creator_job.submit_job(job["job_id"], ws)
                for _ in range(50):
                    loaded = creator_job.load_job(job["job_id"], ws)
                    if loaded and loaded["status"] in ("completed", "failed"):
                        break
                    time.sleep(0.1)

            loaded = creator_job.load_job(job["job_id"], ws)
            self.assertEqual(loaded["status"], "completed", f"Failed: {loaded.get('error')}")
            self.assertIn("embed_store", loaded["artifacts"])
        finally:
            creator_job.stop_worker()
            creator_job._REGISTRY_PATH = orig
            shutil.rmtree(ws, ignore_errors=True)
            shutil.rmtree(reg_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
