"""
Tests for ha_integration.py — Home Assistant Integration

Tests cover:
  - ActionSafety and HAConnectionStatus enums
  - HAEntity dataclass (domain, friendly_name, to_dict)
  - HAAction dataclass (full_service, timestamp, to_dict)
  - HAActionResult dataclass
  - HAClient connection checking
  - Entity state queries (get_states, get_state, search_entities, get_domains)
  - Action safety classification
  - Service calls (safe, caution, approval-blocked)
  - Action logging
  - Status reporting
  - Internal HTTP methods (_api_get, _api_post, _parse_entity)
  - Thread safety
"""

import json
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ha_integration import (
    APPROVAL_DOMAINS,
    SAFE_DOMAINS,
    ActionSafety,
    HAAction,
    HAActionResult,
    HAClient,
    HAConnectionStatus,
    HAEntity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity_dict(
    entity_id: str = "light.living_room",
    state: str = "on",
    friendly_name: str = "Living Room Light",
    last_changed: str = "2026-02-22T10:00:00Z",
    last_updated: str = "2026-02-22T10:00:00Z",
) -> dict:
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": {"friendly_name": friendly_name, "brightness": 255},
        "last_changed": last_changed,
        "last_updated": last_updated,
    }


class _FakeResponse:
    """Fake urllib response for mocking urlopen."""

    def __init__(self, data, status=200):
        self._data = json.dumps(data).encode()
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

class TestActionSafety(unittest.TestCase):
    """Test ActionSafety enum."""

    def test_all_values(self):
        expected = {"safe", "caution", "approval_required"}
        actual = {s.value for s in ActionSafety}
        self.assertEqual(actual, expected)


class TestHAConnectionStatus(unittest.TestCase):
    """Test HAConnectionStatus enum."""

    def test_all_values(self):
        expected = {"connected", "disconnected", "auth_failed", "unknown"}
        actual = {s.value for s in HAConnectionStatus}
        self.assertEqual(actual, expected)


# ---------------------------------------------------------------------------
# HAEntity Tests
# ---------------------------------------------------------------------------

class TestHAEntity(unittest.TestCase):
    """Test HAEntity dataclass."""

    def test_domain_extraction(self):
        e = HAEntity(entity_id="light.living_room", state="on")
        self.assertEqual(e.domain, "light")

    def test_domain_no_dot(self):
        e = HAEntity(entity_id="nodot", state="on")
        self.assertEqual(e.domain, "")

    def test_friendly_name_from_attributes(self):
        e = HAEntity(
            entity_id="light.living_room", state="on",
            attributes={"friendly_name": "Living Room"},
        )
        self.assertEqual(e.friendly_name, "Living Room")

    def test_friendly_name_fallback(self):
        e = HAEntity(entity_id="light.living_room", state="on")
        self.assertEqual(e.friendly_name, "light.living_room")

    def test_to_dict(self):
        e = HAEntity(
            entity_id="sensor.temp", state="22.5",
            attributes={"unit": "°C", "friendly_name": "Temperature"},
            last_changed="2026-02-22T10:00:00Z",
        )
        d = e.to_dict()
        self.assertEqual(d["entity_id"], "sensor.temp")
        self.assertEqual(d["state"], "22.5")
        self.assertEqual(d["domain"], "sensor")
        self.assertEqual(d["friendly_name"], "Temperature")
        self.assertIn("attributes", d)
        self.assertIn("last_changed", d)
        self.assertIn("last_updated", d)

    def test_defaults(self):
        e = HAEntity(entity_id="light.x", state="off")
        self.assertEqual(e.attributes, {})
        self.assertEqual(e.last_changed, "")
        self.assertEqual(e.last_updated, "")


# ---------------------------------------------------------------------------
# HAAction Tests
# ---------------------------------------------------------------------------

