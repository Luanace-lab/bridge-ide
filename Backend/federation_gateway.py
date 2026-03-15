"""Federation gateway helpers for outbound/inbound DM flow (V1)."""

from __future__ import annotations

import json
import base64
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from federation_config import is_peer_allowed
from federation_crypto import (
    NonceReplayGuard,
    decrypt_payload,
    encrypt_payload,
    sign_message,
    verify_message_signature,
)
from federation_protocol import encode_frame, validate_federation_message


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_target(target: str) -> tuple[str, str]:
    if not isinstance(target, str) or "@" not in target:
        raise ValueError("target must be in format agent@instance")
    agent, instance = target.split("@", 1)
    agent = agent.strip()
    instance = instance.strip()
    if not agent or not instance:
        raise ValueError("target must be in format agent@instance")
    return agent, instance


def _sign_payload_bytes(frame: dict[str, Any]) -> bytes:
    canonical = dict(frame)
    canonical.pop("sig", None)
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _aad_context(*, from_instance: str, to_instance: str, from_agent: str, to_agent: str) -> str:
    return f"{from_instance}->{to_instance}:{from_agent}->{to_agent}"


@dataclass
class FederationGateway:
    config: dict[str, Any]
    peers: dict[str, dict[str, str]]
    signing_private_key_hex: str
    exchange_private_key_hex: str
    replay_guard: NonceReplayGuard

    @classmethod
    def from_config(cls, config: dict[str, Any], peers: dict[str, dict[str, str]]) -> "FederationGateway":
        signing_path = str(config.get("signing_private_key_path", "")).strip()
        exchange_path = str(config.get("exchange_private_key_path", "")).strip()
        if not signing_path or not exchange_path:
            raise ValueError("config missing private key paths")

        with open(signing_path, encoding="utf-8") as f:
            signing_private = f.read().strip()
        with open(exchange_path, encoding="utf-8") as f:
            exchange_private = f.read().strip()

        return cls(
            config=config,
            peers=peers,
            signing_private_key_hex=signing_private,
            exchange_private_key_hex=exchange_private,
            replay_guard=NonceReplayGuard(),
        )

    def _require_peer(self, peer_instance: str) -> dict[str, str]:
        if not is_peer_allowed(self.config, peer_instance):
            raise ValueError(f"peer instance not allowed: {peer_instance}")
        peer = self.peers.get(peer_instance)
        if not peer:
            raise ValueError(f"unknown peer instance: {peer_instance}")
        if not peer.get("signing_public_key_hex") or not peer.get("exchange_public_key_hex"):
            raise ValueError("peer keys incomplete")
        return peer

    def build_outbound_frame(self, *, sender_agent: str, target: str, plaintext: bytes) -> dict[str, Any]:
        to_agent, to_instance = parse_target(target)
        peer = self._require_peer(to_instance)

        aad_context = _aad_context(
            from_instance=str(self.config["instance_id"]),
            to_instance=to_instance,
            from_agent=sender_agent,
            to_agent=to_agent,
        )
        aad = aad_context.encode("utf-8")
        cipher = encrypt_payload(
            plaintext=plaintext,
            sender_private_key_hex=self.exchange_private_key_hex,
            recipient_public_key_hex=peer["exchange_public_key_hex"],
            aad=aad,
        )

        frame: dict[str, Any] = {
            "version": 1,
            "type": "federation.message",
            "federation_msg_id": str(uuid.uuid4()),
            "from_instance": self.config["instance_id"],
            "to_instance": to_instance,
            "from_agent": sender_agent,
            "to_agent": to_agent,
            "cipher": {
                "alg": "xchacha20poly1305",
                "nonce": cipher["nonce_b64"],
                "aad": aad_context,
                "ciphertext": cipher["ciphertext_b64"],
            },
            "sig": "",
            "sent_at": _utc_now_iso(),
        }

        payload_bytes = _sign_payload_bytes(frame)
        frame["sig"] = sign_message(payload_bytes, self.signing_private_key_hex)
        return frame

    def process_inbound_frame(self, frame: dict[str, Any]) -> dict[str, Any]:
        # Enforce 64KB frame ceiling even when caller passes a decoded dict.
        encode_frame(frame)
        validate_federation_message(frame)

        local_instance = str(self.config.get("instance_id", "")).strip()
        if frame.get("to_instance") != local_instance:
            raise ValueError("frame not addressed to this instance")

        from_instance = str(frame.get("from_instance", "")).strip()
        peer = self._require_peer(from_instance)

        payload_bytes = _sign_payload_bytes(frame)
        if not verify_message_signature(
            message=payload_bytes,
            signature_b64=str(frame.get("sig", "")),
            signer_public_key_hex=peer["signing_public_key_hex"],
        ):
            raise ValueError("invalid frame signature")

        nonce_b64 = str(frame["cipher"]["nonce"])
        nonce_bytes = base64.b64decode(nonce_b64, validate=True)
        session = f"{from_instance}->{local_instance}"
        if self.replay_guard.seen_before(session, nonce_bytes):
            raise ValueError("replay detected")

        from_agent = str(frame.get("from_agent", "")).strip()
        to_agent = str(frame.get("to_agent", "")).strip()
        expected_aad = _aad_context(
            from_instance=from_instance,
            to_instance=local_instance,
            from_agent=from_agent,
            to_agent=to_agent,
        )
        if str(frame["cipher"].get("aad", "")).strip() != expected_aad:
            raise ValueError("aad context mismatch")
        aad = expected_aad.encode("utf-8")
        plaintext = decrypt_payload(
            ciphertext_b64=str(frame["cipher"]["ciphertext"]),
            nonce_b64=nonce_b64,
            sender_public_key_hex=peer["exchange_public_key_hex"],
            recipient_private_key_hex=self.exchange_private_key_hex,
            aad=aad,
        )

        return {
            "from_instance": from_instance,
            "to_instance": local_instance,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "plaintext": plaintext,
            "federation_msg_id": str(frame.get("federation_msg_id", "")),
        }
