"""
email_integration.py — Email Integration

Provides email sending and inbox reading for agents via SMTP/IMAP.
No external SDK dependency — uses Python's stdlib email/smtplib/imaplib.

Architecture Reference: R3_RealWorld_Capabilities.md
Phase: B — Capabilities

Features:
  - Send emails via SMTP (TLS)
  - Read inbox via IMAP
  - Search emails by subject, sender, date
  - Draft management (compose without sending)
  - Safety classification (read=safe, send=approval_required)
  - Operation logging for audit trail

Design:
  - Pure stdlib (smtplib, imaplib, email)
  - Approval-required for sending emails
  - Read-only operations always allowed
  - Thread-safe
"""

from __future__ import annotations

import email
import email.mime.multipart
import email.mime.text
import imaplib
import smtplib
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SMTP_PORT = 587
DEFAULT_IMAP_PORT = 993
DEFAULT_FETCH_LIMIT = 20

# Common provider configurations
PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "gmail": {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
    },
    "outlook": {
        "smtp_host": "smtp-mail.outlook.com",
        "smtp_port": 587,
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
    },
    "yahoo": {
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 587,
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
    },
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EmailSafety(Enum):
    """Safety classification for email operations."""

    SAFE = "safe"                        # Read operations
    APPROVAL_REQUIRED = "approval_required"  # Send operations


