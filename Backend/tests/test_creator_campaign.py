"""Tests for creator campaign — lifecycle, publishing, performance."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest


class TestCreatorCampaign(unittest.TestCase):
    """Test campaign CRUD, approval, publishing, performance."""

    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="cj_camp_")

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_create_and_persist_campaign(self) -> None:
        import creator_campaign

        camp = creator_campaign.create_campaign(
            title="Spring Launch",
            goal="reach",
            workspace_dir=self.workspace,
            target_platforms=["youtube_short", "instagram_reel"],
        )
        self.assertTrue(camp["campaign_id"].startswith("cc_"))
        self.assertEqual(camp["status"], "draft")

        creator_campaign.save_campaign(camp)
        loaded = creator_campaign.load_campaign(camp["campaign_id"], self.workspace)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["title"], "Spring Launch")

    def test_add_asset_refs(self) -> None:
        import creator_campaign

        camp = creator_campaign.create_campaign(
            title="Test", workspace_dir=self.workspace,
        )
        creator_campaign.add_asset_ref(camp, "cj_abc123", "/tmp/clip.mp4", "youtube_short")
        creator_campaign.add_asset_ref(camp, "cj_abc123", "/tmp/clip2.mp4", "instagram_reel")
        creator_campaign.save_campaign(camp)

        loaded = creator_campaign.load_campaign(camp["campaign_id"], self.workspace)
        self.assertEqual(len(loaded["asset_refs"]), 2)
        self.assertEqual(loaded["asset_refs"][0]["job_id"], "cj_abc123")

    def test_set_publish_plan_transitions_to_planned(self) -> None:
        import creator_campaign

        camp = creator_campaign.create_campaign(
            title="Test", workspace_dir=self.workspace,
        )
        self.assertEqual(camp["status"], "draft")

        creator_campaign.set_publish_plan(camp, [
            {"channel": "telegram", "target": "@ch1", "caption": "Post 1", "schedule_iso": "2026-03-16T09:00:00Z"},
            {"channel": "telegram", "target": "@ch1", "caption": "Post 2", "schedule_iso": "2026-03-17T09:00:00Z"},
        ])
        self.assertEqual(camp["status"], "planned")
        self.assertEqual(len(camp["publish_plan"]), 2)

    def test_approve_campaign(self) -> None:
        import creator_campaign

        camp = creator_campaign.create_campaign(
            title="Test", workspace_dir=self.workspace,
        )
        creator_campaign.set_publish_plan(camp, [{"channel": "telegram", "target": "@t", "caption": "x"}])
        creator_campaign.approve_campaign(camp)
        self.assertEqual(camp["status"], "approved")

    def test_import_performance_snapshot(self) -> None:
        import creator_campaign

        camp = creator_campaign.create_campaign(
            title="Test", workspace_dir=self.workspace,
        )
        creator_campaign.save_campaign(camp)

        creator_campaign.import_performance_snapshot(
            camp,
            channel="telegram",
            metrics={"views": 1200, "engagement_rate": 0.08, "shares": 45},
            period="2026-03-14",
        )
        creator_campaign.save_campaign(camp)

        loaded = creator_campaign.load_campaign(camp["campaign_id"], self.workspace)
        self.assertEqual(len(loaded["performance_snapshots"]), 1)
        self.assertEqual(loaded["performance_snapshots"][0]["channel"], "telegram")
        self.assertEqual(loaded["performance_snapshots"][0]["metrics"]["views"], 1200)

        # Verify performance file on disk
        perf_dir = os.path.join(
            self.workspace, "creator_campaigns", camp["campaign_id"], "performance"
        )
        perf_files = os.listdir(perf_dir)
        self.assertEqual(len(perf_files), 1)

    def test_list_campaigns(self) -> None:
        import creator_campaign

        for i in range(3):
            c = creator_campaign.create_campaign(
                title=f"Camp {i}", workspace_dir=self.workspace,
            )
            creator_campaign.save_campaign(c)

        camps = creator_campaign.list_campaigns(self.workspace)
        self.assertEqual(len(camps), 3)

    def test_campaign_events(self) -> None:
        import creator_campaign

        camp = creator_campaign.create_campaign(
            title="Test", workspace_dir=self.workspace,
        )
        creator_campaign.save_campaign(camp)
        creator_campaign.append_campaign_event(
            camp["campaign_id"], self.workspace, "approved", {"by": "user"},
        )
        events = creator_campaign.load_campaign_events(camp["campaign_id"], self.workspace)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "approved")

    def test_campaign_http_create_endpoint(self) -> None:
        """POST /creator/campaigns returns 201."""
        from handlers.creator import handle_post

        ws = self.workspace

        class MockHandler:
            def __init__(self) -> None:
                self.path = "/creator/campaigns"
                self.response_code: int | None = None
                self.response_body: dict | None = None

            def _parse_json_body(self) -> dict:
                return {
                    "title": "HTTP Campaign",
                    "goal": "reach",
                    "workspace_dir": ws,
                    "target_platforms": ["telegram"],
                }

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_post(handler, "/creator/campaigns")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 201)
        self.assertIn("campaign_id", handler.response_body)

    def test_campaign_http_approve_endpoint(self) -> None:
        """POST /creator/campaigns/{id}/approve transitions status."""
        import creator_campaign
        from handlers.creator import handle_post

        camp = creator_campaign.create_campaign(
            title="Test", workspace_dir=self.workspace,
        )
        creator_campaign.set_publish_plan(camp, [{"channel": "telegram", "target": "@t", "caption": "x"}])
        creator_campaign.save_campaign(camp)

        ws = self.workspace
        cid = camp["campaign_id"]

        class MockHandler:
            def __init__(self) -> None:
                self.path = f"/creator/campaigns/{cid}/approve"
                self.response_code: int | None = None
                self.response_body: dict | None = None

            def _parse_json_body(self) -> dict:
                return {"workspace_dir": ws}

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_post(handler, f"/creator/campaigns/{cid}/approve")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 200)

        loaded = creator_campaign.load_campaign(cid, self.workspace)
        self.assertEqual(loaded["status"], "approved")

    def test_campaign_http_metrics_import(self) -> None:
        """POST /creator/campaigns/{id}/metrics/import stores metrics."""
        import creator_campaign
        from handlers.creator import handle_post

        camp = creator_campaign.create_campaign(
            title="Test", workspace_dir=self.workspace,
        )
        creator_campaign.save_campaign(camp)

        ws = self.workspace
        cid = camp["campaign_id"]

        class MockHandler:
            def __init__(self) -> None:
                self.path = f"/creator/campaigns/{cid}/metrics/import"
                self.response_code: int | None = None
                self.response_body: dict | None = None

            def _parse_json_body(self) -> dict:
                return {
                    "workspace_dir": ws,
                    "channel": "instagram",
                    "metrics": {"views": 500, "likes": 42},
                    "period": "2026-03-15",
                }

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_post(handler, f"/creator/campaigns/{cid}/metrics/import")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 200)

        loaded = creator_campaign.load_campaign(cid, self.workspace)
        self.assertEqual(len(loaded["performance_snapshots"]), 1)

    def test_campaign_http_get_endpoint(self) -> None:
        """GET /creator/campaigns/{id} returns the stored campaign."""
        import creator_campaign
        from handlers.creator import handle_get

        camp = creator_campaign.create_campaign(
            title="Get Campaign", workspace_dir=self.workspace,
        )
        creator_campaign.save_campaign(camp)
        cid = camp["campaign_id"]
        ws = self.workspace

        class MockHandler:
            def __init__(self) -> None:
                self.path = f"/creator/campaigns/{cid}?workspace_dir={ws}"
                self.response_code: int | None = None
                self.response_body: dict | None = None

            def _respond(self, code: int, body: dict) -> None:
                self.response_code = code
                self.response_body = body

        handler = MockHandler()
        result = handle_get(handler, f"/creator/campaigns/{cid}")
        self.assertTrue(result)
        self.assertEqual(handler.response_code, 200)
        self.assertEqual(handler.response_body["campaign_id"], cid)


if __name__ == "__main__":
    unittest.main()
