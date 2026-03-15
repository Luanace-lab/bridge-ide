
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add Backend and tests dir to path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

from test_api_server import APITestCase

class TestBoardApiRegression(APITestCase):
    """
    Regression tests for the Board API (board_api.py).
    """

    def setUp(self):
        """Create some projects for testing before each test."""
        self.create_test_projects()

    def create_test_projects(self):
        """Helper to create some projects for testing."""
        self.post("/board/projects", {"project_id": "proj1", "name": "Project One"})
        self.post("/board/projects", {"project_id": "proj2", "name": "Project Two"})
        self.post("/board/projects", {"project_id": "proj3", "name": "Project Three"})

    def test_get_all_projects_limit_0(self):
        """
        Tests if GET /board/projects?limit=0 returns an empty list.
        This is the regression probe for board_limit_0.
        """
        print("Running test: test_get_all_projects_limit_0")
        
        # This is expected to fail initially, as the limit param is not implemented
        try:
            result = self.get("/board/projects?limit=0")
            
            # The ideal outcome is an empty list of projects
            self.assertIn("projects", result)
            self.assertEqual(len(result["projects"]), 0, 
                             "Expected 0 projects with limit=0, but got a different number.")
                             
        except Exception as e:
            # If the test fails in an unexpected way, we print the error
            # This helps in debugging the test itself.
            print(f"Test failed with an exception: {e}")
            self.fail(f"The test for limit=0 raised an unexpected exception: {e}")

    def test_get_all_projects_limit_1(self):
        """
        Tests if GET /board/projects?limit=1 returns exactly one project.
        """
        print("Running test: test_get_all_projects_limit_1")
        try:
            result = self.get("/board/projects?limit=1")
            
            self.assertIn("projects", result)
            self.assertEqual(len(result["projects"]), 1,
                             "Expected 1 project with limit=1, but got a different number.")

        except Exception as e:
            print(f"Test failed with an exception: {e}")
            self.fail(f"The test for limit=1 raised an unexpected exception: {e}")


if __name__ == "__main__":
    unittest.main()
