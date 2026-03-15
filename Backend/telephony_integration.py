"""
telephony_integration.py — Telephony Integration

Provides outbound call and SMS capabilities for agents via
Twilio API. Voice synthesis via ElevenLabs API for AI-powered calls.

Architecture Reference: R3_RealWorld_Capabilities.md
Phase: B — Capabilities

Features:
  - Outbound calls via Twilio
  - SMS sending via Twilio
  - Voice synthesis via ElevenLabs (optional)
  - Call status tracking
  - Safety classification (ALL calls/SMS require approval)
  - Operation logging for audit trail

Design:
  - Pure HTTP via urllib — no SDK dependency
  - Approval-required for ALL outbound operations
  - Thread-safe
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"

DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs "Rachel"
DEFAULT_VOICE_MODEL = "eleven_monolingual_v1"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TelephonySafety(Enum):
    """Safety classification for telephony operations."""

    APPROVAL_REQUIRED = "approval_required"  # ALL operations require approval


class CallStatus(Enum):
    """Call status."""

    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BUSY = "busy"
    NO_ANSWER = "no-answer"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class ConnectionStatus(Enum):
    """Service connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    AUTH_FAILED = "auth_failed"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class CallRecord:
    """Record of a phone call."""

    call_sid: str = ""
    from_number: str = ""
    to_number: str = ""
    status: str = "queued"
    direction: str = "outbound"
    duration: int = 0
    agent_id: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_sid": self.call_sid,
            "from_number": self.from_number,
            "to_number": self.to_number,
            "status": self.status,
            "direction": self.direction,
            "duration": self.duration,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
        }


@dataclass
class SMSRecord:
    """Record of an SMS message."""

    message_sid: str = ""
    from_number: str = ""
    to_number: str = ""
    body: str = ""
    status: str = "queued"
    agent_id: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_sid": self.message_sid,
            "from_number": self.from_number,
            "to_number": self.to_number,
            "body": self.body,
            "status": self.status,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
        }


@dataclass
class TelephonyResult:
    """Result of a telephony operation."""

    success: bool
    safety: TelephonySafety
    data: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "safety": self.safety.value,
            "data": self.data,
            "error": self.error,
        }


@dataclass
class TelephonyOperation:
    """Audit log entry for telephony operations."""

    timestamp: float
    operation: str
    agent_id: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "operation": self.operation,
            "agent_id": self.agent_id,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Telephony Client
# ---------------------------------------------------------------------------

