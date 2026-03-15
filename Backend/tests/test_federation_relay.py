from __future__ import annotations

import base64
import os
import sys
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from federation_crypto import generate_signing_keypair, sign_message
from federation_relay import (
    RelayHub,
    auth_challenge_message,
    resolve_bind_host,
    verify_auth_response,
)


def _sample_frame(msg_id: str = "m1", to_instance: str = "inst-b", to_agent: str = "agent_x") -> dict:
    return {
        "version": 1,
        "type": "federation.message",
        "federation_msg_id": msg_id,
        "from_instance": "inst-a",
        "to_instance": to_instance,
        "from_agent": "backend",
        "to_agent": to_agent,
        "cipher": {
            "alg": "xchacha20poly1305",
            "nonce": "bm9uY2U=",
            "aad": "YWFk",
            "ciphertext": "Y2lwaGVy",
        },
        "sig": "c2ln",
        "sent_at": "2026-03-11T00:00:00Z",
    }


class TestRelayHub(unittest.TestCase):
    def test_delivers_to_target_instance_only(self):
        hub = RelayHub(limit_per_minute=100)

        delivered_a = []
        delivered_b = []
        hub.register_instance("inst-a", lambda frame: delivered_a.append(frame))
        hub.register_instance("inst-b", lambda frame: delivered_b.append(frame))

        hub.handle_frame("inst-a", _sample_frame())

        self.assertEqual(len(delivered_a), 0)
        self.assertEqual(len(delivered_b), 1)

    def test_rate_limit_100_frames_per_minute(self):
        hub = RelayHub(limit_per_minute=100)

        delivered_b = []
        hub.register_instance("inst-b", lambda frame: delivered_b.append(frame))

        for i in range(100):
            hub.handle_frame("inst-a", _sample_frame(msg_id=f"m{i}"))

        with self.assertRaises(ValueError):
            hub.handle_frame("inst-a", _sample_frame(msg_id="m-over"))

    def test_rejects_broadcast_targets_in_v1(self):
        hub = RelayHub(limit_per_minute=100)
        hub.register_instance("inst-b", lambda frame: None)

        with self.assertRaises(ValueError):
            hub.handle_frame("inst-a", _sample_frame(to_agent="all"))


class TestRelayAuthAndBind(unittest.TestCase):
    def test_verify_auth_response_success_and_failure(self):
        keys = generate_signing_keypair()
        challenge = base64.b64encode(os.urandom(32)).decode("ascii")
        msg = auth_challenge_message("inst-a", challenge)
        signature = sign_message(msg, keys["private_key_hex"])

        ok = verify_auth_response(
            instance_id="inst-a",
            challenge_b64=challenge,
            signature_b64=signature,
            trusted_signing_keys={"inst-a": keys["public_key_hex"]},
        )
        self.assertTrue(ok)

        bad = verify_auth_response(
            instance_id="inst-a",
            challenge_b64=challenge,
            signature_b64=signature[:-2] + "AA",
            trusted_signing_keys={"inst-a": keys["public_key_hex"]},
        )
        self.assertFalse(bad)

    def test_bind_defaults_and_public_guard(self):
        self.assertEqual(resolve_bind_host(public=False), "127.0.0.1")
        self.assertEqual(resolve_bind_host(public=True), "0.0.0.0")
        with self.assertRaises(ValueError):
            resolve_bind_host(public=False, host_override="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
