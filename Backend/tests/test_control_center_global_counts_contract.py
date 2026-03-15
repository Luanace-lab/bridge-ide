from __future__ import annotations

import os
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))
CONTROL_CENTER_PATH = os.path.join(REPO_ROOT, "BRIDGE", "Frontend", "control_center.html")


class TestControlCenterGlobalCountsContract(unittest.TestCase):
    def _read(self) -> str:
        return Path(CONTROL_CENTER_PATH).read_text(encoding="utf-8")

    def test_metrics_prefer_global_org_sources_over_board_projection(self) -> None:
        raw = self._read()
        self.assertIn("const countProjectsSource = dashOpProjectsData.length > 0 ? dashOpProjectsData : projectsData.projects;", raw)
        self.assertIn("const totalAgents = Array.isArray(HIERARCHY_DATA.agents) && HIERARCHY_DATA.agents.length > 0", raw)
        self.assertNotIn("const totalProjects = projectsData.projects.length;", raw)
        self.assertNotIn("const totalTeams = projectsData.projects.reduce((sum, p) => sum + p.teams.length, 0);", raw)

    def test_dashboard_population_refreshes_orgchart_for_global_agent_counts(self) -> None:
        raw = self._read()
        self.assertIn("fetchOrgChartData()", raw)
        self.assertIn("await Promise.all([", raw)


if __name__ == "__main__":
    unittest.main()
