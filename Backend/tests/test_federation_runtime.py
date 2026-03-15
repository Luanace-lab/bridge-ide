from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from federation_config import bootstrap_local_instance
from federation_gateway import FederationGateway
from federation_runtime import FederationRuntime, is_federated_target


class TestFederationRuntime(unittest.TestCase):
    def test_is_federated_target(self):
        self.assertTrue(is_federated_target("agent_x@inst-jp"))
        self.assertFalse(is_federated_target("agent_x"))
        self.assertFalse(is_federated_target("all"))

    def test_from_local_files_loads_peers(self):
        with tempfile.TemporaryDirectory() as td:
            peers_path = os.path.join(td, "peers.json")
            with open(peers_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "instances": {
                            "inst-b": {
                                "signing_public_key_hex": "11" * 32,
                                "exchange_public_key_hex": "22" * 32,
                            }
                        }
                    },
                    f,
                )

            runtime = FederationRuntime.from_local_files(
                base_dir=td,
                peers_file=peers_path,
                relay_url_override="",
            )
            self.assertIn("inst-b", runtime.peers)
            self.assertIsNone(runtime.relay_client)

    def test_send_text_requires_configured_relay(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = bootstrap_local_instance(base_dir=td)
            runtime = FederationRuntime(
                config=cfg,
                peers={},
                gateway=FederationGateway.from_config(config=cfg, peers={}),
                relay_client=None,
            )

            with self.assertRaises(RuntimeError):
                runtime.send_text(sender_agent="backend", target="agent@inst-b", content="hello")

    def test_ingest_inbound_frame_maps_to_local_message(self):
        with tempfile.TemporaryDirectory() as a_dir, tempfile.TemporaryDirectory() as b_dir:
            cfg_a = bootstrap_local_instance(base_dir=a_dir)
            cfg_b = bootstrap_local_instance(base_dir=b_dir)

            cfg_a["allowlist"] = [cfg_b["instance_id"]]
            cfg_b["allowlist"] = [cfg_a["instance_id"]]

            gw_a = FederationGateway.from_config(
                config=cfg_a,
                peers={
                    cfg_b["instance_id"]: {
                        "signing_public_key_hex": cfg_b["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_b["exchange_public_key_hex"],
                    }
                },
            )

            runtime_b = FederationRuntime(
                config=cfg_b,
                peers={
                    cfg_a["instance_id"]: {
                        "signing_public_key_hex": cfg_a["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_a["exchange_public_key_hex"],
                    }
                },
                gateway=FederationGateway.from_config(
                    config=cfg_b,
                    peers={
                        cfg_a["instance_id"]: {
                            "signing_public_key_hex": cfg_a["signing_public_key_hex"],
                            "exchange_public_key_hex": cfg_a["exchange_public_key_hex"],
                        }
                    },
                ),
                relay_client=None,
            )

            frame = gw_a.build_outbound_frame(
                sender_agent="backend",
                target=f"agent_x@{cfg_b['instance_id']}",
                plaintext=b"hello from federation",
            )
            mapped = runtime_b.ingest_inbound_frame(frame)

            self.assertEqual(mapped["from"], f"backend@{cfg_a['instance_id']}")
            self.assertEqual(mapped["to"], "agent_x")
            self.assertEqual(mapped["content"], "hello from federation")
            self.assertEqual(mapped["meta"]["federation"]["direction"], "inbound")

    def test_relay_client_handles_frame_in_worker_thread(self):
        import federation_runtime as runtime_mod

        relay = runtime_mod.FederationRelayClient(
            relay_url="ws://relay.invalid",
            instance_id="inst-a",
            signing_private_key_hex="11" * 32,
            on_frame=lambda _frame: None,
        )

        frame = {"federation_msg_id": "m1"}
        ws_message = json.dumps({"type": "frame", "frame": frame})

        calls: list[dict[str, object]] = []

        async def fake_to_thread(func, arg):
            calls.append({"func": func, "arg": arg})
            return func(arg)

        with mock.patch.object(runtime_mod.asyncio, "to_thread", side_effect=fake_to_thread):
            asyncio.run(relay._handle_ws_message(ws_message))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["arg"], frame)


if __name__ == "__main__":
    unittest.main()
