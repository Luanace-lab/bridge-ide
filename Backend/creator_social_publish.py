"""Creator Social Publish — Direct Social Platform API Integrations.

Supports: YouTube, TikTok, Instagram, Facebook, X/Twitter, LinkedIn.
Each platform uses its official API with OAuth credentials stored locally.

Credential storage: ~/.config/bridge/social_credentials/{platform}.json
OAuth tokens are refreshed automatically where possible.

This module does NOT import from server.py or bridge_mcp.py.
It is called by creator_publisher.py as an additional channel type.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CREDENTIALS_DIR = os.path.join(
    os.environ.get("HOME", "/tmp"),
    ".config", "bridge", "social_credentials",
)

# ---------------------------------------------------------------------------
# Credential Management
# ---------------------------------------------------------------------------


def _load_credentials(platform: str) -> dict[str, Any] | None:
    """Load OAuth credentials for a platform."""
    path = os.path.join(CREDENTIALS_DIR, f"{platform}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_credentials(platform: str, creds: dict[str, Any]) -> None:
    """Save OAuth credentials for a platform."""
    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    path = os.path.join(CREDENTIALS_DIR, f"{platform}.json")
    with open(path, "w") as f:
        json.dump(creds, f, indent=2, ensure_ascii=False)
    os.chmod(path, 0o600)


def get_configured_platforms() -> list[str]:
    """Return list of platforms with stored credentials."""
    if not os.path.isdir(CREDENTIALS_DIR):
        return []
    platforms = []
    for fname in os.listdir(CREDENTIALS_DIR):
        if fname.endswith(".json"):
            platforms.append(fname[:-5])
    return sorted(platforms)


def is_platform_configured(platform: str) -> bool:
    """Check if a platform has stored credentials."""
    return _load_credentials(platform) is not None


# ---------------------------------------------------------------------------
# Token Refresh
# ---------------------------------------------------------------------------


def refresh_token(platform: str) -> dict[str, Any]:
    """Attempt to refresh OAuth token for a platform.

    Returns: {refreshed: bool, error: str | None}
    Saves updated credentials on success.
    """
    creds = _load_credentials(platform)
    if not creds:
        return {"refreshed": False, "error": "No credentials found"}

    try:
        if platform == "youtube":
            return _refresh_youtube(creds)
        elif platform == "tiktok":
            return _refresh_tiktok(creds)
        elif platform in ("instagram", "facebook"):
            return _refresh_facebook_ig(platform, creds)
        elif platform == "linkedin":
            return _refresh_linkedin(creds)
        elif platform == "twitter":
            return {"refreshed": False, "error": "Twitter uses long-lived tokens. Re-authenticate manually if expired."}
        else:
            return {"refreshed": False, "error": f"No refresh logic for {platform}"}
    except Exception as exc:
        return {"refreshed": False, "error": str(exc)}


def _refresh_youtube(creds: dict[str, Any]) -> dict[str, Any]:
    """Refresh YouTube OAuth token via Google token endpoint."""
    refresh_tok = creds.get("refresh_token", "")
    client_id = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")
    if not refresh_tok or not client_id or not client_secret:
        return {"refreshed": False, "error": "Missing refresh_token, client_id, or client_secret"}

    try:
        import httpx
    except ImportError:
        import requests as httpx  # type: ignore[no-redef]

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    data = resp.json() if hasattr(resp, 'json') and callable(resp.json) else json.loads(resp.text)
    new_token = data.get("access_token")
    if not new_token:
        return {"refreshed": False, "error": f"Refresh failed: {data}"}

    creds["access_token"] = new_token
    if data.get("expires_in"):
        from datetime import datetime, timezone, timedelta
        creds["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])).isoformat()
    _save_credentials("youtube", creds)
    return {"refreshed": True}


def _refresh_tiktok(creds: dict[str, Any]) -> dict[str, Any]:
    """Refresh TikTok OAuth token."""
    refresh_tok = creds.get("refresh_token", "")
    client_key = creds.get("client_key", creds.get("client_id", ""))
    client_secret = creds.get("client_secret", "")
    if not refresh_tok:
        return {"refreshed": False, "error": "Missing refresh_token"}

    try:
        import httpx
    except ImportError:
        import requests as httpx  # type: ignore[no-redef]

    resp = httpx.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
            "client_key": client_key,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    data = resp.json() if hasattr(resp, 'json') and callable(resp.json) else json.loads(resp.text)
    new_token = data.get("access_token")
    if not new_token:
        return {"refreshed": False, "error": f"Refresh failed: {data}"}

    creds["access_token"] = new_token
    if data.get("refresh_token"):
        creds["refresh_token"] = data["refresh_token"]
    if data.get("expires_in"):
        from datetime import datetime, timezone, timedelta
        creds["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])).isoformat()
    _save_credentials("tiktok", creds)
    return {"refreshed": True}


def _refresh_facebook_ig(platform: str, creds: dict[str, Any]) -> dict[str, Any]:
    """Exchange short-lived token for long-lived token (Facebook/Instagram)."""
    token = creds.get("access_token") or creds.get("page_access_token", "")
    if not token:
        return {"refreshed": False, "error": "No access_token found"}

    try:
        import httpx
    except ImportError:
        import requests as httpx  # type: ignore[no-redef]

    # Long-lived token exchange
    resp = httpx.get(
        "https://graph.facebook.com/v22.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": creds.get("app_id", creds.get("client_id", "")),
            "client_secret": creds.get("app_secret", creds.get("client_secret", "")),
            "fb_exchange_token": token,
        },
        timeout=15,
    )
    data = resp.json() if hasattr(resp, 'json') and callable(resp.json) else json.loads(resp.text)
    new_token = data.get("access_token")
    if not new_token:
        return {"refreshed": False, "error": f"Token exchange failed: {data}"}

    if platform == "facebook":
        creds["page_access_token"] = new_token
    else:
        creds["access_token"] = new_token
    if data.get("expires_in"):
        from datetime import datetime, timezone, timedelta
        creds["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])).isoformat()
    _save_credentials(platform, creds)
    return {"refreshed": True}


def _refresh_linkedin(creds: dict[str, Any]) -> dict[str, Any]:
    """Refresh LinkedIn OAuth token."""
    refresh_tok = creds.get("refresh_token", "")
    client_id = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")
    if not refresh_tok:
        return {"refreshed": False, "error": "Missing refresh_token"}

    try:
        import httpx
    except ImportError:
        import requests as httpx  # type: ignore[no-redef]

    resp = httpx.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    data = resp.json() if hasattr(resp, 'json') and callable(resp.json) else json.loads(resp.text)
    new_token = data.get("access_token")
    if not new_token:
        return {"refreshed": False, "error": f"Refresh failed: {data}"}

    creds["access_token"] = new_token
    if data.get("refresh_token"):
        creds["refresh_token"] = data["refresh_token"]
    if data.get("expires_in"):
        from datetime import datetime, timezone, timedelta
        creds["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])).isoformat()
    _save_credentials("linkedin", creds)
    return {"refreshed": True}


# ---------------------------------------------------------------------------
# YouTube — Data API v3
# ---------------------------------------------------------------------------


def publish_youtube(
    video_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "private",
    category_id: str = "22",
) -> dict[str, Any]:
    """Upload video to YouTube via Data API v3 resumable upload.

    Requires: pip install google-api-python-client google-auth-oauthlib
    Credentials: ~/.config/bridge/social_credentials/youtube.json
                 (client_secrets.json from Google Cloud Console)

    Args:
        privacy: 'private', 'unlisted', or 'public'
        category_id: '22' = People & Blogs (default)
    """
    creds = _load_credentials("youtube")
    if not creds:
        return _error("youtube", "No credentials. Run: bridge_creator_social_setup youtube")

    if not os.path.isfile(video_path):
        return _error("youtube", f"Video not found: {video_path}")

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return _error("youtube", "Missing: pip install google-api-python-client google-auth-oauthlib")

    try:
        oauth_creds = Credentials(
            token=creds.get("access_token"),
            refresh_token=creds.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds.get("client_id"),
            client_secret=creds.get("client_secret"),
        )

        youtube = build("youtube", "v3", credentials=oauth_creds)

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags or [],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info("YouTube upload %d%%", int(status.progress() * 100))

        video_id = response.get("id", "")
        return {
            "platform": "youtube",
            "status": "published",
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}" if video_id else "",
            "privacy": privacy,
        }

    except Exception as exc:
        return _error("youtube", str(exc))


# ---------------------------------------------------------------------------
# TikTok — Content Posting API
# ---------------------------------------------------------------------------


def publish_tiktok(
    video_path: str,
    title: str = "",
    privacy: str = "PUBLIC_TO_EVERYONE",
) -> dict[str, Any]:
    """Upload video to TikTok via Content Posting API.

    Requires: pip install python-tiktok (or direct HTTP)
    Credentials: ~/.config/bridge/social_credentials/tiktok.json
    """
    creds = _load_credentials("tiktok")
    if not creds:
        return _error("tiktok", "No credentials. Run: bridge_creator_social_setup tiktok")

    if not os.path.isfile(video_path):
        return _error("tiktok", f"Video not found: {video_path}")

    try:
        import httpx
    except ImportError:
        try:
            import requests as httpx  # type: ignore[no-redef]
        except ImportError:
            return _error("tiktok", "Missing: pip install httpx")

    access_token = creds.get("access_token", "")
    if not access_token:
        return _error("tiktok", "No access_token in credentials")

    base_url = "https://open.tiktokapis.com/v2"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    try:
        # Step 1: Initialize upload
        file_size = os.path.getsize(video_path)
        init_payload = {
            "post_info": {
                "title": title[:150] if title else "",
                "privacy_level": privacy,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": min(file_size, 10_000_000),
                "total_chunk_count": max(1, (file_size + 9_999_999) // 10_000_000),
            },
        }

        resp = httpx.post(
            f"{base_url}/post/publish/video/init/",
            headers=headers,
            json=init_payload,
            timeout=30,
        )
        init_data = resp.json() if hasattr(resp, 'json') and callable(resp.json) else json.loads(resp.text)

        if init_data.get("error", {}).get("code") not in (None, "ok", ""):
            return _error("tiktok", f"Init failed: {init_data}")

        publish_id = init_data.get("data", {}).get("publish_id", "")
        upload_url = init_data.get("data", {}).get("upload_url", "")

        if not upload_url:
            return _error("tiktok", f"No upload_url in response: {init_data}")

        # Step 2: Upload file chunks
        chunk_size = min(file_size, 10_000_000)
        with open(video_path, "rb") as f:
            offset = 0
            while offset < file_size:
                chunk = f.read(chunk_size)
                end = offset + len(chunk) - 1
                put_headers = {
                    "Content-Range": f"bytes {offset}-{end}/{file_size}",
                    "Content-Type": "video/mp4",
                }
                httpx.put(upload_url, headers=put_headers, content=chunk, timeout=120)
                offset += len(chunk)

        # Step 3: Poll for status
        status_url = f"{base_url}/post/publish/status/fetch/"
        for _ in range(60):
            time.sleep(5)
            status_resp = httpx.post(
                status_url,
                headers=headers,
                json={"publish_id": publish_id},
                timeout=10,
            )
            status_data = status_resp.json() if hasattr(status_resp, 'json') and callable(status_resp.json) else json.loads(status_resp.text)
            pub_status = status_data.get("data", {}).get("status", "")
            if pub_status == "PUBLISH_COMPLETE":
                return {
                    "platform": "tiktok",
                    "status": "published",
                    "publish_id": publish_id,
                }
            if pub_status in ("FAILED", "PUBLISH_FAILED"):
                return _error("tiktok", f"Publish failed: {status_data}")

        return _error("tiktok", "Publish timed out after 300s")

    except Exception as exc:
        return _error("tiktok", str(exc))


# ---------------------------------------------------------------------------
# Instagram — Graph API (Reels)
# ---------------------------------------------------------------------------


def publish_instagram(
    video_path: str,
    caption: str = "",
    video_url: str = "",
) -> dict[str, Any]:
    """Upload Reel to Instagram via Graph API.

    The video must be accessible via a public URL (video_url) OR
    uploaded to a temporary host. Local file upload is not directly
    supported by the Instagram Graph API — the API requires a URL.

    Credentials: ~/.config/bridge/social_credentials/instagram.json
    """
    creds = _load_credentials("instagram")
    if not creds:
        return _error("instagram", "No credentials. Run: bridge_creator_social_setup instagram")

    access_token = creds.get("access_token", "")
    ig_user_id = creds.get("ig_user_id", "")
    if not access_token or not ig_user_id:
        return _error("instagram", "Missing access_token or ig_user_id in credentials")

    if not video_url and not os.path.isfile(video_path):
        return _error("instagram", "Either video_url or valid video_path required")

    try:
        import httpx
    except ImportError:
        try:
            import requests as httpx  # type: ignore[no-redef]
        except ImportError:
            return _error("instagram", "Missing: pip install httpx")

    api_base = "https://graph.facebook.com/v22.0"

    try:
        # Step 1: Create media container
        container_payload = {
            "media_type": "REELS",
            "caption": caption,
            "access_token": access_token,
        }
        if video_url:
            container_payload["video_url"] = video_url
        else:
            return _error("instagram", "Instagram Graph API requires a public video_url. Local file upload needs a temporary host.")

        resp = httpx.post(
            f"{api_base}/{ig_user_id}/media",
            data=container_payload,
            timeout=30,
        )
        container_data = resp.json() if hasattr(resp, 'json') and callable(resp.json) else json.loads(resp.text)
        container_id = container_data.get("id", "")
        if not container_id:
            return _error("instagram", f"Container creation failed: {container_data}")

        # Step 2: Wait for container to be ready
        for _ in range(60):
            time.sleep(5)
            status_resp = httpx.get(
                f"{api_base}/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
                timeout=10,
            )
            status_data = status_resp.json() if hasattr(status_resp, 'json') and callable(status_resp.json) else json.loads(status_resp.text)
            if status_data.get("status_code") == "FINISHED":
                break
            if status_data.get("status_code") == "ERROR":
                return _error("instagram", f"Container processing failed: {status_data}")
        else:
            return _error("instagram", "Container processing timed out after 300s")

        # Step 3: Publish
        pub_resp = httpx.post(
            f"{api_base}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
            timeout=30,
        )
        pub_data = pub_resp.json() if hasattr(pub_resp, 'json') and callable(pub_resp.json) else json.loads(pub_resp.text)
        media_id = pub_data.get("id", "")
        if not media_id:
            return _error("instagram", f"Publish failed: {pub_data}")

        return {
            "platform": "instagram",
            "status": "published",
            "media_id": media_id,
        }

    except Exception as exc:
        return _error("instagram", str(exc))


# ---------------------------------------------------------------------------
# Facebook Pages — Graph API (Video)
# ---------------------------------------------------------------------------


def publish_facebook(
    video_path: str,
    description: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Upload video to Facebook Page via Graph API.

    Credentials: ~/.config/bridge/social_credentials/facebook.json
    """
    creds = _load_credentials("facebook")
    if not creds:
        return _error("facebook", "No credentials. Run: bridge_creator_social_setup facebook")

    access_token = creds.get("page_access_token", "")
    page_id = creds.get("page_id", "")
    if not access_token or not page_id:
        return _error("facebook", "Missing page_access_token or page_id in credentials")

    if not os.path.isfile(video_path):
        return _error("facebook", f"Video not found: {video_path}")

    try:
        import httpx
    except ImportError:
        try:
            import requests as httpx  # type: ignore[no-redef]
        except ImportError:
            return _error("facebook", "Missing: pip install httpx")

    try:
        with open(video_path, "rb") as f:
            resp = httpx.post(
                f"https://graph-video.facebook.com/v22.0/{page_id}/videos",
                data={
                    "description": description,
                    "title": title,
                    "access_token": access_token,
                },
                files={"source": (os.path.basename(video_path), f, "video/mp4")},
                timeout=300,
            )
        data = resp.json() if hasattr(resp, 'json') and callable(resp.json) else json.loads(resp.text)
        video_id = data.get("id", "")
        if not video_id:
            return _error("facebook", f"Upload failed: {data}")

        return {
            "platform": "facebook",
            "status": "published",
            "video_id": video_id,
        }

    except Exception as exc:
        return _error("facebook", str(exc))


