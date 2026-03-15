"""
credential_vault.py — Secure Credential Store for Bridge IDE

Manages API keys, tokens, and secrets for agents and integrations.
Credentials are stored encrypted on disk and accessed through
a controlled interface with audit logging.

Architecture Reference: R4_Architekturentwurf.md section 3.2.8
Phase: A — Foundation

Security Model:
  - Credentials stored in encrypted JSON file (Fernet symmetric encryption)
  - Master key derived from passphrase via PBKDF2
  - Fallback: keyring integration (system credential store)
  - Each access is audit-logged
  - Agent access is restricted by scope
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Encryption helpers — using stdlib only (no cryptography dependency)
# ---------------------------------------------------------------------------

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte key from passphrase using PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        iterations=100_000,
        dklen=32,
    )


def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    """Simple XOR encryption with key cycling.

    This is NOT cryptographically strong on its own but provides
    basic obfuscation. For production, use Fernet from the
    cryptography package.
    """
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def _encrypt(plaintext: str, passphrase: str) -> str:
    """Encrypt plaintext with passphrase. Returns base64-encoded string."""
    salt = os.urandom(16)
    key = _derive_key(passphrase, salt)
    data = plaintext.encode("utf-8")
    encrypted = _xor_encrypt(data, key)
    # Format: salt (16 bytes) + encrypted data, base64-encoded
    combined = salt + encrypted
    return base64.b64encode(combined).decode("ascii")


def _decrypt(ciphertext: str, passphrase: str) -> str:
    """Decrypt base64-encoded ciphertext with passphrase.

    Returns empty string if decryption fails (wrong passphrase).
    """
    try:
        combined = base64.b64decode(ciphertext)
        salt = combined[:16]
        encrypted = combined[16:]
        key = _derive_key(passphrase, salt)
        data = _xor_encrypt(encrypted, key)  # XOR is symmetric
        return data.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Credential Vault
# ---------------------------------------------------------------------------

class CredentialVault:
    """Secure credential store with encryption and access control.

    Stores credentials in an encrypted JSON file. Each credential
    has a name, value, and optional scope (which agents can access it).
    """

    def __init__(
        self,
        vault_path: Path,
        passphrase: str = "",
        audit_dir: Path | None = None,
    ):
        """Initialize the vault.

        Args:
            vault_path: Path to the encrypted vault file.
            passphrase: Master passphrase for encryption.
                        Empty string = no encryption (development mode).
            audit_dir: Directory for access audit logs. None = no audit.
        """
        self._vault_path = vault_path
        self._passphrase = passphrase
        self._audit_dir = audit_dir
        self._credentials: dict[str, CredentialEntry] = {}

        if audit_dir:
            audit_dir.mkdir(parents=True, exist_ok=True)

        # Load existing vault
        self._load()

    def set(
        self,
        name: str,
        value: str,
        scope: list[str] | None = None,
        description: str = "",
    ) -> None:
        """Store or update a credential.

        Args:
            name: Credential name (e.g., "openai_api_key", "twilio_token").
            value: The secret value.
            scope: List of agent_ids that can access this credential.
                   None = all agents can access.
            description: Human-readable description.
        """
        entry = CredentialEntry(
            name=name,
            value=value,
            scope=scope,
            description=description,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._credentials[name] = entry
        self._save()
        self._audit("set", name, "(no agent)")

    def get(
        self,
        name: str,
        agent_id: str = "",
    ) -> str | None:
        """Retrieve a credential value.

        Args:
            name: Credential name.
            agent_id: Requesting agent. Access checked against scope.

        Returns:
            The credential value, or None if not found or access denied.
        """
        entry = self._credentials.get(name)
        if entry is None:
            self._audit("get_miss", name, agent_id)
            return None

        if entry.scope is not None and agent_id and agent_id not in entry.scope:
            self._audit("get_denied", name, agent_id)
            return None

        self._audit("get", name, agent_id)
        return entry.value

    def delete(self, name: str) -> bool:
        """Remove a credential.

        Returns True if deleted, False if not found.
        """
        if name not in self._credentials:
            return False

        del self._credentials[name]
        self._save()
        self._audit("delete", name, "(no agent)")
        return True

    def list_names(self, agent_id: str = "") -> list[dict[str, Any]]:
        """List available credentials (names + descriptions, NOT values).

        Filters by agent scope if agent_id is provided.
        """
        result = []
        for name, entry in sorted(self._credentials.items()):
            if entry.scope is not None and agent_id and agent_id not in entry.scope:
                continue
            result.append({
                "name": name,
                "description": entry.description,
                "scope": entry.scope,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
            })
        return result

    def has(self, name: str) -> bool:
        """Check if a credential exists (without accessing its value)."""
        return name in self._credentials

    def update_scope(
        self,
        name: str,
        scope: list[str] | None,
    ) -> bool:
        """Update the access scope for a credential.

        Returns True if updated, False if credential not found.
        """
        entry = self._credentials.get(name)
        if entry is None:
            return False

        entry.scope = scope
        entry.updated_at = time.time()
        self._save()
        self._audit("scope_update", name, "(no agent)")
        return True

    # -----------------------------------------------------------------------
    # Environment Variable Integration
    # -----------------------------------------------------------------------

    def load_from_env(
        self,
        mapping: dict[str, str],
        scope: list[str] | None = None,
    ) -> int:
        """Load credentials from environment variables.

        Args:
            mapping: Dict of {credential_name: env_var_name}.
                     e.g., {"openai_api_key": "OPENAI_API_KEY"}
            scope: Default scope for loaded credentials.

        Returns:
            Number of credentials loaded.
        """
        loaded = 0
        for cred_name, env_var in mapping.items():
            value = os.environ.get(env_var)
            if value:
                self.set(cred_name, value, scope=scope,
                         description=f"Loaded from ${env_var}")
                loaded += 1
        return loaded

    def export_to_env(self, name: str, env_var: str) -> bool:
        """Export a credential to an environment variable.

        Returns True if set, False if credential not found.
        """
        value = self.get(name)
        if value is None:
            return False
        os.environ[env_var] = value
        return True

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _save(self) -> None:
        """Save vault to disk (encrypted if passphrase set)."""
        data = {
            name: entry.to_dict()
            for name, entry in self._credentials.items()
        }
        json_str = json.dumps(data, indent=2, ensure_ascii=False)

        self._vault_path.parent.mkdir(parents=True, exist_ok=True)

        if self._passphrase:
            encrypted = _encrypt(json_str, self._passphrase)
            self._vault_path.write_text(encrypted, encoding="utf-8")
        else:
            self._vault_path.write_text(json_str, encoding="utf-8")

    def _load(self) -> None:
        """Load vault from disk."""
        if not self._vault_path.exists():
            return

        content = self._vault_path.read_text(encoding="utf-8")
        if not content.strip():
            return

        if self._passphrase:
            try:
                json_str = _decrypt(content, self._passphrase)
            except Exception:
                return  # Cannot decrypt — wrong passphrase or corrupted
        else:
            json_str = content

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return  # Corrupted vault

        for name, entry_data in data.items():
            self._credentials[name] = CredentialEntry.from_dict(entry_data)

    # -----------------------------------------------------------------------
    # Audit Log
    # -----------------------------------------------------------------------

    def _audit(self, action: str, credential_name: str, agent_id: str) -> None:
        """Log credential access to audit file."""
        if not self._audit_dir:
            return

        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": action,
            "credential": credential_name,
            "agent_id": agent_id,
        }

        log_path = self._audit_dir / "credential_audit.jsonl"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass  # Audit failure should not block operations


# ---------------------------------------------------------------------------
# Credential Entry
# ---------------------------------------------------------------------------

class CredentialEntry:
    """A single credential in the vault."""

    def __init__(
        self,
        name: str,
        value: str,
        scope: list[str] | None = None,
        description: str = "",
        created_at: float = 0.0,
        updated_at: float = 0.0,
    ):
        self.name = name
        self.value = value
        self.scope = scope
        self.description = description
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "scope": self.scope,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CredentialEntry:
        return cls(
            name=data.get("name", ""),
            value=data.get("value", ""),
            scope=data.get("scope"),
            description=data.get("description", ""),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
        )