class TestHAAction(unittest.TestCase):
    """Test HAAction dataclass."""

    def test_full_service(self):
        a = HAAction(domain="light", service="turn_on")
        self.assertEqual(a.full_service, "light.turn_on")

    def test_auto_timestamp(self):
        before = time.time()
        a = HAAction(domain="light", service="turn_on")
        after = time.time()
        self.assertGreaterEqual(a.timestamp, before)
        self.assertLessEqual(a.timestamp, after)

    def test_explicit_timestamp(self):
        a = HAAction(domain="light", service="turn_on", timestamp=12345.0)
        self.assertEqual(a.timestamp, 12345.0)

    def test_to_dict(self):
        a = HAAction(
            domain="light", service="turn_on",
            entity_id="light.living_room",
            data={"brightness": 200},
            agent_id="agent1",
        )
        d = a.to_dict()
        self.assertEqual(d["domain"], "light")
        self.assertEqual(d["service"], "turn_on")
        self.assertEqual(d["full_service"], "light.turn_on")
        self.assertEqual(d["entity_id"], "light.living_room")
        self.assertEqual(d["data"]["brightness"], 200)
        self.assertEqual(d["agent_id"], "agent1")
        self.assertIn("timestamp", d)

    def test_defaults(self):
        a = HAAction(domain="switch", service="toggle")
        self.assertEqual(a.entity_id, "")
        self.assertEqual(a.data, {})
        self.assertEqual(a.agent_id, "")


# ---------------------------------------------------------------------------
# HAActionResult Tests
# ---------------------------------------------------------------------------

class TestHAActionResult(unittest.TestCase):
    """Test HAActionResult dataclass."""

    def test_to_dict(self):
        action = HAAction(domain="light", service="turn_on")
        result = HAActionResult(
            success=True, action=action,
            safety=ActionSafety.SAFE,
            response={"result": "ok"},
        )
        d = result.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["safety"], "safe")
        self.assertIn("action", d)
        self.assertEqual(d["response"]["result"], "ok")
        self.assertEqual(d["error"], "")

    def test_error_result(self):
        action = HAAction(domain="lock", service="lock")
        result = HAActionResult(
            success=False, action=action,
            safety=ActionSafety.APPROVAL_REQUIRED,
            error="Approval needed",
        )
        d = result.to_dict()
        self.assertFalse(d["success"])
        self.assertEqual(d["safety"], "approval_required")
        self.assertEqual(d["error"], "Approval needed")


# ---------------------------------------------------------------------------
# HAClient Connection Tests
# ---------------------------------------------------------------------------

