from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from mcp_catalog import (  # noqa: E402
    build_client_mcp_config,
    catalog_path,
    planned_mcp_specs,
    requested_runtime_mcp_names,
    runtime_mcp_registry,
)


class TestMcpCatalog(unittest.TestCase):
    def test_catalog_file_exists_in_repo(self):
        self.assertTrue(catalog_path().exists())

    def test_runtime_registry_resolves_repo_local_paths(self):
        registry = runtime_mcp_registry()
        self.assertIn("bridge", registry)
        self.assertIn("bridge-rag", registry)
        self.assertIn("n8n", registry)
        self.assertTrue(registry["bridge"]["args"][0].endswith("Backend/bridge_mcp.py"))
        self.assertTrue(registry["bridge-rag"]["args"][0].endswith("Backend/bridge_rag_mcp.py"))
        self.assertTrue(registry["n8n"]["args"][0].endswith("Backend/n8n_mcp.py"))

    def test_requested_runtime_names_honor_include_in_all(self):
        self.assertEqual(
            requested_runtime_mcp_names("all"),
            ["bridge", "playwright", "aase", "ghost"],
        )
        self.assertEqual(
            requested_runtime_mcp_names("bridge-rag,n8n"),
            ["bridge", "bridge-rag", "n8n"],
        )

    def test_build_client_config_uses_central_registry(self):
        payload = build_client_mcp_config("bridge-rag")
        servers = payload["mcpServers"]
        self.assertIn("bridge", servers)
        self.assertIn("bridge-rag", servers)
        self.assertNotIn("n8n", servers)

    def test_planned_specs_include_official_vendor_mcps(self):
        planned = planned_mcp_specs()
        self.assertEqual(planned["openai-docs"]["url"], "https://mcp.openai.com/mcp")
        self.assertIn("googlemaps/google-maps-mcp-server", planned["google-maps"]["source_repo"])
        self.assertIn("googleapis/genai-toolbox", planned["google-genai-toolbox"]["source_repo"])


if __name__ == "__main__":
    unittest.main()
