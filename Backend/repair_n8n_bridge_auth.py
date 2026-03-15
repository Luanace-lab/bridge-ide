#!/usr/bin/env python3
"""Repair active n8n workflows that write to strict-auth Bridge endpoints without auth headers."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import server


def _workflow_requires_bridge_auth_repair(workflow: dict[str, Any]) -> bool:
    repaired = server._inject_bridge_workflow_auth_headers(workflow)
    return repaired != workflow


def _iter_target_workflows(payload: dict[str, Any], *, active_only: bool = True) -> list[dict[str, Any]]:
    items = payload.get("data")
    workflows = items if isinstance(items, list) else []
    if not active_only:
        return [wf for wf in workflows if isinstance(wf, dict)]
    return [wf for wf in workflows if isinstance(wf, dict) and bool(wf.get("active"))]


def repair_workflows(*, limit: int = 250, active_only: bool = True, dry_run: bool = False) -> dict[str, Any]:
    status, payload = server._n8n_request("GET", "/workflows", params={"limit": limit})
    if status >= 400 or not isinstance(payload, dict):
        raise RuntimeError(
            (payload or {}).get("error", f"n8n workflow list failed (HTTP {status})")
            if isinstance(payload, dict)
            else f"n8n workflow list failed (HTTP {status})"
        )

    workflows = _iter_target_workflows(payload, active_only=active_only)
    result: dict[str, Any] = {
        "ok": True,
        "scanned": len(workflows),
        "repaired": [],
        "unchanged": [],
        "dry_run": dry_run,
    }

    for workflow in workflows:
        workflow_id = str(workflow.get("id", "")).strip()
        workflow_name = str(workflow.get("name", "")).strip() or workflow_id
        if not workflow_id:
            continue
        if not _workflow_requires_bridge_auth_repair(workflow):
            result["unchanged"].append({"id": workflow_id, "name": workflow_name})
            continue
        result["repaired"].append({"id": workflow_id, "name": workflow_name})
        if dry_run:
            continue
        server._update_workflow_in_n8n(
            workflow_id,
            workflow,
            workflow_name=workflow_name,
        )

    result["repaired_count"] = len(result["repaired"])
    result["unchanged_count"] = len(result["unchanged"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=250, help="Maximum workflows to scan")
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Also scan inactive workflows instead of only active ones",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report workflows that would be repaired",
    )
    args = parser.parse_args(argv)

    result = repair_workflows(
        limit=args.limit,
        active_only=not args.include_inactive,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