class TestHAClientConnection(unittest.TestCase):
    """Test HAClient connection checking."""

    def test_no_token(self):
        client = HAClient(token="")
        status = client.check_connection()
        self.assertEqual(status, HAConnectionStatus.DISCONNECTED)

    @patch("ha_integration.urllib.request.urlopen")
    def test_connected(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"message": "API running."})
        client = HAClient(token="test_token")
        status = client.check_connection()
        self.assertEqual(status, HAConnectionStatus.CONNECTED)

    @patch("ha_integration.urllib.request.urlopen")
    def test_auth_failed(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="Unauthorized", hdrs=None, fp=None,
        )
        client = HAClient(token="bad_token")
        status = client.check_connection()
        self.assertEqual(status, HAConnectionStatus.AUTH_FAILED)

    @patch("ha_integration.urllib.request.urlopen")
    def test_connection_error(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionError("refused")
        client = HAClient(token="test_token")
        status = client.check_connection()
        self.assertEqual(status, HAConnectionStatus.DISCONNECTED)

    @patch("ha_integration.urllib.request.urlopen")
    def test_api_returns_none(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(None)
        client = HAClient(token="test_token")
        # json.loads("null") returns None
        status = client.check_connection()
        self.assertEqual(status, HAConnectionStatus.DISCONNECTED)


# ---------------------------------------------------------------------------
# Entity Query Tests
# ---------------------------------------------------------------------------

class TestEntityQueries(unittest.TestCase):
    """Test entity query methods."""

    def setUp(self):
        self.client = HAClient(token="test_token")

    @patch("ha_integration.urllib.request.urlopen")
    def test_get_states(self, mock_urlopen):
        entities = [
            _make_entity_dict("light.living_room", "on", "Living Room"),
            _make_entity_dict("sensor.temp", "22.5", "Temperature"),
        ]
        mock_urlopen.return_value = _FakeResponse(entities)
        result = self.client.get_states()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].entity_id, "light.living_room")
        self.assertEqual(result[1].state, "22.5")

    @patch("ha_integration.urllib.request.urlopen")
    def test_get_states_empty(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        result = self.client.get_states()
        self.assertEqual(result, [])

    @patch("ha_integration.urllib.request.urlopen")
    def test_get_states_none(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(None)
        result = self.client.get_states()
        self.assertEqual(result, [])

    @patch("ha_integration.urllib.request.urlopen")
    def test_get_state(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            _make_entity_dict("light.kitchen", "off", "Kitchen"),
        )
        result = self.client.get_state("light.kitchen")
        self.assertIsNotNone(result)
        self.assertEqual(result.entity_id, "light.kitchen")
        self.assertEqual(result.state, "off")

    @patch("ha_integration.urllib.request.urlopen")
    def test_get_state_not_found(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(None)
        result = self.client.get_state("light.nonexistent")
        self.assertIsNone(result)

    @patch("ha_integration.urllib.request.urlopen")
    def test_search_entities_by_query(self, mock_urlopen):
        entities = [
            _make_entity_dict("light.living_room", "on", "Living Room Light"),
            _make_entity_dict("light.bedroom", "off", "Bedroom Light"),
            _make_entity_dict("sensor.temp", "22", "Temperature"),
        ]
        mock_urlopen.return_value = _FakeResponse(entities)
        result = self.client.search_entities(query="living")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].entity_id, "light.living_room")

    @patch("ha_integration.urllib.request.urlopen")
    def test_search_entities_by_domain(self, mock_urlopen):
        entities = [
            _make_entity_dict("light.living_room", "on", "Living Room"),
            _make_entity_dict("sensor.temp", "22", "Temperature"),
            _make_entity_dict("sensor.humidity", "45", "Humidity"),
        ]
        mock_urlopen.return_value = _FakeResponse(entities)
        result = self.client.search_entities(domain="sensor")
        self.assertEqual(len(result), 2)

    @patch("ha_integration.urllib.request.urlopen")
    def test_search_entities_by_domain_and_query(self, mock_urlopen):
        entities = [
            _make_entity_dict("sensor.temp", "22", "Temperature"),
            _make_entity_dict("sensor.humidity", "45", "Humidity"),
        ]
        mock_urlopen.return_value = _FakeResponse(entities)
        result = self.client.search_entities(query="temp", domain="sensor")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].entity_id, "sensor.temp")

    @patch("ha_integration.urllib.request.urlopen")
    def test_search_case_insensitive(self, mock_urlopen):
        entities = [
            _make_entity_dict("light.living_room", "on", "Living Room Light"),
        ]
        mock_urlopen.return_value = _FakeResponse(entities)
        result = self.client.search_entities(query="LIVING")
        self.assertEqual(len(result), 1)

    @patch("ha_integration.urllib.request.urlopen")
    def test_search_no_filters(self, mock_urlopen):
        entities = [
            _make_entity_dict("light.a", "on", "A"),
            _make_entity_dict("sensor.b", "22", "B"),
        ]
        mock_urlopen.return_value = _FakeResponse(entities)
        result = self.client.search_entities()
        self.assertEqual(len(result), 2)

    @patch("ha_integration.urllib.request.urlopen")
    def test_get_domains(self, mock_urlopen):
        entities = [
            _make_entity_dict("light.a", "on", "A"),
            _make_entity_dict("light.b", "off", "B"),
            _make_entity_dict("sensor.c", "22", "C"),
            _make_entity_dict("switch.d", "on", "D"),
        ]
        mock_urlopen.return_value = _FakeResponse(entities)
        domains = self.client.get_domains()
        self.assertEqual(domains, ["light", "sensor", "switch"])


# ---------------------------------------------------------------------------
# Safety Classification Tests
# ---------------------------------------------------------------------------

class TestSafetyClassification(unittest.TestCase):
    """Test action safety classification."""

    def setUp(self):
        self.client = HAClient(token="test_token")

    def test_safe_domain_by_entity(self):
        action = HAAction(domain="homeassistant", service="state", entity_id="sensor.temp")
        result = self.client.classify_action(action)
        self.assertEqual(result, ActionSafety.SAFE)

    def test_approval_domain_by_entity(self):
        action = HAAction(domain="homeassistant", service="lock", entity_id="lock.front_door")
        result = self.client.classify_action(action)
        self.assertEqual(result, ActionSafety.APPROVAL_REQUIRED)

    def test_caution_unknown_domain(self):
        action = HAAction(domain="light", service="turn_on", entity_id="light.living_room")
        result = self.client.classify_action(action)
        self.assertEqual(result, ActionSafety.CAUTION)

    def test_safe_domain_fallback_to_action_domain(self):
        action = HAAction(domain="sensor", service="get_state")
        result = self.client.classify_action(action)
        self.assertEqual(result, ActionSafety.SAFE)

    def test_approval_domain_fallback(self):
        action = HAAction(domain="lock", service="lock")
        result = self.client.classify_action(action)
        self.assertEqual(result, ActionSafety.APPROVAL_REQUIRED)

    def test_all_safe_domains(self):
        for domain in SAFE_DOMAINS:
            action = HAAction(domain=domain, service="test")
            result = self.client.classify_action(action)
            self.assertEqual(result, ActionSafety.SAFE, f"{domain} should be SAFE")

    def test_all_approval_domains(self):
        for domain in APPROVAL_DOMAINS:
            action = HAAction(domain=domain, service="test")
            result = self.client.classify_action(action)
            self.assertEqual(
                result, ActionSafety.APPROVAL_REQUIRED,
                f"{domain} should be APPROVAL_REQUIRED",
            )


