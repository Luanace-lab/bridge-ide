"""Domain Engine — Content Library: Reusable templates and evergreen content.

LibraryItems are templates that can be instantiated into WorkItems.
Domain-agnostic: Marketing templates, Legal clause templates, Finance report templates.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any


def create_library_item(
    domain: str,
    item_type: str,
    title: str,
    body: str,
    workspace_dir: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a reusable library template."""
    now = datetime.now(timezone.utc).isoformat()
    lib_id = f"lib_{uuid.uuid4().hex[:12]}"

    item = {
        "library_id": lib_id,
        "domain": domain,
        "type": item_type,
        "title": title,
        "body": body,
        "tags": tags or [],
        "metadata": metadata or {},
        "usage_count": 0,
        "created_at": now,
        "updated_at": now,
    }

    lib_dir = os.path.join(workspace_dir, "content_library")
    os.makedirs(lib_dir, exist_ok=True)
    _atomic_write_json(os.path.join(lib_dir, f"{lib_id}.json"), item)

    return item


def list_library_items(
    workspace_dir: str,
    domain: str = "",
    item_type: str = "",
) -> list[dict[str, Any]]:
    """List library items."""
    lib_dir = os.path.join(workspace_dir, "content_library")
    if not os.path.isdir(lib_dir):
        return []
    results = []
    for fname in os.listdir(lib_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(lib_dir, fname), encoding="utf-8") as f:
                item = json.load(f)
            if domain and item.get("domain") != domain:
                continue
            if item_type and item.get("type") != item_type:
                continue
            results.append(item)
        except (json.JSONDecodeError, OSError):
            continue
    return results


def instantiate_library_item(
    library_id: str,
    workspace_dir: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new WorkItem from a library template."""
    from domain_engine.work_item import create_work_item

    lib_dir = os.path.join(workspace_dir, "content_library")
    path = os.path.join(lib_dir, f"{library_id}.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Library item not found: {library_id}")

    with open(path, encoding="utf-8") as f:
        template = json.load(f)

    # Increment usage
    template["usage_count"] = template.get("usage_count", 0) + 1
    template["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(path, template)

    # Merge overrides
    params = {
        "domain": template.get("domain", ""),
        "item_type": template.get("type", ""),
        "title": template.get("title", ""),
        "body": template.get("body", ""),
        "workspace_dir": workspace_dir,
        "tags": list(template.get("tags", [])),
        "metadata": {"template_id": library_id},
    }
    if overrides:
        for k, v in overrides.items():
            if k in params and v:
                params[k] = v

    return create_work_item(**params)


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
