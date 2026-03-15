from __future__ import annotations

import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.request
import uuid

import pytest


API_BASE = os.environ.get("BRIDGE_API_BASE", "http://127.0.0.1:9111")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK_WAL_LOG = os.path.join(REPO_ROOT, "task_transition_wal.jsonl")

if os.environ.get("BRIDGE_RUN_LIVE_TESTS") != "1":
    pytestmark = pytest.mark.skip(
        reason="manual live task scaling tests; set BRIDGE_RUN_LIVE_TESTS=1 to enable"
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
    except Exception as exc:  # pragma: no cover - live helper
        return 0, str(exc)


def _register_agent(agent_id: str, capabilities: list[str], role: str = "worker") -> None:
    status, data = _request(
        "POST",
        "/register",
        {"agent_id": agent_id, "role": role, "capabilities": capabilities},
        agent_id=agent_id,
    )
    assert status == 200, data


def _drain_messages(agent_id: str) -> None:
    _request("GET", f"/receive/{agent_id}?limit=100", agent_id=agent_id)


def _create_task(
    *,
    title: str,
    created_by: str,
    assigned_to: str | None = None,
    required_capabilities: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> tuple[int, dict | str | None]:
    payload: dict[str, object] = {
        "type": "general",
        "title": title,
        "description": title,
        "created_by": created_by,
    }
    if assigned_to is not None:
        payload["assigned_to"] = assigned_to
    if required_capabilities is not None:
        payload["required_capabilities"] = required_capabilities
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    return _request("POST", "/task/create", payload, agent_id=created_by)


def _fail_task(task_id: str, *, actor: str, error: str = "cleanup") -> None:
    _request("POST", f"/task/{task_id}/fail", {"error": error}, agent_id=actor)


def _get_task(task_id: str) -> dict:
    status, data = _request("GET", f"/task/{task_id}")
    assert status == 200, data
    assert isinstance(data, dict), data
    task = data.get("task")
    assert isinstance(task, dict), data
    return task


def _claim_and_ack(task_id: str, *, agent_id: str) -> None:
    status, data = _request("POST", f"/task/{task_id}/claim", {}, agent_id=agent_id)
    assert status == 200, data
    status, data = _request("POST", f"/task/{task_id}/ack", {}, agent_id=agent_id)
    assert status == 200, data


def _read_wal_entries(task_id: str, *, after_size: int) -> list[dict]:
    deadline = time.time() + 3
    while time.time() < deadline:
        if os.path.exists(TASK_WAL_LOG):
            with open(TASK_WAL_LOG, encoding="utf-8") as handle:
                handle.seek(after_size)
                lines = [line.strip() for line in handle if line.strip()]
            entries = []
            for line in lines:
                entry = json.loads(line)
                if entry.get("task_id") == task_id:
                    entries.append(entry)
            if entries:
                return entries
        time.sleep(0.1)
    return []


def test_assigned_task_create_rejects_incompatible_registered_agent() -> None:
    creator = f"rt_cap_creator_{uuid.uuid4().hex[:8]}"
    reviewer = f"rt_cap_review_{uuid.uuid4().hex[:8]}"
    required_capability = f"rt_code_{uuid.uuid4().hex[:8]}"
    _register_agent(reviewer, ["review"])

    status, data = _create_task(
        title=f"rt capability assignment {uuid.uuid4().hex[:8]}",
        created_by=creator,
        assigned_to=reviewer,
        required_capabilities=[required_capability],
    )

    assert status == 400, data


def test_claim_rejects_agent_without_required_capabilities() -> None:
    creator = f"rt_cap_creator_{uuid.uuid4().hex[:8]}"
    reviewer = f"rt_cap_review_{uuid.uuid4().hex[:8]}"
    coder = f"rt_cap_code_{uuid.uuid4().hex[:8]}"
    required_capability = f"rt_code_{uuid.uuid4().hex[:8]}"
    _register_agent(reviewer, ["review"])
    _register_agent(coder, [required_capability, "review"])

    status, data = _create_task(
        title=f"rt capability claim {uuid.uuid4().hex[:8]}",
        created_by=creator,
        required_capabilities=[required_capability],
    )
    assert status == 201, data
    assert isinstance(data, dict), data
    task_id = str(data["task_id"])

    try:
        status, data = _request("POST", f"/task/{task_id}/claim", {}, agent_id=reviewer)
        assert status == 403, data

        status, data = _request("POST", f"/task/{task_id}/claim", {}, agent_id=coder)
        assert status == 200, data
    finally:
        _fail_task(task_id, actor=coder)


def test_task_queue_check_agent_selects_capability_matching_task() -> None:
    creator = f"rt_next_creator_{uuid.uuid4().hex[:8]}"
    reviewer = f"rt_next_review_{uuid.uuid4().hex[:8]}"
    required_capability = f"rt_review_{uuid.uuid4().hex[:8]}"
    _register_agent(reviewer, [required_capability])

    created_ids: list[str] = []
    try:
        for required in ([f"rt_other_{uuid.uuid4().hex[:8]}"], [required_capability]):
            status, data = _create_task(
                title=f"rt next action {'-'.join(required)} {uuid.uuid4().hex[:8]}",
                created_by=creator,
                required_capabilities=required,
            )
            assert status == 201, data
            assert isinstance(data, dict), data
            created_ids.append(str(data["task_id"]))

        status, data = _request("GET", f"/task/queue?state=created&check_agent={reviewer}")
        assert status == 200, data
        assert isinstance(data, dict), data
        assert data["backpressure"]["registered"] is True, data
        claimable_ids = {
            str(task["task_id"])
            for task in data["tasks"]
            if task.get("_claimability", {}).get("claimable")
        }
        assert created_ids[1] in claimable_ids, data
        assert created_ids[0] not in claimable_ids, data
    finally:
        for task_id in created_ids:
            _fail_task(task_id, actor=creator)


def test_task_queue_surfaces_backpressure_when_agent_is_at_capacity() -> None:
    creator = f"rt_bp_creator_{uuid.uuid4().hex[:8]}"
    coder = f"rt_bp_code_{uuid.uuid4().hex[:8]}"
    required_capability = f"rt_bp_{uuid.uuid4().hex[:8]}"
    _register_agent(coder, [required_capability])

    task_ids: list[str] = []
    claimed_ids: list[str] = []
    try:
        for idx in range(4):
            status, data = _create_task(
                title=f"rt backpressure {idx} {uuid.uuid4().hex[:8]}",
                created_by=creator,
                required_capabilities=[required_capability],
            )
            assert status == 201, data
            assert isinstance(data, dict), data
            task_ids.append(str(data["task_id"]))

        for task_id in task_ids[:3]:
            _claim_and_ack(task_id, agent_id=coder)
            claimed_ids.append(task_id)

        status, data = _request("GET", f"/task/queue?check_agent={coder}")
        assert status == 200, data
        assert isinstance(data, dict), data
        assert data["backpressure"]["at_capacity"] is True, data
        pending_task = next(task for task in data["tasks"] if str(task["task_id"]) == task_ids[3])
        assert pending_task["_claimability"]["claimable"] is False, pending_task
        assert pending_task["_claimability"]["reason"] == "agent_at_capacity", pending_task
    finally:
        for task_id in task_ids:
            actor = coder if task_id in claimed_ids else creator
            _fail_task(task_id, actor=actor)


def test_checkin_extends_explicit_task_lease() -> None:
    creator = f"rt_lease_creator_{uuid.uuid4().hex[:8]}"
    coder = f"rt_lease_code_{uuid.uuid4().hex[:8]}"
    required_capability = f"rt_lease_{uuid.uuid4().hex[:8]}"
    _register_agent(coder, [required_capability])

    status, data = _create_task(
        title=f"rt lease {uuid.uuid4().hex[:8]}",
        created_by=creator,
        required_capabilities=[required_capability],
        timeout_seconds=30,
    )
    assert status == 201, data
    assert isinstance(data, dict), data
    task_id = str(data["task_id"])

    try:
        _claim_and_ack(task_id, agent_id=coder)
        task = _get_task(task_id)
        first_lease = task["lease_expires_at"]

        time.sleep(1.1)
        status, data = _request(
            "POST",
            f"/task/{task_id}/checkin",
            {"note": "still working"},
            agent_id=coder,
        )
        assert status == 200, data

        task = _get_task(task_id)
        assert task["lease_expires_at"] > first_lease, task
    finally:
        _fail_task(task_id, actor=coder)


def test_task_transition_wal_records_before_and_after_snapshots() -> None:
    creator = f"rt_wal_creator_{uuid.uuid4().hex[:8]}"
    coder = f"rt_wal_code_{uuid.uuid4().hex[:8]}"
    required_capability = f"rt_wal_{uuid.uuid4().hex[:8]}"
    _register_agent(coder, [required_capability])

    wal_size = os.path.getsize(TASK_WAL_LOG) if os.path.exists(TASK_WAL_LOG) else 0
    status, data = _create_task(
        title=f"rt wal {uuid.uuid4().hex[:8]}",
        created_by=creator,
        required_capabilities=[required_capability],
    )
    assert status == 201, data
    assert isinstance(data, dict), data
    task_id = str(data["task_id"])

    try:
        _claim_and_ack(task_id, agent_id=coder)
        entries = _read_wal_entries(task_id, after_size=wal_size)
        actions = {entry.get("event") for entry in entries}
        assert {"created", "claimed", "acked"}.issubset(actions), entries
        for entry in entries:
            assert "before_state" in entry, entry
            assert "after_state" in entry, entry
    finally:
        _fail_task(task_id, actor=coder)


def test_parallel_register_and_agents_read_no_transport_failures() -> None:
    tag = f"rt_parallel_agents_{uuid.uuid4().hex[:8]}"
    transport_failures: list[dict[str, object]] = []

    def _register(idx: int) -> dict[str, object]:
        agent_id = f"{tag}_agent_{idx:03d}"
        status, data = _request(
            "POST",
            "/register",
            {"agent_id": agent_id, "role": "worker", "capabilities": ["synthetic"]},
            agent_id=agent_id,
            timeout=15,
        )
        return {"kind": "register", "agent_id": agent_id, "status": status, "data": data}

    def _read_agents() -> dict[str, object]:
        status, data = _request("GET", "/agents", timeout=15)
        return {"kind": "agents", "status": status, "data": data}

    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        futures = [pool.submit(_register, idx) for idx in range(24)]
        futures.extend(pool.submit(_read_agents) for _ in range(24))
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result["status"] != 200:
                transport_failures.append(result)

    assert not transport_failures, transport_failures


def test_parallel_claim_and_ack_no_transport_failures() -> None:
    tag = f"rt_parallel_claim_{uuid.uuid4().hex[:8]}"
    creator = f"{tag}_creator"
    task_assignments: list[tuple[str, str]] = []
    claimed_task_ids: set[str] = set()

    for idx in range(36):
        agent_id = f"{tag}_agent_{idx:03d}"
        _register_agent(agent_id, ["synthetic"])
        status, data = _create_task(
            title=f"{tag} task {idx}",
            created_by=creator,
            assigned_to=agent_id,
        )
        assert status == 201, data
        assert isinstance(data, dict), data
        task_assignments.append((agent_id, str(data["task_id"])))

    transport_failures: list[dict[str, object]] = []

    def _claim_and_ack_live(item: tuple[str, str]) -> dict[str, object]:
        agent_id, task_id = item
        claim_status, claim_data = _request("POST", f"/task/{task_id}/claim", {}, agent_id=agent_id, timeout=20)
        ack_status = None
        ack_data = None
        if claim_status == 200:
            ack_status, ack_data = _request("POST", f"/task/{task_id}/ack", {}, agent_id=agent_id, timeout=20)
        return {
            "agent_id": agent_id,
            "task_id": task_id,
            "claim_status": claim_status,
            "claim_data": claim_data,
            "ack_status": ack_status,
            "ack_data": ack_data,
        }

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            futures = [pool.submit(_claim_and_ack_live, assignment) for assignment in task_assignments]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result["claim_status"] == 200 and result["ack_status"] == 200:
                    claimed_task_ids.add(str(result["task_id"]))
                    continue
                transport_failures.append(result)

        assert not transport_failures, transport_failures
    finally:
        for agent_id, task_id in task_assignments:
            actor = agent_id if task_id in claimed_task_ids else creator
            _fail_task(task_id, actor=actor)
