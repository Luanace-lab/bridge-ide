"""Creator Campaign — Campaign objects, stages, performance tracking.

Campaigns organize Creator-Job artifacts into planned, approved,
and published multi-channel content series.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

VALID_CAMPAIGN_STATUSES = frozenset({
    "draft", "planned", "approved", "active", "completed", "paused",
})


def create_campaign(
    title: str,
    goal: str = "",
    workspace_dir: str = "",
    owner: str = "",
    target_platforms: list[str] | None = None,
    target_audience: str = "",
) -> dict[str, Any]:
    """Create a new campaign dict."""
    now = datetime.now(timezone.utc).isoformat()
    campaign_id = f"cc_{uuid.uuid4().hex[:12]}"

    return {
        "campaign_id": campaign_id,
        "title": title,
        "goal": goal,
        "status": "draft",
        "owner": owner,
        "workspace_dir": workspace_dir,
        "target_platforms": list(target_platforms) if target_platforms else [],
        "target_audience": target_audience,
        "asset_refs": [],
        "publish_plan": [],
        "calendar": [],
        "performance_snapshots": [],
        "next_actions": [],
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }


def save_campaign(campaign: dict[str, Any]) -> None:
    """Atomically persist a campaign."""
    campaign["updated_at"] = datetime.now(timezone.utc).isoformat()
    camp_dir = _campaign_dir(campaign["workspace_dir"], campaign["campaign_id"])
    os.makedirs(camp_dir, exist_ok=True)
    os.makedirs(os.path.join(camp_dir, "performance"), exist_ok=True)

    path = os.path.join(camp_dir, "campaign.json")
    _atomic_write_json(path, campaign)


def load_campaign(campaign_id: str, workspace_dir: str) -> dict[str, Any] | None:
    """Load a campaign. Returns None if not found."""
    path = os.path.join(_campaign_dir(workspace_dir, campaign_id), "campaign.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def list_campaigns(workspace_dir: str, status: str | None = None) -> list[dict[str, Any]]:
    """List campaigns in a workspace."""
    results: list[dict[str, Any]] = []
    root = os.path.join(workspace_dir, "creator_campaigns")
    if not os.path.isdir(root):
        return results
    for entry in os.listdir(root):
        if not entry.startswith("cc_"):
            continue
        camp = load_campaign(entry, workspace_dir)
        if camp is None:
            continue
        if status and camp.get("status") != status:
            continue
        results.append(camp)
    results.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return results


def append_campaign_event(
    campaign_id: str,
    workspace_dir: str,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Append event to campaign events.jsonl."""
    camp_dir = _campaign_dir(workspace_dir, campaign_id)
    os.makedirs(camp_dir, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "data": data or {},
    }
    events_path = os.path.join(camp_dir, "events.jsonl")
    with open(events_path, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_campaign_events(campaign_id: str, workspace_dir: str) -> list[dict[str, Any]]:
    """Load campaign events."""
    events_path = os.path.join(_campaign_dir(workspace_dir, campaign_id), "events.jsonl")
    if not os.path.isfile(events_path):
        return []
    events: list[dict[str, Any]] = []
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def add_asset_ref(
    campaign: dict[str, Any],
    job_id: str,
    artifact_path: str = "",
    preset_name: str = "",
) -> None:
    """Add an asset reference to a campaign."""
    campaign["asset_refs"].append({
        "job_id": job_id,
        "artifact_path": artifact_path,
        "preset_name": preset_name,
        "added_at": datetime.now(timezone.utc).isoformat(),
    })


def set_publish_plan(
    campaign: dict[str, Any],
    plan: list[dict[str, Any]],
) -> None:
    """Set the publish plan for a campaign."""
    campaign["publish_plan"] = list(plan)
    if campaign["status"] == "draft":
        campaign["status"] = "planned"


def approve_campaign(campaign: dict[str, Any]) -> None:
    """Approve a campaign for publishing."""
    if campaign["status"] not in ("planned", "draft"):
        return
    campaign["status"] = "approved"


def import_performance_snapshot(
    campaign: dict[str, Any],
    channel: str,
    metrics: dict[str, Any],
    period: str = "",
) -> None:
    """Import a performance snapshot (manual or external)."""
    snapshot = {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "metrics": metrics,
        "period": period,
    }
    campaign["performance_snapshots"].append(snapshot)

    # Persist to performance directory
    camp_dir = _campaign_dir(campaign["workspace_dir"], campaign["campaign_id"])
    perf_dir = os.path.join(camp_dir, "performance")
    os.makedirs(perf_dir, exist_ok=True)
    perf_path = os.path.join(perf_dir, f"snapshot_{len(campaign['performance_snapshots']):04d}.json")
    _atomic_write_json(perf_path, snapshot)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _campaign_dir(workspace_dir: str, campaign_id: str) -> str:
    return os.path.join(workspace_dir, "creator_campaigns", campaign_id)


def _atomic_write_json(path: str, data: Any) -> None:
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