class TelephonyClient:
    """Telephony integration client.

    Provides outbound calls and SMS via Twilio with
    ElevenLabs voice synthesis. ALL operations require approval.
    """

    def __init__(
        self,
        twilio_account_sid: str = "",
        twilio_auth_token: str = "",
        twilio_from_number: str = "",
        elevenlabs_api_key: str = "",
        elevenlabs_voice_id: str = DEFAULT_VOICE_ID,
    ) -> None:
        """Initialize telephony client.

        Args:
            twilio_account_sid: Twilio Account SID.
            twilio_auth_token: Twilio Auth Token.
            twilio_from_number: Default outbound phone number.
            elevenlabs_api_key: ElevenLabs API key (optional).
            elevenlabs_voice_id: ElevenLabs voice ID.
        """
        self._twilio_sid = twilio_account_sid
        self._twilio_token = twilio_auth_token
        self._from_number = twilio_from_number
        self._elevenlabs_key = elevenlabs_api_key
        self._voice_id = elevenlabs_voice_id
        self._call_log: list[CallRecord] = []
        self._sms_log: list[SMSRecord] = []
        self._operation_log: list[TelephonyOperation] = []
        self._lock = threading.Lock()

    # -------------------------------------------------------------------
    # Connection Checks
    # -------------------------------------------------------------------

    def check_twilio_connection(self) -> ConnectionStatus:
        """Check Twilio API connection.

        Returns:
            Connection status.
        """
        if not self._twilio_sid or not self._twilio_token:
            return ConnectionStatus.DISCONNECTED

        try:
            url = f"{TWILIO_API_BASE}/Accounts/{self._twilio_sid}.json"
            result = self._twilio_get(url)
            if result and result.get("sid"):
                return ConnectionStatus.CONNECTED
            return ConnectionStatus.DISCONNECTED
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return ConnectionStatus.AUTH_FAILED
            return ConnectionStatus.DISCONNECTED
        except Exception:
            return ConnectionStatus.DISCONNECTED

    def check_elevenlabs_connection(self) -> ConnectionStatus:
        """Check ElevenLabs API connection.

        Returns:
            Connection status.
        """
        if not self._elevenlabs_key:
            return ConnectionStatus.DISCONNECTED

        try:
            url = f"{ELEVENLABS_API_BASE}/user"
            req = urllib.request.Request(url)
            req.add_header("xi-api-key", self._elevenlabs_key)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data:
                    return ConnectionStatus.CONNECTED
            return ConnectionStatus.DISCONNECTED
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return ConnectionStatus.AUTH_FAILED
            return ConnectionStatus.DISCONNECTED
        except Exception:
            return ConnectionStatus.DISCONNECTED

    # -------------------------------------------------------------------
    # Outbound Calls (Approval Required)
    # -------------------------------------------------------------------

    def make_call(
        self,
        to_number: str,
        twiml: str = "",
        message: str = "",
        agent_id: str = "",
        skip_safety: bool = False,
    ) -> TelephonyResult:
        """Make an outbound phone call.

        Args:
            to_number: Destination phone number (E.164 format).
            twiml: TwiML instructions for the call.
            message: Simple text message to speak (converted to TwiML).
            agent_id: Agent making the call.
            skip_safety: Skip safety check (for pre-approved calls).

        Returns:
            TelephonyResult. Blocked if not pre-approved.
        """
        if not skip_safety:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error="Phone calls require human approval. Use approval_gate to request.",
            )

        if not self._twilio_sid or not self._twilio_token:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error="Twilio not configured",
            )

        if not twiml and message:
            twiml = f"<Response><Say>{message}</Say></Response>"

        try:
            url = f"{TWILIO_API_BASE}/Accounts/{self._twilio_sid}/Calls.json"
            data = {
                "To": to_number,
                "From": self._from_number,
                "Twiml": twiml,
            }

            result = self._twilio_post(url, data)
            call_sid = result.get("sid", "") if result else ""

            record = CallRecord(
                call_sid=call_sid,
                from_number=self._from_number,
                to_number=to_number,
                status=result.get("status", "queued") if result else "failed",
                agent_id=agent_id,
            )

            with self._lock:
                self._call_log.append(record)

            self._log("make_call", agent_id, f"To: {to_number}, SID: {call_sid}")
            return TelephonyResult(
                success=True,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                data=record.to_dict(),
            )

        except Exception as e:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error=str(e),
            )

    def get_call_status(self, call_sid: str) -> TelephonyResult:
        """Get status of a call.

        Args:
            call_sid: Twilio Call SID.

        Returns:
            TelephonyResult with call status.
        """
        if not self._twilio_sid or not self._twilio_token:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error="Twilio not configured",
            )

        try:
            url = f"{TWILIO_API_BASE}/Accounts/{self._twilio_sid}/Calls/{call_sid}.json"
            result = self._twilio_get(url)
            return TelephonyResult(
                success=True,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                data=result,
            )
        except Exception as e:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error=str(e),
            )

    # -------------------------------------------------------------------
    # SMS (Approval Required)
    # -------------------------------------------------------------------

    def send_sms(
        self,
        to_number: str,
        body: str,
        agent_id: str = "",
        skip_safety: bool = False,
    ) -> TelephonyResult:
        """Send an SMS message.

        Args:
            to_number: Destination phone number.
            body: SMS message body.
            agent_id: Agent making the call.
            skip_safety: Skip safety check (for pre-approved sends).

        Returns:
            TelephonyResult. Blocked if not pre-approved.
        """
        if not skip_safety:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error="SMS sending requires human approval. Use approval_gate to request.",
            )

        if not self._twilio_sid or not self._twilio_token:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error="Twilio not configured",
            )

        try:
            url = f"{TWILIO_API_BASE}/Accounts/{self._twilio_sid}/Messages.json"
            data = {
                "To": to_number,
                "From": self._from_number,
                "Body": body,
            }

            result = self._twilio_post(url, data)
            msg_sid = result.get("sid", "") if result else ""

            record = SMSRecord(
                message_sid=msg_sid,
                from_number=self._from_number,
                to_number=to_number,
                body=body,
                status=result.get("status", "queued") if result else "failed",
                agent_id=agent_id,
            )

            with self._lock:
                self._sms_log.append(record)

            self._log("send_sms", agent_id, f"To: {to_number}")
            return TelephonyResult(
                success=True,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                data=record.to_dict(),
            )

        except Exception as e:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error=str(e),
            )

    # -------------------------------------------------------------------
    # ElevenLabs Voice Synthesis
    # -------------------------------------------------------------------

    def synthesize_voice(
        self,
        text: str,
        voice_id: str = "",
        agent_id: str = "",
    ) -> TelephonyResult:
        """Synthesize speech from text using ElevenLabs.

        Args:
            text: Text to synthesize.
            voice_id: ElevenLabs voice ID. Empty = default.
            agent_id: Agent making the call.

        Returns:
            TelephonyResult with audio data (bytes).
        """
        if not self._elevenlabs_key:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error="ElevenLabs not configured",
            )

        vid = voice_id or self._voice_id
        try:
            url = f"{ELEVENLABS_API_BASE}/text-to-speech/{vid}"
            payload = json.dumps({
                "text": text,
                "model_id": DEFAULT_VOICE_MODEL,
            }).encode()

            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("xi-api-key", self._elevenlabs_key)
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "audio/mpeg")

            with urllib.request.urlopen(req, timeout=30) as resp:
                audio_data = resp.read()

            self._log("synthesize_voice", agent_id,
                      f"Text length: {len(text)}, Voice: {vid}")
            return TelephonyResult(
                success=True,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                data={"audio_size": len(audio_data), "voice_id": vid},
            )

        except Exception as e:
            return TelephonyResult(
                success=False,
                safety=TelephonySafety.APPROVAL_REQUIRED,
                error=str(e),
            )

    # -------------------------------------------------------------------
    # Logs
    # -------------------------------------------------------------------

    def get_call_log(
        self,
        limit: int = 50,
        agent_id: str = "",
    ) -> list[CallRecord]:
        """Get call log entries.

        Args:
            limit: Maximum entries.
            agent_id: Filter by agent. Empty = all.

        Returns:
            List of CallRecord entries (newest first).
        """
        with self._lock:
            log = list(reversed(self._call_log))
        if agent_id:
            log = [c for c in log if c.agent_id == agent_id]
        return log[:limit]

    def get_sms_log(
        self,
        limit: int = 50,
        agent_id: str = "",
    ) -> list[SMSRecord]:
        """Get SMS log entries.

        Args:
            limit: Maximum entries.
            agent_id: Filter by agent. Empty = all.

        Returns:
            List of SMSRecord entries (newest first).
        """
        with self._lock:
            log = list(reversed(self._sms_log))
        if agent_id:
            log = [s for s in log if s.agent_id == agent_id]
        return log[:limit]

    def get_operation_log(
        self,
        limit: int = 50,
        agent_id: str = "",
    ) -> list[TelephonyOperation]:
        """Get operation log entries.

        Args:
            limit: Maximum entries.
            agent_id: Filter by agent. Empty = all.

        Returns:
            List of TelephonyOperation entries (newest first).
        """
        with self._lock:
            log = list(reversed(self._operation_log))
        if agent_id:
            log = [e for e in log if e.agent_id == agent_id]
        return log[:limit]

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return telephony integration status summary."""
        return {
            "twilio_configured": bool(self._twilio_sid and self._twilio_token),
            "elevenlabs_configured": bool(self._elevenlabs_key),
            "from_number": self._from_number,
            "total_calls": len(self._call_log),
            "total_sms": len(self._sms_log),
            "total_operations": len(self._operation_log),
        }

    # -------------------------------------------------------------------
    # Internal HTTP
    # -------------------------------------------------------------------

    def _twilio_get(self, url: str) -> dict[str, Any] | None:
        """GET request to Twilio API with Basic Auth."""
        req = urllib.request.Request(url)
        credentials = base64.b64encode(
            f"{self._twilio_sid}:{self._twilio_token}".encode()
        ).decode()
        req.add_header("Authorization", f"Basic {credentials}")

        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def _twilio_post(self, url: str, data: dict[str, str]) -> dict[str, Any] | None:
        """POST request to Twilio API with form-encoded data."""
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        credentials = base64.b64encode(
            f"{self._twilio_sid}:{self._twilio_token}".encode()
        ).decode()
        req.add_header("Authorization", f"Basic {credentials}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def _log(
        self,
        operation: str,
        agent_id: str,
        details: str = "",
    ) -> None:
        """Log a telephony operation."""
        entry = TelephonyOperation(
            timestamp=time.time(),
            operation=operation,
            agent_id=agent_id,
            details=details,
        )
        with self._lock:
            self._operation_log.append(entry)
