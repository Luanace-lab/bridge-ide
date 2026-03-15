from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.skills as skills_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, body: dict | None = None):
        self._body = body
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self._body


class TestSkillsRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="skills_routes_contract_")
        self._orig_skills_dir = skills_mod.SKILLS_DIR
        self._orig_proposals = list(skills_mod._SKILL_PROPOSALS)
        skills_mod.SKILLS_DIR = os.path.join(self._tmpdir, "skills")
        os.makedirs(skills_mod.SKILLS_DIR, exist_ok=True)
        skill_dir = os.path.join(skills_mod.SKILLS_DIR, "slice67-skill")
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
            handle.write("---\nname: Slice Skill\ndescription: Contract skill\n---\n\nBody text")
        skills_mod._skills_cache["mtime"] = 0.0
        skills_mod._skills_cache["skills"] = []
        skills_mod._SKILL_PROPOSALS.clear()
        skills_mod._SKILL_PROPOSALS.extend(
            [
                {"id": "p1", "status": "pending"},
                {"id": "p2", "status": "approved"},
            ]
        )
        self._team = {"agents": [{"id": "codex", "skills": ["slice67-skill"], "role": "debug", "description": "debug specialist"}]}
        skills_mod.init(
            team_config_getter=lambda: self._team,
            team_config_lock=threading.RLock(),
            atomic_write_team_json_fn=lambda: None,
            ws_broadcast_fn=lambda *_args, **_kwargs: None,
            deploy_agent_skills_fn=lambda _agent_id, _base_config: None,
        )

    def tearDown(self) -> None:
        skills_mod.SKILLS_DIR = self._orig_skills_dir
        skills_mod._skills_cache["mtime"] = 0.0
        skills_mod._skills_cache["skills"] = []
        skills_mod._SKILL_PROPOSALS.clear()
        skills_mod._SKILL_PROPOSALS.extend(self._orig_proposals)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_skills_list_content_section_proposals_and_agent_routes(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(skills_mod.handle_get(handler, "/skills", {}))
        self.assertEqual(handler.responses[-1][0], 200)
        self.assertEqual(handler.responses[-1][1]["count"], 1)

        self.assertTrue(skills_mod.handle_get(handler, "/skills/slice67-skill/content", {}))
        self.assertEqual(handler.responses[-1][1]["skill"]["id"], "slice67-skill")

        self.assertTrue(skills_mod.handle_get(handler, "/skills/codex/section", {}))
        self.assertIn("Slice Skill", handler.responses[-1][1]["section"])

        self.assertTrue(skills_mod.handle_get(handler, "/skills/proposals", {"status": ["pending"]}))
        self.assertEqual(handler.responses[-1][1]["count"], 1)

        self.assertTrue(skills_mod.handle_get(handler, "/skills/codex", {}))
        self.assertEqual(handler.responses[-1][1]["agent_id"], "codex")

    def test_skills_assign_route(self) -> None:
        skill_dir = os.path.join(skills_mod.SKILLS_DIR, "bridge-agent-core")
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
            handle.write("---\nname: Core\ndescription: Core skill\n---\n")
        skills_mod._skills_cache["mtime"] = 0.0
        skills_mod._skills_cache["skills"] = []

        handler = _DummyHandler({"agent_id": "codex", "skills": ["slice67-skill"]})
        self.assertTrue(skills_mod.handle_post(handler, "/skills/assign"))
        self.assertEqual(handler.responses[-1][0], 200)
        self.assertIn("bridge-agent-core", handler.responses[-1][1]["skills"])


if __name__ == "__main__":
    unittest.main()
