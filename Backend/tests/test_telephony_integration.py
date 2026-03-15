"""
Tests for telephony_integration.py — Telephony Integration

Tests cover:
  - TelephonySafety, CallStatus, ConnectionStatus enums
  - CallRecord, SMSRecord, TelephonyResult, TelephonyOperation dataclasses
  - TelephonyClient initialization
  - Connection checking (Twilio, ElevenLabs)
  - Outbound calls (safety gate, mocked API)
  - SMS sending (safety gate, mocked API)
  - Voice synthesis (mocked ElevenLabs)
  - Call/SMS/operation logging
  - Status reporting
  - Thread safety
"""

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telephony_integration import (
    CallRecord,
    CallStatus,
    ConnectionStatus,
    SMSRecord,
    TelephonyClient,
    TelephonyOperation,
    TelephonyResult,
    TelephonySafety,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Fake urllib response for mocking urlopen."""

    def __init__(self, data, status=200):
        self._data = json.dumps(data).encode() if isinstance(data, dict) else data
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Enum Tests
# ---------------------------------------------------------------------------

class TestTelephonySafety(unittest.TestCase):
    """Test TelephonySafety enum."""

    def test_all_values(self):
        self.assertEqual(TelephonySafety.APPROVAL_REQUIRED.value, "approval_required")


class TestCallStatus(unittest.TestCase):
    """Test CallStatus enum."""

    def test_all_values(self):
        expected = {
            "queued", "ringing", "in-progress", "completed",
            "failed", "busy", "no-answer", "canceled", "unknown",
        }
        actual = {s.value for s in CallStatus}
        self.assertEqual(actual, expected)


class TestConnectionStatus(unittest.TestCase):
    """Test ConnectionStatus enum."""

    def test_all_values(self):
        expected = {"connected", "disconnected", "auth_failed", "unknown"}
        actual = {s.value for s in ConnectionStatus}
        self.assertEqual(actual, expected)


# ---------------------------------------------------------------------------
# Dataclass Tests
# ---------------------------------------------------------------------------

class TestCallRecord(unittest.TestCase):
    """Test CallRecord dataclass."""

    def test_auto_timestamp(self):
        before = time.time()
        r = CallRecord(call_sid="CA123", to_number="+1234567890")
        after = time.time()
        self.assertGreaterEqual(r.timestamp, before)
        self.assertLessEqual(r.timestamp, after)

    def test_to_dict(self):
        r = CallRecord(
            call_sid="CA123", from_number="+1111",
            to_number="+2222", status="completed",
            direction="outbound", duration=30,
            agent_id="a1",
        )
        d = r.to_dict()
        self.assertEqual(d["call_sid"], "CA123")
        self.assertEqual(d["to_number"], "+2222")
        self.assertEqual(d["duration"], 30)

    def test_defaults(self):
        r = CallRecord()
        self.assertEqual(r.call_sid, "")
        self.assertEqual(r.status, "queued")
        self.assertEqual(r.direction, "outbound")


class TestSMSRecord(unittest.TestCase):
    """Test SMSRecord dataclass."""

    def test_auto_timestamp(self):
        r = SMSRecord(message_sid="SM123")
        self.assertGreater(r.timestamp, 0)

    def test_to_dict(self):
        r = SMSRecord(
            message_sid="SM123", from_number="+1111",
            to_number="+2222", body="Hello",
            status="sent", agent_id="a1",
        )
        d = r.to_dict()
        self.assertEqual(d["message_sid"], "SM123")
        self.assertEqual(d["body"], "Hello")


class TestTelephonyResult(unittest.TestCase):
    """Test TelephonyResult dataclass."""

    def test_success(self):
        r = TelephonyResult(
            success=True,
            safety=TelephonySafety.APPROVAL_REQUIRED,
            data={"sid": "CA123"},
        )
        d = r.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["safety"], "approval_required")

    def test_error(self):
        r = TelephonyResult(
            success=False,
            safety=TelephonySafety.APPROVAL_REQUIRED,
            error="Not approved",
        )
        d = r.to_dict()
        self.assertFalse(d["success"])


class TestTelephonyOperation(unittest.TestCase):
    """Test TelephonyOperation dataclass."""

    def test_to_dict(self):
        o = TelephonyOperation(
            timestamp=12345.0, operation="make_call",
            agent_id="a1", details="To: +1234",
        )
        d = o.to_dict()
        self.assertEqual(d["operation"], "make_call")


# ---------------------------------------------------------------------------
# Client Init Tests
# ---------------------------------------------------------------------------

class TestClientInit(unittest.TestCase):
    """Test TelephonyClient initialization."""

    def test_default_init(self):
        client = TelephonyClient()
        self.assertEqual(client._twilio_sid, "")
        self.assertEqual(client._elevenlabs_key, "")

    def test_full_init(self):
        client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="token123",
            twilio_from_number="+15551234567",
            elevenlabs_api_key="el_key",
            elevenlabs_voice_id="voice123",
        )
        self.assertEqual(client._twilio_sid, "AC123")
        self.assertEqual(client._from_number, "+15551234567")
        self.assertEqual(client._elevenlabs_key, "el_key")
        self.assertEqual(client._voice_id, "voice123")


# ---------------------------------------------------------------------------
# Connection Tests
# ---------------------------------------------------------------------------

class TestConnectionChecks(unittest.TestCase):
    """Test connection checking."""

    def test_twilio_no_config(self):
        client = TelephonyClient()
        status = client.check_twilio_connection()
        self.assertEqual(status, ConnectionStatus.DISCONNECTED)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_twilio_connected(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"sid": "AC123"})
        client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="token",
        )
        status = client.check_twilio_connection()
        self.assertEqual(status, ConnectionStatus.CONNECTED)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_twilio_auth_failed(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="Unauthorized", hdrs=None, fp=None,
        )
        client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="bad",
        )
        status = client.check_twilio_connection()
        self.assertEqual(status, ConnectionStatus.AUTH_FAILED)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_twilio_connection_error(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionError("refused")
        client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="token",
        )
        status = client.check_twilio_connection()
        self.assertEqual(status, ConnectionStatus.DISCONNECTED)

    def test_elevenlabs_no_config(self):
        client = TelephonyClient()
        status = client.check_elevenlabs_connection()
        self.assertEqual(status, ConnectionStatus.DISCONNECTED)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_elevenlabs_connected(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"subscription": {}})
        client = TelephonyClient(elevenlabs_api_key="el_key")
        status = client.check_elevenlabs_connection()
        self.assertEqual(status, ConnectionStatus.CONNECTED)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_elevenlabs_auth_failed(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="Unauthorized", hdrs=None, fp=None,
        )
        client = TelephonyClient(elevenlabs_api_key="bad_key")
        status = client.check_elevenlabs_connection()
        self.assertEqual(status, ConnectionStatus.AUTH_FAILED)


# ---------------------------------------------------------------------------
# Call Tests
# ---------------------------------------------------------------------------

class TestMakeCall(unittest.TestCase):
    """Test outbound calls."""

    def setUp(self):
        self.client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="token",
            twilio_from_number="+15551234567",
        )

    def test_blocked_without_approval(self):
        result = self.client.make_call(to_number="+15559999999")
        self.assertFalse(result.success)
        self.assertEqual(result.safety, TelephonySafety.APPROVAL_REQUIRED)
        self.assertIn("approval", result.error.lower())

    @patch("telephony_integration.urllib.request.urlopen")
    def test_call_with_skip_safety(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({
            "sid": "CA12345", "status": "queued",
        })
        result = self.client.make_call(
            to_number="+15559999999",
            message="Hello, this is a test call",
            agent_id="a1",
            skip_safety=True,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["call_sid"], "CA12345")

    @patch("telephony_integration.urllib.request.urlopen")
    def test_call_with_twiml(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({
            "sid": "CA12345", "status": "queued",
        })
        result = self.client.make_call(
            to_number="+15559999999",
            twiml="<Response><Say>Hello</Say></Response>",
            skip_safety=True,
        )
        self.assertTrue(result.success)

    def test_call_no_twilio_config(self):
        client = TelephonyClient()
        result = client.make_call(
            to_number="+15559999999", skip_safety=True,
        )
        self.assertFalse(result.success)
        self.assertIn("not configured", result.error)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_call_error(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionError("refused")
        result = self.client.make_call(
            to_number="+15559999999", skip_safety=True,
        )
        self.assertFalse(result.success)
        self.assertIn("refused", result.error)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_call_logged(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({
            "sid": "CA123", "status": "queued",
        })
        self.client.make_call(
            to_number="+15559999999", skip_safety=True, agent_id="a1",
        )
        log = self.client.get_call_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].call_sid, "CA123")


# ---------------------------------------------------------------------------
# Call Status Tests
# ---------------------------------------------------------------------------

class TestGetCallStatus(unittest.TestCase):
    """Test call status retrieval."""

    def test_no_config(self):
        client = TelephonyClient()
        result = client.get_call_status("CA123")
        self.assertFalse(result.success)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_get_status(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({
            "sid": "CA123", "status": "completed", "duration": "30",
        })
        client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="token",
        )
        result = client.get_call_status("CA123")
        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "completed")


# ---------------------------------------------------------------------------
# SMS Tests
# ---------------------------------------------------------------------------

class TestSendSMS(unittest.TestCase):
    """Test SMS sending."""

    def setUp(self):
        self.client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="token",
            twilio_from_number="+15551234567",
        )

    def test_blocked_without_approval(self):
        result = self.client.send_sms(
            to_number="+15559999999", body="Hello",
        )
        self.assertFalse(result.success)
        self.assertIn("approval", result.error.lower())

    @patch("telephony_integration.urllib.request.urlopen")
    def test_send_with_skip_safety(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({
            "sid": "SM12345", "status": "queued",
        })
        result = self.client.send_sms(
            to_number="+15559999999", body="Hello",
            agent_id="a1", skip_safety=True,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["message_sid"], "SM12345")

    def test_send_no_config(self):
        client = TelephonyClient()
        result = client.send_sms(
            to_number="+15559999999", body="Hello",
            skip_safety=True,
        )
        self.assertFalse(result.success)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_send_error(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionError("refused")
        result = self.client.send_sms(
            to_number="+15559999999", body="Hello",
            skip_safety=True,
        )
        self.assertFalse(result.success)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_sms_logged(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({
            "sid": "SM123", "status": "queued",
        })
        self.client.send_sms(
            to_number="+15559999999", body="Hello",
            skip_safety=True, agent_id="a1",
        )
        log = self.client.get_sms_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].body, "Hello")


# ---------------------------------------------------------------------------
# Voice Synthesis Tests
# ---------------------------------------------------------------------------

class TestVoiceSynthesis(unittest.TestCase):
    """Test ElevenLabs voice synthesis."""

    def test_no_config(self):
        client = TelephonyClient()
        result = client.synthesize_voice("Hello")
        self.assertFalse(result.success)
        self.assertIn("ElevenLabs not configured", result.error)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_synthesis_success(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(b"fake_audio_bytes")
        client = TelephonyClient(elevenlabs_api_key="el_key")
        result = client.synthesize_voice("Hello world", agent_id="a1")
        self.assertTrue(result.success)
        self.assertIn("audio_size", result.data)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_synthesis_custom_voice(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(b"audio")
        client = TelephonyClient(elevenlabs_api_key="el_key")
        result = client.synthesize_voice("Hi", voice_id="custom_voice")
        self.assertTrue(result.success)
        self.assertEqual(result.data["voice_id"], "custom_voice")

    @patch("telephony_integration.urllib.request.urlopen")
    def test_synthesis_error(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionError("refused")
        client = TelephonyClient(elevenlabs_api_key="el_key")
        result = client.synthesize_voice("Hello")
        self.assertFalse(result.success)


# ---------------------------------------------------------------------------
# Log Tests
# ---------------------------------------------------------------------------

class TestLogs(unittest.TestCase):
    """Test log functionality."""

    def setUp(self):
        self.client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="token",
            twilio_from_number="+15551234567",
        )

    @patch("telephony_integration.urllib.request.urlopen")
    def test_call_log_filter_by_agent(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"sid": "CA1", "status": "queued"})
        self.client.make_call("+1", skip_safety=True, agent_id="a1")
        self.client.make_call("+2", skip_safety=True, agent_id="a2")
        self.client.make_call("+3", skip_safety=True, agent_id="a1")

        log = self.client.get_call_log(agent_id="a1")
        self.assertEqual(len(log), 2)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_call_log_limit(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"sid": "CA1", "status": "queued"})
        for _ in range(10):
            self.client.make_call("+1", skip_safety=True)
        log = self.client.get_call_log(limit=3)
        self.assertEqual(len(log), 3)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_sms_log_filter(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"sid": "SM1", "status": "queued"})
        self.client.send_sms("+1", "A", skip_safety=True, agent_id="a1")
        self.client.send_sms("+2", "B", skip_safety=True, agent_id="a2")

        log = self.client.get_sms_log(agent_id="a1")
        self.assertEqual(len(log), 1)

    @patch("telephony_integration.urllib.request.urlopen")
    def test_operation_log(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"sid": "CA1", "status": "queued"})
        self.client.make_call("+1", skip_safety=True, agent_id="a1")
        self.client.send_sms("+1", "Hi", skip_safety=True, agent_id="a1")

        mock_urlopen.return_value = _FakeResponse(b"audio")
        # No elevenlabs key, so this will fail without going to log

        log = self.client.get_operation_log()
        self.assertEqual(len(log), 2)

    def test_empty_logs(self):
        self.assertEqual(self.client.get_call_log(), [])
        self.assertEqual(self.client.get_sms_log(), [])
        self.assertEqual(self.client.get_operation_log(), [])

    @patch("telephony_integration.urllib.request.urlopen")
    def test_call_log_newest_first(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"sid": "CA1", "status": "queued"})
        self.client.make_call("+1", skip_safety=True, agent_id="first")
        self.client.make_call("+2", skip_safety=True, agent_id="second")
        log = self.client.get_call_log()
        self.assertEqual(log[0].agent_id, "second")


# ---------------------------------------------------------------------------
# Status Tests
# ---------------------------------------------------------------------------

class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_unconfigured(self):
        client = TelephonyClient()
        s = client.status()
        self.assertFalse(s["twilio_configured"])
        self.assertFalse(s["elevenlabs_configured"])
        self.assertEqual(s["total_calls"], 0)
        self.assertEqual(s["total_sms"], 0)

    def test_configured(self):
        client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="token",
            twilio_from_number="+15551234567",
            elevenlabs_api_key="el_key",
        )
        s = client.status()
        self.assertTrue(s["twilio_configured"])
        self.assertTrue(s["elevenlabs_configured"])
        self.assertEqual(s["from_number"], "+15551234567")


# ---------------------------------------------------------------------------
# Thread Safety Tests
# ---------------------------------------------------------------------------

class TestThreadSafety(unittest.TestCase):
    """Test thread safety."""

    @patch("telephony_integration.urllib.request.urlopen")
    def test_concurrent_calls(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"sid": "CA1", "status": "queued"})
        client = TelephonyClient(
            twilio_account_sid="AC123",
            twilio_auth_token="token",
            twilio_from_number="+15551234567",
        )
        errors = []

        def caller(agent_id):
            try:
                for _ in range(20):
                    client.make_call("+1", skip_safety=True, agent_id=agent_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=caller, args=(f"a{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(client.get_call_log(limit=200)), 100)

    def test_concurrent_log_access(self):
        client = TelephonyClient()
        errors = []

        def reader():
            try:
                for _ in range(20):
                    client.get_call_log(limit=10)
                    client.get_sms_log(limit=10)
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
