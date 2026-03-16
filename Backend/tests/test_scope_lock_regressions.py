from __future__ import annotations

import json
import os
import subprocess
import time
import unittest


BASE_URL = "http://127.0.0.1:9111"
TOKEN_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".config", "bridge", "tokens.json")


def _load_tokens() -> dict[str, str]:
    try:
        with open(TOKEN_CONFIG_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


_TOKENS: dict[str, str] = _load_tokens()


def _user_token() -> str:
    return _TOKENS.get("user_token", "")


class ScopeLockRegressionTests(unittest.TestCase):
    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict | str]:
        merged_headers: dict[str, str] = {}
        if _user_token():
            merged_headers["X-Bridge-Token"] = _user_token()
        merged_headers.update(headers or {})
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
        for key, value in merged_headers.items():
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
                "description": "scope regression probe",
                "created_by": created_by,
            },
            headers={"X-Bridge-Agent": created_by},
        )
        self.assertEqual(status, 201)
        assert isinstance(body, dict)
        return body["task_id"]

    def claim_and_ack_task(self, task_id: str, agent_id: str) -> None:
        claim_status, claim_body = self.request(
            "POST",
            f"/task/{task_id}/claim",
            {"agent_id": agent_id},
            headers={"X-Bridge-Agent": agent_id},
        )
        self.assertEqual(claim_status, 200, claim_body)
        ack_status, ack_body = self.request(
            "POST",
            f"/task/{task_id}/ack",
            {"agent_id": agent_id},
            headers={"X-Bridge-Agent": agent_id},
        )
        self.assertEqual(ack_status, 200, ack_body)

    def test_foreign_agent_cannot_unlock_another_tasks_scope_lock(self) -> None:
        tag = f"scope_unlock_{int(time.time() * 1000)}"
        owner_agent = f"{tag}_owner"
        foreign_agent = f"{tag}_foreign"
        owner_task = self.create_task(f"{tag}_task", created_by=f"{tag}_creator")
        locked_path = f"src/{tag}.py"
        self.claim_and_ack_task(owner_task, owner_agent)

        lock_status, lock_body = self.request(
            "POST",
            "/scope/lock",
            {
                "task_id": owner_task,
                "agent_id": owner_agent,
                "paths": [locked_path],
                "lock_type": "file",
            },
            headers={"X-Bridge-Agent": owner_agent},
        )
        self.assertEqual(lock_status, 200, lock_body)

        unlock_status, unlock_body = self.request(
            "POST",
            "/scope/unlock",
            {
                "task_id": owner_task,
                "agent_id": foreign_agent,
            },
            headers={"X-Bridge-Agent": foreign_agent},
        )

        self.assertEqual(
            unlock_status,
            403,
            "A foreign agent must not be able to unlock another agent's scope locks.",
        )
        assert isinstance(unlock_body, dict)
        self.assertIn("scope lock owned by", unlock_body.get("error", "").lower())

        owner_unlock_status, owner_unlock_body = self.request(
            "POST",
            "/scope/unlock",
            {
                "task_id": owner_task,
                "agent_id": owner_agent,
            },
            headers={"X-Bridge-Agent": owner_agent},
        )
        self.assertEqual(owner_unlock_status, 200, owner_unlock_body)
        assert isinstance(owner_unlock_body, dict)
        self.assertEqual(owner_unlock_body.get("count"), 1)

    def test_task_checkin_extends_scope_lock_ttl(self) -> None:
        tag = f"scope_checkin_{int(time.time() * 1000)}"
        agent_id = f"{tag}_agent"
        task_id = self.create_task(f"{tag}_task", created_by=f"{tag}_creator")
        locked_path = f"src/{tag}.py"

        self.claim_and_ack_task(task_id, agent_id)

        lock_status, lock_body = self.request(
            "POST",
            "/scope/lock",
            {
                "task_id": task_id,
                "agent_id": agent_id,
                "paths": [locked_path],
                "lock_type": "file",
                "ttl": 2,
            },
            headers={"X-Bridge-Agent": agent_id},
        )
        self.assertEqual(lock_status, 200, lock_body)

        time.sleep(1.2)
        checkin_status, checkin_body = self.request(
            "POST",
            f"/task/{task_id}/checkin",
            {"agent_id": agent_id, "note": "still working"},
            headers={"X-Bridge-Agent": agent_id},
        )
        self.assertEqual(checkin_status, 200, checkin_body)

        time.sleep(1.2)
        check_status, check_body = self.request(
            "GET",
            f"/scope/check?paths={locked_path}",
        )
        self.assertEqual(check_status, 200, check_body)
        assert isinstance(check_body, dict)
        self.assertIsNotNone(
            check_body["paths"][locked_path],
            "Task checkin must refresh scope lock TTL for active work.",
        )


if __name__ == "__main__":
    unittest.main()
