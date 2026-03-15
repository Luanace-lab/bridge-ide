from __future__ import annotations

import os
import sys
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from federation_protocol import (
    MAX_FRAME_SIZE,
    decode_frame,
    encode_frame,
    is_valid_agent_address,
    validate_federation_message,
)


class TestFederationProtocol(unittest.TestCase):
    def test_valid_agent_address(self):
        self.assertTrue(is_valid_agent_address("backend@inst-de"))
        self.assertTrue(is_valid_agent_address("agent_x@japan-bridge-01"))

    def test_invalid_agent_address(self):
        self.assertFalse(is_valid_agent_address("backend"))
        self.assertFalse(is_valid_agent_address("backend@@inst"))
        self.assertFalse(is_valid_agent_address("bad space@inst"))

    def test_validate_message_requires_core_fields(self):
        msg = {
            "version": 1,
            "type": "federation.message",
            "federation_msg_id": "abc",
            "from_instance": "inst-a",
            "to_instance": "inst-b",
            "from_agent": "backend",
            "to_agent": "agent_x",
            "cipher": {
                "alg": "xchacha20poly1305",
                "nonce": "x",
                "aad": "x",
                "ciphertext": "x",
            },
            "sig": "x",
            "sent_at": "2026-03-11T00:00:00Z",
        }
        validate_federation_message(msg)  # does not raise

        broken = dict(msg)
        broken.pop("cipher")
        with self.assertRaises(ValueError):
            validate_federation_message(broken)

    def test_frame_size_limit_64kb(self):
        frame = {"type": "federation.message", "blob": "a" * (MAX_FRAME_SIZE + 1024)}
        with self.assertRaises(ValueError):
            encode_frame(frame)

    def test_decode_frame_roundtrip(self):
        frame = {"type": "federation.message", "x": 1}
        raw = encode_frame(frame)
        decoded = decode_frame(raw)
        self.assertEqual(decoded, frame)

    def test_rejects_unsupported_version_and_cipher(self):
        msg = {
            "version": 2,
            "type": "federation.message",
            "federation_msg_id": "abc",
            "from_instance": "inst-a",
            "to_instance": "inst-b",
            "from_agent": "backend",
            "to_agent": "agent_x",
            "cipher": {
                "alg": "xchacha20poly1305",
                "nonce": "x",
                "aad": "x",
                "ciphertext": "x",
            },
            "sig": "x",
            "sent_at": "2026-03-11T00:00:00Z",
        }
        with self.assertRaises(ValueError):
            validate_federation_message(msg)

        msg["version"] = 1
        msg["cipher"]["alg"] = "aes-gcm"
        with self.assertRaises(ValueError):
            validate_federation_message(msg)


if __name__ == "__main__":
    unittest.main()
