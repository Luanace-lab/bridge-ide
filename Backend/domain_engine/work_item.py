"""Domain Engine — WorkItem: Universal work object for all verticals.

A WorkItem is the smallest operative unit in any domain:
- Marketing: Post, Caption, Newsletter, Ad Copy
- Legal: Clause, Memo, Contract Draft
- Finance: Report, Alert, Analysis Brief
- Support: Answer Template, KB Article
- DevOps: Incident Summary, Postmortem, Runbook

WorkItems have a universal lifecycle and domain-specific overlays.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

LIFECYCLE_STATES = [
    "draft",
    "generated",
    "optimized",
    "approved",
    "scheduled",
    "published",
    "observed",
    "archived",
]

VALID_TRANSITIONS = {
    "draft": ["generated", "approved", "archived"],
    "generated": ["optimized", "approved", "draft", "archived"],
    "optimized": ["approved", "draft", "archived"],
    "approved": ["scheduled", "published", "draft", "archived"],
    "scheduled": ["published", "approved", "archived"],
    "published": ["observed", "archived"],
    "observed": ["archived", "draft"],  # allow recycling
    "archived": ["draft"],  # allow reactivation
}


# ---------------------------------------------------------------------------
# WorkItem CRUD
# ---------------------------------------------------------------------------


def create_work_item(
    domain: str,
    item_type: str,
    title: str,
    workspace_dir: str,
    brief: str = "",
    body: str = "",
    owner: str = "",
    campaign_id: str = "",
    channel_targets: list[str] | None = None,
    schedule: str = "",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new WorkItem."""
    now = datetime.now(timezone.utc).isoformat()
    item_id = f"wi_{uuid.uuid4().hex[:12]}"

    item = {
        "item_id": item_id,
        "domain": domain,
        "type": item_type,
        "title": title,
        "brief": brief,
        "body": body,
        "status": "draft",
        "owner": owner,
        "source_refs": [],
        "campaign_id": campaign_id,
        "template_id": "",
        "channel_targets": channel_targets or [],
        "schedule": schedule,
        "approval": {"status": "pending", "reviewer": "", "approved_at": ""},
        "variants": [],
        "metrics": {},
        "tags": tags or [],
        "metadata": metadata or {},
        "overlay": overlay or {},
        "created_at": now,
        "updated_at": now,
    }

    # Persist
    item_dir = _item_dir(workspace_dir, item_id)
    os.makedirs(item_dir, exist_ok=True)
    _save_item(item, workspace_dir)

    return item


def save_work_item(item: dict[str, Any], workspace_dir: str) -> None:
    """Atomically persist a WorkItem."""
    _save_item(item, workspace_dir)


def load_work_item(item_id: str, workspace_dir: str) -> dict[str, Any] | None:
    """Load a WorkItem by ID."""
    path = os.path.join(_item_dir(workspace_dir, item_id), "item.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_work_items(
    workspace_dir: str,
    domain: str = "",
    status: str = "",
    campaign_id: str = "",
) -> list[dict[str, Any]]:
    """List WorkItems with optional filters."""
    items_root = os.path.join(workspace_dir, "work_items")
    if not os.path.isdir(items_root):
        return []
    results = []
    for entry in os.listdir(items_root):
        if not entry.startswith("wi_"):
            continue
        item = load_work_item(entry, workspace_dir)
        if item is None:
            continue
        if domain and item.get("domain") != domain:
            continue
        if status and item.get("status") != status:
            continue
        if campaign_id and item.get("campaign_id") != campaign_id:
            continue
        results.append(item)
    results.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    return results


def transition_work_item(
    item: dict[str, Any],
    new_status: str,
    workspace_dir: str,
) -> dict[str, Any]:
    """Transition a WorkItem to a new lifecycle state."""
    current = item.get("status", "draft")
    allowed = VALID_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise ValueError(f"Invalid transition: {current} → {new_status}. Allowed: {allowed}")
    item["status"] = new_status
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_item(item, workspace_dir)
    _append_event(item["item_id"], workspace_dir, "transition", {"from": current, "to": new_status})
    return item


def approve_work_item(
    item: dict[str, Any],
    reviewer: str,
    workspace_dir: str,
) -> dict[str, Any]:
    """Approve a WorkItem."""
    item["approval"] = {
        "status": "approved",
        "reviewer": reviewer,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    return transition_work_item(item, "approved", workspace_dir)


# ---------------------------------------------------------------------------
# Variants (A/B Testing)
# ---------------------------------------------------------------------------


def add_variant(
    item: dict[str, Any],
    variant_body: str,
    variant_label: str = "",
    workspace_dir: str = "",
) -> dict[str, Any]:
    """Add a variant to a WorkItem for A/B testing."""
    variant_id = f"var_{uuid.uuid4().hex[:8]}"
    variant = {
        "variant_id": variant_id,
        "label": variant_label or f"Variant {len(item['variants']) + 1}",
        "body": variant_body,
        "metrics": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    item["variants"].append(variant)
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    if workspace_dir:
        _save_item(item, workspace_dir)
    return item


# ---------------------------------------------------------------------------
# Metrics / Observation
# ---------------------------------------------------------------------------


def import_metrics(
    item: dict[str, Any],
    channel: str,
    metrics: dict[str, Any],
    period: str = "",
    workspace_dir: str = "",
) -> dict[str, Any]:
    """Import observation metrics for a WorkItem."""
    snapshot = {
        "channel": channel,
        "metrics": metrics,
        "period": period,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    if "observation_snapshots" not in item:
        item["observation_snapshots"] = []
    item["observation_snapshots"].append(snapshot)
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    if workspace_dir:
        _save_item(item, workspace_dir)
    _append_event(item["item_id"], workspace_dir, "metrics_imported", {"channel": channel, "period": period})
    return item


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def load_events(item_id: str, workspace_dir: str) -> list[dict[str, Any]]:
    """Load all events for a WorkItem."""
    path = os.path.join(_item_dir(workspace_dir, item_id), "events.jsonl")
    if not os.path.isfile(path):
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item_dir(workspace_dir: str, item_id: str) -> str:
    return os.path.join(workspace_dir, "work_items", item_id)


def _save_item(item: dict[str, Any], workspace_dir: str) -> None:
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    item_dir = _item_dir(workspace_dir, item["item_id"])
    os.makedirs(item_dir, exist_ok=True)
    path = os.path.join(item_dir, "item.json")
    _atomic_write_json(path, item)


def _append_event(item_id: str, workspace_dir: str, event_type: str, data: dict[str, Any] | None = None) -> None:
    if not workspace_dir:
        return
    item_dir = _item_dir(workspace_dir, item_id)
    os.makedirs(item_dir, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "data": data or {},
    }
    path = os.path.join(item_dir, "events.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _atomic_write_json(path: str, data: Any) -> None:
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n"
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
