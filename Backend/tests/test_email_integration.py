"""
Tests for email_integration.py — Email Integration

Tests cover:
  - EmailSafety and EmailConnectionStatus enums
  - EmailMessage, EmailDraft, EmailResult, EmailOperation dataclasses
  - EmailClient initialization (direct and provider configs)
  - Connection checking (SMTP, IMAP)
  - Inbox fetching (mocked IMAP)
  - Email search (mocked IMAP)
  - Send email (safety gate, mocked SMTP)
  - Draft management (create, list, delete)
  - Operation logging
  - Status reporting
  - Email parsing
  - Thread safety
"""

import email.mime.text
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email_integration import (
    PROVIDER_CONFIGS,
    EmailClient,
    EmailConnectionStatus,
    EmailDraft,
    EmailMessage,
    EmailOperation,
    EmailResult,
    EmailSafety,
)


# ---------------------------------------------------------------------------
# Enum Tests
# ---------------------------------------------------------------------------

class TestEmailSafety(unittest.TestCase):
    """Test EmailSafety enum."""

    def test_all_values(self):
        expected = {"safe", "approval_required"}
        actual = {s.value for s in EmailSafety}
        self.assertEqual(actual, expected)


class TestEmailConnectionStatus(unittest.TestCase):
    """Test EmailConnectionStatus enum."""

    def test_all_values(self):
        expected = {"connected", "disconnected", "auth_failed", "unknown"}
        actual = {s.value for s in EmailConnectionStatus}
        self.assertEqual(actual, expected)


# ---------------------------------------------------------------------------
# Dataclass Tests
# ---------------------------------------------------------------------------

class TestEmailMessage(unittest.TestCase):
    """Test EmailMessage dataclass."""

    def test_to_dict(self):
        m = EmailMessage(
            message_id="<abc@test.com>",
            subject="Test",
            sender="alice@test.com",
            recipients=["bob@test.com"],
            body="Hello",
            date="Mon, 22 Feb 2026 10:00:00 +0000",
        )
        d = m.to_dict()
        self.assertEqual(d["subject"], "Test")
        self.assertEqual(d["sender"], "alice@test.com")
        self.assertIn("bob@test.com", d["recipients"])

    def test_defaults(self):
        m = EmailMessage()
        self.assertEqual(m.message_id, "")
        self.assertEqual(m.subject, "")
        self.assertFalse(m.is_read)
        self.assertFalse(m.has_attachments)


class TestEmailDraft(unittest.TestCase):
    """Test EmailDraft dataclass."""

    def test_auto_timestamp(self):
        before = time.time()
        d = EmailDraft(to=["a@b.com"], subject="X", body="Y")
        after = time.time()
        self.assertGreaterEqual(d.created_at, before)
        self.assertLessEqual(d.created_at, after)

    def test_to_dict(self):
        d = EmailDraft(
            to=["a@b.com"], subject="Test", body="Body",
            cc=["c@d.com"], agent_id="agent1",
        )
        dd = d.to_dict()
        self.assertEqual(dd["subject"], "Test")
        self.assertEqual(dd["to"], ["a@b.com"])
        self.assertEqual(dd["cc"], ["c@d.com"])

    def test_defaults(self):
        d = EmailDraft(to=["a@b.com"], subject="X", body="Y")
        self.assertEqual(d.cc, [])
        self.assertEqual(d.bcc, [])
        self.assertEqual(d.reply_to, "")


class TestEmailResult(unittest.TestCase):
    """Test EmailResult dataclass."""

    def test_success(self):
        r = EmailResult(success=True, safety=EmailSafety.SAFE, data={"count": 5})
        d = r.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["safety"], "safe")

    def test_error(self):
        r = EmailResult(
            success=False, safety=EmailSafety.APPROVAL_REQUIRED,
            error="Not approved",
        )
        d = r.to_dict()
        self.assertFalse(d["success"])
        self.assertEqual(d["error"], "Not approved")


class TestEmailOperation(unittest.TestCase):
    """Test EmailOperation dataclass."""

    def test_to_dict(self):
        o = EmailOperation(
            timestamp=12345.0, operation="send_email",
            agent_id="a1", details="Sent to bob",
        )
        d = o.to_dict()
        self.assertEqual(d["operation"], "send_email")
        self.assertEqual(d["agent_id"], "a1")


