"""Tests for creator setup — dependency check, credential validation, OAuth guides."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest


class TestCreatorSetup(unittest.TestCase):
    """Test setup check, credential validation, and OAuth guides."""

    def test_check_dependencies_finds_ffmpeg(self) -> None:
        from creator_setup import check_dependencies
        deps = check_dependencies()
        self.assertIn("ffmpeg", deps)
        self.assertTrue(deps["ffmpeg"]["installed"])
        self.assertTrue(deps["ffmpeg"]["required"])

    def test_check_dependencies_finds_faster_whisper(self) -> None:
        from creator_setup import check_dependencies
        deps = check_dependencies()
        self.assertIn("faster-whisper", deps)
        self.assertTrue(deps["faster-whisper"]["installed"])

    def test_check_credentials_empty(self) -> None:
        from creator_setup import check_credentials, CREDENTIALS_DIR
        import creator_setup
        orig = creator_setup.CREDENTIALS_DIR
        creator_setup.CREDENTIALS_DIR = "/tmp/nonexistent_creds_dir"
        try:
            creds = check_credentials()
            for platform in ("youtube", "tiktok", "instagram", "facebook", "twitter", "linkedin"):
                self.assertIn(platform, creds)
                self.assertFalse(creds[platform]["configured"])
        finally:
            creator_setup.CREDENTIALS_DIR = orig

    def test_check_credentials_with_stored_creds(self) -> None:
        from creator_setup import check_credentials
        import creator_setup
        tmpdir = tempfile.mkdtemp(prefix="cj_setup_creds_")
        orig = creator_setup.CREDENTIALS_DIR
        creator_setup.CREDENTIALS_DIR = tmpdir
        try:
            # Store YouTube creds
            yt_creds = {"client_id": "test_id", "client_secret": "test_secret"}
            with open(os.path.join(tmpdir, "youtube.json"), "w") as f:
                json.dump(yt_creds, f)

            creds = check_credentials()
            self.assertTrue(creds["youtube"]["configured"])
            self.assertFalse(creds["tiktok"]["configured"])
        finally:
            creator_setup.CREDENTIALS_DIR = orig
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_check_credentials_detects_missing_fields(self) -> None:
        from creator_setup import check_credentials
        import creator_setup
        tmpdir = tempfile.mkdtemp(prefix="cj_setup_creds_")
        orig = creator_setup.CREDENTIALS_DIR
        creator_setup.CREDENTIALS_DIR = tmpdir
        try:
            # Store incomplete Twitter creds
            tw_creds = {"api_key": "k"}  # missing api_secret, access_token, access_token_secret
            with open(os.path.join(tmpdir, "twitter.json"), "w") as f:
                json.dump(tw_creds, f)

            creds = check_credentials()
            self.assertFalse(creds["twitter"]["configured"])
            self.assertIn("api_secret", creds["twitter"]["missing_fields"])
        finally:
            creator_setup.CREDENTIALS_DIR = orig
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_check_all_returns_complete_status(self) -> None:
        from creator_setup import check_all
        status = check_all()
        self.assertIn("ready", status)
        self.assertIn("core_ready", status)
        self.assertIn("fully_configured", status)
        self.assertIn("feature_readiness", status)
        self.assertIn("limitations", status)
        self.assertIn("dependencies", status)
        self.assertIn("social_credentials", status)
        self.assertIn("checked_at", status)
        self.assertTrue(status["all_required_deps_ok"])  # ffmpeg, ffprobe, yt-dlp installed

    def test_oauth_guide_all_platforms(self) -> None:
        from creator_setup import get_oauth_guide, PLATFORMS
        for platform in PLATFORMS:
            guide = get_oauth_guide(platform)
            self.assertGreater(len(guide), 100)
            self.assertIn("json", guide.lower())  # all guides show JSON config

    def test_oauth_guide_unknown_platform(self) -> None:
        from creator_setup import get_oauth_guide
        guide = get_oauth_guide("snapchat")
        self.assertIn("Keine Anleitung", guide)

    def test_setup_http_status_endpoint(self) -> None:
        """GET /creator/setup/status returns setup status."""
        from handlers.creator import handle_get

        class MockHandler:
            def __init__(self) -> None:
                self.path = "/creator/setup/status"
                self.response_code = None
                self.response_body = None
            def _respond(self, code, body):
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_get(handler, "/creator/setup/status")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 200)
        self.assertIn("ready", handler.response_body)
        self.assertIn("feature_readiness", handler.response_body)
        self.assertIn("dependencies", handler.response_body)

    def test_setup_http_guide_endpoint(self) -> None:
        """GET /creator/setup/guide/youtube returns OAuth guide."""
        from handlers.creator import handle_get

        class MockHandler:
            def __init__(self) -> None:
                self.path = "/creator/setup/guide/youtube"
                self.response_code = None
                self.response_body = None
            def _respond(self, code, body):
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_get(handler, "/creator/setup/guide/youtube")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 200)
        self.assertIn("guide", handler.response_body)
        self.assertIn("console.cloud.google.com", handler.response_body["guide"])


if __name__ == "__main__":
    unittest.main()
