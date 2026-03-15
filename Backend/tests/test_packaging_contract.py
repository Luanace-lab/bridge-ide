import sys
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"


class TestPackagingContract(unittest.TestCase):
    def test_pyproject_targets_bridge_ide_package(self):
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        scripts = data.get("project", {}).get("scripts", {})
        includes = data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {}).get("include", [])

        self.assertEqual(scripts.get("bridge-ide"), "bridge_ide.cli:main")
        self.assertIn("bridge_ide*", includes)
        self.assertTrue((ROOT / "bridge_ide" / "__init__.py").exists())
        self.assertTrue((ROOT / "bridge_ide" / "cli.py").exists())

    def test_bridge_ide_cli_imports_from_repo_root(self):
        sys.path.insert(0, str(ROOT))
        try:
            import bridge_ide.cli as cli  # type: ignore
            import bridge_ide._backend_path as backend_path  # type: ignore
        finally:
            try:
                sys.path.remove(str(ROOT))
            except ValueError:
                pass

        self.assertTrue(callable(cli.main))
        self.assertEqual(cli.build_parser().prog, "bridge-ide")
        self.assertEqual(backend_path.repo_root(), ROOT)
        self.assertEqual(backend_path.backend_dir(), ROOT / "Backend")

    def test_container_runtime_uses_env_driven_bind_hosts(self):
        server_raw = (ROOT / "Backend" / "server.py").read_text(encoding="utf-8")
        ws_raw = (ROOT / "Backend" / "websocket_server.py").read_text(encoding="utf-8")
        docker_raw = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn('PORT = _env_int("PORT", 9111)', server_raw)
        self.assertIn('WS_PORT = _env_int("WS_PORT", 9112)', server_raw)
        self.assertIn('HTTP_HOST = _env_host("BRIDGE_HTTP_HOST", "127.0.0.1")', server_raw)
        self.assertIn('WS_HOST = _env_host("BRIDGE_WS_HOST", HTTP_HOST)', server_raw)
        self.assertIn('(HTTP_HOST, PORT)', server_raw)
        self.assertIn("async with websockets.asyncio.server.serve(", ws_raw)
        self.assertIn("_ws_host_getter()", ws_raw)
        self.assertIn("_ws_port_getter()", ws_raw)
        self.assertIn('ENV BRIDGE_HTTP_HOST=0.0.0.0', docker_raw)
        self.assertIn('ENV BRIDGE_WS_HOST=0.0.0.0', docker_raw)
        self.assertIn('rm -f Backend/runtime_team.json', docker_raw)

    def test_docker_build_context_excludes_stale_runtime_overlay(self):
        dockerignore_raw = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("Backend/runtime_team.json", dockerignore_raw)

    def test_docker_compose_wires_host_n8n_and_control_plane_state(self):
        compose_raw = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn('./Backend/agent_state:/app/Backend/agent_state', compose_raw)
        self.assertIn('./Backend/workflow_registry.json:/app/Backend/workflow_registry.json', compose_raw)
        self.assertIn('./Backend/event_subscriptions.json:/app/Backend/event_subscriptions.json', compose_raw)
        self.assertIn('${HOME}/.config/bridge/tokens.json:/root/.config/bridge/tokens.json:ro', compose_raw)
        self.assertIn('${HOME}/.config/bridge/n8n.env:/root/.config/bridge/n8n.env:ro', compose_raw)
        self.assertIn('BRIDGE_HTTP_HOST=0.0.0.0', compose_raw)
        self.assertIn('BRIDGE_WS_HOST=0.0.0.0', compose_raw)
        self.assertIn('BRIDGE_HTTP_PUBLISH_PORT:-9111', compose_raw)
        self.assertIn('BRIDGE_WS_PUBLISH_PORT:-9112', compose_raw)
        self.assertIn('N8N_BASE_URL=${N8N_BASE_URL:-http://host.docker.internal:5678}', compose_raw)
        self.assertIn('N8N_API_KEY=${N8N_API_KEY:-}', compose_raw)
        self.assertIn('"host.docker.internal:host-gateway"', compose_raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