# ---------------------------------------------------------------------------
# Client Init Tests
# ---------------------------------------------------------------------------

class TestClientInit(unittest.TestCase):
    """Test EmailClient initialization."""

    def test_direct_config(self):
        client = EmailClient(
            smtp_host="smtp.test.com", smtp_port=465,
            imap_host="imap.test.com", imap_port=993,
            username="user@test.com", password="pass",
        )
        self.assertEqual(client._smtp_host, "smtp.test.com")
        self.assertEqual(client._smtp_port, 465)
        self.assertEqual(client._imap_host, "imap.test.com")

    def test_provider_config_gmail(self):
        client = EmailClient(
            provider="gmail",
            username="user@gmail.com", password="pass",
        )
        self.assertEqual(client._smtp_host, "smtp.gmail.com")
        self.assertEqual(client._imap_host, "imap.gmail.com")

    def test_provider_config_outlook(self):
        client = EmailClient(provider="outlook", username="u", password="p")
        self.assertEqual(client._smtp_host, "smtp-mail.outlook.com")

    def test_provider_config_yahoo(self):
        client = EmailClient(provider="yahoo", username="u", password="p")
        self.assertEqual(client._smtp_host, "smtp.mail.yahoo.com")

    def test_unknown_provider(self):
        client = EmailClient(provider="unknown", smtp_host="custom.com")
        self.assertEqual(client._smtp_host, "custom.com")

    def test_provider_override(self):
        client = EmailClient(
            provider="gmail",
            smtp_host="custom-smtp.com",
            username="u", password="p",
        )
        # Direct config overrides provider
        self.assertEqual(client._smtp_host, "custom-smtp.com")

    def test_empty_config(self):
        client = EmailClient()
        self.assertEqual(client._smtp_host, "")
        self.assertEqual(client._username, "")

    def test_provider_configs_nonempty(self):
        self.assertIn("gmail", PROVIDER_CONFIGS)
        self.assertIn("outlook", PROVIDER_CONFIGS)
        self.assertIn("yahoo", PROVIDER_CONFIGS)


# ---------------------------------------------------------------------------
# Connection Tests
# ---------------------------------------------------------------------------

