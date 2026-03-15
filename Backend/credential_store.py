"""
Credential Store — Fernet-encrypted credential storage for Bridge agents.

Stores credentials per service/key in ~/.config/bridge/credentials/.
Each service gets its own encrypted JSON file.
Encryption key from BRIDGE_CRED_KEY env var (Fernet-compatible base64 key).

SECURITY: Values are NEVER logged, NEVER sent via chat, NEVER in plaintext on disk.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

log = logging.getLogger("credential_store")

CRED_DIR = os.path.expanduser("~/.config/bridge/credentials")
_LOCK = threading.Lock()

# Valid service categories
VALID_SERVICES = {"google", "github", "email", "wallet", "phone", "custom"}

# Management agents that can access any credential
_MANAGEMENT_AGENTS = {"viktor", "assi", "projektleiter", "ordo", "user"}


def _get_fernet():
    """Get Fernet instance from BRIDGE_CRED_KEY env var."""
    from cryptography.fernet import Fernet

    key = os.environ.get("BRIDGE_CRED_KEY", "")
    if not key:
        raise ValueError("BRIDGE_CRED_KEY environment variable not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def _service_path(service: str) -> str:
    """Path to encrypted service file."""
    return os.path.join(CRED_DIR, f"{service}.enc")


def _load_service(service: str) -> dict[str, dict[str, Any]]:
    """Load and decrypt a service file. Returns {key: {value, created_by, created_at}}."""
    path = _service_path(service)
    if not os.path.exists(path):
        return {}

    f = _get_fernet()
    try:
        with open(path, "rb") as fh:
            encrypted = fh.read()
        decrypted = f.decrypt(encrypted)
        return json.loads(decrypted)
    except Exception as exc:
        log.error("Failed to decrypt %s: %s", path, type(exc).__name__)
        raise ValueError(f"Failed to decrypt service '{service}': corrupted or wrong key")


def _save_service(service: str, data: dict[str, dict[str, Any]]) -> None:
    """Encrypt and save service data atomically."""
    os.makedirs(CRED_DIR, exist_ok=True)
    # Restrict directory permissions
    os.chmod(CRED_DIR, 0o700)

    f = _get_fernet()
    encrypted = f.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    path = _service_path(service)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(encrypted)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        # Cleanup temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _check_access(agent_id: str, entry: dict[str, Any]) -> bool:
    """Check if agent can access this credential entry."""
    if agent_id in _MANAGEMENT_AGENTS:
        return True
    return entry.get("created_by") == agent_id


def _validate_service(service: str) -> str | None:
    """Validate service name. Returns error message or None."""
    if not service or not service.strip():
        return "service must not be empty"
    if service not in VALID_SERVICES:
        return f"invalid service: {service}. Valid: {', '.join(sorted(VALID_SERVICES))}"
    return None


def _validate_key(key: str) -> str | None:
    """Validate credential key. Returns error message or None."""
    if not key or not key.strip():
        return "key must not be empty"
    if len(key) > 200:
        return "key too long (max 200 chars)"
    return None


def store(
    service: str,
    key: str,
    value: Any,
    agent_id: str = "unknown",
) -> dict[str, Any]:
    """Store a credential. Value is encrypted at rest."""
    from datetime import datetime, timezone

    err = _validate_service(service)
    if err:
        raise ValueError(err)
    err = _validate_key(key)
    if err:
        raise ValueError(err)

    with _LOCK:
        data = _load_service(service)
        data[key] = {
            "value": value,
            "created_by": agent_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_service(service, data)

    log.info("Credential stored: service=%s key=%s by=%s", service, key, agent_id)
    return {"ok": True, "service": service, "key": key}


def get(
    service: str,
    key: str,
    agent_id: str = "unknown",
) -> dict[str, Any]:
    """Retrieve a credential. ACL-checked."""
    err = _validate_service(service)
    if err:
        raise ValueError(err)
    err = _validate_key(key)
    if err:
        raise ValueError(err)

    with _LOCK:
        data = _load_service(service)

    entry = data.get(key)
    if not entry:
        raise KeyError(f"credential not found: {service}/{key}")

    if not _check_access(agent_id, entry):
        raise PermissionError(f"access denied: agent '{agent_id}' cannot read {service}/{key}")

    return {
        "service": service,
        "key": key,
        "value": entry["value"],
        "created_by": entry.get("created_by", "unknown"),
        "created_at": entry.get("created_at", ""),
    }


def delete(
    service: str,
    key: str,
    agent_id: str = "unknown",
) -> dict[str, Any]:
    """Delete a credential. ACL-checked."""
    err = _validate_service(service)
    if err:
        raise ValueError(err)
    err = _validate_key(key)
    if err:
        raise ValueError(err)

    with _LOCK:
        data = _load_service(service)
        entry = data.get(key)
        if not entry:
            raise KeyError(f"credential not found: {service}/{key}")

        if not _check_access(agent_id, entry):
            raise PermissionError(f"access denied: agent '{agent_id}' cannot delete {service}/{key}")

        del data[key]
        _save_service(service, data)

    log.info("Credential deleted: service=%s key=%s by=%s", service, key, agent_id)
    return {"ok": True, "service": service, "key": key}


def list_keys(
    service: str,
    agent_id: str = "unknown",
) -> dict[str, Any]:
    """List credential keys for a service. Only shows keys the agent can access."""
    err = _validate_service(service)
    if err:
        raise ValueError(err)

    with _LOCK:
        data = _load_service(service)

    keys = []
    for k, entry in data.items():
        if _check_access(agent_id, entry):
            keys.append({
                "key": k,
                "created_by": entry.get("created_by", "unknown"),
                "created_at": entry.get("created_at", ""),
            })

    return {"service": service, "keys": keys, "count": len(keys)}


def generate_key() -> str:
    """Generate a new Fernet key. Use this to create BRIDGE_CRED_KEY."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("ascii")