class EmailConnectionStatus(Enum):
    """Email connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    AUTH_FAILED = "auth_failed"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class EmailMessage:
    """Represents an email message."""

    message_id: str = ""
    subject: str = ""
    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    body: str = ""
    date: str = ""
    is_read: bool = False
    has_attachments: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "subject": self.subject,
            "sender": self.sender,
            "recipients": self.recipients,
            "body": self.body,
            "date": self.date,
            "is_read": self.is_read,
            "has_attachments": self.has_attachments,
        }


@dataclass
class EmailDraft:
    """An email draft composed but not yet sent."""

    to: list[str]
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: str = ""
    agent_id: str = ""
    created_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "to": self.to,
            "subject": self.subject,
            "body": self.body,
            "cc": self.cc,
            "bcc": self.bcc,
            "reply_to": self.reply_to,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
        }


@dataclass
class EmailResult:
    """Result of an email operation."""

    success: bool
    safety: EmailSafety
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
class EmailOperation:
    """Audit log entry for email operations."""

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
# Email Client
# ---------------------------------------------------------------------------

class EmailClient:
    """Email integration client.

    Provides safe access to email via SMTP/IMAP with
    safety classification and audit logging.
    """

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = DEFAULT_SMTP_PORT,
        imap_host: str = "",
        imap_port: int = DEFAULT_IMAP_PORT,
        username: str = "",
        password: str = "",
        provider: str = "",
    ) -> None:
        """Initialize email client.

        Args:
            smtp_host: SMTP server hostname.
            smtp_port: SMTP server port.
            imap_host: IMAP server hostname.
            imap_port: IMAP server port.
            username: Email account username.
            password: Email account password or app password.
            provider: Provider shortcut (gmail, outlook, yahoo).
        """
        if provider and provider in PROVIDER_CONFIGS:
            config = PROVIDER_CONFIGS[provider]
            self._smtp_host = smtp_host or config["smtp_host"]
            self._smtp_port = smtp_port if smtp_port != DEFAULT_SMTP_PORT else config["smtp_port"]
            self._imap_host = imap_host or config["imap_host"]
            self._imap_port = imap_port if imap_port != DEFAULT_IMAP_PORT else config["imap_port"]
        else:
            self._smtp_host = smtp_host
            self._smtp_port = smtp_port
            self._imap_host = imap_host
            self._imap_port = imap_port

        self._username = username
        self._password = password
        self._drafts: list[EmailDraft] = []
        self._operation_log: list[EmailOperation] = []
        self._lock = threading.Lock()

    # -------------------------------------------------------------------
    # Connection Check
    # -------------------------------------------------------------------

    def check_smtp_connection(self) -> EmailConnectionStatus:
        """Check SMTP connection.

        Returns:
            Connection status.
        """
        if not self._smtp_host or not self._username:
            return EmailConnectionStatus.DISCONNECTED

        try:
            with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(self._username, self._password)
            return EmailConnectionStatus.CONNECTED
        except smtplib.SMTPAuthenticationError:
            return EmailConnectionStatus.AUTH_FAILED
        except Exception:
            return EmailConnectionStatus.DISCONNECTED

    def check_imap_connection(self) -> EmailConnectionStatus:
        """Check IMAP connection.

        Returns:
            Connection status.
        """
        if not self._imap_host or not self._username:
            return EmailConnectionStatus.DISCONNECTED

        try:
            conn = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
            conn.login(self._username, self._password)
            conn.logout()
            return EmailConnectionStatus.CONNECTED
        except imaplib.IMAP4.error:
            return EmailConnectionStatus.AUTH_FAILED
        except Exception:
            return EmailConnectionStatus.DISCONNECTED

    # -------------------------------------------------------------------
    # Read Operations (Always Safe)
    # -------------------------------------------------------------------

    def fetch_inbox(
        self,
        limit: int = DEFAULT_FETCH_LIMIT,
        folder: str = "INBOX",
        agent_id: str = "",
    ) -> EmailResult:
        """Fetch recent emails from inbox.

        Args:
            limit: Maximum emails to fetch.
            folder: IMAP folder name.
            agent_id: Agent making the call.

        Returns:
            EmailResult with list of EmailMessage.
        """
        if not self._imap_host or not self._username:
            return EmailResult(
                success=False, safety=EmailSafety.SAFE,
                error="IMAP not configured",
            )

        try:
            conn = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
            conn.login(self._username, self._password)
            conn.select(folder, readonly=True)

            _, data = conn.search(None, "ALL")
            msg_ids = data[0].split() if data[0] else []

            # Get most recent
            recent_ids = msg_ids[-limit:] if len(msg_ids) > limit else msg_ids
            recent_ids.reverse()  # Newest first

            messages = []
            for msg_id in recent_ids:
                _, msg_data = conn.fetch(msg_id, "(RFC822)")
                if msg_data and msg_data[0]:
                    raw = msg_data[0]
                    if isinstance(raw, tuple) and len(raw) > 1:
                        msg = email.message_from_bytes(raw[1])
                        messages.append(self._parse_email(msg))

            conn.logout()

            self._log("fetch_inbox", agent_id, f"Fetched {len(messages)} emails")
            return EmailResult(
                success=True, safety=EmailSafety.SAFE,
                data=[m.to_dict() for m in messages],
            )

        except Exception as e:
            return EmailResult(
                success=False, safety=EmailSafety.SAFE,
                error=str(e),
            )

    def search_emails(
        self,
        query: str = "",
        sender: str = "",
        subject: str = "",
        folder: str = "INBOX",
        limit: int = DEFAULT_FETCH_LIMIT,
        agent_id: str = "",
    ) -> EmailResult:
        """Search emails by criteria.

        Args:
            query: General search text.
            sender: Filter by sender address.
            subject: Filter by subject line.
            folder: IMAP folder.
            limit: Maximum results.
            agent_id: Agent making the call.

        Returns:
            EmailResult with matching EmailMessage list.
        """
        if not self._imap_host or not self._username:
            return EmailResult(
                success=False, safety=EmailSafety.SAFE,
                error="IMAP not configured",
            )

        try:
            conn = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
            conn.login(self._username, self._password)
            conn.select(folder, readonly=True)

            # Build IMAP search criteria
            criteria = []
            if sender:
                criteria.append(f'FROM "{sender}"')
            if subject:
                criteria.append(f'SUBJECT "{subject}"')
            if query:
                criteria.append(f'TEXT "{query}"')

            search_str = " ".join(criteria) if criteria else "ALL"
            _, data = conn.search(None, search_str)
            msg_ids = data[0].split() if data[0] else []

            recent_ids = msg_ids[-limit:] if len(msg_ids) > limit else msg_ids
            recent_ids.reverse()

            messages = []
            for msg_id in recent_ids:
                _, msg_data = conn.fetch(msg_id, "(RFC822)")
                if msg_data and msg_data[0]:
                    raw = msg_data[0]
                    if isinstance(raw, tuple) and len(raw) > 1:
                        msg = email.message_from_bytes(raw[1])
                        messages.append(self._parse_email(msg))

            conn.logout()

            self._log("search_emails", agent_id,
                      f"Found {len(messages)} matches")
            return EmailResult(
                success=True, safety=EmailSafety.SAFE,
                data=[m.to_dict() for m in messages],
            )

        except Exception as e:
            return EmailResult(
                success=False, safety=EmailSafety.SAFE,
                error=str(e),
            )

    # -------------------------------------------------------------------
    # Send Operations (Approval Required)
    # -------------------------------------------------------------------

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        agent_id: str = "",
        skip_safety: bool = False,
    ) -> EmailResult:
        """Send an email.

        Args:
            to: Recipient addresses.
            subject: Email subject.
            body: Email body text.
            cc: CC recipients.
            bcc: BCC recipients.
            agent_id: Agent making the call.
            skip_safety: Skip safety check (for pre-approved sends).

        Returns:
            EmailResult. Blocked if not pre-approved.
        """
        if not skip_safety:
            return EmailResult(
                success=False,
                safety=EmailSafety.APPROVAL_REQUIRED,
                error="Email sending requires human approval. Use approval_gate to request.",
            )

        if not self._smtp_host or not self._username:
            return EmailResult(
                success=False, safety=EmailSafety.SAFE,
                error="SMTP not configured",
            )

        try:
            msg = email.mime.multipart.MIMEMultipart()
            msg["From"] = self._username
            msg["To"] = ", ".join(to)
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = ", ".join(cc)

            msg.attach(email.mime.text.MIMEText(body, "plain"))

            all_recipients = list(to) + (cc or []) + (bcc or [])

            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self._username, self._password)
                server.sendmail(self._username, all_recipients, msg.as_string())

            self._log("send_email", agent_id,
                      f"To: {', '.join(to)}, Subject: {subject}")
            return EmailResult(
                success=True, safety=EmailSafety.APPROVAL_REQUIRED,
                data={"recipients": len(all_recipients), "subject": subject},
            )

        except Exception as e:
            return EmailResult(
                success=False, safety=EmailSafety.APPROVAL_REQUIRED,
                error=str(e),
            )

    # -------------------------------------------------------------------
    # Draft Management
    # -------------------------------------------------------------------

    def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        agent_id: str = "",
    ) -> EmailResult:
        """Create an email draft (does not send).

        Args:
            to: Recipient addresses.
            subject: Email subject.
            body: Email body text.
            cc: CC recipients.
            bcc: BCC recipients.
            agent_id: Agent making the call.

        Returns:
            EmailResult with draft data.
        """
        draft = EmailDraft(
            to=to,
            subject=subject,
            body=body,
            cc=cc or [],
            bcc=bcc or [],
            agent_id=agent_id,
        )

        with self._lock:
            self._drafts.append(draft)
            draft_index = len(self._drafts) - 1

        self._log("create_draft", agent_id,
                  f"Draft #{draft_index}: {subject}")
        return EmailResult(
            success=True, safety=EmailSafety.SAFE,
            data={"draft_index": draft_index, "draft": draft.to_dict()},
        )

    def list_drafts(self, agent_id: str = "") -> list[EmailDraft]:
        """List all drafts, optionally filtered by agent.

        Args:
            agent_id: Filter by agent. Empty = all.

        Returns:
            List of EmailDraft objects.
        """
        with self._lock:
            drafts = list(self._drafts)
        if agent_id:
            drafts = [d for d in drafts if d.agent_id == agent_id]
        return drafts

    def delete_draft(self, index: int) -> bool:
        """Delete a draft by index.

        Args:
            index: Draft index.

        Returns:
            True if deleted.
        """
        with self._lock:
            if 0 <= index < len(self._drafts):
                self._drafts.pop(index)
                return True
        return False

    # -------------------------------------------------------------------
    # Operation Log
    # -------------------------------------------------------------------

    def get_operation_log(
        self,
        limit: int = 50,
        agent_id: str = "",
    ) -> list[EmailOperation]:
        """Get operation log entries.

        Args:
            limit: Maximum entries.
            agent_id: Filter by agent. Empty = all.

        Returns:
            List of EmailOperation entries (newest first).
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
        """Return email integration status summary."""
        return {
            "smtp_host": self._smtp_host,
            "imap_host": self._imap_host,
            "has_credentials": bool(self._username and self._password),
            "total_drafts": len(self._drafts),
            "total_operations": len(self._operation_log),
        }

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    @staticmethod
    def _parse_email(msg: email.message.Message) -> EmailMessage:
        """Parse an email.message.Message into EmailMessage."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")

        return EmailMessage(
            message_id=msg.get("Message-ID", ""),
            subject=msg.get("Subject", ""),
            sender=msg.get("From", ""),
            recipients=[r.strip() for r in (msg.get("To", "")).split(",") if r.strip()],
            body=body,
            date=msg.get("Date", ""),
        )

    def _log(
        self,
        operation: str,
        agent_id: str,
        details: str = "",
    ) -> None:
        """Log an email operation."""
        entry = EmailOperation(
            timestamp=time.time(),
            operation=operation,
            agent_id=agent_id,
            details=details,
        )
        with self._lock:
            self._operation_log.append(entry)
