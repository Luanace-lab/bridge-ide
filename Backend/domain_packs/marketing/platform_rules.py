"""Marketing Domain Pack — Platform Rules.

Character limits, hashtag rules, tone guidelines per social platform.
"""

from __future__ import annotations

from typing import Any

PLATFORM_RULES: dict[str, dict[str, Any]] = {
    "twitter": {
        "character_limit": 280,
        "hashtag_max": 3,
        "media_required": False,
        "tone": "conversational, punchy, hook-first",
        "best_times_utc": ["13:00", "17:00"],
        "video_max_duration_s": 140,
    },
    "instagram": {
        "character_limit": 2200,
        "hashtag_max": 30,
        "media_required": True,
        "tone": "visual storytelling, emoji-ok, CTA in first line",
        "best_times_utc": ["11:00", "14:00", "19:00"],
        "video_max_duration_s": 90,  # Reels
    },
    "linkedin": {
        "character_limit": 3000,
        "hashtag_max": 5,
        "media_required": False,
        "tone": "professional, insight-driven, value-first",
        "best_times_utc": ["07:00", "12:00"],
        "video_max_duration_s": 600,
    },
    "tiktok": {
        "character_limit": 4000,
        "hashtag_max": 5,
        "media_required": True,
        "tone": "authentic, trend-aware, hook in 1st second",
        "best_times_utc": ["12:00", "19:00"],
        "video_max_duration_s": 180,
    },
    "youtube": {
        "character_limit": 5000,  # description
        "hashtag_max": 15,
        "media_required": True,
        "tone": "informative, searchable, keyword-rich title",
        "best_times_utc": ["14:00", "17:00"],
        "video_max_duration_s": 3600,
    },
    "facebook": {
        "character_limit": 63206,
        "hashtag_max": 5,
        "media_required": False,
        "tone": "community-oriented, shareable",
        "best_times_utc": ["09:00", "13:00"],
        "video_max_duration_s": 240,
    },
    "telegram": {
        "character_limit": 4096,
        "hashtag_max": 0,
        "media_required": False,
        "tone": "direct, informative",
        "best_times_utc": [],
        "video_max_duration_s": None,
    },
    "email": {
        "character_limit": None,
        "hashtag_max": 0,
        "media_required": False,
        "tone": "professional, personalized, clear CTA",
        "best_times_utc": ["06:00", "10:00"],
        "video_max_duration_s": None,
    },
}


def get_platform_rules(platform: str) -> dict[str, Any]:
    """Get rules for a platform."""
    return PLATFORM_RULES.get(platform.lower(), {})


def optimize_for_platform(body: str, platform: str) -> dict[str, Any]:
    """Basic platform optimization: truncate, add guidance."""
    rules = get_platform_rules(platform)
    if not rules:
        return {"body": body, "platform": platform, "optimized": False}

    char_limit = rules.get("character_limit")
    truncated = False
    optimized_body = body

    if char_limit and len(body) > char_limit:
        optimized_body = body[:char_limit - 3] + "..."
        truncated = True

    return {
        "body": optimized_body,
        "platform": platform,
        "optimized": True,
        "truncated": truncated,
        "character_limit": char_limit,
        "hashtag_max": rules.get("hashtag_max", 0),
        "tone_guidance": rules.get("tone", ""),
        "media_required": rules.get("media_required", False),
    }
