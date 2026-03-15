from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from federation_config import (
    bootstrap_local_instance,
    is_peer_allowed,
    load_federation_config,
    save_federation_config,
)


class TestFederationConfig(unittest.TestCase):
    def test_bootstrap_creates_key_files_with_secure_modes(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = bootstrap_local_instance(base_dir=td)

            for key_name in ("signing_private_key_path", "exchange_private_key_path"):
                path = cfg[key_name]
                mode = stat.S_IMODE(os.stat(path).st_mode)
                self.assertEqual(mode, 0o600)

    def test_deny_by_default_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = bootstrap_local_instance(base_dir=td)
            cfg["allowlist"] = ["inst-jp"]
            save_federation_config(cfg, base_dir=td)

            loaded = load_federation_config(base_dir=td)
            self.assertTrue(is_peer_allowed(loaded, "inst-jp"))
            self.assertFalse(is_peer_allowed(loaded, "inst-unknown"))

    def test_bootstrap_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            first = bootstrap_local_instance(base_dir=td)
            second = bootstrap_local_instance(base_dir=td)
            self.assertEqual(first["instance_id"], second["instance_id"])
            self.assertEqual(first["signing_public_key_hex"], second["signing_public_key_hex"])
            self.assertEqual(first["exchange_public_key_hex"], second["exchange_public_key_hex"])


if __name__ == "__main__":
    unittest.main()
