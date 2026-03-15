from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(BACKEND_DIR)
TASK_TRACKER_PATH = os.path.join(REPO_ROOT, "Frontend", "task_tracker.html")
BASE_URL = "http://127.0.0.1:9111"
TASK_WAL_PATH = os.path.join(BACKEND_DIR, "task_transition_wal.jsonl")
TASK_LIFECYCLE_PATH = os.path.join(BACKEND_DIR, "logs", "task_lifecycle.jsonl")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

class BridgeLiveTaskRegressionTests(unittest.TestCase):
    """Live HTTP regression tests against the running Bridge server."""

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict | str]:
        cmd = [
            "curl",
            "-sS",
            "-X",
            method,
            f"{BASE_URL}{path}",
            "-H",
            "Content-Type: application/json",
            "-w",
            "\n%{http_code}",
        ]
        for key, value in (headers or {}).items():
            cmd.extend(["-H", f"{key}: {value}"])
        if body is not None:
            cmd.extend(["--data", json.dumps(body)])
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        raw, status = proc.stdout.rsplit("\n", 1)
        try:
            payload: dict | str = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return int(status), payload

    def create_task(self, title: str, created_by: str) -> str:
        status, body = self.request(
            "POST",
            "/task/create",
            {
                "type": "general",
                "title": title,
                "description": "regression probe",
                "created_by": created_by,
            },
            headers={"X-Bridge-Agent": created_by},
        )
        self.assertEqual(status, 201)
        assert isinstance(body, dict)
        return body["task_id"]

    def request_stdlib(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 10,
    ) -> tuple[int, dict | str]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            f"{BASE_URL}{path}",
            data=payload,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw
        except Exception as exc:  # noqa: BLE001
            return 0, {"error": str(exc)}

    def read_jsonl_since(self, path: str, offset: int) -> list[dict]:
        with open(path, encoding="utf-8") as handle:
            handle.seek(offset)
            return [json.loads(line) for line in handle if line.strip()]

    def test_fail_created_task_does_not_increment_retry_count(self) -> None:
        tag = f"reg_retry_{int(time.time() * 1000)}"
        task_id = self.create_task(f"{tag}_fail_created_task", created_by=tag)

        status, body = self.request(
            "POST",
            f"/task/{task_id}/fail",
            {"agent_id": tag, "error": "cancelled before claim"},
            headers={"X-Bridge-Agent": tag},
        )

        self.assertEqual(status, 200)
        assert isinstance(body, dict)
        self.assertEqual(
            body["task"]["retry_count"],
            0,
            "Direct fail of an unclaimed created task must not consume retry budget.",
        )

    def test_board_view_respects_limit(self) -> None:
        tag = f"reg_board_{int(time.time() * 1000)}"
        for idx in range(3):
            self.create_task(f"{tag}_board_limit_{idx}", created_by=tag)

        status, body = self.request("GET", "/task/queue?view=board&limit=1")

        self.assertEqual(status, 200)
        assert isinstance(body, dict)
        total_returned = sum(len(items) for items in body["board"].values())
        self.assertEqual(
            total_returned,
            1,
            "Board view must honor limit/offset instead of returning the full task set.",
        )

    def test_queue_claimability_annotations_do_not_mutate_task_storage(self) -> None:
        tag = f"reg_claimability_{int(time.time() * 1000)}"
        worker = f"{tag}_worker"
        create_status, create_body = self.request(
            "POST",
            "/task/create",
            {
                "type": "general",
                "title": f"{tag}_task",
                "description": "claimability mutation probe",
                "created_by": tag,
                "required_capabilities": ["qa"],
            },
            headers={"X-Bridge-Agent": tag},
        )
        self.assertEqual(create_status, 201, create_body)
        assert isinstance(create_body, dict)
        task_id = create_body["task_id"]

        queue_status, queue_body = self.request(
            "GET",
            f"/task/queue?state=created&check_agent={worker}",
        )
        self.assertEqual(queue_status, 200, queue_body)
        assert isinstance(queue_body, dict)
        queued = next(task for task in queue_body["tasks"] if task["task_id"] == task_id)
        self.assertEqual(queued["_claimability"]["reason"], "missing_capabilities")

        detail_status, detail_body = self.request("GET", f"/task/{task_id}")
        self.assertEqual(detail_status, 200, detail_body)
        assert isinstance(detail_body, dict)
        self.assertNotIn(
            "_claimability",
            detail_body["task"],
            "Queue claimability hints must not be persisted onto stored task objects.",
        )

    def test_claim_rejects_when_agent_is_over_capacity(self) -> None:
        tag = f"reg_capacity_{int(time.time() * 1000)}"
        agent_id = f"{tag}_worker"
        task_ids = [self.create_task(f"{tag}_capacity_{idx}", created_by=tag) for idx in range(4)]

        for task_id in task_ids[:3]:
            claim_status, _ = self.request(
                "POST",
                f"/task/{task_id}/claim",
                {"agent_id": agent_id},
                headers={"X-Bridge-Agent": agent_id},
            )
            self.assertEqual(claim_status, 200)
            ack_status, _ = self.request(
                "POST",
                f"/task/{task_id}/ack",
                {"agent_id": agent_id},
                headers={"X-Bridge-Agent": agent_id},
            )
            self.assertEqual(ack_status, 200)

        claim_status_2, body_2 = self.request(
            "POST",
            f"/task/{task_ids[3]}/claim",
            {"agent_id": agent_id},
            headers={"X-Bridge-Agent": agent_id},
        )

        self.assertEqual(
            claim_status_2,
            429,
            "Claim must be rejected once the agent reached its active task capacity.",
        )
        assert isinstance(body_2, dict)
        self.assertIn("capacity", body_2.get("error", "").lower())

    def test_done_error_with_evidence_is_atomic_and_logged(self) -> None:
        tag = f"reg_done_error_{int(time.time() * 1000)}"
        worker = f"{tag}_worker"
        create_status, create_body = self.request(
            "POST",
            "/task/create",
            {
                "type": "general",
                "title": f"{tag}_task",
                "description": "done error path",
                "created_by": tag,
                "assigned_to": worker,
            },
            headers={"X-Bridge-Agent": tag},
        )
        self.assertEqual(create_status, 201, create_body)
        assert isinstance(create_body, dict)
        task_id = create_body["task_id"]

        for suffix in ("claim", "ack"):
            status, body = self.request(
                "POST",
                f"/task/{task_id}/{suffix}",
                {"agent_id": worker},
                headers={"X-Bridge-Agent": worker},
            )
            self.assertEqual(status, 200, body)

        wal_offset = os.path.getsize(TASK_WAL_PATH)
        lifecycle_offset = os.path.getsize(TASK_LIFECYCLE_PATH)

        done_status, done_body = self.request(
            "POST",
            f"/task/{task_id}/done",
            {
                "agent_id": worker,
                "result": {"summary": "error path complete"},
                "result_code": "error",
                "result_summary": "error path complete",
                "evidence": {"type": "log", "ref": "synthetic error-path evidence"},
            },
            headers={"X-Bridge-Agent": worker},
        )
        self.assertEqual(done_status, 200, done_body)
        assert isinstance(done_body, dict)
        self.assertEqual(done_body["task"]["state"], "done")
        self.assertEqual(done_body["task"]["result_code"], "error")
        self.assertEqual(done_body["task"]["evidence"]["type"], "log")

        detail_status, detail_body = self.request("GET", f"/task/{task_id}")
        self.assertEqual(detail_status, 200, detail_body)
        assert isinstance(detail_body, dict)
        detail_task = detail_body["task"]
        self.assertEqual(detail_task["state"], "done")
        self.assertEqual(detail_task["state_history"][-1]["state"], "done")
        self.assertEqual(detail_task["state_history"][-1]["result_code"], "error")

        wal_entries = [e for e in self.read_jsonl_since(TASK_WAL_PATH, wal_offset) if e.get("task_id") == task_id]
        lifecycle_entries = [e for e in self.read_jsonl_since(TASK_LIFECYCLE_PATH, lifecycle_offset) if e.get("task_id") == task_id]
        self.assertTrue(any(e.get("event") == "done" for e in wal_entries), wal_entries)
        self.assertTrue(any(e.get("event") == "done" for e in lifecycle_entries), lifecycle_entries)

    def test_done_requires_durable_ack_before_completion(self) -> None:
        tag = f"reg_done_ack_gate_{int(time.time() * 1000)}"
        worker = f"{tag}_worker"
        create_status, create_body = self.request(
            "POST",
            "/task/create",
            {
                "type": "general",
                "title": f"{tag}_task",
                "description": "ack gate probe",
                "created_by": tag,
                "assigned_to": worker,
            },
            headers={"X-Bridge-Agent": tag},
        )
        self.assertEqual(create_status, 201, create_body)
        assert isinstance(create_body, dict)
        task_id = create_body["task_id"]

        claim_status, claim_body = self.request(
            "POST",
            f"/task/{task_id}/claim",
            {"agent_id": worker},
            headers={"X-Bridge-Agent": worker},
        )
        self.assertEqual(claim_status, 200, claim_body)

        wal_offset = os.path.getsize(TASK_WAL_PATH)
        lifecycle_offset = os.path.getsize(TASK_LIFECYCLE_PATH)

        done_status, done_body = self.request(
            "POST",
            f"/task/{task_id}/done",
            {
                "agent_id": worker,
                "result": {"summary": "should be blocked"},
                "result_code": "success",
                "result_summary": "attempted done without ack",
                "evidence": {"type": "log", "ref": "ack gate regression probe"},
            },
            headers={"X-Bridge-Agent": worker},
        )
        self.assertEqual(done_status, 409, done_body)
        assert isinstance(done_body, dict)
        self.assertIn("expected 'acked'", done_body.get("error", ""))

        detail_status, detail_body = self.request("GET", f"/task/{task_id}")
        self.assertEqual(detail_status, 200, detail_body)
        assert isinstance(detail_body, dict)
        detail_task = detail_body["task"]
        self.assertEqual(detail_task["state"], "claimed")
        self.assertIsNone(detail_task.get("done_at"))
        self.assertFalse(any(entry.get("state") == "done" for entry in detail_task["state_history"]))

        wal_entries = [e for e in self.read_jsonl_since(TASK_WAL_PATH, wal_offset) if e.get("task_id") == task_id]
        lifecycle_entries = [e for e in self.read_jsonl_since(TASK_LIFECYCLE_PATH, lifecycle_offset) if e.get("task_id") == task_id]
        self.assertFalse(any(e.get("event") == "done" for e in wal_entries), wal_entries)
        self.assertFalse(any(e.get("event") == "done" for e in lifecycle_entries), lifecycle_entries)

    def test_checkin_verify_and_delete_emit_durable_audit_events(self) -> None:
        tag = f"reg_audit_{int(time.time() * 1000)}"
        worker = f"{tag}_worker"
        verifier = f"{tag}_verifier"
        create_status, create_body = self.request(
            "POST",
            "/task/create",
            {
                "type": "general",
                "title": f"{tag}_task",
                "description": "audit event probe",
                "created_by": tag,
                "assigned_to": worker,
            },
            headers={"X-Bridge-Agent": tag},
        )
        self.assertEqual(create_status, 201, create_body)
        assert isinstance(create_body, dict)
        task_id = create_body["task_id"]

        claim_status, claim_body = self.request(
            "POST",
            f"/task/{task_id}/claim",
            {"agent_id": worker},
            headers={"X-Bridge-Agent": worker},
        )
        self.assertEqual(claim_status, 200, claim_body)
        ack_status, ack_body = self.request(
            "POST",
            f"/task/{task_id}/ack",
            {"agent_id": worker},
            headers={"X-Bridge-Agent": worker},
        )
        self.assertEqual(ack_status, 200, ack_body)

        wal_offset = os.path.getsize(TASK_WAL_PATH)
        lifecycle_offset = os.path.getsize(TASK_LIFECYCLE_PATH)

        checkin_status, checkin_body = self.request(
            "POST",
            f"/task/{task_id}/checkin",
            {"agent_id": worker, "note": "still working"},
            headers={"X-Bridge-Agent": worker},
        )
        self.assertEqual(checkin_status, 200, checkin_body)
        done_status, done_body = self.request(
            "POST",
            f"/task/{task_id}/done",
            {
                "agent_id": worker,
                "result": {"summary": "audit done"},
                "result_code": "success",
                "result_summary": "audit done",
                "evidence": {"type": "log", "ref": "audit trail probe"},
            },
            headers={"X-Bridge-Agent": worker},
        )
        self.assertEqual(done_status, 200, done_body)
        verify_status, verify_body = self.request(
            "POST",
            f"/task/{task_id}/verify",
            {"agent_id": verifier, "note": "verified in regression"},
            headers={"X-Bridge-Agent": verifier},
        )
        self.assertEqual(verify_status, 200, verify_body)
        delete_status, delete_body = self.request(
            "DELETE",
            f"/task/{task_id}",
            headers={"X-Bridge-Agent": tag},
        )
        self.assertEqual(delete_status, 200, delete_body)

        detail_status, detail_body = self.request("GET", f"/task/{task_id}")
        self.assertEqual(detail_status, 200, detail_body)
        assert isinstance(detail_body, dict)
        history_states = [entry["state"] for entry in detail_body["task"]["state_history"]]
        self.assertIn("checkin", history_states)
        self.assertIn("verified", history_states)
        self.assertIn("deleted", history_states)

        wal_entries = [e for e in self.read_jsonl_since(TASK_WAL_PATH, wal_offset) if e.get("task_id") == task_id]
        lifecycle_entries = [e for e in self.read_jsonl_since(TASK_LIFECYCLE_PATH, lifecycle_offset) if e.get("task_id") == task_id]
        wal_events = {e.get("event") for e in wal_entries}
        lifecycle_events = {e.get("event") for e in lifecycle_entries}
        for expected in ("checkin", "done", "verified", "deleted"):
            self.assertIn(expected, wal_events, wal_entries)
            self.assertIn(expected, lifecycle_events, lifecycle_entries)

    def test_parallel_register_and_agents_reads_do_not_drop_connections(self) -> None:
        tag = f"reg_parallel_agents_{int(time.time() * 1000)}"

        def register(idx: int) -> dict:
            status, body = self.request_stdlib(
                "POST",
                "/register",
                {
                    "agent_id": f"{tag}_agent_{idx:03d}",
                    "role": "worker",
                    "capabilities": ["synthetic"],
                },
                timeout=10,
            )
            return {"kind": "register", "idx": idx, "status": status, "body": body}

        def fetch_agents(idx: int) -> dict:
            status, body = self.request_stdlib("GET", "/agents", timeout=10)
            return {"kind": "agents", "idx": idx, "status": status, "body": body}

        failures: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            futures = [pool.submit(register, idx) for idx in range(36)]
            futures.extend(pool.submit(fetch_agents, idx) for idx in range(36))
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result["status"] != 200:
                    failures.append(result)

        self.assertEqual(
            failures,
            [],
            f"Parallel /register + /agents transport must not drop connections: {failures[:10]}",
        )

    def test_parallel_claim_ack_load_has_no_transport_failures(self) -> None:
        tag = f"reg_parallel_claim_{int(time.time() * 1000)}"
        agent_ids = [f"{tag}_agent_{idx:03d}" for idx in range(48)]
        task_pairs: list[tuple[str, str]] = []

        for agent_id in agent_ids:
            register_status, register_body = self.request_stdlib(
                "POST",
                "/register",
                {"agent_id": agent_id, "role": "worker", "capabilities": ["synthetic"]},
                timeout=10,
            )
            self.assertEqual(register_status, 200, register_body)
            create_status, create_body = self.request_stdlib(
                "POST",
                "/task/create",
                {
                    "type": "research",
                    "title": f"{tag} task for {agent_id}",
                    "description": "parallel claim/ack regression",
                    "created_by": tag,
                    "assigned_to": agent_id,
                },
                headers={"X-Bridge-Agent": tag},
                timeout=10,
            )
            self.assertEqual(create_status, 201, create_body)
            assert isinstance(create_body, dict)
            task_pairs.append((agent_id, create_body["task_id"]))

        def claim_ack(agent_id: str, task_id: str) -> dict:
            claim_status, claim_body = self.request_stdlib(
                "POST",
                f"/task/{task_id}/claim",
                {"agent_id": agent_id},
                headers={"X-Bridge-Agent": agent_id},
                timeout=15,
            )
            ack_status = None
            ack_body: dict | str | None = None
            if claim_status == 200:
                ack_status, ack_body = self.request_stdlib(
                    "POST",
                    f"/task/{task_id}/ack",
                    {"agent_id": agent_id},
                    headers={"X-Bridge-Agent": agent_id},
                    timeout=15,
                )
            return {
                "agent_id": agent_id,
                "task_id": task_id,
                "claim_status": claim_status,
                "claim_body": claim_body,
                "ack_status": ack_status,
                "ack_body": ack_body,
            }

        failures: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(claim_ack, agent_id, task_id) for agent_id, task_id in task_pairs]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result["claim_status"] != 200 or result["ack_status"] != 200:
                    failures.append(result)

        self.assertEqual(
            failures,
            [],
            f"Parallel claim/ack load must complete without transport failures: {failures[:5]}",
        )


class TaskTrackerContractTests(unittest.TestCase):
    def test_task_tracker_fallback_preserves_filters(self) -> None:
        raw = Path(TASK_TRACKER_PATH).read_text(encoding="utf-8")
        self.assertIn("fetch(API_BASE + '/task/tracker?' + params.toString())", raw)
        self.assertIn("params.set('agent', filterAgent.value)", raw)
        self.assertIn("params.set('status', filterStatus.value)", raw)
        self.assertIn(
            "fetch(API_BASE + '/task/queue?' + fallbackParams.toString())",
            raw,
            "Fallback must preserve equivalent filters when /task/tracker is unavailable.",
        )
        self.assertIn("fallbackParams.set('agent_id', filterAgent.value)", raw)
        self.assertIn("fallbackParams.set('state', filterStatus.value)", raw)

    def test_task_tracker_failed_duration_uses_failed_at(self) -> None:
        raw = Path(TASK_TRACKER_PATH).read_text(encoding="utf-8")
        self.assertIn("function calcDuration(t)", raw)
        self.assertIn(
            "const end = t.done_at || t.failed_at",
            raw,
            "Failed task duration must use failed_at, not created_at.",
        )


if __name__ == "__main__":
    unittest.main()
