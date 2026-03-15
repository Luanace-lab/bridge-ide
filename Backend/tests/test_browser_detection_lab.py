from __future__ import annotations

import asyncio
import functools
import json
import os
import sys
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

FIXTURE_DIR = os.path.join(BACKEND_DIR, "tests", "fixtures", "browser_lab")
SNAPSHOT_EXPR = """(() => ({
    userAgent: navigator.userAgent,
    language: navigator.language,
    languages: Array.from(navigator.languages || []),
    platform: navigator.platform,
    vendor: typeof navigator.vendor === "undefined" ? null : navigator.vendor,
    productSub: typeof navigator.productSub === "undefined" ? null : navigator.productSub,
    webdriver: typeof navigator.webdriver === "undefined" ? null : navigator.webdriver,
    hasUserAgentData: typeof navigator.userAgentData !== "undefined",
    hardwareConcurrency: typeof navigator.hardwareConcurrency === "undefined" ? null : navigator.hardwareConcurrency,
    deviceMemory: typeof navigator.deviceMemory === "undefined" ? null : navigator.deviceMemory,
    timezone: (() => {
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
        } catch (err) {
            return null;
        }
    })()
}))()"""


class _FixtureHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        parts = urlsplit(self.path)
        if os.path.basename(parts.path) != "navigator_header_storage.html":
            super().do_GET()
            return

        params = list(parse_qsl(parts.query, keep_blank_values=True))
        param_map = dict(params)
        if param_map.get("_header_echo") == "1":
            super().do_GET()
            return

        echoed_headers = {
            "user-agent": self.headers.get("User-Agent", ""),
            "accept-language": self.headers.get("Accept-Language", ""),
            "sec-ch-ua": self.headers.get("Sec-CH-UA", ""),
            "sec-ch-ua-platform": self.headers.get("Sec-CH-UA-Platform", ""),
            "sec-ch-ua-mobile": self.headers.get("Sec-CH-UA-Mobile", ""),
        }
        params.append(("_header_echo", "1"))
        for key, value in echoed_headers.items():
            if value:
                params.append((f"header_{key}", value))
        location = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()


