"""
Tests for auth.py — API Authentication and Authorization

Tests cover:
  - Permission and AuthResult enums
  - APIKey dataclass (validity, expiry, permissions)
  - AuthEvent dataclass
  - Key creation and management
  - Authentication flow
  - Permission checking
  - Rate limiting
  - Key revocation and expiration
  - Audit logging
  - Status reporting
  - Thread safety
"""

import os
import sys
import threading
import time
import unittest

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import (
    API_KEY_PREFIX,
    APIKey,
    AuthEvent,
    AuthManager,
    AuthResult,
    Permission,
)


class TestPermission(unittest.TestCase):
    """Test Permission enum."""

    def test_all_permissions(self):
        expected = {"read", "write", "admin", "agent"}
        actual = {p.value for p in Permission}
        self.assertEqual(actual, expected)


class TestAuthResult(unittest.TestCase):
    """Test AuthResult enum."""

    def test_all_results(self):
        expected = {
            "ok", "invalid_key", "expired_key",
            "rate_limited", "insufficient_permissions", "missing_key",
        }
        actual = {r.value for r in AuthResult}
        self.assertEqual(actual, expected)


class TestAPIKey(unittest.TestCase):
    """Test APIKey dataclass."""

    def test_defaults(self):
        k = APIKey(key_id="k1", key_hash="abc", owner="user1")
        self.assertFalse(k.revoked)
        self.assertFalse(k.is_expired)
        self.assertTrue(k.is_valid)
        self.assertGreater(k.created_at, 0)

    def test_permissions(self):
        k = APIKey(
            key_id="k1", key_hash="abc", owner="user1",
            permissions={Permission.READ},
        )
        self.assertTrue(k.has_permission(Permission.READ))
        self.assertFalse(k.has_permission(Permission.WRITE))

    def test_admin_has_all(self):
        k = APIKey(
            key_id="k1", key_hash="abc", owner="admin1",
            permissions={Permission.ADMIN},
        )
        self.assertTrue(k.has_permission(Permission.READ))
        self.assertTrue(k.has_permission(Permission.WRITE))
        self.assertTrue(k.has_permission(Permission.AGENT))

    def test_expired(self):
        k = APIKey(
            key_id="k1", key_hash="abc", owner="user1",
            expires_at=time.time() - 100,
        )
        self.assertTrue(k.is_expired)
        self.assertFalse(k.is_valid)

    def test_not_expired(self):
        k = APIKey(
            key_id="k1", key_hash="abc", owner="user1",
            expires_at=time.time() + 3600,
        )
        self.assertFalse(k.is_expired)
        self.assertTrue(k.is_valid)

    def test_never_expires(self):
        k = APIKey(key_id="k1", key_hash="abc", owner="user1", expires_at=0)
        self.assertFalse(k.is_expired)

    def test_revoked(self):
        k = APIKey(key_id="k1", key_hash="abc", owner="user1", revoked=True)
        self.assertFalse(k.is_valid)

    def test_to_dict(self):
        k = APIKey(
            key_id="k1", key_hash="abc", owner="user1",
            permissions={Permission.READ, Permission.WRITE},
        )
        d = k.to_dict()
        self.assertEqual(d["key_id"], "k1")
        self.assertEqual(d["owner"], "user1")
        self.assertIn("read", d["permissions"])
        self.assertNotIn("key_hash", d)  # Hash should NOT be exposed


class TestAuthEvent(unittest.TestCase):
    """Test AuthEvent dataclass."""

    def test_to_dict(self):
        e = AuthEvent(
            timestamp=time.time(),
            event_type="auth_success",
            key_id="k1",
            owner="user1",
            result="ok",
        )
        d = e.to_dict()
        self.assertEqual(d["event_type"], "auth_success")
        self.assertIn("timestamp", d)


class TestKeyCreation(unittest.TestCase):
    """Test API key creation."""

    def setUp(self):
        self.am = AuthManager()

    def test_create_key(self):
        raw_key, api_key = self.am.create_key("user1")
        self.assertTrue(raw_key.startswith(API_KEY_PREFIX))
        self.assertEqual(api_key.owner, "user1")
        self.assertTrue(api_key.is_valid)

    def test_create_with_permissions(self):
        _, api_key = self.am.create_key(
            "admin1",
            permissions={Permission.ADMIN},
        )
        self.assertTrue(api_key.has_permission(Permission.ADMIN))

    def test_create_with_expiry(self):
        _, api_key = self.am.create_key("user1", expires_in=3600)
        self.assertGreater(api_key.expires_at, 0)
        self.assertFalse(api_key.is_expired)

    def test_create_with_description(self):
        _, api_key = self.am.create_key("user1", description="Test key")
        self.assertEqual(api_key.description, "Test key")

    def test_create_empty_owner_raises(self):
        with self.assertRaises(ValueError):
            self.am.create_key("")

    def test_create_with_rate_limit(self):
        _, api_key = self.am.create_key("user1", rate_limit=10)
        self.assertEqual(api_key.rate_limit, 10)

    def test_unique_keys(self):
        raw1, _ = self.am.create_key("user1")
        raw2, _ = self.am.create_key("user1")
        self.assertNotEqual(raw1, raw2)


