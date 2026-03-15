from __future__ import annotations

import asyncio
import functools
import json
import os
import sys
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

FIXTURE_DIR = os.path.join(BACKEND_DIR, "tests", "fixtures", "browser")


class _FixtureHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class TestBrowserObserveLiveIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        handler = functools.partial(_FixtureHandler, directory=FIXTURE_DIR)
        try:
            cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        except PermissionError as exc:
            raise unittest.SkipTest(f"loopback server unavailable in this sandbox: {exc}") from exc
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.server_thread.join(timeout=5)

    def setUp(self) -> None:
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        self.mod = bridge_mcp
        self._orig_agent_id = self.mod._agent_id
        self._orig_unified_sessions = dict(self.mod._unified_sessions)
        self._orig_stealth_sessions = dict(self.mod._stealth_sessions)
        self._orig_stealth_cleanup_task = self.mod._stealth_cleanup_task
        self.mod._agent_id = "codex"
        self.mod._unified_sessions.clear()
        self.mod._stealth_sessions.clear()
        self.mod._stealth_cleanup_task = None
        self.created_session_ids: list[str] = []

    def tearDown(self) -> None:
        for session_id in list(self.created_session_ids):
            try:
                asyncio.run(self.mod.bridge_browser_close(session_id))
            except Exception:
                pass
        self.mod._unified_sessions.clear()
        self.mod._unified_sessions.update(self._orig_unified_sessions)
        self.mod._stealth_sessions.clear()
        self.mod._stealth_sessions.update(self._orig_stealth_sessions)
        self.mod._stealth_cleanup_task = self._orig_stealth_cleanup_task
        self.mod._agent_id = self._orig_agent_id

    async def _evaluate_unified(self, session_id: str, expression: str):
        session = self.mod._unified_sessions[session_id]
        raw = await self.mod.bridge_stealth_evaluate(session["engine_session_id"], expression)
        data = json.loads(raw)
        self.assertEqual(data["status"], "ok", data)
        return data["result"]

    def test_observe_fill_ref_and_click_ref_work_on_real_fixture(self) -> None:
        async def scenario() -> None:
            raw_open = await self.mod.bridge_browser_open(
                url=f"{self.base_url}/basic_form.html",
                engine="stealth",
                headless=True,
            )
            data_open = json.loads(raw_open)
            if not data_open.get("ok"):
                self.skipTest(f"real unified browser unavailable: {data_open.get('error', raw_open)}")
            session_id = data_open["session_id"]
            self.created_session_ids.append(session_id)

            raw_observe = await self.mod.bridge_browser_observe(session_id, max_nodes=10)
            data_observe = json.loads(raw_observe)
            self.assertTrue(data_observe["ok"], data_observe)
            self.assertGreaterEqual(data_observe["element_count"], 3)

            raw_find_email = await self.mod.bridge_browser_find_refs(session_id, name="email")
            data_find_email = json.loads(raw_find_email)
            self.assertTrue(data_find_email["ok"], data_find_email)
            self.assertEqual(data_find_email["count"], 1)
            email_ref = data_find_email["candidates"][0]["ref"]

            raw_find_name = await self.mod.bridge_browser_find_refs(session_id, query="creator name")
            data_find_name = json.loads(raw_find_name)
            self.assertTrue(data_find_name["ok"], data_find_name)
            self.assertGreaterEqual(data_find_name["count"], 1)
            name_ref = data_find_name["candidates"][0]["ref"]

            raw_fill = await self.mod.bridge_browser_fill_ref_verify(
                session_id,
                email_ref,
                "creator@example.com",
                title_contains="Basic Form",
                selector_exists="#email",
            )
            data_fill = json.loads(raw_fill)
            self.assertTrue(data_fill["ok"], data_fill)
            self.assertTrue(data_fill["verified"], data_fill)

            filled_value = await self._evaluate_unified(
                session_id,
                "() => document.querySelector('#email').value",
            )
            self.assertEqual(filled_value, "creator@example.com")

            raw_click = await self.mod.bridge_browser_click_ref_verify(
                session_id,
                name_ref,
                active_selector="#name",
                title_contains="Basic Form",
            )
            data_click = json.loads(raw_click)
            self.assertTrue(data_click["ok"], data_click)
            self.assertTrue(data_click["verified"], data_click)

            clicked_id = await self._evaluate_unified(
                session_id,
                "() => document.activeElement ? document.activeElement.id : null",
            )
            self.assertEqual(clicked_id, "name")

            raw_verify = await self.mod.bridge_browser_verify(
                session_id,
                url_contains="/basic_form.html",
                title_contains="Basic Form",
                text_contains="Newsletter Signup",
                selector_exists="#email",
                selector_missing="#definitely-missing",
            )
            data_verify = json.loads(raw_verify)
            self.assertTrue(data_verify["ok"], data_verify)
            self.assertTrue(data_verify["verified"], data_verify)

        asyncio.run(scenario())
