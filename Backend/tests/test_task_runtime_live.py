from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest


API_BASE = os.environ.get("BRIDGE_API_BASE", "http://127.0.0.1:9111")

if os.environ.get("BRIDGE_RUN_LIVE_TESTS") != "1":
    pytestmark = pytest.mark.skip(
        reason="manual live task tests; set BRIDGE_RUN_LIVE_TESTS=1 to enable"
    )


def _request(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    agent_id: str | None = None,
    timeout: int = 10,
) -> tuple[int, dict | str | None]:
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if agent_id:
        headers["X-Bridge-Agent"] = agent_id
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return exc.code, raw
    except Exception as exc:  # pragma: no cover - live test helper
        return 0, str(exc)


def _create_task(*, title: str, created_by: str, assigned_to: str | None = None) -> str:
    payload = {
        "type": "general",
        "title": title,
        "description": title,
        "created_by": created_by,
    }
    if assigned_to is not None:
        payload["assigned_to"] = assigned_to
    status, data = _request("POST", "/task/create", payload, agent_id=created_by)
    assert status == 201, data
    assert isinstance(data, dict), data
    return str(data["task_id"])


def _fail_task(task_id: str, *, actor: str, error: str = "cleanup") -> None:
    _request("POST", f"/task/{task_id}/fail", {"error": error}, agent_id=actor)


def _get_task(task_id: str) -> dict:
    status, data = _request("GET", f"/task/{task_id}")
    assert status == 200, data
    assert isinstance(data, dict), data
    task = data.get("task")
    assert isinstance(task, dict), data
    return task


def test_direct_fail_of_created_task_does_not_increment_retry_count() -> None:
    actor = f"rt_retry_actor_{uuid.uuid4().hex[:8]}"
    task_id = _create_task(
        title=f"rt retry semantics {uuid.uuid4().hex[:8]}",
        created_by=actor,
    )

    status, data = _request(
        "POST",
        f"/task/{task_id}/fail",
        {"error": "cancelled before claim"},
        agent_id=actor,
    )
    assert status == 200, data

    task = _get_task(task_id)
    assert task["state"] == "failed"
    assert task["retry_count"] == 0, task


def test_board_view_respects_limit_for_filtered_query() -> None:
    creator = f"rt_board_creator_{uuid.uuid4().hex[:8]}"
    assignee = f"rt_board_assignee_{uuid.uuid4().hex[:8]}"
    task_ids: list[str] = []
    try:
        for idx in range(3):
            task_ids.append(
                _create_task(
                    title=f"rt board pagination {idx} {uuid.uuid4().hex[:8]}",
                    created_by=creator,
                    assigned_to=assignee,
                )
            )

        query = urllib.parse.urlencode(
            {
                "view": "board",
                "agent_id": assignee,
                "state": "created",
                "limit": 1,
            }
        )
        status, data = _request("GET", f"/task/queue?{query}")
        assert status == 200, data
        assert isinstance(data, dict), data

        board = data["board"]
        returned = sum(len(items) for items in board.values())
        assert returned <= 1, data
    finally:
        for task_id in task_ids:
            _fail_task(task_id, actor=creator)


def test_claim_rejects_when_agent_exceeds_capacity() -> None:
    creator = f"rt_capacity_creator_{uuid.uuid4().hex[:8]}"
    agent = f"rt_capacity_agent_{uuid.uuid4().hex[:8]}"
    task_ids: list[str] = []
    claimed_ids: list[str] = []
    try:
        for idx in range(4):
            task_ids.append(
                _create_task(
                    title=f"rt capacity probe {idx} {uuid.uuid4().hex[:8]}",
                    created_by=creator,
                )
            )

        for task_id in task_ids[:3]:
            status, data = _request("POST", f"/task/{task_id}/claim", {}, agent_id=agent)
            assert status == 200, data
            claimed_ids.append(task_id)
            status, data = _request("POST", f"/task/{task_id}/ack", {}, agent_id=agent)
            assert status == 200, data

        status, data = _request("POST", f"/task/{task_ids[3]}/claim", {}, agent_id=agent)
        assert status == 429, data
    finally:
        for task_id in task_ids:
            actor = agent if task_id in claimed_ids else creator
            _fail_task(task_id, actor=actor)
