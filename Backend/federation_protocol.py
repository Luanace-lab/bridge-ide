"""Federation protocol helpers (V1).

Scope V1:
- Agent direct messages only (no cross-instance broadcast)
- JSON frame size hard-limit: 64KB
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_FRAME_SIZE = 64 * 1024  # 64KB

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_AGENT_ADDRESS_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}@[A-Za-z0-9_-]{1,128}$")
_RESERVED_BROADCAST_TARGETS = {"all", "all_managers", "leads"}


def is_valid_agent_address(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return bool(_AGENT_ADDRESS_RE.fullmatch(value.strip()))


def validate_federation_message(message: dict[str, Any]) -> None:
    if not isinstance(message, dict):
        raise ValueError("federation message must be an object")

    required = {
        "version",
        "type",
        "federation_msg_id",
        "from_instance",
        "to_instance",
        "from_agent",
        "to_agent",
        "cipher",
        "sig",
        "sent_at",
    }
    missing = sorted(required - set(message.keys()))
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    if message["version"] != 1:
        raise ValueError("unsupported version")
    if message["type"] != "federation.message":
        raise ValueError("unsupported message type")

    from_instance = str(message["from_instance"])
    to_instance = str(message["to_instance"])
    from_agent = str(message["from_agent"])
    to_agent = str(message["to_agent"])

    if not _INSTANCE_ID_RE.fullmatch(from_instance):
        raise ValueError("invalid from_instance")
    if not _INSTANCE_ID_RE.fullmatch(to_instance):
        raise ValueError("invalid to_instance")
    if not _AGENT_ID_RE.fullmatch(from_agent):
        raise ValueError("invalid from_agent")
    if not _AGENT_ID_RE.fullmatch(to_agent):
        raise ValueError("invalid to_agent")
    if to_agent in _RESERVED_BROADCAST_TARGETS:
        raise ValueError("cross-instance broadcast is not supported in V1")

    cipher = message["cipher"]
    if not isinstance(cipher, dict):
        raise ValueError("cipher must be an object")
    for key in ("alg", "nonce", "aad", "ciphertext"):
        if key not in cipher or not isinstance(cipher[key], str) or not cipher[key].strip():
            raise ValueError(f"cipher.{key} missing or invalid")

    if cipher["alg"] != "xchacha20poly1305":
        raise ValueError("unsupported cipher algorithm")


def encode_frame(frame: dict[str, Any]) -> bytes:
    payload = json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_SIZE:
        raise ValueError(f"frame exceeds max size ({MAX_FRAME_SIZE} bytes)")
    return payload


def decode_frame(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_FRAME_SIZE:
        raise ValueError(f"frame exceeds max size ({MAX_FRAME_SIZE} bytes)")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid federation frame") from exc
    if not isinstance(decoded, dict):
        raise ValueError("frame payload must be a JSON object")
    return decoded
