"""
config.py — Central Configuration for Bridge IDE

Single source of truth for all configurable values.
Environment variables override defaults.

Architecture Reference: R4_Architekturentwurf.md
Phase: A — Foundation

Usage:
  from config import cfg
  print(cfg.HTTP_PORT)       # 9111
  print(cfg.PROJECT_PATH)    # /home/user/bridge
"""

from __future__ import annotations

import os
from pathlib import Path


class BridgeConfig:
    """Central configuration for the Bridge platform.

    All values can be overridden via environment variables
    prefixed with BRIDGE_ (e.g., BRIDGE_HTTP_PORT=9111).
    """

    def __init__(self) -> None:
        # -------------------------------------------------------------------
        # Network
        # -------------------------------------------------------------------
        self.HTTP_PORT: int = self._env_int("BRIDGE_HTTP_PORT", 9111)
        self.WS_PORT: int = self._env_int("BRIDGE_WS_PORT", 9112)
        self.HTTP_HOST: str = self._env("BRIDGE_HTTP_HOST", "127.0.0.1")
        self.UI_PORT: int = self._env_int("BRIDGE_UI_PORT", 8787)

        # -------------------------------------------------------------------
        # Paths
        # -------------------------------------------------------------------
        self.PROJECT_PATH: Path = Path(
            self._env("BRIDGE_PROJECT_PATH", str(Path(__file__).resolve().parent.parent.parent))
        )
        self.BRIDGE_DIR: Path = self.PROJECT_PATH / "bridge"
        self.BACKEND_DIR: Path = self.PROJECT_PATH / "BRIDGE" / "Backend"
        self.FRONTEND_DIR: Path = self.PROJECT_PATH / "BRIDGE" / "Frontend"
        self.AGENT_SESSIONS_DIR: Path = self.PROJECT_PATH / ".agent_sessions"
        self.MESSAGES_DIR: Path = self.BRIDGE_DIR / "messages"
        self.LOGS_DIR: Path = self.BRIDGE_DIR / "logs"
        self.VAULT_PATH: Path = self.PROJECT_PATH / ".vault" / "credentials.json"
        self.AUDIT_DIR: Path = self.PROJECT_PATH / ".vault" / "audit"

        # -------------------------------------------------------------------
        # Agent Defaults
        # -------------------------------------------------------------------
        self.AGENT_HEARTBEAT_INTERVAL: float = self._env_float(
            "BRIDGE_HEARTBEAT_INTERVAL", 30.0
        )
        self.AGENT_DISCONNECT_TIMEOUT: float = self._env_float(
            "BRIDGE_DISCONNECT_TIMEOUT", 60.0
        )
        self.AGENT_CLEANUP_TTL: float = self._env_float(
            "BRIDGE_CLEANUP_TTL", 300.0
        )
        self.AGENT_MAX_IDLE: float = self._env_float(
            "BRIDGE_MAX_IDLE", 600.0
        )

        # -------------------------------------------------------------------
        # Message Limits
        # -------------------------------------------------------------------
        self.MAX_MESSAGE_SIZE: int = self._env_int(
            "BRIDGE_MAX_MESSAGE_SIZE", 500_000
        )  # 500 KB
        self.MAX_BODY_SIZE: int = self._env_int(
            "BRIDGE_MAX_BODY_SIZE", 1_048_576
        )  # 1 MB
        self.MAX_SENDER_LENGTH: int = self._env_int(
            "BRIDGE_MAX_SENDER_LENGTH", 128
        )
        self.MAX_MESSAGES_IN_MEMORY: int = self._env_int(
            "BRIDGE_MAX_MESSAGES_IN_MEMORY", 50_000
        )
        self.MESSAGES_TRIM_TO: int = self._env_int(
            "BRIDGE_MESSAGES_TRIM_TO", 25_000
        )
        self.DEFAULT_HISTORY_LIMIT: int = self._env_int(
            "BRIDGE_DEFAULT_HISTORY_LIMIT", 50
        )

        # -------------------------------------------------------------------
        # Approval Gate
        # -------------------------------------------------------------------
        self.APPROVAL_TIMEOUT: float = self._env_float(
            "BRIDGE_APPROVAL_TIMEOUT", 300.0
        )  # 5 minutes
        self.APPROVAL_EXPIRE_CHECK_INTERVAL: float = self._env_float(
            "BRIDGE_APPROVAL_EXPIRE_CHECK", 30.0
        )

        # -------------------------------------------------------------------
        # Credential Vault
        # -------------------------------------------------------------------
        self.VAULT_PASSPHRASE: str = self._env("BRIDGE_VAULT_PASSPHRASE", "")

        # -------------------------------------------------------------------
        # Context Warning
        # -------------------------------------------------------------------
        self.CONTEXT_WARNING_THRESHOLD: int = self._env_int(
            "BRIDGE_CONTEXT_WARNING_THRESHOLD", 95
        )  # Percent

        # -------------------------------------------------------------------
        # Feature Flags
        # -------------------------------------------------------------------
        self.ENABLE_SOUL_ENGINE: bool = self._env_bool(
            "BRIDGE_ENABLE_SOUL_ENGINE", True
        )
        self.ENABLE_APPROVAL_GATE: bool = self._env_bool(
            "BRIDGE_ENABLE_APPROVAL_GATE", True
        )
        self.ENABLE_CREDENTIAL_VAULT: bool = self._env_bool(
            "BRIDGE_ENABLE_CREDENTIAL_VAULT", True
        )
        self.ENABLE_AUTO_CLEANUP: bool = self._env_bool(
            "BRIDGE_ENABLE_AUTO_CLEANUP", True
        )
        self.ENABLE_WATCHER: bool = self._env_bool(
            "BRIDGE_ENABLE_WATCHER", True
        )

    # -----------------------------------------------------------------------
    # Environment variable helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _env(key: str, default: str) -> str:
        return os.environ.get(key, default)

    @staticmethod
    def _env_int(key: str, default: int) -> int:
        val = os.environ.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except ValueError:
            return default

    @staticmethod
    def _env_float(key: str, default: float) -> float:
        val = os.environ.get(key)
        if val is None:
            return default
        try:
            return float(val)
        except ValueError:
            return default

    @staticmethod
    def _env_bool(key: str, default: bool) -> bool:
        val = os.environ.get(key)
        if val is None:
            return default
        return val.lower() in ("1", "true", "yes", "on")

    def to_dict(self) -> dict:
        """Export configuration as dict (for debugging/logging)."""
        result = {}
        for key, value in self.__dict__.items():
            if key.startswith("_"):
                continue
            if key == "VAULT_PASSPHRASE":
                result[key] = "***" if value else "(not set)"
            elif isinstance(value, Path):
                result[key] = str(value)
            else:
                result[key] = value
        return result


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

cfg = BridgeConfig()
