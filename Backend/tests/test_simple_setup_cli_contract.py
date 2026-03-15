from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bridge_ide import cli  # noqa: E402


class TestSimpleSetupCLIContract(unittest.TestCase):
    def test_cli_init_creates_expected_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "demo-bridge"
            exit_code = cli.main(["init", str(project_dir)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((project_dir / "logs").exists())
            self.assertTrue((project_dir / "pids").exists())
            self.assertTrue((project_dir / "messages").exists())
            self.assertTrue((project_dir / "config").exists())
            self.assertTrue((project_dir / ".bridge").exists())
            self.assertTrue((project_dir / "team.json").exists())
            self.assertTrue((project_dir / "agents.conf").exists())
            self.assertTrue((project_dir / ".bridge" / "cred_key").exists())

            team_raw = (project_dir / "team.json").read_text(encoding="utf-8")
            team_data = json.loads(team_raw)
            self.assertEqual(team_data["agents"][0]["id"], "buddy")

    def test_cli_start_uses_backend_start_script(self) -> None:
        with mock.patch("bridge_ide.cli.subprocess.run") as run_mock:
            exit_code = cli.main(["start"])

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once()
        called_cmd = run_mock.call_args.args[0]
        called_cwd = run_mock.call_args.kwargs["cwd"]
        called_check = run_mock.call_args.kwargs["check"]

        self.assertTrue(str(called_cmd[0]).endswith("start_platform.sh"))
        self.assertTrue(str(called_cwd).endswith("/Backend"))
        self.assertTrue(called_check)

    def test_cli_stop_uses_backend_stop_script(self) -> None:
        with mock.patch("bridge_ide.cli.subprocess.run") as run_mock:
            exit_code = cli.main(["stop"])

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once()
        called_cmd = run_mock.call_args.args[0]
        called_cwd = run_mock.call_args.kwargs["cwd"]
        called_check = run_mock.call_args.kwargs["check"]

        self.assertTrue(str(called_cmd[0]).endswith("stop_platform.sh"))
        self.assertTrue(str(called_cwd).endswith("/Backend"))
        self.assertTrue(called_check)

    def test_cli_status_calls_status_endpoint(self) -> None:
        response_mock = mock.Mock()
        response_mock.text = "{\"status\": \"running\"}"

        with mock.patch("bridge_ide.cli.httpx.get", return_value=response_mock) as get_mock:
            with mock.patch("builtins.print") as print_mock:
                exit_code = cli.main(["status", "--url", "http://127.0.0.1:9111"])

        self.assertEqual(exit_code, 0)
        get_mock.assert_called_once_with("http://127.0.0.1:9111/status", timeout=5.0)
        response_mock.raise_for_status.assert_called_once()
        print_mock.assert_called_once_with(response_mock.text)

    def test_package_install_contract_declares_bridge_ide_entrypoint(self) -> None:
        pyproject_path = REPO_ROOT / "pyproject.toml"
        pyproject_raw = pyproject_path.read_text(encoding="utf-8")

        self.assertIn('name = "bridge-ide"', pyproject_raw)
        self.assertIn('bridge-ide = "bridge_ide.cli:main"', pyproject_raw)

    def test_cli_start_returns_error_code_when_script_fails(self) -> None:
        with mock.patch(
            "bridge_ide.cli.subprocess.run",
            side_effect=subprocess.CalledProcessError(returncode=2, cmd=["start_platform.sh"]),
        ):
            with mock.patch("builtins.print") as print_mock:
                exit_code = cli.main(["start"])

        self.assertEqual(exit_code, 1)
        self.assertIn("failed", print_mock.call_args.args[0].lower())

    def test_cli_status_returns_error_code_when_server_is_unreachable(self) -> None:
        request = httpx.Request("GET", "http://127.0.0.1:9111/status")
        with mock.patch(
            "bridge_ide.cli.httpx.get",
            side_effect=httpx.ConnectError("connection failed", request=request),
        ):
            with mock.patch("builtins.print") as print_mock:
                exit_code = cli.main(["status", "--url", "http://127.0.0.1:9111"])

        self.assertEqual(exit_code, 1)
        self.assertIn("not reachable", print_mock.call_args.args[0].lower())

    def test_package_build_creates_bridge_ide_wheel(self) -> None:
        python_bin = shutil.which("python3")
        self.assertIsNotNone(python_bin)

        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    python_bin,
                    "-m",
                    "pip",
                    "wheel",
                    ".",
                    "--no-deps",
                    "--no-build-isolation",
                    "-w",
                    tmpdir,
                ],
                cwd=str(REPO_ROOT),
                check=True,
                capture_output=True,
                text=True,
            )
            wheels = [p.name for p in Path(tmpdir).glob("*.whl")]
            self.assertTrue(any(name.startswith("bridge_ide-0.1.0-") for name in wheels))


if __name__ == "__main__":
    unittest.main()
