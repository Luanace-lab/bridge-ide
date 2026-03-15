"""Federation runtime: outbound hook + relay client + inbound injection helpers.

This module keeps Federation transport concerns outside server.py so the HTTP
handler can stay focused on request/response flow.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from federation_config import bootstrap_local_instance
from federation_crypto import sign_message
from federation_gateway import FederationGateway, parse_target
from federation_protocol import encode_frame
from federation_relay import auth_challenge_message

try:
    import websockets

    HAS_WEBSOCKETS = True
except Exception:
    HAS_WEBSOCKETS = False


InboundCallback = Callable[[dict[str, Any]], None]


def is_federated_target(target: str) -> bool:
    try:
        parse_target(target)
        return True
    except Exception:
        return False


def _load_peers(path: str) -> dict[str, dict[str, str]]:
    expanded = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(expanded):
        return {}

    with open(expanded, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and isinstance(data.get("instances"), dict):
        data = data["instances"]

    if not isinstance(data, dict):
        return {}

    peers: dict[str, dict[str, str]] = {}
    for raw_instance, raw_payload in data.items():
        instance_id = str(raw_instance).strip()
        if not instance_id or not isinstance(raw_payload, dict):
            continue

        signing = str(
            raw_payload.get("signing_public_key_hex")
            or raw_payload.get("signing_public")
            or ""
        ).strip()
        exchange = str(
            raw_payload.get("exchange_public_key_hex")
            or raw_payload.get("exchange_public")
            or ""
        ).strip()
        if not signing or not exchange:
            continue

        peers[instance_id] = {
            "signing_public_key_hex": signing,
            "exchange_public_key_hex": exchange,
        }
    return peers


class FederationRelayClient:
    """Persistent authenticated relay connection with reconnect and queueing."""

    def __init__(
        self,
        *,
        relay_url: str,
        instance_id: str,
        signing_private_key_hex: str,
        on_frame: InboundCallback | None = None,
        reconnect_seconds: float = 3.0,
    ) -> None:
        self.relay_url = relay_url.strip()
        self.instance_id = instance_id.strip()
        self.signing_private_key_hex = signing_private_key_hex.strip()
        self.on_frame = on_frame
        self.reconnect_seconds = max(0.5, float(reconnect_seconds))

        self._outbound: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=500)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._state_lock = threading.RLock()
        self._connected = False
        self._last_error = ""
        self._last_connect_ts = 0.0
        self._frames_sent = 0
        self._frames_received = 0
        self._acks_received = 0

    def start(self) -> None:
        if not HAS_WEBSOCKETS:
            raise RuntimeError("websockets dependency is missing")
        if not self.relay_url:
            raise ValueError("relay_url is required")
        if not self.instance_id:
            raise ValueError("instance_id is required")
        if not self.signing_private_key_hex:
            raise ValueError("signing_private_key_hex is required")

        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="federation-relay-client")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        try:
            self._outbound.put_nowait(None)
        except queue.Full:
            pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def enqueue_frame(self, frame: dict[str, Any]) -> None:
        encode_frame(frame)
        try:
            self._outbound.put_nowait(dict(frame))
        except queue.Full as exc:
            raise RuntimeError("federation outbound queue is full") from exc

    def health(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "connected": self._connected,
                "relay_url": self.relay_url,
                "queue_depth": self._outbound.qsize(),
                "last_error": self._last_error,
                "last_connect_ts": self._last_connect_ts,
                "frames_sent": self._frames_sent,
                "frames_received": self._frames_received,
                "acks_received": self._acks_received,
            }

    def _set_connected(self, value: bool) -> None:
        with self._state_lock:
            self._connected = value
            if value:
                self._last_connect_ts = time.time()

    def _set_error(self, error: str) -> None:
        with self._state_lock:
            self._last_error = error

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run_loop())
        except Exception as exc:
            self._set_error(f"relay client crashed: {exc}")

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(self.relay_url, max_size=64 * 1024) as ws:
                    await self._authenticate(ws)
                    self._set_connected(True)
                    self._set_error("")

                    sender_task = asyncio.create_task(self._sender_loop(ws))
                    try:
                        async for raw in ws:
                            await self._handle_ws_message(raw)
                            if self._stop_event.is_set():
                                break
                    finally:
                        sender_task.cancel()
                        try:
                            await sender_task
                        except (Exception, asyncio.CancelledError):
                            pass
            except Exception as exc:
                self._set_error(str(exc))
            finally:
                self._set_connected(False)

            if not self._stop_event.is_set():
                await asyncio.sleep(self.reconnect_seconds)

    async def _authenticate(self, ws: Any) -> None:
        await ws.send(
            json.dumps(
                {
                    "type": "auth_init",
                    "instance_id": self.instance_id,
                },
                ensure_ascii=False,
            )
        )

        raw_challenge = await asyncio.wait_for(ws.recv(), timeout=10.0)
        challenge_msg = json.loads(raw_challenge)
        if not isinstance(challenge_msg, dict) or challenge_msg.get("type") != "auth_challenge":
            raise RuntimeError("relay auth failed: expected auth_challenge")

        challenge_b64 = str(challenge_msg.get("challenge", "")).strip()
        challenge_instance = str(challenge_msg.get("instance_id", "")).strip()
        if not challenge_b64 or challenge_instance != self.instance_id:
            raise RuntimeError("relay auth failed: invalid challenge payload")

        signed = sign_message(
            auth_challenge_message(self.instance_id, challenge_b64),
            self.signing_private_key_hex,
        )
        await ws.send(
            json.dumps(
                {
                    "type": "auth_response",
                    "instance_id": self.instance_id,
                    "signature": signed,
                },
                ensure_ascii=False,
            )
        )

        raw_ok = await asyncio.wait_for(ws.recv(), timeout=10.0)
        ok_msg = json.loads(raw_ok)
        if not isinstance(ok_msg, dict) or ok_msg.get("type") != "auth_ok":
            err = ok_msg.get("error") if isinstance(ok_msg, dict) else "unknown"
            raise RuntimeError(f"relay auth failed: {err}")

    async def _sender_loop(self, ws: Any) -> None:
        while not self._stop_event.is_set():
            frame = await asyncio.to_thread(self._outbound.get)
            if frame is None:
                return

            await ws.send(
                json.dumps(
                    {
                        "type": "frame",
                        "frame": frame,
                    },
                    ensure_ascii=False,
                )
            )
            with self._state_lock:
                self._frames_sent += 1

    async def _handle_ws_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except Exception:
            return

        if not isinstance(data, dict):
            return

        msg_type = str(data.get("type", ""))
        if msg_type == "ack":
            with self._state_lock:
                self._acks_received += 1
            return

        if msg_type == "error":
            self._set_error(str(data.get("error", "relay error")))
            return

        if msg_type != "frame":
            return

        frame = data.get("frame")
        if not isinstance(frame, dict):
            return

        with self._state_lock:
            self._frames_received += 1

        if self.on_frame:
            await asyncio.to_thread(self.on_frame, frame)


@dataclass
class FederationRuntime:
    config: dict[str, Any]
    peers: dict[str, dict[str, str]]
    gateway: FederationGateway
    relay_client: FederationRelayClient | None = None

    @classmethod
    def from_local_files(
        cls,
        *,
        base_dir: str,
        peers_file: str,
        relay_url_override: str = "",
    ) -> "FederationRuntime":
        config = bootstrap_local_instance(base_dir=base_dir)
        peers = _load_peers(peers_file)
        gateway = FederationGateway.from_config(config=config, peers=peers)

        relay_url = relay_url_override.strip() or str(config.get("relay_url", "")).strip()
        relay_client: FederationRelayClient | None = None

        if relay_url:
            signing_path = str(config.get("signing_private_key_path", "")).strip()
            if not signing_path:
                raise ValueError("config missing signing_private_key_path")
            with open(signing_path, encoding="utf-8") as f:
                signing_private = f.read().strip()
            relay_client = FederationRelayClient(
                relay_url=relay_url,
                instance_id=str(config.get("instance_id", "")),
                signing_private_key_hex=signing_private,
            )

        return cls(config=config, peers=peers, gateway=gateway, relay_client=relay_client)

    def start(self, on_inbound: InboundCallback) -> None:
        if self.relay_client is None:
            return

        def _handle(frame: dict[str, Any]) -> None:
            inbound = self.ingest_inbound_frame(frame)
            on_inbound(inbound)

        self.relay_client.on_frame = _handle
        self.relay_client.start()

    def stop(self) -> None:
        if self.relay_client:
            self.relay_client.stop()

    def send_text(self, *, sender_agent: str, target: str, content: str) -> dict[str, Any]:
        if self.relay_client is None:
            raise RuntimeError("federation relay is not configured")

        frame = self.gateway.build_outbound_frame(
            sender_agent=sender_agent,
            target=target,
            plaintext=content.encode("utf-8"),
        )
        self.relay_client.enqueue_frame(frame)
        return frame

    def ingest_inbound_frame(self, frame: dict[str, Any]) -> dict[str, Any]:
        inbound = self.gateway.process_inbound_frame(frame)
        content = inbound["plaintext"].decode("utf-8", errors="replace")
        return {
            "from": f"{inbound['from_agent']}@{inbound['from_instance']}",
            "to": inbound["to_agent"],
            "content": content,
            "meta": {
                "federation": {
                    "direction": "inbound",
                    "federation_msg_id": inbound.get("federation_msg_id", ""),
                    "from_instance": inbound["from_instance"],
                    "to_instance": inbound["to_instance"],
                }
            },
        }

    def health(self) -> dict[str, Any]:
        relay_state = self.relay_client.health() if self.relay_client else None
        return {
            "enabled": True,
            "instance_id": str(self.config.get("instance_id", "")),
            "relay_configured": self.relay_client is not None,
            "relay": relay_state,
            "trusted_peers": len(self.peers),
        }