class TestConnectionChecks(unittest.TestCase):
    """Test connection checking."""

    def test_smtp_no_config(self):
        client = EmailClient()
        status = client.check_smtp_connection()
        self.assertEqual(status, EmailConnectionStatus.DISCONNECTED)

    def test_imap_no_config(self):
        client = EmailClient()
        status = client.check_imap_connection()
        self.assertEqual(status, EmailConnectionStatus.DISCONNECTED)

    @patch("email_integration.smtplib.SMTP")
    def test_smtp_connected(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        client = EmailClient(
            smtp_host="smtp.test.com",
            username="u@test.com", password="p",
        )
        status = client.check_smtp_connection()
        self.assertEqual(status, EmailConnectionStatus.CONNECTED)

    @patch("email_integration.smtplib.SMTP")
    def test_smtp_auth_failed(self, mock_smtp):
        import smtplib
        mock_smtp.return_value.__enter__ = MagicMock()
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        mock_smtp.return_value.__enter__.return_value.login.side_effect = \
            smtplib.SMTPAuthenticationError(535, b"Auth failed")

        client = EmailClient(
            smtp_host="smtp.test.com",
            username="u@test.com", password="bad",
        )
        status = client.check_smtp_connection()
        self.assertEqual(status, EmailConnectionStatus.AUTH_FAILED)

    @patch("email_integration.smtplib.SMTP")
    def test_smtp_connection_error(self, mock_smtp):
        mock_smtp.side_effect = ConnectionError("refused")
        client = EmailClient(
            smtp_host="smtp.test.com",
            username="u@test.com", password="p",
        )
        status = client.check_smtp_connection()
        self.assertEqual(status, EmailConnectionStatus.DISCONNECTED)

    @patch("email_integration.imaplib.IMAP4_SSL")
    def test_imap_connected(self, mock_imap):
        mock_conn = MagicMock()
        mock_imap.return_value = mock_conn

        client = EmailClient(
            imap_host="imap.test.com",
            username="u@test.com", password="p",
        )
        status = client.check_imap_connection()
        self.assertEqual(status, EmailConnectionStatus.CONNECTED)
        mock_conn.login.assert_called_once()

    @patch("email_integration.imaplib.IMAP4_SSL")
    def test_imap_auth_failed(self, mock_imap):
        import imaplib
        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error("Auth failed")
        mock_imap.return_value = mock_conn

        client = EmailClient(
            imap_host="imap.test.com",
            username="u@test.com", password="bad",
        )
        status = client.check_imap_connection()
        self.assertEqual(status, EmailConnectionStatus.AUTH_FAILED)


# ---------------------------------------------------------------------------
# Send Email Tests
# ---------------------------------------------------------------------------

class TestSendEmail(unittest.TestCase):
    """Test email sending."""

    def setUp(self):
        self.client = EmailClient(
            smtp_host="smtp.test.com",
            username="sender@test.com", password="pass",
        )

    def test_blocked_without_approval(self):
        result = self.client.send_email(
            to=["bob@test.com"], subject="Hi", body="Hello",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.safety, EmailSafety.APPROVAL_REQUIRED)
        self.assertIn("approval", result.error.lower())

    @patch("email_integration.smtplib.SMTP")
    def test_send_with_skip_safety(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        result = self.client.send_email(
            to=["bob@test.com"], subject="Hi", body="Hello",
            skip_safety=True, agent_id="a1",
        )
        self.assertTrue(result.success)
        mock_server.sendmail.assert_called_once()

    @patch("email_integration.smtplib.SMTP")
    def test_send_with_cc_bcc(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        result = self.client.send_email(
            to=["bob@test.com"], subject="Hi", body="Hello",
            cc=["cc@test.com"], bcc=["bcc@test.com"],
            skip_safety=True,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["recipients"], 3)

    def test_send_no_smtp_config(self):
        client = EmailClient()
        result = client.send_email(
            to=["bob@test.com"], subject="Hi", body="Hello",
            skip_safety=True,
        )
        self.assertFalse(result.success)
        self.assertIn("SMTP not configured", result.error)

    @patch("email_integration.smtplib.SMTP")
    def test_send_error(self, mock_smtp):
        mock_smtp.side_effect = ConnectionError("refused")
        result = self.client.send_email(
            to=["bob@test.com"], subject="Hi", body="Hello",
            skip_safety=True,
        )
        self.assertFalse(result.success)
        self.assertIn("refused", result.error)


# ---------------------------------------------------------------------------
# Fetch Inbox Tests
# ---------------------------------------------------------------------------

class TestFetchInbox(unittest.TestCase):
    """Test inbox fetching."""

    def test_no_imap_config(self):
        client = EmailClient()
        result = client.fetch_inbox()
        self.assertFalse(result.success)
        self.assertIn("IMAP not configured", result.error)

    @patch("email_integration.imaplib.IMAP4_SSL")
    def test_fetch_success(self, mock_imap):
        # Build a simple email message
        msg = email.mime.text.MIMEText("Hello World")
        msg["Subject"] = "Test Subject"
        msg["From"] = "alice@test.com"
        msg["To"] = "bob@test.com"
        msg["Message-ID"] = "<123@test.com>"
        msg["Date"] = "Mon, 22 Feb 2026 10:00:00 +0000"
        raw_bytes = msg.as_bytes()

        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b"1 2"])
        mock_conn.fetch.return_value = ("OK", [(b"1", raw_bytes)])
        mock_imap.return_value = mock_conn

        client = EmailClient(
            imap_host="imap.test.com",
            username="u@test.com", password="p",
        )
        result = client.fetch_inbox(limit=10, agent_id="a1")
        self.assertTrue(result.success)
        self.assertEqual(result.safety, EmailSafety.SAFE)
        self.assertIsInstance(result.data, list)

    @patch("email_integration.imaplib.IMAP4_SSL")
    def test_fetch_empty(self, mock_imap):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        mock_imap.return_value = mock_conn

        client = EmailClient(
            imap_host="imap.test.com",
            username="u@test.com", password="p",
        )
        result = client.fetch_inbox()
        self.assertTrue(result.success)
        self.assertEqual(result.data, [])

    @patch("email_integration.imaplib.IMAP4_SSL")
    def test_fetch_error(self, mock_imap):
        mock_imap.side_effect = ConnectionError("refused")
        client = EmailClient(
            imap_host="imap.test.com",
            username="u@test.com", password="p",
        )
        result = client.fetch_inbox()
        self.assertFalse(result.success)


# ---------------------------------------------------------------------------
# Search Email Tests
# ---------------------------------------------------------------------------

class TestSearchEmails(unittest.TestCase):
    """Test email search."""

    def test_no_imap_config(self):
        client = EmailClient()
        result = client.search_emails(query="test")
        self.assertFalse(result.success)

    @patch("email_integration.imaplib.IMAP4_SSL")
    def test_search_success(self, mock_imap):
        msg = email.mime.text.MIMEText("Content")
        msg["Subject"] = "Test"
        msg["From"] = "alice@test.com"
        msg["To"] = "bob@test.com"

        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b"1"])
        mock_conn.fetch.return_value = ("OK", [(b"1", msg.as_bytes())])
        mock_imap.return_value = mock_conn

        client = EmailClient(
            imap_host="imap.test.com",
            username="u@test.com", password="p",
        )
        result = client.search_emails(sender="alice@test.com")
        self.assertTrue(result.success)

    @patch("email_integration.imaplib.IMAP4_SSL")
    def test_search_with_subject(self, mock_imap):
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        mock_imap.return_value = mock_conn

        client = EmailClient(
            imap_host="imap.test.com",
            username="u@test.com", password="p",
        )
        result = client.search_emails(subject="Invoice")
        self.assertTrue(result.success)
        # Check that search was called with SUBJECT criteria
        mock_conn.search.assert_called_once()