class TestBrowserDetectionLab(unittest.TestCase):
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
        self._orig_stealth_sessions = dict(self.mod._stealth_sessions)
        self._orig_unified_sessions = dict(self.mod._unified_sessions)
        self._orig_stealth_cleanup_task = self.mod._stealth_cleanup_task
        self._created_session_ids: list[str] = []
        self.mod._agent_id = "codex"
        self.mod._stealth_sessions.clear()
        self.mod._unified_sessions.clear()
        self.mod._stealth_cleanup_task = None

    def tearDown(self) -> None:
        self.mod._stealth_sessions.clear()
        self.mod._stealth_sessions.update(self._orig_stealth_sessions)
        self.mod._unified_sessions.clear()
        self.mod._unified_sessions.update(self._orig_unified_sessions)
        self.mod._stealth_cleanup_task = self._orig_stealth_cleanup_task
        self.mod._agent_id = self._orig_agent_id

    async def _start_session(self, **kwargs) -> str:
        raw = await self.mod.bridge_stealth_start(headless=True, **kwargs)
        data = json.loads(raw)
        if data.get("status") != "ok":
            self.skipTest(f"real stealth session unavailable: {data.get('error', raw)}")
        session_id = data["session_id"]
        self._created_session_ids.append(session_id)
        return session_id

    async def _goto(self, session_id: str, path: str) -> None:
        raw = await self.mod.bridge_stealth_goto(session_id, f"{self.base_url}/{path}")
        data = json.loads(raw)
        self.assertEqual(data["status"], "ok", data)

    async def _close_created_sessions(self) -> None:
        for session_id in list(self._created_session_ids):
            try:
                await self.mod.bridge_stealth_close(session_id)
            except Exception:
                pass
            finally:
                if session_id in self._created_session_ids:
                    self._created_session_ids.remove(session_id)

    async def _evaluate(self, session_id: str, expression: str):
        raw = await self.mod.bridge_stealth_evaluate(session_id, expression)
        data = json.loads(raw)
        self.assertEqual(data["status"], "ok", data)
        return data["result"]

    async def _wait_for_value(self, session_id: str, expression: str, timeout_s: float = 10.0):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            result = await self._evaluate(session_id, expression)
            if result:
                return result
            await asyncio.sleep(0.2)
        self.fail(f"timed out waiting for expression: {expression}")

    def test_navigator_probe_reports_expected_non_proxy_baseline(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session()
                await self._goto(session_id, "navigator_header_storage.html")

                result = await self._wait_for_value(session_id, "window.__browserLabResult")
                navigator = result["navigator"]
                self.assertEqual(navigator["language"], "en-US")
                self.assertEqual(navigator["languages"][0], "en-US")
                self.assertIsNone(navigator["webdriver"])
                self.assertEqual(result["probe"], "navigator_header_storage")
                self.assertTrue(result["timezone"]["available"])
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_iframe_probe_preserves_identity_between_direct_and_message_access(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session()
                await self._goto(session_id, "iframe_probe.html")

                result = await self._wait_for_value(session_id, "window.__browserLabResult.messageAccess")
                direct = await self._wait_for_value(session_id, "window.__browserLabResult.directAccess")

                self.assertEqual(result["probe"], "navigator_header_storage")
                self.assertEqual(direct["probe"], "navigator_header_storage")
                self.assertEqual(direct["navigator"]["userAgent"], result["navigator"]["userAgent"])
                self.assertEqual(direct["navigator"]["language"], result["navigator"]["language"])
                self.assertEqual(direct["navigator"]["languages"], result["navigator"]["languages"])
                self.assertEqual(direct["navigator"]["platform"], result["navigator"]["platform"])
                self.assertEqual(direct["navigator"]["webdriver"], result["navigator"]["webdriver"])
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_popup_probe_preserves_identity_between_opener_and_popup(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session()
                await self._goto(session_id, "popup_probe.html")

                opener_snapshot = await self._evaluate(session_id, SNAPSHOT_EXPR)
                click_raw = await self.mod.bridge_stealth_click(session_id, "#open-popup")
                click_data = json.loads(click_raw)
                self.assertEqual(click_data["status"], "ok", click_data)

                popup_result = await self._wait_for_value(session_id, "window.__browserLabResult.popupResult")
                popup_navigator = popup_result["navigator"]
                self.assertEqual(opener_snapshot["userAgent"], popup_navigator["userAgent"])
                self.assertEqual(opener_snapshot["language"], popup_navigator["language"])
                self.assertEqual(opener_snapshot["languages"], popup_navigator["languages"])
                self.assertEqual(opener_snapshot["platform"], popup_navigator["platform"])
                self.assertEqual(opener_snapshot["webdriver"], popup_navigator["webdriver"])
                self.assertEqual(opener_snapshot["hasUserAgentData"], popup_navigator["hasUserAgentData"])
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_custom_firefox_like_user_agent_uses_utc_across_top_iframe_and_popup(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session(user_agent=self.mod._STEALTH_TOR_UA)

                await self._goto(session_id, "navigator_header_storage.html")
                top_result = await self._wait_for_value(session_id, "window.__browserLabResult")
                self.assertEqual(top_result["navigator"]["userAgent"], self.mod._STEALTH_TOR_UA)
                self.assertEqual(top_result["timezone"]["value"], "UTC")

                await self._goto(session_id, "iframe_probe.html")
                iframe_message = await self._wait_for_value(session_id, "window.__browserLabResult.messageAccess")
                iframe_direct = await self._wait_for_value(session_id, "window.__browserLabResult.directAccess")
                for iframe_result in (iframe_message, iframe_direct):
                    self.assertEqual(iframe_result["navigator"]["userAgent"], self.mod._STEALTH_TOR_UA)
                    self.assertEqual(iframe_result["timezone"]["value"], "UTC")

                await self._goto(session_id, "popup_probe.html")
                click_raw = await self.mod.bridge_stealth_click(session_id, "#open-popup")
                click_data = json.loads(click_raw)
                self.assertEqual(click_data["status"], "ok", click_data)
                popup_result = await self._wait_for_value(session_id, "window.__browserLabResult.popupResult")
                self.assertEqual(popup_result["navigator"]["userAgent"], self.mod._STEALTH_TOR_UA)
                self.assertEqual(popup_result["timezone"]["value"], "UTC")
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_custom_firefox_like_user_agent_keeps_header_surface_firefox_like(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session(user_agent=self.mod._STEALTH_TOR_UA)
                expected_ua = self.mod._STEALTH_TOR_UA

                await self._goto(session_id, "navigator_header_storage.html")
                top_result = await self._wait_for_value(session_id, "window.__browserLabResult")

                await self._goto(session_id, "iframe_probe.html")
                iframe_result = await self._wait_for_value(session_id, "window.__browserLabResult.messageAccess")

                await self._goto(session_id, "popup_probe.html")
                click_raw = await self.mod.bridge_stealth_click(session_id, "#open-popup")
                click_data = json.loads(click_raw)
                self.assertEqual(click_data["status"], "ok", click_data)
                popup_result = await self._wait_for_value(session_id, "window.__browserLabResult.popupResult")

                for result in (top_result, iframe_result, popup_result):
                    headers = result["headers"]
                    self.assertEqual(headers["user-agent"], expected_ua)
                    self.assertEqual(headers["accept-language"], "en-US")
                    self.assertNotIn("sec-ch-ua", headers)
                    self.assertNotIn("sec-ch-ua-platform", headers)
                    self.assertNotIn("sec-ch-ua-mobile", headers)
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_custom_firefox_like_user_agent_hides_service_worker_surface(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session(user_agent=self.mod._STEALTH_TOR_UA)

                await self._goto(session_id, "navigator_header_storage.html")
                top_result = await self._wait_for_value(session_id, "window.__browserLabResult")

                await self._goto(session_id, "iframe_probe.html")
                iframe_result = await self._wait_for_value(session_id, "window.__browserLabResult.messageAccess")

                await self._goto(session_id, "popup_probe.html")
                click_raw = await self.mod.bridge_stealth_click(session_id, "#open-popup")
                click_data = json.loads(click_raw)
                self.assertEqual(click_data["status"], "ok", click_data)
                popup_result = await self._wait_for_value(session_id, "window.__browserLabResult.popupResult")

                for result in (top_result, iframe_result, popup_result):
                    service_worker = result["storage"]["serviceWorker"]
                    self.assertFalse(service_worker["available"])
                    self.assertFalse(service_worker["controller"])
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_custom_firefox_like_user_agent_keeps_screen_surface_stable_across_popup(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session(user_agent=self.mod._STEALTH_TOR_UA)

                await self._goto(session_id, "navigator_header_storage.html")
                top_result = await self._wait_for_value(session_id, "window.__browserLabResult")

                await self._goto(session_id, "iframe_probe.html")
                iframe_message = await self._wait_for_value(session_id, "window.__browserLabResult.messageAccess")
                iframe_direct = await self._wait_for_value(session_id, "window.__browserLabResult.directAccess")

                await self._goto(session_id, "popup_probe.html")
                click_raw = await self.mod.bridge_stealth_click(session_id, "#open-popup")
                click_data = json.loads(click_raw)
                self.assertEqual(click_data["status"], "ok", click_data)
                popup_result = await self._wait_for_value(session_id, "window.__browserLabResult.popupResult")

                expected_screen = top_result["screen"]
                self.assertEqual(iframe_message["screen"], expected_screen)
                self.assertEqual(iframe_direct["screen"], expected_screen)
                self.assertEqual(popup_result["screen"], expected_screen)
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_custom_firefox_like_user_agent_keeps_outer_window_within_screen_bounds(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session(user_agent=self.mod._STEALTH_TOR_UA)

                await self._goto(session_id, "navigator_header_storage.html")
                top_result = await self._wait_for_value(session_id, "window.__browserLabResult")

                await self._goto(session_id, "popup_probe.html")
                click_raw = await self.mod.bridge_stealth_click(session_id, "#open-popup")
                click_data = json.loads(click_raw)
                self.assertEqual(click_data["status"], "ok", click_data)
                popup_result = await self._wait_for_value(session_id, "window.__browserLabResult.popupResult")

                for result in (top_result, popup_result):
                    screen = result["screen"]
                    viewport = result["viewport"]
                    self.assertLessEqual(viewport["outerWidth"], screen["width"])
                    self.assertLessEqual(viewport["outerHeight"], screen["height"])
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_custom_firefox_like_user_agent_reports_pdf_viewer_enabled(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session(user_agent=self.mod._STEALTH_TOR_UA)

                await self._goto(session_id, "navigator_header_storage.html")
                top_result = await self._wait_for_value(session_id, "window.__browserLabResult")

                await self._goto(session_id, "iframe_probe.html")
                iframe_result = await self._wait_for_value(session_id, "window.__browserLabResult.messageAccess")

                await self._goto(session_id, "popup_probe.html")
                click_raw = await self.mod.bridge_stealth_click(session_id, "#open-popup")
                click_data = json.loads(click_raw)
                self.assertEqual(click_data["status"], "ok", click_data)
                popup_result = await self._wait_for_value(session_id, "window.__browserLabResult.popupResult")

                for result in (top_result, iframe_result, popup_result):
                    self.assertTrue(result["navigator"]["pdfViewerEnabled"])
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_permissions_media_probe_reports_coherent_fresh_permission_state(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session()
                await self._goto(session_id, "permissions_media_probe.html")

                result = await self._wait_for_value(session_id, "window.__browserLabResult")
                self.assertEqual(result["probe"], "permissions_media")
                self.assertTrue(result["notification"]["available"])
                self.assertEqual(result["notification"]["permission"], "default")

                notifications = result["permissions"]["notifications"]
                self.assertTrue(notifications["available"])
                self.assertEqual(notifications["state"], "prompt")

                for name in ("geolocation", "camera", "microphone", "persistent-storage", "push"):
                    self.assertTrue(result["permissions"][name]["available"], name)
                    self.assertEqual(result["permissions"][name]["state"], "prompt", name)

                self.assertTrue(result["mediaDevices"]["available"])
                self.assertTrue(result["mediaDevices"]["getUserMediaAvailable"])
                self.assertTrue(result["enumerateDevices"]["available"])
                self.assertIsInstance(result["enumerateDevices"]["devices"], list)
                self.assertTrue(result["storageManager"]["available"])
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_worker_probe_preserves_identity_between_page_worker_and_shared_worker(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session()
                await self._goto(session_id, "worker_probe.html")

                opener_snapshot = await self._evaluate(session_id, SNAPSHOT_EXPR)
                result = await self._wait_for_value(
                    session_id,
                    "window.__browserLabResult.worker && window.__browserLabResult.sharedWorker && window.__browserLabResult",
                )

                self.assertEqual(result["probe"], "worker")
                self.assertEqual(result["errors"], [])
                for realm_key in ("worker", "sharedWorker"):
                    realm = result[realm_key]
                    navigator = realm["navigator"]
                    self.assertEqual(opener_snapshot["userAgent"], navigator["userAgent"], realm_key)
                    self.assertEqual(opener_snapshot["language"], navigator["language"], realm_key)
                    self.assertEqual(opener_snapshot["languages"], navigator["languages"], realm_key)
                    self.assertEqual(opener_snapshot["platform"], navigator["platform"], realm_key)
                    self.assertEqual(opener_snapshot["webdriver"], navigator["webdriver"], realm_key)
                    self.assertEqual(opener_snapshot["hasUserAgentData"], navigator["hasUserAgentData"], realm_key)
                    self.assertEqual(opener_snapshot["hardwareConcurrency"], navigator["hardwareConcurrency"], realm_key)
                    self.assertEqual(opener_snapshot["deviceMemory"], navigator["deviceMemory"], realm_key)
                    self.assertEqual(opener_snapshot["timezone"], realm["timezone"], realm_key)
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())

    def test_custom_firefox_like_user_agent_stays_coherent_across_page_and_workers(self) -> None:
        async def scenario() -> None:
            try:
                session_id = await self._start_session(user_agent=self.mod._STEALTH_TOR_UA)
                await self._goto(session_id, "worker_probe.html")

                opener_snapshot = await self._evaluate(session_id, SNAPSHOT_EXPR)
                result = await self._wait_for_value(
                    session_id,
                    "window.__browserLabResult.worker && window.__browserLabResult.sharedWorker && window.__browserLabResult",
                )

                self.assertEqual(opener_snapshot["userAgent"], self.mod._STEALTH_TOR_UA)
                self.assertEqual(opener_snapshot["platform"], "Win32")
                self.assertFalse(opener_snapshot["hasUserAgentData"])
                self.assertEqual(opener_snapshot["hardwareConcurrency"], 2)
                self.assertIsNone(opener_snapshot["deviceMemory"])
                self.assertEqual(opener_snapshot["timezone"], "UTC")

                for realm_key in ("worker", "sharedWorker"):
                    navigator = result[realm_key]["navigator"]
                    self.assertEqual(navigator["userAgent"], self.mod._STEALTH_TOR_UA, realm_key)
                    self.assertEqual(navigator["platform"], "Win32", realm_key)
                    self.assertEqual(navigator["language"], opener_snapshot["language"], realm_key)
                    self.assertEqual(navigator["languages"], opener_snapshot["languages"], realm_key)
                    self.assertFalse(navigator["hasUserAgentData"], realm_key)
                    self.assertEqual(navigator["hardwareConcurrency"], 2, realm_key)
                    self.assertIsNone(navigator["deviceMemory"], realm_key)
                    self.assertEqual(result[realm_key]["timezone"], "UTC", realm_key)
            finally:
                await self._close_created_sessions()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
