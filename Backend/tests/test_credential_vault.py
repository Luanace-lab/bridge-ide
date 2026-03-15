"""
Tests for credential_vault.py — Secure Credential Store

Tests cover:
  - Basic CRUD (set, get, delete, list, has)
  - Encryption (set with passphrase, load from disk)
  - Scope-based access control
  - Environment variable integration
  - Audit logging
  - Edge cases (wrong passphrase, empty vault, missing credentials)
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from credential_vault import (
    CredentialVault,
    _decrypt,
    _encrypt,
)


class TestEncryption(unittest.TestCase):
    """Test encryption/decryption helpers."""

    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "my_secret_api_key_123"
        passphrase = "strong_password"
        encrypted = _encrypt(plaintext, passphrase)
        decrypted = _decrypt(encrypted, passphrase)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_produces_different_ciphertext(self):
        plaintext = "same_value"
        passphrase = "same_pass"
        c1 = _encrypt(plaintext, passphrase)
        c2 = _encrypt(plaintext, passphrase)
        # Different salt means different ciphertext
        self.assertNotEqual(c1, c2)

    def test_decrypt_wrong_passphrase(self):
        plaintext = "secret"
        encrypted = _encrypt(plaintext, "correct_pass")
        # Wrong passphrase returns empty string (graceful failure)
        decrypted = _decrypt(encrypted, "wrong_pass")
        self.assertNotEqual(decrypted, plaintext)
        # May be empty string or garbage that happens to be valid UTF-8
        self.assertIsInstance(decrypted, str)

    def test_encrypt_empty_string(self):
        encrypted = _encrypt("", "pass")
        decrypted = _decrypt(encrypted, "pass")
        self.assertEqual(decrypted, "")

    def test_encrypt_unicode(self):
        plaintext = "API-Key: äöü-\u00e9\u00e8-\U0001f600"
        encrypted = _encrypt(plaintext, "pass")
        decrypted = _decrypt(encrypted, "pass")
        self.assertEqual(decrypted, plaintext)


class TestCredentialVaultBasic(unittest.TestCase):
    """Test basic vault operations (no encryption)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_path = Path(self.tmpdir) / "vault.json"
        self.vault = CredentialVault(self.vault_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_set_and_get(self):
        self.vault.set("api_key", "sk-123456")
        self.assertEqual(self.vault.get("api_key"), "sk-123456")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.vault.get("nonexistent"))

    def test_has(self):
        self.assertFalse(self.vault.has("key"))
        self.vault.set("key", "value")
        self.assertTrue(self.vault.has("key"))

    def test_delete(self):
        self.vault.set("key", "value")
        self.assertTrue(self.vault.delete("key"))
        self.assertIsNone(self.vault.get("key"))

    def test_delete_missing_returns_false(self):
        self.assertFalse(self.vault.delete("nonexistent"))

    def test_update_overwrites(self):
        self.vault.set("key", "old_value")
        self.vault.set("key", "new_value")
        self.assertEqual(self.vault.get("key"), "new_value")

    def test_list_names(self):
        self.vault.set("key_a", "val_a", description="First key")
        self.vault.set("key_b", "val_b", description="Second key")
        names = self.vault.list_names()
        self.assertEqual(len(names), 2)
        # Values should NOT be in the list
        for item in names:
            self.assertNotIn("value", item.get("description", "val"))

    def test_list_names_sorted(self):
        self.vault.set("z_key", "v")
        self.vault.set("a_key", "v")
        names = self.vault.list_names()
        self.assertEqual(names[0]["name"], "a_key")
        self.assertEqual(names[1]["name"], "z_key")


