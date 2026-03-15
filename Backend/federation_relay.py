"""Federation relay (V1): separate mini-server + relay hub.

V1 scope:
- Agent direct messages only (no cross-instance broadcast)
- Encrypted payload passthrough only
- Per-source-instance rate limit (default 100 frames/min)
- Ed25519 challenge-response authentication per instance
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import time
from collections import defaultdict, deque
from typing import Any, Callable

from federation_crypto import verify_message_signature
from federation_protocol import encode_frame, validate_federation_message

OnFrameCallback = Callable[[dict[str, Any]], None]
_AUTH_CONTEXT = "bridge-federation-auth-v1"


def _spawn(coro: Any) -> None:
    """Create task with explicit error surfacing (no silent failures)."""
    task = asyncio.create_task(coro)

    def _done(t: asyncio.Task[Any]) -> None:
        try:
            _ = t.result()
        except Exception as exc:  # pragma: no cover - defensive runtime logging
            print(f"[federation_relay] async task failed: {exc}")

    task.add_done_callback(_done)


def _auth_challenge_message(instance_id: str, challenge_b64: str) -> bytes:
    return f"{_AUTH_CONTEXT}:{instance_id}:{challenge_b64}".encode("utf-8")


def auth_challenge_message(instance_id: str, challenge_b64: str) -> bytes:
    """Public helper for auth challenge canonical message construction."""
    return _auth_challenge_message(instance_id, challenge_b64)


def verify_auth_response(
    *,
    instance_id: str,
    challenge_b64: str,
    signature_b64: str,
    trusted_signing_keys: dict[str, str],
) -> bool:
    signer_pub = trusted_signing_keys.get(instance_id, "")
    if not signer_pub:
        return False
    msg = _auth_challenge_message(instance_id, challenge_b64)
    return verify_message_signature(
        message=msg,
        signature_b64=signature_b64,
        signer_public_key_hex=signer_pub,
    )


def resolve_bind_host(*, public: bool, host_override: str | None = None) -> str:
    if host_override:
        host = host_override.strip()
        if host in {"0.0.0.0", "::"} and not public:
            raise ValueError("public bind requires --public")
        return host
    return "0.0.0.0" if public else "127.0.0.1"


def load_trusted_signing_keys(path: str) -> dict[str, str]:
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        return {}
    with open(expanded, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and isinstance(data.get("instances"), dict):
        data = data["instances"]

    if not isinstance(data, dict):
        return {}

    out: dict[str, str] = {}
    for k, v in data.items():
        kid = str(k).strip()
        pub = str(v).strip()
        if kid and pub:
            out[kid] = pub
    return out


class RelayHub:
    def __init__(self, limit_per_minute: int = 100) -> None:
        self._callbacks: dict[str, OnFrameCallback] = {}
        self._rate_limit = max(1, int(limit_per_minute))
        self._recent: dict[str, deque[float]] = defaultdict(deque)

    def register_instance(self, instance_id: str, on_frame: OnFrameCallback) -> None:
        if not instance_id:
            raise ValueError("instance_id is required")
        self._callbacks[instance_id] = on_frame

    def unregister_instance(self, instance_id: str) -> None:
        self._callbacks.pop(instance_id, None)
        self._recent.pop(instance_id, None)

    def _enforce_rate_limit(self, source_instance: str) -> None:
        now = time.monotonic()
        bucket = self._recent[source_instance]
        cutoff = now - 60.0
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._rate_limit:
            raise ValueError("rate limit exceeded for source instance")
        bucket.append(now)

    def handle_frame(self, source_instance: str, frame: dict[str, Any]) -> dict[str, Any]:
        if not source_instance:
            raise ValueError("source_instance is required")

        validate_federation_message(frame)
        if frame.get("from_instance") != source_instance:
            raise ValueError("from_instance mismatch")

        # Enforce max frame size on serialized payload.
        encode_frame(frame)

        self._enforce_rate_limit(source_instance)

        target_instance = str(frame.get("to_instance", "")).strip()
        cb = self._callbacks.get(target_instance)
        if cb is None:
            raise ValueError(f"target instance not connected: {target_instance}")

        cb(frame)
        return {"ok": True, "delivered_to": target_instance}


async def run_relay_server(
    host: str = "127.0.0.1",
    port: int = 9120,
    limit_per_minute: int = 100,
    trusted_signing_keys: dict[str, str] | None = None,
    allow_public: bool = False,
) -> None:
    if host in {"0.0.0.0", "::"} and not allow_public:
        raise ValueError("public bind requires allow_public=True")

    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("websockets is required for federation_relay server") from exc

    hub = RelayHub(limit_per_minute=limit_per_minute)
    ws_by_instance: dict[str, Any] = {}
    trusted = dict(trusted_signing_keys or {})

    async def _send_json(ws: Any, payload: dict[str, Any]) -> None:
        await ws.send(json.dumps(payload, ensure_ascii=False))

    async def _handler(ws: Any) -> None:
        instance_id = ""
        registered = False
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            hello = json.loads(raw)
            if not isinstance(hello, dict) or hello.get("type") != "auth_init":
                await _send_json(ws, {"type": "error", "error": "first message must be auth_init"})
                await ws.close()
                return

            instance_id = str(hello.get("instance_id", "")).strip()
            if not instance_id:
                await _send_json(ws, {"type": "error", "error": "missing instance_id"})
                await ws.close()
                return
            if instance_id not in trusted:
                await _send_json(ws, {"type": "error", "error": "instance is not trusted"})
                await ws.close()
                return

            challenge_b64 = base64.b64encode(os.urandom(32)).decode("ascii")
            await _send_json(ws, {"type": "auth_challenge", "instance_id": instance_id, "challenge": challenge_b64})

            raw_resp = await asyncio.wait_for(ws.recv(), timeout=10.0)
            resp = json.loads(raw_resp)
            if not isinstance(resp, dict) or resp.get("type") != "auth_response":
                await _send_json(ws, {"type": "error", "error": "auth_response required"})
                await ws.close()
                return
            if str(resp.get("instance_id", "")).strip() != instance_id:
                await _send_json(ws, {"type": "error", "error": "instance_id mismatch"})
                await ws.close()
                return

            signature_b64 = str(resp.get("signature", "")).strip()
            if not verify_auth_response(
                instance_id=instance_id,
                challenge_b64=challenge_b64,
                signature_b64=signature_b64,
                trusted_signing_keys=trusted,
            ):
                await _send_json(ws, {"type": "error", "error": "authentication failed"})
                await ws.close()
                return

            ws_by_instance[instance_id] = ws
            registered = True

            def _deliver(frame: dict[str, Any]) -> None:
                target_ws = ws_by_instance.get(str(frame.get("to_instance", "")))
                if target_ws is None:
                    return
                _spawn(_send_json(target_ws, {"type": "frame", "frame": frame}))

            hub.register_instance(instance_id, _deliver)
            await _send_json(ws, {"type": "auth_ok", "instance_id": instance_id})

            async for raw_msg in ws:
                try:
                    data = json.loads(raw_msg)
                except json.JSONDecodeError:
                    await _send_json(ws, {"type": "error", "error": "invalid json"})
                    continue

                if not isinstance(data, dict) or data.get("type") != "frame":
                    await _send_json(ws, {"type": "error", "error": "unsupported message type"})
                    continue

                frame = data.get("frame")
                if not isinstance(frame, dict):
                    await _send_json(ws, {"type": "error", "error": "frame must be object"})
                    continue

                try:
                    result = hub.handle_frame(instance_id, frame)
                    await _send_json(ws, {"type": "ack", **result})
                except ValueError as exc:
                    await _send_json(ws, {"type": "error", "error": str(exc)})
        finally:
            # Race-safe cleanup: only unregister if this websocket is still the active mapping.
            if instance_id and registered and ws_by_instance.get(instance_id) is ws:
                hub.unregister_instance(instance_id)
                ws_by_instance.pop(instance_id, None)

    async with websockets.asyncio.server.serve(_handler, host, port, max_size=64 * 1024):
        await asyncio.Future()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge Federation Relay (V1)")
    parser.add_argument("--host", default="", help="bind host (default: safe localhost unless --public)")
    parser.add_argument("--public", action="store_true", help="allow public bind (0.0.0.0)")
    parser.add_argument("--port", type=int, default=9120)
    parser.add_argument("--limit", type=int, default=100, help="max frames/minute per source instance")
    parser.add_argument(
        "--trusted-keys",
        default="~/.bridge/federation/trusted_keys.json",
        help="JSON file with trusted instance signing public keys",
    )
    args = parser.parse_args()

    host = resolve_bind_host(public=bool(args.public), host_override=args.host or None)
    trusted = load_trusted_signing_keys(args.trusted_keys)
    asyncio.run(
        run_relay_server(
            host=host,
            port=args.port,
            limit_per_minute=args.limit,
            trusted_signing_keys=trusted,
            allow_public=bool(args.public),
        )
    )


if __name__ == "__main__":
    main()
