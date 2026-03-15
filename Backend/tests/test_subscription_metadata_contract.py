from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.cli as cli_mod  # noqa: E402


class TestSubscriptionMetadataContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_team_json_path = srv.TEAM_JSON_PATH

    def tearDown(self) -> None:
        srv.TEAM_JSON_PATH = self._orig_team_json_path

    def test_load_team_config_does_not_enrich_claude_subscription_from_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            team_path = os.path.join(tmpdir, "team.json")
            profile_dir = os.path.join(tmpdir, "claude-profile")
            os.makedirs(profile_dir, exist_ok=True)

            with open(os.path.join(profile_dir, ".claude.json"), "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "oauthAccount": {
                            "emailAddress": "from-claude-json@example.com",
                            "accountCreatedAt": "2026-01-01T00:00:00Z",
                            "billingType": "stripe_subscription",
                            "displayName": "Injected Display",
                        }
                    },
                    fh,
                )

            with open(os.path.join(profile_dir, ".credentials.json"), "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "claudeAiOauth": {
                            "subscriptionType": "max",
                            "rateLimitTier": "default_claude_max_20x",
                        }
                    },
                    fh,
                )

            with open(team_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "version": 3,
                        "agents": [],
                        "subscriptions": [
                            {
                                "id": "subx",
                                "name": "Pool",
                                "path": profile_dir,
                                "active": True,
                            }
                        ],
                    },
                    fh,
                )

            real_expanduser = os.path.expanduser
            srv.TEAM_JSON_PATH = team_path

            with mock.patch.object(
                srv.os.path,
                "expanduser",
                side_effect=lambda value: tmpdir if value == "~" else real_expanduser(value),
            ):
                loaded = srv.load_team_config()

            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded["subscriptions"]), 1)
            sub = loaded["subscriptions"][0]
            self.assertEqual(sub["id"], "subx")
            self.assertEqual(sub.get("email", ""), "")
            self.assertEqual(sub.get("account_created_at", ""), "")
            self.assertEqual(sub.get("billing_type", ""), "")
            self.assertEqual(sub.get("display_name", ""), "")
            self.assertEqual(sub.get("plan", ""), "")
            self.assertEqual(sub.get("rate_limit_tier", ""), "")

    def test_build_subscription_response_item_hides_claude_account_projection_and_uses_profile_state(self) -> None:
        agents = [
            {"id": "buddy", "config_dir": "/profiles/claude-a"},
            {"id": "viktor", "config_dir": "/profiles/claude-a"},
        ]
        sub = {
            "id": "sub1",
            "name": "Primary Claude",
            "path": "/profiles/claude-a",
            "provider": "claude",
            "active": True,
            "email": "legacy@example.com",
            "plan": "max",
            "billing_type": "stripe_subscription",
            "display_name": "Legacy",
            "account_created_at": "2026-01-01T00:00:00Z",
            "rate_limit_tier": "default_claude_max_20x",
        }

        with mock.patch.object(
            cli_mod,
            "_probe_claude_profile_state",
            return_value={
                "profile_status": "ready",
                "profile_probe": "claude auth status",
                "profile_note": "Official Claude auth detected",
                "observed_email": "real@example.com",
                "observed_subscription_type": "max",
            },
        ):
            payload = srv._build_subscription_response_item(sub, agents)

        self.assertEqual(payload["provider"], "claude")
        self.assertEqual(payload["agent_count"], 2)
        self.assertEqual(payload["email"], "")
        self.assertEqual(payload["plan"], "")
        self.assertEqual(payload["billing_type"], "")
        self.assertEqual(payload["display_name"], "")
        self.assertEqual(payload["account_created_at"], "")
        self.assertEqual(payload["rate_limit_tier"], "")
        self.assertEqual(payload["profile_status"], "ready")
        self.assertEqual(payload["observed_email"], "real@example.com")

    def test_probe_cli_runtime_status_for_claude_avoids_non_interactive_probe(self) -> None:
        with mock.patch.object(
            cli_mod,
            "_run_cli_probe",
            side_effect=AssertionError("Claude runtime probe must not run"),
        ):
            payload = srv._probe_cli_runtime_status("claude", "/usr/bin/claude")

        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(payload["probe"], "")
        self.assertIn("No verified non-interactive runtime probe configured for Claude", payload["note"])

    def test_load_team_config_detects_provider_profiles_without_reading_auth_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            team_path = os.path.join(tmpdir, "team.json")
            os.makedirs(os.path.join(tmpdir, ".codex"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, ".gemini"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, ".qwen"), exist_ok=True)
            with open(os.path.join(tmpdir, ".codex", "auth.json"), "w", encoding="utf-8") as fh:
                fh.write('{"tokens":{"id_token":"secret"}}')
            with open(os.path.join(tmpdir, ".gemini", "google_accounts.json"), "w", encoding="utf-8") as fh:
                fh.write('{"active":"secret@example.com"}')
            with open(os.path.join(tmpdir, ".qwen", "oauth_creds.json"), "w", encoding="utf-8") as fh:
                fh.write('{"resource_url":"portal.qwen.ai"}')
            with open(team_path, "w", encoding="utf-8") as fh:
                json.dump({"version": 3, "agents": [], "subscriptions": []}, fh)

            real_open = open
            real_expanduser = os.path.expanduser

            def guarded_open(path: str, *args: object, **kwargs: object):
                if path in {
                    os.path.join(tmpdir, ".codex", "auth.json"),
                    os.path.join(tmpdir, ".gemini", "google_accounts.json"),
                    os.path.join(tmpdir, ".qwen", "oauth_creds.json"),
                }:
                    raise AssertionError(f"load_team_config must not read {path}")
                return real_open(path, *args, **kwargs)

            srv.TEAM_JSON_PATH = team_path
            with mock.patch("builtins.open", side_effect=guarded_open):
                with mock.patch.object(
                    srv.os.path,
                    "expanduser",
                    side_effect=lambda value: tmpdir if value == "~" else real_expanduser(value),
                ):
                    loaded = srv.load_team_config()

            self.assertIsNotNone(loaded)
            subs = {sub["id"]: sub for sub in loaded["subscriptions"]}
            self.assertEqual(set(subs), {"codex", "gemini", "qwen"})
            self.assertEqual(subs["codex"]["path"], os.path.join(tmpdir, ".codex"))
            self.assertEqual(subs["gemini"]["path"], os.path.join(tmpdir, ".gemini"))
            self.assertEqual(subs["qwen"]["path"], os.path.join(tmpdir, ".qwen"))
            self.assertEqual(subs["codex"].get("email", ""), "")
            self.assertEqual(subs["codex"].get("plan", ""), "")
            self.assertEqual(subs["gemini"].get("email", ""), "")
            self.assertEqual(subs["qwen"].get("email", ""), "")

    def test_load_team_config_strips_legacy_metadata_from_detected_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            team_path = os.path.join(tmpdir, "team.json")
            with open(team_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "version": 3,
                        "agents": [],
                        "subscriptions": [
                            {
                                "id": "codex",
                                "name": "Codex",
                                "provider": "openai",
                                "path": os.path.join(tmpdir, ".codex"),
                                "active": True,
                                "_detected": True,
                                "email": "legacy@example.com",
                                "plan": "plus",
                            },
                            {
                                "id": "gemini",
                                "name": "Gemini",
                                "provider": "gemini",
                                "path": os.path.join(tmpdir, ".gemini"),
                                "active": True,
                                "_detected": True,
                                "email": "legacy@example.com",
                            },
                        ],
                    },
                    fh,
                )

            srv.TEAM_JSON_PATH = team_path
            loaded = srv.load_team_config()

            self.assertIsNotNone(loaded)
            subs = {sub["id"]: sub for sub in loaded["subscriptions"]}
            self.assertNotIn("email", subs["codex"])
            self.assertNotIn("plan", subs["codex"])
            self.assertNotIn("email", subs["gemini"])

            persisted = json.loads(open(team_path, encoding="utf-8").read())
            persisted_subs = {sub["id"]: sub for sub in persisted["subscriptions"]}
            self.assertNotIn("email", persisted_subs["codex"])
            self.assertNotIn("plan", persisted_subs["codex"])
            self.assertNotIn("email", persisted_subs["gemini"])