# ---------------------------------------------------------------------------
# X/Twitter — API v2
# ---------------------------------------------------------------------------


def publish_twitter(
    video_path: str,
    text: str = "",
) -> dict[str, Any]:
    """Upload video and post tweet via X API v2.

    Requires: pip install tweepy
    Credentials: ~/.config/bridge/social_credentials/twitter.json
    """
    creds = _load_credentials("twitter")
    if not creds:
        return _error("twitter", "No credentials. Run: bridge_creator_social_setup twitter")

    if not os.path.isfile(video_path):
        return _error("twitter", f"Video not found: {video_path}")

    try:
        import tweepy
    except ImportError:
        return _error("twitter", "Missing: pip install tweepy")

    try:
        # tweepy v2 with OAuth 2.0
        client = tweepy.Client(
            bearer_token=creds.get("bearer_token"),
            consumer_key=creds.get("api_key"),
            consumer_secret=creds.get("api_secret"),
            access_token=creds.get("access_token"),
            access_token_secret=creds.get("access_token_secret"),
        )

        # Media upload via v1.1 (still required for media)
        auth = tweepy.OAuth1UserHandler(
            creds.get("api_key", ""),
            creds.get("api_secret", ""),
            creds.get("access_token", ""),
            creds.get("access_token_secret", ""),
        )
        api_v1 = tweepy.API(auth)
        media = api_v1.media_upload(video_path, media_category="tweet_video")

        # Wait for processing
        if hasattr(media, "processing_info"):
            while True:
                info = media.processing_info
                if not info:
                    break
                state = info.get("state", "")
                if state == "succeeded":
                    break
                if state == "failed":
                    return _error("twitter", f"Media processing failed: {info}")
                wait = info.get("check_after_secs", 5)
                time.sleep(wait)
                media = api_v1.get_media_upload_status(media.media_id)

        # Post tweet
        response = client.create_tweet(text=text, media_ids=[media.media_id])
        tweet_id = response.data.get("id", "") if response.data else ""

        return {
            "platform": "twitter",
            "status": "published",
            "tweet_id": tweet_id,
            "media_id": str(media.media_id),
        }

    except Exception as exc:
        return _error("twitter", str(exc))


