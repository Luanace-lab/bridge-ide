from __future__ import annotations

import os
import sys
import tempfile
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import server_utils  # noqa: E402


class TestServerUtilsContract(unittest.TestCase):
    def tearDown(self) -> None:
        server_utils.init(
            max_wait_seconds=srv.MAX_WAIT_SECONDS,
            max_limit=srv.MAX_LIMIT,
        )

    def test_server_reexports_server_utils_contract(self) -> None:
        self.assertIs(srv.utc_now_iso, server_utils.utc_now_iso)
        self.assertIs(srv.is_within_directory, server_utils.is_within_directory)
        self.assertIs(srv.validate_project_path, server_utils.validate_project_path)
        self.assertIs(srv.resolve_team_lead_scope_file, server_utils.resolve_team_lead_scope_file)
        self.assertIs(srv.ensure_parent_dir, server_utils.ensure_parent_dir)
        self.assertIs(srv.parse_wait, server_utils.parse_wait)
        self.assertIs(srv.parse_limit, server_utils.parse_limit)
        self.assertIs(srv.parse_after_id, server_utils.parse_after_id)
        self.assertIs(srv.parse_bool, server_utils.parse_bool)
        self.assertIs(srv.parse_non_negative_int, server_utils.parse_non_negative_int)
        self.assertIs(srv.normalize_path, server_utils.normalize_path)

    def test_parse_helpers_preserve_bounds(self) -> None:
        server_utils.init(max_wait_seconds=60.0, max_limit=1000)

        self.assertEqual(server_utils.parse_wait(None), 20.0)
        self.assertEqual(server_utils.parse_wait("-5"), 0.0)
        self.assertEqual(server_utils.parse_wait("120"), 60.0)

        self.assertIsNone(server_utils.parse_limit(None))
        self.assertEqual(server_utils.parse_limit("abc"), 50)
        self.assertEqual(server_utils.parse_limit("0"), 50)
        self.assertEqual(server_utils.parse_limit("5000"), 1000)

        self.assertIsNone(server_utils.parse_after_id("abc"))
        self.assertIsNone(server_utils.parse_after_id("-2"))
        self.assertEqual(server_utils.parse_after_id("-1"), -1)

        self.assertTrue(server_utils.parse_bool("yes"))
        self.assertFalse(server_utils.parse_bool("off", default=True))
        self.assertEqual(server_utils.parse_non_negative_int("-4", 9), 0)
        self.assertEqual(server_utils.parse_non_negative_int("abc", 9), 9)

    def test_path_helpers_preserve_directory_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = os.path.join(tmpdir, "project")
            os.makedirs(project, exist_ok=True)

            self.assertTrue(server_utils.is_within_directory(project, tmpdir))
            self.assertEqual(server_utils.validate_project_path(project, tmpdir), os.path.abspath(project))
            self.assertIsNone(server_utils.validate_project_path("/etc", tmpdir))

            escaped = server_utils.resolve_team_lead_scope_file(project, "../../escape.md")
            expected = os.path.abspath(os.path.join(tmpdir, "teamlead.md"))
            self.assertEqual(escaped, expected)

            nested = os.path.join(project, "notes", "ctx.md")
            server_utils.ensure_parent_dir(nested)
            self.assertTrue(os.path.isdir(os.path.dirname(nested)))
