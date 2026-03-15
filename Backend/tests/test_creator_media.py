from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from creator_media import (  # noqa: E402
    create_social_package,
    CreatorMediaError,
    export_clip,
    export_social_clip,
    extract_audio_for_transcription,
    group_segments_into_chapters,
    ingest_local_media,
    ingest_url_media,
    list_social_presets,
    pick_highlight_candidates,
    probe_media,
    write_srt,
)


class TestCreatorMedia(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="creator_media_test_")
        self.sample_video = os.path.join(self.tmpdir, "sample.mp4")
        self._build_sample_video(self.sample_video)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _start_file_server(self, directory: str) -> str:
        handler = functools.partial(SimpleHTTPRequestHandler, directory=directory)
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

    def _build_sample_video(self, output_path: str) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
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

    def test_probe_media_and_extract_audio(self) -> None:
        info = probe_media(self.sample_video)
        audio_path = os.path.join(self.tmpdir, "audio.wav")
        audio = extract_audio_for_transcription(self.sample_video, audio_path)

        self.assertEqual(info["video_stream_count"], 1)
        self.assertEqual(info["audio_stream_count"], 1)
        self.assertGreater(info["duration_s"], 0)
        self.assertTrue(os.path.isfile(audio["audio_path"]))
        self.assertGreater(audio["duration_s"], 0)

    def test_group_segments_and_write_srt(self) -> None:
        segments = [
            {"start": 0.0, "end": 10.0, "text": "Intro zum Thema."},
            {"start": 10.0, "end": 28.0, "text": "Wir erklaeren die ersten Schritte."},
            {"start": 28.0, "end": 61.0, "text": "Jetzt kommt der zweite groessere Block."},
        ]

        chapters = group_segments_into_chapters(segments, target_duration_s=25)
        srt_path = os.path.join(self.tmpdir, "captions.srt")
        subtitle = write_srt(segments, srt_path)

        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0]["start"], 0.0)
        self.assertEqual(chapters[1]["end"], 61.0)
        self.assertTrue(os.path.isfile(subtitle["output_path"]))
        with open(srt_path, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("00:00:00,000 --> 00:00:10,000", content)
        self.assertIn("Jetzt kommt der zweite groessere Block.", content)

        highlights = pick_highlight_candidates(segments, max_candidates=2, min_duration_s=5)
        self.assertEqual(len(highlights), 2)
        self.assertGreaterEqual(highlights[0]["score"], highlights[1]["score"])

    def test_export_clip_writes_shorter_video(self) -> None:
        clip_path = os.path.join(self.tmpdir, "clip.mp4")
        clip = export_clip(self.sample_video, clip_path, start_s=0.2, end_s=1.2)

        self.assertTrue(os.path.isfile(clip["output_path"]))
        self.assertGreater(clip["size_bytes"], 0)
        self.assertLess(clip["duration_s"], 2.0)

    def test_export_social_clip_applies_preset_and_burns_subtitles(self) -> None:
        clip_path = os.path.join(self.tmpdir, "square_social.mp4")
        clip = export_social_clip(
            self.sample_video,
            clip_path,
            start_s=0.0,
            end_s=1.5,
            preset_name="square_post",
            segments=[
                {"start": 0.0, "end": 1.4, "text": "Untertitel fuer den Creator-Clip."},
            ],
            burn_subtitles=True,
        )

        self.assertTrue(os.path.isfile(clip["output_path"]))
        self.assertEqual(clip["preset_name"], "square_post")
        self.assertEqual(clip["width"], 1080)
        self.assertEqual(clip["height"], 1080)
        self.assertTrue(clip["burned_subtitles"])
        self.assertEqual(clip["subtitle_segment_count"], 1)

    def test_social_presets_are_exposed(self) -> None:
        presets = list_social_presets()
        self.assertIn("youtube_short", presets)
        self.assertEqual(presets["youtube_short"]["width"], 1080)
        self.assertEqual(presets["youtube_short"]["height"], 1920)

    def test_export_social_clip_requires_segments_for_burned_subtitles(self) -> None:
        clip_path = os.path.join(self.tmpdir, "missing_segments.mp4")
        with self.assertRaises(CreatorMediaError):
            export_social_clip(
                self.sample_video,
                clip_path,
                start_s=0.0,
                end_s=1.0,
                preset_name="youtube_short",
                burn_subtitles=True,
            )

    def test_create_social_package_writes_manifest_assets_and_sidecar_srt(self) -> None:
        package = create_social_package(
            self.sample_video,
            self.tmpdir,
            package_name="creator-package",
            start_s=0.0,
            end_s=1.5,
            preset_names=["youtube_short", "square_post"],
            segments=[
                {"start": 0.0, "end": 1.4, "text": "Creator package subtitle line."},
            ],
            burn_subtitles=True,
            write_sidecar_srt=True,
            default_metadata={
                "title": "Default Creator Title",
                "hashtags": ["creator", "bridge"],
                "campaign": "spring-launch",
            },
            metadata_by_preset={
                "square_post": {
                    "caption": "Square caption",
                    "description": "Square description",
                }
            },
        )

        self.assertEqual(package["package_name"], "creator-package")
        self.assertEqual(len(package["assets"]), 2)
        self.assertTrue(os.path.isfile(package["manifest_path"]))
        self.assertTrue(os.path.isfile(package["sidecar_srt"]["output_path"]))
        self.assertTrue(os.path.isfile(package["assets"][0]["output_path"]))
        self.assertTrue(os.path.isfile(package["assets"][1]["output_path"]))
        self.assertEqual(len(package["metadata_sidecars"]), 2)
        self.assertTrue(os.path.isfile(package["metadata_sidecars"][0]["path"]))
        self.assertTrue(os.path.isfile(package["metadata_sidecars"][1]["path"]))

        with open(package["metadata_sidecars"][1]["path"], "r", encoding="utf-8") as handle:
            sidecar = json.load(handle)
        self.assertEqual(sidecar["title"], "Default Creator Title")
        self.assertEqual(sidecar["caption"], "Square caption")
        self.assertEqual(sidecar["description"], "Square description")
        self.assertEqual(sidecar["hashtags"], ["creator", "bridge"])
        self.assertEqual(sidecar["metadata"]["campaign"], "spring-launch")

    def test_ingest_local_media_without_transcription(self) -> None:
        result = ingest_local_media(self.sample_video, self.tmpdir, transcribe=False)

        self.assertEqual(result["input_path"], self.sample_video)
        self.assertIsNone(result["transcript"])
        self.assertEqual(result["media"]["video_stream_count"], 1)
        self.assertEqual(result["media"]["audio_stream_count"], 1)
        self.assertEqual(result["highlights"], [])
        self.assertTrue(os.path.isfile(result["artifacts"]["audio_path"]))

    def test_ingest_url_media_downloads_local_http_source(self) -> None:
        workspace_dir = os.path.join(self.tmpdir, "workspace")
        os.makedirs(workspace_dir, exist_ok=True)
        base_url = self._start_file_server(self.tmpdir)

        result = ingest_url_media(f"{base_url}/sample.mp4", workspace_dir, transcribe=False)

        self.assertEqual(result["source"]["type"], "url")
        self.assertEqual(result["source"]["provider"], "url")
        self.assertTrue(os.path.isfile(result["download"]["local_path"]))
        self.assertEqual(result["download"]["method"], "direct")
        self.assertIsNone(result["transcript"])
        self.assertEqual(result["media"]["video_stream_count"], 1)
        self.assertEqual(result["media"]["audio_stream_count"], 1)

    def test_ingest_requires_existing_workspace(self) -> None:
        with self.assertRaises(CreatorMediaError):
            ingest_local_media(self.sample_video, os.path.join(self.tmpdir, "missing"), transcribe=False)


if __name__ == "__main__":
    unittest.main()
