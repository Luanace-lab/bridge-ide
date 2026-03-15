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


class TestBrowserSemanticFlowsLiveIntegration(unittest.TestCase):
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

    async def _open_fixture(self, fixture_name: str) -> str:
        raw = await self.mod.bridge_browser_open(
            url=f"{self.base_url}/{fixture_name}",
            engine="stealth",
            headless=True,
        )
        data = json.loads(raw)
        if not data.get("ok"):
            self.skipTest(f"real unified browser unavailable: {data.get('error', raw)}")
        session_id = data["session_id"]
        self.created_session_ids.append(session_id)
        return session_id

    async def _find_single_ref(self, session_id: str, **kwargs) -> str:
        raw = await self.mod.bridge_browser_find_refs(session_id, **kwargs)
        data = json.loads(raw)
        self.assertTrue(data["ok"], data)
        self.assertGreaterEqual(data["count"], 1, data)
        return data["candidates"][0]["ref"]

    def test_menu_flow_resolve_click_verify(self) -> None:
        async def scenario() -> None:
            session_id = await self._open_fixture("menu_flow.html")
            pricing_ref = await self._find_single_ref(session_id, query="pricing")
            raw = await self.mod.bridge_browser_click_ref_verify(
                session_id,
                pricing_ref,
                url_contains="#pricing",
                text_contains="Starter, Pro, and Studio plans.",
                selector_exists="#pricing",
            )
            data = json.loads(raw)
            self.assertTrue(data["ok"], data)
            self.assertTrue(data["verified"], data)

        asyncio.run(scenario())

    def test_login_flow_fill_and_submit(self) -> None:
        async def scenario() -> None:
            session_id = await self._open_fixture("login_flow.html")
            email_ref = await self._find_single_ref(session_id, name="email")
            password_ref = await self._find_single_ref(session_id, name="password")
            sign_in_ref = await self._find_single_ref(session_id, query="sign in")

            raw_email = await self.mod.bridge_browser_fill_ref_verify(
                session_id,
                email_ref,
                "creator@example.com",
                selector_exists="#email",
            )
            raw_password = await self.mod.bridge_browser_fill_ref_verify(
                session_id,
                password_ref,
                "supersecret",
                selector_exists="#password",
            )
            raw_submit = await self.mod.bridge_browser_click_ref_verify(
                session_id,
                sign_in_ref,
                text_contains="Dashboard Ready",
                selector_exists='#status[data-state="success"]',
            )

            self.assertTrue(json.loads(raw_email)["verified"])
            self.assertTrue(json.loads(raw_password)["verified"])
            self.assertTrue(json.loads(raw_submit)["verified"])

        asyncio.run(scenario())

    def test_modal_flow_open_fill_and_close(self) -> None:
        async def scenario() -> None:
            session_id = await self._open_fixture("modal_flow.html")
            open_ref = await self._find_single_ref(session_id, query="open creator modal")
            raw_open = await self.mod.bridge_browser_click_ref_verify(
                session_id,
                open_ref,
                text_contains="Creator modal open",
                selector_exists='#creator-modal[data-modal-state="open"]',
            )
            self.assertTrue(json.loads(raw_open)["verified"])

            title_ref = await self._find_single_ref(session_id, placeholder="clip title")
            raw_fill = await self.mod.bridge_browser_fill_ref_verify(
                session_id,
                title_ref,
                "Hook Cut",
                selector_exists="#clip-title",
            )
            self.assertTrue(json.loads(raw_fill)["verified"])

            close_ref = await self._find_single_ref(session_id, query="close modal")
            raw_close = await self.mod.bridge_browser_click_ref_verify(
                session_id,
                close_ref,
                selector_missing='#creator-modal[data-modal-state="open"]',
                text_contains="Open Creator Modal",
            )
            self.assertTrue(json.loads(raw_close)["verified"])

        asyncio.run(scenario())
