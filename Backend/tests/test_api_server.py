"""
Tests for api_server.py — Unified REST API Server

Tests all endpoints via real HTTP requests against a temporary server.
No mocking — all tests hit real module instances.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

# Add Backend dir to path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from api_server import Platform, APIHandler, create_server, _routes, DEFAULT_API_PORT, API_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_port_counter = 19300


def _next_port() -> int:
    global _port_counter
    _port_counter += 1
    return _port_counter


class APITestCase(unittest.TestCase):
    """Base class — spins up a temporary server per test class."""

    server = None
    platform = None
    port = None
    thread = None
    data_dir = None

    @classmethod
    def setUpClass(cls):
        cls.data_dir = tempfile.mkdtemp()
        cls.port = _next_port()
        cls.server, cls.platform = create_server(port=cls.port, data_dir=cls.data_dir)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()
        if cls.data_dir:
            shutil.rmtree(cls.data_dir, ignore_errors=True)

    def get(self, path: str) -> dict:
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def post(self, path: str, data: dict) -> dict:
        url = f"http://127.0.0.1:{self.port}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def get_raw(self, path: str) -> urllib.request.Request:
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url)
        return urllib.request.urlopen(req)

    def post_raw(self, path: str, body: bytes, content_type: str = "application/json"):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": content_type},
        )
        return urllib.request.urlopen(req)


# ===========================================================================
# 1. Platform + Server Init
# ===========================================================================

class TestPlatformInit(APITestCase):
    """Tests for Platform initialization and status."""

    def test_platform_data_dir_created(self):
        self.assertTrue(os.path.isdir(self.platform.data_dir))

    def test_platform_status_structure(self):
        s = self.platform.status()
        self.assertIn("api_version", s)
        self.assertEqual(s["api_version"], API_VERSION)
        self.assertIn("timestamp", s)
        self.assertIn("modules", s)

    def test_platform_all_modules_present(self):
        modules = self.platform.status()["modules"]
        expected = [
            "memory", "approval", "vault", "soul", "skills",
            "ha", "office", "email", "telephony", "engines",
            "router", "runtime", "bus", "shared", "monitor", "auth",
        ]
        for m in expected:
            self.assertIn(m, modules, f"Module '{m}' missing from status")

    def test_routes_registered(self):
        total = sum(len(v) for v in _routes.values())
        self.assertGreaterEqual(total, 30)

    def test_default_port(self):
        self.assertEqual(DEFAULT_API_PORT, 9222)


# ===========================================================================
# 2. Status Endpoint
# ===========================================================================

class TestStatusEndpoint(APITestCase):
    """Tests for GET /api/status."""

    def test_get_status(self):
        result = self.get("/api/status")
        self.assertEqual(result["api_version"], API_VERSION)
        self.assertIn("modules", result)

    def test_status_contains_timestamp(self):
        result = self.get("/api/status")
        self.assertIsInstance(result["timestamp"], float)

    def test_status_modules_return_dicts(self):
        result = self.get("/api/status")
        for name in result["modules"]:
            mod = result["modules"][name]
            self.assertIsInstance(mod, dict, f"Module '{name}' status is not a dict")


# ===========================================================================
# 3. Memory Endpoints
# ===========================================================================

class TestMemoryEndpoints(APITestCase):
    """Tests for /api/memory/* endpoints."""

    def test_memory_write(self):
        result = self.post("/api/memory/write", {
            "agent_id": "test_agent",
            "category": "episodes",
            "content": "Test memory episode for search",
        })
        self.assertTrue(result["success"])

    def test_memory_write_requires_agent_id(self):
        result = self.post("/api/memory/write", {"content": "data"})
        self.assertIn("error", result)

    def test_memory_write_requires_content(self):
        result = self.post("/api/memory/write", {"agent_id": "a"})
        self.assertIn("error", result)

    def test_memory_search(self):
        self.post("/api/memory/write", {
            "agent_id": "searcher",
            "category": "episodes",
            "content": "unique_searchable_content_xyz",
        })
        result = self.post("/api/memory/search", {
            "query": "unique_searchable_content_xyz",
            "agent_id": "searcher",
        })
        self.assertIn("results", result)

    def test_memory_search_requires_query(self):
        result = self.post("/api/memory/search", {"agent_id": "a"})
        self.assertIn("error", result)

    def test_memory_search_requires_agent_id(self):
        result = self.post("/api/memory/search", {"query": "test"})
        self.assertIn("error", result)

    def test_memory_daily_note(self):
        result = self.post("/api/memory/daily", {
            "agent_id": "daily_agent",
            "content": "Today was productive",
        })
        self.assertTrue(result["success"])

    def test_memory_daily_requires_agent_id(self):
        result = self.post("/api/memory/daily", {"content": "note"})
        self.assertIn("error", result)

    def test_memory_daily_requires_content(self):
        result = self.post("/api/memory/daily", {"agent_id": "a"})
        self.assertIn("error", result)

    def test_memory_episodes_list(self):
        result = self.get("/api/memory/episodes")
        self.assertIn("episodes", result)

    def test_memory_episodes_with_agent_filter(self):
        result = self.get("/api/memory/episodes?agent_id=test_agent&limit=5")
        self.assertIn("episodes", result)


# ===========================================================================
# 4. Skills Endpoints
# ===========================================================================

class TestSkillsEndpoints(APITestCase):
    """Tests for /api/skills/* endpoints."""

    def test_skills_list(self):
        result = self.get("/api/skills/list")
        self.assertIn("skills", result)
        self.assertIsInstance(result["skills"], list)

    def test_skills_activate_requires_name(self):
        result = self.post("/api/skills/activate", {"agent_id": "a"})
        self.assertIn("error", result)

    def test_skills_activate_requires_agent_id(self):
        result = self.post("/api/skills/activate", {"name": "test"})
        self.assertIn("error", result)

    def test_skills_deactivate_requires_params(self):
        result = self.post("/api/skills/deactivate", {})
        self.assertIn("error", result)


# ===========================================================================
# 5. Approval Gate Endpoints
# ===========================================================================

class TestApprovalEndpoints(APITestCase):
    """Tests for /api/approval/* endpoints."""

    def test_approval_queue_empty(self):
        result = self.get("/api/approval/queue")
        self.assertIn("pending", result)

    def test_approval_request_and_approve(self):
        req = self.post("/api/approval/request", {
            "action_type": "delete_file",
            "agent_id": "test_agent",
            "description": "Delete temp file",
            "preview": "rm /tmp/test.txt",
        })
        self.assertTrue(req["success"])
        rid = req["request"]["request_id"]

        queue = self.get("/api/approval/queue")
        self.assertGreaterEqual(len(queue["pending"]), 1)

        approved = self.post("/api/approval/approve", {"request_id": rid})
        self.assertTrue(approved["success"])

    def test_approval_request_and_deny(self):
        req = self.post("/api/approval/request", {
            "action_type": "send_email",
            "agent_id": "email_agent",
            "description": "Send marketing email",
            "preview": "To: all@company.com",
        })
        rid = req["request"]["request_id"]

        denied = self.post("/api/approval/deny", {
            "request_id": rid,
            "reason": "Not authorized",
        })
        self.assertTrue(denied["success"])

    def test_approval_request_requires_action_type(self):
        result = self.post("/api/approval/request", {"agent_id": "a"})
        self.assertIn("error", result)

    def test_approval_approve_requires_request_id(self):
        result = self.post("/api/approval/approve", {})
        self.assertIn("error", result)

    def test_approval_deny_requires_request_id(self):
        result = self.post("/api/approval/deny", {})
        self.assertIn("error", result)

    def test_approval_approve_nonexistent(self):
        result = self.post("/api/approval/approve", {"request_id": "nonexistent"})
        self.assertFalse(result["success"])

    def test_approval_deny_nonexistent(self):
        result = self.post("/api/approval/deny", {"request_id": "nonexistent"})
        self.assertFalse(result["success"])


# ===========================================================================
# 6. Auth Endpoints
# ===========================================================================

class TestAuthEndpoints(APITestCase):
    """Tests for /api/auth/* endpoints."""

    def test_create_key(self):
        result = self.post("/api/auth/create_key", {"owner": "test_owner"})
        self.assertIn("key", result)
        self.assertIn("key_info", result)

    def test_create_key_requires_owner(self):
        result = self.post("/api/auth/create_key", {})
        self.assertIn("error", result)

    def test_list_keys(self):
        self.post("/api/auth/create_key", {"owner": "lister"})
        result = self.get("/api/auth/keys")
        self.assertIn("keys", result)
        self.assertGreaterEqual(len(result["keys"]), 1)

    def test_list_keys_filter_by_owner(self):
        self.post("/api/auth/create_key", {"owner": "filter_test"})
        result = self.get("/api/auth/keys?owner=filter_test")
        self.assertIn("keys", result)
        for k in result["keys"]:
            self.assertEqual(k["owner"], "filter_test")


# ===========================================================================
# 7. Engine Routing Endpoints
# ===========================================================================

class TestEngineEndpoints(APITestCase):
    """Tests for /api/engines/* endpoints."""

    def test_engines_list(self):
        result = self.get("/api/engines/list")
        self.assertIn("engines", result)
        self.assertIsInstance(result["engines"], list)

    def test_engines_route(self):
        result = self.post("/api/engines/route", {"category": "default"})
        self.assertIn("decision", result)
        self.assertIn("engine_name", result["decision"])


# ===========================================================================
# 8. Runtime Manager Endpoints
# ===========================================================================

class TestAgentsEndpoints(APITestCase):
    """Tests for /api/agents/* endpoints."""

    def test_agents_list(self):
        result = self.get("/api/agents/list")
        self.assertIn("agents", result)
        self.assertIsInstance(result["agents"], list)

    def test_agents_status(self):
        result = self.get("/api/agents/status")
        self.assertIsInstance(result, dict)


# ===========================================================================
# 9. Message Bus Endpoints
# ===========================================================================

class TestMessagesEndpoints(APITestCase):
    """Tests for /api/messages/* endpoints."""

    def test_messages_send(self):
        result = self.post("/api/messages/send", {
            "sender": "agent_a",
            "recipient": "agent_b",
            "content": "Hello from test",
        })
        self.assertTrue(result["success"])
        self.assertIn("message", result)

    def test_messages_send_requires_sender(self):
        result = self.post("/api/messages/send", {"content": "hello"})
        self.assertIn("error", result)

    def test_messages_send_requires_content(self):
        result = self.post("/api/messages/send", {"sender": "a"})
        self.assertIn("error", result)

    def test_messages_history(self):
        self.post("/api/messages/send", {
            "sender": "hist_a", "recipient": "hist_b", "content": "hist msg",
        })
        result = self.get("/api/messages/history?limit=10")
        self.assertIn("messages", result)
        self.assertGreaterEqual(len(result["messages"]), 1)

    def test_messages_receive_requires_agent_id(self):
        result = self.post("/api/messages/receive", {})
        self.assertIn("error", result)

    def test_messages_receive(self):
        result = self.post("/api/messages/receive", {
            "agent_id": "recv_agent",
            "limit": 5,
        })
        self.assertIn("messages", result)


# ===========================================================================
# 10. Shared Memory Endpoints
# ===========================================================================

class TestSharedMemoryEndpoints(APITestCase):
    """Tests for /api/shared/* endpoints."""

    def test_shared_write(self):
        result = self.post("/api/shared/write", {
            "topic": "test_topic",
            "content": "shared data",
            "agent_id": "writer_agent",
        })
        self.assertTrue(result["success"])

    def test_shared_write_requires_topic(self):
        result = self.post("/api/shared/write", {"content": "data"})
        self.assertIn("error", result)

    def test_shared_write_requires_content(self):
        result = self.post("/api/shared/write", {"topic": "t"})
        self.assertIn("error", result)

    def test_shared_read(self):
        self.post("/api/shared/write", {
            "topic": "read_test",
            "content": "readable data",
            "agent_id": "a",
        })
        result = self.get("/api/shared/read?topic=read_test")
        self.assertIn("entry", result)
        self.assertIsNotNone(result["entry"])

    def test_shared_read_requires_topic(self):
        result = self.get("/api/shared/read")
        self.assertIn("error", result)

    def test_shared_read_nonexistent(self):
        result = self.get("/api/shared/read?topic=nonexistent_topic_xyz")
        self.assertIsNone(result["entry"])

    def test_shared_search(self):
        self.post("/api/shared/write", {
            "topic": "search_topic",
            "content": "searchable unique content abc",
            "agent_id": "a",
        })
        result = self.post("/api/shared/search", {"query": "searchable unique"})
        self.assertIn("results", result)

    def test_shared_search_requires_query(self):
        result = self.post("/api/shared/search", {})
        self.assertIn("error", result)


# ===========================================================================
# 11. Monitor Endpoints
# ===========================================================================

class TestMonitorEndpoints(APITestCase):
    """Tests for /api/monitor/* endpoints."""

    def test_monitor_fleet(self):
        result = self.get("/api/monitor/fleet")
        self.assertIn("total_agents", result)

    def test_monitor_alerts(self):
        result = self.get("/api/monitor/alerts")
        self.assertIn("alerts", result)
        self.assertIsInstance(result["alerts"], list)

    def test_monitor_alerts_with_limit(self):
        result = self.get("/api/monitor/alerts?limit=5")
        self.assertIn("alerts", result)


# ===========================================================================
# 12. Delegation Endpoints
# ===========================================================================

class TestDelegationEndpoints(APITestCase):
    """Tests for /api/delegation/* endpoints."""

    def test_delegation_create(self):
        result = self.post("/api/delegation/create", {
            "parent_agent": "manager",
            "description": "Build feature X",
        })
        self.assertTrue(result["success"])
        self.assertIn("task", result)

    def test_delegation_create_requires_parent(self):
        result = self.post("/api/delegation/create", {"description": "task"})
        self.assertIn("error", result)

    def test_delegation_create_requires_description(self):
        result = self.post("/api/delegation/create", {"parent_agent": "mgr"})
        self.assertIn("error", result)

    def test_delegation_status(self):
        result = self.get("/api/delegation/status")
        self.assertIsInstance(result, dict)

    def test_delegation_get_task(self):
        created = self.post("/api/delegation/create", {
            "parent_agent": "mgr",
            "description": "Test task lookup",
        })
        task_id = created["task"]["task_id"]
        result = self.get(f"/api/delegation/task?task_id={task_id}")
        self.assertIn("task", result)
        self.assertEqual(result["task"]["task_id"], task_id)

    def test_delegation_get_task_requires_id(self):
        result = self.get("/api/delegation/task")
        self.assertIn("error", result)

    def test_delegation_get_nonexistent_task(self):
        result = self.get("/api/delegation/task?task_id=nonexistent")
        self.assertIn("error", result)


# ===========================================================================
# 13. Soul Endpoints
# ===========================================================================

class TestSoulEndpoints(APITestCase):
    """Tests for /api/soul/* endpoints."""

    def test_soul_resolve(self):
        result = self.get("/api/soul/resolve?agent_id=test_soul")
        self.assertIn("soul", result)
        self.assertEqual(result["soul"]["agent_id"], "test_soul")

    def test_soul_resolve_requires_agent_id(self):
        result = self.get("/api/soul/resolve")
        self.assertIn("error", result)

    def test_soul_identity(self):
        result = self.get("/api/soul/identity?agent_id=test_soul")
        self.assertIn("prolog", result)
        self.assertIn("soul_md", result)

    def test_soul_identity_requires_agent_id(self):
        result = self.get("/api/soul/identity")
        self.assertIn("error", result)

    def test_soul_resolve_has_fields(self):
        result = self.get("/api/soul/resolve?agent_id=soul_fields")
        soul = result["soul"]
        for field in ["agent_id", "name", "core_truths", "strengths", "boundaries"]:
            self.assertIn(field, soul)


# ===========================================================================
# 14. Reflection Endpoint
# ===========================================================================

class TestReflectionEndpoint(APITestCase):
    """Tests for /api/reflection/* endpoints."""

    def test_reflection_status(self):
        result = self.get("/api/reflection/status")
        self.assertEqual(result["status"], "active")


# ===========================================================================
# 15. HTTP Handler Behavior
# ===========================================================================

class TestHTTPHandler(APITestCase):
    """Tests for HTTP handler edge cases."""

    def test_404_on_unknown_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/nonexistent")
        self.assertEqual(ctx.exception.code, 404)

    def test_404_response_is_json(self):
        try:
            self.get("/api/nonexistent")
        except urllib.error.HTTPError as e:
            body = json.loads(e.read())
            self.assertIn("error", body)

    def test_cors_headers(self):
        url = f"http://127.0.0.1:{self.port}/api/status"
        req = urllib.request.Request(url, headers={"Origin": "http://127.0.0.1:9111"})
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.headers["Access-Control-Allow-Origin"], "http://127.0.0.1:9111")

    def test_options_preflight(self):
        url = f"http://127.0.0.1:{self.port}/api/status"
        req = urllib.request.Request(url, method="OPTIONS")
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 204)
            self.assertEqual(r.headers["Access-Control-Allow-Methods"], "GET, POST, OPTIONS")

    def test_invalid_json_post(self):
        url = f"http://127.0.0.1:{self.port}/api/memory/write"
        req = urllib.request.Request(
            url, data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_empty_post_body(self):
        url = f"http://127.0.0.1:{self.port}/api/memory/write"
        req = urllib.request.Request(
            url, data=b"",
            headers={"Content-Type": "application/json", "Content-Length": "0"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read())
            self.assertIn("error", body)

    def test_get_root_redirects_to_status(self):
        result = self.get("/")
        self.assertIn("api_version", result)


# ===========================================================================
# 16. Integration — Full Workflow
# ===========================================================================

class TestIntegrationWorkflow(APITestCase):
    """End-to-end integration tests."""

    def test_approval_workflow(self):
        # Request
        req = self.post("/api/approval/request", {
            "action_type": "ha_switch",
            "agent_id": "ha_agent",
            "description": "Turn on living room light",
            "preview": "switch.turn_on(light.living_room)",
        })
        rid = req["request"]["request_id"]

        # Check queue
        queue = self.get("/api/approval/queue")
        ids = [p["request_id"] for p in queue["pending"]]
        self.assertIn(rid, ids)

        # Approve
        approved = self.post("/api/approval/approve", {"request_id": rid})
        self.assertTrue(approved["success"])

        # Verify queue is empty for this request
        queue2 = self.get("/api/approval/queue")
        ids2 = [p["request_id"] for p in queue2["pending"]]
        self.assertNotIn(rid, ids2)

    def test_message_send_receive_flow(self):
        # Agent A sends to Agent B
        self.post("/api/messages/send", {
            "sender": "flow_a",
            "recipient": "flow_b",
            "content": "task complete",
        })

        # Check history
        hist = self.get("/api/messages/history?limit=100")
        contents = [m["content"] for m in hist["messages"]]
        self.assertIn("task complete", contents)

    def test_shared_memory_write_read_search(self):
        # Write
        self.post("/api/shared/write", {
            "topic": "integration_test",
            "content": "Integration test data for verification",
            "agent_id": "int_agent",
        })

        # Read
        read = self.get("/api/shared/read?topic=integration_test")
        self.assertIsNotNone(read["entry"])

        # Search
        search = self.post("/api/shared/search", {"query": "Integration verification"})
        self.assertIn("results", search)

    def test_delegation_create_and_lookup(self):
        created = self.post("/api/delegation/create", {
            "parent_agent": "lead",
            "description": "Implement feature Y",
            "engine": "claude",
        })
        task_id = created["task"]["task_id"]

        # Lookup
        task = self.get(f"/api/delegation/task?task_id={task_id}")
        self.assertEqual(task["task"]["description"], "Implement feature Y")

        # Status includes task
        status = self.get("/api/delegation/status")
        self.assertIsInstance(status, dict)

    def test_auth_create_and_list(self):
        self.post("/api/auth/create_key", {"owner": "integration_owner"})
        keys = self.get("/api/auth/keys?owner=integration_owner")
        self.assertGreaterEqual(len(keys["keys"]), 1)

    def test_memory_write_and_search(self):
        self.post("/api/memory/write", {
            "agent_id": "mem_int",
            "category": "episodes",
            "content": "Critical finding during integration test run alpha",
        })
        # BM25 search
        result = self.post("/api/memory/search", {
            "query": "Critical finding integration alpha",
            "agent_id": "mem_int",
        })
        self.assertIn("results", result)


# ===========================================================================
# 17. Context Scan Endpoint
# ===========================================================================

class TestContextScan(APITestCase):
    """Tests for GET /api/context/scan."""

    def test_scan_valid_project(self):
        result = self.get("/api/context/scan?project_path=" + self.data_dir)
        self.assertIn("claude", result)
        self.assertIn("codex", result)
        self.assertIsInstance(result["claude"]["config"], list)
        self.assertIsInstance(result["codex"]["config"], list)

    def test_scan_detects_claude_md(self):
        # Create a CLAUDE.md in temp dir
        Path(self.data_dir, "CLAUDE.md").write_text("# Test")
        result = self.get("/api/context/scan?project_path=" + self.data_dir)
        claude_files = result["claude"]["config"]
        claude_md = [f for f in claude_files if f["source"] == "CLAUDE.md"][0]
        self.assertTrue(claude_md["exists"])
        self.assertFalse(claude_md["is_dir"])

    def test_scan_detects_missing_files(self):
        result = self.get("/api/context/scan?project_path=" + self.data_dir)
        claude_files = result["claude"]["config"]
        agents_md = [f for f in result["codex"]["config"] if f["source"] == "AGENTS.md"][0]
        self.assertFalse(agents_md["exists"])

    def test_scan_detects_directories(self):
        Path(self.data_dir, ".claude").mkdir(exist_ok=True)
        result = self.get("/api/context/scan?project_path=" + self.data_dir)
        claude_dir = [f for f in result["claude"]["config"] if f["source"] == ".claude/"][0]
        self.assertTrue(claude_dir["exists"])
        self.assertTrue(claude_dir["is_dir"])

    def test_scan_missing_path(self):
        result = self.get("/api/context/scan")
        self.assertIn("error", result)

    def test_scan_nonexistent_path(self):
        result = self.get("/api/context/scan?project_path=/nonexistent/path")
        self.assertIn("error", result)


# ===========================================================================
# 18. Projects Create Endpoint
# ===========================================================================

class TestProjectsCreate(APITestCase):
    """Tests for POST /api/projects/create."""

    def test_create_project_structure(self):
        project_dir = os.path.join(self.data_dir, "new_project")
        os.makedirs(project_dir)
        result = self.post("/api/projects/create", {
            "project_name": "test-proj",
            "base_dir": project_dir,
        })
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["created"], list)
        self.assertTrue(len(result["created"]) > 0)

    def test_create_writes_claude_md(self):
        project_dir = os.path.join(self.data_dir, "proj2")
        os.makedirs(project_dir)
        self.post("/api/projects/create", {
            "project_name": "proj2",
            "base_dir": project_dir,
        })
        claude_md = Path(project_dir, "CLAUDE.md")
        self.assertTrue(claude_md.exists())
        content = claude_md.read_text()
        self.assertIn("proj2", content)

    def test_create_writes_settings(self):
        project_dir = os.path.join(self.data_dir, "proj3")
        os.makedirs(project_dir)
        self.post("/api/projects/create", {
            "project_name": "proj3",
            "base_dir": project_dir,
        })
        settings = Path(project_dir, ".claude", "settings.json")
        self.assertTrue(settings.exists())

    def test_create_idempotent(self):
        project_dir = os.path.join(self.data_dir, "proj4")
        os.makedirs(project_dir)
        r1 = self.post("/api/projects/create", {
            "project_name": "proj4",
            "base_dir": project_dir,
        })
        r2 = self.post("/api/projects/create", {
            "project_name": "proj4",
            "base_dir": project_dir,
        })
        self.assertTrue(r1["ok"])
        self.assertTrue(r2["ok"])
        # Second call creates fewer files (already exist)
        self.assertLessEqual(len(r2["created"]), len(r1["created"]))

    def test_create_missing_params(self):
        result = self.post("/api/projects/create", {"project_name": "x"})
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_create_nonexistent_dir(self):
        result = self.post("/api/projects/create", {
            "project_name": "x",
            "base_dir": "/nonexistent/dir",
        })
        self.assertFalse(result["ok"])


# ===========================================================================
# 19. Runtime Configure Endpoint
# ===========================================================================

class TestRuntimeConfigure(APITestCase):
    """Tests for POST /api/runtime/configure."""

    def test_configure_basic_team(self):
        result = self.post("/api/runtime/configure", {
            "project_path": self.data_dir,
            "leader": {"name": "lead1", "prompt": "Leader"},
            "agents": [{"name": "agent1", "position": "Dev"}],
        })
        self.assertTrue(result["ok"])
        self.assertIn("lead1", result["started"])
        self.assertIn("agent1", result["started"])

    def test_configure_leader_only(self):
        result = self.post("/api/runtime/configure", {
            "project_path": self.data_dir,
            "leader": {"name": "solo_lead", "prompt": "Solo"},
            "agents": [],
        })
        self.assertTrue(result["ok"])
        self.assertIn("solo_lead", result["started"])

    def test_configure_no_project_path(self):
        result = self.post("/api/runtime/configure", {
            "leader": {"name": "l", "prompt": "L"},
        })
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_configure_duplicate_agent_error(self):
        # First call succeeds
        self.post("/api/runtime/configure", {
            "project_path": self.data_dir,
            "leader": {"name": "dup_lead", "prompt": "Leader"},
        })
        # Second call with same name should report error
        result = self.post("/api/runtime/configure", {
            "project_path": self.data_dir,
            "leader": {"name": "dup_lead", "prompt": "Leader"},
        })
        self.assertIn("errors", result)

    def test_configure_agents_registered_in_runtime(self):
        self.post("/api/runtime/configure", {
            "project_path": self.data_dir,
            "leader": {"name": "rt_lead", "prompt": "Leader"},
            "agents": [{"name": "rt_a", "position": "Dev"}],
        })
        status = self.get("/api/agents/status")
        agents = status.get("agents", [])
        agent_ids = [a["agent_id"] for a in agents]
        self.assertIn("rt_lead", agent_ids)
        self.assertIn("rt_a", agent_ids)

    def test_configure_nonexistent_dir(self):
        result = self.post("/api/runtime/configure", {
            "project_path": "/nonexistent",
            "leader": {"name": "x"},
        })
        self.assertFalse(result["ok"])


# ===========================================================================
# 20. create_server function
# ===========================================================================

class TestCreateServer(unittest.TestCase):
    """Tests for the create_server factory function."""

    def test_create_server_returns_tuple(self):
        tmp = tempfile.mkdtemp()
        try:
            port = _next_port()
            server, platform = create_server(port=port, data_dir=tmp)
            self.assertIsNotNone(server)
            self.assertIsInstance(platform, Platform)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_create_server_default_data_dir(self):
        port = _next_port()
        server, platform = create_server(port=port)
        self.assertTrue(os.path.isdir(platform.data_dir))
        shutil.rmtree(platform.data_dir, ignore_errors=True)

    def test_platform_sets_handler(self):
        tmp = tempfile.mkdtemp()
        try:
            port = _next_port()
            server, platform = create_server(port=port, data_dir=tmp)
            self.assertIs(APIHandler.platform, platform)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
