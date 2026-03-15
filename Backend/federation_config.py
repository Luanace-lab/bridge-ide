"""Federation local configuration and key material management (V1)."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from typing import Any

from federation_crypto import generate_exchange_keypair, generate_signing_keypair

DEFAULT_BASE_DIR = os.path.expanduser("~/.bridge/federation")
CONFIG_FILE_NAME = "config.json"
SIGNING_PRIVATE_FILE = "signing_private.key"
SIGNING_PUBLIC_FILE = "signing_public.key"
EXCHANGE_PRIVATE_FILE = "exchange_private.key"
EXCHANGE_PUBLIC_FILE = "exchange_public.key"


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    os.chmod(path, 0o700)


def _write_text_secure(path: str, value: str, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
    finally:
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def _base_dir(base_dir: str | None = None) -> str:
    return os.path.abspath(os.path.expanduser(base_dir or DEFAULT_BASE_DIR))


def _config_path(base_dir: str | None = None) -> str:
    return os.path.join(_base_dir(base_dir), CONFIG_FILE_NAME)


def save_federation_config(config: dict[str, Any], base_dir: str | None = None) -> None:
    root = _base_dir(base_dir)
    _ensure_dir(root)
    path = _config_path(root)
    data = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=root, prefix=".federation_config_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def load_federation_config(base_dir: str | None = None) -> dict[str, Any]:
    path = _config_path(base_dir)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("invalid federation config")
    return data


def is_peer_allowed(config: dict[str, Any], peer_instance_id: str) -> bool:
    allowlist = config.get("allowlist", [])
    if not isinstance(allowlist, list):
        return False
    return str(peer_instance_id) in {str(v) for v in allowlist}


def bootstrap_local_instance(base_dir: str | None = None) -> dict[str, Any]:
    root = _base_dir(base_dir)
    _ensure_dir(root)

    signing_private_path = os.path.join(root, SIGNING_PRIVATE_FILE)
    signing_public_path = os.path.join(root, SIGNING_PUBLIC_FILE)
    exchange_private_path = os.path.join(root, EXCHANGE_PRIVATE_FILE)
    exchange_public_path = os.path.join(root, EXCHANGE_PUBLIC_FILE)

    if not (os.path.isfile(signing_private_path) and os.path.isfile(signing_public_path)):
        signing = generate_signing_keypair()
        _write_text_secure(signing_private_path, signing["private_key_hex"], mode=0o600)
        _write_text_secure(signing_public_path, signing["public_key_hex"], mode=0o600)

    if not (os.path.isfile(exchange_private_path) and os.path.isfile(exchange_public_path)):
        exchange = generate_exchange_keypair()
        _write_text_secure(exchange_private_path, exchange["private_key_hex"], mode=0o600)
        _write_text_secure(exchange_public_path, exchange["public_key_hex"], mode=0o600)

    config_path = _config_path(root)
    if os.path.isfile(config_path):
        config = load_federation_config(root)
    else:
        config = {
            "version": 1,
            "instance_id": f"inst-{uuid.uuid4().hex[:12]}",
            "allowlist": [],
            "relay_url": "",
        }

    config["signing_public_key_hex"] = _read_text(signing_public_path)
    config["exchange_public_key_hex"] = _read_text(exchange_public_path)
    config["signing_private_key_path"] = signing_private_path
    config["exchange_private_key_path"] = exchange_private_path

    save_federation_config(config, root)
    return config