# ---------------------------------------------------------------------------
# LinkedIn — Community Management API
# ---------------------------------------------------------------------------


def publish_linkedin(
    video_path: str,
    text: str = "",
) -> dict[str, Any]:
    """Upload video to LinkedIn via Community Management API.

    Credentials: ~/.config/bridge/social_credentials/linkedin.json
    """
    creds = _load_credentials("linkedin")
    if not creds:
        return _error("linkedin", "No credentials. Run: bridge_creator_social_setup linkedin")

    if not os.path.isfile(video_path):
        return _error("linkedin", f"Video not found: {video_path}")

    access_token = creds.get("access_token", "")
    person_urn = creds.get("person_urn", "")  # urn:li:person:{id}
    if not access_token or not person_urn:
        return _error("linkedin", "Missing access_token or person_urn")

    try:
        import httpx
    except ImportError:
        try:
            import requests as httpx  # type: ignore[no-redef]
        except ImportError:
            return _error("linkedin", "Missing: pip install httpx")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": "202401",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    try:
        # Step 1: Initialize video upload
        file_size = os.path.getsize(video_path)
        init_resp = httpx.post(
            "https://api.linkedin.com/rest/videos",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "initializeUploadRequest": {
                    "owner": person_urn,
                    "fileSizeBytes": file_size,
                },
            },
            timeout=30,
        )
        init_data = init_resp.json() if hasattr(init_resp, 'json') and callable(init_resp.json) else json.loads(init_resp.text)
        upload_url = init_data.get("value", {}).get("uploadInstructions", [{}])[0].get("uploadUrl", "")
        video_urn = init_data.get("value", {}).get("video", "")

        if not upload_url or not video_urn:
            return _error("linkedin", f"Init failed: {init_data}")

        # Step 2: Upload video (PUT without auth header per LinkedIn docs)
        with open(video_path, "rb") as f:
            httpx.put(upload_url, content=f.read(), timeout=300)

        # Step 3: Create post with video
        post_resp = httpx.post(
            "https://api.linkedin.com/rest/posts",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "author": person_urn,
                "commentary": text,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                },
                "content": {
                    "media": {
                        "id": video_urn,
                    },
                },
                "lifecycleState": "PUBLISHED",
            },
            timeout=30,
        )

        if post_resp.status_code in (200, 201):
            post_id = post_resp.headers.get("x-restli-id", "")
            return {
                "platform": "linkedin",
                "status": "published",
                "post_id": post_id,
                "video_urn": video_urn,
            }
        else:
            post_data = post_resp.json() if hasattr(post_resp, 'json') and callable(post_resp.json) else json.loads(post_resp.text)
            return _error("linkedin", f"Post failed ({post_resp.status_code}): {post_data}")

    except Exception as exc:
        return _error("linkedin", str(exc))


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------

