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

import output_forwarder as forwarder  # noqa: E402
from common import store_bridge_agent_session_token  # noqa: E402


class _DummyResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestOutputForwarderStrictAuthContract(unittest.TestCase):
    def test_relay_message_uses_bound_agent_sender(self):
        captured: dict[str, object] = {}

        def _fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _DummyResponse()

        forwarder._relay_sent_hashes.clear()
        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            ok = forwarder.send_relay_message("forwarder_probe", "user", "Hello from strict auth relay")

        self.assertTrue(ok)
        self.assertEqual(captured["url"], f"{forwarder.BRIDGE_URL}/send")
        self.assertEqual(captured["body"]["from"], "forwarder_probe")
        self.assertEqual(captured["body"]["meta"]["source"], "output_forwarder")

    def test_relay_prefers_agent_session_token_from_tmux_workspace(self):
        captured: dict[str, object] = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            store_bridge_agent_session_token(
                tmpdir,
                agent_id="forwarder_probe",
                session_token="agent-session-token",
            )

            def _fake_run(cmd, capture_output=False, text=False, timeout=0):
                if cmd[:4] == ["tmux", "show-environment", "-t", "acw_forwarder_probe"]:
                    key = cmd[4]
                    if key == "BRIDGE_CLI_WORKSPACE":
                        return mock.Mock(returncode=0, stdout=f"{key}={tmpdir}\n", stderr="")
                    return mock.Mock(returncode=1, stdout="", stderr="")
                return mock.Mock(returncode=1, stdout="", stderr="")

            def _fake_urlopen(request, timeout=0):
                captured["headers"] = dict(request.header_items())
                captured["body"] = json.loads(request.data.decode("utf-8"))
                return _DummyResponse()

            forwarder._relay_sent_hashes.clear()
            with mock.patch("subprocess.run", side_effect=_fake_run), mock.patch(
                "urllib.request.urlopen", side_effect=_fake_urlopen
            ):
                ok = forwarder.send_relay_message(
                    "forwarder_probe",
                    "user",
                    "Hello from strict auth relay",
                    session_name="acw_forwarder_probe",
                )

        self.assertTrue(ok)
        self.assertEqual(captured["body"]["from"], "forwarder_probe")
        self.assertEqual(captured["headers"]["X-bridge-token"], "agent-session-token")
        self.assertEqual(captured["headers"]["X-bridge-agent"], "forwarder_probe")


if __name__ == "__main__":
    unittest.main()
