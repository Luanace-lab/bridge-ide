"""Marketing Domain Pack — Content Types.

Defines marketing-specific WorkItem types and their default configurations.
"""

from __future__ import annotations

from typing import Any

MARKETING_CONTENT_TYPES: dict[str, dict[str, Any]] = {
    "social_post": {
        "description": "Social media post (text + optional media)",
        "default_channels": ["instagram", "linkedin", "twitter"],
        "requires_media": False,
        "max_variants": 3,
    },
    "video_clip": {
        "description": "Short video clip for social platforms",
        "default_channels": ["tiktok", "instagram", "youtube"],
        "requires_media": True,
        "max_variants": 2,
    },
    "newsletter": {
        "description": "Email newsletter",
        "default_channels": ["email"],
        "requires_media": False,
        "max_variants": 2,
    },
    "blog_post": {
        "description": "Long-form blog article",
        "default_channels": [],
        "requires_media": False,
        "max_variants": 1,
    },
    "ad_copy": {
        "description": "Advertising copy for paid campaigns",
        "default_channels": ["facebook", "instagram"],
        "requires_media": True,
        "max_variants": 5,
    },
    "story": {
        "description": "Ephemeral story content (24h)",
        "default_channels": ["instagram", "facebook"],
        "requires_media": True,
        "max_variants": 1,
    },
    "thread": {
        "description": "Multi-post thread (Twitter/X style)",
        "default_channels": ["twitter"],
        "requires_media": False,
        "max_variants": 2,
    },
}


def get_content_type(type_name: str) -> dict[str, Any] | None:
    """Get marketing content type definition."""
    return MARKETING_CONTENT_TYPES.get(type_name)


def list_content_types() -> dict[str, dict[str, Any]]:
    """List all marketing content types."""
    return dict(MARKETING_CONTENT_TYPES)
