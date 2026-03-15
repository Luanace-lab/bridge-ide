from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from federation_config import bootstrap_local_instance
from federation_crypto import sign_message
from federation_gateway import FederationGateway
from federation_protocol import MAX_FRAME_SIZE


def _resign_frame(frame: dict[str, object], signing_private_key_hex: str) -> None:
    canonical = dict(frame)
    canonical.pop("sig", None)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    frame["sig"] = sign_message(payload, signing_private_key_hex)


class TestFederationGateway(unittest.TestCase):
    def test_outbound_inbound_roundtrip(self):
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
            gw_b = FederationGateway.from_config(
                config=cfg_b,
                peers={
                    cfg_a["instance_id"]: {
                        "signing_public_key_hex": cfg_a["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_a["exchange_public_key_hex"],
                    }
                },
            )

            frame = gw_a.build_outbound_frame(
                sender_agent="backend",
                target=f"agent_x@{cfg_b['instance_id']}",
                plaintext=b"hello from a",
            )

            inbound = gw_b.process_inbound_frame(frame)
            self.assertEqual(inbound["from_agent"], "backend")
            self.assertEqual(inbound["to_agent"], "agent_x")
            self.assertEqual(inbound["plaintext"], b"hello from a")

    def test_deny_by_default_allowlist(self):
        with tempfile.TemporaryDirectory() as a_dir, tempfile.TemporaryDirectory() as b_dir:
            cfg_a = bootstrap_local_instance(base_dir=a_dir)
            cfg_b = bootstrap_local_instance(base_dir=b_dir)

            cfg_a["allowlist"] = []
            gw_a = FederationGateway.from_config(
                config=cfg_a,
                peers={
                    cfg_b["instance_id"]: {
                        "signing_public_key_hex": cfg_b["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_b["exchange_public_key_hex"],
                    }
                },
            )

            with self.assertRaises(ValueError):
                gw_a.build_outbound_frame(
                    sender_agent="backend",
                    target=f"agent_x@{cfg_b['instance_id']}",
                    plaintext=b"blocked",
                )

    def test_replay_nonce_rejected(self):
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
            gw_b = FederationGateway.from_config(
                config=cfg_b,
                peers={
                    cfg_a["instance_id"]: {
                        "signing_public_key_hex": cfg_a["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_a["exchange_public_key_hex"],
                    }
                },
            )

            frame = gw_a.build_outbound_frame(
                sender_agent="backend",
                target=f"agent_x@{cfg_b['instance_id']}",
                plaintext=b"once",
            )
            gw_b.process_inbound_frame(frame)
            with self.assertRaises(ValueError):
                gw_b.process_inbound_frame(frame)

    def test_rejects_tampered_signature(self):
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
            gw_b = FederationGateway.from_config(
                config=cfg_b,
                peers={
                    cfg_a["instance_id"]: {
                        "signing_public_key_hex": cfg_a["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_a["exchange_public_key_hex"],
                    }
                },
            )

            frame = gw_a.build_outbound_frame(
                sender_agent="backend",
                target=f"agent_x@{cfg_b['instance_id']}",
                plaintext=b"hello from a",
            )
            frame["sig"] = frame["sig"][:-2] + "AA"
            with self.assertRaises(ValueError):
                gw_b.process_inbound_frame(frame)

    def test_rejects_tampered_ciphertext(self):
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
            gw_b = FederationGateway.from_config(
                config=cfg_b,
                peers={
                    cfg_a["instance_id"]: {
                        "signing_public_key_hex": cfg_a["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_a["exchange_public_key_hex"],
                    }
                },
            )

            frame = gw_a.build_outbound_frame(
                sender_agent="backend",
                target=f"agent_x@{cfg_b['instance_id']}",
                plaintext=b"hello from a",
            )
            frame["cipher"]["ciphertext"] = frame["cipher"]["ciphertext"][:-2] + "AA"
            _resign_frame(frame, gw_a.signing_private_key_hex)
            with self.assertRaises(ValueError):
                gw_b.process_inbound_frame(frame)

    def test_rejects_wrong_to_instance(self):
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
            gw_b = FederationGateway.from_config(
                config=cfg_b,
                peers={
                    cfg_a["instance_id"]: {
                        "signing_public_key_hex": cfg_a["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_a["exchange_public_key_hex"],
                    }
                },
            )

            frame = gw_a.build_outbound_frame(
                sender_agent="backend",
                target=f"agent_x@{cfg_b['instance_id']}",
                plaintext=b"hello from a",
            )
            frame["to_instance"] = "inst-wrong"
            with self.assertRaises(ValueError):
                gw_b.process_inbound_frame(frame)

    def test_inbound_deny_by_default_allowlist(self):
        with tempfile.TemporaryDirectory() as a_dir, tempfile.TemporaryDirectory() as b_dir:
            cfg_a = bootstrap_local_instance(base_dir=a_dir)
            cfg_b = bootstrap_local_instance(base_dir=b_dir)
            cfg_a["allowlist"] = [cfg_b["instance_id"]]
            cfg_b["allowlist"] = []

            gw_a = FederationGateway.from_config(
                config=cfg_a,
                peers={
                    cfg_b["instance_id"]: {
                        "signing_public_key_hex": cfg_b["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_b["exchange_public_key_hex"],
                    }
                },
            )
            gw_b = FederationGateway.from_config(
                config=cfg_b,
                peers={
                    cfg_a["instance_id"]: {
                        "signing_public_key_hex": cfg_a["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_a["exchange_public_key_hex"],
                    }
                },
            )

            frame = gw_a.build_outbound_frame(
                sender_agent="backend",
                target=f"agent_x@{cfg_b['instance_id']}",
                plaintext=b"blocked by inbound allowlist",
            )
            with self.assertRaises(ValueError):
                gw_b.process_inbound_frame(frame)

    def test_rejects_oversized_frame_even_if_dict_input(self):
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
            gw_b = FederationGateway.from_config(
                config=cfg_b,
                peers={
                    cfg_a["instance_id"]: {
                        "signing_public_key_hex": cfg_a["signing_public_key_hex"],
                        "exchange_public_key_hex": cfg_a["exchange_public_key_hex"],
                    }
                },
            )

            frame = gw_a.build_outbound_frame(
                sender_agent="backend",
                target=f"agent_x@{cfg_b['instance_id']}",
                plaintext=b"hello from a",
            )
            frame["padding"] = "x" * MAX_FRAME_SIZE
            with self.assertRaises(ValueError):
                gw_b.process_inbound_frame(frame)


if __name__ == "__main__":
    unittest.main()
