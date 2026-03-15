from __future__ import annotations

import os
import sys
import base64
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from federation_crypto import (
    NonceReplayGuard,
    decrypt_payload,
    encrypt_payload,
    generate_exchange_keypair,
    generate_signing_keypair,
    sign_message,
    verify_message_signature,
)


class TestFederationCrypto(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip_with_aad(self):
        sender = generate_exchange_keypair()
        recipient = generate_exchange_keypair()

        plaintext = b"hello federation"
        aad = b"frame-meta-v1"

        frame = encrypt_payload(
            plaintext=plaintext,
            sender_private_key_hex=sender["private_key_hex"],
            recipient_public_key_hex=recipient["public_key_hex"],
            aad=aad,
        )

        out = decrypt_payload(
            ciphertext_b64=frame["ciphertext_b64"],
            nonce_b64=frame["nonce_b64"],
            sender_public_key_hex=sender["public_key_hex"],
            recipient_private_key_hex=recipient["private_key_hex"],
            aad=aad,
        )
        self.assertEqual(out, plaintext)

    def test_decrypt_rejects_tampered_ciphertext(self):
        sender = generate_exchange_keypair()
        recipient = generate_exchange_keypair()

        frame = encrypt_payload(
            plaintext=b"secret",
            sender_private_key_hex=sender["private_key_hex"],
            recipient_public_key_hex=recipient["public_key_hex"],
            aad=b"aad",
        )

        tampered = frame["ciphertext_b64"][:-2] + "AA"
        with self.assertRaises(ValueError):
            decrypt_payload(
                ciphertext_b64=tampered,
                nonce_b64=frame["nonce_b64"],
                sender_public_key_hex=sender["public_key_hex"],
                recipient_private_key_hex=recipient["private_key_hex"],
                aad=b"aad",
            )

    def test_decrypt_rejects_wrong_aad(self):
        sender = generate_exchange_keypair()
        recipient = generate_exchange_keypair()

        frame = encrypt_payload(
            plaintext=b"secret",
            sender_private_key_hex=sender["private_key_hex"],
            recipient_public_key_hex=recipient["public_key_hex"],
            aad=b"good-aad",
        )

        with self.assertRaises(ValueError):
            decrypt_payload(
                ciphertext_b64=frame["ciphertext_b64"],
                nonce_b64=frame["nonce_b64"],
                sender_public_key_hex=sender["public_key_hex"],
                recipient_private_key_hex=recipient["private_key_hex"],
                aad=b"bad-aad",
            )

    def test_sign_verify_roundtrip(self):
        signer = generate_signing_keypair()
        message = b"federation-envelope"
        sig = sign_message(message, signer["private_key_hex"])

        ok = verify_message_signature(
            message=message,
            signature_b64=sig,
            signer_public_key_hex=signer["public_key_hex"],
        )
        self.assertTrue(ok)

    def test_sign_verify_rejects_tamper(self):
        signer = generate_signing_keypair()
        sig = sign_message(b"payload-a", signer["private_key_hex"])

        ok = verify_message_signature(
            message=b"payload-b",
            signature_b64=sig,
            signer_public_key_hex=signer["public_key_hex"],
        )
        self.assertFalse(ok)

    def test_encrypt_rejects_invalid_key_hex(self):
        recipient = generate_exchange_keypair()
        with self.assertRaises(ValueError):
            encrypt_payload(
                plaintext=b"x",
                sender_private_key_hex="not-hex",
                recipient_public_key_hex=recipient["public_key_hex"],
                aad=b"aad",
            )

    def test_decrypt_rejects_invalid_nonce_length(self):
        sender = generate_exchange_keypair()
        recipient = generate_exchange_keypair()
        frame = encrypt_payload(
            plaintext=b"hello",
            sender_private_key_hex=sender["private_key_hex"],
            recipient_public_key_hex=recipient["public_key_hex"],
            aad=b"aad",
        )
        bad_nonce = base64.b64encode(os.urandom(23)).decode("ascii")
        with self.assertRaises(ValueError):
            decrypt_payload(
                ciphertext_b64=frame["ciphertext_b64"],
                nonce_b64=bad_nonce,
                sender_public_key_hex=sender["public_key_hex"],
                recipient_private_key_hex=recipient["private_key_hex"],
                aad=b"aad",
            )


class TestNonceReplayGuard(unittest.TestCase):
    def test_nonce_reuse_detected(self):
        guard = NonceReplayGuard(max_entries_per_session=4)
        session_id = "peer-a"
        nonce = os.urandom(24)

        self.assertFalse(guard.seen_before(session_id, nonce))
        self.assertTrue(guard.seen_before(session_id, nonce))


if __name__ == "__main__":
    unittest.main()
