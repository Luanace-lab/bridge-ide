from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.skills as skills_mod  # noqa: E402


class TestSkillsRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="skills_routes_http_contract_")
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_team_config = srv.TEAM_CONFIG
        self._orig_team_lock = srv.TEAM_CONFIG_LOCK
        self._orig_skills_dir = skills_mod.SKILLS_DIR
        self._orig_proposals = list(skills_mod._SKILL_PROPOSALS)

        srv.BRIDGE_STRICT_AUTH = False
        srv.TEAM_CONFIG_LOCK = threading.RLock()
        srv.TEAM_CONFIG = {"agents": [{"id": "codex", "skills": ["http-skill"], "role": "debug", "description": "debug specialist"}]}
        skills_mod.SKILLS_DIR = os.path.join(self._tmpdir, "skills")
        os.makedirs(skills_mod.SKILLS_DIR, exist_ok=True)
        skill_dir = os.path.join(skills_mod.SKILLS_DIR, "http-skill")
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
            handle.write("---\nname: HTTP Skill\ndescription: HTTP contract skill\n---\n\nHTTP body")
        skills_mod._skills_cache["mtime"] = 0.0
        skills_mod._skills_cache["skills"] = []
        skills_mod._SKILL_PROPOSALS.clear()
        skills_mod._SKILL_PROPOSALS.extend([{"id": "proposal-http", "status": "pending"}])
        skills_mod.init(
            team_config_getter=lambda: srv.TEAM_CONFIG,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
            atomic_write_team_json_fn=lambda: None,
            ws_broadcast_fn=lambda *_args, **_kwargs: None,
            deploy_agent_skills_fn=lambda _agent_id, _base_config: "/tmp/http-skill-config",
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        srv.TEAM_CONFIG = self._orig_team_config
        srv.TEAM_CONFIG_LOCK = self._orig_team_lock
        skills_mod.SKILLS_DIR = self._orig_skills_dir
        skills_mod._skills_cache["mtime"] = 0.0
        skills_mod._skills_cache["skills"] = []
        skills_mod._SKILL_PROPOSALS.clear()
        skills_mod._SKILL_PROPOSALS.extend(self._orig_proposals)
        skills_mod.init(
            team_config_getter=lambda: srv.TEAM_CONFIG,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
            atomic_write_team_json_fn=srv._atomic_write_team_json,
            ws_broadcast_fn=srv.ws_broadcast,
            deploy_agent_skills_fn=srv._deploy_agent_skills,
        )
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _start_server(self) -> str:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _get(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_skills_get_routes_http(self) -> None:
        base_url = self._start_server()

        status_list, body_list = self._get(base_url, "/skills")
        self.assertEqual(status_list, 200)
        self.assertEqual(body_list["count"], 1)

        status_content, body_content = self._get(base_url, "/skills/http-skill/content")
        self.assertEqual(status_content, 200)
        self.assertEqual(body_content["skill"]["id"], "http-skill")

        status_section, body_section = self._get(base_url, "/skills/codex/section")
        self.assertEqual(status_section, 200)
        self.assertIn("HTTP Skill", body_section["section"])

        status_props, body_props = self._get(base_url, "/skills/proposals?status=pending")
        self.assertEqual(status_props, 200)
        self.assertEqual(body_props["count"], 1)

        status_agent, body_agent = self._get(base_url, "/skills/codex")
        self.assertEqual(status_agent, 200)
        self.assertEqual(body_agent["agent_id"], "codex")

        status_assign, body_assign = self._post(base_url, "/skills/assign", {"agent_id": "codex", "skills": ["http-skill"]})
        self.assertEqual(status_assign, 200)
        self.assertIn("http-skill", body_assign["skills"])


if __name__ == "__main__":
    unittest.main()
