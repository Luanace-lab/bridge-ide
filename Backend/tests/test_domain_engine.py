"""Tests for domain_engine — WorkItem, Calendar, Library + Marketing Domain Pack."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest


class TestWorkItem(unittest.TestCase):
    """Test WorkItem CRUD and lifecycle."""

    def setUp(self) -> None:
        self.ws = tempfile.mkdtemp(prefix="de_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_create_work_item(self) -> None:
        from domain_engine.work_item import create_work_item
        item = create_work_item("marketing", "social_post", "Launch Post", self.ws, brief="Announce Q2 launch")
        self.assertTrue(item["item_id"].startswith("wi_"))
        self.assertEqual(item["domain"], "marketing")
        self.assertEqual(item["type"], "social_post")
        self.assertEqual(item["status"], "draft")

    def test_persist_and_reload(self) -> None:
        from domain_engine.work_item import create_work_item, load_work_item
        item = create_work_item("marketing", "social_post", "Test", self.ws)
        loaded = load_work_item(item["item_id"], self.ws)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["item_id"], item["item_id"])

    def test_lifecycle_transitions(self) -> None:
        from domain_engine.work_item import create_work_item, transition_work_item
        item = create_work_item("marketing", "social_post", "Test", self.ws)
        self.assertEqual(item["status"], "draft")

        item = transition_work_item(item, "generated", self.ws)
        self.assertEqual(item["status"], "generated")

        item = transition_work_item(item, "optimized", self.ws)
        self.assertEqual(item["status"], "optimized")

        item = transition_work_item(item, "approved", self.ws)
        self.assertEqual(item["status"], "approved")

        item = transition_work_item(item, "scheduled", self.ws)
        self.assertEqual(item["status"], "scheduled")

        item = transition_work_item(item, "published", self.ws)
        self.assertEqual(item["status"], "published")

        item = transition_work_item(item, "observed", self.ws)
        self.assertEqual(item["status"], "observed")

        item = transition_work_item(item, "archived", self.ws)
        self.assertEqual(item["status"], "archived")

    def test_invalid_transition_raises(self) -> None:
        from domain_engine.work_item import create_work_item, transition_work_item
        item = create_work_item("marketing", "social_post", "Test", self.ws)
        with self.assertRaises(ValueError):
            transition_work_item(item, "published", self.ws)  # draft → published not allowed

    def test_approve(self) -> None:
        from domain_engine.work_item import create_work_item, transition_work_item, approve_work_item
        item = create_work_item("marketing", "social_post", "Test", self.ws)
        item = transition_work_item(item, "generated", self.ws)
        item = approve_work_item(item, "leo", self.ws)
        self.assertEqual(item["status"], "approved")
        self.assertEqual(item["approval"]["reviewer"], "leo")

    def test_add_variant(self) -> None:
        from domain_engine.work_item import create_work_item, add_variant
        item = create_work_item("marketing", "social_post", "Test", self.ws)
        item = add_variant(item, "Variant A text", "A", self.ws)
        item = add_variant(item, "Variant B text", "B", self.ws)
        self.assertEqual(len(item["variants"]), 2)
        self.assertEqual(item["variants"][0]["label"], "A")

    def test_import_metrics(self) -> None:
        from domain_engine.work_item import create_work_item, import_metrics
        item = create_work_item("marketing", "social_post", "Test", self.ws)
        item = import_metrics(item, "instagram", {"impressions": 1200, "likes": 45}, "2026-03-15", self.ws)
        self.assertEqual(len(item["observation_snapshots"]), 1)
        self.assertEqual(item["observation_snapshots"][0]["metrics"]["impressions"], 1200)

    def test_list_work_items(self) -> None:
        from domain_engine.work_item import create_work_item, list_work_items
        create_work_item("marketing", "social_post", "Post 1", self.ws)
        create_work_item("marketing", "newsletter", "News 1", self.ws)
        create_work_item("legal", "memo", "Legal Memo", self.ws)

        all_items = list_work_items(self.ws)
        self.assertEqual(len(all_items), 3)

        marketing = list_work_items(self.ws, domain="marketing")
        self.assertEqual(len(marketing), 2)

        legal = list_work_items(self.ws, domain="legal")
        self.assertEqual(len(legal), 1)

    def test_events_logged(self) -> None:
        from domain_engine.work_item import create_work_item, transition_work_item, load_events
        item = create_work_item("marketing", "social_post", "Test", self.ws)
        transition_work_item(item, "generated", self.ws)
        events = load_events(item["item_id"], self.ws)
        self.assertGreater(len(events), 0)
        self.assertEqual(events[0]["event_type"], "transition")

    def test_domain_agnostic(self) -> None:
        """WorkItem works for any domain — not just marketing."""
        from domain_engine.work_item import create_work_item
        legal = create_work_item("legal", "clause", "Haftung §5", self.ws)
        finance = create_work_item("finance", "report", "Q2 Analysis", self.ws)
        devops = create_work_item("devops", "postmortem", "Incident 2026-03-15", self.ws)
        self.assertEqual(legal["domain"], "legal")
        self.assertEqual(finance["domain"], "finance")
        self.assertEqual(devops["domain"], "devops")


class TestCalendarIndex(unittest.TestCase):
    """Test calendar view over scheduled WorkItems."""

    def setUp(self) -> None:
        self.ws = tempfile.mkdtemp(prefix="de_cal_")

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_calendar_shows_scheduled_items(self) -> None:
        from domain_engine.work_item import create_work_item
        from domain_engine.calendar_index import get_calendar

        create_work_item("marketing", "social_post", "Post 1", self.ws, schedule="2026-04-01T09:00:00Z")
        create_work_item("marketing", "social_post", "Post 2", self.ws, schedule="2026-04-02T09:00:00Z")
        create_work_item("marketing", "social_post", "No Schedule", self.ws)

        entries = get_calendar(self.ws)
        self.assertEqual(len(entries), 2)

    def test_calendar_filters_by_date(self) -> None:
        from domain_engine.work_item import create_work_item
        from domain_engine.calendar_index import get_calendar

        create_work_item("marketing", "social_post", "Early", self.ws, schedule="2026-03-01T09:00:00Z")
        create_work_item("marketing", "social_post", "Mid", self.ws, schedule="2026-04-15T09:00:00Z")
        create_work_item("marketing", "social_post", "Late", self.ws, schedule="2026-06-01T09:00:00Z")

        entries = get_calendar(self.ws, start_date="2026-04-01", end_date="2026-05-01")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Mid")


class TestContentLibrary(unittest.TestCase):
    """Test content library templates."""

    def setUp(self) -> None:
        self.ws = tempfile.mkdtemp(prefix="de_lib_")

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_create_library_item(self) -> None:
        from domain_engine.content_library import create_library_item
        item = create_library_item("marketing", "social_post", "Weekly Tip", "Here's your weekly tip: {tip}", self.ws)
        self.assertTrue(item["library_id"].startswith("lib_"))

    def test_instantiate_creates_work_item(self) -> None:
        from domain_engine.content_library import create_library_item, instantiate_library_item
        template = create_library_item("marketing", "social_post", "Template", "Template body", self.ws)
        work_item = instantiate_library_item(template["library_id"], self.ws)
        self.assertTrue(work_item["item_id"].startswith("wi_"))
        self.assertEqual(work_item["body"], "Template body")

    def test_usage_count_increments(self) -> None:
        from domain_engine.content_library import create_library_item, instantiate_library_item, list_library_items
        template = create_library_item("marketing", "social_post", "Template", "Body", self.ws)
        instantiate_library_item(template["library_id"], self.ws)
        instantiate_library_item(template["library_id"], self.ws)
        items = list_library_items(self.ws)
        self.assertEqual(items[0]["usage_count"], 2)


class TestMarketingDomainPack(unittest.TestCase):
    """Test marketing-specific functionality."""

    def test_platform_rules_exist(self) -> None:
        from domain_packs.marketing.platform_rules import PLATFORM_RULES
        self.assertIn("twitter", PLATFORM_RULES)
        self.assertIn("instagram", PLATFORM_RULES)
        self.assertIn("linkedin", PLATFORM_RULES)
        self.assertEqual(PLATFORM_RULES["twitter"]["character_limit"], 280)

    def test_optimize_truncates(self) -> None:
        from domain_packs.marketing.platform_rules import optimize_for_platform
        long_text = "A" * 500
        result = optimize_for_platform(long_text, "twitter")
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["body"]), 280)

    def test_optimize_short_text_not_truncated(self) -> None:
        from domain_packs.marketing.platform_rules import optimize_for_platform
        result = optimize_for_platform("Short post", "twitter")
        self.assertFalse(result["truncated"])

    def test_content_types_defined(self) -> None:
        from domain_packs.marketing.content_types import list_content_types
        types = list_content_types()
        self.assertIn("social_post", types)
        self.assertIn("video_clip", types)
        self.assertIn("newsletter", types)
        self.assertGreater(len(types), 5)

    def test_full_marketing_workflow(self) -> None:
        """E2E: Create post → optimize → approve → schedule → publish lifecycle."""
        ws = tempfile.mkdtemp(prefix="de_mkt_e2e_")
        try:
            from domain_engine.work_item import (
                create_work_item, transition_work_item, approve_work_item,
                add_variant, import_metrics,
            )
            from domain_packs.marketing.platform_rules import optimize_for_platform

            # 1. Create
            item = create_work_item(
                domain="marketing",
                item_type="social_post",
                title="Q2 Launch",
                workspace_dir=ws,
                brief="Announce our new product",
                body="We're excited to announce our new product! Check it out at example.com #launch #product",
                channel_targets=["twitter", "linkedin", "instagram"],
                schedule="2026-04-01T09:00:00Z",
            )
            self.assertEqual(item["status"], "draft")

            # 2. Optimize per platform
            for platform in item["channel_targets"]:
                opt = optimize_for_platform(item["body"], platform)
                self.assertTrue(opt["optimized"])

            # 3. Generate → Optimize
            item = transition_work_item(item, "generated", ws)
            item = transition_work_item(item, "optimized", ws)

            # 4. Add A/B variant
            item = add_variant(item, "Alternative: Our product just dropped! 🚀", "Variant B", ws)
            self.assertEqual(len(item["variants"]), 1)

            # 5. Approve
            item = approve_work_item(item, "leo", ws)
            self.assertEqual(item["status"], "approved")

            # 6. Schedule → Publish → Observe
            item = transition_work_item(item, "scheduled", ws)
            item = transition_work_item(item, "published", ws)
            item = transition_work_item(item, "observed", ws)

            # 7. Import metrics
            item = import_metrics(item, "twitter", {"impressions": 5000, "clicks": 120, "ctr": 0.024}, "2026-04-02", ws)
            item = import_metrics(item, "linkedin", {"impressions": 2000, "clicks": 80, "ctr": 0.04}, "2026-04-02", ws)
            self.assertEqual(len(item["observation_snapshots"]), 2)

            # 8. Archive
            item = transition_work_item(item, "archived", ws)
            self.assertEqual(item["status"], "archived")

        finally:
            shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
