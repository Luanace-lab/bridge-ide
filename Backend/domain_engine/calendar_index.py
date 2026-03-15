"""Domain Engine — CalendarIndex: Time-based view over scheduled WorkItems.

Calendar is a VIEW, not Source of Truth.
It indexes WorkItems by date for quick lookup.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from domain_engine.work_item import list_work_items


def get_calendar(
    workspace_dir: str,
    start_date: str = "",
    end_date: str = "",
    domain: str = "",
    status: str = "",
    channel: str = "",
) -> list[dict[str, Any]]:
    """Get calendar entries (WorkItems with schedule) in a date range."""
    items = list_work_items(workspace_dir, domain=domain, status=status)

    entries = []
    for item in items:
        schedule = item.get("schedule", "")
        if not schedule:
            continue

        # Filter by date range
        if start_date and schedule < start_date:
            continue
        if end_date and schedule > end_date:
            continue

        # Filter by channel
        if channel and channel not in item.get("channel_targets", []):
            continue

        entries.append({
            "item_id": item["item_id"],
            "title": item.get("title", ""),
            "domain": item.get("domain", ""),
            "type": item.get("type", ""),
            "status": item.get("status", ""),
            "schedule": schedule,
            "channel_targets": item.get("channel_targets", []),
            "campaign_id": item.get("campaign_id", ""),
            "owner": item.get("owner", ""),
        })

    entries.sort(key=lambda e: e.get("schedule", ""))
    return entries