# ---------------------------------------------------------------------------
# Draft Tests
# ---------------------------------------------------------------------------

class TestDraftManagement(unittest.TestCase):
    """Test draft management."""

    def setUp(self):
        self.client = EmailClient()

    def test_create_draft(self):
        result = self.client.create_draft(
            to=["bob@test.com"], subject="Test", body="Hello",
            agent_id="a1",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.safety, EmailSafety.SAFE)
        self.assertEqual(result.data["draft_index"], 0)

    def test_list_drafts(self):
        self.client.create_draft(to=["a@b.com"], subject="A", body="X", agent_id="a1")
        self.client.create_draft(to=["c@d.com"], subject="B", body="Y", agent_id="a2")

        all_drafts = self.client.list_drafts()
        self.assertEqual(len(all_drafts), 2)

        a1_drafts = self.client.list_drafts(agent_id="a1")
        self.assertEqual(len(a1_drafts), 1)
        self.assertEqual(a1_drafts[0].subject, "A")

    def test_delete_draft(self):
        self.client.create_draft(to=["a@b.com"], subject="A", body="X")
        self.client.create_draft(to=["c@d.com"], subject="B", body="Y")

        self.assertTrue(self.client.delete_draft(0))
        self.assertEqual(len(self.client.list_drafts()), 1)
        self.assertEqual(self.client.list_drafts()[0].subject, "B")

    def test_delete_invalid_index(self):
        self.assertFalse(self.client.delete_draft(99))
        self.assertFalse(self.client.delete_draft(-1))

    def test_draft_with_cc_bcc(self):
        result = self.client.create_draft(
            to=["a@b.com"], subject="X", body="Y",
            cc=["cc@b.com"], bcc=["bcc@b.com"],
        )
        draft = self.client.list_drafts()[0]
        self.assertEqual(draft.cc, ["cc@b.com"])
        self.assertEqual(draft.bcc, ["bcc@b.com"])


# ---------------------------------------------------------------------------
# Operation Log Tests
# ---------------------------------------------------------------------------

