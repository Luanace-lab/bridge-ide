"""
Tests for engine_routing.py — Smart Engine Routing

Tests cover:
  - TaskCategory enum
  - RoutingDecision dataclass
  - Default routing rules
  - Category-based routing
  - Fallback chains
  - Health-aware routing
  - Agent overrides
  - Explicit preferences
  - Custom rules
  - Status reporting
"""

import os
import sys
import unittest

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_routing import (
    CATEGORY_MODELS,
    DEFAULT_ROUTING_RULES,
    EngineRouter,
    RoutingDecision,
    TaskCategory,
)


class TestTaskCategory(unittest.TestCase):
    """Test TaskCategory enum."""

    def test_all_categories(self):
        expected = {
            "code_review", "code_generation", "documentation",
            "research", "quick_task", "conversation",
            "analysis", "translation", "default",
        }
        actual = {c.value for c in TaskCategory}
        self.assertEqual(actual, expected)


class TestRoutingDecision(unittest.TestCase):
    """Test RoutingDecision dataclass."""

    def test_to_dict(self):
        rd = RoutingDecision(
            engine_name="openai_api",
            model="gpt-4o",
            category="code_review",
            reason="Rule match",
            fallback_chain=["gemini_api", "litellm"],
        )
        d = rd.to_dict()
        self.assertEqual(d["engine_name"], "openai_api")
        self.assertEqual(d["model"], "gpt-4o")
        self.assertEqual(len(d["fallback_chain"]), 2)

    def test_defaults(self):
        rd = RoutingDecision(
            engine_name="echo",
            model="",
            category="default",
            reason="Test",
        )
        self.assertEqual(rd.fallback_chain, [])


class TestDefaultRules(unittest.TestCase):
    """Test default routing rules and models."""

    def test_all_categories_have_rules(self):
        for cat in TaskCategory:
            self.assertIn(cat.value, DEFAULT_ROUTING_RULES,
                          f"Missing rule for {cat.value}")

    def test_all_categories_have_models(self):
        for cat in TaskCategory:
            self.assertIn(cat.value, CATEGORY_MODELS,
                          f"Missing model for {cat.value}")

    def test_rules_have_fallbacks(self):
        for cat, engines in DEFAULT_ROUTING_RULES.items():
            self.assertGreater(len(engines), 0,
                               f"Empty rule for {cat}")


class TestBasicRouting(unittest.TestCase):
    """Test basic routing decisions."""

    def setUp(self):
        self.router = EngineRouter()

    def test_default_category(self):
        decision = self.router.route()
        self.assertNotEqual(decision.engine_name, "")
        self.assertEqual(decision.category, "default")

    def test_code_review_routing(self):
        decision = self.router.route(category="code_review")
        self.assertEqual(decision.category, "code_review")
        # Should pick first available from the chain
        self.assertIn(decision.engine_name, DEFAULT_ROUTING_RULES["code_review"])

    def test_unknown_category_uses_default(self):
        decision = self.router.route(category="nonexistent")
        # Falls back to "default" rules
        self.assertNotEqual(decision.engine_name, "")

    def test_fallback_chain_populated(self):
        decision = self.router.route(category="code_review")
        # Should have other engines as fallbacks
        self.assertIsInstance(decision.fallback_chain, list)

    def test_model_recommendation(self):
        decision = self.router.route(category="quick_task")
        self.assertEqual(decision.model, CATEGORY_MODELS["quick_task"])


class TestHealthAwareRouting(unittest.TestCase):
    """Test health-aware routing."""

    def setUp(self):
        self.router = EngineRouter()

    def test_skip_unhealthy_engine(self):
        # Mark first engine in chain as unhealthy
        chain = DEFAULT_ROUTING_RULES["code_review"]
        first = chain[0]
        self.router.set_health(first, available=False)

        decision = self.router.route(category="code_review")
        # Should skip the unhealthy engine
        self.assertNotEqual(decision.engine_name, first)

    def test_healthy_engine_selected(self):
        self.router.set_health("echo", available=True)
        decision = self.router.route(category="default")
        # echo should be selectable
        self.assertNotEqual(decision.engine_name, "")

    def test_all_unhealthy_uses_last_resort(self):
        # Mark all common engines as unhealthy
        for engine in ["openai_api", "gemini_api", "litellm"]:
            self.router.set_health(engine, available=False)

        decision = self.router.route(category="default")
        # Should still find echo as fallback
        self.assertEqual(decision.engine_name, "echo")