# ---------------------------------------------------------------------------
# Service Call Tests
# ---------------------------------------------------------------------------

class TestServiceCalls(unittest.TestCase):
    """Test service call execution."""

    def setUp(self):
        self.client = HAClient(token="test_token")

    @patch("ha_integration.urllib.request.urlopen")
    def test_safe_service_call(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([{"result": "ok"}])
        result = self.client.call_service(
            domain="sensor", service="get_state",
            entity_id="sensor.temp", agent_id="agent1",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.safety, ActionSafety.SAFE)

    @patch("ha_integration.urllib.request.urlopen")
    def test_caution_service_call(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([{"result": "ok"}])
        result = self.client.call_service(
            domain="light", service="turn_on",
            entity_id="light.living_room",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.safety, ActionSafety.CAUTION)

    def test_approval_required_blocked(self):
        result = self.client.call_service(
            domain="lock", service="lock",
            entity_id="lock.front_door",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.safety, ActionSafety.APPROVAL_REQUIRED)
        self.assertIn("approval", result.error.lower())

    @patch("ha_integration.urllib.request.urlopen")
    def test_skip_safety(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        result = self.client.call_service(
            domain="lock", service="lock",
            entity_id="lock.front_door",
            skip_safety=True,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.safety, ActionSafety.SAFE)

    @patch("ha_integration.urllib.request.urlopen")
    def test_service_call_with_data(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        result = self.client.call_service(
            domain="light", service="turn_on",
            entity_id="light.living_room",
            data={"brightness": 128, "color_temp": 400},
        )
        self.assertTrue(result.success)

    @patch("ha_integration.urllib.request.urlopen")
    def test_service_call_error(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionError("refused")
        result = self.client.call_service(
            domain="sensor", service="get_state",
            entity_id="sensor.temp",
        )
        self.assertFalse(result.success)
        self.assertIn("refused", result.error)

    @patch("ha_integration.urllib.request.urlopen")
    def test_service_call_no_entity(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        result = self.client.call_service(
            domain="sensor", service="update",
        )
        self.assertTrue(result.success)


# ---------------------------------------------------------------------------
# Action Log Tests
# ---------------------------------------------------------------------------

class TestActionLog(unittest.TestCase):
    """Test action logging."""

    def setUp(self):
        self.client = HAClient(token="test_token")

    @patch("ha_integration.urllib.request.urlopen")
    def test_log_populated(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        self.client.call_service("sensor", "get_state", "sensor.temp", agent_id="a1")
        self.client.call_service("input_boolean", "toggle", "input_boolean.x", agent_id="a2")
        log = self.client.get_action_log()
        self.assertEqual(len(log), 2)
        # Newest first
        self.assertEqual(log[0].agent_id, "a2")
        self.assertEqual(log[1].agent_id, "a1")

    @patch("ha_integration.urllib.request.urlopen")
    def test_log_filter_by_agent(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        self.client.call_service("sensor", "get_state", agent_id="a1")
        self.client.call_service("sensor", "get_state", agent_id="a2")
        self.client.call_service("sensor", "get_state", agent_id="a1")
        log = self.client.get_action_log(agent_id="a1")
        self.assertEqual(len(log), 2)

    @patch("ha_integration.urllib.request.urlopen")
    def test_log_limit(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        for i in range(10):
            self.client.call_service("sensor", "get_state", agent_id=f"a{i}")
        log = self.client.get_action_log(limit=3)
        self.assertEqual(len(log), 3)

    def test_log_empty(self):
        log = self.client.get_action_log()
        self.assertEqual(log, [])

    def test_approval_blocked_not_logged(self):
        self.client.call_service("lock", "lock", "lock.front_door")
        log = self.client.get_action_log()
        self.assertEqual(len(log), 0)


# ---------------------------------------------------------------------------
# Status Tests
# ---------------------------------------------------------------------------

class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_unconfigured_status(self):
        client = HAClient()
        s = client.status()
        self.assertEqual(s["url"], "http://homeassistant.local:8123")
        self.assertFalse(s["has_token"])
        self.assertEqual(s["connection"], "not_configured")
        self.assertEqual(s["total_actions"], 0)
        self.assertIn("sensor", s["safe_domains"])
        self.assertIn("lock", s["approval_domains"])

    @patch("ha_integration.urllib.request.urlopen")
    def test_configured_status(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse({"message": "API running."})
        client = HAClient(token="test_token")
        s = client.status()
        self.assertTrue(s["has_token"])
        self.assertEqual(s["connection"], "connected")

    @patch("ha_integration.urllib.request.urlopen")
    def test_status_action_count(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        client = HAClient(token="test_token")
        client.call_service("sensor", "get_state")
        client.call_service("sensor", "get_state")
        s = client.status()
        self.assertEqual(s["total_actions"], 2)


# ---------------------------------------------------------------------------
# Parse Entity Tests
# ---------------------------------------------------------------------------

class TestParseEntity(unittest.TestCase):
    """Test internal entity parsing."""

    def test_parse_full(self):
        data = _make_entity_dict("light.x", "on", "X Light")
        entity = HAClient._parse_entity(data)
        self.assertEqual(entity.entity_id, "light.x")
        self.assertEqual(entity.state, "on")
        self.assertEqual(entity.friendly_name, "X Light")

    def test_parse_minimal(self):
        entity = HAClient._parse_entity({})
        self.assertEqual(entity.entity_id, "")
        self.assertEqual(entity.state, "unknown")
        self.assertEqual(entity.attributes, {})

    def test_parse_missing_fields(self):
        entity = HAClient._parse_entity({"entity_id": "sensor.x"})
        self.assertEqual(entity.entity_id, "sensor.x")
        self.assertEqual(entity.state, "unknown")
        self.assertEqual(entity.last_changed, "")


# ---------------------------------------------------------------------------
# Domain Constants Tests
# ---------------------------------------------------------------------------

class TestDomainConstants(unittest.TestCase):
    """Test domain constant sets."""

    def test_no_overlap(self):
        overlap = SAFE_DOMAINS & APPROVAL_DOMAINS
        self.assertEqual(overlap, frozenset(), f"Overlap: {overlap}")

    def test_safe_domains_nonempty(self):
        self.assertGreater(len(SAFE_DOMAINS), 0)

    def test_approval_domains_nonempty(self):
        self.assertGreater(len(APPROVAL_DOMAINS), 0)

    def test_expected_safe_domains(self):
        for d in ("sensor", "binary_sensor", "weather", "sun", "zone"):
            self.assertIn(d, SAFE_DOMAINS)

    def test_expected_approval_domains(self):
        for d in ("lock", "alarm_control_panel", "cover", "siren"):
            self.assertIn(d, APPROVAL_DOMAINS)


# ---------------------------------------------------------------------------
# Thread Safety Tests
# ---------------------------------------------------------------------------

class TestThreadSafety(unittest.TestCase):
    """Test thread safety of HAClient."""

    @patch("ha_integration.urllib.request.urlopen")
    def test_concurrent_service_calls(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        client = HAClient(token="test_token")
        errors = []

        def caller(agent_id):
            try:
                for _ in range(20):
                    client.call_service("sensor", "get_state", agent_id=agent_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=caller, args=(f"agent_{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        log = client.get_action_log(limit=200)
        self.assertEqual(len(log), 100)

    @patch("ha_integration.urllib.request.urlopen")
    def test_concurrent_log_access(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse([])
        client = HAClient(token="test_token")
        errors = []

        # Populate some log entries
        for i in range(50):
            client.call_service("sensor", "get_state", agent_id=f"a{i}")

        def reader():
            try:
                for _ in range(20):
                    client.get_action_log(limit=10)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)


# ---------------------------------------------------------------------------
# Client Init Tests
# ---------------------------------------------------------------------------

class TestClientInit(unittest.TestCase):
    """Test HAClient initialization."""

    def test_default_url(self):
        client = HAClient()
        self.assertEqual(client._url, "http://homeassistant.local:8123")

    def test_custom_url(self):
        client = HAClient(url="http://192.168.1.100:8123")
        self.assertEqual(client._url, "http://192.168.1.100:8123")

    def test_url_trailing_slash_stripped(self):
        client = HAClient(url="http://192.168.1.100:8123/")
        self.assertEqual(client._url, "http://192.168.1.100:8123")

    def test_custom_timeout(self):
        client = HAClient(timeout=30)
        self.assertEqual(client._timeout, 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
