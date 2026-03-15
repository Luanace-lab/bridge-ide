from __future__ import annotations

import os
import sys
from pathlib import Path


def repo_root() -> Path:
    """Find the Bridge repo root. Works in source checkout and packaged installs."""
    env_root = os.environ.get("BRIDGE_ROOT")
    if env_root:
        candidate = Path(env_root).resolve()
        if (candidate / "Backend" / "server.py").exists():
            return candidate

    source_root = Path(__file__).resolve().parent.parent
    if (source_root / "Backend" / "server.py").exists():
        return source_root

    for candidate in (
        Path.home() / "Desktop" / "CC" / "BRIDGE",
        Path("/opt/bridge-ide"),
    ):
        if (candidate / "Backend" / "server.py").exists():
            return candidate

    return source_root


def backend_dir() -> Path:
    """Return the Backend directory containing server.py."""
    env_backend = os.environ.get("BRIDGE_BACKEND_DIR")
    if env_backend:
        candidate = Path(env_backend).resolve()
        if (candidate / "server.py").exists():
            return candidate
    return repo_root() / "Backend"


def ensure_backend_on_path() -> Path:
    backend = backend_dir()
    backend_str = str(backend)
    if backend_str not in sys.path:
        sys.path.insert(0, backend_str)
    return backend
