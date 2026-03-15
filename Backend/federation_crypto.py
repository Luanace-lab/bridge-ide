"""Federation cryptography helpers (V1) based on PyNaCl/libsodium."""

from __future__ import annotations

import base64
import os
from collections import OrderedDict
from typing import Any

from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
    crypto_box_beforenm,
)
from nacl.exceptions import BadSignatureError, CryptoError
from nacl.public import PrivateKey
from nacl.signing import SigningKey, VerifyKey

_NONCE_LEN = 24


def _to_b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _from_b64(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError("invalid base64 payload") from exc


def generate_signing_keypair() -> dict[str, str]:
    key = SigningKey.generate()
    return {
        "private_key_hex": key.encode().hex(),
        "public_key_hex": key.verify_key.encode().hex(),
    }


def generate_exchange_keypair() -> dict[str, str]:
    key = PrivateKey.generate()
    return {
        "private_key_hex": bytes(key).hex(),
        "public_key_hex": bytes(key.public_key).hex(),
    }


def _shared_key(*, own_private_key_hex: str, peer_public_key_hex: str) -> bytes:
    try:
        own_sk = bytes.fromhex(own_private_key_hex)
        peer_pk = bytes.fromhex(peer_public_key_hex)
    except ValueError as exc:
        raise ValueError("invalid key hex") from exc
    return crypto_box_beforenm(peer_pk, own_sk)


def encrypt_payload(
    *,
    plaintext: bytes,
    sender_private_key_hex: str,
    recipient_public_key_hex: str,
    aad: bytes = b"",
) -> dict[str, str]:
    if not isinstance(plaintext, (bytes, bytearray)):
        raise ValueError("plaintext must be bytes")

    nonce = os.urandom(_NONCE_LEN)
    shared = _shared_key(
        own_private_key_hex=sender_private_key_hex,
        peer_public_key_hex=recipient_public_key_hex,
    )
    ciphertext = crypto_aead_xchacha20poly1305_ietf_encrypt(
        bytes(plaintext),
        aad,
        nonce,
        shared,
    )
    return {
        "nonce_b64": _to_b64(nonce),
        "ciphertext_b64": _to_b64(ciphertext),
    }


def decrypt_payload(
    *,
    ciphertext_b64: str,
    nonce_b64: str,
    sender_public_key_hex: str,
    recipient_private_key_hex: str,
    aad: bytes = b"",
) -> bytes:
    nonce = _from_b64(nonce_b64)
    ciphertext = _from_b64(ciphertext_b64)
    if len(nonce) != _NONCE_LEN:
        raise ValueError("invalid nonce length")

    shared = _shared_key(
        own_private_key_hex=recipient_private_key_hex,
        peer_public_key_hex=sender_public_key_hex,
    )

    try:
        return crypto_aead_xchacha20poly1305_ietf_decrypt(
            ciphertext,
            aad,
            nonce,
            shared,
        )
    except CryptoError as exc:
        raise ValueError("decrypt failed") from exc


def sign_message(message: bytes, signing_private_key_hex: str) -> str:
    if not isinstance(message, (bytes, bytearray)):
        raise ValueError("message must be bytes")
    try:
        key = SigningKey(bytes.fromhex(signing_private_key_hex))
    except ValueError as exc:
        raise ValueError("invalid signing private key") from exc
    signature = key.sign(bytes(message)).signature
    return _to_b64(signature)


def verify_message_signature(
    *,
    message: bytes,
    signature_b64: str,
    signer_public_key_hex: str,
) -> bool:
    if not isinstance(message, (bytes, bytearray)):
        return False
    try:
        verify_key = VerifyKey(bytes.fromhex(signer_public_key_hex))
        signature = _from_b64(signature_b64)
        verify_key.verify(bytes(message), signature)
        return True
    except (ValueError, BadSignatureError):
        return False


class NonceReplayGuard:
    """In-memory nonce replay guard by session.

    V1 scope: process-local best-effort replay detection.
    """

    def __init__(self, max_entries_per_session: int = 2048) -> None:
        self._max_entries = max(1, int(max_entries_per_session))
        self._store: dict[str, OrderedDict[bytes, None]] = {}

    def seen_before(self, session_id: str, nonce: bytes) -> bool:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(nonce, (bytes, bytearray)):
            raise ValueError("nonce must be bytes")

        bucket = self._store.setdefault(session_id, OrderedDict())
        nonce_bytes = bytes(nonce)

        if nonce_bytes in bucket:
            return True

        bucket[nonce_bytes] = None
        while len(bucket) > self._max_entries:
            bucket.popitem(last=False)
        return False