SOCIAL_PLATFORMS = {
    "youtube": publish_youtube,
    "tiktok": publish_tiktok,
    "instagram": publish_instagram,
    "facebook": publish_facebook,
    "twitter": publish_twitter,
    "linkedin": publish_linkedin,
}


def publish_social(
    platform: str,
    video_path: str,
    title: str = "",
    caption: str = "",
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "private",
    video_url: str = "",
) -> dict[str, Any]:
    """Unified social publish dispatcher with auto-retry on auth failure.

    On 401/403: attempts token refresh, then retries once.
    """
    fn = SOCIAL_PLATFORMS.get(platform)
    if fn is None:
        return _error(platform, f"Unknown platform: {platform}. Supported: {list(SOCIAL_PLATFORMS.keys())}")

    def _do_publish() -> dict[str, Any]:
        if platform == "youtube":
            return publish_youtube(video_path, title=title, description=description, tags=tags, privacy=privacy)
        elif platform == "tiktok":
            return publish_tiktok(video_path, title=title, privacy="PUBLIC_TO_EVERYONE" if privacy == "public" else "SELF_ONLY")
        elif platform == "instagram":
            return publish_instagram(video_path, caption=caption or title, video_url=video_url)
        elif platform == "facebook":
            return publish_facebook(video_path, description=caption or description, title=title)
        elif platform == "twitter":
            return publish_twitter(video_path, text=caption or title)
        elif platform == "linkedin":
            return publish_linkedin(video_path, text=caption or title)
        else:
            return _error(platform, f"No handler for {platform}")

    # Attempt 1
    result = _do_publish()

    # Auto-retry on auth failure
    if result.get("status") == "error":
        err = result.get("error", "")
        if any(code in err for code in ("401", "403", "Unauthorized", "Forbidden", "expired", "invalid_token")):
            logger.info("Auth failure for %s, attempting token refresh", platform)
            refresh_result = refresh_token(platform)
            if refresh_result.get("refreshed"):
                logger.info("Token refreshed for %s, retrying publish", platform)
                result = _do_publish()
                if result.get("status") != "error":
                    result["token_refreshed"] = True

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(platform: str, msg: str) -> dict[str, Any]:
    """Standard error response."""
    logger.error("Social publish %s: %s", platform, msg)
    return {"platform": platform, "status": "error", "error": msg}