class TestCredentialVaultPersistence(unittest.TestCase):
    """Test vault persistence (load/save)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_path = Path(self.tmpdir) / "vault.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_persists_to_disk(self):
        vault1 = CredentialVault(self.vault_path)
        vault1.set("key", "value")

        # New vault instance loads from disk
        vault2 = CredentialVault(self.vault_path)
        self.assertEqual(vault2.get("key"), "value")

    def test_persists_with_encryption(self):
        vault1 = CredentialVault(self.vault_path, passphrase="secret")
        vault1.set("api_key", "sk-test-123")

        # New vault with same passphrase
        vault2 = CredentialVault(self.vault_path, passphrase="secret")
        self.assertEqual(vault2.get("api_key"), "sk-test-123")

    def test_wrong_passphrase_fails_gracefully(self):
        vault1 = CredentialVault(self.vault_path, passphrase="correct")
        vault1.set("key", "value")

        # New vault with wrong passphrase — should load empty, not crash
        vault2 = CredentialVault(self.vault_path, passphrase="wrong")
        self.assertIsNone(vault2.get("key"))

    def test_empty_vault_file(self):
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_text("")
        vault = CredentialVault(self.vault_path)
        self.assertEqual(vault.list_names(), [])

    def test_unencrypted_vault_is_readable_json(self):
        vault = CredentialVault(self.vault_path)
        vault.set("key", "value")
        content = self.vault_path.read_text()
        data = json.loads(content)
        self.assertIn("key", data)
        self.assertEqual(data["key"]["value"], "value")


class TestCredentialVaultScope(unittest.TestCase):
    """Test scope-based access control."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_path = Path(self.tmpdir) / "vault.json"
        self.vault = CredentialVault(self.vault_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_scope_allows_all(self):
        self.vault.set("global_key", "value", scope=None)
        self.assertEqual(self.vault.get("global_key", agent_id="any_agent"), "value")

    def test_scope_restricts_access(self):
        self.vault.set("restricted", "secret", scope=["agent_a", "agent_b"])
        self.assertEqual(self.vault.get("restricted", agent_id="agent_a"), "secret")
        self.assertIsNone(self.vault.get("restricted", agent_id="agent_c"))

    def test_scope_empty_agent_id_allows(self):
        self.vault.set("scoped", "val", scope=["agent_a"])
        # No agent_id = system access, allowed
        self.assertEqual(self.vault.get("scoped"), "val")

    def test_update_scope(self):
        self.vault.set("key", "val", scope=["agent_a"])
        self.assertIsNone(self.vault.get("key", agent_id="agent_b"))

        self.vault.update_scope("key", ["agent_a", "agent_b"])
        self.assertEqual(self.vault.get("key", agent_id="agent_b"), "val")

    def test_update_scope_missing_returns_false(self):
        self.assertFalse(self.vault.update_scope("missing", ["a"]))

    def test_list_names_respects_scope(self):
        self.vault.set("public", "val", scope=None)
        self.vault.set("private", "val", scope=["agent_a"])

        names_a = self.vault.list_names(agent_id="agent_a")
        self.assertEqual(len(names_a), 2)

        names_b = self.vault.list_names(agent_id="agent_b")
        self.assertEqual(len(names_b), 1)
        self.assertEqual(names_b[0]["name"], "public")


class TestCredentialVaultEnv(unittest.TestCase):
    """Test environment variable integration."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_path = Path(self.tmpdir) / "vault.json"
        self.vault = CredentialVault(self.vault_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        # Clean up env vars
        for key in ["TEST_VAULT_KEY_A", "TEST_VAULT_KEY_B", "TEST_VAULT_EXPORT"]:
            os.environ.pop(key, None)

    def test_load_from_env(self):
        os.environ["TEST_VAULT_KEY_A"] = "value_a"
        os.environ["TEST_VAULT_KEY_B"] = "value_b"

        loaded = self.vault.load_from_env({
            "key_a": "TEST_VAULT_KEY_A",
            "key_b": "TEST_VAULT_KEY_B",
        })
        self.assertEqual(loaded, 2)
        self.assertEqual(self.vault.get("key_a"), "value_a")

    def test_load_from_env_skips_missing(self):
        os.environ["TEST_VAULT_KEY_A"] = "value_a"

        loaded = self.vault.load_from_env({
            "key_a": "TEST_VAULT_KEY_A",
            "key_missing": "NONEXISTENT_ENV_VAR",
        })
        self.assertEqual(loaded, 1)

    def test_export_to_env(self):
        self.vault.set("export_key", "export_value")
        result = self.vault.export_to_env("export_key", "TEST_VAULT_EXPORT")
        self.assertTrue(result)
        self.assertEqual(os.environ.get("TEST_VAULT_EXPORT"), "export_value")

    def test_export_missing_returns_false(self):
        result = self.vault.export_to_env("missing", "TEST_VAULT_EXPORT")
        self.assertFalse(result)


class TestCredentialVaultAudit(unittest.TestCase):
    """Test audit logging."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_path = Path(self.tmpdir) / "vault.json"
        self.audit_dir = Path(self.tmpdir) / "audit"
        self.vault = CredentialVault(
            self.vault_path, audit_dir=self.audit_dir
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_audit_log_created(self):
        self.vault.set("key", "value")
        log_path = self.audit_dir / "credential_audit.jsonl"
        self.assertTrue(log_path.exists())

    def test_audit_logs_set_and_get(self):
        self.vault.set("key", "value")
        self.vault.get("key", agent_id="agent_a")

        log_path = self.audit_dir / "credential_audit.jsonl"
        lines = log_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)

        actions = [json.loads(line)["action"] for line in lines]
        self.assertIn("set", actions)
        self.assertIn("get", actions)

    def test_audit_logs_denied_access(self):
        self.vault.set("restricted", "value", scope=["agent_a"])
        self.vault.get("restricted", agent_id="agent_b")

        log_path = self.audit_dir / "credential_audit.jsonl"
        lines = log_path.read_text().strip().splitlines()
        last_entry = json.loads(lines[-1])
        self.assertEqual(last_entry["action"], "get_denied")

    def test_audit_logs_miss(self):
        self.vault.get("nonexistent", agent_id="agent_a")

        log_path = self.audit_dir / "credential_audit.jsonl"
        lines = log_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["action"], "get_miss")


if __name__ == "__main__":
    unittest.main(verbosity=2)
