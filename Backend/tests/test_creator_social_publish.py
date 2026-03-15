"""Tests for creator_social_publish — social platform API integrations."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock


class TestCreatorSocialPublish(unittest.TestCase):
    """Test social platform publishing functions."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="cj_social_")
        self.creds_dir = os.path.join(self.tmpdir, "creds")
        os.makedirs(self.creds_dir, exist_ok=True)
        # Patch credentials dir
        import creator_social_publish
        self._orig_creds_dir = creator_social_publish.CREDENTIALS_DIR
        creator_social_publish.CREDENTIALS_DIR = self.creds_dir
        # Create a fake video file
        self.video_path = os.path.join(self.tmpdir, "clip.mp4")
        with open(self.video_path, "wb") as f:
            f.write(b"\x00" * 1024)

    def tearDown(self) -> None:
        import creator_social_publish
        creator_social_publish.CREDENTIALS_DIR = self._orig_creds_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _store_creds(self, platform: str, data: dict) -> None:
        path = os.path.join(self.creds_dir, f"{platform}.json")
        with open(path, "w") as f:
            json.dump(data, f)

    def test_no_credentials_returns_error(self) -> None:
        from creator_social_publish import publish_youtube
        result = publish_youtube(self.video_path, "Test Title")
        self.assertEqual(result["status"], "error")
        self.assertIn("No credentials", result["error"])

    def test_unknown_platform_returns_error(self) -> None:
        from creator_social_publish import publish_social
        result = publish_social("snapchat", self.video_path, title="Test")
        self.assertEqual(result["status"], "error")
        self.assertIn("Unknown platform", result["error"])

    def test_get_configured_platforms(self) -> None:
        from creator_social_publish import get_configured_platforms
        self.assertEqual(get_configured_platforms(), [])
        self._store_creds("youtube", {"access_token": "test"})
        self._store_creds("tiktok", {"access_token": "test"})
        platforms = get_configured_platforms()
        self.assertEqual(platforms, ["tiktok", "youtube"])

    def test_is_platform_configured(self) -> None:
        from creator_social_publish import is_platform_configured
        self.assertFalse(is_platform_configured("youtube"))
        self._store_creds("youtube", {"access_token": "test"})
        self.assertTrue(is_platform_configured("youtube"))

    def test_video_not_found_returns_error(self) -> None:
        from creator_social_publish import publish_youtube
        self._store_creds("youtube", {"access_token": "t", "client_id": "c", "client_secret": "s"})
        result = publish_youtube("/nonexistent/video.mp4", "Title")
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["error"])

    def test_tiktok_no_access_token_returns_error(self) -> None:
        from creator_social_publish import publish_tiktok
        self._store_creds("tiktok", {"client_id": "c"})
        result = publish_tiktok(self.video_path, "Title")
        self.assertEqual(result["status"], "error")
        self.assertIn("access_token", result["error"])

    def test_instagram_requires_video_url(self) -> None:
        from creator_social_publish import publish_instagram
        self._store_creds("instagram", {"access_token": "t", "ig_user_id": "123"})
        result = publish_instagram(self.video_path, "Caption")
        self.assertEqual(result["status"], "error")
        self.assertIn("video_url", result["error"])

    def test_publisher_routes_social_channels(self) -> None:
        """publish_to_channel routes 'youtube' to social publish."""
        from creator_publisher import publish_to_channel
        # Without credentials, should return error about credentials
        result = publish_to_channel("youtube", "", "Test Caption", self.video_path)
        self.assertEqual(result["channel"], "youtube")
        self.assertEqual(result["status"], "error")
        # Should mention credentials, not "Unknown channel"
        self.assertNotIn("Unknown channel", result.get("error", ""))

    def test_publisher_still_supports_bridge_channels(self) -> None:
        """Telegram, WhatsApp etc. still route to Bridge server."""
        from creator_publisher import publish_to_channel
        with patch("common.http_post_json") as mock_post:
            mock_post.return_value = {"status": "sent"}
            result = publish_to_channel("telegram", "@test", "Caption")
        self.assertEqual(result["channel"], "telegram")
        self.assertEqual(result["status"], "sent")

    def test_refresh_token_no_creds(self) -> None:
        from creator_social_publish import refresh_token
        result = refresh_token("youtube")
        self.assertFalse(result["refreshed"])
        self.assertIn("No credentials", result["error"])

    def test_refresh_token_twitter_not_supported(self) -> None:
        from creator_social_publish import refresh_token
        self._store_creds("twitter", {
            "api_key": "k", "api_secret": "s",
            "access_token": "t", "access_token_secret": "ts",
        })
        result = refresh_token("twitter")
        self.assertFalse(result["refreshed"])
        self.assertIn("long-lived", result["error"])

    def test_refresh_tiktok_missing_refresh_token(self) -> None:
        from creator_social_publish import refresh_token
        self._store_creds("tiktok", {"access_token": "t"})
        result = refresh_token("tiktok")
        self.assertFalse(result["refreshed"])
        self.assertIn("refresh_token", result["error"])

    def test_auto_retry_on_auth_failure(self) -> None:
        """publish_social retries after token refresh on 401."""
        from creator_social_publish import publish_social
        self._store_creds("youtube", {
            "client_id": "c", "client_secret": "s",
            "access_token": "old", "refresh_token": "r",
        })

        call_count = {"n": 0}

        def mock_publish(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"platform": "youtube", "status": "error", "error": "401 Unauthorized"}
            return {"platform": "youtube", "status": "published", "video_id": "abc"}

        with patch("creator_social_publish.publish_youtube", side_effect=mock_publish), \
             patch("creator_social_publish.refresh_token", return_value={"refreshed": True}):
            result = publish_social("youtube", self.video_path, title="Test")

        self.assertEqual(result["status"], "published")
        self.assertEqual(call_count["n"], 2)

    def test_all_six_platforms_registered(self) -> None:
        from creator_social_publish import SOCIAL_PLATFORMS
        self.assertIn("youtube", SOCIAL_PLATFORMS)
        self.assertIn("tiktok", SOCIAL_PLATFORMS)
        self.assertIn("instagram", SOCIAL_PLATFORMS)
        self.assertIn("facebook", SOCIAL_PLATFORMS)
        self.assertIn("twitter", SOCIAL_PLATFORMS)
        self.assertIn("linkedin", SOCIAL_PLATFORMS)
        self.assertEqual(len(SOCIAL_PLATFORMS), 6)

    def test_multi_channel_with_social(self) -> None:
        """publish_multi_channel handles mixed Bridge + social channels."""
        from creator_publisher import publish_multi_channel
        with patch("common.http_post_json") as mock_post:
            mock_post.return_value = {"status": "sent"}
            results = publish_multi_channel([
                {"type": "telegram", "target": "@test", "caption": "Cap1"},
                {"type": "youtube", "target": "", "caption": "Cap2"},
            ], media_path=self.video_path)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["channel"], "telegram")
        self.assertEqual(results[0]["status"], "sent")
        self.assertEqual(results[1]["channel"], "youtube")
        self.assertEqual(results[1]["status"], "error")  # no creds


if __name__ == "__main__":
    unittest.main()