class TestAuthentication(unittest.TestCase):
    """Test authentication flow."""

    def setUp(self):
        self.am = AuthManager()
        self.raw_key, self.api_key = self.am.create_key("user1")

    def test_valid_key(self):
        result, key = self.am.authenticate(self.raw_key)
        self.assertEqual(result, AuthResult.OK)
        self.assertIsNotNone(key)
        self.assertEqual(key.owner, "user1")

    def test_invalid_key(self):
        result, key = self.am.authenticate("bridge_invalid_key_here")
        self.assertEqual(result, AuthResult.INVALID_KEY)
        self.assertIsNone(key)

    def test_missing_key(self):
        result, key = self.am.authenticate("")
        self.assertEqual(result, AuthResult.MISSING_KEY)
        self.assertIsNone(key)

    def test_revoked_key(self):
        self.am.revoke_key(self.api_key.key_id)
        result, key = self.am.authenticate(self.raw_key)
        self.assertEqual(result, AuthResult.INVALID_KEY)

    def test_expired_key(self):
        raw, api_key = self.am.create_key("user1", expires_in=0.001)
        time.sleep(0.01)
        result, key = self.am.authenticate(raw)
        self.assertEqual(result, AuthResult.EXPIRED_KEY)


class TestPermissionChecking(unittest.TestCase):
    """Test permission enforcement."""

    def setUp(self):
        self.am = AuthManager()

    def test_read_only_key(self):
        raw, _ = self.am.create_key(
            "reader", permissions={Permission.READ},
        )
        result, _ = self.am.authenticate(raw, Permission.READ)
        self.assertEqual(result, AuthResult.OK)

        result, _ = self.am.authenticate(raw, Permission.WRITE)
        self.assertEqual(result, AuthResult.INSUFFICIENT_PERMISSIONS)

    def test_admin_key_has_all(self):
        raw, _ = self.am.create_key(
            "admin", permissions={Permission.ADMIN},
        )
        for perm in Permission:
            result, _ = self.am.authenticate(raw, perm)
            self.assertEqual(result, AuthResult.OK, f"Admin should have {perm}")


class TestRateLimiting(unittest.TestCase):
    """Test rate limiting."""

    def setUp(self):
        self.am = AuthManager()

    def test_rate_limit_enforced(self):
        raw, _ = self.am.create_key("user1", rate_limit=3)

        for _ in range(3):
            result, _ = self.am.authenticate(raw)
            self.assertEqual(result, AuthResult.OK)

        result, _ = self.am.authenticate(raw)
        self.assertEqual(result, AuthResult.RATE_LIMITED)


class TestKeyManagement(unittest.TestCase):
    """Test key management operations."""

    def setUp(self):
        self.am = AuthManager()

    def test_revoke_key(self):
        _, api_key = self.am.create_key("user1")
        self.assertTrue(self.am.revoke_key(api_key.key_id))
        self.assertTrue(api_key.revoked)

    def test_revoke_nonexistent(self):
        self.assertFalse(self.am.revoke_key("missing"))

    def test_get_key_info(self):
        _, api_key = self.am.create_key("user1")
        info = self.am.get_key_info(api_key.key_id)
        self.assertIsNotNone(info)
        self.assertEqual(info.owner, "user1")

    def test_get_key_info_missing(self):
        self.assertIsNone(self.am.get_key_info("missing"))

    def test_list_keys(self):
        self.am.create_key("user1")
        self.am.create_key("user2")
        self.am.create_key("user1")
        all_keys = self.am.list_keys()
        self.assertEqual(len(all_keys), 3)

    def test_list_keys_by_owner(self):
        self.am.create_key("user1")
        self.am.create_key("user2")
        self.am.create_key("user1")
        user1_keys = self.am.list_keys(owner="user1")
        self.assertEqual(len(user1_keys), 2)


class TestAuditLog(unittest.TestCase):
    """Test audit logging."""

    def setUp(self):
        self.am = AuthManager()

    def test_log_created(self):
        self.am.create_key("user1")
        log = self.am.get_audit_log(event_type="key_created")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].owner, "user1")

    def test_log_auth_success(self):
        raw, _ = self.am.create_key("user1")
        self.am.authenticate(raw)
        log = self.am.get_audit_log(event_type="auth_success")
        self.assertEqual(len(log), 1)

    def test_log_auth_failure(self):
        self.am.authenticate("invalid")
        log = self.am.get_audit_log(event_type="auth_failure")
        self.assertEqual(len(log), 1)

    def test_log_limit(self):
        log = self.am.get_audit_log(limit=5)
        self.assertLessEqual(len(log), 5)

    def test_log_by_key_id(self):
        _, api_key = self.am.create_key("user1")
        log = self.am.get_audit_log(key_id=api_key.key_id)
        self.assertGreater(len(log), 0)

    def test_audit_cap(self):
        am = AuthManager(audit_limit=5)
        for i in range(10):
            am.create_key(f"user{i}")
        self.assertLessEqual(len(am._audit_log), 5)


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_empty_status(self):
        am = AuthManager()
        s = am.status()
        self.assertEqual(s["total_keys"], 0)
        self.assertEqual(s["active_keys"], 0)

    def test_status_with_keys(self):
        am = AuthManager()
        am.create_key("user1")
        am.create_key("user2")
        raw, api_key = am.create_key("user3")
        am.revoke_key(api_key.key_id)

        s = am.status()
        self.assertEqual(s["total_keys"], 3)
        self.assertEqual(s["active_keys"], 2)
        self.assertEqual(s["revoked_keys"], 1)
        self.assertIn("user1", s["owners"])


class TestThreadSafety(unittest.TestCase):
    """Test thread safety."""

    def test_concurrent_create(self):
        am = AuthManager()
        errors = []

        def creator(user_id):
            try:
                for _ in range(20):
                    am.create_key(user_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=creator, args=(f"user_{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(am.status()["total_keys"], 100)

    def test_concurrent_auth(self):
        am = AuthManager()
        raw, _ = am.create_key("user1", rate_limit=10000)
        errors = []

        def authenticator():
            try:
                for _ in range(50):
                    am.authenticate(raw)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=authenticator)
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
