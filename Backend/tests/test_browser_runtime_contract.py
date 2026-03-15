from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import execution_journal as journal  # noqa: E402
import server as srv  # noqa: E402


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestBrowserRuntimeContracts(unittest.TestCase):
    def setUp(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        self.mod = bridge_mcp
        self.tmpdir = tempfile.mkdtemp(prefix="bridge_browser_contract_")
        self._orig_runs_base_dir = journal.RUNS_BASE_DIR
        journal.RUNS_BASE_DIR = self.tmpdir
        self._orig_agent_id = self.mod._agent_id
        self._orig_unified_sessions = dict(self.mod._unified_sessions)
        self._orig_stealth_sessions = dict(self.mod._stealth_sessions)
        self._orig_stealth_cleanup_task = self.mod._stealth_cleanup_task
        self._orig_cdp_browser = self.mod._cdp_browser
        self.mod._agent_id = "codex"
        self.mod._unified_sessions.clear()
        self.mod._stealth_sessions.clear()
        self.mod._stealth_cleanup_task = None

    def tearDown(self):
        journal.RUNS_BASE_DIR = self._orig_runs_base_dir
        self.mod._agent_id = self._orig_agent_id
        self.mod._unified_sessions.clear()
        self.mod._unified_sessions.update(self._orig_unified_sessions)
        self.mod._stealth_sessions.clear()
        self.mod._stealth_sessions.update(self._orig_stealth_sessions)
        self.mod._stealth_cleanup_task = self._orig_stealth_cleanup_task
        self.mod._cdp_browser = self._orig_cdp_browser
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_browser_open_stealth_starts_then_navigates(self):
        start = AsyncMock(return_value=json.dumps({"status": "ok", "session_id": "st123"}))
        goto = AsyncMock(return_value=json.dumps({
            "status": "ok",
            "url": "https://example.com",
            "title": "Example",
        }))

        with patch.object(self.mod, "bridge_stealth_start", start), patch.object(self.mod, "bridge_stealth_goto", goto):
            raw = asyncio.run(self.mod.bridge_browser_open(url="https://example.com", engine="stealth"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["engine"], "stealth")
        self.assertEqual(data["session_id"], data["run_id"])
        start.assert_awaited_once_with(headless=True, proxy="", user_agent="", profile="")
        goto.assert_awaited_once_with("st123", "https://example.com")
        self.assertIn(data["session_id"], self.mod._unified_sessions)
        self.assertEqual(self.mod._unified_sessions[data["session_id"]]["run_id"], data["run_id"])

        run_state = journal.read_run(data["run_id"])
        self.assertEqual(len(run_state["steps"]), 1)
        self.assertEqual(run_state["steps"][0]["tool_name"], "bridge_browser_open")

    def test_browser_open_stealth_surfaces_initial_bot_detection_signals(self):
        start = AsyncMock(return_value=json.dumps({"status": "ok", "session_id": "st123"}))
        goto = AsyncMock(return_value=json.dumps({
            "status": "ok",
            "url": "https://example.com/challenge",
            "title": "Just a moment...",
            "bot_protection": "cloudflare",
            "challenge_detected": True,
            "response_status": 403,
        }))

        with patch.object(self.mod, "bridge_stealth_start", start), patch.object(self.mod, "bridge_stealth_goto", goto):
            raw = asyncio.run(self.mod.bridge_browser_open(url="https://example.com", engine="stealth"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["bot_protection"], "cloudflare")
        self.assertTrue(data["challenge_detected"])
        self.assertEqual(data["response_status"], 403)

    def test_browser_open_stealth_forwards_proxy_profile_and_user_agent(self):
        start = AsyncMock(return_value=json.dumps({"status": "ok", "session_id": "st777"}))
        goto = AsyncMock(return_value=json.dumps({
            "status": "ok",
            "url": "https://example.com",
            "title": "Example",
        }))

        with patch.object(self.mod, "bridge_stealth_start", start), patch.object(self.mod, "bridge_stealth_goto", goto):
            raw = asyncio.run(self.mod.bridge_browser_open(
                url="https://example.com",
                engine="stealth",
                proxy="socks5://127.0.0.1:9050",
                user_agent="Mozilla/5.0 Test",
                profile="lab-a",
            ))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["engine"], "stealth")
        start.assert_awaited_once_with(
            headless=True,
            proxy="socks5://127.0.0.1:9050",
            user_agent="Mozilla/5.0 Test",
            profile="lab-a",
        )
        goto.assert_awaited_once_with("st777", "https://example.com")

    def test_browser_open_cdp_creates_dedicated_tab(self):
        ensure_connected = AsyncMock(return_value=object())
        new_tab = AsyncMock(return_value=json.dumps({
            "status": "ok",
            "tab_index": "0:2",
            "url": "https://example.com",
            "title": "Example",
        }))
        self.mod._cdp_browser = object()

        with patch.object(self.mod, "_cdp_ensure_connected", ensure_connected), patch.object(self.mod, "bridge_cdp_new_tab", new_tab):
            raw = asyncio.run(self.mod.bridge_browser_open(url="https://example.com", engine="cdp"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["engine"], "cdp")
        ensure_connected.assert_awaited_once()
        new_tab.assert_awaited_once_with(url="https://example.com")
        self.assertEqual(self.mod._unified_sessions[data["session_id"]]["engine_session_id"], "0:2")

    def test_browser_open_cdp_rejects_stealth_only_options(self):
        raw = asyncio.run(self.mod.bridge_browser_open(
            url="https://example.com",
            engine="cdp",
            proxy="socks5://127.0.0.1:9050",
        ))

        data = json.loads(raw)
        self.assertFalse(data["ok"])
        self.assertIn("stealth-only", data["error"])

    def test_browser_open_auto_falls_back_to_cdp_when_stealth_start_fails(self):
        start = AsyncMock(return_value=json.dumps({"status": "error", "error": "launch failed"}))
        ensure_connected = AsyncMock(return_value=object())
        new_tab = AsyncMock(return_value=json.dumps({
            "status": "ok",
            "tab_index": "0:5",
            "url": "https://example.com",
            "title": "Example",
        }))
        self.mod._cdp_browser = object()

        with patch.object(self.mod, "bridge_stealth_start", start), \
             patch.object(self.mod, "_cdp_ensure_connected", ensure_connected), \
             patch.object(self.mod, "bridge_cdp_new_tab", new_tab):
            raw = asyncio.run(self.mod.bridge_browser_open(url="https://example.com", engine="auto"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["engine"], "cdp")
        self.assertEqual(data["fallback_from"], "stealth")
        self.assertEqual(data["fallback_reason"], "launch failed")
        start.assert_awaited_once_with(headless=True, proxy="", user_agent="", profile="")
        ensure_connected.assert_awaited_once()
        new_tab.assert_awaited_once_with(url="https://example.com")

    def test_browser_open_auto_with_stealth_options_does_not_fallback_to_cdp(self):
        start = AsyncMock(return_value=json.dumps({"status": "error", "error": "launch failed"}))
        ensure_connected = AsyncMock(return_value=object())
        new_tab = AsyncMock()
        self.mod._cdp_browser = object()

        with patch.object(self.mod, "bridge_stealth_start", start), \
             patch.object(self.mod, "_cdp_ensure_connected", ensure_connected), \
             patch.object(self.mod, "bridge_cdp_new_tab", new_tab):
            raw = asyncio.run(self.mod.bridge_browser_open(
                url="https://example.com",
                engine="auto",
                proxy="socks5://127.0.0.1:9050",
            ))

        data = json.loads(raw)
        self.assertFalse(data["ok"])
        self.assertEqual(data["engine"], "stealth")
        self.assertEqual(data["error"], "launch failed")
        ensure_connected.assert_not_awaited()
        new_tab.assert_not_called()

    def test_browser_open_auto_falls_back_to_cdp_when_stealth_navigation_fails(self):
        start = AsyncMock(return_value=json.dumps({"status": "ok", "session_id": "st123"}))
        goto = AsyncMock(return_value=json.dumps({"status": "error", "error": "navigation failed"}))
        close = AsyncMock(return_value=json.dumps({"status": "ok", "session_id": "st123"}))
        ensure_connected = AsyncMock(return_value=object())
        new_tab = AsyncMock(return_value=json.dumps({
            "status": "ok",
            "tab_index": "0:6",
            "url": "https://fallback.example",
            "title": "Fallback",
        }))
        self.mod._cdp_browser = object()

        with patch.object(self.mod, "bridge_stealth_start", start), \
             patch.object(self.mod, "bridge_stealth_goto", goto), \
             patch.object(self.mod, "bridge_stealth_close", close), \
             patch.object(self.mod, "_cdp_ensure_connected", ensure_connected), \
             patch.object(self.mod, "bridge_cdp_new_tab", new_tab):
            raw = asyncio.run(self.mod.bridge_browser_open(url="https://example.com", engine="auto"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["engine"], "cdp")
        self.assertEqual(data["fallback_from"], "stealth")
        self.assertEqual(data["fallback_reason"], "navigation failed")
        close.assert_awaited_once_with("st123")

    def test_browser_navigate_prunes_stale_unified_stealth_session(self):
        self.mod._unified_sessions["unified-stale"] = {
            "engine": "stealth",
            "engine_session_id": "missing-stealth",
            "run_id": "unified-stale",
            "created_at": time.time(),
        }

        goto = AsyncMock(return_value=json.dumps({
            "status": "error",
            "error": "session 'missing-stealth' not found",
        }))

        with patch.object(self.mod, "bridge_stealth_goto", goto):
            raw = asyncio.run(self.mod.bridge_browser_nav("unified-stale", "https://example.com"))

        data = json.loads(raw)
        self.assertFalse(data["ok"])
        self.assertTrue(data["stale_session_pruned"])
        self.assertNotIn("unified-stale", self.mod._unified_sessions)

    def test_browser_observe_reads_unified_stealth_session(self):
        self.mod._unified_sessions["unified-observe"] = {
            "engine": "stealth",
            "engine_session_id": "st-observe",
            "run_id": "unified-observe",
            "created_at": time.time(),
        }
        evaluate = AsyncMock(return_value=json.dumps({
            "status": "ok",
            "result": {
                "url": "https://example.com/form",
                "title": "Form",
                "element_count": 1,
                "elements": [
                    {"ref": "bref-1", "tag": "button", "label": "Submit"},
                ],
            },
        }))

        with patch.object(self.mod, "bridge_stealth_evaluate", evaluate):
            raw = asyncio.run(self.mod.bridge_browser_observe("unified-observe", max_nodes=25))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["element_count"], 1)
        self.assertEqual(data["elements"][0]["ref"], "bref-1")
        self.assertEqual(data["elements"][0]["label"], "Submit")
        evaluate.assert_awaited_once()

    def test_browser_find_refs_returns_scored_candidates(self):
        self.mod._unified_sessions["unified-find"] = {
            "engine": "stealth",
            "engine_session_id": "st-find",
            "run_id": "unified-find",
            "created_at": time.time(),
        }

        async def fake_observe_raw(_session_id, _session, *, max_nodes):
            self.assertGreaterEqual(max_nodes, 50)
            return {
                "status": "ok",
                "url": "https://example.com/form",
                "title": "Form",
                "elements": [
                    {"ref": "bref-1", "tag": "input", "name": "email", "label": "Email", "text": "", "placeholder": "creator@example.com", "x": 0, "y": 10},
                    {"ref": "bref-2", "tag": "button", "role": "button", "label": "Join List", "text": "Join List", "x": 0, "y": 20},
                ],
                "element_count": 2,
            }

        with patch.object(self.mod, "_browser_observe_raw", side_effect=fake_observe_raw):
            raw = asyncio.run(self.mod.bridge_browser_find_refs("unified-find", query="join list", max_results=3))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["candidates"][0]["ref"], "bref-2")
        self.assertGreater(data["candidates"][0]["score"], 0)

    def test_browser_find_refs_supports_explicit_name_filter(self):
        self.mod._unified_sessions["unified-find-name"] = {
            "engine": "cdp",
            "engine_session_id": "0:8",
            "run_id": "unified-find-name",
            "created_at": time.time(),
        }

        async def fake_observe_raw(_session_id, _session, *, max_nodes):
            return {
                "status": "ok",
                "url": "https://example.com/form",
                "title": "Form",
                "elements": [
                    {"ref": "bref-1", "tag": "input", "name": "email", "label": "Email", "text": "", "placeholder": "creator@example.com", "x": 0, "y": 10},
                    {"ref": "bref-2", "tag": "input", "name": "name", "label": "Name", "text": "", "placeholder": "Creator Name", "x": 0, "y": 20},
                ],
                "element_count": 2,
            }

        with patch.object(self.mod, "_browser_observe_raw", side_effect=fake_observe_raw):
            raw = asyncio.run(self.mod.bridge_browser_find_refs("unified-find-name", name="email"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["candidates"][0]["ref"], "bref-1")

    def test_browser_click_ref_uses_bridge_ref_selector(self):
        self.mod._unified_sessions["unified-ref-click"] = {
            "engine": "stealth",
            "engine_session_id": "st-ref-click",
            "run_id": "unified-ref-click",
            "created_at": time.time(),
        }
        click = AsyncMock(return_value=json.dumps({"status": "ok"}))

        with patch.object(self.mod, "bridge_stealth_click", click):
            raw = asyncio.run(self.mod.bridge_browser_click_ref("unified-ref-click", "bref-12"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        click.assert_awaited_once_with("st-ref-click", '[data-bridge-ref="bref-12"]')

    def test_browser_fill_ref_uses_bridge_ref_selector_for_cdp(self):
        self.mod._unified_sessions["unified-ref-fill"] = {
            "engine": "cdp",
            "engine_session_id": "0:9",
            "run_id": "unified-ref-fill",
            "created_at": time.time(),
        }
        fill = AsyncMock(return_value=json.dumps({"status": "ok"}))

        with patch.object(self.mod, "bridge_cdp_fill", fill):
            raw = asyncio.run(self.mod.bridge_browser_fill_ref("unified-ref-fill", "bref-77", "hello"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        fill.assert_awaited_once_with('[data-bridge-ref="bref-77"]', "hello", tab_index="0:9")

    def test_browser_verify_returns_structured_match_state(self):
        self.mod._unified_sessions["unified-verify"] = {
            "engine": "stealth",
            "engine_session_id": "st-verify",
            "run_id": "unified-verify",
            "created_at": time.time(),
        }
        evaluate = AsyncMock(return_value=json.dumps({
            "status": "ok",
            "result": {
                "url": "https://example.com/form",
                "title": "Form",
                "text_preview": "Newsletter Signup",
                "matches": {
                    "url_contains": True,
                    "title_contains": True,
                    "text_contains": True,
                    "selector_exists": True,
                    "selector_missing": True,
                    "value_contains": True,
                    "value_equals": True,
                    "active_selector": True,
                },
                "ok": True,
            },
        }))

        with patch.object(self.mod, "bridge_stealth_evaluate", evaluate):
            raw = asyncio.run(
                self.mod.bridge_browser_verify(
                    "unified-verify",
                    url_contains="example.com",
                    title_contains="Form",
                    text_contains="Newsletter",
                    selector_exists="#email",
                    selector_missing="#missing",
                    value_selector="#email",
                    value_contains="creator",
                    value_equals="creator@example.com",
                    active_selector="#email",
                )
            )

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertTrue(data["verified"])
        self.assertEqual(data["matches"]["selector_exists"], True)
        evaluate.assert_awaited_once()

    def test_browser_click_ref_verify_combines_action_and_verification(self):
        self.mod._unified_sessions["unified-click-verify"] = {
            "engine": "stealth",
            "engine_session_id": "st-click-verify",
            "run_id": "unified-click-verify",
            "created_at": time.time(),
        }
        click = AsyncMock(return_value=json.dumps({"ok": True, "status": "ok", "session_id": "unified-click-verify"}))
        verify = AsyncMock(return_value=json.dumps({
            "ok": True,
            "status": "ok",
            "verified": True,
            "matches": {"active_selector": True},
            "url": "https://example.com/form",
            "title": "Form",
        }))

        with patch.object(self.mod, "bridge_browser_click_ref", click), patch.object(self.mod, "bridge_browser_verify", verify):
            raw = asyncio.run(
                self.mod.bridge_browser_click_ref_verify(
                    "unified-click-verify",
                    "bref-2",
                    active_selector="#name",
                )
            )

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertTrue(data["verified"])
        self.assertEqual(data["matches"]["active_selector"], True)
        click.assert_awaited_once_with("unified-click-verify", "bref-2")
        verify.assert_awaited_once()

    def test_browser_fill_ref_verify_combines_action_and_value_verification(self):
        self.mod._unified_sessions["unified-fill-verify"] = {
            "engine": "cdp",
            "engine_session_id": "0:11",
            "run_id": "unified-fill-verify",
            "created_at": time.time(),
        }
        fill = AsyncMock(return_value=json.dumps({"ok": True, "status": "ok", "session_id": "unified-fill-verify"}))
        verify = AsyncMock(return_value=json.dumps({
            "ok": True,
            "status": "ok",
            "verified": True,
            "matches": {"value_equals": True},
            "value_text": "creator@example.com",
            "url": "https://example.com/form",
            "title": "Form",
        }))

        with patch.object(self.mod, "bridge_browser_fill_ref", fill), patch.object(self.mod, "bridge_browser_verify", verify):
            raw = asyncio.run(
                self.mod.bridge_browser_fill_ref_verify(
                    "unified-fill-verify",
                    "bref-1",
                    "creator@example.com",
                )
            )

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertTrue(data["verified"])
        self.assertEqual(data["value_text"], "creator@example.com")
        fill.assert_awaited_once_with("unified-fill-verify", "bref-1", "creator@example.com")
        verify.assert_awaited_once()

    def test_browser_fingerprint_snapshot_reads_unified_stealth_session(self):
        self.mod._unified_sessions["unified-fp"] = {
            "engine": "stealth",
            "engine_session_id": "st-fp",
            "run_id": "unified-fp",
            "created_at": time.time(),
        }
        snapshot = {"userAgent": "UA", "language": "en-US", "webdriver": False}
        probe = AsyncMock(return_value=json.dumps({"status": "ok", "snapshot": snapshot}))

        with patch.object(self.mod, "bridge_stealth_fingerprint_snapshot", probe):
            raw = asyncio.run(self.mod.bridge_browser_fingerprint_snapshot("unified-fp"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["snapshot"], snapshot)
        probe.assert_awaited_once_with("st-fp")

    def test_browser_fingerprint_snapshot_prunes_stale_unified_stealth_session(self):
        self.mod._unified_sessions["unified-fp-stale"] = {
            "engine": "stealth",
            "engine_session_id": "missing-stealth",
            "run_id": "unified-fp-stale",
            "created_at": time.time(),
        }
        probe = AsyncMock(return_value=json.dumps({
            "status": "error",
            "error": "session 'missing-stealth' not found",
        }))

        with patch.object(self.mod, "bridge_stealth_fingerprint_snapshot", probe):
            raw = asyncio.run(self.mod.bridge_browser_fingerprint_snapshot("unified-fp-stale"))

        data = json.loads(raw)
        self.assertFalse(data["ok"])
        self.assertTrue(data["stale_session_pruned"])
        self.assertNotIn("unified-fp-stale", self.mod._unified_sessions)

    def test_browser_fingerprint_snapshot_reads_unified_cdp_session(self):
        self.mod._unified_sessions["unified-cdp-fp"] = {
            "engine": "cdp",
            "engine_session_id": "0:7",
            "run_id": "unified-cdp-fp",
            "created_at": time.time(),
        }
        snapshot = {"userAgent": "UA-CDP", "platform": "Linux x86_64"}
        evaluate = AsyncMock(return_value=json.dumps({"status": "ok", "result": snapshot}))

        with patch.object(self.mod, "bridge_cdp_evaluate", evaluate):
            raw = asyncio.run(self.mod.bridge_browser_fingerprint_snapshot("unified-cdp-fp"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["snapshot"], snapshot)
        self.assertIn("navigator.userAgent", evaluate.await_args.args[0])

    def test_browser_navigate_preserves_bot_detection_signals(self):
        self.mod._unified_sessions["unified-bot"] = {
            "engine": "stealth",
            "engine_session_id": "st-bot",
            "run_id": "unified-bot",
            "created_at": time.time(),
        }

        goto = AsyncMock(return_value=json.dumps({
            "status": "ok",
            "url": "https://example.com/challenge",
            "bot_protection": "cloudflare",
            "challenge_detected": True,
            "response_status": 403,
        }))

        with patch.object(self.mod, "bridge_stealth_goto", goto):
            raw = asyncio.run(self.mod.bridge_browser_nav("unified-bot", "https://example.com"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["bot_protection"], "cloudflare")
        self.assertTrue(data["challenge_detected"])
        self.assertEqual(data["response_status"], 403)

    def test_browser_action_returns_structured_pending_approval(self):
        screenshot_path = os.path.join(self.tmpdir, "browser_action.png")
        with open(screenshot_path, "wb") as handle:
            handle.write(b"png")

        playwright_calls = AsyncMock(return_value=[
            {"text": "navigated"},
            {"text": f"saved screenshot {screenshot_path}"},
        ])

        async def fake_bridge_post(_path, **_kwargs):
            return _DummyResponse({"status": "pending_approval", "request_id": "req-browser"})

        with patch.object(self.mod, "_playwright_mcp_session", playwright_calls), patch.object(self.mod, "_bridge_post", fake_bridge_post):
            raw = asyncio.run(self.mod.bridge_browser_action("https://example.com", "Log into dashboard"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "pending_approval")
        self.assertEqual(data["request_id"], "req-browser")
        self.assertEqual(data["source"], "browser")
        self.assertTrue(data["run_id"].startswith("browser_action_"))

        run_state = journal.read_run(data["run_id"])
        self.assertEqual(len(run_state["steps"]), 1)
        self.assertEqual(run_state["steps"][0]["status"], "pending_approval")

    def test_stealth_cleanup_loop_logs_session_id_when_cookie_save_fails(self):
        session = self.mod.StealthSession(
            session_id="st-cleanup",
            browser=SimpleNamespace(close=AsyncMock()),
            page=SimpleNamespace(context=None),
            pw_context=SimpleNamespace(stop=AsyncMock()),
            agent_id="codex",
            profile="profile-a",
            last_used=time.time(),
        )
        self.mod._stealth_sessions["st-cleanup"] = session

        sleep_calls = {"count": 0}

        async def fake_sleep(_seconds):
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError()

        with patch.object(self.mod, "_stealth_save_cookies", AsyncMock(side_effect=RuntimeError("boom"))), \
             patch.object(self.mod.asyncio, "sleep", side_effect=fake_sleep), \
             patch.object(self.mod.log, "warning") as log_warning:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.mod._stealth_cleanup_loop())

        log_warning.assert_any_call("Cookie save failed for session %s: %s", "st-cleanup", unittest.mock.ANY)

    def test_stealth_close_prunes_linked_unified_sessions(self):
        session = self.mod.StealthSession(
            session_id="st-linked",
            browser=SimpleNamespace(close=AsyncMock()),
            page=SimpleNamespace(context=None),
            pw_context=SimpleNamespace(stop=AsyncMock()),
            agent_id="codex",
        )
        self.mod._stealth_sessions["st-linked"] = session
        self.mod._unified_sessions["unified-a"] = {
            "engine": "stealth",
            "engine_session_id": "st-linked",
            "run_id": "unified-a",
            "created_at": time.time(),
        }

        with patch.object(self.mod, "_stealth_save_cookies", AsyncMock()):
            raw = asyncio.run(self.mod.bridge_stealth_close("st-linked"))

        data = json.loads(raw)
        self.assertEqual(data["status"], "ok")
        self.assertNotIn("unified-a", self.mod._unified_sessions)

    def test_stealth_close_prunes_linked_unified_sessions_even_on_close_error(self):
        session = self.mod.StealthSession(
            session_id="st-linked-error",
            browser=SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("close failed"))),
            page=SimpleNamespace(context=None),
            pw_context=SimpleNamespace(stop=AsyncMock()),
            agent_id="codex",
        )
        self.mod._stealth_sessions["st-linked-error"] = session
        self.mod._unified_sessions["unified-error"] = {
            "engine": "stealth",
            "engine_session_id": "st-linked-error",
            "run_id": "unified-error",
            "created_at": time.time(),
        }

        with patch.object(self.mod, "_stealth_save_cookies", AsyncMock()):
            raw = asyncio.run(self.mod.bridge_stealth_close("st-linked-error"))

        data = json.loads(raw)
        self.assertEqual(data["status"], "error")
        self.assertNotIn("unified-error", self.mod._unified_sessions)
        session.pw_context.stop.assert_awaited_once()

    def test_stealth_cleanup_prunes_unified_sessions_for_expired_session(self):
        session = self.mod.StealthSession(
            session_id="st-expired",
            browser=SimpleNamespace(close=AsyncMock()),
            page=SimpleNamespace(context=None),
            pw_context=SimpleNamespace(stop=AsyncMock()),
            agent_id="codex",
            last_used=time.time() - (self.mod._STEALTH_IDLE_TIMEOUT + 5),
        )
        self.mod._stealth_sessions["st-expired"] = session
        self.mod._unified_sessions["unified-expired"] = {
            "engine": "stealth",
            "engine_session_id": "st-expired",
            "run_id": "unified-expired",
            "created_at": time.time(),
        }

        sleep_calls = {"count": 0}

        async def fake_sleep(_seconds):
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError()

        with patch.object(self.mod, "_stealth_save_cookies", AsyncMock()), \
             patch.object(self.mod.asyncio, "sleep", side_effect=fake_sleep):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.mod._stealth_cleanup_loop())

        self.assertNotIn("unified-expired", self.mod._unified_sessions)
        session.browser.close.assert_awaited_once()
        session.pw_context.stop.assert_awaited_once()

    def test_stealth_cleanup_stops_playwright_even_when_browser_close_fails(self):
        session = self.mod.StealthSession(
            session_id="st-expired-error",
            browser=SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("close failed"))),
            page=SimpleNamespace(context=None),
            pw_context=SimpleNamespace(stop=AsyncMock()),
            agent_id="codex",
            last_used=time.time() - (self.mod._STEALTH_IDLE_TIMEOUT + 5),
        )
        self.mod._stealth_sessions["st-expired-error"] = session

        sleep_calls = {"count": 0}

        async def fake_sleep(_seconds):
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError()

        with patch.object(self.mod, "_stealth_save_cookies", AsyncMock()), \
             patch.object(self.mod.asyncio, "sleep", side_effect=fake_sleep):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.mod._stealth_cleanup_loop())

        session.pw_context.stop.assert_awaited_once()

    def test_stealth_start_proxy_blocks_service_workers(self):
        context = SimpleNamespace()
        context.grant_permissions = AsyncMock()
        context.route = AsyncMock()
        context.add_init_script = AsyncMock()
        context.on = lambda *_args, **_kwargs: None
        page = SimpleNamespace(context=context)
        context.new_page = AsyncMock(return_value=page)
        cdp = SimpleNamespace(send=AsyncMock())
        context.new_cdp_session = AsyncMock(return_value=cdp)

        class _Browser:
            def __init__(self):
                self.context_kwargs = None

            async def new_context(self, **kwargs):
                self.context_kwargs = kwargs
                return context

            async def close(self):
                return None

        browser = _Browser()

        class _Chromium:
            async def launch(self, **_kwargs):
                return browser

        class _Playwright:
            def __init__(self):
                self.chromium = _Chromium()

            async def stop(self):
                return None

        class _AsyncPlaywrightFactory:
            def __init__(self, pw):
                self._pw = pw

            def __call__(self):
                return self

            async def start(self):
                return self._pw

        fake_module = SimpleNamespace(async_playwright=_AsyncPlaywrightFactory(_Playwright()))

        def fake_create_task(coro):
            coro.close()
            return SimpleNamespace(done=lambda: False)

        with patch.dict(sys.modules, {"playwright.async_api": fake_module}), \
             patch.object(self.mod.asyncio, "create_task", side_effect=fake_create_task):
            raw = asyncio.run(self.mod.bridge_stealth_start(proxy="socks5://127.0.0.1:9050"))

        data = json.loads(raw)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(browser.context_kwargs["service_workers"], "block")
        self.assertEqual(browser.context_kwargs["timezone_id"], "Etc/UTC")
        self.assertEqual(browser.context_kwargs["locale"], "en-US")
        self.assertEqual(browser.context_kwargs["user_agent"], self.mod._STEALTH_TOR_UA)
        self.assertEqual(browser.context_kwargs["extra_http_headers"]["Accept-Language"], "en-US")
        init_scripts = [call.args[0] for call in context.add_init_script.await_args_list]
        self.assertEqual(init_scripts, self.mod._stealth_scripts_for_session(is_proxy=True, firefox_like=True))
        runtime_expressions = [
            call.args[1]["expression"]
            for call in cdp.send.await_args_list
            if call.args[0] == "Runtime.evaluate"
        ]
        self.assertEqual(runtime_expressions, self.mod._stealth_scripts_for_session(is_proxy=True, firefox_like=True))

    def test_stealth_fingerprint_snapshot_returns_structured_probe(self):
        page = SimpleNamespace(evaluate=AsyncMock(return_value={
            "userAgent": "UA",
            "language": "en-US",
            "webdriver": False,
        }))
        self.mod._stealth_sessions["st-probe"] = self.mod.StealthSession(
            session_id="st-probe",
            browser=SimpleNamespace(close=AsyncMock()),
            page=page,
            pw_context=SimpleNamespace(stop=AsyncMock()),
            agent_id="codex",
        )

        raw = asyncio.run(self.mod.bridge_stealth_fingerprint_snapshot("st-probe"))

        data = json.loads(raw)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["session_id"], "st-probe")
        self.assertEqual(data["snapshot"]["userAgent"], "UA")
        self.assertIn("navigator.userAgent", page.evaluate.await_args.args[0])

    def test_stealth_start_non_proxy_sets_locale_to_match_accept_language(self):
        context = SimpleNamespace()
        context.route = AsyncMock()
        context.add_init_script = AsyncMock()
        context.on = lambda *_args, **_kwargs: None
        page = SimpleNamespace(context=context)
        context.new_page = AsyncMock(return_value=page)
        cdp = SimpleNamespace(send=AsyncMock())
        context.new_cdp_session = AsyncMock(return_value=cdp)

        class _Browser:
            def __init__(self):
                self.context_kwargs = None

            async def new_context(self, **kwargs):
                self.context_kwargs = kwargs
                return context

            async def close(self):
                return None

        browser = _Browser()

        class _Chromium:
            async def launch(self, **_kwargs):
                return browser

        class _Playwright:
            def __init__(self):
                self.chromium = _Chromium()

            async def stop(self):
                return None

        class _AsyncPlaywrightFactory:
            def __init__(self, pw):
                self._pw = pw

            def __call__(self):
                return self

            async def start(self):
                return self._pw

        fake_module = SimpleNamespace(async_playwright=_AsyncPlaywrightFactory(_Playwright()))

        def fake_create_task(coro):
            coro.close()
            return SimpleNamespace(done=lambda: False)

        with patch.dict(sys.modules, {"playwright.async_api": fake_module}), \
             patch.object(self.mod.asyncio, "create_task", side_effect=fake_create_task):
            raw = asyncio.run(self.mod.bridge_stealth_start())

        data = json.loads(raw)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(browser.context_kwargs["locale"], "en-US")
        self.assertEqual(browser.context_kwargs["extra_http_headers"]["Accept-Language"], "en-US")
        self.assertNotIn("service_workers", browser.context_kwargs)
        init_scripts = [call.args[0] for call in context.add_init_script.await_args_list]
        self.assertEqual(init_scripts, self.mod._stealth_scripts_for_session(is_proxy=False))
        runtime_expressions = [
            call.args[1]["expression"]
            for call in cdp.send.await_args_list
            if call.args[0] == "Runtime.evaluate"
        ]
        self.assertEqual(runtime_expressions, self.mod._stealth_scripts_for_session(is_proxy=False))

    def test_non_proxy_script_manifest_includes_permission_and_notification_spoofs(self):
        script_blob = "\n".join(self.mod._stealth_scripts_for_session(is_proxy=False))
        self.assertIn("Notification.permission", script_blob)
        self.assertIn("navigator.permissions.query", script_blob)
        self.assertIn("clipboard-read", script_blob)
        self.assertIn("Navigator.prototype, 'webdriver'", script_blob)

    def test_proxy_script_manifest_keeps_permission_and_notification_spoofs(self):
        script_blob = "\n".join(self.mod._stealth_scripts_for_session(is_proxy=True))
        self.assertIn("Notification.permission", script_blob)
        self.assertIn("navigator.permissions.query", script_blob)

    def test_firefox_like_script_manifest_hides_service_worker_surface(self):
        script_blob = "\n".join(self.mod._stealth_scripts_for_session(is_proxy=False, firefox_like=True))
        self.assertIn("Navigator.prototype, 'serviceWorker'", script_blob)

    def test_firefox_like_script_manifest_stabilizes_screen_surface(self):
        script_blob = "\n".join(self.mod._stealth_scripts_for_session(is_proxy=False, firefox_like=True))
        self.assertIn("Screen.prototype", script_blob)
        self.assertIn("availHeight", script_blob)
        self.assertIn("1536", script_blob)

    def test_firefox_like_script_manifest_reports_pdf_viewer_enabled(self):
        script_blob = "\n".join(self.mod._stealth_scripts_for_session(is_proxy=False, firefox_like=True))
        self.assertIn("pdfViewerEnabled", script_blob)
        self.assertIn("true", script_blob)

    def test_worker_navigator_spoof_uses_firefox_like_languages(self):
        script_blob = self.mod._STEALTH_WORKER_NAVIGATOR_SPOOF
        self.assertIn("Object.freeze(['en-US', 'en'])", script_blob)

    def test_stealth_start_custom_firefox_user_agent_uses_firefox_like_identity_profile(self):
        context = SimpleNamespace()
        context.route = AsyncMock()
        context.add_init_script = AsyncMock()
        context.on = lambda *_args, **_kwargs: None
        page = SimpleNamespace(context=context)
        context.new_page = AsyncMock(return_value=page)
        cdp = SimpleNamespace(send=AsyncMock())
        context.new_cdp_session = AsyncMock(return_value=cdp)

        class _Browser:
            def __init__(self):
                self.context_kwargs = None

            async def new_context(self, **kwargs):
                self.context_kwargs = kwargs
                return context

            async def close(self):
                return None

        browser = _Browser()

        class _Chromium:
            async def launch(self, **_kwargs):
                return browser

        class _Playwright:
            def __init__(self):
                self.chromium = _Chromium()

            async def stop(self):
                return None

        class _AsyncPlaywrightFactory:
            def __init__(self, pw):
                self._pw = pw

            def __call__(self):
                return self

            async def start(self):
                return self._pw

        fake_module = SimpleNamespace(async_playwright=_AsyncPlaywrightFactory(_Playwright()))

        def fake_create_task(coro):
            coro.close()
            return SimpleNamespace(done=lambda: False)

        with patch.dict(sys.modules, {"playwright.async_api": fake_module}), \
             patch.object(self.mod.asyncio, "create_task", side_effect=fake_create_task):
            raw = asyncio.run(self.mod.bridge_stealth_start(user_agent=self.mod._STEALTH_TOR_UA))

        data = json.loads(raw)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(browser.context_kwargs["user_agent"], self.mod._STEALTH_TOR_UA)
        init_scripts = [call.args[0] for call in context.add_init_script.await_args_list]
        self.assertIn(self.mod._STEALTH_HARDWARE_SPOOF, init_scripts)
        self.assertIn(self.mod._STEALTH_FIREFOX_LIKE_POPUP_NAV, init_scripts)
        context.route.assert_awaited()
        user_agent_override = [
            call.args[1]
            for call in cdp.send.await_args_list
            if call.args[0] == "Emulation.setUserAgentOverride"
        ][0]
        self.assertEqual(user_agent_override["platform"], "Win32")
        self.assertEqual(browser.context_kwargs["timezone_id"], "Etc/UTC")

    def test_install_stealth_worker_route_treats_ua_bearing_blank_dest_scripts_as_workers(self):
        captured_handler = None

        async def fake_route(pattern, handler):
            nonlocal captured_handler
            self.assertEqual(pattern, "**/*")
            captured_handler = handler

        context = SimpleNamespace(route=AsyncMock(side_effect=fake_route))

        asyncio.run(self.mod._install_stealth_worker_route(context))

        self.assertIsNotNone(captured_handler)
        response = SimpleNamespace(
            text=AsyncMock(return_value="self.postMessage('ok');"),
            headers={"Content-Length": "22", "content-type": "application/javascript"},
        )
        route = SimpleNamespace(
            continue_=AsyncMock(),
            fetch=AsyncMock(return_value=response),
            fulfill=AsyncMock(),
        )
        request = SimpleNamespace(
            resource_type="script",
            headers={
                "accept": "*/*",
                "user-agent": self.mod._STEALTH_TOR_UA,
            },
        )

        asyncio.run(captured_handler(route, request))

        route.continue_.assert_not_awaited()
        route.fetch.assert_awaited_once()
        route.fulfill.assert_awaited_once()
        fulfill_kwargs = route.fulfill.await_args.kwargs
        self.assertTrue(fulfill_kwargs["body"].startswith(self.mod._STEALTH_WORKER_NAVIGATOR_SPOOF))
        self.assertNotIn("Content-Length", fulfill_kwargs["headers"])

    def test_install_stealth_worker_route_strips_chromium_client_hints_for_firefox_like_requests(self):
        captured_handler = None

        async def fake_route(pattern, handler):
            nonlocal captured_handler
            self.assertEqual(pattern, "**/*")
            captured_handler = handler

        context = SimpleNamespace(route=AsyncMock(side_effect=fake_route))

        asyncio.run(self.mod._install_stealth_worker_route(context))

        self.assertIsNotNone(captured_handler)
        route = SimpleNamespace(
            continue_=AsyncMock(),
            fetch=AsyncMock(),
            fulfill=AsyncMock(),
        )
        request = SimpleNamespace(
            resource_type="document",
            headers={
                "accept": "text/html",
                "user-agent": self.mod._STEALTH_TOR_UA,
                "accept-language": "en-US",
                "sec-ch-ua": '"Chromium";v="145"',
                "sec-ch-ua-platform": '"Windows"',
                "sec-ch-ua-mobile": "?0",
            },
        )

        asyncio.run(captured_handler(route, request))

        route.fetch.assert_not_awaited()
        route.fulfill.assert_not_awaited()
        route.continue_.assert_awaited_once()
        forwarded_headers = route.continue_.await_args.kwargs["headers"]
        self.assertEqual(forwarded_headers["user-agent"], self.mod._STEALTH_TOR_UA)
        self.assertEqual(forwarded_headers["accept-language"], "en-US")
        self.assertNotIn("sec-ch-ua", forwarded_headers)
        self.assertNotIn("sec-ch-ua-platform", forwarded_headers)
        self.assertNotIn("sec-ch-ua-mobile", forwarded_headers)

    def test_tor_proxy_identity_spoof_hides_chromium_only_navigator_fields(self):
        script = self.mod._STEALTH_HARDWARE_SPOOF
        self.assertIn("hardwareConcurrency', {get: () => 2", script)
        self.assertIn("deviceMemory', {get: () => undefined", script)
        self.assertIn("vendor: ''", script)
        self.assertIn("productSub: '20100101'", script)
        self.assertIn("oscpu: 'Windows NT 10.0; Win64; x64'", script)

    def test_stealth_goto_reuses_proxy_script_manifest_for_both_injection_passes(self):
        page = SimpleNamespace(
            goto=AsyncMock(return_value=None),
            evaluate=AsyncMock(),
            wait_for_load_state=AsyncMock(),
            title=AsyncMock(return_value="Example"),
            content=AsyncMock(return_value="<html>ok</html>"),
            url="https://example.com",
        )
        self.mod._stealth_sessions["st-proxy"] = self.mod.StealthSession(
            session_id="st-proxy",
            browser=SimpleNamespace(close=AsyncMock()),
            page=page,
            pw_context=SimpleNamespace(stop=AsyncMock()),
            agent_id="codex",
            is_proxy=True,
        )

        raw = asyncio.run(self.mod.bridge_stealth_goto("st-proxy", "https://example.com"))

        data = json.loads(raw)
        self.assertEqual(data["status"], "ok")
        scripts = self.mod._stealth_scripts_for_session(is_proxy=True)
        evaluated = [call.args[0] for call in page.evaluate.await_args_list]
        self.assertEqual(evaluated, scripts + scripts)

    def test_stealth_goto_reports_bot_protection_and_challenge_state(self):
        response = SimpleNamespace(
            headers={"cf-ray": "1234", "server": "cloudflare"},
            status=403,
        )
        page = SimpleNamespace(
            goto=AsyncMock(return_value=response),
            evaluate=AsyncMock(),
            wait_for_load_state=AsyncMock(),
            title=AsyncMock(return_value="Just a moment..."),
            content=AsyncMock(return_value="<html>Checking your browser before accessing example.com</html>"),
            url="https://example.com/challenge",
        )
        self.mod._stealth_sessions["st-bot"] = self.mod.StealthSession(
            session_id="st-bot",
            browser=SimpleNamespace(close=AsyncMock()),
            page=page,
            pw_context=SimpleNamespace(stop=AsyncMock()),
            agent_id="codex",
        )

        raw = asyncio.run(self.mod.bridge_stealth_goto("st-bot", "https://example.com"))

        data = json.loads(raw)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["bot_protection"], "cloudflare")
        self.assertTrue(data["challenge_detected"])
        self.assertEqual(data["response_status"], 403)

    def test_browser_close_prunes_orphaned_unified_stealth_session(self):
        self.mod._unified_sessions["unified-orphan"] = {
            "engine": "stealth",
            "engine_session_id": "missing-stealth",
            "run_id": "unified-orphan",
            "created_at": time.time(),
        }

        raw = asyncio.run(self.mod.bridge_browser_cls("unified-orphan"))

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertTrue(data["stale_session_pruned"])
        self.assertTrue(data["engine_session_missing"])
        self.assertNotIn("unified-orphan", self.mod._unified_sessions)

    def test_browser_sessions_prunes_orphaned_unified_stealth_sessions(self):
        self.mod._unified_sessions["unified-live"] = {
            "engine": "stealth",
            "engine_session_id": "st-live",
            "run_id": "unified-live",
            "created_at": time.time(),
            "url": "https://live.example",
        }
        self.mod._unified_sessions["unified-orphan"] = {
            "engine": "stealth",
            "engine_session_id": "missing-stealth",
            "run_id": "unified-orphan",
            "created_at": time.time(),
            "url": "https://stale.example",
        }
        self.mod._stealth_sessions["st-live"] = self.mod.StealthSession(
            session_id="st-live",
            browser=SimpleNamespace(close=AsyncMock()),
            page=SimpleNamespace(context=None),
            pw_context=SimpleNamespace(stop=AsyncMock()),
            agent_id="codex",
        )

        raw = asyncio.run(self.mod.bridge_browser_lst())

        data = json.loads(raw)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["pruned_stale_sessions"], ["unified-orphan"])
        self.assertNotIn("unified-orphan", self.mod._unified_sessions)
        self.assertIn("unified-live", self.mod._unified_sessions)

    def test_server_allows_browser_action_approval_type(self):
        self.assertIn("browser_action", srv.ALLOWED_APPROVAL_ACTIONS)


if __name__ == "__main__":
    unittest.main()