class TestAgentOverrides(unittest.TestCase):
    """Test per-agent engine overrides."""

    def setUp(self):
        self.router = EngineRouter()

    def test_set_override(self):
        self.router.set_override("agent_1", "echo")
        decision = self.router.route(agent_id="agent_1")
        self.assertEqual(decision.engine_name, "echo")
        self.assertIn("override", decision.reason.lower())

    def test_override_takes_priority(self):
        self.router.set_override("agent_1", "echo")
        # Even with explicit category, override wins
        decision = self.router.route(
            category="code_review", agent_id="agent_1"
        )
        self.assertEqual(decision.engine_name, "echo")

    def test_remove_override(self):
        self.router.set_override("agent_1", "echo")
        self.assertTrue(self.router.remove_override("agent_1"))
        decision = self.router.route(agent_id="agent_1")
        # Should no longer be overridden
        self.assertNotEqual(decision.reason, "Agent override")

    def test_remove_nonexistent_override(self):
        self.assertFalse(self.router.remove_override("missing"))


class TestExplicitPreference(unittest.TestCase):
    """Test explicit engine preference."""

    def setUp(self):
        self.router = EngineRouter()

    def test_prefer_specific_engine(self):
        decision = self.router.route(preferred_engine="echo")
        self.assertEqual(decision.engine_name, "echo")
        self.assertIn("preference", decision.reason.lower())

    def test_unknown_preferred_ignored(self):
        decision = self.router.route(preferred_engine="nonexistent")
        # Should fall through to normal routing
        self.assertNotEqual(decision.engine_name, "nonexistent")


class TestCustomRules(unittest.TestCase):
    """Test custom routing rules."""

    def setUp(self):
        self.router = EngineRouter()

    def test_add_rule(self):
        self.router.add_rule("custom_task", ["echo", "litellm"])
        decision = self.router.route(category="custom_task")
        self.assertEqual(decision.engine_name, "echo")

    def test_update_rule(self):
        self.router.add_rule("code_review", ["echo"])
        decision = self.router.route(category="code_review")
        self.assertEqual(decision.engine_name, "echo")

    def test_remove_rule(self):
        self.router.add_rule("temp", ["echo"])
        self.assertTrue(self.router.remove_rule("temp"))

    def test_remove_nonexistent_rule(self):
        self.assertFalse(self.router.remove_rule("nonexistent"))

    def test_get_rules(self):
        rules = self.router.get_rules()
        self.assertIsInstance(rules, dict)
        self.assertIn("default", rules)

    def test_get_categories(self):
        cats = self.router.get_categories()
        self.assertIn("default", cats)
        self.assertEqual(cats, sorted(cats))


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_basic_status(self):
        router = EngineRouter()
        s = router.status()
        self.assertIn("rules_count", s)
        self.assertIn("categories", s)
        self.assertIn("registered_engines", s)
        self.assertGreater(s["rules_count"], 0)

    def test_status_with_health(self):
        router = EngineRouter()
        router.set_health("echo", available=True, error_count=2, avg_latency_ms=150.0)
        s = router.status()
        self.assertIn("echo", s["health"])
        self.assertEqual(s["health"]["echo"]["error_count"], 2)

    def test_status_with_overrides(self):
        router = EngineRouter()
        router.set_override("agent_1", "echo")
        s = router.status()
        self.assertEqual(s["overrides"]["agent_1"], "echo")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases."""

    def test_empty_rules(self):
        router = EngineRouter(rules={})
        decision = router.route()
        # Should still find something via last resort
        self.assertNotEqual(decision.engine_name, "")

    def test_no_registered_engine_in_rules(self):
        router = EngineRouter(rules={"default": ["nonexistent_1", "nonexistent_2"]})
        decision = router.route()
        # Falls through to last resort
        self.assertNotEqual(decision.engine_name, "")

    def test_custom_models(self):
        router = EngineRouter(models={"default": "custom-model-v1"})
        decision = router.route()
        self.assertEqual(decision.model, "custom-model-v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
