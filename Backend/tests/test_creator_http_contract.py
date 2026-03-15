from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestCreatorHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="creator_http_contract_")
        self.sample_video = os.path.join(self.tmpdir, "sample.mp4")
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self._build_sample_video(self.sample_video)

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build_sample_video(self, output_path: str) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=320x240:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:duration=2",
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:500])

    def _start_server(self) -> str:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _start_file_server(self) -> str:
        handler = functools.partial(SimpleHTTPRequestHandler, directory=self.tmpdir)
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _get(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_creator_local_ingest_without_transcription(self) -> None:
        base_url = self._start_server()

        status_code, body = self._post(
            base_url,
            "/creator/local-ingest",
            {
                "input_path": self.sample_video,
                "workspace_dir": self.tmpdir,
                "transcribe": False,
            },
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["result"]["media"]["video_stream_count"], 1)
        self.assertEqual(body["result"]["media"]["audio_stream_count"], 1)
        self.assertTrue(os.path.isfile(body["result"]["artifacts"]["audio_path"]))

    def test_creator_url_ingest_downloads_local_http_source(self) -> None:
        base_url = self._start_server()
        file_server_url = self._start_file_server()
        workspace_dir = os.path.join(self.tmpdir, "workspace")
        os.makedirs(workspace_dir, exist_ok=True)

        status_code, body = self._post(
            base_url,
            "/creator/url-ingest",
            {
                "source_url": f"{file_server_url}/sample.mp4",
                "workspace_dir": workspace_dir,
                "transcribe": False,
            },
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["result"]["source"]["type"], "url")
        self.assertEqual(body["result"]["download"]["method"], "direct")
        self.assertTrue(os.path.isfile(body["result"]["download"]["local_path"]))

    def test_creator_write_srt_exports_caption_file(self) -> None:
        base_url = self._start_server()
        srt_path = os.path.join(self.tmpdir, "captions.srt")

        status_code, body = self._post(
            base_url,
            "/creator/write-srt",
            {
                "output_path": srt_path,
                "segments": [
                    {"start": 0.0, "end": 1.2, "text": "Erster Satz."},
                    {"start": 1.2, "end": 2.4, "text": "Zweiter Satz."},
                ],
            },
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(os.path.isfile(srt_path))
        with open(srt_path, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("Erster Satz.", content)
        self.assertIn("00:00:01,200 --> 00:00:02,400", content)

    def test_creator_lists_social_presets(self) -> None:
        base_url = self._start_server()
        status_code, body = self._get(base_url, "/creator/social-presets")

        self.assertEqual(status_code, 200)
        self.assertIn("youtube_short", body["presets"])
        self.assertEqual(body["presets"]["square_post"]["aspect_ratio"], "1080:1080")

    def test_creator_lists_jobs_for_workspace(self) -> None:
        import creator_job
        from creator_job_stages import register_analysis_stages, register_embed_stages, register_ingest_stages

        register_ingest_stages()
        register_analysis_stages()
        register_embed_stages()
        job = creator_job.create_job(
            job_type="local_ingest",
            source={"input_path": self.sample_video},
            workspace_dir=self.tmpdir,
            config={"transcribe": False},
        )
        creator_job.save_job(job)

        base_url = self._start_server()
        status_code, body = self._get(base_url, f"/creator/jobs?workspace_dir={self.tmpdir}")

        self.assertEqual(status_code, 200)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["jobs"][0]["job_id"], job["job_id"])
        self.assertEqual(body["jobs"][0]["job_type"], "local_ingest")

    def test_creator_lists_campaigns_for_workspace(self) -> None:
        import creator_campaign

        campaign = creator_campaign.create_campaign(
            title="Creator Launch",
            goal="ship",
            workspace_dir=self.tmpdir,
            owner="leo",
            target_platforms=["youtube", "instagram"],
        )
        creator_campaign.save_campaign(campaign)

        base_url = self._start_server()
        status_code, body = self._get(base_url, f"/creator/campaigns?workspace_dir={self.tmpdir}")

        self.assertEqual(status_code, 200)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["campaigns"][0]["campaign_id"], campaign["campaign_id"])
        self.assertEqual(body["campaigns"][0]["title"], "Creator Launch")

    def test_creator_search_returns_client_error_when_google_key_missing(self) -> None:
        base_url = self._start_server()
        with patch("creator_embeddings.search", side_effect=RuntimeError("No GOOGLE_API_KEY for search embedding")):
            req = urllib.request.Request(
                f"{base_url}/creator/search",
                data=json.dumps({"query": "bridge"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=20)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("No GOOGLE_API_KEY", body["error"])

    def test_creator_highlights_and_export_clip(self) -> None:
        base_url = self._start_server()
        clip_path = os.path.join(self.tmpdir, "clip.mp4")

        status_highlights, body_highlights = self._post(
            base_url,
            "/creator/highlights",
            {
                "segments": [
                    {"start": 0.0, "end": 2.0, "text": "Kurz."},
                    {"start": 2.0, "end": 6.5, "text": "Dies ist ein brauchbarer Highlight-Satz."},
                    {"start": 6.5, "end": 12.0, "text": "Noch ein weiterer Highlight-Kandidat fuer Shorts."},
                ],
                "max_candidates": 2,
                "min_duration_s": 3.0,
            },
        )
        self.assertEqual(status_highlights, 200)
        self.assertEqual(body_highlights["count"], 2)

        status_clip, body_clip = self._post(
            base_url,
            "/creator/export-clip",
            {
                "input_path": self.sample_video,
                "output_path": clip_path,
                "start_s": 0.2,
                "end_s": 1.2,
            },
        )
        self.assertEqual(status_clip, 200)
        self.assertTrue(os.path.isfile(body_clip["result"]["output_path"]))
        self.assertLess(body_clip["result"]["duration_s"], 2.0)

    def test_creator_export_social_clip_with_burned_subtitles(self) -> None:
        base_url = self._start_server()
        clip_path = os.path.join(self.tmpdir, "vertical_clip.mp4")

        status_code, body = self._post(
            base_url,
            "/creator/export-social-clip",
            {
                "input_path": self.sample_video,
                "output_path": clip_path,
                "start_s": 0.0,
                "end_s": 1.5,
                "preset_name": "youtube_short",
                "segments": [
                    {"start": 0.0, "end": 1.4, "text": "Creator Subtitle Line"},
                ],
                "burn_subtitles": True,
            },
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(os.path.isfile(body["result"]["output_path"]))
        self.assertEqual(body["result"]["width"], 1080)
        self.assertEqual(body["result"]["height"], 1920)
        self.assertTrue(body["result"]["burned_subtitles"])
        self.assertEqual(body["result"]["subtitle_segment_count"], 1)

    def test_creator_package_social_outputs_manifest_and_assets(self) -> None:
        base_url = self._start_server()

        status_code, body = self._post(
            base_url,
            "/creator/package-social",
            {
                "input_path": self.sample_video,
                "output_dir": self.tmpdir,
                "package_name": "contract_package",
                "start_s": 0.0,
                "end_s": 1.5,
                "preset_names": ["youtube_short", "square_post"],
                "segments": [
                    {"start": 0.0, "end": 1.4, "text": "Creator package subtitle line"},
                ],
                "burn_subtitles": True,
                "write_sidecar_srt": True,
                "default_metadata": {
                    "title": "Creator Package Title",
                    "hashtags": ["creator", "bridge"],
                    "campaign": "http-contract",
                },
                "metadata_by_preset": {
                    "square_post": {
                        "caption": "Square caption",
                    }
                },
            },
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(os.path.isfile(body["result"]["manifest_path"]))
        self.assertEqual(len(body["result"]["assets"]), 2)
        self.assertTrue(os.path.isfile(body["result"]["sidecar_srt"]["output_path"]))
        self.assertEqual(len(body["result"]["metadata_sidecars"]), 2)
        self.assertTrue(os.path.isfile(body["result"]["metadata_sidecars"][0]["path"]))


if __name__ == "__main__":
    unittest.main()