class TestOperationLog(unittest.TestCase):
    """Test operation logging."""

    def setUp(self):
        self.client = EmailClient()

    def test_draft_logged(self):
        self.client.create_draft(to=["a@b.com"], subject="X", body="Y", agent_id="a1")
        log = self.client.get_operation_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].operation, "create_draft")

    def test_log_filter_by_agent(self):
        self.client.create_draft(to=["a@b.com"], subject="A", body="X", agent_id="a1")
        self.client.create_draft(to=["a@b.com"], subject="B", body="Y", agent_id="a2")
        self.client.create_draft(to=["a@b.com"], subject="C", body="Z", agent_id="a1")

        log = self.client.get_operation_log(agent_id="a1")
        self.assertEqual(len(log), 2)

    def test_log_limit(self):
        for i in range(10):
            self.client.create_draft(to=["a@b.com"], subject=f"S{i}", body="X")
        log = self.client.get_operation_log(limit=3)
        self.assertEqual(len(log), 3)

    def test_log_newest_first(self):
        self.client.create_draft(to=["a@b.com"], subject="First", body="X", agent_id="a1")
        self.client.create_draft(to=["a@b.com"], subject="Second", body="Y", agent_id="a2")
        log = self.client.get_operation_log()
        self.assertEqual(log[0].agent_id, "a2")

    def test_log_empty(self):
        log = self.client.get_operation_log()
        self.assertEqual(log, [])


# ---------------------------------------------------------------------------
# Status Tests
# ---------------------------------------------------------------------------

class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_unconfigured(self):
        client = EmailClient()
        s = client.status()
        self.assertEqual(s["smtp_host"], "")
        self.assertFalse(s["has_credentials"])
        self.assertEqual(s["total_drafts"], 0)
        self.assertEqual(s["total_operations"], 0)

    def test_configured(self):
        client = EmailClient(
            smtp_host="smtp.test.com", imap_host="imap.test.com",
            username="u@test.com", password="pass",
        )
        s = client.status()
        self.assertEqual(s["smtp_host"], "smtp.test.com")
        self.assertTrue(s["has_credentials"])


# ---------------------------------------------------------------------------
# Email Parsing Tests
# ---------------------------------------------------------------------------

class TestEmailParsing(unittest.TestCase):
    """Test internal email parsing."""

    def test_parse_simple(self):
        msg = email.mime.text.MIMEText("Hello World")
        msg["Subject"] = "Test"
        msg["From"] = "alice@test.com"
        msg["To"] = "bob@test.com"
        msg["Message-ID"] = "<123@test.com>"

        parsed = EmailClient._parse_email(msg)
        self.assertEqual(parsed.subject, "Test")
        self.assertEqual(parsed.sender, "alice@test.com")
        self.assertEqual(parsed.body, "Hello World")
        self.assertIn("bob@test.com", parsed.recipients)

    def test_parse_empty(self):
        from email.message import Message
        msg = Message()
        parsed = EmailClient._parse_email(msg)
        self.assertEqual(parsed.subject, "")
        self.assertEqual(parsed.sender, "")
        self.assertEqual(parsed.body, "")

    def test_parse_multiple_recipients(self):
        msg = email.mime.text.MIMEText("Body")
        msg["To"] = "a@test.com, b@test.com, c@test.com"
        parsed = EmailClient._parse_email(msg)
        self.assertEqual(len(parsed.recipients), 3)


# ---------------------------------------------------------------------------
# Thread Safety Tests
# ---------------------------------------------------------------------------

class TestThreadSafety(unittest.TestCase):
    """Test thread safety."""

    def test_concurrent_drafts(self):
        client = EmailClient()
        errors = []

        def drafter(agent_id):
            try:
                for i in range(20):
                    client.create_draft(
                        to=["a@b.com"], subject=f"S{i}",
                        body="X", agent_id=agent_id,
                    )
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=drafter, args=(f"a{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(client.list_drafts()), 100)

    def test_concurrent_log_access(self):
        client = EmailClient()
        errors = []

        # Populate some log
        for i in range(50):
            client.create_draft(to=["a@b.com"], subject=f"S{i}", body="X")

        def reader():
            try:
                for _ in range(20):
                    client.get_operation_log(limit=10)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
