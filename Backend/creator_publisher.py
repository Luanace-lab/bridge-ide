"""Creator Publisher — Multi-Channel Publishing Dispatcher.

Sends clips to Bridge channels (Telegram, WhatsApp, Slack, Email)
via HTTP to the existing server endpoints. Respects approval gates.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Channel -> server endpoint mapping (Bridge internal channels)
_CHANNEL_ENDPOINTS = {
    "telegram": "/telegram/send",
    "whatsapp": "/whatsapp/send",
    "slack": "/slack/send",
    "email": "/email/send",
}

# Social platforms (direct API, handled by creator_social_publish.py)
_SOCIAL_PLATFORMS = {"youtube", "tiktok", "instagram", "facebook", "twitter", "linkedin"}

_SERVER_URL = os.environ.get("BRIDGE_SERVER_URL", "http://127.0.0.1:9111")


def publish_to_channel(
    channel_type: str,
    target: str,
    caption: str,
    media_path: str = "",
) -> dict[str, Any]:
    """Publish content to a single channel via Bridge server.

    Returns: {channel, target, status, response}
    Raises on connection failure.
    """
    # Route social platforms to creator_social_publish
    if channel_type in _SOCIAL_PLATFORMS:
        return _publish_social(channel_type, target, caption, media_path)

    if channel_type not in _CHANNEL_ENDPOINTS:
        all_channels = sorted(list(_CHANNEL_ENDPOINTS.keys()) + list(_SOCIAL_PLATFORMS))
        return {
            "channel": channel_type,
            "target": target,
            "status": "error",
            "error": f"Unknown channel: {channel_type}. Supported: {all_channels}",
        }

    endpoint = _CHANNEL_ENDPOINTS[channel_type]

    # Build payload per channel type
    if channel_type == "telegram":
        payload = {"to": target, "message": caption}
        if media_path and os.path.isfile(media_path):
            payload["media_path"] = media_path
    elif channel_type == "whatsapp":
        payload = {"to": target, "message": caption}
        if media_path and os.path.isfile(media_path):
            payload["media_path"] = media_path
    elif channel_type == "slack":
        payload = {"channel": target, "message": caption}
    elif channel_type == "email":
        payload = {"to": target, "subject": caption[:80], "body": caption}
    else:
        payload = {"to": target, "message": caption}

    try:
        from common import http_post_json, build_bridge_auth_headers

        headers = build_bridge_auth_headers(agent_id="creator_publisher")
        resp = http_post_json(f"{_SERVER_URL}{endpoint}", payload, timeout=30, headers=headers)
        return {
            "channel": channel_type,
            "target": target,
            "status": resp.get("status", "sent"),
            "response": resp,
        }
    except Exception as exc:
        return {
            "channel": channel_type,
            "target": target,
            "status": "error",
            "error": str(exc),
        }


def schedule_publish(
    channel_type: str,
    target: str,
    caption: str,
    schedule_iso: str,
    media_path: str = "",
) -> dict[str, Any]:
    """Schedule a publish action for a future time.

    Creates an automation via Bridge automation engine.
    """
    try:
        from common import http_post_json, build_bridge_auth_headers

        headers = build_bridge_auth_headers(agent_id="creator_publisher")

        automation_payload = {
            "name": f"creator_publish_{channel_type}_{schedule_iso}",
            "trigger": {
                "type": "schedule",
                "at": schedule_iso,
            },
            "action": {
                "type": "webhook",
                "url": f"{_SERVER_URL}{_CHANNEL_ENDPOINTS.get(channel_type, '/telegram/send')}",
                "payload": {
                    "to": target,
                    "message": caption,
                },
            },
            "one_shot": True,
        }

        resp = http_post_json(
            f"{_SERVER_URL}/automation/create",
            automation_payload,
            timeout=10,
            headers=headers,
        )
        return {
            "channel": channel_type,
            "target": target,
            "status": "scheduled",
            "schedule": schedule_iso,
            "automation_id": resp.get("automation_id", resp.get("id", "")),
        }
    except Exception as exc:
        return {
            "channel": channel_type,
            "target": target,
            "status": "error",
            "error": str(exc),
        }


def _publish_social(
    platform: str,
    target: str,
    caption: str,
    media_path: str,
) -> dict[str, Any]:
    """Route to creator_social_publish for direct social platform APIs."""
    try:
        from creator_social_publish import publish_social, is_platform_configured

        if not is_platform_configured(platform):
            return {
                "channel": platform,
                "target": target,
                "status": "error",
                "error": f"{platform} not configured. Store credentials in ~/.config/bridge/social_credentials/{platform}.json",
            }

        result = publish_social(
            platform=platform,
            video_path=media_path,
            title=caption[:100] if caption else "",
            caption=caption,
            description=caption,
            privacy="private",
        )
        return {
            "channel": platform,
            "target": target,
            "status": result.get("status", "error"),
            "response": result,
        }
    except ImportError:
        return {
            "channel": platform,
            "target": target,
            "status": "error",
            "error": "creator_social_publish module not available",
        }
    except Exception as exc:
        return {
            "channel": platform,
            "target": target,
            "status": "error",
            "error": str(exc),
        }


def publish_multi_channel(
    channels: list[dict[str, Any]],
    media_path: str = "",
) -> list[dict[str, Any]]:
    """Publish to multiple channels, return per-channel results."""
    results: list[dict[str, Any]] = []
    for ch in channels:
        channel_type = ch.get("type", "")
        target = ch.get("target", "")
        caption = ch.get("caption", "")
        schedule = ch.get("schedule")

        if schedule:
            result = schedule_publish(channel_type, target, caption, schedule, media_path)
        else:
            result = publish_to_channel(channel_type, target, caption, media_path)

        results.append(result)

    return results
