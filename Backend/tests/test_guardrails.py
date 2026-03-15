from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import guardrails  # noqa: E402


class TestConsequentialToolClassification(unittest.TestCase):
    def test_classify_browser_and_desktop_tools(self):
        browser = guardrails.classify_tool("bridge_browser_click")
        desktop = guardrails.classify_tool("bridge_desktop_click")

        self.assertIsNotNone(browser)
        self.assertEqual(browser["group"], "browser_write")
        self.assertEqual(browser["severity"], "high")

        self.assertIsNotNone(desktop)
        self.assertEqual(desktop["group"], "desktop_control")
        self.assertTrue(guardrails.is_consequential_tool("bridge_desktop_click"))
        self.assertFalse(guardrails.is_consequential_tool("bridge_browser_open"))

    def test_list_consequential_tools_returns_catalog(self):
        catalog = guardrails.list_consequential_tools()
        self.assertIn("browser_write", catalog)
        self.assertIn("desktop_control", catalog)
        self.assertIn("communications", catalog)


class TestConsequentialToolModes(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="guardrails_test_")
        self.violations_dir = os.path.join(self.tmpdir, "logs")
        self.policy_file = os.path.join(self.tmpdir, "guardrails.json")
        self.violations_file = os.path.join(self.violations_dir, "guardrails_violations.jsonl")
        self._orig_file = guardrails.GUARDRAILS_FILE
        self._orig_violations = guardrails.VIOLATIONS_FILE
        self._orig_tracker = dict(guardrails._rate_tracker)
        guardrails.GUARDRAILS_FILE = self.policy_file
        guardrails.VIOLATIONS_FILE = self.violations_file
        guardrails._rate_tracker.clear()

    def tearDown(self):
        guardrails.GUARDRAILS_FILE = self._orig_file
        guardrails.VIOLATIONS_FILE = self._orig_violations
        guardrails._rate_tracker.clear()
        guardrails._rate_tracker.update(self._orig_tracker)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_explicit_allow_blocks_consequential_tools_until_named(self):
        guardrails.set_policy("codex", {"allowed_tools": ["*"], "consequential_tools_mode": "explicit_allow"})

        allowed, reason = guardrails.check_tool_allowed("codex", "bridge_browser_click")
        self.assertFalse(allowed)
        self.assertIn("requires explicit allow", reason)

        guardrails.set_policy(
            "codex",
            {"allowed_tools": ["bridge_browser_click"], "consequential_tools_mode": "explicit_allow"},
        )
        allowed_after, reason_after = guardrails.check_tool_allowed("codex", "bridge_browser_click")
        self.assertTrue(allowed_after)
        self.assertEqual(reason_after, "")

    def test_deny_mode_rejects_consequential_tools_even_with_wildcard(self):
        guardrails.set_policy("codex", {"allowed_tools": ["*"], "consequential_tools_mode": "deny"})

        allowed, reason = guardrails.check_tool_allowed("codex", "bridge_desktop_click")
        self.assertFalse(allowed)
        self.assertIn("denied by guardrails policy", reason)

    def test_invalid_consequential_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            guardrails.set_policy("codex", {"consequential_tools_mode": "invalid"})

    def test_evaluate_policy_reports_tool_and_action_decision(self):
        guardrails.set_policy(
            "codex",
            {
                "allowed_tools": ["bridge_browser_click"],
                "consequential_tools_mode": "explicit_allow",
                "denied_actions": ["delete database"],
            },
        )

        result = guardrails.evaluate_policy(
            "codex",
            tool_name="bridge_browser_click",
            action_text="please delete database rows",
        )

        self.assertTrue(result["tool_allowed"])
        self.assertEqual(result["tool_classification"]["group"], "browser_write")
        self.assertTrue(result["action_denied"])
        self.assertIn("delete database", result["action_reason"])

    def test_evaluate_policy_is_side_effect_free_but_enforcement_logs(self):
        guardrails.set_policy(
            "codex",
            {
                "allowed_tools": [],
                "consequential_tools_mode": "explicit_allow",
                "denied_actions": ["wipe disk"],
            },
        )

        result = guardrails.evaluate_policy(
            "codex",
            tool_name="bridge_desktop_click",
            action_text="wipe disk now",
        )

        self.assertFalse(result["tool_allowed"])
        self.assertTrue(result["action_denied"])
        self.assertFalse(os.path.exists(self.violations_file))

        allowed, _ = guardrails.check_tool_allowed("codex", "bridge_desktop_click")
        denied, _ = guardrails.check_action_denied("codex", "wipe disk now")

        self.assertFalse(allowed)
        self.assertTrue(denied)
        self.assertTrue(os.path.exists(self.violations_file))
        violations = guardrails.get_violations("codex", limit=10)
        self.assertEqual(len(violations), 2)

    def test_evaluate_policy_reports_rate_limit_without_consuming_budget(self):
        guardrails.set_policy("codex", {"rate_limits": {"max_per_minute": 1}})

        exceeded_first, reason_first = guardrails.check_rate_limit("codex")
        self.assertFalse(exceeded_first)
        self.assertEqual(reason_first, "")
        self.assertEqual(len(guardrails._rate_tracker["codex"]), 1)

        result = guardrails.evaluate_policy("codex")

        self.assertTrue(result["rate_limited"])
        self.assertIn("1/minute", result["rate_limit_reason"])
        self.assertTrue(result["rate_limit"]["enabled"])
        self.assertEqual(result["rate_limit"]["max_per_minute"], 1)
        self.assertEqual(result["rate_limit"]["current_count"], 1)
        self.assertEqual(result["rate_limit"]["remaining"], 0)
        self.assertEqual(len(guardrails._rate_tracker["codex"]), 1)
        self.assertFalse(os.path.exists(self.violations_file))

    def test_violation_log_contains_metadata_and_supports_type_filter(self):
        guardrails.set_policy("codex", {"allowed_tools": [], "consequential_tools_mode": "explicit_allow"})

        allowed, _ = guardrails.check_tool_allowed("codex", "bridge_desktop_click")

        self.assertFalse(allowed)
        self.assertTrue(os.path.exists(self.violations_file))

        all_violations = guardrails.get_violations("codex", limit=10)
        tool_violations = guardrails.get_violations("codex", limit=10, violation_type="tool_denied")

        self.assertEqual(len(all_violations), 1)
        self.assertEqual(len(tool_violations), 1)
        self.assertEqual(tool_violations[0]["type"], "tool_denied")
        self.assertEqual(tool_violations[0]["metadata"]["tool_name"], "bridge_desktop_click")
        self.assertEqual(tool_violations[0]["metadata"]["group"], "desktop_control")

    def test_violation_summary_aggregates_recent_entries(self):
        guardrails.set_policy(
            "codex",
            {
                "allowed_tools": [],
                "consequential_tools_mode": "explicit_allow",
                "denied_actions": ["wipe disk"],
            },
        )
        guardrails.check_tool_allowed("codex", "bridge_desktop_click")
        guardrails.check_action_denied("codex", "wipe disk now")

        summary = guardrails.summarize_violations("codex", limit=10)

        self.assertEqual(summary["total_violations"], 2)
        self.assertEqual(summary["by_type"]["tool_denied"], 1)
        self.assertEqual(summary["by_type"]["action_denied"], 1)
        self.assertEqual(summary["by_agent_id"]["codex"], 2)
        self.assertTrue(summary["latest_timestamp"])

    def test_list_presets_and_apply_preset(self):
        presets = guardrails.list_presets()
        self.assertIn("safe_default", presets)
        self.assertIn("creator_operator", presets)
        self.assertIn("admin_operator", presets)

        safe_policy = guardrails.apply_preset("codex", "safe_default")
        safe_allowed, _ = guardrails.check_tool_allowed("codex", "bridge_browser_click")

        self.assertEqual(safe_policy["preset_name"], "safe_default")
        self.assertTrue(safe_policy["preset_applied_at"])
        self.assertFalse(safe_allowed)

        creator_policy = guardrails.apply_preset("codex", "creator_operator")
        creator_allowed, creator_reason = guardrails.check_tool_allowed("codex", "bridge_browser_click")

        self.assertEqual(creator_policy["preset_name"], "creator_operator")
        self.assertTrue(creator_allowed)
        self.assertEqual(creator_reason, "")

    def test_apply_preset_accepts_overrides(self):
        policy = guardrails.apply_preset(
            "codex",
            "safe_default",
            overrides={"rate_limits": {"max_per_minute": 5}},
        )

        self.assertEqual(policy["preset_name"], "safe_default")
        self.assertEqual(policy["rate_limits"]["max_per_minute"], 5)


if __name__ == "__main__":
    unittest.main()
