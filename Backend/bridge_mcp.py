#!/usr/bin/env python3
"""
MCP Server for Bridge API communication.

Provides native MCP tools for agent-to-agent communication via the Bridge server.
Replaces curl-based polling with efficient WebSocket push and native tool calls.

Usage:
    python3 bridge_mcp.py

Architecture:
    - stdio transport (Claude Code connects via stdin/stdout)
    - Background WebSocket connection to ws://127.0.0.1:9112 for push messages
    - Background heartbeat task (every 30s via HTTP POST)
    - Message buffer for received WebSocket messages
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import math
import os
import random
import re
import signal
import shlex
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

import bridge_cli_identity
import execution_journal
from common import mask_phone as _mask_phone
from common import load_bridge_agent_session_token
from common import store_bridge_agent_session_token
from execution_contracts import error_result, success_result
from mcp_catalog import runtime_mcp_registry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BRIDGE_SERVER_URL = os.environ.get("BRIDGE_SERVER_URL", "").strip().rstrip("/")
if _BRIDGE_SERVER_URL:
    BRIDGE_HTTP = _BRIDGE_SERVER_URL
    # Derive WebSocket URL: http→ws, https→wss, append /ws for Caddy routing
    if _BRIDGE_SERVER_URL.startswith("https://"):
        BRIDGE_WS = "wss://" + _BRIDGE_SERVER_URL[8:] + "/ws"
    elif _BRIDGE_SERVER_URL.startswith("http://"):
        BRIDGE_WS = "ws://" + _BRIDGE_SERVER_URL[7:] + "/ws"
    else:
        BRIDGE_WS = "ws://" + _BRIDGE_SERVER_URL + "/ws"
else:
    BRIDGE_HTTP = "http://127.0.0.1:9111"
    BRIDGE_WS = "ws://127.0.0.1:9112"
HEARTBEAT_INTERVAL = 30  # seconds
WS_RECONNECT_DELAY = 3  # seconds
MESSAGE_BUFFER_MAX = 500
PLAYWRIGHT_MCP_COMMAND = os.environ.get("PLAYWRIGHT_MCP_COMMAND", "").strip()
try:
    PLAYWRIGHT_MCP_TIMEOUT = max(10.0, float(os.environ.get("PLAYWRIGHT_MCP_TIMEOUT", "45")))
except ValueError:
    PLAYWRIGHT_MCP_TIMEOUT = 45.0
_BROWSER_ALLOWED_RISK_LEVELS = {"medium", "high", "critical"}

_TOKEN_CONFIG_FILE = os.path.expanduser("~/.config/bridge/tokens.json")
_N8N_ENV_FILE = os.path.expanduser("~/.config/bridge/n8n.env")


def _load_bridge_register_token(token_file: str | None = None) -> str:
    """Load register token — ALWAYS prefer disk over env var.

    The env var BRIDGE_REGISTER_TOKEN is a snapshot frozen at agent launch.
    After server restart, tokens.json is updated but the env var stays stale.
    Reading from disk ensures we always use the current token.
    Env var is only used as last-resort fallback if the file is unreadable.
    """
    configured_path = os.environ.get("BRIDGE_TOKEN_CONFIG_FILE", "").strip()
    path = os.path.expanduser(token_file or configured_path or _TOKEN_CONFIG_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        disk_token = str(payload.get("register_token", "")).strip()
        if disk_token:
            return disk_token
    except (OSError, json.JSONDecodeError):
        pass

    # Fallback: env var (may be stale after server restart, but better than nothing)
    return os.environ.get("BRIDGE_REGISTER_TOKEN", "").strip()


def _load_n8n_config() -> tuple[str, str]:
    """Load n8n base URL and API key from env or config file."""
    env_vars: dict[str, str] = {}
    if os.path.isfile(_N8N_ENV_FILE):
        with open(_N8N_ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip('"')
    base_url = os.environ.get("N8N_BASE_URL", env_vars.get("N8N_BASE_URL", "http://localhost:5678")).rstrip("/")
    api_key = os.environ.get("N8N_API_KEY", env_vars.get("N8N_API_KEY", ""))
    return base_url, api_key


# ---------------------------------------------------------------------------
# Logging — stderr only (stdout is MCP stdio transport)
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[bridge_mcp] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("bridge_mcp")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_agent_id: str | None = None
_session_token: str | None = None  # S5: session token from /register
_is_management_agent: bool = False  # True if agent is level <= 1 and active in team.json
_message_buffer: deque[dict[str, Any]] = deque(maxlen=MESSAGE_BUFFER_MAX)
_buffer_lock = asyncio.Lock()
_ws_task: asyncio.Task[None] | None = None
_heartbeat_task: asyncio.Task[None] | None = None
_http_client: httpx.AsyncClient | None = None
_last_seen_msg_id: int = -1  # Track highest seen message ID to avoid duplicates after reconnect
_reregister_lock = asyncio.Lock()  # S3-F5 FIX: Serialize re-register calls

# Hardening: Session-Nonce + Identity Preservation
_session_nonce: str = str(uuid.uuid4())  # Unique per MCP process lifetime — survives /compact
_registered_once: bool = False  # True after first successful registration
_registered_role: str = ""  # Preserved role for auto-re-registration (C2/C6 fix)
_registered_capabilities: list[str] = []  # Preserved capabilities for auto-re-registration


def _cli_identity_payload_from_env(*, transport_source: str = "") -> dict[str, str]:
    return bridge_cli_identity.cli_identity_payload_from_env(
        os.environ,
        transport_source=transport_source,
    )


def _self_reflection_agent_configs() -> dict[str, dict[str, Any]]:
    return bridge_cli_identity.self_reflection_agent_configs(
        os.environ,
        agent_id=_agent_id,
        registered_role=_registered_role,
    )


def _heartbeat_payload() -> dict[str, Any]:
    return bridge_cli_identity.heartbeat_payload(
        os.environ,
        agent_id=_agent_id,
        transport_source="cli_heartbeat",
    )


def _persist_agent_session_token_for_helpers() -> None:
    workspace = (
        str(os.environ.get("BRIDGE_CLI_WORKSPACE", "")).strip()
        or str(os.environ.get("BRIDGE_CLI_HOME_DIR", "")).strip()
    )
    if not workspace or not _agent_id or not _session_token:
        return
    path = store_bridge_agent_session_token(
        workspace,
        agent_id=_agent_id,
        session_token=_session_token,
        source="bridge_mcp",
    )
    log.info("Persisted helper session token at %s", path)


async def _send_heartbeat_once(*, auto_reregister: bool) -> dict[str, Any]:
    resp = await _bridge_post("/heartbeat", json=_heartbeat_payload())
    resp.raise_for_status()
    hb_data = resp.json()
    if hb_data.get("registered") is False and auto_reregister:
        log.warning("Heartbeat: server says not registered — triggering auto-re-register for %s", _agent_id)
        hb_data["auto_reregistered"] = await _auto_reregister()
    return hb_data


# ---------------------------------------------------------------------------
# Stealth Browser State
# ---------------------------------------------------------------------------

_STEALTH_MEMORY_SPOOF = """\
try {
    // Define on Prototype (not instance) to avoid hasOwnProperty/ownKeys detection
    var _memTarget = (typeof Performance !== 'undefined' && Performance.prototype) ? Performance.prototype : performance;
    Object.defineProperty(_memTarget, 'memory', {
        get: function() { return {
            jsHeapSizeLimit: 2172649472,
            totalJSHeapSize: 35839892,
            usedJSHeapSize: 23292036
        }; },
        configurable: true,
        enumerable: true
    });
} catch(e) {}"""

_STEALTH_PERMISSION_MEDIA_SPOOF = """\
(function() {
    const _initialNotificationPermission = (() => {
        try {
            if (typeof Notification === 'undefined') {
                return 'default';
            }
            return Notification.permission;
        } catch(e) {
            return 'default';
        }
    })();
    const _normalizedNotificationPermission = _initialNotificationPermission === 'granted' ? 'granted' : 'default';
    const _promptPermissions = {
        notifications: 'prompt',
        geolocation: 'prompt',
        camera: 'prompt',
        microphone: 'prompt',
        'persistent-storage': 'prompt',
        'clipboard-read': 'prompt',
        'clipboard-write': 'prompt',
        push: 'prompt',
    };

    try {
        if (typeof Notification !== 'undefined') {
            Object.defineProperty(Notification, 'permission', {
                get: () => _normalizedNotificationPermission,
                configurable: true
            });
        }
    } catch(e) {}

    try {
        Object.defineProperty(Navigator.prototype, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
    } catch(e) {}

    try {
        if ((navigator.userAgent || '').includes('Firefox/')) {
            Object.defineProperty(Navigator.prototype, 'serviceWorker', {
                get: () => undefined,
                configurable: true
            });
        }
    } catch(e) {}

    try {
        if (navigator.permissions && typeof navigator.permissions.query === 'function') {
            const _origQuery = navigator.permissions.query.bind(navigator.permissions);
            const _buildPermissionStatus = (state) => {
                const _status = {
                    state: state,
                    onchange: null,
                    addEventListener: () => {},
                    removeEventListener: () => {},
                    dispatchEvent: () => true
                };
                if (typeof PermissionStatus !== 'undefined') {
                    Object.setPrototypeOf(_status, PermissionStatus.prototype);
                }
                return _status;
            };
            navigator.permissions.query = function(desc) {
                const name = desc && desc.name ? String(desc.name) : '';
                if (name === 'notifications') {
                    const notificationState = _normalizedNotificationPermission === 'granted' ? 'granted' : 'prompt';
                    return Promise.resolve(_buildPermissionStatus(notificationState));
                }
                if (name in _promptPermissions) {
                    return Promise.resolve(_buildPermissionStatus(_promptPermissions[name]));
                }
                return _origQuery(desc).catch((err) => {
                    if (name) {
                        return _buildPermissionStatus('prompt');
                    }
                    throw err;
                });
            };
            Object.defineProperty(navigator.permissions.query, 'toString', {
                value: () => 'function query() { [native code] }',
                configurable: false
            });
        }
    } catch(e) {}

    try {
        if (navigator.mediaDevices && typeof navigator.mediaDevices.enumerateDevices === 'function') {
            const _origEnumerateDevices = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
            navigator.mediaDevices.enumerateDevices = function() {
                return _origEnumerateDevices().catch(() => []);
            };
            Object.defineProperty(navigator.mediaDevices.enumerateDevices, 'toString', {
                value: () => 'function enumerateDevices() { [native code] }',
                configurable: false
            });
        }
    } catch(e) {}

    try {
        if (navigator.storage) {
            if (typeof navigator.storage.persisted !== 'function') {
                navigator.storage.persisted = () => Promise.resolve(false);
            }
            if (typeof navigator.storage.estimate !== 'function') {
                navigator.storage.estimate = () => Promise.resolve({usage: 0, quota: 1073741824});
            }
        }
    } catch(e) {}
})();"""

# Hardware + identity spoofing for proxy/Tor sessions.
# Goal: keep a Firefox/Tor-like JS footprint internally coherent instead of
# mixing a Tor UA with Chromium-only navigator fields.
_STEALTH_HARDWARE_SPOOF = """\
// Fix uaDataIsBlank: Handle userAgentData based on UA type
// Firefox/Tor has NO userAgentData — remove it entirely for Tor sessions
// Chrome headless has empty brands — spoof with real brands for non-Tor
const isTorUA = navigator.userAgent && navigator.userAgent.includes('rv:140.0');
if (isTorUA) {
    // Firefox/Tor rounds hardware concurrency and does not expose deviceMemory.
    try {
        Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', {get: () => 2, configurable: true});
    } catch(e) {}
    try {
        Object.defineProperty(Navigator.prototype, 'deviceMemory', {get: () => undefined, configurable: true});
    } catch(e) { try { delete Navigator.prototype.deviceMemory; } catch(e2) {} }

    // Align Chromium navigator fields with the Firefox/Tor UA being presented.
    const _torNavigatorValues = {
        vendor: '',
        vendorSub: '',
        productSub: '20100101',
        platform: 'Win32',
        oscpu: 'Windows NT 10.0; Win64; x64',
        language: 'en-US',
        pdfViewerEnabled: true,
    };
    for (const [key, value] of Object.entries(_torNavigatorValues)) {
        try {
            Object.defineProperty(Navigator.prototype, key, {get: () => value, configurable: true});
        } catch(e) {}
    }
    try {
        Object.defineProperty(Navigator.prototype, 'languages', {
            get: () => Object.freeze(['en-US', 'en']),
            configurable: true
        });
    } catch(e) {}
    const _torScreenValues = {
        width: 1536,
        height: 864,
        availWidth: 1536,
        availHeight: 824,
        availTop: 0,
        availLeft: 0,
        colorDepth: 24,
        pixelDepth: 24,
    };
    const _torScreenTargets = [];
    if (typeof Screen !== 'undefined' && Screen.prototype) {
        _torScreenTargets.push(Screen.prototype);
    }
    if (typeof screen !== 'undefined') {
        _torScreenTargets.unshift(screen);
    }
    for (const _target of _torScreenTargets) {
        for (const [key, value] of Object.entries(_torScreenValues)) {
            try {
                Object.defineProperty(_target, key, {
                    get: () => value,
                    configurable: true
                });
            } catch(e) {}
        }
    }
    if (navigator.userAgentData) {
        try {
            Object.defineProperty(Navigator.prototype, 'userAgentData', {
                get: () => undefined,
                configurable: true
            });
        } catch(e) { try { delete Navigator.prototype.userAgentData; } catch(e2) {} }
    }
} else {
    // Define on Prototype with getter (not instance) — avoids hasOwnProperty/ownKeys detection
    Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', {get: () => 4, configurable: true});
    Object.defineProperty(Navigator.prototype, 'deviceMemory', {get: () => 8, configurable: true});
    if (navigator.userAgentData) {
        const brandData = {
            brands: [
                {brand: 'Chromium', version: '145'},
                {brand: 'Google Chrome', version: '145'},
                {brand: 'Not-A.Brand', version: '99'}
            ],
            mobile: false,
            platform: 'Windows'
        };
        try {
            Object.defineProperty(Navigator.prototype, 'userAgentData', {
                get: () => ({
                    ...brandData,
                    getHighEntropyValues: (hints) => Promise.resolve({
                        ...brandData,
                        architecture: 'x86',
                        bitness: '64',
                        fullVersionList: brandData.brands,
                        model: '',
                        platformVersion: '15.0.0',
                        uaFullVersion: '145.0.0.0',
                        wow64: false
                    }),
                    toJSON: () => brandData
                }),
                configurable: true
            });
        } catch(e) {}
    }
}

// Fix noTaskbar: Make availHeight < screen.height (real browsers have taskbar)
try {
    Object.defineProperty(screen, 'availHeight', {value: screen.height - 40, writable: false, configurable: false});
    Object.defineProperty(screen, 'availWidth', {value: screen.width, writable: false, configurable: false});
    Object.defineProperty(screen, 'availTop', {value: 0, writable: false, configurable: false});
    Object.defineProperty(screen, 'availLeft', {value: 0, writable: false, configurable: false});
} catch(e) {}

// Fix noWebShare + missing APIs: Stub implementations on Prototype
if (!navigator.share) {
    Object.defineProperty(Navigator.prototype, 'share', {get: () => (() => Promise.reject(new DOMException('Share canceled', 'AbortError'))), configurable: true});
    Object.defineProperty(Navigator.prototype, 'canShare', {get: () => (() => true), configurable: true});
}
if (!navigator.contacts) {
    Object.defineProperty(Navigator.prototype, 'contacts', {get: () => ({ select: () => Promise.resolve([]), getProperties: () => Promise.resolve([]) }), configurable: true});
}

// Fix noDownlinkMax: Stub NetworkInformation API
if (navigator.connection && !navigator.connection.downlinkMax) {
    try {
        Object.defineProperty(navigator.connection, 'downlinkMax', {value: Infinity, writable: false});
    } catch(e) {}
}

// Fix prefersLightColor + prefers-reduced-motion + prefers-contrast: Spoof media queries to realistic values
try {
    const origMatchMedia = window.matchMedia;
    const _spoofedQueries = {
        '(prefers-color-scheme: light)': false,
        '(prefers-color-scheme: dark)': true,
        '(prefers-reduced-motion: reduce)': false,
        '(prefers-reduced-motion: no-preference)': true,
        '(prefers-contrast: more)': false,
        '(prefers-contrast: no-preference)': true,
        '(forced-colors: active)': false,
        '(forced-colors: none)': true,
    };
    window.matchMedia = function(query) {
        if (query in _spoofedQueries) {
            return { matches: _spoofedQueries[query], media: query, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, onchange: null, dispatchEvent: () => true };
        }
        return origMatchMedia.call(this, query);
    };
    Object.defineProperty(window.matchMedia, 'toString', {value: () => 'function matchMedia() { [native code] }', configurable: false});
} catch(e) {}

// Fix permissions API: Stub navigator.permissions.query for common permissions
try {
    if (navigator.permissions) {
        const _origQuery = navigator.permissions.query;
        navigator.permissions.query = function(desc) {
            // Return realistic defaults for commonly queried permissions
            const _defaults = {notifications: 'prompt', geolocation: 'prompt', camera: 'prompt', microphone: 'prompt', 'persistent-storage': 'prompt', push: 'prompt'};
            if (desc && desc.name in _defaults) {
                const _result = {state: _defaults[desc.name], onchange: null, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => true};
                // Fix Bug 3: Use PermissionStatus prototype if available
                if (typeof PermissionStatus !== 'undefined') { Object.setPrototypeOf(_result, PermissionStatus.prototype); }
                return Promise.resolve(_result);
            }
            return _origQuery.call(this, desc);
        };
        Object.defineProperty(navigator.permissions.query, 'toString', {value: () => 'function query() { [native code] }', configurable: false});
    }
} catch(e) {}

// Fix getBattery: Always override on Prototype with spoofed values (headless Chromium has real getBattery)
try {
    const _fakeBattery = () => Promise.resolve({
        charging: true, chargingTime: 0, dischargingTime: Infinity, level: 1.0,
        addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => true,
        onchargingchange: null, onchargingtimechange: null, ondischargingtimechange: null, onlevelchange: null
    });
    Object.defineProperty(_fakeBattery, 'toString', {value: () => 'function getBattery() { [native code] }', configurable: false});
    Object.defineProperty(Navigator.prototype, 'getBattery', {get: () => _fakeBattery, configurable: true});
} catch(e) {}
"""

# Headless signal fix — reduces "63% like headless" in creepjs
# Targets: plugins, mimeTypes, window.chrome, connection.rtt, Notification.permission
_STEALTH_HEADLESS_FIX = """\
(function() {
    'use strict';

    // 1. Fake Chrome Plugins (PDF Viewer — standard in Chrome 145+)
    const _fakePlugins = [
        {name: 'PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', length: 1},
        {name: 'Chrome PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', length: 1},
        {name: 'Chromium PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', length: 1},
        {name: 'Microsoft Edge PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', length: 1},
        {name: 'WebKit built-in PDF', description: 'Portable Document Format', filename: 'internal-pdf-viewer', length: 1},
    ];

    const _fakeMimeType = {type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format'};

    // Create PluginArray-like object
    const _pluginArray = Object.create(PluginArray.prototype);
    _fakePlugins.forEach((p, i) => {
        const plugin = Object.create(Plugin.prototype);
        Object.defineProperties(plugin, {
            name: {value: p.name, enumerable: true},
            description: {value: p.description, enumerable: true},
            filename: {value: p.filename, enumerable: true},
            length: {value: p.length, enumerable: true},
            0: {value: _fakeMimeType, enumerable: true},
        });
        _pluginArray[i] = plugin;
    });
    Object.defineProperty(_pluginArray, 'length', {value: _fakePlugins.length, enumerable: true});
    _pluginArray.item = function(i) { return this[i] || null; };
    _pluginArray.namedItem = function(n) {
        for (let i = 0; i < this.length; i++) { if (this[i].name === n) return this[i]; }
        return null;
    };
    _pluginArray.refresh = function() {};

    Object.defineProperty(navigator, 'plugins', {get: () => _pluginArray, configurable: true});

    // 2. Fake MimeTypeArray
    const _mimeArray = Object.create(MimeTypeArray.prototype);
    const _mime1 = Object.create(MimeType.prototype);
    Object.defineProperties(_mime1, {
        type: {value: 'application/pdf', enumerable: true},
        suffixes: {value: 'pdf', enumerable: true},
        description: {value: 'Portable Document Format', enumerable: true},
        enabledPlugin: {value: _pluginArray[0], enumerable: true},
    });
    const _mime2 = Object.create(MimeType.prototype);
    Object.defineProperties(_mime2, {
        type: {value: 'text/pdf', enumerable: true},
        suffixes: {value: 'pdf', enumerable: true},
        description: {value: 'Portable Document Format', enumerable: true},
        enabledPlugin: {value: _pluginArray[0], enumerable: true},
    });
    _mimeArray[0] = _mime1;
    _mimeArray[1] = _mime2;
    Object.defineProperty(_mimeArray, 'length', {value: 2, enumerable: true});
    _mimeArray.item = function(i) { return this[i] || null; };
    _mimeArray.namedItem = function(n) {
        for (let i = 0; i < this.length; i++) { if (this[i].type === n) return this[i]; }
        return null;
    };

    Object.defineProperty(navigator, 'mimeTypes', {get: () => _mimeArray, configurable: true});

    // 3. Fake window.chrome object
    if (typeof window.chrome === 'undefined') {
        window.chrome = {
            app: {isInstalled: false, InstallState: {DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed'}, RunningState: {CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running'}},
            runtime: {OnInstalledReason: {CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update'}, OnRestartRequiredReason: {APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic'}, PlatformArch: {ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64'}, PlatformNaclArch: {ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64'}, PlatformOs: {ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win'}, RequestUpdateCheckStatus: {NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available'}, connect: function() {}, sendMessage: function() {}},
            csi: function() { return {}; },
            loadTimes: function() { return {}; },
        };
    }

    // 4. Fix connection.rtt (headless has rtt=0)
    if (navigator.connection) {
        const _origConn = navigator.connection;
        const _connProxy = new Proxy(_origConn, {
            get(target, prop) {
                if (prop === 'rtt') return 100;
                const val = target[prop];
                return typeof val === 'function' ? val.bind(target) : val;
            }
        });
        Object.defineProperty(navigator, 'connection', {get: () => _connProxy, configurable: true});
    }

    // 5. Fix Notification.permission (headless = "denied", real = "default")
    if (typeof Notification !== 'undefined') {
        try {
            Object.defineProperty(Notification, 'permission', {get: () => 'default', configurable: true});
        } catch(e) {}
    }
})();
"""

# WebGL renderer spoofing — hides SwiftShader (headless indicator)
# Spoofs to Intel Iris (common laptop GPU) to avoid headless detection
_STEALTH_WEBGL_SPOOF = """\
(function() {
    const _origGetParameter = WebGLRenderingContext.prototype.getParameter;
    const _origGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
    const _origGetExtension = WebGLRenderingContext.prototype.getExtension;
    const _origGetExtension2 = WebGL2RenderingContext.prototype.getExtension;
    // GL constants — Intel Iris OpenGL Engine consistent values
    const SPOOF_MAP = {
        0x9245: 'Intel Inc.',                    // UNMASKED_VENDOR_WEBGL
        0x9246: 'Intel Iris OpenGL Engine',      // UNMASKED_RENDERER_WEBGL
        0x1F00: 'WebKit',                        // VENDOR
        0x1F01: 'WebKit WebGL',                  // RENDERER
        0x0D33: 16384,                           // MAX_TEXTURE_SIZE
        0x84E8: 16384,                           // MAX_RENDERBUFFER_SIZE
        0x8869: 16,                              // MAX_VERTEX_ATTRIBS
        0x8DFC: 15,                              // MAX_VARYING_VECTORS (Intel Iris real value)
        0x8DFD: 1024,                            // MAX_FRAGMENT_UNIFORM_VECTORS
        0x8DFB: 1024,                            // MAX_VERTEX_UNIFORM_VECTORS
        0x8B4C: 16,                              // MAX_VERTEX_TEXTURE_IMAGE_UNITS
        0x8872: 16,                              // MAX_TEXTURE_IMAGE_UNITS
        0x8B4D: 32,                              // MAX_COMBINED_TEXTURE_IMAGE_UNITS
    };
    function _spoofedGetParam(orig, pname) {
        if (SPOOF_MAP.hasOwnProperty(pname)) return SPOOF_MAP[pname];
        // Range parameters (must return typed arrays)
        if (pname === 0x0D3D) return new Int32Array([16384, 16384]);   // MAX_VIEWPORT_DIMS
        if (pname === 0x846E) return new Float32Array([1, 7.375]);     // ALIASED_LINE_WIDTH_RANGE (real Intel Iris)
        if (pname === 0x846D) return new Float32Array([1, 255]);       // ALIASED_POINT_SIZE_RANGE (real Intel Iris)
        // MAX_TEXTURE_MAX_ANISOTROPY_EXT (from EXT_texture_filter_anisotropic)
        if (pname === 0x84FF) return 16;
        return orig.call(this, pname);
    }
    WebGLRenderingContext.prototype.getParameter = function(p) { return _spoofedGetParam.call(this, _origGetParameter, p); };
    WebGL2RenderingContext.prototype.getParameter = function(p) { return _spoofedGetParam.call(this, _origGetParameter2, p); };
    Object.defineProperty(WebGLRenderingContext.prototype.getParameter, 'toString', {value: () => 'function getParameter() { [native code] }', configurable: false});
    Object.defineProperty(WebGL2RenderingContext.prototype.getParameter, 'toString', {value: () => 'function getParameter() { [native code] }', configurable: false});
    // Spoof getExtension to return consistent debug_renderer_info
    function _spoofedGetExtension(orig, name) {
        const ext = orig.call(this, name);
        if (name === 'WEBGL_debug_renderer_info' && !ext) {
            // If extension is blocked, return a fake one with the constants
            return { UNMASKED_VENDOR_WEBGL: 0x9245, UNMASKED_RENDERER_WEBGL: 0x9246 };
        }
        return ext;
    }
    WebGLRenderingContext.prototype.getExtension = function(n) { return _spoofedGetExtension.call(this, _origGetExtension, n); };
    WebGL2RenderingContext.prototype.getExtension = function(n) { return _spoofedGetExtension.call(this, _origGetExtension2, n); };
    Object.defineProperty(WebGLRenderingContext.prototype.getExtension, 'toString', {value: () => 'function getExtension() { [native code] }', configurable: false});
    Object.defineProperty(WebGL2RenderingContext.prototype.getExtension, 'toString', {value: () => 'function getExtension() { [native code] }', configurable: false});
})();
"""

_STEALTH_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)


@dataclass
class StealthSession:
    session_id: str
    browser: Any        # Playwright Browser
    page: Any           # Playwright Page
    pw_context: Any     # async_playwright context (for cleanup)
    agent_id: str
    profile: str = ""   # Browser profile name for cookie persistence
    is_proxy: bool = False  # True if session uses proxy (Tor/SOCKS) — disables cookie persistence
    firefox_like: bool = False  # True if the declared UA should look Firefox/Tor-like in JS surfaces
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    first_navigation: bool = True  # Only first goto needs reload


_stealth_sessions: dict[str, StealthSession] = {}
_STEALTH_MAX_SESSIONS = 3       # per agent process
_STEALTH_IDLE_TIMEOUT = 300     # 5 minutes

# OPSEC args for proxy/Tor sessions — prevent DNS and WebRTC leaks
_STEALTH_PROXY_OPSEC_ARGS = [
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--enforce-webrtc-ip-permission-check",
    "--enable-features=WebRtcHideLocalIpsWithMdns",
    # NOTE: --host-resolver-rules=MAP * ~NOTFOUND was removed — it blocks ALL
    # navigation (ERR_NAME_NOT_RESOLVED) because Chromium resolves DNS before
    # proxy routing. For SOCKS5 proxies, Chrome handles remote DNS automatically
    # via SOCKS5h when proxy is set via --proxy-server or Playwright proxy config.
    "--disable-background-networking",
]

# Tor Browser User-Agent (matches Tor Browser stable / Firefox ESR 128)
# ALL Tor Browser users share this EXACT UA regardless of OS
_STEALTH_TOR_UA = (
    "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"
)

_STEALTH_FIREFOX_LIKE_STRIPPED_HEADERS = {
    "sec-ch-ua",
    "sec-ch-ua-arch",
    "sec-ch-ua-bitness",
    "sec-ch-ua-full-version",
    "sec-ch-ua-full-version-list",
    "sec-ch-ua-mobile",
    "sec-ch-ua-model",
    "sec-ch-ua-platform",
    "sec-ch-ua-platform-version",
}

_STEALTH_WORKER_NAVIGATOR_SPOOF = """\
(function() {
    const _navTarget =
        (typeof WorkerNavigator !== 'undefined' && WorkerNavigator.prototype)
            ? WorkerNavigator.prototype
            : ((typeof Navigator !== 'undefined' && Navigator.prototype)
                ? Navigator.prototype
                : Object.getPrototypeOf(navigator));
    const _ua = navigator.userAgent || '';
    const _isFirefoxLike = _ua.includes('Firefox/');
    const _define = (key, getter) => {
        try {
            Object.defineProperty(_navTarget, key, {
                get: getter,
                configurable: true
            });
        } catch(e) {}
    };

    _define('webdriver', () => undefined);

    if (_isFirefoxLike) {
        _define('platform', () => 'Win32');
        _define('language', () => 'en-US');
        _define('languages', () => Object.freeze(['en-US', 'en']));
        _define('hardwareConcurrency', () => 2);
        _define('deviceMemory', () => undefined);
        _define('userAgentData', () => undefined);
    }
})();"""

_STEALTH_FIREFOX_LIKE_POPUP_NAV = """\
(function() {
    const _origOpen = window.open.bind(window);
    function _openWithDelay(url, target, features) {
        if (!url || typeof url !== 'string' || url === 'about:blank') {
            return _origOpen(url, target, features);
        }
        const popup = _origOpen('about:blank', target, features);
        if (!popup) {
            return popup;
        }
        setTimeout(() => {
            try {
                popup.location.replace(url);
            } catch (err) {
                try {
                    popup.location = url;
                } catch (innerErr) {}
            }
        }, 25);
        return popup;
    }
    Object.defineProperty(window, 'open', {
        value: _openWithDelay,
        configurable: true,
        writable: true,
    });
    Object.defineProperty(window.open, 'toString', {
        value: () => 'function open() { [native code] }',
        configurable: false,
    });
})();"""

# WebRTC kill script — removes RTCPeerConnection as defense-in-depth
# Primary protection: Chromium flags (--force-webrtc-ip-handling-policy, --enforce-webrtc-ip-permission-check)
# This JS kill is a secondary layer injected via context.add_init_script for all frames
_STEALTH_WEBRTC_KILL = """\
(function() {
    const targets = ['RTCPeerConnection', 'webkitRTCPeerConnection', 'RTCSessionDescription', 'RTCIceCandidate', 'RTCDataChannel'];
    for (const t of targets) {
        try { delete window[t]; } catch(e) {}
        try {
            Object.defineProperty(window, t, {
                get: () => undefined,
                set: () => {},
                configurable: false
            });
        } catch(e) {
            try { window[t] = undefined; } catch(e2) {}
        }
    }
    // Also kill mediaDevices.getUserMedia to prevent media-based IP leaks
    if (navigator.mediaDevices) {
        navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Not allowed', 'NotAllowedError'));
        navigator.mediaDevices.enumerateDevices = () => Promise.resolve([]);
    }
})();
"""

# Canvas fingerprint noise injection — adds subtle random noise to canvas operations
# Prevents cross-session canvas fingerprint correlation
_STEALTH_CANVAS_NOISE = """\
(function() {
    const _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    const _origToBlob = HTMLCanvasElement.prototype.toBlob;
    const _origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    // Session-stable seed (constant for this page load)
    const _seed = Math.floor(Math.random() * 2147483647) || 1;
    // Deterministic hash: mulberry32
    function _hash(x) {
        x = Math.imul(x ^ (x >>> 16), 0x45d9f3b);
        x = Math.imul(x ^ (x >>> 13), 0x45d9f3b);
        return (x ^ (x >>> 16)) >>> 0;
    }
    // Deterministic noise: same pixel index always gets same noise value
    function _addNoise(img) {
        const len = img.data.length;
        for (let i = 0; i < len; i += 4) {
            const h = _hash(_seed + (i >> 2));
            img.data[i]     ^= h & 1;        // R: flip LSB based on hash bit 0
            img.data[i + 1] ^= (h >> 1) & 1; // G: flip LSB based on hash bit 1
        }
    }
    function _cloneCanvas(canvas) {
        const clone = document.createElement('canvas');
        clone.width = canvas.width;
        clone.height = canvas.height;
        const cloneCtx = clone.getContext('2d');
        if (!cloneCtx) return null;
        cloneCtx.drawImage(canvas, 0, 0);
        return { canvas: clone, ctx: cloneCtx };
    }
    HTMLCanvasElement.prototype.toDataURL = function() {
        if (!this.width || !this.height) return _origToDataURL.apply(this, arguments);
        try {
            const cloned = _cloneCanvas(this);
            if (!cloned) return _origToDataURL.apply(this, arguments);
            const img = _origGetImageData.call(cloned.ctx, 0, 0, cloned.canvas.width, cloned.canvas.height);
            _addNoise(img);
            cloned.ctx.putImageData(img, 0, 0);
            return _origToDataURL.apply(cloned.canvas, arguments);
        } catch (e) {
            return _origToDataURL.apply(this, arguments);
        }
    };
    HTMLCanvasElement.prototype.toBlob = function(cb, type, quality) {
        if (!this.width || !this.height) return _origToBlob.call(this, cb, type, quality);
        try {
            const cloned = _cloneCanvas(this);
            if (!cloned) return _origToBlob.call(this, cb, type, quality);
            const img = _origGetImageData.call(cloned.ctx, 0, 0, cloned.canvas.width, cloned.canvas.height);
            _addNoise(img);
            cloned.ctx.putImageData(img, 0, 0);
            return _origToBlob.call(cloned.canvas, cb, type, quality);
        } catch (e) {
            return _origToBlob.call(this, cb, type, quality);
        }
    };
    CanvasRenderingContext2D.prototype.getImageData = function() {
        const img = _origGetImageData.apply(this, arguments);
        _addNoise(img);
        return img;
    };
    Object.defineProperty(HTMLCanvasElement.prototype.toDataURL, 'toString', {value: () => 'function toDataURL() { [native code] }', configurable: false});
    Object.defineProperty(HTMLCanvasElement.prototype.toBlob, 'toString', {value: () => 'function toBlob() { [native code] }', configurable: false});
    Object.defineProperty(CanvasRenderingContext2D.prototype.getImageData, 'toString', {value: () => 'function getImageData() { [native code] }', configurable: false});
})();
"""

# AudioContext fingerprint noise injection — prevents audio fingerprint correlation
# Detection vector: OfflineAudioContext.startRendering() → Float32Array hash (creepjs, FingerprintJS)
_STEALTH_AUDIO_NOISE = """\
(function() {
    // Spoof static AudioContext properties to common values
    if (typeof AudioContext !== 'undefined') {
        const _origAudioCtx = AudioContext;
        window.AudioContext = function() {
            const ctx = new _origAudioCtx(...arguments);
            try {
                Object.defineProperty(ctx, 'sampleRate', {value: 44100, writable: false, configurable: false});
                if (ctx.destination) {
                    Object.defineProperty(ctx.destination, 'maxChannelCount', {value: 2, writable: false, configurable: false});
                }
            } catch(e) {}
            return ctx;
        };
        window.AudioContext.prototype = _origAudioCtx.prototype;
        Object.defineProperty(window, 'AudioContext', {writable: false, configurable: false});
    }
    // Deterministic noise seed (consistent within session, different across sessions)
    const _seed = Math.random() * 1000;
    function _noise(i) {
        const x = Math.sin(_seed + i) * 10000;
        return (x - Math.floor(x)) * 0.0001;
    }
    // Noise injection into OfflineAudioContext.startRendering results
    if (typeof OfflineAudioContext !== 'undefined') {
        const _origStartRendering = OfflineAudioContext.prototype.startRendering;
        OfflineAudioContext.prototype.startRendering = function() {
            return _origStartRendering.apply(this, arguments).then(function(audioBuffer) {
                try {
                    for (let ch = 0; ch < audioBuffer.numberOfChannels; ch++) {
                        const samples = audioBuffer.getChannelData(ch);
                        for (let i = 0; i < samples.length; i++) {
                            samples[i] += _noise(i + ch);
                        }
                    }
                } catch(e) {}
                return audioBuffer;
            });
        };
    }
    // Noise injection into AnalyserNode frequency/time data
    if (typeof AnalyserNode !== 'undefined') {
        const _origGetFloat = AnalyserNode.prototype.getFloatFrequencyData;
        const _origGetByte = AnalyserNode.prototype.getByteFrequencyData;
        AnalyserNode.prototype.getFloatFrequencyData = function(arr) {
            _origGetFloat.call(this, arr);
            for (let i = 0; i < arr.length; i++) {
                arr[i] += _noise(i);
            }
        };
        AnalyserNode.prototype.getByteFrequencyData = function(arr) {
            _origGetByte.call(this, arr);
            for (let i = 0; i < arr.length; i++) {
                arr[i] = Math.max(0, Math.min(255, arr[i] + ((_noise(i) > 0.00005) ? 1 : -1)));
            }
        };
        Object.defineProperty(AnalyserNode.prototype.getFloatFrequencyData, 'toString', {value: () => 'function getFloatFrequencyData() { [native code] }', configurable: false});
        Object.defineProperty(AnalyserNode.prototype.getByteFrequencyData, 'toString', {value: () => 'function getByteFrequencyData() { [native code] }', configurable: false});
    }
    // Patch AudioBuffer.getChannelData (second primary audio fingerprint vector)
    // Uses WeakSet instead of property flag to avoid detection via Object.keys/hasOwnProperty
    if (typeof AudioBuffer !== 'undefined') {
        const _noisedBuffers = new WeakSet();
        const _origGetChannel = AudioBuffer.prototype.getChannelData;
        AudioBuffer.prototype.getChannelData = function(channel) {
            const data = _origGetChannel.call(this, channel);
            if (!_noisedBuffers.has(this)) {
                for (let i = 0; i < data.length; i += 100) {
                    data[i] += _noise(i + channel);
                }
                _noisedBuffers.add(this);
            }
            return data;
        };
        Object.defineProperty(AudioBuffer.prototype.getChannelData, 'toString', {value: () => 'function getChannelData() { [native code] }', configurable: false});
    }
})();
"""
_stealth_cleanup_task: asyncio.Task[None] | None = None

# Cookie persistence directory
_COOKIE_DIR = os.path.expanduser("~/.config/bridge/browser_cookies")

_BROWSER_FINGERPRINT_SNAPSHOT_SCRIPT = """() => {
    const snapshot = {
        userAgent: navigator.userAgent,
        userAgentDataPresent: typeof navigator.userAgentData !== 'undefined' && !!navigator.userAgentData,
        userAgentDataBrands: [],
        platform: navigator.platform,
        vendor: navigator.vendor,
        vendorSub: navigator.vendorSub,
        productSub: navigator.productSub,
        language: navigator.language,
        languages: Array.isArray(navigator.languages) ? Array.from(navigator.languages) : [],
        hardwareConcurrency: navigator.hardwareConcurrency ?? null,
        deviceMemory: navigator.deviceMemory ?? null,
        webdriver: navigator.webdriver,
        cookieEnabled: navigator.cookieEnabled,
        doNotTrack: navigator.doNotTrack ?? null,
        globalPrivacyControl: navigator.globalPrivacyControl ?? null,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        screen: {
            width: screen.width,
            height: screen.height,
            availWidth: screen.availWidth,
            availHeight: screen.availHeight,
            colorDepth: screen.colorDepth,
            pixelDepth: screen.pixelDepth,
        },
        viewport: {
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            devicePixelRatio: window.devicePixelRatio,
        },
        storage: {
            localStorage: typeof window.localStorage !== 'undefined',
            sessionStorage: typeof window.sessionStorage !== 'undefined',
            indexedDB: typeof window.indexedDB !== 'undefined',
            serviceWorker: typeof navigator.serviceWorker !== 'undefined',
        },
        webgl: {
            vendor: null,
            renderer: null,
        },
    };

    try {
        if (snapshot.userAgentDataPresent && navigator.userAgentData.brands) {
            snapshot.userAgentDataBrands = navigator.userAgentData.brands.map((brand) => ({
                brand: brand.brand,
                version: brand.version,
            }));
        }
    } catch (e) {}

    try {
        snapshot.oscpu = navigator.oscpu ?? null;
    } catch (e) {
        snapshot.oscpu = null;
    }

    try {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        if (gl) {
            const dbg = gl.getExtension('WEBGL_debug_renderer_info');
            if (dbg) {
                snapshot.webgl.vendor = gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL);
                snapshot.webgl.renderer = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL);
            }
        }
    } catch (e) {}

    return snapshot;
}"""


def _get_stealth_session(session_id: str) -> StealthSession | None:
    """Get stealth session by ID and update last_used timestamp."""
    session = _stealth_sessions.get(session_id)
    if session:
        session.last_used = time.time()
    return session


def _drop_unified_stealth_sessions(engine_session_id: str) -> list[str]:
    """Remove unified sessions that reference a closed stealth session."""
    removed: list[str] = []
    for sid, info in list(_unified_sessions.items()):
        if info.get("engine") == "stealth" and info.get("engine_session_id") == engine_session_id:
            _unified_sessions.pop(sid, None)
            removed.append(sid)
    return removed


def _prune_orphaned_unified_stealth_sessions(session_id: str | None = None) -> list[str]:
    """Remove unified stealth wrappers whose backing stealth session is already gone."""
    removed: list[str] = []
    for sid, info in list(_unified_sessions.items()):
        if session_id is not None and sid != session_id:
            continue
        if info.get("engine") != "stealth":
            continue
        engine_session_id = str(info.get("engine_session_id", "") or "")
        if not engine_session_id or engine_session_id not in _stealth_sessions:
            _unified_sessions.pop(sid, None)
            removed.append(sid)
    return removed


async def _close_stealth_runtime(session: StealthSession) -> list[str]:
    """Best-effort teardown of stealth browser resources."""
    errors: list[str] = []
    for label, closer in (
        ("browser.close", session.browser.close),
        ("playwright.stop", session.pw_context.stop),
    ):
        try:
            await closer()
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    return errors


def _stealth_ua_is_firefox_like(user_agent: str) -> bool:
    """Return True when the declared UA asks for a Firefox/Tor-like JS identity."""
    return "firefox/" in (user_agent or "").lower()


def _stealth_scripts_for_session(*, is_proxy: bool, firefox_like: bool = False) -> list[str]:
    """Return the JS spoof scripts that define a session's browser footprint.

    P0 Fingerprint-Haertung: WebGL/Canvas/Audio/Headless-Fix werden IMMER geladen
    (nicht nur bei Proxy), damit creepjs-Score auch ohne Proxy < 20% bleibt.
    """
    scripts = [
        _STEALTH_MEMORY_SPOOF,
        _STEALTH_HARDWARE_SPOOF,
        _STEALTH_HEADLESS_FIX,         # window.chrome + plugins + connection.rtt + Notification
        _STEALTH_WEBGL_SPOOF,          # Intel Iris GPU spoofing
        _STEALTH_CANVAS_NOISE,         # Canvas fingerprint noise
        _STEALTH_AUDIO_NOISE,          # AudioContext spoofing
        _STEALTH_PERMISSION_MEDIA_SPOOF,
    ]
    if firefox_like:
        scripts.append(_STEALTH_FIREFOX_LIKE_POPUP_NAV)
    if is_proxy:
        scripts.append(_STEALTH_WEBRTC_KILL)
    return scripts


async def _install_stealth_worker_route(context: Any) -> None:
    """Strip Chromium-only request hints and inject spoofing into worker scripts."""

    async def _handler(route: Any, request: Any) -> None:
        raw_headers: dict[str, Any] | None = None
        if hasattr(request, "all_headers"):
            try:
                raw_headers = await request.all_headers()
            except Exception:
                raw_headers = None
        if raw_headers is None:
            raw_headers = getattr(request, "headers", {}) or {}
        headers = {str(key).lower(): value for key, value in raw_headers.items()}
        forwarded_headers = {
            key: value
            for key, value in headers.items()
            if key not in _STEALTH_FIREFOX_LIKE_STRIPPED_HEADERS
        }
        destination = str(headers.get("sec-fetch-dest", "")).lower()
        resource_type = str(getattr(request, "resource_type", "") or "").lower()
        accept = str(headers.get("accept", "")).lower()
        # Chromium worker script fetches can arrive with an empty sec-fetch-dest
        # while still carrying a normal User-Agent header, so header absence is
        # not a safe discriminator here.
        looks_like_worker_script = (
            resource_type == "script"
            and accept == "*/*"
            and destination in {"", "worker", "sharedworker"}
        )
        if not looks_like_worker_script:
            if forwarded_headers != headers:
                await route.continue_(headers=forwarded_headers)
            else:
                await route.continue_()
            return

        response = await route.fetch(headers=forwarded_headers)
        body = await response.text()
        response_headers = dict(getattr(response, "headers", {}) or {})
        response_headers.pop("content-length", None)
        response_headers.pop("Content-Length", None)
        await route.fulfill(
            response=response,
            body=f"{_STEALTH_WORKER_NAVIGATOR_SPOOF}\n{body}",
            headers=response_headers,
        )

    await context.route("**/*", _handler)


async def _stealth_apply_page_cdp_profile(page: Any, *, user_agent: str, accept_lang: str, firefox_like: bool) -> None:
    """Apply per-page UA/platform overrides to the current document target."""
    context = getattr(page, "context", None)
    if callable(context):
        context = context()
    if context is None or not hasattr(context, "new_cdp_session"):
        return
    cdp = await context.new_cdp_session(page)
    await cdp.send("Emulation.setUserAgentOverride", {
        "userAgent": user_agent,
        "acceptLanguage": accept_lang,
        "platform": "Win32" if firefox_like else "Linux x86_64",
    })


def _detect_bot_protection(html: str, headers: dict[str, str]) -> str | None:
    """Detect common bot-protection vendors from HTML and response headers."""
    html_lower = (html or "").lower()
    headers_lower = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    header_values = tuple(headers_lower.values())
    detectors: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("cloudflare", ("cf-browser-verification", "cf_clearance", "cloudflare", "__cf_bm", "cf-ray", "challenge-platform")),
        ("datadome", ("datadome", "dd_cookie_test")),
        ("perimeterx", ("px-captcha", "_px", "perimeterx", "human-challenge")),
        ("akamai", ("akamai", "_abck", "bm_sz")),
        ("imperva", ("incapsula", "visid_incap", "___utmvc")),
    )
    for vendor, indicators in detectors:
        for indicator in indicators:
            if indicator in html_lower or any(indicator in value for value in header_values):
                return vendor
    return None


def _is_bot_challenge_page(html: str) -> bool:
    """Detect common bot-challenge page markers."""
    html_lower = (html or "").lower()
    indicators = (
        "checking your browser",
        "just a moment",
        "please wait",
        "verify you are human",
        "security check",
        "ddos protection",
        "ray id",
        "cf-browser-verification",
        "challenge-running",
    )
    return any(indicator in html_lower for indicator in indicators)


async def _stealth_save_cookies(session: StealthSession) -> None:
    """Save cookies from browser context to disk."""
    if not session.profile:
        return
    try:
        context = session.page.context
        cookies = await context.cookies()
        if not cookies:
            return
        # Filter expired cookies
        now = time.time()
        valid = [c for c in cookies if c.get("expires", -1) == -1 or c.get("expires", 0) > now]
        os.makedirs(_COOKIE_DIR, mode=0o700, exist_ok=True)
        path = os.path.join(_COOKIE_DIR, f"{session.profile}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(valid, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        log.info("Cookies saved for profile %s: %d cookies", session.profile, len(valid))
    except Exception as exc:
        log.warning("Failed to save cookies for profile %s: %s", session.profile, exc)


async def _stealth_load_cookies(session: StealthSession) -> None:
    """Load cookies from disk into browser context."""
    if not session.profile:
        return
    path = os.path.join(_COOKIE_DIR, f"{session.profile}.json")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        if not isinstance(cookies, list) or not cookies:
            return
        # Filter expired cookies
        now = time.time()
        valid = [c for c in cookies if c.get("expires", -1) == -1 or c.get("expires", 0) > now]
        if valid:
            context = session.page.context
            await context.add_cookies(valid)
            log.info("Cookies loaded for profile %s: %d cookies", session.profile, len(valid))
    except Exception as exc:
        log.warning("Failed to load cookies for profile %s: %s", session.profile, exc)


async def _stealth_cleanup_loop() -> None:
    """Background task: close idle stealth sessions every 60s, auto-save cookies."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        # Auto-save cookies for active sessions
        for session in list(_stealth_sessions.values()):
            if session.profile:
                try:
                    await _stealth_save_cookies(session)
                except Exception as exc:
                    log.warning("Cookie save failed for session %s: %s", session.session_id, exc)
        # Close idle sessions
        expired = [
            sid for sid, s in _stealth_sessions.items()
            if now - s.last_used > _STEALTH_IDLE_TIMEOUT
        ]
        for sid in expired:
            try:
                session = _stealth_sessions.pop(sid)
                dropped = _drop_unified_stealth_sessions(sid)
                errors: list[str] = []
                try:
                    await _stealth_save_cookies(session)
                except Exception as exc:
                    errors.append(f"cookie_save: {exc}")
                errors.extend(await _close_stealth_runtime(session))
                if errors:
                    log.warning("Stealth cleanup error for session %s: %s", sid, "; ".join(errors))
                else:
                    log.info("Stealth session %s auto-closed (idle >%ds)", sid, _STEALTH_IDLE_TIMEOUT)
                if dropped:
                    log.info("Pruned unified sessions after stealth auto-close: %s", ", ".join(sorted(dropped)))
            except Exception as exc:
                log.warning("Stealth cleanup error for session %s: %s", sid, exc)


def _get_http() -> httpx.AsyncClient:
    """Lazy-init shared async HTTP client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(base_url=BRIDGE_HTTP, timeout=10.0)
    return _http_client


def _auth_headers(*, include_register_token: bool = False) -> dict[str, str]:
    global _session_token
    headers: dict[str, str] = {}
    session_token = str(_session_token or "").strip()
    if not session_token:
        workspace = (
            str(os.environ.get("BRIDGE_CLI_WORKSPACE", "")).strip()
            or str(os.environ.get("BRIDGE_CLI_HOME_DIR", "")).strip()
        )
        session_token = load_bridge_agent_session_token(
            workspace,
            agent_id=str(_agent_id or "").strip(),
        )
        if session_token:
            _session_token = session_token
            log.info("Recovered persisted session token for %s", _agent_id or "<unknown>")
    if session_token:
        headers["X-Bridge-Token"] = session_token
    if include_register_token:
        register_token = _load_bridge_register_token()
        if register_token:
            headers["X-Bridge-Register-Token"] = register_token
    return headers


def _exc_message(exc: Exception) -> str:
    """Return a stable non-empty error message for MCP tool responses."""
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__


_TRANSPORT_RETRY_ERRORS = (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError)


async def _bridge_request(method: str, path: str, *, include_register_token: bool = False, **kwargs: Any) -> httpx.Response:
    """Unified HTTP helper with 1 retry on transport errors (connection reset after server restart)."""
    global _http_client
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(_auth_headers(include_register_token=include_register_token))
    for attempt in range(2):
        client = _get_http()
        try:
            resp = await getattr(client, method)(path, headers=headers or None, **kwargs)
            resp.raise_for_status()
            return resp
        except _TRANSPORT_RETRY_ERRORS:
            if attempt == 0:
                log.warning("Transport error on %s %s — resetting client and retrying", method.upper(), path)
                if _http_client is not None:
                    await _http_client.aclose()
                    _http_client = None
            else:
                raise
    raise httpx.ConnectError(f"unreachable after retry: {method.upper()} {path}")  # should not reach


async def _bridge_get(path: str, **kwargs: Any) -> httpx.Response:
    return await _bridge_request("get", path, **kwargs)


async def _bridge_post(path: str, *, include_register_token: bool = False, **kwargs: Any) -> httpx.Response:
    return await _bridge_request("post", path, include_register_token=include_register_token, **kwargs)


async def _bridge_put(path: str, **kwargs: Any) -> httpx.Response:
    return await _bridge_request("put", path, **kwargs)


async def _bridge_delete(path: str, **kwargs: Any) -> httpx.Response:
    return await _bridge_request("delete", path, **kwargs)


async def _bridge_patch(path: str, **kwargs: Any) -> httpx.Response:
    return await _bridge_request("patch", path, **kwargs)


def _check_management_level(agent_id: str) -> bool:
    """Check if agent is management-level (level <= 1 and active) in team.json."""
    team_json_path = os.path.join(os.path.dirname(__file__), "team.json")
    try:
        with open(team_json_path, "r") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Cannot read team.json for management check: %s", exc)
        return False
    for agent in config.get("agents", []):
        if agent.get("id") == agent_id:
            return agent.get("level", 99) <= 1 and agent.get("active", True)
    return False


def _message_targets_agent(msg: dict[str, Any], agent_id: str | None) -> bool:
    """Return True if msg should be buffered for agent_id."""
    if not agent_id:
        return False
    to = msg.get("to", "")
    sender = msg.get("from", "")
    if sender == agent_id:
        return False
    if to == agent_id or to == "all":
        return True
    if to == "all_managers" and _is_management_agent:
        return True
    return False


def _select_recoverable_history_messages(
    history_msgs: list[dict[str, Any]],
    agent_id: str | None,
    last_seen_msg_id: int,
) -> tuple[list[dict[str, Any]], int]:
    """Select unseen history messages to buffer after reconnect/startup.

    The server sends recent history on subscribe. We need to:
    1. recover messages newer than last_seen that were missed while disconnected
    2. avoid duplicating already-seen messages
    3. still advance last_seen to the highest valid ID in history
    """
    recoverable: list[dict[str, Any]] = []
    new_last_seen = last_seen_msg_id

    for msg in history_msgs:
        raw_id = msg.get("id")
        try:
            msg_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        if msg_id > new_last_seen:
            new_last_seen = msg_id

        if msg_id <= last_seen_msg_id:
            continue

        if _message_targets_agent(msg, agent_id):
            recoverable.append(msg)

    return recoverable, new_last_seen


def _normalize_last_seen_for_possible_server_restart(
    max_observed_id: int,
    last_seen_msg_id: int,
    *,
    source: str,
) -> int:
    """Reset last_seen when the server likely restarted and message IDs reset."""
    if last_seen_msg_id > 0 and max_observed_id > 0 and max_observed_id < last_seen_msg_id // 2:
        log.warning(
            "Server restart detected via %s: max_id=%d << last_seen=%d — resetting",
            source,
            max_observed_id,
            last_seen_msg_id,
        )
        return -1
    return last_seen_msg_id


# ---------------------------------------------------------------------------
# Background: WebSocket listener
# ---------------------------------------------------------------------------

async def _ws_listener() -> None:
    """Connect to Bridge WebSocket and buffer incoming messages.

    Uses _last_seen_msg_id to avoid buffering duplicate messages after reconnect.
    The server sends history (last 100 messages) on subscribe — without ID tracking,
    these would be re-delivered to the agent as "new" messages.
    """
    global _last_seen_msg_id
    try:
        import websockets
    except ImportError:
        log.error("websockets library not installed — WS push disabled")
        return

    while True:
        try:
            # S7: Include session token in WS URL for authentication
            ws_url = BRIDGE_WS
            if _session_token:
                ws_url = f"{BRIDGE_WS}?token={_session_token}"
            async with websockets.connect(
                ws_url,
                max_size=10 * 1024 * 1024,
            ) as ws:
                log.info("WebSocket connected to %s (authenticated=%s)", BRIDGE_WS, bool(_session_token))
                # Subscribe to get history
                await ws.send(json.dumps({"type": "subscribe"}))

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue

                    event_type = data.get("type", "")

                    if event_type == "history":
                        # On reconnect/startup, server sends recent history.
                        # Recover unseen messages (> last_seen) that target this agent,
                        # then advance last_seen to suppress duplicates.
                        history_msgs = data.get("messages", [])
                        if history_msgs:
                            try:
                                max_hist_id = max(
                                    (int(m.get("id", 0)) for m in history_msgs if m.get("id") is not None),
                                    default=0,
                                )
                            except (ValueError, TypeError):
                                max_hist_id = 0
                            _last_seen_msg_id = _normalize_last_seen_for_possible_server_restart(
                                max_hist_id,
                                _last_seen_msg_id,
                                source="history",
                            )
                            recoverable, new_last_seen = _select_recoverable_history_messages(
                                history_msgs=history_msgs,
                                agent_id=_agent_id,
                                last_seen_msg_id=_last_seen_msg_id,
                            )
                            if recoverable:
                                async with _buffer_lock:
                                    _message_buffer.extend(recoverable)
                                log.info("Recovered %d missed message(s) from history", len(recoverable))
                            if new_last_seen > _last_seen_msg_id:
                                _last_seen_msg_id = new_last_seen
                                log.info("History sync: updated last_seen_msg_id to %d", _last_seen_msg_id)
                        continue

                    if event_type == "message":
                        msg = data.get("message", {})
                        msg_id = msg.get("id")
                        # S3-F2 FIX: Safe int parse — invalid IDs skip instead of crash
                        try:
                            msg_id_int = int(msg_id) if msg_id is not None else None
                        except (ValueError, TypeError):
                            log.warning("Invalid msg_id=%r — skipping", msg_id)
                            continue
                        # Skip messages we've already seen (dedup after reconnect)
                        if msg_id_int is not None and msg_id_int <= _last_seen_msg_id:
                            continue

                        # Update tracking
                        if msg_id_int is not None:
                            _last_seen_msg_id = max(_last_seen_msg_id, msg_id_int)

                        # Only buffer messages addressed to us or broadcast
                        # Filter out own broadcasts (Bug #33)
                        if _message_targets_agent(msg, _agent_id):
                            async with _buffer_lock:
                                _message_buffer.append(msg)

                    # Ignore other event types (activity, runtime, etc.)

        except Exception as exc:
            exc_str = str(exc)
            # S3-F3 FIX: Mask token in log output to prevent leaks
            safe_exc = exc_str
            if _session_token and _session_token in safe_exc:
                safe_exc = safe_exc.replace(_session_token, "***TOKEN***")
            # Auto-re-register when server rejects our token (e.g. after server restart)
            if "4001" in exc_str or "unauthorized" in exc_str.lower():
                log.warning("WebSocket token rejected — auto-re-registering %s", _agent_id)
                await _auto_reregister()
            else:
                log.warning("WebSocket disconnected: %s — reconnecting in %ds", safe_exc, WS_RECONNECT_DELAY)
            await asyncio.sleep(WS_RECONNECT_DELAY)


async def _auto_reregister() -> bool:
    """Re-register with the Bridge server to get a fresh session token.

    Called automatically when the WebSocket connection is rejected due to an
    invalid token (e.g. after server restart).  Returns True on success.

    Hardening: Sends session_nonce (same as original registration) and
    context_lost=false to signal this is a token refresh, NOT a new session.
    Also preserves role and capabilities (C2/C6 fix).
    S3-F5 FIX: Serialized with _reregister_lock to prevent parallel re-registration.
    """
    global _session_token
    if not _agent_id:
        return False
    async with _reregister_lock:
        # BUG-6 FIX: After acquiring lock, verify re-registration is still needed.
        # Another coroutine may have already refreshed the token while we waited.
        try:
            pre_check = await _bridge_post("/heartbeat", json=_heartbeat_payload())
            if pre_check.status_code == 200:
                hb = pre_check.json()
                if hb.get("registered") is not False:
                    log.info("Auto-re-register skipped: token already valid (refreshed by another coroutine)")
                    return True
        except Exception:
            pass  # Heartbeat failed — proceed with re-registration
        try:
            register_payload: dict[str, Any] = {
                "agent_id": _agent_id,
                "role": _registered_role,
                "capabilities": _registered_capabilities,
                "session_nonce": _session_nonce,
                "context_lost": False,
            }
            register_payload.update(_cli_identity_payload_from_env(transport_source="cli_reregister"))
            resp = await _bridge_post(
                "/register",
                include_register_token=True,
                json=register_payload,
            )
            resp.raise_for_status()
            result = resp.json()
            new_token = result.get("session_token")
            if new_token:
                _session_token = new_token
                _persist_agent_session_token_for_helpers()
                log.info("Auto-re-registered: fresh token for %s (nonce preserved, no context restore)", _agent_id)
                return True
        except Exception as exc:
            log.warning("Auto-re-registration failed: %s", exc)
    return False


# ---------------------------------------------------------------------------
# Background: Heartbeat
# ---------------------------------------------------------------------------

async def _heartbeat_loop() -> None:
    """Send heartbeat every HEARTBEAT_INTERVAL seconds."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        if _agent_id is None:
            continue
        try:
            await _send_heartbeat_once(auto_reregister=True)
        except Exception as exc:
            log.warning("Heartbeat failed: %s", exc)


# ---------------------------------------------------------------------------
# Start background tasks
# ---------------------------------------------------------------------------

def _ensure_background_tasks() -> None:
    """Start WS listener and heartbeat if not already running."""
    global _ws_task, _heartbeat_task

    loop = asyncio.get_running_loop()

    if _ws_task is None or _ws_task.done():
        _ws_task = loop.create_task(_ws_listener())

    if _heartbeat_task is None or _heartbeat_task.done():
        _heartbeat_task = loop.create_task(_heartbeat_loop())


# ---------------------------------------------------------------------------
# BUG-7 FIX: Cleanup on process exit — prevent orphan background tasks
# ---------------------------------------------------------------------------

def _cleanup_background_tasks() -> None:
    """Cancel background tasks and close HTTP client on exit."""
    global _ws_task, _heartbeat_task, _http_client
    for task in (_ws_task, _heartbeat_task):
        if task is not None and not task.done():
            task.cancel()
    _ws_task = None
    _heartbeat_task = None
    if _http_client is not None:
        try:
            asyncio.get_event_loop().run_until_complete(_http_client.aclose())
        except Exception:
            pass
        _http_client = None


def _signal_exit(signum: int, _frame: Any) -> None:
    """Handle SIGTERM/SIGINT by cleaning up and exiting."""
    _cleanup_background_tasks()
    sys.exit(0)


signal.signal(signal.SIGTERM, _signal_exit)
signal.signal(signal.SIGINT, _signal_exit)
atexit.register(_cleanup_background_tasks)


async def _auto_register_from_cli_identity() -> bool:
    """Bootstrap registration from CLI identity env when tools are called too early.

    This keeps persistent CLI agents from falling into an unregistered loop where
    bridge_receive() appears to work (empty buffer) but no heartbeats ever start.
    """
    agent_id = str(_agent_id or os.environ.get("BRIDGE_CLI_AGENT_ID", "")).strip()
    if not agent_id:
        return False
    try:
        raw = await bridge_register(
            agent_id,
            role=_registered_role,
            capabilities=list(_registered_capabilities) or None,
        )
        data = json.loads(raw)
    except Exception as exc:
        log.warning("Auto-bootstrap register failed for %s: %s", agent_id, exc)
        return False
    return bool(data.get("ok"))


async def _bridge_receive_server_fallback(limit: int = 50) -> list[dict[str, Any]]:
    """Fetch unread messages once via HTTP when the WS buffer is empty.

    This restores a truthful liveness signal through `/receive/{agent_id}` and
    recovers from startup races where the WS subscription is not ready yet.
    """
    global _last_seen_msg_id
    if _agent_id is None:
        return []
    # P0-FIX: Do NOT send after_id — it conflicts with the server-side cursor.
    # The WS listener advances _last_seen_msg_id independently, which caused
    # the HTTP fallback to filter out ALL cursor-based unread messages.
    # MCP-side dedup via _last_seen_msg_id (below) handles duplicates.
    params: dict[str, Any] = {"wait": 0, "limit": limit, "fresh_only": 1}
    try:
        resp = await _bridge_get(
            f"/receive/{_agent_id}",
            params=params,
            headers={"X-Bridge-Client": "bridge_mcp"},
        )
    except Exception as exc:
        log.warning("bridge_receive fallback failed for %s: %s", _agent_id, exc)
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return []
    seen_before = _last_seen_msg_id
    max_seen = seen_before
    filtered: list[dict[str, Any]] = []
    for msg in messages:
        try:
            msg_id = int(msg.get("id"))
        except (TypeError, ValueError):
            filtered.append(msg)
            continue
        if msg_id > max_seen:
            max_seen = msg_id
    seen_before = _normalize_last_seen_for_possible_server_restart(
        max_seen,
        seen_before,
        source="receive_fallback",
    )
    for msg in messages:
        try:
            msg_id = int(msg.get("id"))
        except (TypeError, ValueError):
            continue
        if msg_id <= seen_before:
            continue
        filtered.append(msg)
    _last_seen_msg_id = max_seen
    return filtered


# ---------------------------------------------------------------------------
# MCP Server & Tools
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="bridge",
    instructions=(
        "Bridge communication tools for multi-agent coordination. "
        "Call bridge_register first to set your agent identity, "
        "then use other tools to communicate."
    ),
)


@mcp.tool(
    name="bridge_register",
    description=(
        "Register this agent with the Bridge server. "
        "Must be called once before using other bridge tools. "
        "Starts background WebSocket listener and automatic heartbeat."
    ),
)
async def bridge_register(
    agent_id: str,
    role: str = "",
    capabilities: list[str] | None = None,
) -> str:
    """Register agent and start background tasks."""
    global _agent_id, _session_token, _registered_once, _registered_role, _registered_capabilities

    caps = capabilities or ["code", "review", "communicate"]

    # Hardening: Detect context loss (re-registration from same MCP process = post-/compact)
    context_lost = _registered_once  # If we already registered, this is a re-register after /compact

    try:
        register_payload: dict[str, Any] = {
            "agent_id": agent_id,
            "role": role,
            "capabilities": caps,
            "session_nonce": _session_nonce,
            "context_lost": context_lost,
        }
        register_payload.update(_cli_identity_payload_from_env(transport_source="cli_register"))
        resp = await _bridge_post(
            "/register",
            include_register_token=True,
            json=register_payload,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as exc:
        return json.dumps({"error": str(exc)})

    _agent_id = agent_id
    # S5: Store session token for authenticated requests
    _session_token = result.get("session_token")
    if _session_token:
        _persist_agent_session_token_for_helpers()
        log.info("Session token received for agent %s", agent_id)

    # Hardening: Preserve identity for auto-re-registration (C2/C6 fix)
    _registered_once = True
    if role:
        _registered_role = role
    if caps:
        _registered_capabilities = list(caps)

    # Check if this agent is management-level (for all_managers routing)
    global _is_management_agent
    _is_management_agent = _check_management_level(agent_id)
    if _is_management_agent:
        log.info("Agent %s is management-level (receives all_managers messages)", agent_id)

    _ensure_background_tasks()

    return json.dumps(result)


@mcp.tool(
    name="bridge_send",
    description=(
        "Send a message to another agent or broadcast. "
        "The 'from' field is set automatically from your registration. "
        "Valid recipients: user, teamlead, claude_a, claude_b, all, team:<team_id>. "
        "Optional 'team' tags the message with a team context for filtered retrieval."
    ),
)
async def bridge_send(to: str, content: str, team: str | None = None) -> str:
    """Send a message via Bridge."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        payload: dict[str, Any] = {
            "from": _agent_id,
            "to": to,
            "content": content,
        }
        if team:
            payload["team"] = team
        resp = await _bridge_post(
            "/send",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        # Surface warning about unregistered recipients
        if "warning" in data:
            data["result_note"] = f"WARNING: {data['warning']}"
        return json.dumps(data)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_receive",
    description=(
        "Get buffered messages received via WebSocket push. "
        "Returns all messages since last call and clears the buffer. "
        "No polling needed — messages arrive automatically via WebSocket."
    ),
)
async def bridge_receive() -> str:
    """Return and clear buffered messages."""
    if _agent_id is None:
        ok = await _auto_register_from_cli_identity()
        if not ok:
            return json.dumps({"error": "Not registered. Call bridge_register first."})

    async with _buffer_lock:
        messages = list(_message_buffer)
        _message_buffer.clear()

    if not messages:
        messages = await _bridge_receive_server_fallback()

    return json.dumps({"count": len(messages), "messages": messages})


@mcp.tool(
    name="bridge_heartbeat",
    description=(
        "Manually send a heartbeat to the Bridge server. "
        "Note: Heartbeats are also sent automatically every 30 seconds."
    ),
)
async def bridge_heartbeat() -> str:
    """Manual heartbeat trigger."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        return json.dumps(await _send_heartbeat_once(auto_reregister=True))
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_activity",
    description=(
        "Report your current activity to the Bridge server. "
        "Use before file edits to coordinate with other agents."
    ),
)
async def bridge_activity(
    action: str,
    target: str = "",
    description: str = "",
) -> str:
    """Report agent activity."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        resp = await _bridge_post(
            "/activity",
            json={
                "agent_id": _agent_id,
                "action": action,
                "target": target,
                "description": description,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_check_activity",
    description="Get all current agent activities from the Bridge server.",
)
async def bridge_check_activity() -> str:
    """Check what other agents are doing."""
    try:
        resp = await _bridge_get("/activity")
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_history",
    description="Get message history from the Bridge server. Optional team filter returns only messages tagged with that team. Optional since= ISO timestamp filters to messages after that time (e.g. '2026-03-06T00:00:00').",
)
async def bridge_history(limit: int = 20, team: str | None = None, since: str | None = None) -> str:
    """Get message history."""
    try:
        params: dict[str, Any] = {"limit": limit}
        if team:
            params["team"] = team
        if since:
            params["since"] = since
        resp = await _bridge_get("/history", params=params)
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_health",
    description=(
        "Get comprehensive health status of all Bridge components. "
        "Returns status for server, websocket, agents, watcher, forwarder, and messages."
    ),
)
async def bridge_health() -> str:
    """Get system health check."""
    try:
        resp = await _bridge_get("/health")
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ===== STRUCTURED TASK PROTOCOL (Phase 3) =====


@mcp.tool(
    name="bridge_task_create",
    description=(
        "Create a structured task for an agent. "
        "Types: code_change, review, test, research, general, task. "
        "Requires title. Optionally assign to a specific agent. Returns task_id."
    ),
)
async def bridge_task_create(
    task_type: str,
    title: str,
    description: str,
    team: str = "",
    priority: int = 1,
    labels: list[str] | None = None,
    assigned_to: str = "",
    files: list[str] | None = None,
    ack_deadline_seconds: int = 120,
    max_retries: int = 2,
    idempotency_key: str = "",
    blocker_reason: str = "",
) -> str:
    """Create a new structured task. Set blocker_reason to mark the task as blocked."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    payload: dict[str, Any] = {"description": description}
    if files:
        payload["files"] = files
    body: dict[str, Any] = {
        "type": task_type,
        "title": title,
        "description": description,  # F-04: top-level description field
        "payload": payload,
        "created_by": _agent_id,
        "ack_deadline_seconds": ack_deadline_seconds,
        "max_retries": max_retries,
        "priority": priority,
    }
    if team:
        body["team"] = team
    if labels:
        body["labels"] = labels
    if assigned_to:
        body["assigned_to"] = assigned_to
    if idempotency_key:
        body["idempotency_key"] = idempotency_key
    if blocker_reason:
        body["blocker_reason"] = blocker_reason
    try:
        resp = await _bridge_post("/task/create", json=body)
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_task_claim",
    description="Claim a task (state: created → claimed). You become the assigned agent.",
)
async def bridge_task_claim(task_id: str) -> str:
    """Claim a task for execution."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_post(f"/task/{task_id}/claim", json={"agent_id": _agent_id})
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_task_ack",
    description="Acknowledge task start (state: claimed → acked). Confirms you are actively working on it.",
)
async def bridge_task_ack(task_id: str) -> str:
    """Acknowledge that you started working on a task."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_post(f"/task/{task_id}/ack", json={"agent_id": _agent_id})
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_task_done",
    description=(
        "Mark a task as done with result data (state: claimed/acked → done). "
        "result_code: success, partial, skipped, error, timeout. "
        "PFLICHT bei success/partial: result_summary + evidence_type + evidence_ref. "
        "evidence_type: test, log, screenshot, code, manual, review. "
        "evidence_ref: Konkreter Beleg (Testname, Log-Zeile, Screenshot-Pfad, etc.)."
    ),
)
async def bridge_task_done(
    task_id: str,
    result_summary: str = "",
    result_code: str = "success",
    evidence_type: str = "",
    evidence_ref: str = "",
) -> str:
    """Report task completion with evidence."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    evidence_type_norm = str(evidence_type or "").strip().lower()
    evidence_ref_norm = str(evidence_ref or "").strip()
    if bool(evidence_type_norm) ^ bool(evidence_ref_norm):
        return json.dumps(
            {
                "error": (
                    "evidence_type und evidence_ref muessen zusammen gesetzt werden, "
                    "damit ein gueltiges evidence-Objekt erstellt werden kann."
                )
            }
        )
    result = {"summary": result_summary} if result_summary else {}
    payload: dict = {
        "agent_id": _agent_id, "result": result,
        "result_code": result_code, "result_summary": result_summary,
    }
    if evidence_type_norm:
        payload["evidence"] = {"type": evidence_type_norm, "ref": evidence_ref_norm}
    try:
        resp = await _bridge_post(f"/task/{task_id}/done", json=payload)
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_task_fail",
    description="Mark a task as failed with error message (any active state → failed).",
)
async def bridge_task_fail(task_id: str, error: str = "unknown error") -> str:
    """Report task failure."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_post(f"/task/{task_id}/fail", json={"agent_id": _agent_id, "error": error})
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_task_queue",
    description=(
        "List tasks from the queue. Filter by state (created/claimed/acked/done/failed) "
        "and/or agent_id. Supports limit for bounded shared-queue reads. "
        "Returns tasks sorted by creation time."
    ),
)
async def bridge_task_queue(
    state: str = "",
    agent_id: str = "",
    team: str = "",
    limit: int = 0,
) -> str:
    """Get task queue, optionally filtered."""
    params = []
    if state:
        params.append(f"state={state}")
    if agent_id:
        params.append(f"agent_id={agent_id}")
    if team:
        params.append(f"team={team}")
    try:
        bounded_limit = int(limit)
    except (TypeError, ValueError):
        bounded_limit = 0
    if bounded_limit > 0:
        params.append(f"limit={bounded_limit}")
    query = f"?{'&'.join(params)}" if params else ""
    try:
        resp = await _bridge_get(f"/task/queue{query}")
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_task_get",
    description="Get details of a single task by ID.",
)
async def bridge_task_get(task_id: str) -> str:
    """Get single task details."""
    try:
        resp = await _bridge_get(f"/task/{task_id}")
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_task_update",
    description=(
        "Update an existing task. Can change title, priority, assigned_to, labels, team. "
        "Only allowed for assigned_to, created_by, or team-lead."
    ),
)
async def bridge_task_update(
    task_id: str,
    title: str = "",
    priority: int = 0,
    assigned_to: str = "",
    labels: list[str] | None = None,
    team: str = "",
    description: str = "",
    blocker_reason: str | None = None,
) -> str:
    """Update task fields via PATCH. Set blocker_reason to block a task, pass empty string to unblock."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    body: dict[str, Any] = {"requester": _agent_id}
    if title:
        body["title"] = title
    if description:
        body["description"] = description
    if priority:
        body["priority"] = priority
    if assigned_to:
        body["assigned_to"] = assigned_to
    if labels is not None:
        body["labels"] = labels
    if team:
        body["team"] = team
    # V4: blocker_reason — None=don't change, ""=clear, "reason"=set
    if blocker_reason is not None:
        body["blocker_reason"] = blocker_reason if blocker_reason else None
    try:
        resp = await _bridge_patch(f"/task/{task_id}", json=body)
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ===== END STRUCTURED TASK PROTOCOL =====


# ---------------------------------------------------------------------------
# V3 Scope-Lock Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_scope_lock",
    description=(
        "Acquire scope locks for file/directory paths before editing. "
        "Prevents other agents from modifying the same files. "
        "Locks expire after TTL (default 1800s = 30min). "
        "Returns conflict info if paths are already locked by another agent."
    ),
)
async def bridge_scope_lock(
    task_id: str,
    paths: list[str],
    lock_type: str = "file",
    ttl: int = 1800,
) -> str:
    """Acquire scope locks for paths tied to a task."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    body: dict[str, Any] = {
        "agent_id": _agent_id,
        "task_id": task_id,
        "paths": paths,
        "lock_type": lock_type,
        "ttl": ttl,
    }
    try:
        resp = await _bridge_post("/scope/lock", json=body)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_scope_unlock",
    description=(
        "Release scope locks for a task. "
        "If paths are specified, only those paths are unlocked. "
        "If no paths specified, all locks for the task are released."
    ),
)
async def bridge_scope_unlock(
    task_id: str,
    paths: list[str] | None = None,
) -> str:
    """Release scope locks for a task."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    body: dict[str, Any] = {
        "agent_id": _agent_id,
        "task_id": task_id,
    }
    if paths:
        body["paths"] = paths
    try:
        resp = await _bridge_post("/scope/unlock", json=body)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_scope_check",
    description=(
        "Check if file/directory paths are free to lock. "
        "Returns which paths are free and which are locked (with lock owner info)."
    ),
)
async def bridge_scope_check(paths: list[str]) -> str:
    """Check if paths are free to lock."""
    try:
        resp = await _bridge_get("/scope/check", params={"paths": ",".join(paths)})
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_scope_locks",
    description="List all currently active scope locks across all agents.",
)
async def bridge_scope_locks() -> str:
    """Get all active scope locks."""
    try:
        resp = await _bridge_get("/scope/locks")
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# V3 Whiteboard / Live-Board Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_whiteboard_post",
    description=(
        "Post or update an entry on the team whiteboard (Live-Board). "
        "Types: status, blocker, result, alert, escalation_response. "
        "Severity: info, warning, critical. "
        "Auto-upserts by agent_id + task_id + type."
    ),
)
async def bridge_whiteboard_post(
    type: str,
    content: str,
    task_id: str = "",
    scope_label: str = "",
    severity: str = "info",
    ttl: int = 3600,
    tags: list[str] | None = None,
) -> str:
    """Post or update a whiteboard entry."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    body: dict[str, Any] = {
        "agent_id": _agent_id,
        "type": type,
        "content": content,
        "severity": severity,
        "ttl": ttl,
    }
    if task_id:
        body["task_id"] = task_id
    if scope_label:
        body["scope_label"] = scope_label
    if tags:
        body["tags"] = tags
    try:
        resp = await _bridge_post("/whiteboard", json=body)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_whiteboard_read",
    description=(
        "Read entries from the team whiteboard (Live-Board). "
        "Filter by agent_id, type, severity, or limit. "
        "Use priority=3 to get only critical (Stufe 3) escalation alerts."
    ),
)
async def bridge_whiteboard_read(
    agent_id: str = "",
    type: str = "",
    severity: str = "",
    limit: int = 50,
    priority: int = 0,
) -> str:
    """Read whiteboard entries with optional filters."""
    params: dict[str, Any] = {"limit": limit}
    if agent_id:
        params["agent"] = agent_id
    if type:
        params["type"] = type
    if severity:
        params["severity"] = severity
    if priority:
        params["priority"] = priority
    try:
        resp = await _bridge_get("/whiteboard", params=params)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_whiteboard_delete",
    description="Delete a whiteboard entry by its ID.",
)
async def bridge_whiteboard_delete(entry_id: str) -> str:
    """Delete a whiteboard entry."""
    try:
        client = _get_http()
        headers = _auth_headers()
        resp = await client.delete(f"/whiteboard/{entry_id}", headers=headers or None)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# E1 Credential Store Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_credential_store",
    description=(
        "Store a credential (API key, token, password) securely. "
        "Encrypted at rest with Fernet. You can only read/delete credentials you created. "
        "Valid services: google, github, email, wallet, phone, custom."
    ),
)
async def bridge_credential_store(
    service: str,
    key: str,
    value: str,
) -> str:
    """Store an encrypted credential."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_post(
            f"/credentials/{service}/{key}",
            json={"value": value},
            headers={"X-Bridge-Agent": _agent_id},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_credential_get",
    description=(
        "Retrieve a stored credential by service and key. "
        "You can only access credentials you created (or management agents can access all). "
        "Valid services: google, github, email, wallet, phone, custom."
    ),
)
async def bridge_credential_get(
    service: str,
    key: str,
) -> str:
    """Retrieve a credential value."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_get(
            f"/credentials/{service}/{key}",
            headers={"X-Bridge-Agent": _agent_id},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_credential_delete",
    description=(
        "Delete a stored credential by service and key. "
        "You can only delete credentials you created (or management agents can delete all). "
        "Valid services: google, github, email, wallet, phone, custom."
    ),
)
async def bridge_credential_delete(
    service: str,
    key: str,
) -> str:
    """Delete a credential."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_delete(
            f"/credentials/{service}/{key}",
            headers={"X-Bridge-Agent": _agent_id},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_credential_list",
    description=(
        "List credential keys for a service. Only shows keys you have access to. "
        "Valid services: google, github, email, wallet, phone, custom."
    ),
)
async def bridge_credential_list(
    service: str,
) -> str:
    """List available credential keys for a service."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_get(
            f"/credentials/{service}",
            headers={"X-Bridge-Agent": _agent_id},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# V3 Task Check-in Tool
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_task_checkin",
    description=(
        "Send a heartbeat/check-in for a running task. "
        "Resets the task timeout timer and optionally updates a status note. "
        "Call this periodically while working on a long-running task to prevent timeout escalation."
    ),
)
async def bridge_task_checkin(
    task_id: str,
    note: str = "",
) -> str:
    """Check in on a running task to prevent timeout."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    body: dict[str, Any] = {"agent_id": _agent_id}
    if note:
        body["note"] = note
    try:
        resp = await _bridge_post(f"/task/{task_id}/checkin", json=body)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# V3 Escalation Tool
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_escalation_resolve",
    description=(
        "Resolve a Stage 3 escalation (Susi-Entscheidung). "
        "Actions: extend (give more time), reassign (assign to another agent), cancel (abort task). "
        "Only applicable when escalation has reached Stage 3."
    ),
)
async def bridge_escalation_resolve(
    task_id: str,
    action: str,
    reassign_to: str = "",
    extend_minutes: int = 30,
) -> str:
    """Resolve a Stage 3 escalation."""
    body: dict[str, Any] = {
        "action": action,
        "resolved_by": _agent_id or "unknown",
    }
    if action == "reassign" and reassign_to:
        body["reassign_to"] = reassign_to
    if action == "extend":
        body["extend_minutes"] = extend_minutes
    try:
        resp = await _bridge_post(f"/escalation/{task_id}/resolve", json=body)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_save_context",
    description=(
        "Save your current context summary and open tasks to the server. "
        "Call this after completing a task or before expected context loss. "
        "The saved state is automatically restored when you re-register."
    ),
)
async def bridge_save_context(
    summary: str,
    open_tasks: list[str] | None = None,
) -> str:
    """Explicitly save agent context to server-side state store."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    payload: dict[str, Any] = {"context_summary": summary}
    if open_tasks:
        payload["open_tasks"] = open_tasks
    try:
        resp = await _bridge_post(f"/state/{_agent_id}", json=payload)
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Approval Gate Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_approval_request",
    description=(
        "Request approval for a real-world action (email, phone call, etc.). "
        "Returns a request_id. The request is shown to the user in the Bridge UI. "
        "Use bridge_approval_check to poll for the decision. "
        "Allowed actions: email_send, email_delete, phone_call, smart_home, "
        "slack_send, whatsapp_send, file_delete, trade_execute, browser_login."
    ),
)
async def bridge_approval_request(
    action: str,
    target: str,
    description: str,
    risk_level: str = "low",
    payload: dict[str, Any] | None = None,
    timeout_seconds: int = 300,
) -> str:
    """Submit an approval request. Does NOT wait for the decision."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    body: dict[str, Any] = {
        "agent_id": _agent_id,
        "action": action,
        "target": target,
        "description": description,
        "risk_level": risk_level,
        "timeout_seconds": timeout_seconds,
    }
    if payload:
        body["payload"] = payload
    try:
        resp = await _bridge_post("/approval/request", json=body)
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_approval_check",
    description=(
        "Check the status of an approval request by its request_id. "
        "Returns: pending, approved, denied, or expired."
    ),
)
async def bridge_approval_check(request_id: str) -> str:
    """Poll the status of an approval request."""
    try:
        resp = await _bridge_get(f"/approval/{request_id}")
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_approval_wait",
    description=(
        "Wait for an approval decision. Polls every 5 seconds until the request "
        "is approved, denied, or expired. Returns the final status. "
        "Use this after bridge_approval_request to block until a decision is made."
    ),
)
async def bridge_approval_wait(
    request_id: str,
    poll_interval: int = 5,
    max_wait: int = 300,
) -> str:
    """Wait for an approval decision by polling."""
    elapsed = 0
    interval = max(2, min(poll_interval, 30))
    while elapsed < max_wait:
        try:
            resp = await _bridge_get(f"/approval/{request_id}")
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")
            if status in ("approved", "denied", "expired"):
                return json.dumps(data)
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        await asyncio.sleep(interval)
        elapsed += interval
    return json.dumps({"status": "timeout", "request_id": request_id, "waited_seconds": elapsed})


def _approval_owner_error(
    approval: dict[str, Any], request_id: str
) -> dict[str, Any] | None:
    """Reject execution when an approval belongs to another agent."""
    approval_agent_id = str(approval.get("agent_id", "")).strip()
    if approval_agent_id and approval_agent_id != _agent_id:
        return {
            "error": (
                f"Approval gehoert zu Agent '{approval_agent_id}', "
                f"nicht zu '{_agent_id}'."
            ),
            "request_id": request_id,
        }
    return None


# ---------------------------------------------------------------------------
# Email Backend: InboxAPI subprocess helper
# ---------------------------------------------------------------------------

_INBOXAPI_CMD = "inboxapi"


async def _inboxapi_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call an InboxAPI MCP tool via subprocess (stdio proxy).

    Starts `inboxapi proxy`, sends initialize + tools/call, returns result.
    Auth is handled automatically by the CLI (credentials in ~/.config/inboxapi/).
    """

    init_msg = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "bridge-mcp", "version": "1.0.0"},
        },
    })

    call_msg = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })

    stdin_data = f"{init_msg}\n{call_msg}\n"

    try:
        proc = await asyncio.create_subprocess_exec(
            _INBOXAPI_CMD, "proxy",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data.encode()),
            timeout=30.0,
        )

        # Parse response lines — find id=2 (tools/call response)
        for line in stdout.decode().strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
                if resp.get("id") == 2:
                    if "error" in resp:
                        return {"error": resp["error"].get("message", str(resp["error"])), "source": "inboxapi"}
                    result = resp.get("result", {})
                    # MCP tools/call returns {content: [{type, text}], isError}
                    content = result.get("content", [])
                    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                    return {
                        "ok": not result.get("isError", False),
                        "text": "\n".join(texts) if texts else str(result),
                    }
            except (json.JSONDecodeError, TypeError):
                continue

        return {"error": f"No valid response from InboxAPI. stderr: {stderr.decode()[:200]}", "source": "inboxapi"}

    except asyncio.TimeoutError:
        # Kill leaked subprocess
        try:
            proc.kill()  # type: ignore[possibly-undefined]
            await proc.wait()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        return {"error": "InboxAPI call timed out (30s)", "source": "inboxapi"}
    except FileNotFoundError:
        return {"error": "inboxapi CLI not found. Install: npm install -g @inboxapi/cli", "source": "inboxapi"}
    except Exception as exc:
        return {"error": f"InboxAPI call failed: {exc}", "source": "inboxapi"}


# ---------------------------------------------------------------------------
# Browser Automation Helpers (Playwright MCP stdio wrapper)
# ---------------------------------------------------------------------------

def _playwright_command() -> list[str]:
    """Resolve Playwright MCP command from env, .mcp.json config, or the central catalog."""
    if PLAYWRIGHT_MCP_COMMAND:
        parsed = shlex.split(PLAYWRIGHT_MCP_COMMAND)
        if parsed:
            return parsed

    candidate_paths = [
        os.path.join(os.getcwd(), ".mcp.json"),
        os.path.join(os.path.dirname(__file__), "..", ".mcp.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".mcp.json"),
    ]
    for raw_path in candidate_paths:
        path = os.path.abspath(raw_path)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            mcp_servers = data.get("mcpServers", {})
            playwright_cfg = mcp_servers.get("playwright", {})
            command = str(playwright_cfg.get("command", "")).strip()
            args = playwright_cfg.get("args", [])
            if command:
                arg_list = [str(a) for a in args] if isinstance(args, list) else []
                return [command, *arg_list]
        except Exception:
            continue

    # Fallback must stay aligned with the repository catalog.
    try:
        cfg = runtime_mcp_registry().get("playwright", {})
        command = str(cfg.get("command", "")).strip()
        args = cfg.get("args", [])
        if command:
            arg_list = [str(a) for a in args] if isinstance(args, list) else []
            return [command, *arg_list]
    except Exception:
        pass
    return ["npx", "@playwright/mcp@0.0.68"]


def _mcp_result_text(result: dict[str, Any]) -> str:
    content = result.get("content", [])
    if not isinstance(content, list):
        return ""
    texts = [str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text"]
    return "\n".join([t for t in texts if t]).strip()


def _extract_png_path(text: str) -> str:
    match = re.search(r"(/[^\s\"']+\.png)", text)
    return match.group(1) if match else ""


def _valid_http_url(url: str) -> bool:
    return bool(re.match(r"^https?://", (url or "").strip(), flags=re.IGNORECASE))


def _normalize_browser_risk_level(risk_level: str) -> str | None:
    normalized = (risk_level or "").strip().lower()
    if normalized in _BROWSER_ALLOWED_RISK_LEVELS:
        return normalized
    return None


async def _playwright_mcp_session(
    calls: list[tuple[str, dict[str, Any] | None]],
) -> list[dict[str, Any]]:
    """Send multiple JSON-RPC tool calls to ONE Playwright MCP subprocess.

    Uses interactive I/O (write→read per call) instead of communicate() to
    keep the browser alive across calls.  The MCP protocol requires:
      1. Send initialize request
      2. Read initialize response
      3. Send notifications/initialized
      4. Send tool calls sequentially (write request, read response)
      5. Close stdin → subprocess exits

    Returns a list of result dicts, one per call in *calls*, in the same order.
    """
    cmd = _playwright_command()
    if not cmd:
        return [{"error": "Playwright MCP not configured", "source": "browser"}] * len(calls)

    # Launch subprocess
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return [
            {"error": f"Playwright MCP command not found: {' '.join(cmd)}", "source": "browser", "tool": t}
            for t, _ in calls
        ]
    except Exception as exc:
        return [
            {"error": f"Could not start Playwright MCP: {exc}", "source": "browser", "tool": t}
            for t, _ in calls
        ]

    async def _write_json(obj: dict[str, Any]) -> None:
        proc.stdin.write((json.dumps(obj) + "\n").encode())  # type: ignore[union-attr]
        await proc.stdin.drain()  # type: ignore[union-attr]

    async def _read_response() -> dict[str, Any] | None:
        while True:
            try:
                raw = await asyncio.wait_for(
                    proc.stdout.readline(),  # type: ignore[union-attr]
                    timeout=PLAYWRIGHT_MCP_TIMEOUT,
                )
            except asyncio.TimeoutError:
                return None
            if not raw:
                return None
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue

    try:
        # Step 1: Initialize
        await _write_json({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "bridge_mcp", "version": "1.0"},
            },
        })
        init_resp = await _read_response()
        if init_resp is None:
            raise RuntimeError("No initialize response from Playwright MCP")

        # Step 2: Send initialized notification (required by MCP protocol)
        await _write_json({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        # Step 3: Send tool calls sequentially
        results: list[dict[str, Any]] = []
        for tool_name, arguments in calls:
            req_id = len(results) + 1
            await _write_json({
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments or {},
                },
            })
            resp = await _read_response()
            if resp is None:
                results.append({
                    "error": f"No response from Playwright MCP for tool '{tool_name}'",
                    "source": "browser",
                    "tool": tool_name,
                })
                continue

            if "error" in resp:
                err = resp["error"]
                message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                results.append({
                    "error": message,
                    "source": "browser",
                    "tool": tool_name,
                })
                continue

            result = resp.get("result", {})
            text = _mcp_result_text(result)
            if result.get("isError", False):
                results.append({
                    "error": text or f"Playwright tool '{tool_name}' returned isError=true",
                    "source": "browser",
                    "tool": tool_name,
                })
                continue

            results.append({
                "ok": True,
                "text": text,
                "result": result,
                "source": "browser",
                "tool": tool_name,
            })

        return results

    except Exception as exc:
        return [
            {"error": f"Playwright MCP session failed: {exc}", "source": "browser", "tool": t}
            for t, _ in calls
        ]
    finally:
        # Cleanup: close stdin → server exits, then wait
        try:
            proc.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


# ---------------------------------------------------------------------------
# Email Proxy Tools (Bridge-Proxy-Tools Pattern — Option A)
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_email_send",
    description=(
        "Send an email through the Bridge email system. "
        "Creates an approval request — the email is only sent after Leo approves. "
        "Returns immediately with the approval request_id. "
        "Use bridge_approval_wait(request_id) to wait for the decision, "
        "then call bridge_email_execute(request_id) to send after approval."
    ),
)
async def bridge_email_send(
    to: str,
    subject: str,
    body: str,
) -> str:
    """Create approval request for email send. Does NOT send immediately."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    approval_body = {
        "agent_id": _agent_id,
        "action": "email_send",
        "target": to,
        "description": f"Email an {to}: {subject}",
        "risk_level": "medium",
        "payload": {
            "to": to,
            "subject": subject,
            "body": body,
            "from": "bridge-agents@4480f5.inboxapi.ai",
        },
        "timeout_seconds": 300,
    }

    try:
        resp = await _bridge_post("/approval/request", json=approval_body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "auto_approved":
            result = await _inboxapi_call("send_email", {
                "to": to,
                "subject": subject,
                "body": body,
                "from_name": "bridge-agents",
            })
            if result.get("error"):
                return json.dumps({"status": "send_failed", "error": result["error"], "source": "email"})
            return json.dumps({
                "status": "sent",
                "auto_approved": True,
                "standing_approval_id": data.get("standing_approval_id", ""),
                "to": to,
                "subject": subject,
                "backend": "email",
            })
        return json.dumps({
            "status": "pending_approval",
            "request_id": data.get("request_id"),
            "message": f"Email an {to} wartet auf Leos Genehmigung. "
                       f"Nutze bridge_approval_wait('{data.get('request_id')}') zum Warten, "
                       f"dann bridge_email_execute('{data.get('request_id')}') zum Senden.",
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_email_execute",
    description=(
        "Execute a previously approved email send. "
        "Only works if the approval request has status 'approved'. "
        "Call this after bridge_approval_wait confirms approval."
    ),
)
async def bridge_email_execute(request_id: str) -> str:
    """Send email after approval is confirmed."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    # 1. Verify approval status
    try:
        resp = await _bridge_get(f"/approval/{request_id}")
        resp.raise_for_status()
        approval = resp.json()
    except Exception as exc:
        return json.dumps({"error": f"Could not check approval: {exc}"})

    if approval.get("status") != "approved":
        return json.dumps({
            "error": f"Email not sent. Approval status: {approval.get('status', 'unknown')}",
            "request_id": request_id,
        })
    owner_error = _approval_owner_error(approval, request_id)
    if owner_error:
        return json.dumps(owner_error)

    # 2. Extract email data from approval payload
    payload = approval.get("payload", {})
    to_addr = payload.get("to", "")
    subject = payload.get("subject", "")
    body = payload.get("body", "")

    if not to_addr or not subject:
        return json.dumps({"error": "Missing to or subject in approval payload"})

    # 3. Send via InboxAPI
    result = await _inboxapi_call("send_email", {
        "to": to_addr,
        "subject": subject,
        "body": body,
        "from_name": "bridge-agents",
    })

    if result.get("error"):
        return json.dumps({
            "status": "send_failed",
            "request_id": request_id,
            "error": result["error"],
        })

    return json.dumps({
        "status": "sent",
        "request_id": request_id,
        "to": to_addr,
        "subject": subject,
        "backend": "inboxapi",
        "result": result.get("text", ""),
    })


@mcp.tool(
    name="bridge_email_read",
    description=(
        "Read emails from the Bridge email inbox. No approval needed. "
        "Returns recent emails with sender, subject, date, and body preview."
    ),
)
async def bridge_email_read(
    limit: int = 10,
    sender: str = "",
    subject: str = "",
) -> str:
    """Read emails — no approval required."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    if sender or subject:
        # Use search
        args: dict[str, Any] = {}
        if sender:
            args["sender"] = sender
        if subject:
            args["subject"] = subject
        result = await _inboxapi_call("search_emails", args)
    else:
        # Get recent emails
        result = await _inboxapi_call("get_emails", {"limit": min(limit, 50)})

    if result.get("error"):
        return json.dumps({"status": "error", "error": result["error"]})

    return json.dumps({
        "status": "ok",
        "backend": "inboxapi",
        "account": "bridge-agents@4480f5.inboxapi.ai",
        "result": result.get("text", ""),
    })


# ---------------------------------------------------------------------------
# Slack Integration (Stubs — aktiviert wenn Leo Slack-Token liefert)
# ---------------------------------------------------------------------------

_SLACK_TOKEN: str | None = os.environ.get("SLACK_BOT_TOKEN")
_SLACK_API_BASE_URL = "https://slack.com/api"


def _looks_like_slack_channel_id(value: str) -> bool:
    candidate = value.strip().upper()
    return bool(re.fullmatch(r"[CGD][A-Z0-9]{8,}", candidate))


async def _slack_api_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Call the Slack Web API."""
    if not _SLACK_TOKEN:
        return {
            "error": "Slack nicht konfiguriert. SLACK_BOT_TOKEN fehlt.",
            "source": "slack",
        }
    headers = {
        "Authorization": f"Bearer {_SLACK_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        async with httpx.AsyncClient(
            base_url=_SLACK_API_BASE_URL, timeout=20.0
        ) as client:
            resp = await client.post(f"/{method}", headers=headers, json=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"error": f"Slack API request failed: {exc}", "source": "slack"}
    if not data.get("ok"):
        return {
            "error": f"Slack API error: {data.get('error', 'unknown_error')}",
            "source": "slack",
            "details": data,
        }
    return data


async def _slack_resolve_channel_id(channel: str) -> tuple[str, str | None]:
    """Resolve channel names like '#general' to Slack conversation IDs."""
    raw_channel = str(channel or "").strip()
    if not raw_channel:
        return "", "Slack channel is required"
    if _looks_like_slack_channel_id(raw_channel):
        return raw_channel.upper(), None
    channel_name = raw_channel.lstrip("#")
    lookup = await _slack_api_call(
        "conversations.list",
        {
            "types": "public_channel,private_channel",
            "exclude_archived": True,
            "limit": 1000,
        },
    )
    if lookup.get("error"):
        return "", str(lookup["error"])
    for entry in lookup.get("channels", []):
        if entry.get("name") == channel_name or entry.get("name_normalized") == channel_name:
            return str(entry.get("id", "")), None
    return "", f"Slack channel '{raw_channel}' nicht gefunden"


async def _slack_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Call Slack Web API with basic channel-name resolution."""
    payload = dict(params)
    if "channel" in payload:
        resolved_channel, error = await _slack_resolve_channel_id(str(payload["channel"]))
        if error:
            return {"error": error, "source": "slack"}
        payload["channel"] = resolved_channel
    return await _slack_api_call(method, payload)


@mcp.tool(
    name="bridge_slack_send",
    description=(
        "Send a message to a Slack channel through the Bridge. "
        "Creates an approval request — Leo must approve before the message is sent. "
        "After approval, call bridge_slack_execute(request_id) to send."
    ),
)
async def bridge_slack_send(channel: str, message: str) -> str:
    """Create approval request for Slack message. Does NOT send immediately."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    approval_body = {
        "agent_id": _agent_id,
        "action": "slack_send",
        "target": channel,
        "description": f"Slack-Nachricht an #{channel}: {message[:80]}",
        "risk_level": "medium",
        "payload": {
            "channel": channel,
            "message": message,
        },
        "timeout_seconds": 300,
    }

    try:
        resp = await _bridge_post("/approval/request", json=approval_body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "auto_approved":
            result = await _slack_call("chat.postMessage", {
                "channel": channel,
                "text": message,
            })
            if result.get("error"):
                return json.dumps({"status": "send_failed", "error": result["error"], "source": "slack"})
            return json.dumps({
                "status": "sent",
                "auto_approved": True,
                "standing_approval_id": data.get("standing_approval_id", ""),
                "channel": channel,
                "backend": "slack",
                "slack_channel_id": result.get("channel"),
                "ts": result.get("ts"),
            })
        return json.dumps({
            "status": "pending_approval",
            "request_id": data.get("request_id"),
            "message": f"Slack-Nachricht an #{channel} wartet auf Leos Genehmigung. "
                       f"Nach Genehmigung: bridge_slack_execute('{data.get('request_id')}')",
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_slack_execute",
    description=(
        "Execute a previously approved Slack message send. "
        "Only works if the approval request has status 'approved'."
    ),
)
async def bridge_slack_execute(request_id: str) -> str:
    """Send Slack message after approval is confirmed."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        resp = await _bridge_get(f"/approval/{request_id}")
        resp.raise_for_status()
        approval = resp.json()
    except Exception as exc:
        return json.dumps({"error": f"Could not check approval: {exc}"})

    if approval.get("status") != "approved":
        return json.dumps({
            "error": f"Message not sent. Approval status: {approval.get('status', 'unknown')}",
            "request_id": request_id,
        })
    owner_error = _approval_owner_error(approval, request_id)
    if owner_error:
        return json.dumps(owner_error)

    payload = approval.get("payload", {})
    channel = payload.get("channel", "")
    message = payload.get("message", "")

    if not channel or not message:
        return json.dumps({"error": "Missing channel or message in approval payload"})

    result = await _slack_call("chat.postMessage", {
        "channel": channel,
        "text": message,
    })

    if result.get("error"):
        return json.dumps({
            "status": "send_failed",
            "request_id": request_id,
            "error": result["error"],
        })

    return json.dumps({
        "status": "sent",
        "request_id": request_id,
        "channel": channel,
        "backend": "slack",
        "slack_channel_id": result.get("channel"),
        "ts": result.get("ts"),
    })


@mcp.tool(
    name="bridge_slack_read",
    description=(
        "Read messages from a Slack channel. No approval needed. "
        "Returns recent messages with author, timestamp, and text."
    ),
)
async def bridge_slack_read(channel: str, limit: int = 20) -> str:
    """Read Slack messages — no approval required."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    result = await _slack_call("conversations.history", {
        "channel": channel,
        "limit": min(limit, 100),
    })

    if result.get("error"):
        return json.dumps({"status": "error", "error": result["error"]})

    messages = [
        {
            "user": msg.get("user", ""),
            "text": msg.get("text", ""),
            "timestamp": msg.get("ts", ""),
        }
        for msg in result.get("messages", [])
    ]
    return json.dumps({
        "status": "ok",
        "backend": "slack",
        "channel": channel,
        "messages": messages,
        "has_more": bool(result.get("has_more", False)),
    })


# ---------------------------------------------------------------------------
# Telegram Integration (Bot API)
# ---------------------------------------------------------------------------

_TELEGRAM_API_BASE_URL = os.environ.get("TELEGRAM_API_BASE_URL", "https://api.telegram.org").rstrip("/")
_TELEGRAM_TOKEN_PATH = os.path.expanduser("~/.config/bridge/telegram_bot_token")
_TELEGRAM_DEFAULT_STORE_CANDIDATES: tuple[str, ...] = (
    "~/.local/share/bridge/telegram/updates.jsonl",
    "~/.config/bridge/telegram/updates.jsonl",
)


def _resolve_telegram_config_path() -> str:
    env_val = os.environ.get("TELEGRAM_CONFIG_PATH", "").strip()
    if env_val:
        return os.path.expanduser(env_val)
    candidates = (
        "~/.config/bridge/telegram_config.json",
        os.path.join(os.path.dirname(__file__), "telegram_config.json"),
    )
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return os.path.expanduser("~/.config/bridge/telegram_config.json")


def _resolve_telegram_store_path() -> str:
    env_val = os.environ.get("TELEGRAM_UPDATES_STORE_PATH", "").strip()
    if env_val:
        return os.path.expanduser(env_val)
    for candidate in _TELEGRAM_DEFAULT_STORE_CANDIDATES:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return os.path.expanduser(_TELEGRAM_DEFAULT_STORE_CANDIDATES[0])


def _load_telegram_config() -> dict[str, Any]:
    if not os.path.exists(_TELEGRAM_CONFIG_PATH):
        return {}
    try:
        with open(_TELEGRAM_CONFIG_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


_TELEGRAM_CONFIG_PATH: str = _resolve_telegram_config_path()
_TELEGRAM_UPDATES_STORE_PATH: str = _resolve_telegram_store_path()
_TELEGRAM_CONFIG: dict[str, Any] = _load_telegram_config()


def _load_telegram_bot_token() -> str:
    env_val = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if env_val:
        return env_val
    if os.path.exists(_TELEGRAM_TOKEN_PATH):
        try:
            with open(_TELEGRAM_TOKEN_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


def _load_telegram_list(env_key: str, config_key: str) -> list[str]:
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        return [value.strip() for value in env_val.split(",") if value.strip()]
    raw = _TELEGRAM_CONFIG.get(config_key, [])
    if isinstance(raw, list):
        return [str(value).strip() for value in raw if str(value).strip()]
    return []


def _load_telegram_contacts() -> dict[str, str]:
    raw = _TELEGRAM_CONFIG.get("contacts", {})
    if not isinstance(raw, dict):
        return {}
    return {str(key).strip(): str(value).strip() for key, value in raw.items() if key and value}


_TELEGRAM_BOT_TOKEN: str = _load_telegram_bot_token()
_TELEGRAM_READ_WHITELIST: list[str] = _load_telegram_list("TELEGRAM_READ_WHITELIST", "read_whitelist")
_TELEGRAM_SEND_WHITELIST: list[str] = _load_telegram_list("TELEGRAM_SEND_WHITELIST", "send_whitelist")
_TELEGRAM_APPROVAL_WHITELIST: list[str] = _load_telegram_list(
    "TELEGRAM_APPROVAL_WHITELIST", "approval_whitelist"
)
_TELEGRAM_CONTACTS: dict[str, str] = _load_telegram_contacts()


def _looks_like_telegram_chat(value: str) -> bool:
    candidate = str(value or "").strip()
    return bool(re.fullmatch(r"-?\d+", candidate)) or candidate.startswith("@")


def _resolve_telegram_recipient(name_or_chat: str) -> str:
    candidate = str(name_or_chat or "").strip()
    if not candidate:
        return ""
    if _looks_like_telegram_chat(candidate):
        return candidate
    return (
        _TELEGRAM_CONTACTS.get(candidate)
        or _TELEGRAM_CONTACTS.get(candidate.lower())
        or candidate
    )


def _telegram_with_sender_prefix(message: str, agent_id: str | None) -> str:
    text = str(message or "").strip()
    aid = str(agent_id or "").strip()
    if not text or not aid:
        return text
    if re.match(rf"^\[\s*{re.escape(aid)}\s*\]\s*", text, flags=re.IGNORECASE):
        return text
    return f"[{aid.upper()}] {text}"


def _telegram_normalize_update(update: dict[str, Any]) -> dict[str, Any] | None:
    raw_message = update.get("message") or update.get("channel_post")
    if not isinstance(raw_message, dict):
        return None
    chat = raw_message.get("chat", {})
    chat_id = str(chat.get("id", "")).strip()
    if not chat_id:
        return None
    text = str(raw_message.get("text") or raw_message.get("caption") or "").strip()
    sender_obj = raw_message.get("from") or {}
    sender = (
        str(sender_obj.get("username", "")).strip()
        or " ".join(
            part
            for part in (
                str(sender_obj.get("first_name", "")).strip(),
                str(sender_obj.get("last_name", "")).strip(),
            )
            if part
        ).strip()
        or str(sender_obj.get("id", "")).strip()
    )
    timestamp = raw_message.get("date")
    time_iso = ""
    if isinstance(timestamp, (int, float)) and timestamp > 0:
        time_iso = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()
    return {
        "update_id": update.get("update_id"),
        "message_id": raw_message.get("message_id"),
        "chat_id": chat_id,
        "chat": str(chat.get("title") or chat.get("username") or chat_id),
        "sender": sender,
        "text": text,
        "time": time_iso,
    }


async def _telegram_api_call(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _TELEGRAM_BOT_TOKEN:
        return {
            "error": (
                "Telegram nicht konfiguriert. TELEGRAM_BOT_TOKEN fehlt oder "
                "~/.config/bridge/telegram_bot_token existiert nicht."
            ),
            "source": "telegram",
        }

    url = f"{_TELEGRAM_API_BASE_URL}/bot{_TELEGRAM_BOT_TOKEN}/{method}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload or {})
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        return {
            "error": f"Telegram API nicht erreichbar: {_TELEGRAM_API_BASE_URL}",
            "source": "telegram",
        }
    except Exception as exc:
        return {"error": f"Telegram API request failed: {exc}", "source": "telegram"}

    if not data.get("ok"):
        return {
            "error": f"Telegram API error: {data.get('description', 'unknown_error')}",
            "source": "telegram",
            "details": data,
        }
    return data


async def _telegram_send(params: dict[str, Any]) -> dict[str, Any]:
    recipient = _resolve_telegram_recipient(str(params.get("to", "")))
    message = str(params.get("message", "")).strip()
    if not recipient or not message:
        return {"error": "Missing 'to' or 'message'", "source": "telegram"}
    if len(message) > 4096:
        return {"error": "Telegram message too long (max 4096 characters)", "source": "telegram"}
    if not _TELEGRAM_SEND_WHITELIST:
        return {
            "error": (
                "Telegram Send-Whitelist ist leer. Keine Empfaenger erlaubt. "
                f"Konfiguration: {_TELEGRAM_CONFIG_PATH} -> send_whitelist"
            ),
            "source": "telegram",
        }
    if recipient not in _TELEGRAM_SEND_WHITELIST:
        return {
            "error": f"Empfaenger '{recipient}' nicht in Telegram Send-Whitelist.",
            "source": "telegram",
        }

    result = await _telegram_api_call(
        "sendMessage",
        {
            "chat_id": recipient,
            "text": message,
            "disable_web_page_preview": True,
        },
    )
    if result.get("error"):
        return result

    message_result = result.get("result", {})
    chat = message_result.get("chat", {})
    return {
        "ok": True,
        "text": "Sent",
        "source": "telegram",
        "chat_id": str(chat.get("id", recipient)).strip() or recipient,
        "message_id": message_result.get("message_id"),
    }


def _telegram_read_from_store(limit: int, chat_filter: str) -> list[dict[str, Any]] | None:
    if not os.path.exists(_TELEGRAM_UPDATES_STORE_PATH):
        return None

    messages: list[dict[str, Any]] = []
    try:
        with open(_TELEGRAM_UPDATES_STORE_PATH, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                chat_id = str(entry.get("chat_id", "")).strip()
                if chat_id not in _TELEGRAM_READ_WHITELIST:
                    continue
                if chat_filter and chat_id != chat_filter:
                    continue
                messages.append(
                    {
                        "chat": str(entry.get("chat") or chat_id),
                        "chat_id": chat_id,
                        "sender": str(entry.get("sender", "")),
                        "text": str(entry.get("text", "")),
                        "time": str(entry.get("time", "")),
                        "message_id": entry.get("message_id"),
                    }
                )
    except OSError:
        return None

    return messages[-limit:]


async def _telegram_read_live(limit: int, chat_filter: str) -> list[dict[str, Any]] | dict[str, Any]:
    result = await _telegram_api_call(
        "getUpdates",
        {
            "limit": min(limit, 100),
            "timeout": 0,
            "allowed_updates": ["message", "channel_post"],
        },
    )
    if result.get("error"):
        return result

    messages: list[dict[str, Any]] = []
    for update in result.get("result", []):
        if not isinstance(update, dict):
            continue
        normalized = _telegram_normalize_update(update)
        if not normalized:
            continue
        chat_id = str(normalized.get("chat_id", "")).strip()
        if chat_id not in _TELEGRAM_READ_WHITELIST:
            continue
        if chat_filter and chat_id != chat_filter:
            continue
        messages.append(
            {
                "chat": normalized.get("chat", chat_id),
                "chat_id": chat_id,
                "sender": normalized.get("sender", ""),
                "text": normalized.get("text", ""),
                "time": normalized.get("time", ""),
                "message_id": normalized.get("message_id"),
            }
        )
    return messages[-limit:]


async def _telegram_call(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "send_message":
        return await _telegram_send(params)
    return {"error": f"Unknown Telegram action: {action}", "source": "telegram"}


@mcp.tool(
    name="bridge_telegram_send",
    description=(
        "Send a Telegram message through the Bridge. "
        "Creates an approval request and sends only after approval or auto-approval."
    ),
)
async def bridge_telegram_send(to: str, message: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not message or not message.strip():
        return json.dumps({"error": "message is required"})

    resolved_to = _resolve_telegram_recipient(to)
    formatted_message = _telegram_with_sender_prefix(message, _agent_id)

    if resolved_to in _TELEGRAM_APPROVAL_WHITELIST:
        result = await _telegram_call("send_message", {"to": resolved_to, "message": formatted_message})
        if result.get("error"):
            return json.dumps({"status": "send_failed", "error": result["error"], "source": "telegram"})
        return json.dumps({
            "status": "sent",
            "approval_whitelisted": True,
            "to": to,
            "backend": "telegram",
            "telegram_chat_id": result.get("chat_id", resolved_to),
        })

    approval_body = {
        "agent_id": _agent_id,
        "action": "telegram_send",
        "target": to,
        "description": f"Telegram an {to}: {formatted_message[:80]}",
        "risk_level": "medium",
        "payload": {
            "to": resolved_to,
            "message": formatted_message,
        },
        "timeout_seconds": 300,
    }

    try:
        resp = await _bridge_post("/approval/request", json=approval_body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "auto_approved":
            result = await _telegram_call("send_message", {"to": resolved_to, "message": formatted_message})
            if result.get("error"):
                return json.dumps({"status": "send_failed", "error": result["error"], "source": "telegram"})
            return json.dumps({
                "status": "sent",
                "auto_approved": True,
                "standing_approval_id": data.get("standing_approval_id", ""),
                "to": to,
                "backend": "telegram",
                "telegram_chat_id": result.get("chat_id", resolved_to),
            })
        return json.dumps({
            "status": "pending_approval",
            "request_id": data.get("request_id"),
            "message": (
                f"Telegram an {to} wartet auf Genehmigung. "
                f"Nach Genehmigung: bridge_telegram_execute('{data.get('request_id')}')"
            ),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_telegram_execute",
    description=(
        "Execute a previously approved Telegram message send. "
        "Only works if the approval request has status 'approved'."
    ),
)
async def bridge_telegram_execute(request_id: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        resp = await _bridge_get(f"/approval/{request_id}")
        resp.raise_for_status()
        approval = resp.json()
    except Exception as exc:
        return json.dumps({"error": f"Could not check approval: {exc}"})

    if approval.get("status") != "approved":
        return json.dumps({
            "error": f"Message not sent. Approval status: {approval.get('status', 'unknown')}",
            "request_id": request_id,
        })
    owner_error = _approval_owner_error(approval, request_id)
    if owner_error:
        return json.dumps(owner_error)

    payload = approval.get("payload", {})
    to_target = str(payload.get("to", "")).strip()
    message = str(payload.get("message", "")).strip()
    if not to_target or not message:
        return json.dumps({"error": "Missing to or message in approval payload"})

    result = await _telegram_call("send_message", {"to": to_target, "message": message})
    if result.get("error"):
        return json.dumps({
            "status": "send_failed",
            "request_id": request_id,
            "error": result["error"],
        })

    return json.dumps({
        "status": "sent",
        "request_id": request_id,
        "to": to_target,
        "backend": "telegram",
        "telegram_chat_id": result.get("chat_id", to_target),
        "result": result.get("text", ""),
    })


@mcp.tool(
    name="bridge_telegram_read",
    description=(
        "Read recent Telegram messages from the configured bot inbox or local watcher store. "
        "No approval needed."
    ),
)
async def bridge_telegram_read(chat: str = "", limit: int = 20) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not _TELEGRAM_READ_WHITELIST:
        return json.dumps({
            "status": "error",
            "error": (
                "Telegram Read-Whitelist ist leer. "
                f"Konfiguration: {_TELEGRAM_CONFIG_PATH} -> read_whitelist"
            ),
        })

    resolved_chat = _resolve_telegram_recipient(chat) if chat else ""
    if resolved_chat and resolved_chat not in _TELEGRAM_READ_WHITELIST:
        return json.dumps({
            "status": "error",
            "error": f"Chat '{chat}' ist nicht in der Telegram Read-Whitelist.",
        })

    store_messages = _telegram_read_from_store(min(limit, 100), resolved_chat)
    if store_messages is not None:
        return json.dumps({
            "status": "ok",
            "backend": "telegram",
            "source": "store",
            "messages": store_messages,
            "has_more": False,
        })

    live_messages = await _telegram_read_live(min(limit, 100), resolved_chat)
    if isinstance(live_messages, dict) and live_messages.get("error"):
        return json.dumps({"status": "error", "error": live_messages["error"]})
    return json.dumps({
        "status": "ok",
        "backend": "telegram",
        "source": "live",
        "messages": live_messages,
        "has_more": False,
    })


# ---------------------------------------------------------------------------
# WhatsApp Integration (Stubs — aktiviert wenn Leo QR-Code scannt)
# ---------------------------------------------------------------------------

# WhatsApp nutzt lharries/whatsapp-mcp (Go Bridge + Python MCP Server)
# Go Bridge API: http://localhost:8080/api/{send,download}
# Messages in SQLite: store/messages.db
_WHATSAPP_BRIDGE_URL: str = os.environ.get("WHATSAPP_BRIDGE_URL", "http://localhost:8080")
_WHATSAPP_TOKEN_PATH: str = os.path.expanduser("~/.config/bridge/whatsapp_bridge_token")
# Privacy: Only read/send messages from/to whitelisted JIDs (Leo's explicit permission)
# Priority: ENV variable > config file > empty (no access)
_WHATSAPP_DEFAULT_DB_CANDIDATES: tuple[str, ...] = (
    "~/.config/bridge/whatsapp-bridge/store/messages.db",
    "~/.local/share/bridge/whatsapp-bridge/store/messages.db",
)


def _resolve_whatsapp_db_path() -> str:
    """Resolve WhatsApp SQLite DB without operator-specific fallbacks."""
    env_val = os.environ.get("WHATSAPP_DB_PATH", "").strip()
    if env_val:
        return os.path.expanduser(env_val)
    for candidate in _WHATSAPP_DEFAULT_DB_CANDIDATES:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return os.path.expanduser(_WHATSAPP_DEFAULT_DB_CANDIDATES[0])


def _resolve_whatsapp_config_path() -> str:
    """Resolve WhatsApp config path with home config preferred over repo-local fallback."""
    env_val = os.environ.get("WHATSAPP_CONFIG_PATH", "").strip()
    if env_val:
        return os.path.expanduser(env_val)
    candidates = (
        "~/.config/bridge/whatsapp_config.json",
        os.path.join(os.path.dirname(__file__), "whatsapp_config.json"),
    )
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return os.path.expanduser("~/.config/bridge/whatsapp_config.json")


def _load_whatsapp_config() -> dict[str, Any]:
    """Load structured WhatsApp config once during module init."""
    if not os.path.exists(_WHATSAPP_CONFIG_PATH):
        return {}
    try:
        with open(_WHATSAPP_CONFIG_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


_WHATSAPP_DB_PATH: str = _resolve_whatsapp_db_path()
_WHATSAPP_CONFIG_PATH: str = _resolve_whatsapp_config_path()
_WHATSAPP_CONFIG: dict[str, Any] = _load_whatsapp_config()


def _load_whatsapp_bridge_token() -> str:
    """Load WhatsApp Bridge auth token from file. Fail-closed: no token = no sends."""
    env_val = os.environ.get("WHATSAPP_API_TOKEN", "").strip()
    if env_val:
        return env_val
    if os.path.exists(_WHATSAPP_TOKEN_PATH):
        try:
            with open(_WHATSAPP_TOKEN_PATH, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


_WHATSAPP_API_TOKEN: str = _load_whatsapp_bridge_token()
_WHATSAPP_AGENT_BADGES: dict[str, str] = {
    "ordo": "🟥",
    "viktor": "🟩",
    "nova": "🟨",
    "frontend": "🟧",
    "backend": "🟫",
    "security": "⬛",
    "lucy": "🟪",
    "stellexa": "⬜",
    "codex": "🟦",
}
_WHATSAPP_BADGE_DEFAULT = "🟦"

def _load_whatsapp_whitelist() -> list[str]:
    """Load WhatsApp read whitelist. ENV takes precedence over config file."""
    env_val = os.environ.get("WHATSAPP_READ_WHITELIST", "").strip()
    if env_val:
        return [jid.strip() for jid in env_val.split(",") if jid.strip()]
    jids = _WHATSAPP_CONFIG.get("read_whitelist", [])
    if isinstance(jids, list):
        return [str(j).strip() for j in jids if str(j).strip()]
    return []

_WHATSAPP_READ_WHITELIST: list[str] = _load_whatsapp_whitelist()


def _load_whatsapp_send_whitelist() -> list[str]:
    """Load WhatsApp send whitelist. ENV takes precedence over config file.
    Fail-closed: empty whitelist = no sends allowed."""
    env_val = os.environ.get("WHATSAPP_SEND_WHITELIST", "").strip()
    if env_val:
        return [jid.strip() for jid in env_val.split(",") if jid.strip()]
    jids = _WHATSAPP_CONFIG.get("send_whitelist", [])
    if isinstance(jids, list):
        return [str(j).strip() for j in jids if str(j).strip()]
    return []


_WHATSAPP_SEND_WHITELIST: list[str] = _load_whatsapp_send_whitelist()


def _load_whatsapp_approval_whitelist() -> list[str]:
    """Load WhatsApp approval whitelist — JIDs that skip the approval gate.
    Messages to these JIDs are sent directly (still enforcing send_whitelist).
    Leo-Direktive: 'Nachrichten an meine Nummer brauchen keine Approval.'"""
    env_val = os.environ.get("WHATSAPP_APPROVAL_WHITELIST", "").strip()
    if env_val:
        return [jid.strip() for jid in env_val.split(",") if jid.strip()]
    jids = _WHATSAPP_CONFIG.get("approval_whitelist", [])
    if isinstance(jids, list):
        return [str(j).strip() for j in jids if str(j).strip()]
    return []


_WHATSAPP_APPROVAL_WHITELIST: list[str] = _load_whatsapp_approval_whitelist()


def _load_whatsapp_contacts() -> dict[str, str]:
    """Load name→JID contacts mapping from whatsapp_config.json."""
    contacts = _WHATSAPP_CONFIG.get("contacts", {})
    if isinstance(contacts, dict):
        return {str(k).strip(): str(v).strip() for k, v in contacts.items() if k and v}
    return {}


_WHATSAPP_CONTACTS: dict[str, str] = _load_whatsapp_contacts()


def _resolve_whatsapp_recipient(name_or_jid: str) -> str:
    """Resolve friendly name to JID. Returns input unchanged if already a JID."""
    if "@" in name_or_jid:
        return name_or_jid
    # Normalize phone numbers: +49151XXXXXXXX → 49151XXXXXXXX@s.whatsapp.net
    stripped = name_or_jid.lstrip("+")
    if stripped.isdigit() and len(stripped) >= 7:
        return f"{stripped}@s.whatsapp.net"
    resolved = _WHATSAPP_CONTACTS.get(name_or_jid) or _WHATSAPP_CONTACTS.get(name_or_jid.lower())
    return resolved if resolved else name_or_jid


def _whatsapp_agent_prefix(agent_id: str | None) -> str:
    """Build visible sender prefix for shared WhatsApp channel."""
    aid = (agent_id or "").strip()
    if not aid:
        return "[AGENT]"
    badge = _WHATSAPP_AGENT_BADGES.get(aid.lower(), _WHATSAPP_BADGE_DEFAULT)
    return f"{badge} [{aid.upper()}]"


def _whatsapp_with_sender_prefix(message: str, agent_id: str | None) -> str:
    """Prefix outgoing WhatsApp text with agent identity, avoiding duplicates."""
    text = str(message or "").strip()
    aid = (agent_id or "").strip()
    if not text or not aid:
        return text

    # Respect explicit sender prefixes already present at the start.
    already_prefixed = re.match(
        rf"^\s*(?:[🟥🟧🟨🟩🟦🟪🟫⬛⬜]\s*)?\[\s*{re.escape(aid)}\s*\]\s*",
        text,
        flags=re.IGNORECASE,
    )
    if already_prefixed:
        return text

    return f"{_whatsapp_agent_prefix(aid)} {text}"


async def _whatsapp_call(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Call WhatsApp Bridge (Go HTTP API + SQLite).

    Actions:
        send_message: POST /api/send — sends WhatsApp message
        get_messages: SQLite query — reads messages (whitelist-filtered)
    """
    if action == "send_message":
        return await _whatsapp_send(params)
    elif action == "get_messages":
        return _whatsapp_read(params)
    else:
        return {"error": f"Unknown WhatsApp action: {action}", "source": "whatsapp"}


async def _whatsapp_send(params: dict[str, Any]) -> dict[str, Any]:
    """Send WhatsApp message via Go Bridge HTTP API.
    Fail-closed: No token = no send. No whitelist match = no send."""
    recipient = _resolve_whatsapp_recipient(params.get("to", ""))
    message = params.get("message", "")
    media_path = params.get("media_path", "")
    if not recipient or (not message and not media_path):
        return {"error": "Missing 'to' or 'message'/'media_path'", "source": "whatsapp"}

    # Schicht 1: Token enforcement (fail-closed)
    if not _WHATSAPP_API_TOKEN:
        return {
            "error": "WhatsApp Bridge Token nicht konfiguriert. "
            "Datei fehlt: ~/.config/bridge/whatsapp_bridge_token",
            "source": "whatsapp",
        }

    # Schicht 2: Send-Whitelist enforcement (fail-closed: empty = deny all)
    if not _WHATSAPP_SEND_WHITELIST:
        return {
            "error": "WhatsApp Send-Whitelist ist leer. Keine Empfaenger erlaubt. "
            f"Konfiguration: {_WHATSAPP_CONFIG_PATH} → send_whitelist",
            "source": "whatsapp",
        }
    if recipient not in _WHATSAPP_SEND_WHITELIST:
        return {
            "error": f"Empfaenger '{_mask_phone(recipient)}' nicht in Send-Whitelist. "
            f"Erlaubt: {[_mask_phone(j) for j in _WHATSAPP_SEND_WHITELIST]}",
            "source": "whatsapp",
        }

    try:
        headers = {"X-WhatsApp-Token": _WHATSAPP_API_TOKEN}

        async with httpx.AsyncClient(timeout=30.0) as client:
            payload: dict[str, str] = {"recipient": recipient, "message": message}
            if media_path:
                payload["media_path"] = media_path
            resp = await client.post(
                f"{_WHATSAPP_BRIDGE_URL}/api/send",
                json=payload,
                headers=headers,
            )
            data = resp.json()
            if data.get("success"):
                return {"ok": True, "text": data.get("message", "Sent"), "source": "whatsapp"}
            else:
                return {"error": data.get("message", "Send failed"), "source": "whatsapp"}
    except httpx.ConnectError:
        return {
            "error": "WhatsApp Bridge nicht erreichbar. "
            "Pruefen: tmux attach -t whatsapp_bridge",
            "source": "whatsapp",
        }
    except Exception as exc:
        return {"error": f"WhatsApp send failed: {exc}", "source": "whatsapp"}


def _whatsapp_read(params: dict[str, Any]) -> dict[str, Any]:
    """Read WhatsApp messages from SQLite (privacy-filtered)."""
    import sqlite3 as sqlite3_mod

    if not _WHATSAPP_READ_WHITELIST:
        return {
            "error": "WhatsApp-Leseschutz aktiv. Keine JIDs freigegeben. "
            "Leo muss WHATSAPP_READ_WHITELIST setzen (z.B. Gruppen-JID).",
            "source": "whatsapp",
        }

    if not os.path.exists(_WHATSAPP_DB_PATH):
        return {
            "error": f"WhatsApp-DB nicht gefunden: {_WHATSAPP_DB_PATH}",
            "source": "whatsapp",
        }

    limit = min(params.get("limit", 20), 100)
    contact = params.get("contact", "")

    conn = None
    try:
        conn = sqlite3_mod.connect(_WHATSAPP_DB_PATH)
        conn.row_factory = sqlite3_mod.Row
        cur = conn.cursor()

        # Build query with whitelist filter
        placeholders = ",".join("?" for _ in _WHATSAPP_READ_WHITELIST)
        query = f"""
            SELECT m.id, m.chat_jid, m.sender, m.content, m.timestamp, m.is_from_me,
                   c.name as chat_name
            FROM messages m
            LEFT JOIN chats c ON m.chat_jid = c.jid
            WHERE m.chat_jid IN ({placeholders})
        """
        query_params: list[Any] = list(_WHATSAPP_READ_WHITELIST)

        if contact:
            query += " AND (m.sender LIKE ? OR m.chat_jid LIKE ?)"
            query_params.extend([f"%{contact}%", f"%{contact}%"])

        query += " ORDER BY m.timestamp DESC LIMIT ?"
        query_params.append(limit)

        cur.execute(query, query_params)
        rows = cur.fetchall()

        messages = []
        for row in rows:
            messages.append({
                "id": row["id"],
                "chat": row["chat_name"] or _mask_phone(row["chat_jid"]),
                "sender": _mask_phone(row["sender"]) if row["sender"] else "",
                "text": row["content"],
                "time": row["timestamp"],
                "from_me": bool(row["is_from_me"]),
            })

        return {
            "ok": True,
            "text": json.dumps(messages, ensure_ascii=False, indent=2),
            "source": "whatsapp",
            "count": len(messages),
        }
    except Exception as exc:
        return {"error": f"WhatsApp read failed: {exc}", "source": "whatsapp"}
    finally:
        if conn:
            conn.close()


@mcp.tool(
    name="bridge_whatsapp_send",
    description=(
        "Send a WhatsApp message (text and/or image) through the Bridge. "
        "For images, pass media_path (absolute path to file on disk). "
        "Creates an approval request — Leo must approve before the message is sent. "
        "After approval, call bridge_whatsapp_execute(request_id) to send."
    ),
)
async def bridge_whatsapp_send(to: str, message: str = "", media_path: str = "") -> str:
    """Create approval request for WhatsApp message/media. Does NOT send immediately."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    if not message and not media_path:
        return json.dumps({"error": "Either message or media_path required."})

    # Validate media_path if provided
    if media_path and not os.path.isfile(media_path):
        return json.dumps({"error": f"media_path not found: {media_path}"})

    # Resolve friendly name → JID (e.g. "Leo" → "120363...@g.us")
    resolved_to = _resolve_whatsapp_recipient(to)
    display_name = to  # Keep original name for display

    formatted_message = _whatsapp_with_sender_prefix(message, _agent_id) if message else ""

    # Approval-Whitelist: Skip approval gate for whitelisted JIDs (Leo-Direktive)
    if resolved_to in _WHATSAPP_APPROVAL_WHITELIST:
        # Still enforce send_whitelist (security layer)
        if not _WHATSAPP_SEND_WHITELIST or resolved_to not in _WHATSAPP_SEND_WHITELIST:
            return json.dumps({
                "status": "blocked",
                "error": f"Empfaenger '{display_name}' (JID: {_mask_phone(resolved_to)}) nicht in Send-Whitelist",
            })
        send_params: dict[str, str] = {
            "to": resolved_to,
            "message": formatted_message,
        }
        if media_path:
            send_params["media_path"] = media_path
        result = await _whatsapp_call("send_message", send_params)
        if result.get("error"):
            return json.dumps({"status": "send_failed", "error": result["error"], "source": "whatsapp"})
        return json.dumps({
            "status": "sent",
            "approval_whitelisted": True,
            "to": to,
            "backend": "whatsapp",
        })

    # Standard path: Approval gate
    approval_body = {
        "agent_id": _agent_id,
        "action": "whatsapp_send",
        "target": display_name,
        "description": f"WhatsApp an {display_name}: {formatted_message[:80]}",
        "risk_level": "high",
        "payload": {
            "to": resolved_to,
            "message": formatted_message,
            **({"media_path": media_path} if media_path else {}),
        },
        "timeout_seconds": 300,
    }

    try:
        resp = await _bridge_post("/approval/request", json=approval_body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "auto_approved":
            if not _WHATSAPP_SEND_WHITELIST or resolved_to not in _WHATSAPP_SEND_WHITELIST:
                return json.dumps({
                    "status": "blocked",
                    "error": f"Empfaenger '{display_name}' (JID: {_mask_phone(resolved_to)}) nicht in Send-Whitelist",
                })
            result = await _whatsapp_call("send_message", {
                "to": resolved_to,
                "message": formatted_message,
                **({"media_path": media_path} if media_path else {}),
            })
            if result.get("error"):
                return json.dumps({"status": "send_failed", "error": result["error"], "source": "whatsapp"})
            return json.dumps({
                "status": "sent",
                "auto_approved": True,
                "standing_approval_id": data.get("standing_approval_id", ""),
                "to": to,
                "backend": "whatsapp",
            })
        return json.dumps({
            "status": "pending_approval",
            "request_id": data.get("request_id"),
            "message": f"WhatsApp an {to} wartet auf Leos Genehmigung. "
                       f"Nach Genehmigung: bridge_whatsapp_execute('{data.get('request_id')}')",
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_whatsapp_execute",
    description=(
        "Execute a previously approved WhatsApp message send. "
        "Only works if the approval request has status 'approved'."
    ),
)
async def bridge_whatsapp_execute(request_id: str) -> str:
    """Send WhatsApp message after approval is confirmed."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        resp = await _bridge_get(f"/approval/{request_id}")
        resp.raise_for_status()
        approval = resp.json()
    except Exception as exc:
        return json.dumps({"error": f"Could not check approval: {exc}"})

    if approval.get("status") != "approved":
        return json.dumps({
            "error": f"Message not sent. Approval status: {approval.get('status', 'unknown')}",
            "request_id": request_id,
        })
    owner_error = _approval_owner_error(approval, request_id)
    if owner_error:
        return json.dumps(owner_error)

    payload = approval.get("payload", {})
    to_number = payload.get("to", "")
    message = payload.get("message", "")
    exec_media_path = payload.get("media_path", "")

    if not to_number or (not message and not exec_media_path):
        return json.dumps({"error": "Missing 'to' or 'message'/'media_path' in approval payload"})

    # Defense-in-depth: re-validate send whitelist at execute time (fail-closed)
    if not _WHATSAPP_SEND_WHITELIST or to_number not in _WHATSAPP_SEND_WHITELIST:
        return json.dumps({
            "error": f"Empfaenger '{_mask_phone(to_number)}' nicht in Send-Whitelist (execute-check)",
            "request_id": request_id,
        })

    send_params_exec: dict[str, str] = {
        "to": to_number,
        "message": message,
    }
    if exec_media_path:
        send_params_exec["media_path"] = exec_media_path
    result = await _whatsapp_call("send_message", send_params_exec)

    if result.get("error"):
        return json.dumps({
            "status": "send_failed",
            "request_id": request_id,
            "error": result["error"],
        })

    return json.dumps({
        "status": "sent",
        "request_id": request_id,
        "to": to_number,
        "backend": "whatsapp",
        "result": result.get("text", ""),
    })


@mcp.tool(
    name="bridge_whatsapp_read",
    description=(
        "Read recent WhatsApp messages. No approval needed. "
        "Returns recent messages with sender, timestamp, and text."
    ),
)
async def bridge_whatsapp_read(limit: int = 20, contact: str = "") -> str:
    """Read WhatsApp messages — no approval required."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    params: dict[str, Any] = {"limit": min(limit, 100)}
    if contact:
        params["contact"] = contact

    result = await _whatsapp_call("get_messages", params)

    if result.get("error"):
        return json.dumps({"status": "error", "error": result["error"]})

    return json.dumps({
        "status": "ok",
        "backend": "whatsapp",
        "result": result.get("text", ""),
    })


# ---------------------------------------------------------------------------
# Todoist Integration
# Spec: docs/TODOIST_INTEGRATION_SPEC.md
# ---------------------------------------------------------------------------

_TODOIST_TOKEN_PATH: str = os.path.expanduser("~/.config/bridge/todoist_token")
_TODOIST_BASE_URL: str = "https://api.todoist.com/api/v1"


def _load_todoist_token() -> str:
    """Load Todoist API token from file. Fail-closed: no token = no access."""
    env_val = os.environ.get("TODOIST_API_TOKEN", "").strip()
    if env_val:
        return env_val
    if os.path.exists(_TODOIST_TOKEN_PATH):
        try:
            with open(_TODOIST_TOKEN_PATH, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


_TODOIST_API_TOKEN: str = _load_todoist_token()


async def _todoist_request(
    method: str, endpoint: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call Todoist Unified API v1. Returns dict with response or error."""
    if not _TODOIST_API_TOKEN:
        return {
            "error": "Todoist nicht konfiguriert. Token fehlt: ~/.config/bridge/todoist_token",
            "source": "todoist",
        }
    headers = {
        "Authorization": f"Bearer {_TODOIST_API_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if method == "GET":
                resp = await client.get(f"{_TODOIST_BASE_URL}{endpoint}", headers=headers, params=params)
            elif method == "POST":
                resp = await client.post(f"{_TODOIST_BASE_URL}{endpoint}", headers=headers, json=json_body)
            elif method == "DELETE":
                resp = await client.delete(f"{_TODOIST_BASE_URL}{endpoint}", headers=headers)
            else:
                return {"error": f"Unknown method: {method}", "source": "todoist"}

            if resp.status_code == 204:
                return {"ok": True, "source": "todoist"}
            if resp.status_code == 401:
                return {"error": "Todoist Token ungueltig oder abgelaufen. Bitte erneuern.", "source": "todoist"}
            if resp.status_code == 429:
                return {"error": "Todoist Rate-Limit erreicht. Bitte kurz warten.", "source": "todoist"}
            if resp.status_code >= 400:
                return {"error": f"Todoist API Fehler {resp.status_code}: {resp.text[:200]}", "source": "todoist"}
            return resp.json()
    except httpx.ConnectError:
        return {"error": "Todoist API nicht erreichbar.", "source": "todoist"}
    except Exception as exc:
        return {"error": f"Todoist request failed: {exc}", "source": "todoist"}


def _todoist_format_task(task: dict[str, Any]) -> dict[str, Any]:
    """Format a Todoist task for agent consumption."""
    due = task.get("due")
    return {
        "id": task.get("id", ""),
        "content": task.get("content", ""),
        "description": task.get("description", ""),
        "priority": task.get("priority", 1),
        "due": due.get("date", "") if isinstance(due, dict) else "",
        "due_string": due.get("string", "") if isinstance(due, dict) else "",
        "project_id": task.get("project_id", ""),
        "labels": task.get("labels", []),
        "is_completed": task.get("is_completed", False),
        "url": task.get("url", ""),
    }


@mcp.tool(
    name="bridge_todoist_read",
    description=(
        "Read Todoist tasks. No approval needed. "
        "Filter options: 'today', 'overdue', 'tomorrow', '7 days', 'priority 1', '#ProjectName', '@label'. "
        "Returns task list with content, priority, due date, labels."
    ),
)
async def bridge_todoist_read(
    filter: str = "today",
    project: str = "",
    limit: int = 20,
) -> str:
    """Read Todoist tasks with optional filter."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    params: dict[str, Any] = {}
    if filter:
        params["filter"] = filter
    if project:
        params["filter"] = f"#{project}" if not filter else f"{filter} & #{project}"

    result = await _todoist_request("GET", "/tasks", params=params)
    if "error" in result:
        return json.dumps(result)

    tasks_raw = result.get("results", []) if isinstance(result, dict) else result if isinstance(result, list) else []
    tasks = [_todoist_format_task(t) for t in tasks_raw[:limit]]
    return json.dumps({
        "status": "ok",
        "backend": "todoist",
        "tasks": tasks,
        "count": len(tasks),
        "filter_used": filter or "all",
    })


@mcp.tool(
    name="bridge_todoist_create",
    description=(
        "Create a new Todoist task. Requires MEDIUM approval. "
        "Provide content (title), optional description, due_string ('today', 'tomorrow', 'next monday'), "
        "priority (1=normal, 4=urgent), project_id (numeric Todoist project ID), labels."
    ),
)
async def bridge_todoist_create(
    content: str,
    description: str = "",
    due_string: str = "",
    priority: int = 1,
    project_id: str = "",
    labels: str = "",
) -> str:
    """Create a Todoist task (approval-gated)."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else []
    prio_names = {1: "Normal", 2: "Mittel", 3: "Hoch", 4: "Dringend"}

    approval_body = {
        "agent_id": _agent_id,
        "action": "todoist_create",
        "target": "Todoist",
        "description": f"Neue Aufgabe: {content}" + (f" (faellig: {due_string})" if due_string else ""),
        "risk_level": "medium",
        "payload": {
            "content": content,
            "description": description,
            "due_string": due_string,
            "priority": priority,
            "priority_name": prio_names.get(priority, "Normal"),
            "project_id": project_id,
            "labels": label_list,
        },
        "timeout_seconds": 300,
    }
    try:
        resp = await _bridge_post("/approval/request", json=approval_body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "auto_approved":
            body: dict[str, Any] = {"content": content}
            if description:
                body["description"] = description
            if due_string:
                body["due_string"] = due_string
            if priority:
                body["priority"] = priority
            if label_list:
                body["labels"] = label_list
            if project_id:
                body["project_id"] = project_id
            result = await _todoist_request("POST", "/tasks", json_body=body)
            if "error" in result:
                return json.dumps({"status": "failed", "error": result["error"], "source": "todoist"})
            return json.dumps({
                "status": "created",
                "auto_approved": True,
                "standing_approval_id": data.get("standing_approval_id", ""),
                "task": _todoist_format_task(result),
                "backend": "todoist",
            })
        return json.dumps({
            "status": "pending_approval",
            "request_id": data.get("request_id", ""),
            "message": f"Aufgabe '{content}' wartet auf Genehmigung.",
        })
    except Exception as exc:
        return json.dumps({"error": f"Approval request failed: {exc}"})


@mcp.tool(
    name="bridge_todoist_execute",
    description=(
        "Execute a previously approved Todoist action. "
        "Works for: todoist_create, todoist_update, todoist_delete. "
        "Only works if approval status is 'approved'."
    ),
)
async def bridge_todoist_execute(request_id: str) -> str:
    """Execute approved Todoist action."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        resp = await _bridge_get(f"/approval/{request_id}")
        resp.raise_for_status()
        approval = resp.json()
    except Exception as exc:
        return json.dumps({"error": f"Could not check approval: {exc}"})

    if approval.get("status") != "approved":
        return json.dumps({
            "error": f"Aktion nicht genehmigt. Status: {approval.get('status', 'unknown')}",
            "request_id": request_id,
        })

    approval_agent_id = str(approval.get("agent_id", "")).strip()
    if approval_agent_id and approval_agent_id != _agent_id:
        return json.dumps({
            "error": (
                f"Approval gehoert zu Agent '{approval_agent_id}', "
                f"nicht zu '{_agent_id}'."
            ),
            "request_id": request_id,
        })

    action = approval.get("action", "")
    payload = approval.get("payload", {})

    if action == "todoist_create":
        body: dict[str, Any] = {"content": payload.get("content", "")}
        if payload.get("description"):
            body["description"] = payload["description"]
        if payload.get("due_string"):
            body["due_string"] = payload["due_string"]
        if payload.get("priority"):
            body["priority"] = payload["priority"]
        if payload.get("labels"):
            body["labels"] = payload["labels"]
        if payload.get("project_id"):
            body["project_id"] = payload["project_id"]
        result = await _todoist_request("POST", "/tasks", json_body=body)
        if "error" in result:
            return json.dumps({"status": "failed", "request_id": request_id, "error": result["error"]})
        return json.dumps({
            "status": "created",
            "request_id": request_id,
            "task": _todoist_format_task(result),
            "backend": "todoist",
        })

    elif action == "todoist_update":
        task_id = payload.get("task_id", "")
        if not task_id:
            return json.dumps({"error": "task_id missing in payload", "request_id": request_id})
        body = {}
        for key in ("content", "description", "due_string", "priority"):
            if payload.get(key):
                body[key] = payload[key]
        if not body:
            return json.dumps({
                "error": "Keine Aenderungen im Approval-Payload gefunden.",
                "request_id": request_id,
            })
        result = await _todoist_request("POST", f"/tasks/{task_id}", json_body=body)
        if "error" in result:
            return json.dumps({"status": "failed", "request_id": request_id, "error": result["error"]})
        task_data = _todoist_format_task(result) if "ok" not in result else {"id": task_id}
        return json.dumps({
            "status": "updated",
            "request_id": request_id,
            "task": task_data,
            "backend": "todoist",
        })

    elif action == "todoist_delete":
        task_id = payload.get("task_id", "")
        if not task_id:
            return json.dumps({"error": "task_id missing in payload", "request_id": request_id})
        result = await _todoist_request("DELETE", f"/tasks/{task_id}")
        if "error" in result:
            return json.dumps({"status": "failed", "request_id": request_id, "error": result["error"]})
        return json.dumps({
            "status": "deleted",
            "request_id": request_id,
            "task_id": task_id,
            "backend": "todoist",
        })

    else:
        return json.dumps({"error": f"Unknown todoist action: {action}", "request_id": request_id})


@mcp.tool(
    name="bridge_todoist_update",
    description=(
        "Update an existing Todoist task. Requires MEDIUM approval. "
        "Provide task_id and fields to change (content, description, due_string, priority)."
    ),
)
async def bridge_todoist_update(
    task_id: str,
    content: str = "",
    description: str = "",
    due_string: str = "",
    priority: int = 0,
) -> str:
    """Update a Todoist task (approval-gated)."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    changes = []
    if content:
        changes.append(f"Titel: {content}")
    if description:
        changes.append("Beschreibung aktualisiert")
    if due_string:
        changes.append(f"Faellig: {due_string}")
    if priority:
        changes.append(f"Prioritaet: {priority}")
    if not changes:
        return json.dumps({
            "error": (
                "Keine Aenderungen angegeben. "
                "Mindestens eines von content, description, due_string oder priority setzen."
            )
        })

    approval_body = {
        "agent_id": _agent_id,
        "action": "todoist_update",
        "target": "Todoist",
        "description": f"Task {task_id} aendern: {', '.join(changes) or 'keine Aenderungen'}",
        "risk_level": "medium",
        "payload": {
            "task_id": task_id,
            "content": content,
            "description": description,
            "due_string": due_string,
            "priority": priority,
        },
        "timeout_seconds": 300,
    }
    try:
        resp = await _bridge_post("/approval/request", json=approval_body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "auto_approved":
            update_body: dict[str, Any] = {}
            if content:
                update_body["content"] = content
            if description:
                update_body["description"] = description
            if due_string:
                update_body["due_string"] = due_string
            if priority:
                update_body["priority"] = priority
            result = await _todoist_request("POST", f"/tasks/{task_id}", json_body=update_body)
            if "error" in result:
                return json.dumps({"status": "failed", "error": result["error"], "source": "todoist"})
            task_data = _todoist_format_task(result) if "ok" not in result else {"id": task_id}
            return json.dumps({
                "status": "updated",
                "auto_approved": True,
                "standing_approval_id": data.get("standing_approval_id", ""),
                "task": task_data,
                "backend": "todoist",
            })
        return json.dumps({
            "status": "pending_approval",
            "request_id": data.get("request_id", ""),
            "message": f"Aenderung an Task {task_id} wartet auf Genehmigung.",
        })
    except Exception as exc:
        return json.dumps({"error": f"Approval request failed: {exc}"})


@mcp.tool(
    name="bridge_todoist_complete",
    description="Mark a Todoist task as completed. No approval needed (reversible via reopen).",
)
async def bridge_todoist_complete(task_id: str) -> str:
    """Mark a task as completed (no approval — reversible)."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    result = await _todoist_request("POST", f"/tasks/{task_id}/close")
    if "error" in result:
        return json.dumps({"status": "failed", "error": result["error"], "source": "todoist"})
    return json.dumps({
        "status": "completed",
        "task_id": task_id,
        "message": f"Task {task_id} als erledigt markiert. Rueckgaengig mit bridge_todoist_reopen.",
        "backend": "todoist",
    })


@mcp.tool(
    name="bridge_todoist_reopen",
    description="Reopen a completed Todoist task. No approval needed (undo of complete).",
)
async def bridge_todoist_reopen(task_id: str) -> str:
    """Reopen a completed task (no approval — undo of complete)."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    result = await _todoist_request("POST", f"/tasks/{task_id}/reopen")
    if "error" in result:
        return json.dumps({"status": "failed", "error": result["error"], "source": "todoist"})
    return json.dumps({
        "status": "reopened",
        "task_id": task_id,
        "message": f"Task {task_id} wieder geoeffnet.",
        "backend": "todoist",
    })


@mcp.tool(
    name="bridge_todoist_delete",
    description="Delete a Todoist task permanently. Requires HIGH approval (irreversible).",
)
async def bridge_todoist_delete(task_id: str) -> str:
    """Delete a task (HIGH approval — irreversible)."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    approval_body = {
        "agent_id": _agent_id,
        "action": "todoist_delete",
        "target": "Todoist",
        "description": f"Task {task_id} PERMANENT loeschen (nicht rueckgaengig machbar)",
        "risk_level": "high",
        "payload": {"task_id": task_id},
        "timeout_seconds": 300,
    }
    try:
        resp = await _bridge_post("/approval/request", json=approval_body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "auto_approved":
            result = await _todoist_request("DELETE", f"/tasks/{task_id}")
            if "error" in result:
                return json.dumps({"status": "failed", "error": result["error"], "source": "todoist"})
            return json.dumps({
                "status": "deleted",
                "auto_approved": True,
                "standing_approval_id": data.get("standing_approval_id", ""),
                "task_id": task_id,
                "backend": "todoist",
            })
        return json.dumps({
            "status": "pending_approval",
            "request_id": data.get("request_id", ""),
            "message": f"Loeschung von Task {task_id} wartet auf Genehmigung (HIGH).",
        })
    except Exception as exc:
        return json.dumps({"error": f"Approval request failed: {exc}"})


# ---------------------------------------------------------------------------
# Browser Automation (Phase A)
# ---------------------------------------------------------------------------


def _extract_page_date(html: str) -> str | None:
    """Extract publication/update date from HTML meta tags.

    Checks: <meta name="date">, <meta property="article:published_time">,
    <meta property="og:updated_time">, <time datetime="...">,
    Schema.org datePublished/dateModified.
    Returns ISO date string or None.
    """
    import re as _re
    patterns = [
        r'<meta\s+(?:name|property)=["\'](?:date|article:published_time|article:modified_time|og:updated_time|dcterms\.modified)["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\']\s+(?:name|property)=["\'](?:date|article:published_time|article:modified_time|og:updated_time)["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateModified"\s*:\s*"([^"]+)"',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        m = _re.search(pat, html[:20000], _re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Normalize: take first 10 chars if ISO-like
            if len(raw) >= 10 and raw[4:5] == "-":
                return raw[:10]
            return raw
    return None


def _freshness_warning(page_date: str | None) -> str | None:
    """Return warning if page_date is older than 6 months."""
    if not page_date:
        return None
    try:
        # Parse YYYY-MM-DD
        dt = datetime.strptime(page_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt).days
        if age_days > 180:
            months = age_days // 30
            return f"Page date {page_date} is ~{months} months old. Data may be outdated."
    except (ValueError, TypeError):
        pass
    return None


@mcp.tool(
    name="bridge_browser_research",
    description=(
        "Navigate to a URL, capture browser snapshot + screenshot, and return "
        "structured research data. No approval required."
    ),
)
async def bridge_browser_research(url: str, question: str) -> str:
    """Run read-only browser research using Playwright MCP tools."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    target_url = (url or "").strip()
    user_question = (question or "").strip()
    if not target_url or not user_question:
        return json.dumps({
            "status": "error",
            "error": "url and question are required",
            "source": "browser",
        })
    if not _valid_http_url(target_url):
        return json.dumps({
            "status": "error",
            "error": "url must start with http:// or https://",
            "source": "browser",
        })

    screenshot_path = f"/tmp/bridge_browser_research_{time.time_ns()}.png"

    # All three calls in ONE subprocess to preserve browser state
    results = await _playwright_mcp_session([
        ("browser_navigate", {"url": target_url}),
        ("browser_snapshot", {}),
        ("browser_take_screenshot", {"filename": screenshot_path, "fullPage": True}),
    ])
    navigate, snapshot, screenshot = results[0], results[1], results[2]

    if navigate.get("error"):
        return json.dumps({
            "status": "error",
            "step": "browser_navigate",
            "error": navigate["error"],
            "source": "browser",
        })

    if snapshot.get("error"):
        return json.dumps({
            "status": "error",
            "step": "browser_snapshot",
            "error": snapshot["error"],
            "source": "browser",
        })

    if screenshot.get("error"):
        # Retry without filename/fullPage in a separate session
        retry = await _playwright_mcp_session([
            ("browser_navigate", {"url": target_url}),
            ("browser_take_screenshot", {}),
        ])
        screenshot = retry[1] if len(retry) > 1 else screenshot
    if screenshot.get("error"):
        return json.dumps({
            "status": "error",
            "step": "browser_take_screenshot",
            "error": screenshot["error"],
            "source": "browser",
        })

    reported_path = _extract_png_path(screenshot.get("text", ""))
    if reported_path:
        screenshot_path = reported_path

    snapshot_text = snapshot.get("text", "")
    truncated = len(snapshot_text) > 12000
    page_date = _extract_page_date(snapshot_text)
    freshness = _freshness_warning(page_date)
    result: dict[str, object] = {
        "status": "ok",
        "backend": "playwright_mcp",
        "source": "browser",
        "url": target_url,
        "question": user_question,
        "screenshot_path": screenshot_path,
        "snapshot": snapshot_text[:12000],
        "snapshot_truncated": truncated,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "page_date": page_date,
        "analysis_hint": "Use snapshot + screenshot_path to answer the question with concrete evidence.",
    }
    if freshness:
        result["freshness_warning"] = freshness
    return json.dumps(result)


@mcp.tool(
    name="bridge_browser_action",
    description=(
        "Create approval request for a browser action with consequence. "
        "Captures a screenshot preview before requesting approval."
    ),
)
async def bridge_browser_action(
    url: str,
    action_description: str,
    risk_level: str = "medium",
) -> str:
    """Create approval request for consequential browser actions."""
    if _agent_id is None:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_action",
            raw_payload={"status": "error", "error": "Not registered. Call bridge_register first."},
        )

    target_url = (url or "").strip()
    action_text = (action_description or "").strip()
    normalized_risk = _normalize_browser_risk_level(risk_level)
    run_id = _default_run_id("browser_action")
    _ensure_execution_run(
        run_id=run_id,
        source="browser",
        tool_name="bridge_browser_action",
        meta={"url": target_url, "risk_level": normalized_risk or risk_level},
    )
    if not target_url or not action_text:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_action",
            run_id=run_id,
            raw_payload={
                "status": "error",
                "error": "url and action_description are required",
                "source": "browser",
            },
            input_summary={"url": target_url, "risk_level": normalized_risk or risk_level},
        )
    if not _valid_http_url(target_url):
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_action",
            run_id=run_id,
            raw_payload={
                "status": "error",
                "error": "url must start with http:// or https://",
                "source": "browser",
            },
            input_summary={"url": target_url, "risk_level": normalized_risk or risk_level},
        )
    if not normalized_risk:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_action",
            run_id=run_id,
            raw_payload={
                "status": "error",
                "error": "risk_level must be one of: medium, high, critical",
                "source": "browser",
            },
            input_summary={"url": target_url, "risk_level": risk_level},
        )

    screenshot_path = f"/tmp/bridge_browser_action_{time.time_ns()}.png"

    # Navigate + screenshot in ONE subprocess to preserve browser state
    results = await _playwright_mcp_session([
        ("browser_navigate", {"url": target_url}),
        ("browser_take_screenshot", {"filename": screenshot_path, "fullPage": True}),
    ])
    navigate, screenshot = results[0], results[1]

    if navigate.get("error"):
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_action",
            run_id=run_id,
            raw_payload={
                "status": "error",
                "step": "browser_navigate",
                "error": navigate["error"],
                "source": "browser",
            },
            input_summary={"url": target_url, "risk_level": normalized_risk},
        )

    if screenshot.get("error"):
        # Retry without filename/fullPage in a separate session
        retry = await _playwright_mcp_session([
            ("browser_navigate", {"url": target_url}),
            ("browser_take_screenshot", {}),
        ])
        screenshot = retry[1] if len(retry) > 1 else screenshot
    if screenshot.get("error"):
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_action",
            run_id=run_id,
            raw_payload={
                "status": "error",
                "step": "browser_take_screenshot",
                "error": screenshot["error"],
                "source": "browser",
            },
            input_summary={"url": target_url, "risk_level": normalized_risk},
        )

    reported_path = _extract_png_path(screenshot.get("text", ""))
    if reported_path:
        screenshot_path = reported_path

    approval_body = {
        "agent_id": _agent_id,
        "action": "browser_action",
        "target": target_url,
        "description": f"Browser action on {target_url}: {action_text[:140]}",
        "risk_level": normalized_risk,
        "payload": {
            "url": target_url,
            "action_description": action_text,
            "screenshot_path": screenshot_path,
        },
        "timeout_seconds": 300,
    }

    try:
        resp = await _bridge_post("/approval/request", json=approval_body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "auto_approved":
            return _structured_action_json(
                source="browser",
                tool_name="bridge_browser_action",
                run_id=run_id,
                raw_payload={
                    "status": "auto_approved",
                    "standing_approval_id": data.get("standing_approval_id", ""),
                    "source": "browser",
                    "screenshot_path": screenshot_path,
                    "message": "Browser action auto-approved via Standing Approval. Execute browser_* tools directly.",
                },
                input_summary={"url": target_url, "risk_level": normalized_risk},
            )
        request_id = data.get("request_id")
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_action",
            run_id=run_id,
            raw_payload={
                "status": "pending_approval",
                "request_id": request_id,
                "risk_level": normalized_risk,
                "source": "browser",
                "screenshot_path": screenshot_path,
                "message": (
                    f"Browser action awaits Leo's approval. "
                    f"Use bridge_approval_wait('{request_id}') and execute raw browser_* tool after approval."
                ),
            },
            input_summary={"url": target_url, "risk_level": normalized_risk},
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_action",
            run_id=run_id,
            raw_payload={
                "status": "error",
                "error": str(exc),
                "source": "browser",
            },
            input_summary={"url": target_url, "risk_level": normalized_risk},
        )


# ---------------------------------------------------------------------------
# Stealth Browser Tools (8)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="bridge_stealth_start",
    description=(
        "Start a stealth browser session. For Tor: just pass proxy='socks5://127.0.0.1:9050' — "
        "Firefox with resistFingerprinting, Tor UA, 1000x900 viewport, DNS protection, and "
        "navigation jitter are set AUTOMATICALLY. No engine selection needed. "
        "For normal browsing: engine='camoufox' (0% detection, default). "
        "Returns session_id for subsequent calls. Max 3 concurrent sessions."
    ),
)
async def bridge_stealth_start(
    proxy: str = "",
    user_agent: str = "",
    headless: bool = True,
    profile: str = "",
    engine: str = "camoufox",
) -> str:
    """Start stealth browser. engine: 'camoufox' (0% detection), 'firefox' (Tor-optimized), 'patchright' (Chromium).
    AUTO-DETECTION: If proxy contains port 9050 (Tor), automatically uses Firefox with
    resistFingerprinting, Tor UA, 1000x900 viewport, DNS leak protection, navigation jitter.
    Agent only needs: bridge_stealth_start(proxy="socks5://127.0.0.1:9050") — everything else is automatic.
    """
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    if len(_stealth_sessions) >= _STEALTH_MAX_SESSIONS:
        return json.dumps({
            "status": "error",
            "error": f"max sessions ({_STEALTH_MAX_SESSIONS}) reached. Close a session first.",
        })

    _engine = engine.lower()

    # AUTO-TOR-DETECTION: If proxy is Tor (port 9050), force Firefox engine
    _is_tor_proxy = bool(proxy) and ("9050" in proxy or "tor" in proxy.lower())
    if _is_tor_proxy and _engine != "firefox":
        _engine = "firefox"  # Override: Tor MUST use Firefox (resistFingerprinting)

    # ===== FIREFOX TOR ENGINE (resistFingerprinting + Tor SOCKS) =====
    if _engine == "firefox":
        try:
            from patchright.async_api import async_playwright as _ff_pw
        except ImportError:
            try:
                from playwright.async_api import async_playwright as _ff_pw
            except ImportError:
                return json.dumps({"status": "error", "error": "playwright/patchright not installed"})
        try:
            _is_proxy_session = bool(proxy)
            pw = await _ff_pw().start()

            # Tor-optimized Firefox preferences (resistFingerprinting + forensic hardening)
            _ff_prefs = {
                "privacy.resistFingerprinting": True,
                "privacy.resistFingerprinting.letterboxing": True,
                "privacy.trackingprotection.enabled": True,
                "privacy.trackingprotection.socialtracking.enabled": True,
                "media.peerconnection.enabled": False,           # Kill WebRTC
                "media.peerconnection.ice.default_address_only": True,
                "media.peerconnection.ice.no_host": True,
                "media.navigator.enabled": False,                # Hide media devices
                "geo.enabled": False,                            # No geolocation
                "dom.battery.enabled": False,                    # No battery API
                "dom.webaudio.enabled": False,                   # Kill AudioContext (fingerprint)
                "dom.netinfo.enabled": False,                    # Kill NetworkInfo API
                "network.dns.disablePrefetch": True,             # No DNS prefetch
                "network.prefetch-next": False,                  # No link prefetch
                "network.proxy.socks_remote_dns": True,          # DNS through SOCKS (critical!)
                "network.trr.mode": 3,                           # DNS-over-HTTPS only (no system DNS fallback!)
                "javascript.options.wasm": False,                # No WebAssembly (fingerprint vector)
                "webgl.disabled": True,                          # No WebGL (fingerprint vector)
            }

            ff_launch: dict[str, Any] = {
                "headless": headless,
                "firefox_user_prefs": _ff_prefs,
            }
            if proxy:
                ff_launch["proxy"] = {"server": proxy}

            browser = await pw.firefox.launch(**ff_launch)
            # Tor Browser viewport: 1000x900 (letterboxing standard)
            _tor_viewport = {"width": 1000, "height": 900}
            context = await browser.new_context(
                locale="en-US",
                timezone_id="Etc/UTC",
                viewport=_tor_viewport,
                screen={"width": 1000, "height": 900},
                # Tor Browser UA: Windows (all Tor Browser users share the SAME UA regardless of OS)
                # ESR 128 = current Tor Browser stable. Linux platform mismatch is accepted
                # because resistFingerprinting normalizes navigator.platform to "Linux x86_64"
                user_agent="Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0",
            )
            page = await context.new_page()

            # DNS Leak Test if Tor proxy
            dns_leak_test = None
            if _is_proxy_session and "9050" in proxy:
                try:
                    async with httpx.AsyncClient(
                        proxy=f"socks5://127.0.0.1:{_TOR_SOCKS_PORT}",
                        timeout=10.0,
                    ) as _dns_client:
                        _ip_resp = await _dns_client.get("https://ifconfig.me/ip")
                        tor_ip = _ip_resp.text.strip()
                    async with httpx.AsyncClient(timeout=5.0) as _real_client:
                        _real_resp = await _real_client.get("https://ifconfig.me/ip")
                        real_ip = _real_resp.text.strip()
                    dns_leak_test = {
                        "tor_ip": tor_ip,
                        "real_ip": real_ip,
                        "leaked": tor_ip == real_ip,
                        "result": "FAIL" if tor_ip == real_ip else "PASS",
                    }
                except Exception as _dns_exc:
                    dns_leak_test = {"error": str(_dns_exc)}

            # Tor: NEVER persist cookies (forensic isolation)
            safe_profile = ""

            session_id = uuid.uuid4().hex[:8]
            session = StealthSession(
                session_id=session_id,
                browser=browser,
                page=page,
                pw_context=pw,
                agent_id=_agent_id,
                profile="",  # Tor: no cookie persistence (forensic hardening)
                is_proxy=_is_proxy_session,
                firefox_like=True,
            )
            _stealth_sessions[session_id] = session

            if session.profile:
                await _stealth_load_cookies(session)

            result: dict[str, Any] = {
                "status": "ok",
                "session_id": session_id,
                "engine": "firefox",
                "resistFingerprinting": True,
                "headless": headless,
                "proxy": bool(proxy),
                "prefs_applied": len(_ff_prefs),
            }
            if dns_leak_test:
                result["dns_leak_test"] = dns_leak_test
            # Auto-start traffic padding for Tor sessions
            if _is_proxy_session and "9050" in proxy:
                _start_tor_padding(session_id)
                result["traffic_padding"] = True
            return json.dumps(result)
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Firefox Tor launch failed: {exc}"})

    _use_camoufox = _engine == "camoufox"

    # ===== CAMOUFOX ENGINE (0% detection — Firefox-based, C++ level stealth) =====
    if _use_camoufox:
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            return json.dumps({
                "status": "error",
                "error": "camoufox not installed. Run: pip install camoufox && python -m camoufox fetch",
            })
        try:
            _is_proxy_session = bool(proxy)
            cf_kwargs: dict[str, Any] = {
                "headless": "virtual" if headless else False,  # Xvfb virtual display (0% detection)
                "humanize": True,
                "os": "linux",
            }
            if proxy:
                cf_kwargs["proxy"] = {"server": proxy}

            cf_ctx = AsyncCamoufox(**cf_kwargs)
            browser_or_context = await cf_ctx.__aenter__()

            # Camoufox returns BrowserContext directly
            if hasattr(browser_or_context, "new_page"):
                context = browser_or_context
                browser = getattr(context, "browser", None) or context
            else:
                browser = browser_or_context
                context = await browser.new_context()

            page = await context.new_page()

            # Validate profile name
            safe_profile = ""
            if profile:
                import re as _re_profile
                safe_profile = _re_profile.sub(r"[^a-zA-Z0-9_-]", "", profile.strip())[:50]

            session_id = uuid.uuid4().hex[:8]
            session = StealthSession(
                session_id=session_id,
                browser=browser,
                page=page,
                pw_context=cf_ctx,  # Store for cleanup
                agent_id=_agent_id,
                profile="" if _is_proxy_session else safe_profile,
                is_proxy=_is_proxy_session,
                firefox_like=True,  # Camoufox is Firefox-based
            )
            _stealth_sessions[session_id] = session

            # Load persisted cookies if profile specified
            if session.profile:
                await _stealth_load_cookies(session)

            return json.dumps({
                "status": "ok",
                "session_id": session_id,
                "engine": "camoufox",
                "detection_score": "0%",
                "headless": headless,
                "humanize": True,
                "proxy": bool(proxy),
            })
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"camoufox launch failed: {exc}"})

    # ===== PATCHRIGHT/PLAYWRIGHT ENGINE (Chromium with JS spoofing) =====
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return json.dumps({
                "status": "error",
                "error": "patchright/playwright not installed. Run: pip install patchright && patchright install chromium",
            })

    try:
        pw = await async_playwright().start()
        args = ["--disable-blink-features=AutomationControlled"]
        # NOTE: headless is controlled via Playwright's native parameter,
        # not --headless=new CLI arg (which breaks bundled Chromium navigation)

        # P0 Fix: Inject OPSEC args when proxy is set (prevents DNS/WebRTC leaks)
        _is_proxy_session = bool(proxy)
        if _is_proxy_session:
            args.extend(_STEALTH_PROXY_OPSEC_ARGS)

        # P1 Fix: Set UA via CLI arg — applies to ALL contexts including Workers
        # (CDP Emulation.setUserAgentOverride only affects main thread, not Workers)
        if _is_proxy_session and not user_agent:
            _effective_ua = _STEALTH_TOR_UA
        else:
            _effective_ua = user_agent or _STEALTH_DEFAULT_UA
        _firefox_like_identity = _is_proxy_session or _stealth_ua_is_firefox_like(_effective_ua)
        args.append(f"--user-agent={_effective_ua}")

        launch_kwargs: dict[str, Any] = {
            "headless": headless,  # Native Playwright headless (not --headless=new CLI arg)
            # NOTE: "channel": "chrome" removed — System Chrome has CDP version
            # mismatch, breaking Page.navigate (goto). Using bundled Chromium.
            "args": args,
        }
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}

        browser = await pw.chromium.launch(**launch_kwargs)

        # P1 Fix: Create context with OPSEC defaults (timezone, locale)
        # Prevents Europe/Berlin timezone leak and "de" language leak
        # Chromium can surface q-values from Accept-Language back into navigator.languages
        # on the main page while workers keep a clean ["en-US"], so keep the declared
        # language header minimal to avoid cross-realm drift.
        accept_lang = "en-US"
        ctx_kwargs: dict[str, Any] = {}
        ctx_kwargs["user_agent"] = _effective_ua
        ctx_kwargs["extra_http_headers"] = {"Accept-Language": accept_lang}
        # Keep navigator.language / navigator.languages coherent with the declared header.
        ctx_kwargs["locale"] = "en-US"
        if _firefox_like_identity:
            ctx_kwargs["timezone_id"] = "Etc/UTC"
        if _is_proxy_session:
            # P1 Fix: Realistic viewport (avoids 1280x720 headless default where inner=outer=avail)
            ctx_kwargs["viewport"] = {"width": 1920, "height": 1040}
            ctx_kwargs["screen"] = {"width": 1920, "height": 1080}
        if _is_proxy_session or _firefox_like_identity:
            # Privacy hardening: block service workers for proxy/Tor sessions to reduce
            # persistent background fetches and worker-side fingerprint drift.
            ctx_kwargs["service_workers"] = "block"
        context = await browser.new_context(**ctx_kwargs)

        # P0 Fix: Block WebRTC-related permissions to prevent IP leaks
        if _is_proxy_session:
            await context.grant_permissions([])
        if _firefox_like_identity:
            await _install_stealth_worker_route(context)

        # Create page with CDP stealth patches
        page = await context.new_page()
        await _stealth_apply_page_cdp_profile(
            page,
            user_agent=_effective_ua,
            accept_lang=accept_lang,
            firefox_like=_firefox_like_identity,
        )
        if _firefox_like_identity:
            context.on(
                "page",
                lambda popup_page: asyncio.create_task(
                    _stealth_apply_page_cdp_profile(
                        popup_page,
                        user_agent=_effective_ua,
                        accept_lang=accept_lang,
                        firefox_like=True,
                    )
                ),
            )
        # Stealth scripts via context.add_init_script() — covers Workers + iframes
        # Stealth scripts injected via add_init_script (fires on every new document/iframe)
        for _script in _stealth_scripts_for_session(is_proxy=_is_proxy_session, firefox_like=_firefox_like_identity):
            await context.add_init_script(_script)
        # _STEALTH_HEADLESS_FIX now included in _stealth_scripts_for_session (P0 Fingerprint-Haertung)
        # Execute immediately on current page (init_script only fires on next navigation)
        cdp = await context.new_cdp_session(page)
        for _script in _stealth_scripts_for_session(is_proxy=_is_proxy_session, firefox_like=_firefox_like_identity):
            await cdp.send("Runtime.evaluate", {
                "expression": _script,
                "allowUnsafeEvalBlockedByCSP": True,
            })

        # Validate profile name (safe chars only)
        safe_profile = ""
        if profile:
            import re as _re_profile
            safe_profile = _re_profile.sub(r"[^a-zA-Z0-9_-]", "", profile.strip())[:50]

        session_id = uuid.uuid4().hex[:8]
        session = StealthSession(
            session_id=session_id,
            browser=browser,
            page=page,
            pw_context=pw,
            agent_id=_agent_id,
            profile="" if _is_proxy_session else safe_profile,  # P1 Fix: no cookie persistence for proxy sessions
            is_proxy=_is_proxy_session,
            firefox_like=_firefox_like_identity,
        )
        _stealth_sessions[session_id] = session

        # Load persisted cookies if profile specified (P1: skip for proxy sessions)
        if session.profile:
            await _stealth_load_cookies(session)

        # Start cleanup task if not running
        global _stealth_cleanup_task
        if _stealth_cleanup_task is None or _stealth_cleanup_task.done():
            _stealth_cleanup_task = asyncio.create_task(_stealth_cleanup_loop())

        log.info("Stealth session %s started (proxy=%s, headless=%s, profile=%s, opsec=%s)", session_id, proxy or "none", headless, session.profile or "none", _is_proxy_session)
        return json.dumps({"status": "ok", "session_id": session_id, "profile": session.profile or None, "opsec_hardened": _is_proxy_session})

    except Exception as exc:
        # Cleanup partially created resources on failure
        try:
            if "browser" in locals():
                await browser.close()
            if "pw" in locals():
                await pw.stop()
        except Exception:
            pass
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_stealth_goto",
    description="Navigate to URL in stealth session. Returns page title and content preview.",
)
async def bridge_stealth_goto(session_id: str, url: str, timeout: int = 30000) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    session = _get_stealth_session(session_id)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    if not _valid_http_url(url):
        return json.dumps({"status": "error", "error": f"invalid URL: must start with http:// or https://"})

    try:
        # Forensic hardening: human-like navigation delay for Tor/proxy sessions
        if session.is_proxy or session.firefox_like:
            _nav_jitter = random.gauss(2.5, 0.8)  # Mean 2.5s, std 0.8s
            _nav_jitter = max(0.5, min(5.0, _nav_jitter))  # Clamp 0.5-5.0s
            await asyncio.sleep(_nav_jitter)

        response = await session.page.goto(url, wait_until="commit", timeout=timeout)
        _nav_scripts = _stealth_scripts_for_session(
            is_proxy=session.is_proxy,
            firefox_like=session.firefox_like,
        )
        # First injection: immediately after commit (before page JS runs)
        for _script in _nav_scripts:
            try:
                await session.page.evaluate(_script)
            except Exception:
                pass  # Best-effort — some scripts may fail on about:blank etc.
        # Wait for page to finish loading
        try:
            await session.page.wait_for_load_state("load", timeout=timeout)
        except Exception:
            pass  # Timeout on load is acceptable — page may be slow
        # Second injection: after load complete — browser may reset prototypes during load
        for _script in _nav_scripts:
            try:
                await session.page.evaluate(_script)
            except Exception:
                pass

        title = await session.page.title()
        content = await session.page.content()
        content_preview = content[:12000] if len(content) > 12000 else content
        response_headers = dict(response.headers) if response else {}
        bot_protection = _detect_bot_protection(content, response_headers)
        challenge_detected = _is_bot_challenge_page(content)

        result: dict[str, Any] = {
            "status": "ok",
            "title": title,
            "url": session.page.url,
            "content_preview": content_preview,
            "challenge_detected": challenge_detected,
            "response_status": response.status if response else None,
        }
        if bot_protection:
            result["bot_protection"] = bot_protection
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_stealth_content",
    description="Get current page HTML content from stealth session.",
)
async def bridge_stealth_content(session_id: str) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    session = _get_stealth_session(session_id)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    try:
        title = await session.page.title()
        content = await session.page.content()
        content_truncated = content[:50000] if len(content) > 50000 else content
        page_date = _extract_page_date(content)
        freshness = _freshness_warning(page_date)

        result: dict[str, object] = {
            "status": "ok",
            "title": title,
            "url": session.page.url,
            "content": content_truncated,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "page_date": page_date,
        }
        if freshness:
            result["freshness_warning"] = freshness
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_stealth_fingerprint_snapshot",
    description="Capture a browser-level fingerprint snapshot from a stealth session for lab analysis.",
)
async def bridge_stealth_fingerprint_snapshot(session_id: str) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    session = _get_stealth_session(session_id)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    try:
        snapshot = await session.page.evaluate(_BROWSER_FINGERPRINT_SNAPSHOT_SCRIPT)
        return json.dumps({
            "status": "ok",
            "session_id": session_id,
            "snapshot": snapshot,
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_stealth_screenshot",
    description="Take screenshot of current page in stealth session. Returns file path.",
)
async def bridge_stealth_screenshot(session_id: str, full_page: bool = True) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    session = _get_stealth_session(session_id)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    try:
        path = f"/tmp/stealth_{session_id}_{time.time_ns()}.png"
        await session.page.screenshot(path=path, full_page=full_page)
        return json.dumps({"status": "ok", "path": path})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_stealth_click",
    description="Click element by CSS selector in stealth session.",
)
async def bridge_stealth_click(session_id: str, selector: str) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    session = _get_stealth_session(session_id)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    try:
        await session.page.click(selector, timeout=10000)
        # Wait for potential navigation after click
        try:
            await session.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass  # No navigation happened — that's fine
        return json.dumps({"status": "ok", "selector": selector})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_stealth_fill",
    description="Fill input field by CSS selector in stealth session.",
)
async def bridge_stealth_fill(session_id: str, selector: str, value: str) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    session = _get_stealth_session(session_id)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    try:
        await session.page.fill(selector, value, timeout=10000)
        return json.dumps({"status": "ok", "selector": selector, "value_length": len(value)})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_stealth_evaluate",
    description="Execute JavaScript on page in stealth session. Returns result.",
)
async def bridge_stealth_evaluate(session_id: str, expression: str) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})
    log.info("[AUDIT] bridge_stealth_evaluate by=%s session=%s expr=%s", _agent_id, session_id, expression[:200])

    session = _get_stealth_session(session_id)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    try:
        result = await session.page.evaluate(expression)
        return json.dumps({"status": "ok", "result": result})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_stealth_file_upload",
    description=(
        "Upload a file via a file input element in a stealth browser session. "
        "Selector should target an <input type='file'> element."
    ),
)
async def bridge_stealth_file_upload(session_id: str, selector: str, file_path: str) -> str:
    """Upload file to input element in stealth session."""
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    session = _get_stealth_session(session_id)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    path = os.path.expanduser(file_path.strip())
    if not os.path.isfile(path):
        return json.dumps({"status": "error", "error": f"File not found: {path}"})

    try:
        await session.page.set_input_files(selector, path, timeout=10000)
        file_size = os.path.getsize(path)
        return json.dumps({
            "status": "ok", "selector": selector,
            "file": path, "size_bytes": file_size,
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_stealth_close",
    description="Close stealth browser session and free resources.",
)
async def bridge_stealth_close(session_id: str) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    session = _stealth_sessions.pop(session_id, None)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    # Stop traffic padding if active
    _stop_tor_padding(session_id)

    try:
        # Save cookies before closing
        dropped = _drop_unified_stealth_sessions(session_id)
        errors: list[str] = []
        cookies_saved = False
        try:
            await _stealth_save_cookies(session)
            cookies_saved = bool(session.profile)
        except Exception as exc:
            errors.append(f"cookie_save: {exc}")
        errors.extend(await _close_stealth_runtime(session))

        payload: dict[str, Any] = {
            "session_id": session_id,
            "cookies_saved": cookies_saved,
        }
        if dropped:
            payload["dropped_unified_sessions"] = dropped
            log.info("Pruned unified sessions after direct stealth close: %s", ", ".join(sorted(dropped)))

        if errors:
            payload["status"] = "error"
            payload["error"] = "; ".join(errors)
            return json.dumps(payload)

        log.info("Stealth session %s closed by agent %s (profile=%s)", session_id, _agent_id, session.profile or "none")
        payload["status"] = "ok"
        return json.dumps(payload)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# CAPTCHA Solver Tool
# ---------------------------------------------------------------------------

_CAPSOLVER_CONFIG_PATH = os.path.expanduser("~/.config/bridge/capsolver_account.json")
_CAPSOLVER_API = "https://api.capsolver.com"
_CAPSOLVER_TASK_TYPES = {
    "recaptcha_v2": "ReCaptchaV2TaskProxyLess",
    "recaptcha_v3": "ReCaptchaV3TaskProxyLess",
    "turnstile": "AntiTurnstileTaskProxyLess",
    "hcaptcha": "HCaptchaTaskProxyLess",
    "funcaptcha": "FunCaptchaTaskProxyLess",
    "datadome": "DatadomeSliderTask",
}

# Anti-Captcha: Fallback provider (no website restrictions, supports FunCaptcha + hCaptcha token solving)
_ANTICAPTCHA_CONFIG_PATH = os.path.expanduser("~/.config/bridge/anticaptcha_account.json")
_ANTICAPTCHA_API = "https://api.anti-captcha.com"
_ANTICAPTCHA_TASK_TYPES = {
    "recaptcha_v2": "RecaptchaV2TaskProxyless",
    "recaptcha_v3": "RecaptchaV3TaskProxyless",
    "recaptcha_v2_enterprise": "RecaptchaV2EnterpriseTaskProxyless",
    "recaptcha_v3_enterprise": "RecaptchaV3EnterpriseTaskProxyless",
    "turnstile": "TurnstileTaskProxyless",
    "hcaptcha": "HCaptchaTaskProxyless",
    "funcaptcha": "FunCaptchaTaskProxyless",
}


async def _captcha_solve_with_provider(
    provider: str,
    captcha_type: str,
    website_url: str,
    website_key: str,
    min_score: float = 0.7,
) -> dict[str, Any]:
    """Solve captcha with a specific provider. Returns dict with status/token/error."""
    if provider == "capsolver":
        config_path, api_url, task_types, label = _CAPSOLVER_CONFIG_PATH, _CAPSOLVER_API, _CAPSOLVER_TASK_TYPES, "CAPSolver"
    elif provider == "anticaptcha":
        config_path, api_url, task_types, label = _ANTICAPTCHA_CONFIG_PATH, _ANTICAPTCHA_API, _ANTICAPTCHA_TASK_TYPES, "Anti-Captcha"
    else:
        return {"status": "error", "error": f"unknown provider '{provider}'"}

    if captcha_type not in task_types:
        return {"status": "error", "error": f"unsupported captcha_type '{captcha_type}' for {label}. Supported: {', '.join(task_types)}"}

    # Load API key
    try:
        with open(config_path) as f:
            config = json.load(f)
        api_key = config.get("api_key", "")
        if not api_key:
            return {"status": "error", "error": f"{label} API key not configured"}
    except FileNotFoundError:
        return {"status": "error", "error": f"{label} config not found: {config_path}"}
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "error": f"failed to read {label} config: {exc}"}

    # Build task
    task_data: dict[str, Any] = {
        "type": task_types[captcha_type],
        "websiteURL": website_url,
    }
    if captcha_type == "funcaptcha":
        task_data["websitePublicKey"] = website_key
    else:
        task_data["websiteKey"] = website_key
    if captcha_type in ("recaptcha_v3", "recaptcha_v3_enterprise"):
        task_data["minScore"] = min_score

    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{api_url}/createTask", json={"clientKey": api_key, "task": task_data})
            resp.raise_for_status()
            create_data = resp.json()

            if create_data.get("errorId", 0) != 0:
                return {"status": "error", "error": create_data.get("errorDescription", create_data.get("errorCode", "unknown")), "provider": label}

            task_id = create_data.get("taskId")
            if not task_id:
                return {"status": "error", "error": f"no taskId in {label} createTask response", "provider": label}

            log.info("%s task created: %s (type=%s)", label, task_id, captcha_type)

            # Poll for result (max 120s, 5s interval)
            for _ in range(24):
                await asyncio.sleep(5)
                resp = await client.post(f"{api_url}/getTaskResult", json={"clientKey": api_key, "taskId": task_id})
                resp.raise_for_status()
                result_data = resp.json()

                if result_data.get("errorId", 0) != 0:
                    return {"status": "error", "error": result_data.get("errorDescription", result_data.get("errorCode", "unknown")), "provider": label}

                if result_data.get("status") == "ready":
                    solution = result_data.get("solution", {})
                    token = (
                        solution.get("gRecaptchaResponse")
                        or solution.get("token")
                        or solution.get("cookie")
                        or json.dumps(solution)
                    )
                    solve_time_ms = int((time.time() - start_time) * 1000)
                    log.info("%s solved %s in %dms", label, captcha_type, solve_time_ms)
                    return {"status": "ok", "token": token, "captcha_type": captcha_type, "solve_time_ms": solve_time_ms, "provider": label}

            return {"status": "error", "error": f"{label} timeout after 120s for {captcha_type}", "provider": label}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "provider": label}


@mcp.tool(
    name="bridge_captcha_solve",
    description=(
        "Solve a CAPTCHA using CAPSolver or Anti-Captcha (fallback). "
        "Supported types: recaptcha_v2, recaptcha_v3, turnstile, hcaptcha, funcaptcha, datadome. "
        "Anti-Captcha also supports: recaptcha_v2_enterprise, recaptcha_v3_enterprise. "
        "provider='auto' tries CAPSolver first, falls back to Anti-Captcha on policy blocks. "
        "Returns solution token for injection into page via bridge_stealth_evaluate."
    ),
)
async def bridge_captcha_solve(
    captcha_type: str,
    website_url: str,
    website_key: str,
    min_score: float = 0.7,
    provider: str = "auto",
) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    if not _valid_http_url(website_url):
        return json.dumps({"status": "error", "error": "invalid website_url: must start with http:// or https://"})

    all_types = set(_CAPSOLVER_TASK_TYPES) | set(_ANTICAPTCHA_TASK_TYPES)
    if captcha_type not in all_types:
        return json.dumps({"status": "error", "error": f"unsupported captcha_type '{captcha_type}'. Supported: {', '.join(sorted(all_types))}"})

    valid_providers = ("auto", "capsolver", "anticaptcha")
    if provider not in valid_providers:
        return json.dumps({"status": "error", "error": f"invalid provider '{provider}'. Valid: {', '.join(valid_providers)}"})

    if provider == "capsolver":
        result = await _captcha_solve_with_provider("capsolver", captcha_type, website_url, website_key, min_score)
        return json.dumps(result)
    elif provider == "anticaptcha":
        result = await _captcha_solve_with_provider("anticaptcha", captcha_type, website_url, website_key, min_score)
        return json.dumps(result)
    else:
        # Auto: try CAPSolver first, fallback to Anti-Captcha on error
        if captcha_type in _CAPSOLVER_TASK_TYPES:
            result = await _captcha_solve_with_provider("capsolver", captcha_type, website_url, website_key, min_score)
            if result.get("status") == "ok":
                return json.dumps(result)
            capsolver_error = result.get("error", "")
            log.warning("CAPSolver failed (%s), trying Anti-Captcha fallback", capsolver_error)
        else:
            capsolver_error = f"captcha_type '{captcha_type}' not supported by CAPSolver"

        # Fallback to Anti-Captcha
        if captcha_type in _ANTICAPTCHA_TASK_TYPES:
            result = await _captcha_solve_with_provider("anticaptcha", captcha_type, website_url, website_key, min_score)
            if result.get("status") == "ok":
                result["fallback"] = True
                result["capsolver_error"] = capsolver_error
            return json.dumps(result)
        else:
            return json.dumps({"status": "error", "error": f"captcha_type '{captcha_type}' not supported by any provider. CAPSolver error: {capsolver_error}"})


# ===== NATIVE CAPTCHA SOLVER (kostenlos, keine externen APIs) =====

async def _captcha_solve_hcaptcha_ollama(image_path: str, target_label: str = "") -> dict[str, Any]:
    """Solve hCaptcha image challenge using Ollama LLaVA vision model.

    Sends the image to a local LLaVA model and asks it to classify what's in the image.
    For hCaptcha: target_label is the challenge text (e.g. "Select all images with a bus").
    """
    if not os.path.isfile(image_path):
        return {"status": "error", "error": f"image not found: {image_path}"}
    try:
        import base64 as _b64
        with open(image_path, "rb") as f:
            img_b64 = _b64.b64encode(f.read()).decode()

        prompt = target_label or "What objects do you see in this image? List them."
        payload = {
            "model": "llava",
            "prompt": f"Answer concisely. {prompt}",
            "images": [img_b64],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("http://localhost:11434/api/generate", json=payload)
            if resp.status_code != 200:
                return {"status": "error", "error": f"Ollama returned {resp.status_code}. Is Ollama running? Install: curl -fsSL https://ollama.com/install.sh | sh && ollama pull llava"}
            data = resp.json()
            answer = data.get("response", "").strip()
            if not answer:
                return {"status": "error", "error": "LLaVA returned empty response"}
            return {"status": "ok", "solution": answer, "method": "ollama_llava", "cost": 0}
    except httpx.ConnectError:
        return {"status": "error", "error": "Ollama not running. Start: ollama serve & ollama pull llava"}
    except Exception as exc:
        return {"status": "error", "error": f"hCaptcha Ollama solver failed: {exc}"}


async def _captcha_solve_recaptcha_yolo(image_path: str, target_label: str = "") -> dict[str, Any]:
    """Solve reCAPTCHA v2 image challenge using YOLO object detection.

    Detects objects in the image grid and checks if they match the target label.
    target_label: the challenge text (e.g. "bicycles", "traffic lights", "buses").
    Returns which grid cells contain the target object.
    """
    if not os.path.isfile(image_path):
        return {"status": "error", "error": f"image not found: {image_path}"}
    try:
        from ultralytics import YOLO
    except ImportError:
        return {"status": "error", "error": "ultralytics not installed. Run: pip install ultralytics"}
    try:
        from PIL import Image
        model = YOLO("yolov8n.pt")  # Nano model — fast, auto-downloads on first use
        img = Image.open(image_path)
        w, h = img.size

        results = model(img, verbose=False)
        detections = []
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names[cls_id].lower()
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                detections.append({
                    "class": cls_name,
                    "confidence": round(conf, 3),
                    "center": [round(cx), round(cy)],
                    "bbox": [round(x1), round(y1), round(x2), round(y2)],
                })

        # Map detections to 3x3 or 4x4 grid cells
        target = target_label.lower().strip().rstrip("s")  # "bicycles" → "bicycle"
        grid_size = 3  # reCAPTCHA typically uses 3x3
        cell_w, cell_h = w / grid_size, h / grid_size
        matching_cells = set()
        for det in detections:
            if target and target in det["class"]:
                cx, cy = det["center"]
                col = min(int(cx / cell_w), grid_size - 1)
                row = min(int(cy / cell_h), grid_size - 1)
                matching_cells.add(row * grid_size + col)

        return {
            "status": "ok",
            "solution": {
                "matching_cells": sorted(matching_cells),
                "grid_size": grid_size,
                "target_label": target_label,
                "total_detections": len(detections),
                "detections": detections,
            },
            "method": "yolov8_detect",
            "cost": 0,
        }
    except Exception as exc:
        return {"status": "error", "error": f"YOLO solver failed: {exc}"}


_NATIVE_CAPTCHA_TYPES = ("text", "audio", "recaptcha_v2_audio", "turnstile", "hcaptcha_image", "recaptcha_v2_image")


async def _captcha_solve_text_ocr(image_path: str) -> dict[str, Any]:
    """Solve text-based CAPTCHA using Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image, ImageFilter
    except ImportError:
        return {"status": "error", "error": "pytesseract or Pillow not installed"}
    if not os.path.isfile(image_path):
        return {"status": "error", "error": f"image not found: {image_path}"}
    try:
        img = Image.open(image_path)
        # Pre-process: grayscale + sharpen for better OCR
        img = img.convert("L").filter(ImageFilter.SHARPEN)
        text = pytesseract.image_to_string(img, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789").strip()
        if not text:
            return {"status": "error", "error": "OCR returned empty result"}
        return {"status": "ok", "solution": text, "method": "tesseract_ocr", "cost": 0}
    except Exception as exc:
        return {"status": "error", "error": f"OCR failed: {exc}"}


async def _captcha_solve_audio_whisper(audio_path: str) -> dict[str, Any]:
    """Solve audio CAPTCHA using faster-whisper STT."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {"status": "error", "error": "faster-whisper not installed. Run: pip install faster-whisper"}
    if not os.path.isfile(audio_path):
        return {"status": "error", "error": f"audio file not found: {audio_path}"}
    try:
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, language="en")
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if not text:
            return {"status": "error", "error": "Whisper returned empty transcription"}
        # reCAPTCHA audio: digits only, clean up
        digits = "".join(c for c in text if c.isdigit() or c == " ").strip()
        return {"status": "ok", "solution": digits or text, "method": "whisper_stt", "cost": 0}
    except Exception as exc:
        return {"status": "error", "error": f"Whisper STT failed: {exc}"}


async def _captcha_solve_turnstile_wait(session_id: str) -> dict[str, Any]:
    """Solve Cloudflare Turnstile by waiting — stealth browser auto-solves it."""
    if session_id not in _stealth_sessions:
        return {"status": "error", "error": f"session '{session_id}' not found. Start a stealth session first."}
    page = _stealth_sessions[session_id].page
    try:
        # Turnstile auto-solves in stealth browser. Wait for cf-turnstile-response input.
        for _ in range(30):  # max 30s
            token = await page.evaluate("""() => {
                const input = document.querySelector('input[name="cf-turnstile-response"]');
                return input ? input.value : null;
            }""")
            if token:
                return {"status": "ok", "token": token, "method": "turnstile_auto_solve", "cost": 0}
            await asyncio.sleep(1)
        return {"status": "error", "error": "Turnstile did not auto-solve within 30s. Page may need better stealth."}
    except Exception as exc:
        return {"status": "error", "error": f"Turnstile wait failed: {exc}"}


@mcp.tool(
    name="bridge_captcha_solve_native",
    description=(
        "Solve CAPTCHAs locally without paid external APIs. "
        "Supported types: 'text' (Tesseract OCR on image), 'audio' (Whisper STT on audio file), "
        "'recaptcha_v2_audio' (alias for audio — download the audio challenge first), "
        "'turnstile' (auto-solve in stealth browser session — requires active session_id). "
        "Cost: always 0. No API keys needed."
    ),
)
async def bridge_captcha_solve_native(
    captcha_type: str,
    image_path: str = "",
    audio_path: str = "",
    session_id: str = "",
) -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    if captcha_type not in _NATIVE_CAPTCHA_TYPES:
        return json.dumps({"status": "error", "error": f"unsupported type '{captcha_type}'. Supported: {', '.join(_NATIVE_CAPTCHA_TYPES)}"})

    start = time.time()

    if captcha_type == "text":
        if not image_path:
            return json.dumps({"status": "error", "error": "image_path required for text CAPTCHA"})
        result = await _captcha_solve_text_ocr(image_path)
    elif captcha_type in ("audio", "recaptcha_v2_audio"):
        if not audio_path:
            return json.dumps({"status": "error", "error": "audio_path required for audio CAPTCHA"})
        result = await _captcha_solve_audio_whisper(audio_path)
    elif captcha_type == "turnstile":
        if not session_id:
            return json.dumps({"status": "error", "error": "session_id required for turnstile (needs active stealth browser)"})
        result = await _captcha_solve_turnstile_wait(session_id)
    elif captcha_type == "hcaptcha_image":
        if not image_path:
            return json.dumps({"status": "error", "error": "image_path required for hCaptcha image challenge"})
        result = await _captcha_solve_hcaptcha_ollama(image_path, target_label=audio_path or "")
    elif captcha_type == "recaptcha_v2_image":
        if not image_path:
            return json.dumps({"status": "error", "error": "image_path required for reCAPTCHA v2 image challenge"})
        result = await _captcha_solve_recaptcha_yolo(image_path, target_label=audio_path or "")
    else:
        result = {"status": "error", "error": f"unhandled type: {captcha_type}"}

    if result.get("status") == "ok":
        result["solve_time_ms"] = int((time.time() - start) * 1000)
        result["captcha_type"] = captcha_type
    return json.dumps(result)


# ===== TOR INTEGRATION (IP Anonymization) =====

_TOR_SOCKS_PORT = 9050
_TOR_CONTROL_PORT = 9051


@mcp.tool(
    name="bridge_tor_start",
    description=(
        "Check if Tor service is running. Returns SOCKS proxy address. "
        "If Tor is not running, attempts to start it."
    ),
)
async def bridge_tor_start() -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})
    import socket
    # Check if Tor SOCKS port is open
    try:
        s = socket.create_connection(("127.0.0.1", _TOR_SOCKS_PORT), timeout=2)
        s.close()
        tor_running = True
    except (ConnectionRefusedError, OSError):
        tor_running = False

    if not tor_running:
        # Try to start Tor
        try:
            proc = await asyncio.create_subprocess_exec(
                "tor", "--runas-tor", "--SocksPort", str(_TOR_SOCKS_PORT),
                "--ControlPort", str(_TOR_CONTROL_PORT),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.sleep(5)  # Wait for Tor to bootstrap
            s = socket.create_connection(("127.0.0.1", _TOR_SOCKS_PORT), timeout=2)
            s.close()
            tor_running = True
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Tor not running and failed to start: {exc}"})

    # Verify by fetching exit IP
    try:
        async with httpx.AsyncClient(
            proxy=f"socks5://127.0.0.1:{_TOR_SOCKS_PORT}",
            timeout=15.0,
        ) as client:
            resp = await client.get("https://ifconfig.me/ip")
            exit_ip = resp.text.strip()
    except Exception as exc:
        exit_ip = f"UNKNOWN ({exc})"

    return json.dumps({
        "status": "ok",
        "tor_running": True,
        "socks_proxy": f"socks5://127.0.0.1:{_TOR_SOCKS_PORT}",
        "exit_ip": exit_ip,
        "hint": "Use proxy='socks5://127.0.0.1:9050' in bridge_stealth_start()",
    })


@mcp.tool(
    name="bridge_tor_rotate",
    description=(
        "Request a new Tor circuit (new exit IP). Uses stem NEWNYM signal. "
        "Returns the new exit IP after rotation."
    ),
)
async def bridge_tor_rotate() -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})
    try:
        from stem import Signal
        from stem.control import Controller
    except ImportError:
        return json.dumps({"status": "error", "error": "stem not installed. Run: pip install stem"})

    try:
        with Controller.from_port(port=_TOR_CONTROL_PORT) as controller:
            controller.authenticate()
            controller.signal(Signal.NEWNYM)
    except Exception as exc:
        return json.dumps({"status": "error", "error": f"Tor circuit rotation failed: {exc}. Is ControlPort {_TOR_CONTROL_PORT} enabled in torrc?"})

    # Wait for new circuit
    await asyncio.sleep(3)

    # Fetch new exit IP
    try:
        async with httpx.AsyncClient(
            proxy=f"socks5://127.0.0.1:{_TOR_SOCKS_PORT}",
            timeout=15.0,
        ) as client:
            resp = await client.get("https://ifconfig.me/ip")
            new_ip = resp.text.strip()
    except Exception as exc:
        new_ip = f"UNKNOWN ({exc})"

    return json.dumps({
        "status": "ok",
        "new_exit_ip": new_ip,
        "rotated": True,
    })


@mcp.tool(
    name="bridge_tor_status",
    description=(
        "Check Tor status: running, exit IP, SOCKS port. "
        "Also performs IP leak test — verifies traffic goes through Tor."
    ),
)
async def bridge_tor_status() -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})
    import socket

    # Check SOCKS port
    try:
        s = socket.create_connection(("127.0.0.1", _TOR_SOCKS_PORT), timeout=2)
        s.close()
        socks_open = True
    except (ConnectionRefusedError, OSError):
        socks_open = False

    if not socks_open:
        return json.dumps({"status": "error", "tor_running": False, "error": "Tor SOCKS port not open"})

    # Get exit IP via Tor
    tor_ip = "UNKNOWN"
    try:
        async with httpx.AsyncClient(
            proxy=f"socks5://127.0.0.1:{_TOR_SOCKS_PORT}",
            timeout=15.0,
        ) as client:
            resp = await client.get("https://ifconfig.me/ip")
            tor_ip = resp.text.strip()
    except Exception as exc:
        tor_ip = f"ERROR: {exc}"

    # Get real IP (without Tor) for leak comparison
    real_ip = "UNKNOWN"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://ifconfig.me/ip")
            real_ip = resp.text.strip()
    except Exception:
        pass

    # Leak test
    ip_leaked = (tor_ip == real_ip) if tor_ip != "UNKNOWN" and real_ip != "UNKNOWN" else None

    return json.dumps({
        "status": "ok",
        "tor_running": True,
        "socks_proxy": f"socks5://127.0.0.1:{_TOR_SOCKS_PORT}",
        "tor_exit_ip": tor_ip,
        "real_ip": real_ip,
        "ip_leaked": ip_leaked,
        "leak_test": "PASS" if ip_leaked is False else ("FAIL — IPs match!" if ip_leaked else "INCONCLUSIVE"),
    })


# --- Tor Traffic Padding (anti-traffic-analysis) ---

_TOR_PADDING_SITES = [
    "https://www.wikipedia.org", "https://www.bbc.com", "https://www.reuters.com",
    "https://www.nature.com", "https://www.arxiv.org", "https://www.gutenberg.org",
    "https://www.python.org", "https://www.rust-lang.org", "https://www.mozilla.org",
    "https://www.debian.org", "https://www.kernel.org", "https://www.apache.org",
    "https://www.w3.org", "https://www.ietf.org", "https://www.unicode.org",
    "https://www.archive.org", "https://www.openstreetmap.org", "https://www.fsf.org",
    "https://www.eff.org", "https://www.torproject.org",
]
_TOR_PADDING_TASKS: dict[str, asyncio.Task] = {}  # session_id → padding task


async def _tor_padding_loop(session_id: str) -> None:
    """Background task: send dummy HTTPS requests through Tor at human-like intervals."""
    try:
        async with httpx.AsyncClient(
            proxy=f"socks5://127.0.0.1:{_TOR_SOCKS_PORT}",
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            while session_id in _stealth_sessions:
                url = random.choice(_TOR_PADDING_SITES)
                try:
                    await client.get(url)
                except Exception:
                    pass  # Silent — padding is best-effort
                # Human-like interval: Gauss(500ms, 200ms), clamped 200ms-2s
                delay = max(0.2, min(2.0, random.gauss(0.5, 0.2)))
                await asyncio.sleep(delay)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


def _start_tor_padding(session_id: str) -> None:
    """Start traffic padding for a Tor session."""
    if session_id not in _TOR_PADDING_TASKS:
        task = asyncio.ensure_future(_tor_padding_loop(session_id))
        _TOR_PADDING_TASKS[session_id] = task


def _stop_tor_padding(session_id: str) -> None:
    """Stop traffic padding for a session."""
    task = _TOR_PADDING_TASKS.pop(session_id, None)
    if task and not task.done():
        task.cancel()


# --- Obfs4 Bridge Configuration ---

_OBFS4_TORRC_TEMPLATE = """# Bridge ACE Tor Configuration — obfs4 pluggable transport
# ISP sees HTTPS traffic, NOT Tor protocol
UseBridges 1
ClientTransportPlugin obfs4 exec /usr/bin/obfs4proxy

# Vanguards: Guard Discovery reduced from seconds to months (NSA/Europol countermeasure)
VanguardsEnabled 1

# Public obfs4 bridges (from bridges.torproject.org)
# Replace with your own bridges for maximum security
Bridge obfs4 193.11.166.194:27020 2D82C2E354D531A68469ADA8C1E43D973CB6FF87 cert=4TLQPIAyzbkLFMKpKNT6GNMJKcBvydBM4OTH4QMVi4JB/cFlMM3ARfyLGCbhzI7bWI4v0A iat-mode=0
Bridge obfs4 193.11.166.194:27015 2D82C2E354D531A68469ADA8C1E43D973CB6FF87 cert=4TLQPIAyzbkLFMKpKNT6GNMJKcBvydBM4OTH4QMVi4JB/cFlMM3ARfyLGCbhzI7bWI4v0A iat-mode=0
Bridge obfs4 85.31.186.98:443 011F2599C0E9B27EE74B353155E244813763C3E5 cert=ayq0XzCwhpdysn5o0EyDUbmSOx3X/oTEbzDMvczHOl79AzVCBNF3Xqsf9O9mHR96VGMpA iat-mode=0

SocksPort 9050
"""


@mcp.tool(
    name="bridge_tor_obfs4_enable",
    description=(
        "Enable obfs4 pluggable transport for Tor. ISP sees HTTPS traffic instead of Tor protocol. "
        "Writes torrc with obfs4 bridge config and restarts Tor. Requires obfs4proxy installed."
    ),
)
async def bridge_tor_obfs4_enable() -> str:
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    # Check obfs4proxy
    import shutil
    if not shutil.which("obfs4proxy"):
        return json.dumps({
            "status": "error",
            "error": "obfs4proxy not installed. Run: sudo apt install obfs4proxy",
        })

    torrc_path = os.path.expanduser("~/.config/bridge/torrc")
    os.makedirs(os.path.dirname(torrc_path), exist_ok=True)

    # Backup existing torrc
    if os.path.isfile(torrc_path):
        import shutil as _sh
        _sh.copy2(torrc_path, torrc_path + ".bak")

    with open(torrc_path, "w") as f:
        f.write(_OBFS4_TORRC_TEMPLATE)

    # Restart Tor with new config
    try:
        proc = await asyncio.create_subprocess_exec(
            "tor", "-f", torrc_path, "--quiet",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(10)  # Wait for Tor + obfs4 bootstrap

        import socket
        try:
            s = socket.create_connection(("127.0.0.1", _TOR_SOCKS_PORT), timeout=3)
            s.close()
            tor_ok = True
        except (ConnectionRefusedError, OSError):
            tor_ok = False

        return json.dumps({
            "status": "ok" if tor_ok else "warning",
            "obfs4_enabled": True,
            "torrc_path": torrc_path,
            "tor_socks": f"127.0.0.1:{_TOR_SOCKS_PORT}",
            "tor_running": tor_ok,
            "isp_sees": "HTTPS (obfs4 encrypted, NOT Tor protocol)",
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": f"Tor restart failed: {exc}"})


# ===== CDP BROWSER CONNECT (Leo's Real Browser) =====

# Singleton: one CDP connection shared across all tools in this MCP process
_cdp_browser: Any = None  # Playwright Browser (connected via CDP)
_cdp_pw: Any = None       # Playwright context (for cleanup)
_cdp_default_page: Any = None  # Default page reference
_cdp_chrome_proc: Any = None   # Auto-started Chrome subprocess


async def _cdp_ensure_connected(port: int = 9222) -> Any:
    """Ensure CDP connection to Leo's browser. Auto-starts Chrome if needed."""
    global _cdp_browser, _cdp_pw, _cdp_default_page, _cdp_chrome_proc
    if _cdp_browser is not None:
        try:
            # Quick health check — list contexts
            _cdp_browser.contexts
            return _cdp_browser
        except Exception:
            _cdp_browser = None
            _cdp_pw = None
            _cdp_default_page = None

    try:
        from patchright.async_api import async_playwright
    except ImportError:
        from playwright.async_api import async_playwright
    pw = await async_playwright().start()

    # Try connecting to existing Chrome first
    try:
        browser = await pw.chromium.connect_over_cdp(f"http://localhost:{port}")
    except Exception:
        # Auto-start Chrome with CDP enabled
        import subprocess, shutil, atexit
        chrome_bin = shutil.which("google-chrome-stable") or shutil.which("google-chrome") or shutil.which("chromium-browser") or "google-chrome"
        user_data = f"/tmp/bridge-cdp-chrome-{port}"
        _cdp_chrome_proc = subprocess.Popen(
            [chrome_bin, f"--remote-debugging-port={port}",
             "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={user_data}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        atexit.register(lambda: _cdp_chrome_proc and _cdp_chrome_proc.kill())
        # Wait for Chrome to be ready (max 5s)
        import asyncio
        for _ in range(10):
            await asyncio.sleep(0.5)
            try:
                browser = await pw.chromium.connect_over_cdp(f"http://localhost:{port}")
                break
            except Exception:
                continue
        else:
            raise RuntimeError(f"Chrome failed to start on port {port} within 5s")
        logging.getLogger("bridge_mcp").info("Started CDP Chrome on :%d (PID %d)", port, _cdp_chrome_proc.pid)

    _cdp_browser = browser
    _cdp_pw = pw
    # Get first page from default context
    contexts = browser.contexts
    if contexts and contexts[0].pages:
        _cdp_default_page = contexts[0].pages[0]
    return browser


async def _cdp_list_tabs_via_http(port: int = 9222) -> list:
    """Query CDP /json endpoint directly for all page targets.

    Fallback for when Playwright connect_over_cdp doesn't discover existing tabs.
    Returns list of dicts with 'url' and 'title' keys (only type=page targets).
    """
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json", timeout=5) as resp:
            targets = json.loads(resp.read().decode())
            return [
                {"url": t.get("url", ""), "title": t.get("title", "")}
                for t in targets
                if t.get("type") == "page"
            ]
    except Exception:
        return []


@mcp.tool(
    name="bridge_cdp_connect",
    description=(
        "Connect to Chrome via CDP (Chrome DevTools Protocol). "
        "Auto-starts headless Chrome if no instance found. "
        "Returns list of open tabs/pages."
    ),
)
async def bridge_cdp_connect(port: int = 9222) -> str:
    """Connect to Leo's real browser via CDP."""
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})
    try:
        browser = await _cdp_ensure_connected(port)
        tabs = []
        for ctx in browser.contexts:
            for page in ctx.pages:
                tabs.append({"url": page.url, "title": await page.title()})
        # Fallback: If Playwright contexts show 0 tabs, query CDP /json endpoint directly.
        # connect_over_cdp may not discover all existing Chrome tabs.
        if not tabs:
            tabs = await _cdp_list_tabs_via_http(port)
        return json.dumps({"status": "ok", "tabs": tabs, "tab_count": len(tabs)})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_tabs",
    description="List all open tabs in Leo's browser with URLs and titles.",
)
async def bridge_cdp_tabs() -> str:
    """List all open browser tabs."""
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected. Call bridge_cdp_connect first."})
    try:
        tabs = []
        for ctx_idx, ctx in enumerate(_cdp_browser.contexts):
            for page_idx, page in enumerate(ctx.pages):
                tabs.append({
                    "index": f"{ctx_idx}:{page_idx}",
                    "url": page.url,
                    "title": await page.title(),
                })
        # Fallback: If Playwright contexts show 0 tabs, query CDP /json directly.
        if not tabs:
            cdp_tabs = await _cdp_list_tabs_via_http()
            for i, t in enumerate(cdp_tabs):
                tabs.append({
                    "index": f"cdp:{i}",
                    "url": t.get("url", ""),
                    "title": t.get("title", ""),
                })
        return json.dumps({"status": "ok", "tabs": tabs})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_navigate",
    description="Navigate a tab in Leo's browser to a URL. Specify tab index (from bridge_cdp_tabs) or uses active tab.",
)
async def bridge_cdp_navigate(url: str, tab_index: str = "0:0") -> str:
    """Navigate to URL in Leo's browser."""
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected"})
    try:
        ctx_idx, page_idx = [int(x) for x in tab_index.split(":")]
        page = _cdp_browser.contexts[ctx_idx].pages[page_idx]
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return json.dumps({
            "status": "ok",
            "url": page.url,
            "title": await page.title(),
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_screenshot",
    description="Take a screenshot of a tab in Leo's browser. Returns file path to saved screenshot.",
)
async def bridge_cdp_screenshot(tab_index: str = "0:0", full_page: bool = False) -> str:
    """Screenshot a tab in Leo's browser."""
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected"})
    try:
        ctx_idx, page_idx = [int(x) for x in tab_index.split(":")]
        page = _cdp_browser.contexts[ctx_idx].pages[page_idx]
        filename = f"/tmp/cdp_screenshot_{int(time.time())}.png"
        await page.screenshot(path=filename, full_page=full_page)
        return json.dumps({"status": "ok", "path": filename, "url": page.url})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_click",
    description="Click an element by CSS selector in Leo's browser.",
)
async def bridge_cdp_click(selector: str, tab_index: str = "0:0") -> str:
    """Click element in Leo's browser."""
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected"})
    try:
        ctx_idx, page_idx = [int(x) for x in tab_index.split(":")]
        page = _cdp_browser.contexts[ctx_idx].pages[page_idx]
        await page.click(selector, timeout=10000)
        return json.dumps({"status": "ok", "selector": selector})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_fill",
    description="Fill an input field by CSS selector in Leo's browser.",
)
async def bridge_cdp_fill(selector: str, value: str, tab_index: str = "0:0") -> str:
    """Fill input field in Leo's browser."""
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected"})
    try:
        ctx_idx, page_idx = [int(x) for x in tab_index.split(":")]
        page = _cdp_browser.contexts[ctx_idx].pages[page_idx]
        await page.fill(selector, value, timeout=10000)
        return json.dumps({"status": "ok", "selector": selector})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_evaluate",
    description="Execute JavaScript on a page in Leo's browser. Returns result.",
)
async def bridge_cdp_evaluate(expression: str, tab_index: str = "0:0") -> str:
    """Execute JS in Leo's browser."""
    log.info("[AUDIT] bridge_cdp_evaluate by=%s tab=%s expr=%s", _agent_id, tab_index, expression[:200])
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected"})
    try:
        ctx_idx, page_idx = [int(x) for x in tab_index.split(":")]
        page = _cdp_browser.contexts[ctx_idx].pages[page_idx]
        result = await page.evaluate(expression)
        return json.dumps({"status": "ok", "result": result})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_content",
    description="Get the HTML content of a page in Leo's browser.",
)
async def bridge_cdp_content(tab_index: str = "0:0") -> str:
    """Get page HTML content from Leo's browser."""
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected"})
    try:
        ctx_idx, page_idx = [int(x) for x in tab_index.split(":")]
        page = _cdp_browser.contexts[ctx_idx].pages[page_idx]
        content = await page.content()
        # Truncate if too large (>100KB)
        if len(content) > 100_000:
            content = content[:100_000] + "\n... [TRUNCATED at 100KB]"
        return json.dumps({
            "status": "ok",
            "url": page.url,
            "title": await page.title(),
            "content_length": len(content),
            "content": content,
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_disconnect",
    description="Disconnect from Leo's browser. Does NOT close the browser.",
)
async def bridge_cdp_disconnect() -> str:
    """Disconnect CDP connection. Browser stays open."""
    global _cdp_browser, _cdp_pw, _cdp_default_page
    if _cdp_browser is None:
        return json.dumps({"status": "ok", "message": "already disconnected"})
    try:
        await _cdp_browser.close()
    except Exception:
        pass
    try:
        if _cdp_pw:
            await _cdp_pw.stop()
    except Exception:
        pass
    _cdp_browser = None
    _cdp_pw = None
    _cdp_default_page = None
    return json.dumps({"status": "ok", "message": "disconnected"})


@mcp.tool(
    name="bridge_cdp_new_tab",
    description="Open a new tab in Leo's browser and navigate to a URL. Returns the new tab index.",
)
async def bridge_cdp_new_tab(url: str = "about:blank") -> str:
    """Open a new tab in Leo's browser."""
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected"})
    try:
        ctx = _cdp_browser.contexts[0]
        page = await ctx.new_page()
        if url != "about:blank":
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Find the new tab index
        page_idx = len(ctx.pages) - 1
        return json.dumps({
            "status": "ok",
            "tab_index": f"0:{page_idx}",
            "url": page.url,
            "title": await page.title(),
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_close_tab",
    description="Close a specific tab in Leo's browser by index. Use bridge_cdp_tabs to find indices.",
)
async def bridge_cdp_close_tab(tab_index: str) -> str:
    """Close a tab in Leo's browser."""
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected"})
    try:
        ctx_idx, page_idx = [int(x) for x in tab_index.split(":")]
        page = _cdp_browser.contexts[ctx_idx].pages[page_idx]
        url = page.url
        await page.close()
        return json.dumps({"status": "ok", "closed_tab": tab_index, "url": url})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool(
    name="bridge_cdp_file_upload",
    description=(
        "Upload a file via a file input element in Leo's browser (CDP). "
        "Selector should target an <input type='file'> element."
    ),
)
async def bridge_cdp_file_upload(
    selector: str, file_path: str, tab_index: str = "0:0",
) -> str:
    """Upload file to input element via CDP."""
    if _cdp_browser is None:
        return json.dumps({"status": "error", "error": "not connected. Call bridge_cdp_connect first."})

    path = os.path.expanduser(file_path.strip())
    if not os.path.isfile(path):
        return json.dumps({"status": "error", "error": f"File not found: {path}"})

    try:
        ctx_idx, page_idx = [int(x) for x in tab_index.split(":")]
        page = _cdp_browser.contexts[ctx_idx].pages[page_idx]
        await page.set_input_files(selector, path, timeout=10000)
        file_size = os.path.getsize(path)
        return json.dumps({
            "status": "ok", "selector": selector,
            "file": path, "size_bytes": file_size,
            "tab": tab_index,
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


# ===== UNIFIED BROWSER SESSION API =====

# Unified session registry: session_id -> {"engine": "stealth"|"cdp", ...}
_unified_sessions: dict[str, dict[str, Any]] = {}


def _default_run_id(prefix: str) -> str:
    agent = (_agent_id or "agent").strip() or "agent"
    return f"{prefix}_{agent}_{int(time.time() * 1000)}"


def _artifact_refs_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for key in ("path", "screenshot_path", "final_screenshot", "file", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            refs.append({"path": value.strip(), "kind": key})
    return refs


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "status", "engine", "url", "title", "session_id", "request_id", "selector",
        "path", "tab_index", "closed", "message", "risk_level",
        "bot_protection", "challenge_detected", "response_status",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            summary[key] = value
    if isinstance(payload.get("content"), str):
        summary["content_length"] = len(payload["content"])
    if isinstance(payload.get("content_preview"), str):
        summary["content_preview_length"] = len(payload["content_preview"])
    if "error" in payload and payload["error"] not in (None, ""):
        summary["error"] = payload["error"]
    return summary


def _ensure_execution_run(
    *,
    run_id: str,
    source: str,
    tool_name: str,
    engine: str = "",
    session_id: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    if not run_id:
        return
    execution_journal.ensure_run(
        run_id,
        source=source,
        tool_name=tool_name,
        agent_id=_agent_id or "",
        engine=engine,
        session_id=session_id,
        meta=meta or {},
    )


def _structured_action_json(
    *,
    source: str,
    tool_name: str,
    raw_payload: dict[str, Any],
    engine: str = "",
    run_id: str = "",
    session_id: str = "",
    input_summary: dict[str, Any] | None = None,
) -> str:
    payload = dict(raw_payload)
    status = str(payload.get("status") or ("ok" if payload.get("ok") else "error"))
    ok = bool(payload.get("ok")) if "ok" in payload else status not in {"error", "failed"}
    artifacts = _artifact_refs_from_payload(payload)
    step_id = ""
    if run_id:
        step = execution_journal.append_step(
            run_id,
            source=source,
            tool_name=tool_name,
            status=status,
            agent_id=_agent_id or "",
            engine=engine,
            session_id=session_id,
            input_summary=dict(input_summary or {}),
            result_summary=_payload_summary(payload),
            artifacts=artifacts,
            error=str(payload.get("error", "")) or None,
            error_class=str(payload.get("error_class", "")),
        )
        step_id = step["step_id"]

    data = _payload_summary(payload)
    if ok:
        result = success_result(
            source=source,
            tool_name=tool_name,
            status=status,
            engine=engine,
            run_id=run_id,
            step_id=step_id,
            session_id=session_id,
            data=data,
            artifacts=artifacts,
            legacy_fields=payload,
        )
    else:
        result = error_result(
            source=source,
            tool_name=tool_name,
            error=str(payload.get("error", "unknown error")),
            status=status,
            engine=engine,
            run_id=run_id,
            step_id=step_id,
            session_id=session_id,
            data=data,
            artifacts=artifacts,
            error_class=str(payload.get("error_class", "")),
            legacy_fields=payload,
        )
    return json.dumps(result.to_dict())

async def _open_unified_stealth_engine(
    url: str,
    headless: bool,
    *,
    proxy: str = "",
    user_agent: str = "",
    profile: str = "",
) -> tuple[str, dict[str, Any], str]:
    """Open the stealth engine and optionally navigate to the initial URL."""
    result_json = await bridge_stealth_start(
        headless=headless,
        proxy=proxy,
        user_agent=user_agent,
        profile=profile,
    )
    result = json.loads(result_json)
    if result.get("error") or result.get("status") == "error":
        return "", {"url": url}, str(result.get("error", "stealth start failed"))

    stealth_sid = str(result.get("session_id", ""))
    result_data: dict[str, Any] = {"url": url}
    if url and url != "about:blank":
        nav_json = await bridge_stealth_goto(stealth_sid, url)
        nav_result = json.loads(nav_json)
        if nav_result.get("error") or nav_result.get("status") == "error":
            try:
                await bridge_stealth_close(stealth_sid)
            except Exception:
                pass
            return "", {"url": url}, str(nav_result.get("error", "stealth navigate failed"))
        result_data = dict(nav_result)
    return stealth_sid, result_data, ""


async def _open_unified_cdp_engine(url: str) -> tuple[str, dict[str, Any], str]:
    """Open the CDP engine and navigate via a dedicated tab."""
    await _cdp_ensure_connected()
    if _cdp_browser is None:
        return "", {"url": url}, "CDP connection failed"

    tab_json = await bridge_cdp_new_tab(url=url)
    tab_result = json.loads(tab_json)
    if tab_result.get("error") or tab_result.get("status") == "error":
        return "", {"url": url}, str(tab_result.get("error", "CDP tab creation failed"))

    return str(tab_result.get("tab_index", "")), dict(tab_result), ""


@mcp.tool(
    name="bridge_browser_open",
    description=(
        "Open a unified browser session. Choose engine: "
        "'stealth' (anti-detection Playwright), 'cdp' (Chrome DevTools, Leo's browser), "
        "or 'auto' (stealth if available, falls back to cdp). "
        "Returns a session_id for use with other bridge_browser_* tools. "
        "All subsequent operations use the same session_id regardless of engine."
    ),
)
async def bridge_browser_open(
    url: str = "about:blank",
    engine: str = "auto",
    headless: bool = True,
    proxy: str = "",
    user_agent: str = "",
    profile: str = "",
) -> str:
    """Open a unified browser session."""
    if _agent_id is None:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_open",
            raw_payload={"status": "error", "error": "Not registered. Call bridge_register first."},
        )

    engine = (engine or "auto").strip().lower()
    proxy = (proxy or "").strip()
    user_agent = (user_agent or "").strip()
    profile = (profile or "").strip()
    stealth_only_requested = bool(proxy or user_agent or profile)
    if engine not in ("stealth", "cdp", "auto"):
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_open",
            raw_payload={"status": "error", "error": "engine must be 'stealth', 'cdp', or 'auto'"},
            input_summary={"engine": engine, "url": url, "proxy_configured": bool(proxy)},
        )

    url = (url or "about:blank").strip()

    # Auto engine selection: prefer stealth, fallback to cdp
    chosen_engine = engine
    if engine == "auto":
        if stealth_only_requested:
            chosen_engine = "stealth"
        else:
            try:
                import patchright  # noqa: F401
                chosen_engine = "stealth"
            except ImportError:
                try:
                    import playwright  # noqa: F401
                    chosen_engine = "stealth"
                except ImportError:
                    chosen_engine = "cdp"

    if chosen_engine == "cdp" and stealth_only_requested:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_open",
            engine="cdp",
            raw_payload={
                "status": "error",
                "engine": "cdp",
                "error": "stealth-only options (proxy, user_agent, profile) are not supported with engine='cdp'",
            },
            input_summary={
                "engine": engine,
                "url": url,
                "headless": headless,
                "proxy_configured": bool(proxy),
                "custom_user_agent": bool(user_agent),
                "profile": profile or None,
            },
        )

    session_id = f"unified_{_agent_id}_{int(time.time() * 1000)}"
    run_id = session_id
    _ensure_execution_run(
        run_id=run_id,
        source="browser",
        tool_name="bridge_browser_open",
        engine=chosen_engine,
        session_id=session_id,
        meta={
            "requested_engine": engine,
            "chosen_engine": chosen_engine,
            "requested_url": url,
            "proxy_configured": bool(proxy),
            "custom_user_agent": bool(user_agent),
            "profile": profile or None,
        },
    )

    try:
        fallback_from = ""
        fallback_reason = ""
        open_metadata: dict[str, Any] = {}
        if chosen_engine == "stealth":
            stealth_sid, stealth_data, stealth_error = await _open_unified_stealth_engine(
                url,
                headless,
                proxy=proxy,
                user_agent=user_agent,
                profile=profile,
            )
            if stealth_error:
                if engine != "auto" or stealth_only_requested:
                    return _structured_action_json(
                        source="browser",
                        tool_name="bridge_browser_open",
                        engine="stealth",
                        run_id=run_id,
                        session_id=session_id,
                        raw_payload={
                            "status": "error",
                            "engine": "stealth",
                            "error": stealth_error,
                        },
                        input_summary={
                            "engine": chosen_engine,
                            "url": url,
                            "headless": headless,
                            "proxy_configured": bool(proxy),
                            "custom_user_agent": bool(user_agent),
                            "profile": profile or None,
                        },
                    )
                chosen_engine = "cdp"
                fallback_from = "stealth"
                fallback_reason = stealth_error
            else:
                current_url = str(stealth_data.get("url", url))
                _unified_sessions[session_id] = {
                    "engine": "stealth",
                    "engine_session_id": stealth_sid,
                    "url": current_url,
                    "run_id": run_id,
                    "created_at": time.time(),
                }
                open_metadata = stealth_data

        elif chosen_engine == "cdp":
            pass

        if chosen_engine == "cdp":
            tab_index, cdp_data, cdp_error = await _open_unified_cdp_engine(url)
            if cdp_error:
                raw_payload: dict[str, Any] = {
                    "status": "error",
                    "engine": "cdp",
                    "error": cdp_error,
                }
                if fallback_from:
                    raw_payload["fallback_from"] = fallback_from
                    raw_payload["fallback_reason"] = fallback_reason
                return _structured_action_json(
                    source="browser",
                    tool_name="bridge_browser_open",
                    engine="cdp",
                    run_id=run_id,
                    session_id=session_id,
                    raw_payload=raw_payload,
                    input_summary={
                        "engine": chosen_engine,
                        "url": url,
                        "headless": headless,
                        "proxy_configured": bool(proxy),
                        "custom_user_agent": bool(user_agent),
                        "profile": profile or None,
                    },
                )

            current_url = str(cdp_data.get("url", url))
            _unified_sessions[session_id] = {
                "engine": "cdp",
                "engine_session_id": tab_index,
                "url": current_url,
                "run_id": run_id,
                "created_at": time.time(),
            }
            open_metadata = cdp_data

        raw_payload: dict[str, Any] = {
            "status": "ok",
            "session_id": session_id,
            "engine": chosen_engine,
            "url": _unified_sessions[session_id].get("url", url),
        }
        for key in ("title", "bot_protection", "challenge_detected", "response_status"):
            value = open_metadata.get(key)
            if value is not None:
                raw_payload[key] = value
        if fallback_from:
            raw_payload["fallback_from"] = fallback_from
            raw_payload["fallback_reason"] = fallback_reason
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_open",
            engine=chosen_engine,
            run_id=run_id,
            session_id=session_id,
            raw_payload=raw_payload,
            input_summary={
                "engine": chosen_engine,
                "url": url,
                "headless": headless,
                "proxy_configured": bool(proxy),
                "custom_user_agent": bool(user_agent),
                "profile": profile or None,
            },
        )

    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_open",
            engine=chosen_engine,
            run_id=run_id,
            session_id=session_id,
            raw_payload={"status": "error", "engine": chosen_engine, "error": str(exc)},
            input_summary={
                "engine": chosen_engine,
                "url": url,
                "headless": headless,
                "proxy_configured": bool(proxy),
                "custom_user_agent": bool(user_agent),
                "profile": profile or None,
            },
        )


def _get_unified_session(session_id: str) -> dict[str, Any] | None:
    """Look up a unified session."""
    return _unified_sessions.get(session_id)


def _prune_dead_unified_stealth_session(
    session_id: str,
    session: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Prune a unified stealth session if the underlying engine session is gone."""
    if session.get("engine") != "stealth":
        return raw
    error = str(raw.get("error", ""))
    if raw.get("status") == "error" and "not found" in error.lower():
        _unified_sessions.pop(session_id, None)
        raw = dict(raw)
        raw["stale_session_pruned"] = True
    return raw


def _browser_observe_script(max_nodes: int) -> str:
    max_nodes = max(1, min(int(max_nodes), 200))
    return f"""() => {{
        const isVisible = (node) => {{
            if (!(node instanceof HTMLElement)) return false;
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            return !!(rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden');
        }};
        if (!window.__bridgeObserveSeq) {{
            window.__bridgeObserveSeq = 0;
        }}
        const seen = new Set();
        const nodes = Array.from(document.querySelectorAll(
            'a,button,input,textarea,select,[role="button"],[role="link"],[role="textbox"],[role="menuitem"],[contenteditable="true"],[tabindex]'
        ));
        const elements = [];
        for (const node of nodes) {{
            if (!isVisible(node)) continue;
            let ref = node.getAttribute('data-bridge-ref');
            if (!ref) {{
                window.__bridgeObserveSeq += 1;
                ref = `bref-${{window.__bridgeObserveSeq}}`;
                node.setAttribute('data-bridge-ref', ref);
            }}
            if (seen.has(ref)) continue;
            seen.add(ref);
            const rect = node.getBoundingClientRect();
            const text = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 200);
            const ariaLabel = (node.getAttribute('aria-label') || '').trim();
            const placeholder = (node.getAttribute('placeholder') || '').trim();
            const name = (node.getAttribute('name') || '').trim();
            const role = (node.getAttribute('role') || '').trim();
            const type = (node.getAttribute('type') || '').trim();
            const tag = node.tagName.toLowerCase();
            const label = text || ariaLabel || placeholder || name || tag;
            elements.push({{
                ref,
                tag,
                type,
                role,
                text,
                aria_label: ariaLabel,
                placeholder,
                name,
                label,
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            }});
            if (elements.length >= {max_nodes}) break;
        }}
        return {{
            url: window.location.href,
            title: document.title,
            element_count: elements.length,
            elements,
        }};
    }}"""


def _browser_ref_selector(ref: str) -> str:
    if not re.match(r"^[A-Za-z0-9._:-]+$", ref):
        raise ValueError(f"invalid ref: {ref}")
    return f'[data-bridge-ref="{ref}"]'


def _normalize_browser_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


async def _browser_observe_raw(
    session_id: str,
    session: dict[str, Any],
    *,
    max_nodes: int,
) -> dict[str, Any]:
    script = _browser_observe_script(max_nodes)
    if session["engine"] == "stealth":
        raw = json.loads(await bridge_stealth_evaluate(session["engine_session_id"], script))
    elif session["engine"] == "cdp":
        raw = json.loads(await bridge_cdp_evaluate(script, tab_index=session["engine_session_id"]))
    else:
        raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
    raw = _prune_dead_unified_stealth_session(session_id, session, raw)
    if raw.get("status") != "error" and isinstance(raw.get("result"), dict):
        snapshot = dict(raw["result"])
        raw = {
            "status": "ok",
            "url": snapshot.get("url", session.get("url", "")),
            "title": snapshot.get("title", ""),
            "elements": snapshot.get("elements", []),
            "element_count": int(snapshot.get("element_count", len(snapshot.get("elements", [])))),
        }
    return raw


def _browser_field_matches(value: str, expected: str, *, exact: bool) -> bool:
    lhs = _normalize_browser_text(value)
    rhs = _normalize_browser_text(expected)
    if not rhs:
        return True
    if exact:
        return lhs == rhs
    return rhs in lhs


def _browser_find_ref_candidates(
    elements: list[dict[str, Any]],
    *,
    query: str = "",
    tag: str = "",
    role: str = "",
    name: str = "",
    placeholder: str = "",
    text: str = "",
    exact: bool = False,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    norm_query = _normalize_browser_text(query)
    norm_tag = _normalize_browser_text(tag)
    norm_role = _normalize_browser_text(role)
    norm_name = _normalize_browser_text(name)
    norm_placeholder = _normalize_browser_text(placeholder)
    norm_text = _normalize_browser_text(text)
    query_tokens = [token for token in norm_query.split() if token]

    candidates: list[dict[str, Any]] = []
    for element in elements:
        tag_value = str(element.get("tag", ""))
        role_value = str(element.get("role", ""))
        name_value = str(element.get("name", ""))
        placeholder_value = str(element.get("placeholder", ""))
        text_value = str(element.get("text", ""))
        label_value = str(element.get("label", ""))
        aria_label_value = str(element.get("aria_label", ""))

        if norm_tag and not _browser_field_matches(tag_value, norm_tag, exact=True):
            continue
        if norm_role and not _browser_field_matches(role_value, norm_role, exact=exact):
            continue
        if norm_name and not _browser_field_matches(name_value, norm_name, exact=exact):
            continue
        if norm_placeholder and not _browser_field_matches(placeholder_value, norm_placeholder, exact=exact):
            continue
        if norm_text and not _browser_field_matches(text_value, norm_text, exact=exact):
            continue

        haystacks = [
            _normalize_browser_text(label_value),
            _normalize_browser_text(text_value),
            _normalize_browser_text(aria_label_value),
            _normalize_browser_text(placeholder_value),
            _normalize_browser_text(name_value),
        ]
        searchable = " ".join(part for part in haystacks if part)
        score = 0
        if norm_query:
            if exact and any(part == norm_query for part in haystacks if part):
                score += 120
            elif any(norm_query and norm_query in part for part in haystacks if part):
                score += 90
            elif query_tokens and all(token in searchable for token in query_tokens):
                score += 60
            else:
                continue

        if norm_name and _browser_field_matches(name_value, norm_name, exact=exact):
            score += 25
        if norm_placeholder and _browser_field_matches(placeholder_value, norm_placeholder, exact=exact):
            score += 20
        if norm_text and _browser_field_matches(text_value, norm_text, exact=exact):
            score += 20
        if norm_role and _browser_field_matches(role_value, norm_role, exact=exact):
            score += 10
        if norm_tag and _browser_field_matches(tag_value, norm_tag, exact=True):
            score += 5
        if not norm_query and not any((norm_tag, norm_role, norm_name, norm_placeholder, norm_text)):
            continue

        candidate = dict(element)
        candidate["score"] = score
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            -int(item.get("score", 0)),
            int(item.get("y", 0)),
            int(item.get("x", 0)),
        )
    )
    return candidates[: max(1, min(int(max_results), 20))]


def _browser_verify_script(
    url_contains: str,
    title_contains: str,
    text_contains: str,
    selector_exists: str,
    selector_missing: str,
    value_selector: str,
    value_contains: str,
    value_equals: str,
    active_selector: str,
) -> str:
    return json.dumps(
        {
            "url_contains": url_contains,
            "title_contains": title_contains,
            "text_contains": text_contains,
            "selector_exists": selector_exists,
            "selector_missing": selector_missing,
            "value_selector": value_selector,
            "value_contains": value_contains,
            "value_equals": value_equals,
            "active_selector": active_selector,
        }
    )


def _browser_has_verify_conditions(
    *,
    url_contains: str = "",
    title_contains: str = "",
    text_contains: str = "",
    selector_exists: str = "",
    selector_missing: str = "",
    value_selector: str = "",
    value_contains: str = "",
    value_equals: str = "",
    active_selector: str = "",
) -> bool:
    return any(
        [
            url_contains,
            title_contains,
            text_contains,
            selector_exists,
            selector_missing,
            value_selector and value_contains,
            value_selector and value_equals,
            active_selector,
        ]
    )


@mcp.tool(
    name="bridge_browser_navigate",
    description=(
        "Navigate a unified browser session to a URL. "
        "Works with any engine (stealth/cdp) transparently."
    ),
)
async def bridge_browser_nav(session_id: str, url: str) -> str:
    """Navigate unified session to URL."""
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_navigate",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
            input_summary={"url": url},
        )

    url = (url or "").strip()
    if not url:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_navigate",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": "url is required"},
        )

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_goto(session["engine_session_id"], url))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_navigate(url, tab_index=session["engine_session_id"]))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        if raw.get("status") != "error" and raw.get("url"):
            session["url"] = raw["url"]
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_navigate",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={"url": url},
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_navigate",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={"url": url},
        )


@mcp.tool(
    name="bridge_browser_observe",
    description=(
        "Capture a semantic snapshot of interactive elements in a unified browser session. "
        "Returns stable refs that can be used with bridge_browser_click_ref or bridge_browser_fill_ref."
    ),
)
async def bridge_browser_observe(session_id: str, max_nodes: int = 50) -> str:
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_observe",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
        )

    try:
        raw = await _browser_observe_raw(session_id, session, max_nodes=max_nodes)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_observe",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={"max_nodes": max_nodes},
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_observe",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={"max_nodes": max_nodes},
        )


@mcp.tool(
    name="bridge_browser_find_refs",
    description=(
        "Resolve semantic browser targets to stable refs using query or explicit field filters. "
        "Returns scored candidates that can be used with bridge_browser_click_ref or bridge_browser_fill_ref."
    ),
)
async def bridge_browser_find_refs(
    session_id: str,
    query: str = "",
    tag: str = "",
    role: str = "",
    name: str = "",
    placeholder: str = "",
    text: str = "",
    exact: bool = False,
    max_results: int = 5,
) -> str:
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_find_refs",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
        )

    if not any([query, tag, role, name, placeholder, text]):
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_find_refs",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": "at least one search criterion is required"},
        )

    try:
        observed = await _browser_observe_raw(session_id, session, max_nodes=max(max_results * 10, 50))
        if observed.get("status") == "error":
            raw = observed
        else:
            candidates = _browser_find_ref_candidates(
                list(observed.get("elements", [])),
                query=query,
                tag=tag,
                role=role,
                name=name,
                placeholder=placeholder,
                text=text,
                exact=exact,
                max_results=max_results,
            )
            raw = {
                "status": "ok" if candidates else "not_found",
                "url": observed.get("url", session.get("url", "")),
                "title": observed.get("title", ""),
                "candidates": candidates,
                "count": len(candidates),
            }
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_find_refs",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={
                "query": query or None,
                "tag": tag or None,
                "role": role or None,
                "name": name or None,
                "placeholder": placeholder or None,
                "text": text or None,
                "exact": exact,
                "max_results": max_results,
            },
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_find_refs",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={
                "query": query or None,
                "tag": tag or None,
                "role": role or None,
                "name": name or None,
                "placeholder": placeholder or None,
                "text": text or None,
                "exact": exact,
                "max_results": max_results,
            },
        )


@mcp.tool(
    name="bridge_browser_click",
    description=(
        "Click an element in a unified browser session by CSS selector. "
        "Works with any engine (stealth/cdp) transparently."
    ),
)
async def bridge_browser_clk(session_id: str, selector: str) -> str:
    """Click element in unified session."""
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
            input_summary={"selector": selector},
        )

    selector = (selector or "").strip()
    if not selector:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": "selector is required"},
        )

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_click(session["engine_session_id"], selector))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_click(selector, tab_index=session["engine_session_id"]))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={"selector": selector},
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={"selector": selector},
        )


@mcp.tool(
    name="bridge_browser_click_ref",
    description=(
        "Click an observed element in a unified browser session by stable ref. "
        "Call bridge_browser_observe first to obtain refs."
    ),
)
async def bridge_browser_click_ref(session_id: str, ref: str) -> str:
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click_ref",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
            input_summary={"ref": ref},
        )
    try:
        selector = _browser_ref_selector((ref or "").strip())
    except ValueError as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click_ref",
            raw_payload={"status": "error", "error": str(exc)},
            session_id=session_id,
            input_summary={"ref": ref},
        )
    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_click(session["engine_session_id"], selector))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_click(selector, tab_index=session["engine_session_id"]))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click_ref",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={"ref": ref, "selector": selector},
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click_ref",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={"ref": ref, "selector": selector},
        )


@mcp.tool(
    name="bridge_browser_fill",
    description=(
        "Fill an input field in a unified browser session. "
        "Works with any engine (stealth/cdp) transparently."
    ),
)
async def bridge_browser_fll(session_id: str, selector: str, value: str) -> str:
    """Fill input in unified session."""
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fill",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
            input_summary={"selector": selector, "value_length": len(value or "")},
        )

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_fill(session["engine_session_id"], selector, value))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_fill(selector, value, tab_index=session["engine_session_id"]))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fill",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={"selector": selector, "value_length": len(value or "")},
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fill",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={"selector": selector, "value_length": len(value or "")},
        )


@mcp.tool(
    name="bridge_browser_fill_ref",
    description=(
        "Fill an observed input element in a unified browser session by stable ref. "
        "Call bridge_browser_observe first to obtain refs."
    ),
)
async def bridge_browser_fill_ref(session_id: str, ref: str, value: str) -> str:
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fill_ref",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
            input_summary={"ref": ref, "value_length": len(value or "")},
        )
    try:
        selector = _browser_ref_selector((ref or "").strip())
    except ValueError as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fill_ref",
            raw_payload={"status": "error", "error": str(exc)},
            session_id=session_id,
            input_summary={"ref": ref, "value_length": len(value or "")},
        )
    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_fill(session["engine_session_id"], selector, value))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_fill(selector, value, tab_index=session["engine_session_id"]))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fill_ref",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={"ref": ref, "selector": selector, "value_length": len(value or "")},
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fill_ref",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={"ref": ref, "selector": selector, "value_length": len(value or "")},
        )


@mcp.tool(
    name="bridge_browser_content",
    description=(
        "Get page content (HTML text) from a unified browser session. "
        "Works with any engine (stealth/cdp) transparently."
    ),
)
async def bridge_browser_cnt(session_id: str) -> str:
    """Get page content from unified session."""
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_content",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
        )

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_content(session["engine_session_id"]))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_content(tab_index=session["engine_session_id"]))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_content",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_content",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
        )


@mcp.tool(
    name="bridge_browser_verify",
    description=(
        "Verify a unified browser session against simple postconditions such as url, title, text, "
        "or selector presence. Returns structured pass/fail details."
    ),
)
async def bridge_browser_verify(
    session_id: str,
    url_contains: str = "",
    title_contains: str = "",
    text_contains: str = "",
    selector_exists: str = "",
    selector_missing: str = "",
    value_selector: str = "",
    value_contains: str = "",
    value_equals: str = "",
    active_selector: str = "",
) -> str:
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_verify",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
        )

    verify_expr = f"""(() => {{
        const expectations = { _browser_verify_script(url_contains, title_contains, text_contains, selector_exists, selector_missing, value_selector, value_contains, value_equals, active_selector) };
        const bodyText = (document.body ? document.body.innerText || document.body.textContent || '' : '').replace(/\\s+/g, ' ').trim();
        const valueNode = expectations.value_selector ? document.querySelector(expectations.value_selector) : null;
        const valueText = valueNode
            ? (typeof valueNode.value !== 'undefined'
                ? String(valueNode.value ?? '')
                : ((valueNode.innerText || valueNode.textContent || '').replace(/\\s+/g, ' ').trim()))
            : '';
        const activeMatches = expectations.active_selector
            ? !!(document.activeElement && document.activeElement.matches && document.activeElement.matches(expectations.active_selector))
            : true;
        const matches = {{
            url_contains: !expectations.url_contains || window.location.href.includes(expectations.url_contains),
            title_contains: !expectations.title_contains || document.title.includes(expectations.title_contains),
            text_contains: !expectations.text_contains || bodyText.includes(expectations.text_contains),
            selector_exists: !expectations.selector_exists || !!document.querySelector(expectations.selector_exists),
            selector_missing: !expectations.selector_missing || !document.querySelector(expectations.selector_missing),
            value_contains: !expectations.value_contains || (!!valueNode && valueText.includes(expectations.value_contains)),
            value_equals: !expectations.value_equals || (!!valueNode && valueText === expectations.value_equals),
            active_selector: activeMatches,
        }};
        return {{
            url: window.location.href,
            title: document.title,
            text_preview: bodyText.slice(0, 240),
            value_text: valueText,
            active_element: document.activeElement && document.activeElement.tagName
                ? {{
                    tag: document.activeElement.tagName.toLowerCase(),
                    id: document.activeElement.id || '',
                    name: document.activeElement.getAttribute && (document.activeElement.getAttribute('name') || ''),
                }}
                : null,
            matches,
            ok: Object.values(matches).every(Boolean),
        }};
    }})()"""

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_evaluate(session["engine_session_id"], verify_expr))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_evaluate(verify_expr, tab_index=session["engine_session_id"]))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        if raw.get("status") != "error" and isinstance(raw.get("result"), dict):
            result = dict(raw["result"])
            raw = {
                "status": "ok" if result.get("ok") else "mismatch",
                "url": result.get("url", session.get("url", "")),
                "title": result.get("title", ""),
                "text_preview": result.get("text_preview", ""),
                "value_text": result.get("value_text", ""),
                "active_element": result.get("active_element"),
                "matches": result.get("matches", {}),
                "verified": bool(result.get("ok")),
            }
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_verify",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={
                "url_contains": url_contains or None,
                "title_contains": title_contains or None,
                "text_contains": text_contains or None,
                "selector_exists": selector_exists or None,
                "selector_missing": selector_missing or None,
                "value_selector": value_selector or None,
                "value_contains": value_contains or None,
                "value_equals": value_equals or None,
                "active_selector": active_selector or None,
            },
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_verify",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={
                "url_contains": url_contains or None,
                "title_contains": title_contains or None,
                "text_contains": text_contains or None,
                "selector_exists": selector_exists or None,
                "selector_missing": selector_missing or None,
                "value_selector": value_selector or None,
                "value_contains": value_contains or None,
                "value_equals": value_equals or None,
                "active_selector": active_selector or None,
            },
        )


@mcp.tool(
    name="bridge_browser_click_ref_verify",
    description=(
        "Click a browser element by ref and immediately verify postconditions such as url, title, text, "
        "selector presence, or active element."
    ),
)
async def bridge_browser_click_ref_verify(
    session_id: str,
    ref: str,
    url_contains: str = "",
    title_contains: str = "",
    text_contains: str = "",
    selector_exists: str = "",
    selector_missing: str = "",
    active_selector: str = "",
) -> str:
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click_ref_verify",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
            input_summary={"ref": ref},
        )

    if not _browser_has_verify_conditions(
        url_contains=url_contains,
        title_contains=title_contains,
        text_contains=text_contains,
        selector_exists=selector_exists,
        selector_missing=selector_missing,
        active_selector=active_selector,
    ):
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click_ref_verify",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": "at least one verify condition is required"},
            input_summary={"ref": ref},
        )

    action = json.loads(await bridge_browser_click_ref(session_id, ref))
    if not action.get("ok"):
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_click_ref_verify",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": "click action failed", "action": action},
            input_summary={"ref": ref},
        )

    verification = json.loads(
        await bridge_browser_verify(
            session_id,
            url_contains=url_contains,
            title_contains=title_contains,
            text_contains=text_contains,
            selector_exists=selector_exists,
            selector_missing=selector_missing,
            active_selector=active_selector,
        )
    )
    verification_status = str(verification.get("status", ""))
    verified = bool(verification.get("verified"))
    status = "ok" if verified else ("error" if verification_status == "error" else "mismatch")
    return _structured_action_json(
        source="browser",
        tool_name="bridge_browser_click_ref_verify",
        engine=str(session.get("engine", "")),
        run_id=str(session.get("run_id", "")),
        session_id=session_id,
        raw_payload={
            "status": status,
            "verified": verified,
            "action": action,
            "verification": verification,
            "matches": verification.get("matches", {}),
            "url": verification.get("url", action.get("url", "")),
            "title": verification.get("title", ""),
        },
        input_summary={
            "ref": ref,
            "url_contains": url_contains or None,
            "title_contains": title_contains or None,
            "text_contains": text_contains or None,
            "selector_exists": selector_exists or None,
            "selector_missing": selector_missing or None,
            "active_selector": active_selector or None,
        },
    )


@mcp.tool(
    name="bridge_browser_fill_ref_verify",
    description=(
        "Fill a browser input by ref and immediately verify the resulting field value plus optional "
        "postconditions such as url, title, text, or selector presence."
    ),
)
async def bridge_browser_fill_ref_verify(
    session_id: str,
    ref: str,
    value: str,
    url_contains: str = "",
    title_contains: str = "",
    text_contains: str = "",
    selector_exists: str = "",
    selector_missing: str = "",
) -> str:
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fill_ref_verify",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
            input_summary={"ref": ref, "value_length": len(value or "")},
        )

    action = json.loads(await bridge_browser_fill_ref(session_id, ref, value))
    if not action.get("ok"):
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fill_ref_verify",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": "fill action failed", "action": action},
            input_summary={"ref": ref, "value_length": len(value or "")},
        )

    selector = _browser_ref_selector((ref or "").strip())
    verification = json.loads(
        await bridge_browser_verify(
            session_id,
            url_contains=url_contains,
            title_contains=title_contains,
            text_contains=text_contains,
            selector_exists=selector_exists,
            selector_missing=selector_missing,
            value_selector=selector,
            value_equals=value,
        )
    )
    verification_status = str(verification.get("status", ""))
    verified = bool(verification.get("verified"))
    status = "ok" if verified else ("error" if verification_status == "error" else "mismatch")
    return _structured_action_json(
        source="browser",
        tool_name="bridge_browser_fill_ref_verify",
        engine=str(session.get("engine", "")),
        run_id=str(session.get("run_id", "")),
        session_id=session_id,
        raw_payload={
            "status": status,
            "verified": verified,
            "action": action,
            "verification": verification,
            "matches": verification.get("matches", {}),
            "value_text": verification.get("value_text", ""),
            "url": verification.get("url", action.get("url", "")),
            "title": verification.get("title", ""),
        },
        input_summary={
            "ref": ref,
            "value_length": len(value or ""),
            "url_contains": url_contains or None,
            "title_contains": title_contains or None,
            "text_contains": text_contains or None,
            "selector_exists": selector_exists or None,
            "selector_missing": selector_missing or None,
        },
    )


@mcp.tool(
    name="bridge_browser_fingerprint_snapshot",
    description=(
        "Capture a browser-level fingerprint snapshot from a unified browser session. "
        "Useful for anti-detection lab validation and regression tracking."
    ),
)
async def bridge_browser_fingerprint_snapshot(session_id: str) -> str:
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fingerprint_snapshot",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
        )

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_fingerprint_snapshot(session["engine_session_id"]))
        elif session["engine"] == "cdp":
            raw = json.loads(
                await bridge_cdp_evaluate(
                    _BROWSER_FINGERPRINT_SNAPSHOT_SCRIPT,
                    tab_index=session["engine_session_id"],
                )
            )
            if raw.get("status") != "error":
                raw = {
                    "status": "ok",
                    "snapshot": raw.get("result"),
                }
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fingerprint_snapshot",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_fingerprint_snapshot",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
        )


@mcp.tool(
    name="bridge_browser_screenshot",
    description=(
        "Take a screenshot of a unified browser session. "
        "Works with any engine (stealth/cdp) transparently. "
        "Returns path to the saved PNG file."
    ),
)
async def bridge_browser_scr(session_id: str, full_page: bool = True) -> str:
    """Take screenshot of unified session."""
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_screenshot",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
            input_summary={"full_page": full_page},
        )

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_screenshot(session["engine_session_id"], full_page=full_page))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_screenshot(tab_index=session["engine_session_id"], full_page=full_page))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_screenshot",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={"full_page": full_page},
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_screenshot",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={"full_page": full_page},
        )


@mcp.tool(
    name="bridge_browser_evaluate",
    description=(
        "Execute JavaScript in a unified browser session. "
        "Works with any engine (stealth/cdp) transparently."
    ),
)
async def bridge_browser_eval(session_id: str, expression: str) -> str:
    """Evaluate JS in unified session."""
    log.info("[AUDIT] bridge_browser_evaluate by=%s session=%s expr=%s", _agent_id, session_id, expression[:200])
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_evaluate",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
        )

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_evaluate(session["engine_session_id"], expression))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_evaluate(expression, tab_index=session["engine_session_id"]))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_evaluate",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_evaluate",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
        )


@mcp.tool(
    name="bridge_browser_upload",
    description=(
        "Upload a file to an input element in a unified browser session. "
        "Works with any engine (stealth/cdp) transparently."
    ),
)
async def bridge_browser_upl(session_id: str, selector: str, file_path: str) -> str:
    """Upload file in unified session."""
    session = _get_unified_session(session_id)
    if not session:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_upload",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
            input_summary={"selector": selector, "file_path": file_path},
        )

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_file_upload(session["engine_session_id"], selector, file_path))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_file_upload(selector, file_path, tab_index=session["engine_session_id"]))
        else:
            raw = {"status": "error", "error": f"Unknown engine: {session['engine']}"}
        raw = _prune_dead_unified_stealth_session(session_id, session, raw)
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_upload",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
            input_summary={"selector": selector, "file_path": file_path},
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_upload",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={"selector": selector, "file_path": file_path},
        )


@mcp.tool(
    name="bridge_browser_close",
    description=(
        "Close a unified browser session. "
        "Cleans up the underlying engine session."
    ),
)
async def bridge_browser_cls(session_id: str) -> str:
    """Close unified session."""
    stale_pruned = _prune_orphaned_unified_stealth_sessions(session_id)
    session = _unified_sessions.pop(session_id, None)
    if not session:
        if stale_pruned:
            return _structured_action_json(
                source="browser",
                tool_name="bridge_browser_close",
                engine="stealth",
                session_id=session_id,
                raw_payload={
                    "status": "ok",
                    "closed": session_id,
                    "engine": "stealth",
                    "engine_session_missing": True,
                    "stale_session_pruned": True,
                },
            )
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_close",
            raw_payload={"status": "error", "error": f"Unknown session: {session_id}"},
            session_id=session_id,
        )

    try:
        if session["engine"] == "stealth":
            raw = json.loads(await bridge_stealth_close(session["engine_session_id"]))
        elif session["engine"] == "cdp":
            raw = json.loads(await bridge_cdp_close_tab(session["engine_session_id"]))
            raw["closed"] = session_id
            raw["engine"] = "cdp"
        else:
            raw = {"status": "ok", "closed": session_id}
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_close",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload=raw,
        )
    except Exception as exc:
        return _structured_action_json(
            source="browser",
            tool_name="bridge_browser_close",
            engine=str(session.get("engine", "")),
            run_id=str(session.get("run_id", "")),
            session_id=session_id,
            raw_payload={"status": "error", "error": str(exc)},
        )


@mcp.tool(
    name="bridge_browser_sessions",
    description=(
        "List all active unified browser sessions. "
        "Shows session IDs, engines, URLs, and age."
    ),
)
async def bridge_browser_lst() -> str:
    """List all unified sessions."""
    now = time.time()
    pruned_stale_sessions = _prune_orphaned_unified_stealth_sessions()
    sessions = []
    for sid, info in _unified_sessions.items():
        sessions.append({
            "session_id": sid,
            "engine": info["engine"],
            "url": info.get("url", ""),
            "run_id": info.get("run_id", ""),
            "age_seconds": round(now - info.get("created_at", now)),
        })

    # Also list raw stealth sessions not in unified
    for stealth_sid, stealth_session in _stealth_sessions.items():
        if not any(s.get("engine_session_id") == stealth_sid for s in _unified_sessions.values()):
            sessions.append({
                "session_id": stealth_sid,
                "engine": "stealth (direct)",
                "url": "",
                "age_seconds": round(now - stealth_session.created_at),
                "note": "created via bridge_stealth_start directly",
            })

    # CDP status
    cdp_status = "connected" if _cdp_browser is not None else "disconnected"

    return json.dumps({
        "status": "ok",
        "unified_sessions": len([s for s in sessions if s["session_id"].startswith("unified_")]),
        "total_sessions": len(sessions),
        "cdp_status": cdp_status,
        "pruned_stale_sessions": pruned_stale_sessions,
        "sessions": sessions,
    })


# ===== PLATFORM ORCHESTRATION =====


@mcp.tool(
    name="bridge_project_create",
    description=(
        "Create a new Bridge project from a full project config payload. "
        "This wraps POST /projects/create and returns the created project metadata."
    ),
)
async def bridge_project_create(config: dict[str, Any]) -> str:
    """Create a Bridge project from a canonical config payload."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not isinstance(config, dict) or not config:
        return json.dumps({"error": "config must be a non-empty object"})
    try:
        resp = await _bridge_post("/projects/create", json=config)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_runtime_configure",
    description=(
        "Configure and start the Bridge runtime from a full runtime config payload. "
        "This wraps POST /runtime/configure."
    ),
)
async def bridge_runtime_configure(config: dict[str, Any]) -> str:
    """Configure and start the runtime."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not isinstance(config, dict) or not config:
        return json.dumps({"error": "config must be a non-empty object"})
    try:
        resp = await _bridge_post("/runtime/configure", json=config)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_runtime_stop",
    description="Stop the current Bridge runtime and clear the active runtime state.",
)
async def bridge_runtime_stop() -> str:
    """Stop the current runtime."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_post("/runtime/stop", json={})
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_industry_templates",
    description=(
        "Search industry templates for team creation. "
        "Optional query parameter filters by keyword (e.g. 'trading', 'marketing'). "
        "Returns matching templates with agent definitions, scopes, and recommended MCPs."
    ),
)
async def bridge_industry_templates(query: str = "") -> str:
    """Search industry templates."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        params = {}
        if query:
            params["q"] = query
        resp = await _bridge_get("/industry-templates", params=params)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_mcp_register",
    description=(
        "Register a runtime MCP server in the central catalog. "
        "For stdio: provide name, transport='stdio', command, args, env. "
        "For remote: provide name, transport='streamable-http', url, headers (optional). "
        "Registered servers become available to agents via mcp_servers field."
    ),
)
async def bridge_mcp_register(
    name: str,
    transport: str = "stdio",
    command: str = "",
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    url: str = "",
    headers: dict[str, str] | None = None,
    include_in_all: bool = False,
) -> str:
    """Register a runtime MCP server."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    spec: dict[str, Any] = {"transport": transport}
    if transport == "stdio":
        spec["command"] = command
        if args:
            spec["args"] = args
        if env:
            spec["env"] = env
    elif transport == "streamable-http":
        spec["url"] = url
        if headers:
            spec["headers"] = headers
    spec["include_in_all"] = include_in_all
    try:
        resp = await _bridge_post("/mcp-catalog", json={"name": name, "spec": spec})
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_agent_create",
    description=(
        "Create a new agent entry in team.json. Required: id (lowercase, 3-30 chars), "
        "description or role. Optional: engine, model, level, reports_to, mcp_servers, skills, "
        "permissions, scope, project_path, config_dir, name, active. "
        "After creation, use bridge_agent_start to launch it."
    ),
)
async def bridge_agent_create(
    id: str,
    description: str = "",
    role: str = "",
    name: str = "",
    engine: str = "claude",
    level: int = 3,
    reports_to: str = "buddy",
    mcp_servers: str | list[str] = "bridge",
    skills: list[str] | None = None,
    permissions: list[str] | None = None,
    scope: list[str] | None = None,
    project_path: str = "",
    config_dir: str = "",
    model: str = "",
    active: bool = True,
) -> str:
    """Create a new agent in team.json."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    payload: dict[str, Any] = {
        "id": id,
        "description": description,
        "role": role,
        "name": name,
        "engine": engine,
        "level": level,
        "reports_to": reports_to,
        "mcp_servers": mcp_servers,
        "active": active,
    }
    if model:
        payload["model"] = model
    if skills:
        payload["skills"] = skills
    if permissions:
        payload["permissions"] = permissions
    if scope:
        payload["scope"] = scope
    if project_path:
        payload["project_path"] = project_path
    if config_dir:
        payload["config_dir"] = config_dir
    try:
        resp = await _bridge_post("/agents/create", json=payload)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_agent_start",
    description=(
        "Start or nudge a Bridge agent by ID. "
        "This wraps POST /agents/{id}/start."
    ),
)
async def bridge_agent_start(agent_id: str) -> str:
    """Start or resume a Bridge agent."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    agent_id = str(agent_id).strip()
    if not agent_id:
        return json.dumps({"error": "agent_id is required"})
    try:
        resp = await _bridge_post(f"/agents/{agent_id}/start", json={"from": _agent_id})
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


# ---------------------------------------------------------------------------
# Self-Reflection / Growth Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_lesson_add",
    description=(
        "Add a lesson learned to your persistent memory. "
        "Categories: general, technical, collaboration, process. "
        "Confidence: 0.0-1.0 (how certain is this lesson). "
        "Use this after completing tasks, encountering errors, or receiving feedback."
    ),
)
async def bridge_lesson_add(
    title: str,
    content: str,
    category: str = "general",
    confidence: float = 1.0,
) -> str:
    """Add a lesson to the agent's persistent memory."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        from self_reflection import SelfReflection
        from pathlib import Path
        base = Path(__file__).resolve().parent
        sr = SelfReflection(base, agent_configs=_self_reflection_agent_configs())
        lesson = sr.add_lesson(
            agent_id=_agent_id,
            title=title,
            content=content,
            category=category,
            confidence=confidence,
        )
        return json.dumps({
            "ok": True,
            "lesson": {
                "title": lesson.title,
                "content": lesson.content,
                "category": lesson.category,
                "confidence": lesson.confidence,
                "agent_id": lesson.agent_id,
                "created_at": lesson.created_at,
            },
        })
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_reflect",
    description=(
        "Generate a self-reflection prompt for session-end review. "
        "Provide a brief session summary as context. "
        "Returns questions to guide your reflection and lesson extraction."
    ),
)
async def bridge_reflect(
    session_summary: str = "",
    tasks_completed: int = 0,
) -> str:
    """Generate reflection questions for session review."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        from self_reflection import SelfReflection
        from pathlib import Path
        base = Path(__file__).resolve().parent
        sr = SelfReflection(base, agent_configs=_self_reflection_agent_configs())
        prompt = sr.generate_reflection_prompt(
            agent_id=_agent_id,
            context=session_summary,
            tasks_completed=tasks_completed,
        )
        return json.dumps({
            "ok": True,
            "agent_id": prompt.agent_id,
            "questions": prompt.questions,
            "context": prompt.context,
        })
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_growth_propose",
    description=(
        "Propose a growth update for your soul. "
        "Suggest updates to your strengths or growth areas based on experience. "
        "Proposals require human approval before being applied to SOUL.md."
    ),
)
async def bridge_growth_propose(
    section: str,
    old_value: str,
    new_value: str,
    reason: str,
) -> str:
    """Propose an update to your soul (requires approval)."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if section not in ("strengths", "growth_area", "communication_style", "core_truths", "quirks"):
        return json.dumps({"error": f"Invalid section: {section}. Valid: strengths, growth_area, communication_style, core_truths, quirks"})
    try:
        from soul_engine import propose_soul_update
        from pathlib import Path
        # Find agent workspace — search project subdirectories dynamically
        _project_root = Path(__file__).resolve().parent.parent.parent
        workspace = None
        # Search all .agent_sessions dirs under project root (any depth)
        _search_dirs = list(_project_root.glob(f"**/.agent_sessions/{_agent_id}"))
        for search_dir in _search_dirs:
            if search_dir.exists():
                workspace = search_dir
                break
        if not workspace:
            return json.dumps({"error": f"Could not find workspace for agent {_agent_id}"})
        proposal = propose_soul_update(
            workspace=workspace,
            section=section,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )
        return json.dumps({"ok": True, "proposal": proposal})
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_workflow_compile",
    description=(
        "Compile a canonical Bridge workflow definition into the n8n workflow format "
        "without deploying it."
    ),
)
async def bridge_workflow_compile(definition: dict[str, Any]) -> str:
    """Compile a Bridge workflow definition."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not isinstance(definition, dict) or not definition:
        return json.dumps({"error": "definition must be a non-empty object"})
    try:
        resp = await _bridge_post("/workflows/compile", json={"definition": definition})
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_workflow_deploy",
    description=(
        "Compile and deploy a canonical Bridge workflow definition into n8n. "
        "Returns workflow metadata, validation, and any registered Bridge integrations."
    ),
)
async def bridge_workflow_deploy(
    definition: dict[str, Any],
    activate: bool = True,
) -> str:
    """Compile and deploy a Bridge workflow definition."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not isinstance(definition, dict) or not definition:
        return json.dumps({"error": "definition must be a non-empty object"})
    try:
        resp = await _bridge_post(
            "/workflows/deploy",
            json={"definition": definition, "activate": bool(activate)},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_workflow_deploy_template",
    description=(
        "Deploy a named workflow template with variable substitution via "
        "POST /workflows/deploy-template."
    ),
)
async def bridge_workflow_deploy_template(
    template_id: str,
    variables: dict[str, Any] | None = None,
) -> str:
    """Deploy a Bridge workflow template."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    template_id = str(template_id).strip()
    if not template_id:
        return json.dumps({"error": "template_id is required"})
    payload: dict[str, Any] = {"template_id": template_id, "variables": variables or {}}
    try:
        resp = await _bridge_post("/workflows/deploy-template", json=payload)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


# ===== TEAM MANAGEMENT (Phase 2) =====


@mcp.tool(
    name="bridge_team_list",
    description=(
        "List all teams from the Bridge server. "
        "Returns team IDs, names, leads, members, online counts, and last activity."
    ),
)
async def bridge_team_list(include_inactive: bool = False) -> str:
    """List all teams."""
    try:
        params: dict[str, str] = {}
        if include_inactive:
            params["include_inactive"] = "true"
        resp = await _bridge_get("/teams", params=params)
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_team_get",
    description=(
        "Get details of a specific team by ID. "
        "Returns team config, members with live status, and recent activity."
    ),
)
async def bridge_team_get(team_id: str) -> str:
    """Get team details."""
    try:
        resp = await _bridge_get(f"/teams/{team_id}")
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_team_create",
    description=(
        "Create a new team. Requires name and lead. "
        "Optionally provide members list and scope description."
    ),
)
async def bridge_team_create(
    name: str,
    lead: str,
    members: list[str] | None = None,
    scope: str = "",
) -> str:
    """Create a new team."""
    try:
        payload: dict[str, Any] = {"name": name, "lead": lead, "scope": scope}
        if members:
            payload["members"] = members
        resp = await _bridge_post("/teams", json=payload)
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_team_update_members",
    description=(
        "Add or remove members from a team. "
        "Provide add and/or remove lists of agent IDs."
    ),
)
async def bridge_team_update_members(
    team_id: str,
    add: list[str] | None = None,
    remove: list[str] | None = None,
) -> str:
    """Update team membership."""
    try:
        payload: dict[str, Any] = {}
        if add:
            payload["add"] = add
        if remove:
            payload["remove"] = remove
        resp = await _bridge_put(f"/teams/{team_id}/members", json=payload)
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_team_delete",
    description="Delete a team by ID. Soft-deletes by setting active=false.",
)
async def bridge_team_delete(team_id: str) -> str:
    """Delete a team."""
    try:
        resp = await _bridge_delete(f"/teams/{team_id}")
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Voice Gateway (Phone) — Port 8877
# ---------------------------------------------------------------------------

VOICE_GATEWAY_URL = "http://127.0.0.1:8877"
_voice_http: httpx.AsyncClient | None = None
_pending_phone_call_tasks: dict[str, asyncio.Task[None]] = {}


def _get_voice_http() -> httpx.AsyncClient:
    """Lazy-init Voice Gateway HTTP client."""
    global _voice_http
    if _voice_http is None or _voice_http.is_closed:
        _voice_http = httpx.AsyncClient(base_url=VOICE_GATEWAY_URL, timeout=30.0)
    return _voice_http


async def _await_phone_call_approval(
    request_id: str, number: str, agent_id: str
) -> None:
    """Wait for approval in the background and place the call on success."""
    try:
        elapsed = 0
        while elapsed < 120:
            check_resp = await _bridge_get(f"/approval/{request_id}")
            check_resp.raise_for_status()
            check_data = check_resp.json()
            status = check_data.get("status", "")
            if status == "approved":
                owner_error = _approval_owner_error(check_data, request_id)
                if owner_error:
                    log.warning("Phone approval owner mismatch for %s: %s", request_id, owner_error)
                    return
                client = _get_voice_http()
                resp = await client.post(
                    "/phone/call", json={"number": number, "agent_id": agent_id}
                )
                resp.raise_for_status()
                log.info("Phone call approved and started for %s", request_id)
                return
            if status in ("denied", "expired"):
                log.info("Phone call %s not started: approval status=%s", request_id, status)
                return
            await asyncio.sleep(3)
            elapsed += 3
        log.warning("Phone approval timed out for %s", request_id)
    except Exception as exc:
        log.warning("Phone approval watcher failed for %s: %s", request_id, exc)
    finally:
        _pending_phone_call_tasks.pop(request_id, None)


@mcp.tool(
    name="bridge_phone_call",
    description=(
        "Start an outgoing phone call via the Voice Gateway. "
        "Requires Leo's approval before the call is placed. "
        "Returns the approval request_id — use bridge_approval_wait to wait for approval, "
        "then the call starts automatically."
    ),
)
async def bridge_phone_call(number: str) -> str:
    """Start outgoing call. Returns immediately and places the call after approval."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    # Approval gate — phone calls require explicit Leo approval
    approval_body: dict[str, Any] = {
        "agent_id": _agent_id,
        "action": "phone_call",
        "target": number,
        "description": f"Agent {_agent_id} wants to call {number}",
        "risk_level": "medium",
        "timeout_seconds": 120,
    }
    try:
        approval_resp = await _bridge_post("/approval/request", json=approval_body)
        approval_resp.raise_for_status()
        approval_data = approval_resp.json()
        if approval_data.get("status") == "auto_approved":
            client = _get_voice_http()
            resp = await client.post("/phone/call", json={"number": number, "agent_id": _agent_id})
            resp.raise_for_status()
            data = resp.json()
            data.setdefault("status", "in_call")
            data["auto_approved"] = True
            return json.dumps(data)
        request_id = str(approval_data.get("request_id", "")).strip()
        if not request_id:
            return json.dumps({"error": "Approval request did not return request_id"})
        _pending_phone_call_tasks[request_id] = asyncio.create_task(
            _await_phone_call_approval(request_id, number, _agent_id)
        )
        return json.dumps({
            "status": "pending_approval",
            "request_id": request_id,
            "message": (
                "Anruf wartet auf Genehmigung. "
                f"Nutze bridge_approval_wait('{request_id}') zum Warten; "
                "der Anruf startet danach automatisch."
            ),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_phone_speak",
    description=(
        "Send text to be spoken (TTS) on the active phone call. "
        "The Voice Gateway converts text to speech and plays it to the caller."
    ),
)
async def bridge_phone_speak(text: str) -> str:
    """Speak text on active call via TTS."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        client = _get_voice_http()
        resp = await client.post("/phone/speak", json={"text": text, "agent_id": _agent_id})
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_phone_listen",
    description=(
        "Get the latest speech-to-text transcript from the active phone call. "
        "Returns the most recent caller speech converted to text. "
        "Use wait parameter (seconds) to block until new speech arrives (0 = immediate)."
    ),
)
async def bridge_phone_listen(wait: int = 0) -> str:
    """Get STT text from active call."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        client = _get_voice_http()
        params: dict[str, Any] = {"agent_id": _agent_id}
        if wait > 0:
            params["wait"] = min(wait, 30)
        resp = await client.get("/phone/listen", params=params, timeout=max(35.0, wait + 5.0))
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_phone_hangup",
    description="End the active phone call.",
)
async def bridge_phone_hangup() -> str:
    """Hang up active call."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        client = _get_voice_http()
        resp = await client.post("/phone/hangup", json={"agent_id": _agent_id})
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_phone_status",
    description=(
        "Get the current phone call status. "
        "Returns: idle, ringing, in_call, or error with details."
    ),
)
async def bridge_phone_status() -> str:
    """Get phone call status."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        client = _get_voice_http()
        resp = await client.get("/phone/status", params={"agent_id": _agent_id})
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Token Usage Reporting (C2-Integration)
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_report_usage",
    description=(
        "Report token usage for cost tracking. "
        "Call after significant API calls or at end of task. "
        "Data feeds into GET /metrics/costs dashboard."
    ),
)
async def bridge_report_usage(
    input_tokens: int,
    output_tokens: int,
    model: str = "",
    engine: str = "claude",
    cached_tokens: int = 0,
) -> str:
    """Report token usage to the cost tracker."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        client = _get_http()
        resp = await client.post(
            "/metrics/tokens",
            json={
                "agent_id": _agent_id,
                "engine": engine,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": cached_tokens,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Vision / OCR Analysis (A2)
# ---------------------------------------------------------------------------

_VISION_API_URL = "https://api.anthropic.com/v1/messages"
_VISION_MODEL = "claude-sonnet-4-6"  # cost-effective for vision tasks
_VISION_MAX_TOKENS = 4096

_VISION_SYSTEM_PROMPT = """You are a UI analysis assistant. Analyze the screenshot and return a structured JSON response with:
1. "elements": Array of UI elements found (buttons, inputs, links, text, images) with {type, text, location_hint}
2. "text": Array of all readable text found on screen
3. "suggested_actions": Array of possible interactions {action, target, description}
4. "page_description": Brief description of what the page/screen shows

Return ONLY valid JSON, no markdown code fences."""


@mcp.tool(
    name="bridge_vision_analyze",
    description=(
        "Analyze a screenshot using Claude Vision API. "
        "Takes a file path to a screenshot (PNG/JPG) and returns structured analysis: "
        "UI elements, text content, and suggested actions. "
        "Uses Claude Sonnet for cost-effective vision analysis."
    ),
)
async def bridge_vision_analyze(
    screenshot_path: str,
    prompt: str = "Analyze this screenshot. Identify all UI elements, text, and suggest possible actions.",
    model: str = "",
) -> str:
    """Analyze a screenshot via Claude Vision API."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    # Resolve and validate path
    path = os.path.expanduser(screenshot_path.strip())
    if not os.path.isfile(path):
        return json.dumps({"error": f"File not found: {path}"})

    # Check file size (max 20MB for API)
    file_size = os.path.getsize(path)
    if file_size > 20 * 1024 * 1024:
        return json.dumps({"error": f"File too large: {file_size} bytes (max 20MB)"})

    # Determine media type
    ext = os.path.splitext(path)[1].lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
    media_type = media_types.get(ext)
    if not media_type:
        return json.dumps({"error": f"Unsupported image format: {ext}. Use PNG, JPG, GIF, or WebP."})

    # Read and base64-encode
    import base64
    try:
        with open(path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("ascii")
    except OSError as exc:
        return json.dumps({"error": f"Failed to read file: {exc}"})

    # Get API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return json.dumps({"error": "ANTHROPIC_API_KEY not set in environment"})

    # Build request
    use_model = model.strip() or _VISION_MODEL
    request_body = {
        "model": use_model,
        "max_tokens": _VISION_MAX_TOKENS,
        "system": _VISION_SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                _VISION_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=request_body,
            )
            if resp.status_code != 200:
                return json.dumps({"error": f"API error {resp.status_code}: {resp.text[:500]}"})
            data = resp.json()
    except httpx.TimeoutException:
        return json.dumps({"error": "Vision API call timed out (60s)"})
    except Exception as exc:
        return json.dumps({"error": f"Vision API call failed: {exc}"})

    # Extract response text
    content_blocks = data.get("content", [])
    text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
    raw_text = "\n".join(text_parts).strip()

    # Try to parse as JSON
    analysis = None
    try:
        analysis = json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code fence
        import re as _re
        m = _re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw_text, _re.DOTALL)
        if m:
            try:
                analysis = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

    # Build result
    usage = data.get("usage", {})
    result = {
        "ok": True,
        "model": use_model,
        "screenshot": path,
        "analysis": analysis if analysis else {"raw_text": raw_text},
        "usage": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        },
    }

    # Log token usage via token_tracker if available
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import token_tracker
        token_tracker.log_usage(
            agent_id=_agent_id,
            engine="claude",
            model=use_model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cached_tokens=usage.get("cache_read_input_tokens", 0),
        )
    except Exception:
        pass  # Non-critical

    return json.dumps(result)


# ---------------------------------------------------------------------------
# Vision-Action Loop (D1)
# ---------------------------------------------------------------------------

_VISION_ACT_SYSTEM = """You are a browser automation agent. You see a screenshot of a web page and must decide the NEXT action to achieve the user's goal.

You MUST return ONLY valid JSON with this exact structure:
{
  "done": false,
  "reasoning": "Brief explanation of what you see and why you chose this action",
  "action": {
    "type": "click|fill|goto|evaluate|wait|done",
    "selector": "CSS selector (for click/fill)",
    "value": "text to type (for fill) or URL (for goto) or JS expression (for evaluate)",
    "description": "Human-readable description of the action"
  }
}

Action types:
- "click": Click an element. Requires "selector".
- "fill": Fill an input field. Requires "selector" and "value".
- "goto": Navigate to a URL. Requires "value" (the URL).
- "evaluate": Run JavaScript on the page. Requires "value" (JS expression).
- "wait": Wait 2 seconds (use when page is loading).
- "done": Goal achieved. Set "done": true.

Rules:
- Use specific CSS selectors (prefer [name=], [id=], [type=], [aria-label=], button text).
- If the goal appears achieved, set "done": true.
- If you're stuck after multiple attempts, set "done": true with reasoning explaining why.
- NEVER use browser APIs that require permissions (clipboard, notifications, etc).
- Return ONLY JSON, no markdown fences."""


async def _vision_act_analyze(
    image_data: str,
    media_type: str,
    goal: str,
    step: int,
    max_steps: int,
    history: list[dict],
) -> dict | None:
    """Call Claude Vision API with goal-aware prompt for action decision."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    history_text = ""
    if history:
        history_text = "\n\nPrevious actions:\n"
        for h in history[-5:]:  # Last 5 steps to keep context manageable
            history_text += f"- Step {h['step']}: {h['action_desc']} → {h['result']}\n"

    user_prompt = (
        f"GOAL: {goal}\n"
        f"Step {step}/{max_steps}.{history_text}\n"
        f"Look at the screenshot and decide the next action to achieve the goal."
    )

    request_body = {
        "model": _VISION_MODEL,
        "max_tokens": 1024,
        "system": _VISION_ACT_SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": user_prompt},
                ],
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                _VISION_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=request_body,
            )
            if resp.status_code != 200:
                log.warning("Vision-act API error %d: %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
    except Exception as exc:
        log.warning("Vision-act API call failed: %s", exc)
        return None

    # Extract text and parse JSON
    content_blocks = data.get("content", [])
    raw = "\n".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()

    result = None
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        import re as _re
        m = _re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, _re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

    # Log token usage
    usage = data.get("usage", {})
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import token_tracker
        token_tracker.log_usage(
            agent_id=_agent_id or "unknown",
            engine="claude",
            model=_VISION_MODEL,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cached_tokens=usage.get("cache_read_input_tokens", 0),
        )
    except Exception:
        pass

    return result


@mcp.tool(
    name="bridge_vision_act",
    description=(
        "Autonomous vision-action loop: takes a goal and executes browser actions "
        "to achieve it. Requires an active stealth browser session. "
        "Loop: screenshot → Claude Vision analysis → action → verify. "
        "Returns steps taken, success status, and action history."
    ),
)
async def bridge_vision_act(
    session_id: str,
    goal: str,
    max_steps: int = 10,
) -> str:
    """Vision-action loop: screenshot → analyze → act → verify → repeat."""
    if _agent_id is None:
        return json.dumps({"status": "error", "error": "not registered"})

    session = _get_stealth_session(session_id)
    if not session:
        return json.dumps({"status": "error", "error": f"session '{session_id}' not found"})

    if not goal or not goal.strip():
        return json.dumps({"status": "error", "error": "goal must not be empty"})

    max_steps = max(1, min(max_steps, 25))  # Clamp 1-25

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return json.dumps({"status": "error", "error": "ANTHROPIC_API_KEY not set"})

    import base64

    history: list[dict] = []
    final_screenshot = ""
    success = False

    for step in range(1, max_steps + 1):
        # 1. Take screenshot
        try:
            ss_path = f"/tmp/vision_act_{session_id}_{step}_{time.time_ns()}.png"
            await session.page.screenshot(path=ss_path, full_page=False)
            final_screenshot = ss_path
        except Exception as exc:
            history.append({"step": step, "action_desc": "screenshot", "result": f"FAIL: {exc}"})
            break

        # 2. Base64 encode
        try:
            with open(ss_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("ascii")
        except OSError as exc:
            history.append({"step": step, "action_desc": "read screenshot", "result": f"FAIL: {exc}"})
            break

        # 3. Vision analysis → action decision
        decision = await _vision_act_analyze(
            image_data=image_data,
            media_type="image/png",
            goal=goal,
            step=step,
            max_steps=max_steps,
            history=history,
        )

        if not decision:
            history.append({"step": step, "action_desc": "vision API", "result": "FAIL: no response"})
            break

        # 4. Check if done
        if decision.get("done", False):
            reasoning = decision.get("reasoning", "Goal achieved")
            history.append({"step": step, "action_desc": "done", "result": reasoning})
            success = True
            break

        # 5. Execute action
        action = decision.get("action", {})
        action_type = action.get("type", "")
        action_desc = action.get("description", action_type)
        selector = action.get("selector", "")
        value = action.get("value", "")

        try:
            if action_type == "click" and selector:
                await session.page.click(selector, timeout=10000)
                try:
                    await session.page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                history.append({"step": step, "action_desc": f"click: {action_desc}", "result": "ok"})

            elif action_type == "fill" and selector and value:
                await session.page.fill(selector, value, timeout=10000)
                history.append({"step": step, "action_desc": f"fill: {action_desc}", "result": "ok"})

            elif action_type == "goto" and value:
                if not value.startswith(("http://", "https://")):
                    history.append({"step": step, "action_desc": f"goto: {value}", "result": "FAIL: invalid URL"})
                    continue
                await session.page.goto(value, timeout=30000)
                try:
                    await session.page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                history.append({"step": step, "action_desc": f"goto: {action_desc}", "result": "ok"})

            elif action_type == "evaluate" and value:
                eval_result = await session.page.evaluate(value)
                result_str = str(eval_result)[:200] if eval_result is not None else "null"
                history.append({"step": step, "action_desc": f"evaluate: {action_desc}", "result": result_str})

            elif action_type == "wait":
                await asyncio.sleep(2)
                history.append({"step": step, "action_desc": "wait 2s", "result": "ok"})

            else:
                history.append({"step": step, "action_desc": f"unknown: {action_type}", "result": "skipped"})

        except Exception as exc:
            history.append({"step": step, "action_desc": action_desc, "result": f"FAIL: {exc}"})
            # Don't break on action failure — let the loop retry with a new screenshot

        # Brief pause between steps for page to settle
        await asyncio.sleep(0.5)

    return json.dumps({
        "status": "ok" if success else "incomplete",
        "goal": goal,
        "success": success,
        "steps_taken": len(history),
        "max_steps": max_steps,
        "final_screenshot": final_screenshot,
        "history": history,
    })


# ---------------------------------------------------------------------------
# B3: n8n Webhook-Bridge — execute n8n workflows as tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="bridge_workflow_execute",
    description=(
        "Execute an n8n workflow by name via its webhook trigger. "
        "Finds the workflow in n8n, extracts the webhook URL, and POSTs input_data to it. "
        "Returns the workflow response. Requires the workflow to have a Webhook trigger node and be active."
    ),
)
async def bridge_workflow_execute(
    workflow_name: str,
    input_data: dict[str, Any] | None = None,
    timeout: int = 60,
) -> str:
    """Execute an n8n workflow via webhook."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not workflow_name:
        return json.dumps({"error": "workflow_name is required"})
    timeout = max(5, min(timeout, 300))

    # Load n8n config
    n8n_base, n8n_api_key = _load_n8n_config()
    if not n8n_api_key:
        return json.dumps({"error": "n8n API key not configured (set N8N_API_KEY or ~/.config/bridge/n8n.env)"})

    n8n_headers = {"X-N8N-API-KEY": n8n_api_key, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(base_url=n8n_base, timeout=15, headers=n8n_headers) as client:
            # Step 1: List workflows to find by name
            resp = await client.get("/api/v1/workflows", params={"limit": "100"})
            if resp.status_code >= 400:
                return json.dumps({"error": f"n8n API error: HTTP {resp.status_code}"})
            workflows = resp.json().get("data", [])

            # Find matching workflow (case-insensitive, exact first, partial fallback)
            match = None
            name_lower = workflow_name.lower()
            for wf in workflows:
                if wf.get("name", "").lower() == name_lower:
                    match = wf
                    break
            if not match:
                for wf in workflows:
                    if name_lower in wf.get("name", "").lower():
                        match = wf
                        break
            if not match:
                available = [wf.get("name", "") for wf in workflows[:20]]
                return json.dumps({
                    "error": f"Workflow '{workflow_name}' not found",
                    "available_workflows": available,
                })

            if not match.get("active"):
                return json.dumps({
                    "error": f"Workflow '{match['name']}' is not active. Activate it first.",
                    "workflow_id": match.get("id"),
                })

            wf_id = match["id"]

            # Step 2: Get full workflow to find webhook path
            resp2 = await client.get(f"/api/v1/workflows/{wf_id}")
            if resp2.status_code >= 400:
                return json.dumps({"error": f"Could not get workflow details: HTTP {resp2.status_code}"})

            wf_data = resp2.json()
            nodes = wf_data.get("nodes", [])
            webhook_path = None
            for node in nodes:
                node_type = node.get("type", "")
                if "webhook" in node_type.lower():
                    webhook_path = node.get("parameters", {}).get("path")
                    break

            if not webhook_path:
                return json.dumps({
                    "error": f"Workflow '{match['name']}' has no webhook trigger node",
                    "workflow_id": wf_id,
                })

        # Step 3: POST to webhook
        webhook_url = f"{n8n_base}/webhook/{webhook_path}"
        payload = input_data or {}

        async with httpx.AsyncClient(timeout=timeout) as wh_client:
            wh_resp = await wh_client.post(webhook_url, json=payload)

        # Parse response
        ct = wh_resp.headers.get("content-type", "")
        if "json" in ct:
            resp_data = wh_resp.json()
        else:
            resp_data = wh_resp.text[:2000]

        return json.dumps({
            "ok": True,
            "workflow_name": match["name"],
            "workflow_id": wf_id,
            "webhook_url": webhook_url,
            "status_code": wh_resp.status_code,
            "response": resp_data,
        })

    except httpx.TimeoutException:
        return json.dumps({"error": f"Webhook request timed out after {timeout}s"})
    except Exception as exc:
        return json.dumps({"error": f"Workflow execution failed: {exc}"})


# ---------------------------------------------------------------------------
# Skills Management — list, activate, deactivate via server API
# ---------------------------------------------------------------------------


@mcp.tool(
    name="bridge_skill_list",
    description=(
        "List all available skills and your currently assigned skills. "
        "Shows skill name, description, and whether it's assigned to you."
    ),
)
async def bridge_skill_list() -> str:
    """List available and assigned skills via server API."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        # Get all available skills
        async with httpx.AsyncClient(timeout=10.0) as client:
            all_resp = await client.get(f"{BRIDGE_HTTP}/skills")
            if all_resp.status_code != 200:
                return json.dumps({"error": f"GET /skills failed: {all_resp.status_code}"})
            all_data = all_resp.json()

            # Get agent's assigned skills
            agent_resp = await client.get(f"{BRIDGE_HTTP}/skills/{_agent_id}")
            if agent_resp.status_code != 200:
                return json.dumps({"error": f"GET /skills/{_agent_id} failed: {agent_resp.status_code}"})
            agent_data = agent_resp.json()

        available = all_data.get("skills", [])
        assigned = set(agent_data.get("skills", []))
        suggested = agent_data.get("suggested", [])

        skills_out = []
        for s in available:
            sid = s.get("id", s.get("name", ""))
            skills_out.append({
                "name": sid,
                "description": s.get("description", ""),
                "assigned": sid in assigned,
            })

        return json.dumps({
            "ok": True,
            "agent_id": _agent_id,
            "total_available": len(available),
            "assigned_count": len(assigned),
            "assigned": sorted(assigned),
            "suggested": suggested,
            "skills": skills_out,
        })
    except Exception as exc:
        return json.dumps({"error": f"skill_list failed: {exc}"})


@mcp.tool(
    name="bridge_skill_activate",
    description=(
        "Activate/assign a skill to yourself. The skill must exist in the skills directory. "
        "Adds it to your skills list in team.json. Max 20 skills per agent."
    ),
)
async def bridge_skill_activate(name: str) -> str:
    """Activate a skill by adding it to the agent's skill list."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not name or not name.strip():
        return json.dumps({"error": "skill name is required"})
    name = name.strip()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get current skills
            agent_resp = await client.get(f"{BRIDGE_HTTP}/skills/{_agent_id}")
            if agent_resp.status_code != 200:
                return json.dumps({"error": f"Failed to get current skills: {agent_resp.status_code}"})
            current = agent_resp.json().get("skills", [])

            if name in current:
                return json.dumps({"ok": True, "message": f"Skill '{name}' already active", "skills": current})

            # Add the new skill
            new_skills = current + [name]

            # Assign via API
            assign_resp = await client.post(
                f"{BRIDGE_HTTP}/skills/assign",
                json={"agent_id": _agent_id, "skills": new_skills},
            )
            if assign_resp.status_code != 200:
                error_data = assign_resp.json() if assign_resp.headers.get("content-type", "").startswith("application/json") else {}
                return json.dumps({"error": f"Activation failed: {error_data.get('error', assign_resp.status_code)}"})

            result = assign_resp.json()
            return json.dumps({
                "ok": True,
                "activated": name,
                "skills": result.get("skills", new_skills),
                "invalid": result.get("invalid", []),
            })
    except Exception as exc:
        return json.dumps({"error": f"skill_activate failed: {exc}"})


@mcp.tool(
    name="bridge_skill_deactivate",
    description=(
        "Deactivate/remove a skill from yourself. "
        "Cannot deactivate 'bridge-agent-core' (always required)."
    ),
)
async def bridge_skill_deactivate(name: str) -> str:
    """Deactivate a skill by removing it from the agent's skill list."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not name or not name.strip():
        return json.dumps({"error": "skill name is required"})
    name = name.strip()

    if name == "bridge-agent-core":
        return json.dumps({"error": "Cannot deactivate 'bridge-agent-core' — it is always required."})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get current skills
            agent_resp = await client.get(f"{BRIDGE_HTTP}/skills/{_agent_id}")
            if agent_resp.status_code != 200:
                return json.dumps({"error": f"Failed to get current skills: {agent_resp.status_code}"})
            current = agent_resp.json().get("skills", [])

            if name not in current:
                return json.dumps({"ok": True, "message": f"Skill '{name}' not active", "skills": current})

            # Remove the skill
            new_skills = [s for s in current if s != name]

            # Assign via API
            assign_resp = await client.post(
                f"{BRIDGE_HTTP}/skills/assign",
                json={"agent_id": _agent_id, "skills": new_skills},
            )
            if assign_resp.status_code != 200:
                error_data = assign_resp.json() if assign_resp.headers.get("content-type", "").startswith("application/json") else {}
                return json.dumps({"error": f"Deactivation failed: {error_data.get('error', assign_resp.status_code)}"})

            result = assign_resp.json()
            return json.dumps({
                "ok": True,
                "deactivated": name,
                "skills": result.get("skills", new_skills),
            })
    except Exception as exc:
        return json.dumps({"error": f"skill_deactivate failed: {exc}"})


# ---------------------------------------------------------------------------
# D2: Desktop Interaction — xdotool + screenshot for arbitrary apps
# ---------------------------------------------------------------------------

_DESKTOP_SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")


def _desktop_parse_geometry(raw: str) -> dict[str, int]:
    geometry = {"x": 0, "y": 0, "width": 0, "height": 0}
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("Position:"):
            pos = line.split(":", 1)[1].strip().split("(")[0].strip()
            parts = pos.split(",")
            if len(parts) == 2:
                try:
                    geometry["x"] = int(parts[0])
                    geometry["y"] = int(parts[1])
                except ValueError:
                    pass
        elif line.startswith("Geometry:"):
            size = line.split(":", 1)[1].strip()
            parts = size.split("x")
            if len(parts) == 2:
                try:
                    geometry["width"] = int(parts[0])
                    geometry["height"] = int(parts[1])
                except ValueError:
                    pass
    return geometry


async def _desktop_get_focused_window_state() -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        "xdotool", "getwindowfocus",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
    if proc.returncode != 0:
        return {"available": False, "error": stderr.decode()[:200]}
    window_id = stdout.decode().strip()
    if not window_id:
        return {"available": False, "error": "no focused window id"}

    name = ""
    geometry = {"x": 0, "y": 0, "width": 0, "height": 0}

    proc_name = await asyncio.create_subprocess_exec(
        "xdotool", "getwindowname", window_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
    )
    stdout_name, _ = await asyncio.wait_for(proc_name.communicate(), timeout=5)
    if proc_name.returncode == 0:
        name = stdout_name.decode().strip()

    proc_geo = await asyncio.create_subprocess_exec(
        "xdotool", "getwindowgeometry", window_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
    )
    stdout_geo, _ = await asyncio.wait_for(proc_geo.communicate(), timeout=5)
    if proc_geo.returncode == 0:
        geometry = _desktop_parse_geometry(stdout_geo.decode())

    return {
        "available": True,
        "window_id": window_id,
        "name": name,
        **geometry,
    }


def _desktop_ocr_available() -> bool:
    return bool(shutil.which("tesseract"))


async def _desktop_ocr_image(image_path: str) -> dict[str, Any]:
    if not _desktop_ocr_available():
        return {"available": False, "text": "", "engine": None}
    proc = await asyncio.create_subprocess_exec(
        "tesseract", image_path, "stdout", "--psm", "6",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    if proc.returncode != 0:
        return {
            "available": True,
            "ok": False,
            "text": "",
            "engine": "tesseract",
            "error": stderr.decode()[:200],
        }
    text = stdout.decode("utf-8", errors="replace")
    return {
        "available": True,
        "ok": True,
        "text": text[:5000],
        "length": len(text),
        "engine": "tesseract",
    }


def _normalize_desktop_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _desktop_text_contains(value: str, expected: str) -> bool:
    norm_expected = _normalize_desktop_text(expected)
    if not norm_expected:
        return True
    return norm_expected in _normalize_desktop_text(value)


def _desktop_has_verify_conditions(
    *,
    expect_focused_window: str = "",
    expect_focused_name_contains: str = "",
    expect_window_name_contains: str = "",
    expect_clipboard_contains: str = "",
    expect_ocr_contains: str = "",
    require_screenshot: bool = False,
) -> bool:
    return any(
        [
            expect_focused_window,
            expect_focused_name_contains,
            expect_window_name_contains,
            expect_clipboard_contains,
            expect_ocr_contains,
            require_screenshot,
        ]
    )


@mcp.tool(
    name="bridge_desktop_observe",
    description=(
        "Capture a structured desktop snapshot with the focused window, optional window list, "
        "optional screenshot, clipboard text, and optional OCR when available."
    ),
)
async def bridge_desktop_observe(
    window_name: str = "",
    include_screenshot: bool = True,
    include_windows: bool = True,
    include_clipboard: bool = True,
    ocr: bool = False,
) -> str:
    if _agent_id is None:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_observe",
            raw_payload={"status": "error", "error": "Not registered. Call bridge_register first."},
        )

    run_id = _default_run_id("desktop")
    _ensure_execution_run(
        run_id=run_id,
        source="desktop",
        tool_name="bridge_desktop_observe",
        meta={
            "window_name": window_name,
            "include_screenshot": include_screenshot,
            "include_windows": include_windows,
            "include_clipboard": include_clipboard,
            "ocr": ocr,
        },
    )

    try:
        focused_window = await _desktop_get_focused_window_state()

        screenshot: dict[str, Any] | None = None
        screenshot_path = ""
        if include_screenshot:
            screenshot = json.loads(await bridge_desktop_screenshot(window_name=window_name))
            if screenshot.get("ok"):
                screenshot_path = str(screenshot.get("path", ""))

        windows: dict[str, Any] | None = None
        if include_windows:
            windows = json.loads(await bridge_desktop_window_list(name_filter=window_name))

        clipboard: dict[str, Any] | None = None
        if include_clipboard:
            clipboard = json.loads(await bridge_desktop_clipboard_read())

        ocr_payload: dict[str, Any] = {"available": _desktop_ocr_available(), "text": "", "engine": None}
        if ocr and screenshot_path:
            ocr_payload = await _desktop_ocr_image(screenshot_path)

        raw_payload = {
            "status": "ok",
            "focused_window": focused_window,
            "screenshot": screenshot,
            "windows": windows,
            "clipboard": clipboard,
            "ocr": ocr_payload,
        }
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_observe",
            run_id=run_id,
            raw_payload=raw_payload,
            input_summary={
                "window_name": window_name or None,
                "include_screenshot": include_screenshot,
                "include_windows": include_windows,
                "include_clipboard": include_clipboard,
                "ocr": ocr,
            },
        )
    except Exception as exc:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_observe",
            run_id=run_id,
            raw_payload={"status": "error", "error": str(exc)},
            input_summary={
                "window_name": window_name or None,
                "include_screenshot": include_screenshot,
                "include_windows": include_windows,
                "include_clipboard": include_clipboard,
                "ocr": ocr,
            },
        )


@mcp.tool(
    name="bridge_desktop_verify",
    description=(
        "Verify desktop postconditions such as focused-window state, window names, clipboard text, "
        "screenshot creation, and OCR text. Returns structured pass/fail details."
    ),
)
async def bridge_desktop_verify(
    window_name: str = "",
    expect_focused_window: str = "",
    expect_focused_name_contains: str = "",
    expect_window_name_contains: str = "",
    expect_clipboard_contains: str = "",
    expect_ocr_contains: str = "",
    require_screenshot: bool = False,
) -> str:
    if _agent_id is None:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_verify",
            raw_payload={"status": "error", "error": "Not registered. Call bridge_register first."},
        )

    expect_focused_window = (expect_focused_window or "").strip().lower()
    if expect_focused_window not in {"", "present", "absent"}:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_verify",
            raw_payload={
                "status": "error",
                "error": "expect_focused_window must be '', 'present', or 'absent'",
            },
            input_summary={"expect_focused_window": expect_focused_window or None},
        )

    if not _desktop_has_verify_conditions(
        expect_focused_window=expect_focused_window,
        expect_focused_name_contains=expect_focused_name_contains,
        expect_window_name_contains=expect_window_name_contains,
        expect_clipboard_contains=expect_clipboard_contains,
        expect_ocr_contains=expect_ocr_contains,
        require_screenshot=require_screenshot,
    ):
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_verify",
            raw_payload={"status": "error", "error": "at least one verify condition is required"},
        )

    observation = json.loads(
        await bridge_desktop_observe(
            window_name=window_name,
            include_screenshot=require_screenshot or bool(expect_ocr_contains),
            include_windows=bool(expect_window_name_contains),
            include_clipboard=bool(expect_clipboard_contains),
            ocr=bool(expect_ocr_contains),
        )
    )
    run_id = str(observation.get("run_id", "")) or _default_run_id("desktop")
    if not observation.get("ok"):
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_verify",
            run_id=run_id,
            raw_payload={"status": "error", "error": "desktop observe failed", "observation": observation},
            input_summary={
                "window_name": window_name or None,
                "expect_focused_window": expect_focused_window or None,
                "expect_focused_name_contains": expect_focused_name_contains or None,
                "expect_window_name_contains": expect_window_name_contains or None,
                "expect_clipboard_contains": expect_clipboard_contains or None,
                "expect_ocr_contains": expect_ocr_contains or None,
                "require_screenshot": require_screenshot,
            },
        )

    focused_window = dict(observation.get("focused_window") or {})
    screenshot = dict(observation.get("screenshot") or {})
    windows = dict(observation.get("windows") or {})
    clipboard = dict(observation.get("clipboard") or {})
    ocr_payload = dict(observation.get("ocr") or {})

    focused_available = bool(focused_window.get("available"))
    if expect_focused_window == "present":
        focused_window_ok = focused_available
    elif expect_focused_window == "absent":
        focused_window_ok = not focused_available
    else:
        focused_window_ok = True

    focused_name = str(focused_window.get("name", ""))
    focused_name_ok = True
    if expect_focused_name_contains:
        focused_name_ok = focused_available and _desktop_text_contains(focused_name, expect_focused_name_contains)

    window_names = [
        str(window.get("name", ""))
        for window in windows.get("windows", [])
        if isinstance(window, dict) and window.get("name")
    ]
    window_name_ok = True
    if expect_window_name_contains:
        window_name_ok = any(_desktop_text_contains(name, expect_window_name_contains) for name in window_names)

    clipboard_content = str(clipboard.get("content", ""))
    clipboard_ok = True
    if expect_clipboard_contains:
        clipboard_ok = _desktop_text_contains(clipboard_content, expect_clipboard_contains)

    ocr_text = str(ocr_payload.get("text", ""))
    ocr_ok = True
    if expect_ocr_contains:
        ocr_ok = bool(ocr_payload.get("available")) and _desktop_text_contains(ocr_text, expect_ocr_contains)

    screenshot_path = str(screenshot.get("path", ""))
    screenshot_ok = True
    if require_screenshot:
        screenshot_ok = bool(screenshot.get("ok")) and bool(screenshot_path) and os.path.isfile(screenshot_path)

    matches = {
        "focused_window": focused_window_ok,
        "focused_name_contains": focused_name_ok,
        "window_name_contains": window_name_ok,
        "clipboard_contains": clipboard_ok,
        "ocr_contains": ocr_ok,
        "screenshot_created": screenshot_ok,
    }
    verified = all(matches.values())
    status = "ok" if verified else "mismatch"

    return _structured_action_json(
        source="desktop",
        tool_name="bridge_desktop_verify",
        run_id=run_id,
        raw_payload={
            "status": status,
            "verified": verified,
            "matches": matches,
            "focused_window": focused_window,
            "window_names": window_names[:20],
            "clipboard_preview": clipboard_content[:240],
            "ocr_preview": ocr_text[:240],
            "screenshot": screenshot if require_screenshot or screenshot else None,
            "observation": observation,
        },
        input_summary={
            "window_name": window_name or None,
            "expect_focused_window": expect_focused_window or None,
            "expect_focused_name_contains": expect_focused_name_contains or None,
            "expect_window_name_contains": expect_window_name_contains or None,
            "expect_clipboard_contains": expect_clipboard_contains or None,
            "expect_ocr_contains": expect_ocr_contains or None,
            "require_screenshot": require_screenshot,
        },
    )


@mcp.tool(
    name="bridge_desktop_screenshot",
    description=(
        "Take a screenshot of the desktop or a specific window. "
        "Returns the file path to the saved PNG screenshot. "
        "Optional window_name to target a specific window (uses xdotool search)."
    ),
)
async def bridge_desktop_screenshot(
    window_name: str = "",
) -> str:
    """Take a desktop screenshot via gnome-screenshot or import."""
    if _agent_id is None:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_screenshot",
            raw_payload={"status": "error", "error": "Not registered. Call bridge_register first."},
        )

    os.makedirs(_DESKTOP_SCREENSHOT_DIR, exist_ok=True)
    ts = int(time.time() * 1000)
    out_path = os.path.join(_DESKTOP_SCREENSHOT_DIR, f"desktop_{_agent_id}_{ts}.png")
    run_id = _default_run_id("desktop")
    _ensure_execution_run(
        run_id=run_id,
        source="desktop",
        tool_name="bridge_desktop_screenshot",
        meta={"window_name": window_name},
    )

    try:
        if window_name:
            # Find window ID by name
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "search", "--name", window_name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            wids = stdout.decode().strip().split("\n")
            if not wids or not wids[0]:
                return _structured_action_json(
                    source="desktop",
                    tool_name="bridge_desktop_screenshot",
                    run_id=run_id,
                    raw_payload={"status": "error", "error": f"Window not found: {window_name}"},
                    input_summary={"window_name": window_name},
                )
            wid = wids[0]
            # Use import (ImageMagick) to capture specific window
            proc = await asyncio.create_subprocess_exec(
                "import", "-window", wid, out_path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                # Fallback to gnome-screenshot
                proc2 = await asyncio.create_subprocess_exec(
                    "gnome-screenshot", "-w", "-f", out_path,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
                )
                await asyncio.wait_for(proc2.communicate(), timeout=15)
        else:
            # Full desktop screenshot
            proc = await asyncio.create_subprocess_exec(
                "gnome-screenshot", "-f", out_path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                return _structured_action_json(
                    source="desktop",
                    tool_name="bridge_desktop_screenshot",
                    run_id=run_id,
                    raw_payload={"status": "error", "error": f"gnome-screenshot failed: {stderr.decode()[:200]}"},
                    input_summary={"window_name": window_name},
                )

        if not os.path.isfile(out_path):
            return _structured_action_json(
                source="desktop",
                tool_name="bridge_desktop_screenshot",
                run_id=run_id,
                raw_payload={"status": "error", "error": "Screenshot file was not created"},
                input_summary={"window_name": window_name},
            )

        file_size = os.path.getsize(out_path)
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_screenshot",
            run_id=run_id,
            raw_payload={
                "status": "ok",
                "ok": True,
                "path": out_path,
                "size_bytes": file_size,
            },
            input_summary={"window_name": window_name},
        )
    except asyncio.TimeoutError:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_screenshot",
            run_id=run_id,
            raw_payload={"status": "error", "error": "Screenshot timed out after 15s"},
            input_summary={"window_name": window_name},
        )
    except Exception as exc:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_screenshot",
            run_id=run_id,
            raw_payload={"status": "error", "error": f"Screenshot failed: {exc}"},
            input_summary={"window_name": window_name},
        )


@mcp.tool(
    name="bridge_desktop_screenshot_stream",
    description=(
        "Take a series of desktop screenshots at regular intervals. "
        "Returns a list of screenshot file paths with timestamps. "
        "Useful for vision-AI loops that need continuous screen monitoring. "
        "interval_ms: time between screenshots (min 200ms). "
        "duration_s: total capture duration (max 60s). "
        "max_frames: hard cap on number of screenshots (max 120)."
    ),
)
async def bridge_desktop_screenshot_stream(
    interval_ms: int = 500,
    duration_s: float = 10.0,
    max_frames: int = 30,
    window_name: str = "",
) -> str:
    """Stream desktop screenshots at regular intervals."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    # Clamp parameters
    interval_ms = max(200, min(interval_ms, 5000))
    duration_s = min(max(0.5, duration_s), 60.0)
    max_frames = min(max(1, max_frames), 120)

    os.makedirs(_DESKTOP_SCREENSHOT_DIR, exist_ok=True)
    session_id = f"stream_{_agent_id}_{int(time.time() * 1000)}"
    session_dir = os.path.join(_DESKTOP_SCREENSHOT_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    # Resolve window ID once if targeting specific window
    window_id: str | None = None
    if window_name:
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "search", "--name", window_name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            wids = stdout.decode().strip().split("\n")
            if wids and wids[0]:
                window_id = wids[0]
            else:
                return json.dumps({"error": f"Window not found: {window_name}"})
        except (asyncio.TimeoutError, Exception) as exc:
            return json.dumps({"error": f"Window search failed: {exc}"})

    frames: list[dict[str, object]] = []
    interval_s = interval_ms / 1000.0
    start_time = time.monotonic()
    frame_idx = 0

    while frame_idx < max_frames:
        elapsed = time.monotonic() - start_time
        if elapsed >= duration_s:
            break

        frame_path = os.path.join(session_dir, f"frame_{frame_idx:04d}.png")
        capture_ts = time.time()

        try:
            if window_id:
                proc = await asyncio.create_subprocess_exec(
                    "import", "-window", window_id, frame_path,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "gnome-screenshot", "-f", frame_path,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
                )
            await asyncio.wait_for(proc.communicate(), timeout=10)

            if os.path.isfile(frame_path):
                frames.append({
                    "index": frame_idx,
                    "path": frame_path,
                    "timestamp": capture_ts,
                    "size_bytes": os.path.getsize(frame_path),
                })
        except (asyncio.TimeoutError, Exception):
            pass  # Skip failed frame, continue capturing

        frame_idx += 1

        # Wait for next interval (subtract capture time)
        capture_duration = time.monotonic() - start_time - elapsed
        sleep_time = interval_s - capture_duration
        if sleep_time > 0 and (time.monotonic() - start_time + sleep_time) < duration_s:
            await asyncio.sleep(sleep_time)

    return json.dumps({
        "ok": True,
        "session_id": session_id,
        "session_dir": session_dir,
        "frames_captured": len(frames),
        "frames_requested": max_frames,
        "duration_actual_s": round(time.monotonic() - start_time, 2),
        "interval_ms": interval_ms,
        "frames": frames,
    })


# ---------------------------------------------------------------------------
# Bezier mouse-movement helpers (human-like cursor motion via xdotool)
# ---------------------------------------------------------------------------

_DESKTOP_DISPLAY_ENV = lambda: {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}


def _desktop_bezier_curve(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int = 25,
) -> list[tuple[int, int]]:
    """Return a list of (x, y) points along a cubic Bezier with random control
    points and micro-tremor, producing a human-like arc between *start* and *end*."""
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    dist = math.sqrt(dx ** 2 + dy ** 2)
    spread = max(50, dist * 0.3)

    # Two random control points offset from the straight line
    cp1 = (
        sx + dx * 0.25 + random.gauss(0, spread * 0.3),
        sy + dy * 0.25 + random.gauss(0, spread * 0.3),
    )
    cp2 = (
        sx + dx * 0.75 + random.gauss(0, spread * 0.3),
        sy + dy * 0.75 + random.gauss(0, spread * 0.3),
    )

    points: list[tuple[int, int]] = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u ** 3 * sx + 3 * u ** 2 * t * cp1[0] + 3 * u * t ** 2 * cp2[0] + t ** 3 * ex
        y = u ** 3 * sy + 3 * u ** 2 * t * cp1[1] + 3 * u * t ** 2 * cp2[1] + t ** 3 * ey
        # Gaussian micro-tremor
        x += random.gauss(0, 1.5)
        y += random.gauss(0, 1.5)
        points.append((int(x), int(y)))

    # Ensure the last point is exactly the target
    points[-1] = (ex, ey)
    return points


async def _desktop_get_mouse_position() -> tuple[int, int]:
    """Return current (x, y) mouse position via xdotool getmouselocation."""
    proc = await asyncio.create_subprocess_exec(
        "xdotool", "getmouselocation",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_DESKTOP_DISPLAY_ENV(),
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    # Output format: "x:123 y:456 screen:0 window:789"
    parts = stdout.decode().strip().split()
    x = int(parts[0].split(":")[1])
    y = int(parts[1].split(":")[1])
    return (x, y)


async def _desktop_human_mouse_move(x: int, y: int) -> None:
    """Move the mouse from its current position to (x, y) along a Bezier curve,
    stepping through intermediate points with short random delays."""
    current = await _desktop_get_mouse_position()
    points = _desktop_bezier_curve(current, (x, y))

    env = _DESKTOP_DISPLAY_ENV()
    for px, py in points:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "mousemove", "--sync", str(px), str(py),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        await asyncio.sleep(random.uniform(0.005, 0.02))


# ---------------------------------------------------------------------------
# Desktop tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_desktop_type",
    description=(
        "Type text into the currently focused window using xdotool. "
        "Characters are typed with human-like Gaussian timing variation."
    ),
)
async def bridge_desktop_type(text: str, delay_ms: int = 12) -> str:
    """Type text via xdotool with human-like keystroke timing."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not text:
        return json.dumps({"error": "text is required"})
    if len(text) > 5000:
        return json.dumps({"error": "text too long (max 5000 chars)"})

    try:
        env = _DESKTOP_DISPLAY_ENV()
        for ch in text:
            # Use xdotool key for each character for precise timing control
            # Map special chars to xdotool key names
            key_name: str
            if ch == " ":
                key_name = "space"
            elif ch == "\n":
                key_name = "Return"
            elif ch == "\t":
                key_name = "Tab"
            else:
                # xdotool type for regular characters (handles shift etc.)
                proc = await asyncio.create_subprocess_exec(
                    "xdotool", "type", "--clearmodifiers", "--", ch,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                await asyncio.wait_for(proc.communicate(), timeout=5)
                # Gaussian delay between keystrokes
                delay = max(0.01, random.gauss(0.075, 0.02))
                # 5% chance of a "thinking pause" (200-600ms)
                if random.random() < 0.05:
                    delay += random.uniform(0.2, 0.6)
                await asyncio.sleep(delay)
                continue

            # Send special key
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", key_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            delay = max(0.01, random.gauss(0.075, 0.02))
            if random.random() < 0.05:
                delay += random.uniform(0.2, 0.6)
            await asyncio.sleep(delay)

        return json.dumps({"ok": True, "typed_chars": len(text)})
    except asyncio.TimeoutError:
        return json.dumps({"error": "xdotool type timed out after 30s"})
    except Exception as exc:
        return json.dumps({"error": f"xdotool type failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_key",
    description=(
        "Send a keyboard shortcut/key combination to the focused window via xdotool. "
        "Examples: 'ctrl+s', 'alt+F4', 'Return', 'ctrl+shift+t', 'Escape'. "
        "Uses xdotool key syntax (modifier+key)."
    ),
)
async def bridge_desktop_key(combo: str) -> str:
    """Send a key combination via xdotool."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not combo:
        return json.dumps({"error": "combo is required"})
    # Validate: only allow safe characters (alphanumeric, +, _, -)
    if not re.match(r'^[a-zA-Z0-9+_\- ]+$', combo):
        return json.dumps({"error": f"Invalid key combo: {combo}"})

    try:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "key", "--", combo,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return json.dumps({"error": f"xdotool key failed: {stderr.decode()[:200]}"})
        return json.dumps({"ok": True, "combo": combo})
    except asyncio.TimeoutError:
        return json.dumps({"error": "xdotool key timed out after 10s"})
    except Exception as exc:
        return json.dumps({"error": f"xdotool key failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_click",
    description=(
        "Click at specific screen coordinates (x, y) using xdotool. "
        "Optional button parameter: 1=left (default), 2=middle, 3=right."
    ),
)
async def bridge_desktop_click(x: int, y: int, button: int = 1) -> str:
    """Click at screen coordinates via xdotool."""
    if _agent_id is None:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_click",
            raw_payload={"status": "error", "error": "Not registered. Call bridge_register first."},
        )
    run_id = _default_run_id("desktop")
    _ensure_execution_run(
        run_id=run_id,
        source="desktop",
        tool_name="bridge_desktop_click",
        meta={"x": x, "y": y, "button": button},
    )
    if button not in (1, 2, 3):
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_click",
            run_id=run_id,
            raw_payload={"status": "error", "error": "button must be 1 (left), 2 (middle), or 3 (right)"},
            input_summary={"x": x, "y": y, "button": button},
        )
    if x < 0 or y < 0 or x > 10000 or y > 10000:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_click",
            run_id=run_id,
            raw_payload={"status": "error", "error": f"Coordinates out of range: ({x}, {y})"},
            input_summary={"x": x, "y": y, "button": button},
        )

    try:
        # Human-like Bezier mouse movement, then click
        await _desktop_human_mouse_move(x, y)
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "click", str(button),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=_DESKTOP_DISPLAY_ENV(),
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return _structured_action_json(
                source="desktop",
                tool_name="bridge_desktop_click",
                run_id=run_id,
                raw_payload={"status": "error", "error": f"xdotool click failed: {stderr.decode()[:200]}"},
                input_summary={"x": x, "y": y, "button": button},
            )
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_click",
            run_id=run_id,
            raw_payload={"status": "ok", "ok": True, "x": x, "y": y, "button": button},
            input_summary={"x": x, "y": y, "button": button},
        )
    except asyncio.TimeoutError:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_click",
            run_id=run_id,
            raw_payload={"status": "error", "error": "xdotool click timed out after 10s"},
            input_summary={"x": x, "y": y, "button": button},
        )
    except Exception as exc:
        return _structured_action_json(
            source="desktop",
            tool_name="bridge_desktop_click",
            run_id=run_id,
            raw_payload={"status": "error", "error": f"xdotool click failed: {exc}"},
            input_summary={"x": x, "y": y, "button": button},
        )


@mcp.tool(
    name="bridge_desktop_scroll",
    description=(
        "Scroll at current mouse position or specific coordinates. "
        "direction: 'up' or 'down'. clicks: number of scroll steps (1-20). "
        "Optional x, y to move mouse first."
    ),
)
async def bridge_desktop_scroll(
    direction: str = "down", clicks: int = 3, x: int = -1, y: int = -1,
) -> str:
    """Scroll via xdotool (button 4=up, 5=down)."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if direction not in ("up", "down"):
        return json.dumps({"error": "direction must be 'up' or 'down'"})
    clicks = max(1, min(clicks, 20))
    button = "4" if direction == "up" else "5"

    try:
        cmds: list[list[str]] = []
        if x >= 0 and y >= 0:
            cmds.append(["xdotool", "mousemove", str(x), str(y)])
        cmds.append(["xdotool", "click", "--repeat", str(clicks), "--delay", "50", button])

        for cmd in cmds:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                return json.dumps({"error": f"xdotool scroll failed: {stderr.decode()[:200]}"})
        return json.dumps({"ok": True, "direction": direction, "clicks": clicks})
    except asyncio.TimeoutError:
        return json.dumps({"error": "xdotool scroll timed out after 10s"})
    except Exception as exc:
        return json.dumps({"error": f"xdotool scroll failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_hover",
    description=(
        "Move mouse to specific screen coordinates (x, y) WITHOUT clicking. "
        "Useful for triggering hover menus, tooltips, or highlighting elements."
    ),
)
async def bridge_desktop_hover(x: int, y: int) -> str:
    """Move mouse to coordinates via human-like Bezier curve (no click)."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if x < 0 or y < 0 or x > 10000 or y > 10000:
        return json.dumps({"error": f"Coordinates out of range: ({x}, {y})"})

    try:
        await _desktop_human_mouse_move(x, y)
        return json.dumps({"ok": True, "x": x, "y": y})
    except asyncio.TimeoutError:
        return json.dumps({"error": "xdotool mousemove timed out after 10s"})
    except Exception as exc:
        return json.dumps({"error": f"xdotool mousemove failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_clipboard_read",
    description="Read the current clipboard content. Returns text from system clipboard.",
)
async def bridge_desktop_clipboard_read() -> str:
    """Read clipboard via xclip."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        proc = await asyncio.create_subprocess_exec(
            "xclip", "-selection", "clipboard", "-o",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return json.dumps({"error": f"xclip read failed: {stderr.decode()[:200]}"})
        text = stdout.decode("utf-8", errors="replace")
        if len(text) > 50000:
            text = text[:50000] + "... (truncated)"
        return json.dumps({"ok": True, "content": text, "length": len(text)})
    except asyncio.TimeoutError:
        return json.dumps({"error": "xclip read timed out after 10s"})
    except Exception as exc:
        return json.dumps({"error": f"clipboard read failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_clipboard_write",
    description="Write text to the system clipboard. Makes it available for Ctrl+V paste.",
)
async def bridge_desktop_clipboard_write(text: str) -> str:
    """Write to clipboard via xclip."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not text:
        return json.dumps({"error": "text is required"})
    if len(text) > 100000:
        return json.dumps({"error": "text too long (max 100000 chars)"})

    try:
        proc = await asyncio.create_subprocess_exec(
            "xclip", "-selection", "clipboard",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(input=text.encode("utf-8")), timeout=10,
        )
        if proc.returncode != 0:
            return json.dumps({"error": f"xclip write failed: {stderr.decode()[:200]}"})
        return json.dumps({"ok": True, "written_chars": len(text)})
    except asyncio.TimeoutError:
        return json.dumps({"error": "xclip write timed out after 10s"})
    except Exception as exc:
        return json.dumps({"error": f"clipboard write failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_wait",
    description=(
        "Wait until a window with given name appears on screen. "
        "Polls xdotool search every 500ms until found or timeout. "
        "Returns the window ID when found."
    ),
)
async def bridge_desktop_wait(window_name: str, timeout: int = 30) -> str:
    """Wait for a window to appear via xdotool search polling."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not window_name:
        return json.dumps({"error": "window_name is required"})
    timeout = max(1, min(timeout, 120))

    start = time.time()
    while time.time() - start < timeout:
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "search", "--name", window_name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            wids = stdout.decode().strip().split("\n")
            if wids and wids[0]:
                return json.dumps({
                    "ok": True,
                    "window_id": wids[0],
                    "window_name": window_name,
                    "waited_seconds": round(time.time() - start, 1),
                })
        except (asyncio.TimeoutError, Exception):
            pass
        await asyncio.sleep(0.5)

    return json.dumps({
        "error": f"Window '{window_name}' not found within {timeout}s",
        "waited_seconds": timeout,
    })


@mcp.tool(
    name="bridge_desktop_double_click",
    description=(
        "Double-click at specific screen coordinates (x, y) using xdotool. "
        "Useful for opening files, selecting words, or activating UI elements."
    ),
)
async def bridge_desktop_double_click(x: int, y: int, button: int = 1) -> str:
    """Double-click at screen coordinates via human-like Bezier move + xdotool."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if button not in (1, 2, 3):
        return json.dumps({"error": "button must be 1 (left), 2 (middle), or 3 (right)"})
    if x < 0 or y < 0 or x > 10000 or y > 10000:
        return json.dumps({"error": f"Coordinates out of range: ({x}, {y})"})

    try:
        await _desktop_human_mouse_move(x, y)
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "click", "--repeat", "2", "--delay", "50", str(button),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=_DESKTOP_DISPLAY_ENV(),
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return json.dumps({"error": f"xdotool double-click failed: {stderr.decode()[:200]}"})
        return json.dumps({"ok": True, "x": x, "y": y, "button": button, "clicks": 2})
    except asyncio.TimeoutError:
        return json.dumps({"error": "xdotool double-click timed out after 10s"})
    except Exception as exc:
        return json.dumps({"error": f"xdotool double-click failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_drag",
    description=(
        "Drag from one screen position to another. "
        "Simulates mouse-down at (start_x, start_y), move to (end_x, end_y), mouse-up. "
        "Useful for moving files, resizing windows, selecting text ranges."
    ),
)
async def bridge_desktop_drag(
    start_x: int, start_y: int, end_x: int, end_y: int, button: int = 1,
) -> str:
    """Drag from start to end coordinates via xdotool."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if button not in (1, 2, 3):
        return json.dumps({"error": "button must be 1 (left), 2 (middle), or 3 (right)"})
    for name, val in [("start_x", start_x), ("start_y", start_y), ("end_x", end_x), ("end_y", end_y)]:
        if val < 0 or val > 10000:
            return json.dumps({"error": f"{name} out of range: {val}"})

    env = _DESKTOP_DISPLAY_ENV()
    try:
        # Bezier move to start position
        await _desktop_human_mouse_move(start_x, start_y)

        # Mouse down
        p2 = await asyncio.create_subprocess_exec(
            "xdotool", "mousedown", str(button),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        await asyncio.wait_for(p2.communicate(), timeout=5)

        # Bezier move to end position (with button held)
        await asyncio.sleep(0.05)
        drag_points = _desktop_bezier_curve((start_x, start_y), (end_x, end_y))
        for px, py in drag_points:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "mousemove", "--sync", str(px), str(py),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            await asyncio.sleep(random.uniform(0.005, 0.02))

        # Mouse up
        p4 = await asyncio.create_subprocess_exec(
            "xdotool", "mouseup", str(button),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr = await asyncio.wait_for(p4.communicate(), timeout=5)
        if p4.returncode != 0:
            return json.dumps({"error": f"xdotool drag failed at mouseup: {stderr.decode()[:200]}"})

        return json.dumps({
            "ok": True,
            "from": {"x": start_x, "y": start_y},
            "to": {"x": end_x, "y": end_y},
            "button": button,
        })
    except asyncio.TimeoutError:
        # Ensure mouse is released on timeout
        try:
            p_up = await asyncio.create_subprocess_exec(
                "xdotool", "mouseup", str(button),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            await asyncio.wait_for(p_up.communicate(), timeout=2)
        except Exception:
            pass
        return json.dumps({"error": "xdotool drag timed out"})
    except Exception as exc:
        # Ensure mouse is released on error
        try:
            p_up = await asyncio.create_subprocess_exec(
                "xdotool", "mouseup", str(button),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            await asyncio.wait_for(p_up.communicate(), timeout=2)
        except Exception:
            pass
        return json.dumps({"error": f"xdotool drag failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_window_list",
    description=(
        "List all open windows with their IDs, names, and geometry. "
        "Returns window_id, name, x, y, width, height for each window."
    ),
)
async def bridge_desktop_window_list(name_filter: str = "") -> str:
    """List open windows via xdotool search."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})

    try:
        search_args = ["xdotool", "search", "--name", name_filter or ""]
        proc = await asyncio.create_subprocess_exec(
            *search_args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        wids = [w.strip() for w in stdout.decode().strip().split("\n") if w.strip()]

        windows = []
        for wid in wids[:50]:  # Limit to 50 windows
            try:
                # Get window name
                p_name = await asyncio.create_subprocess_exec(
                    "xdotool", "getwindowname", wid,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
                )
                name_out, _ = await asyncio.wait_for(p_name.communicate(), timeout=3)
                win_name = name_out.decode().strip() if p_name.returncode == 0 else ""

                # Get geometry
                p_geo = await asyncio.create_subprocess_exec(
                    "xdotool", "getwindowgeometry", wid,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
                )
                geo_out, _ = await asyncio.wait_for(p_geo.communicate(), timeout=3)
                geo_text = geo_out.decode().strip() if p_geo.returncode == 0 else ""

                # Parse geometry: "Window 12345\n  Position: 100,200 (screen: 0)\n  Geometry: 800x600"
                x, y, w, h = 0, 0, 0, 0
                for line in geo_text.split("\n"):
                    line = line.strip()
                    if line.startswith("Position:"):
                        pos = line.split(":")[1].strip().split("(")[0].strip()
                        parts = pos.split(",")
                        if len(parts) == 2:
                            x, y = int(parts[0]), int(parts[1])
                    elif line.startswith("Geometry:"):
                        size = line.split(":")[1].strip()
                        parts = size.split("x")
                        if len(parts) == 2:
                            w, h = int(parts[0]), int(parts[1])

                if win_name:  # Skip unnamed windows
                    windows.append({
                        "window_id": wid, "name": win_name,
                        "x": x, "y": y, "width": w, "height": h,
                    })
            except (asyncio.TimeoutError, Exception):
                continue

        return json.dumps({"ok": True, "count": len(windows), "windows": windows})
    except asyncio.TimeoutError:
        return json.dumps({"error": "window list timed out"})
    except Exception as exc:
        return json.dumps({"error": f"window list failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_window_focus",
    description=(
        "Focus/activate a window by its window ID (from bridge_desktop_window_list) "
        "or by name search. Brings the window to the foreground."
    ),
)
async def bridge_desktop_window_focus(window_id: str = "", window_name: str = "") -> str:
    """Focus a window via xdotool windowactivate."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not window_id and not window_name:
        return json.dumps({"error": "Either window_id or window_name is required"})

    try:
        wid = window_id.strip()
        if not wid and window_name:
            # Search by name
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "search", "--name", window_name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            wids = stdout.decode().strip().split("\n")
            if not wids or not wids[0]:
                return json.dumps({"error": f"Window not found: {window_name}"})
            wid = wids[0]

        proc = await asyncio.create_subprocess_exec(
            "xdotool", "windowactivate", "--sync", wid,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return json.dumps({"error": f"windowactivate failed: {stderr.decode()[:200]}"})
        return json.dumps({"ok": True, "window_id": wid, "action": "focused"})
    except asyncio.TimeoutError:
        return json.dumps({"error": "window focus timed out"})
    except Exception as exc:
        return json.dumps({"error": f"window focus failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_window_resize",
    description=(
        "Resize and/or move a window. Specify window_id or window_name. "
        "width/height set the new size. x/y set the new position (optional)."
    ),
)
async def bridge_desktop_window_resize(
    width: int = 0, height: int = 0, x: int = -1, y: int = -1,
    window_id: str = "", window_name: str = "",
) -> str:
    """Resize/move a window via xdotool."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not window_id and not window_name:
        return json.dumps({"error": "Either window_id or window_name is required"})
    if width <= 0 and height <= 0 and x < 0 and y < 0:
        return json.dumps({"error": "At least width/height or x/y must be specified"})

    try:
        wid = window_id.strip()
        if not wid and window_name:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "search", "--name", window_name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            wids = stdout.decode().strip().split("\n")
            if not wids or not wids[0]:
                return json.dumps({"error": f"Window not found: {window_name}"})
            wid = wids[0]

        actions_done = []

        # Resize
        if width > 0 and height > 0:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "windowsize", wid, str(width), str(height),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                return json.dumps({"error": f"windowsize failed: {stderr.decode()[:200]}"})
            actions_done.append(f"resized to {width}x{height}")

        # Move
        if x >= 0 and y >= 0:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "windowmove", wid, str(x), str(y),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                return json.dumps({"error": f"windowmove failed: {stderr.decode()[:200]}"})
            actions_done.append(f"moved to ({x}, {y})")

        return json.dumps({"ok": True, "window_id": wid, "actions": actions_done})
    except asyncio.TimeoutError:
        return json.dumps({"error": "window resize/move timed out"})
    except Exception as exc:
        return json.dumps({"error": f"window resize/move failed: {exc}"})


@mcp.tool(
    name="bridge_desktop_window_minimize",
    description="Minimize a window by ID or name.",
)
async def bridge_desktop_window_minimize(window_id: str = "", window_name: str = "") -> str:
    """Minimize a window via xdotool windowminimize."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not window_id and not window_name:
        return json.dumps({"error": "Either window_id or window_name is required"})

    try:
        wid = window_id.strip()
        if not wid and window_name:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "search", "--name", window_name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            wids = stdout.decode().strip().split("\n")
            if not wids or not wids[0]:
                return json.dumps({"error": f"Window not found: {window_name}"})
            wid = wids[0]

        proc = await asyncio.create_subprocess_exec(
            "xdotool", "windowminimize", wid,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            return json.dumps({"error": f"windowminimize failed: {stderr.decode()[:200]}"})
        return json.dumps({"ok": True, "window_id": wid, "action": "minimized"})
    except asyncio.TimeoutError:
        return json.dumps({"error": "window minimize timed out"})
    except Exception as exc:
        return json.dumps({"error": f"window minimize failed: {exc}"})


# ---------------------------------------------------------------------------
# V4 Knowledge Engine — Obsidian-inspired Knowledge Backend
# ---------------------------------------------------------------------------

try:
    from knowledge_engine import (
        read_note as _ke_read,
        write_note as _ke_write,
        delete_note as _ke_delete,
        list_notes as _ke_list,
        search_notes as _ke_search,
        manage_frontmatter as _ke_frontmatter,
        search_replace as _ke_search_replace,
        init_vault as _ke_init_vault,
        init_agent_vault as _ke_init_agent_vault,
        init_user_vault as _ke_init_user_vault,
        init_project_vault as _ke_init_project_vault,
        init_team_vault as _ke_init_team_vault,
        vault_info as _ke_vault_info,
    )
    _KE_AVAILABLE = True
except ImportError:
    _KE_AVAILABLE = False
    log.warning("knowledge_engine not available — knowledge tools disabled")


def _ke_guard() -> str | None:
    if not _KE_AVAILABLE:
        return json.dumps({"error": "Knowledge engine not available"})
    return None


@mcp.tool(
    name="bridge_knowledge_read",
    description=(
        "Read a note from the knowledge vault. "
        "Path is relative to vault root (e.g. 'Agents/atlas/SOUL', 'Shared/architecture'). "
        ".md extension added automatically. Returns frontmatter + body."
    ),
)
async def bridge_knowledge_read(note_path: str) -> str:
    """Read a knowledge note."""
    if err := _ke_guard():
        return err
    return json.dumps(_ke_read(note_path))


@mcp.tool(
    name="bridge_knowledge_write",
    description=(
        "Write or update a note in the knowledge vault. "
        "mode: 'overwrite' (default), 'append', 'prepend'. "
        "frontmatter is optional JSON object (e.g. {\"tags\": [\"backend\"], \"status\": \"open\"}). "
        "Path is relative to vault root."
    ),
)
async def bridge_knowledge_write(
    note_path: str,
    body: str,
    frontmatter: str = "",
    mode: str = "overwrite",
) -> str:
    """Write a knowledge note."""
    if err := _ke_guard():
        return err
    fm: dict[str, Any] = {}
    if frontmatter:
        try:
            fm = json.loads(frontmatter)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid frontmatter JSON: {exc}"})
    return json.dumps(_ke_write(note_path, body, fm or None, mode))


@mcp.tool(
    name="bridge_knowledge_delete",
    description="Delete a note from the knowledge vault. Path is relative to vault root.",
)
async def bridge_knowledge_delete(note_path: str) -> str:
    """Delete a knowledge note."""
    if err := _ke_guard():
        return err
    return json.dumps(_ke_delete(note_path))


@mcp.tool(
    name="bridge_knowledge_list",
    description=(
        "List notes in the knowledge vault. "
        "Optional directory filter (e.g. 'Agents/atlas', 'Tasks'). "
        "Returns paths and frontmatter for each note."
    ),
)
async def bridge_knowledge_list(
    directory: str = "",
    pattern: str = "*.md",
    recursive: bool = True,
) -> str:
    """List knowledge notes."""
    if err := _ke_guard():
        return err
    return json.dumps(_ke_list(directory, pattern, recursive))


@mcp.tool(
    name="bridge_knowledge_search",
    description=(
        "Full-text search across knowledge vault notes. "
        "Supports regex patterns. Optional frontmatter_filter as JSON "
        "(e.g. '{\"status\": \"open\", \"agent\": \"atlas\"}'). "
        "Returns matching lines and frontmatter."
    ),
)
async def bridge_knowledge_search(
    query: str = "",
    directory: str = "",
    frontmatter_filter: str = "",
) -> str:
    """Search knowledge notes."""
    if err := _ke_guard():
        return err
    fm_filter: dict[str, Any] | None = None
    if frontmatter_filter:
        try:
            fm_filter = json.loads(frontmatter_filter)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid filter JSON: {exc}"})
    return json.dumps(_ke_search(query, directory, fm_filter))


@mcp.tool(
    name="bridge_knowledge_frontmatter",
    description=(
        "Get, set, or delete frontmatter fields on a knowledge note. "
        "action: 'get', 'set', 'delete'. "
        "data: JSON object with fields to set/delete (e.g. '{\"status\": \"done\"}')."
    ),
)
async def bridge_knowledge_frontmatter(
    note_path: str,
    action: str = "get",
    data: str = "",
) -> str:
    """Manage frontmatter on a knowledge note."""
    if err := _ke_guard():
        return err
    d: dict[str, Any] | None = None
    if data:
        try:
            d = json.loads(data)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid data JSON: {exc}"})
    return json.dumps(_ke_frontmatter(note_path, action, d))


@mcp.tool(
    name="bridge_knowledge_init",
    description=(
        "Initialize the knowledge vault structure and optional scoped homes. "
        "Call without IDs to create base dirs (Agents/, Users/, Projects/, Teams/, Tasks/, Shared/). "
        "Optional IDs create scoped homes such as agent SOUL/GROW/SKILLS or USER/PROJECT/TEAM notes."
    ),
)
async def bridge_knowledge_init(
    agent_id: str = "",
    user_id: str = "",
    project_id: str = "",
    team_id: str = "",
) -> str:
    """Initialize knowledge vault."""
    if err := _ke_guard():
        return err
    result = _ke_init_vault()
    if agent_id:
        agent_result = _ke_init_agent_vault(agent_id)
        result["agent"] = agent_result
    if user_id:
        result["user"] = _ke_init_user_vault(user_id)
    if project_id:
        result["project"] = _ke_init_project_vault(project_id)
    if team_id:
        result["team"] = _ke_init_team_vault(team_id)
    return json.dumps(result)


@mcp.tool(
    name="bridge_knowledge_search_replace",
    description=(
        "Search and replace text in a knowledge note's body. "
        "regex: set to true for regex patterns. "
        "Returns replacement count."
    ),
)
async def bridge_knowledge_search_replace(
    note_path: str,
    search: str,
    replace: str,
    regex: bool = False,
) -> str:
    """Search and replace in a knowledge note."""
    if err := _ke_guard():
        return err
    return json.dumps(_ke_search_replace(note_path, search, replace, regex=regex))


@mcp.tool(
    name="bridge_knowledge_info",
    description="Get knowledge vault metadata: path, note count, total size.",
)
async def bridge_knowledge_info() -> str:
    """Get vault info."""
    if err := _ke_guard():
        return err
    return json.dumps(_ke_vault_info())


# ---------------------------------------------------------------------------
# Automation / Cron (Gap #2)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="bridge_cron_create",
    description=(
        "Create a scheduled automation (cron job). "
        "Use cron_expression for recurring schedules (e.g. '*/30 * * * *' for every 30min). "
        "action_type: 'send_message' (sends to a recipient) or 'http' (calls a URL). "
        "For send_message: provide recipient and message. "
        "For http: provide url and method."
    ),
)
async def bridge_cron_create(
    name: str,
    cron_expression: str,
    action_type: str = "send_message",
    recipient: str = "",
    message: str = "",
    url: str = "",
    method: str = "POST",
) -> str:
    """Create a cron-based automation."""
    if _agent_id is None:
        return json.dumps({"error": "not registered"})
    agent_id = _agent_id

    if action_type == "send_message":
        if not recipient or not message:
            return json.dumps({"error": "recipient and message required for send_message action"})
        action = {"type": "send_message", "from": agent_id, "to": recipient, "content": message}
    elif action_type == "http":
        if not url:
            return json.dumps({"error": "url required for http action"})
        action = {"type": "http", "url": url, "method": method}
    else:
        return json.dumps({"error": f"unknown action_type: {action_type}"})

    payload = {
        "name": name,
        "created_by": agent_id,
        "trigger": {"type": "schedule", "cron": cron_expression},
        "action": action,
        "active": True,
    }
    try:
        http = _get_http()
        r = await http.post("/automations", json=payload, headers=_auth_headers())
        return json.dumps(r.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_cron_list",
    description="List all your scheduled automations (cron jobs).",
)
async def bridge_cron_list() -> str:
    """List automations for the current agent."""
    if _agent_id is None:
        return json.dumps({"error": "not registered"})
    agent_id = _agent_id
    try:
        http = _get_http()
        r = await http.get(f"/automations?created_by={agent_id}", headers=_auth_headers())
        return json.dumps(r.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_cron_delete",
    description="Delete a scheduled automation by ID.",
)
async def bridge_cron_delete(automation_id: str) -> str:
    """Delete an automation."""
    if _agent_id is None:
        return json.dumps({"error": "not registered"})
    try:
        http = _get_http()
        r = await http.delete(f"/automations/{automation_id}", headers=_auth_headers())
        return json.dumps(r.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# P1-A: bridge_loop — /loop-style repeating prompts
# ---------------------------------------------------------------------------

import re as _re_mod


def interval_to_cron(interval: str) -> str:
    """Convert interval string (5m, 2h, 1d, 30s) to 5-field cron expression.

    Rules:
    - Seconds: rounded up to 1 minute minimum
    - Minutes: */N pattern
    - Hours: 0 */N pattern
    - Days: relative to current time (M H * * *)
    - Invalid format: raises ValueError
    """
    m = _re_mod.match(r"^(\d+)(s|m|h|d)$", interval.strip().lower())
    if not m:
        raise ValueError(f"Invalid interval format: '{interval}'. Use Ns, Nm, Nh, or Nd.")

    value = int(m.group(1))
    unit = m.group(2)

    if value <= 0:
        raise ValueError(f"Interval value must be positive, got {value}")

    if unit == "s":
        # Round up to 1 minute minimum
        minutes = max(1, (value + 59) // 60)
        return f"*/{minutes} * * * *" if minutes < 60 else "0 * * * *"
    elif unit == "m":
        if value >= 60:
            hours = value // 60
            return f"0 */{hours} * * *" if hours < 24 else "0 0 * * *"
        return f"*/{value} * * * *"
    elif unit == "h":
        if value >= 24:
            return "0 0 * * *"
        return f"0 */{value} * * *"
    elif unit == "d":
        # Relative to current time (Atlas-K2, Viktor-B2)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return f"{now.minute} {now.hour} * * *"
    else:
        raise ValueError(f"Unknown unit: {unit}")


@mcp.tool(
    name="bridge_loop",
    description=(
        "Create a repeating scheduled prompt (like Claude Code /loop). "
        "Interval formats: '5m' (5 min), '2h' (2 hours), '1d' (daily), '30s' (rounds to 1min). "
        "Default interval: 10m. The prompt runs on the assigned agent at each interval."
    ),
)
async def bridge_loop(
    prompt: str,
    interval: str = "10m",
    assigned_to: str = "",
    max_runs: int = 0,
) -> str:
    """Create a repeating automation that delivers a prompt at intervals."""
    if _agent_id is None:
        return json.dumps({"error": "not registered"})

    try:
        cron_expr = interval_to_cron(interval)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    agent_id = _agent_id
    target_agent = assigned_to or agent_id

    payload: dict = {
        "name": f"loop: {prompt[:50]}",
        "created_by": agent_id,
        "assigned_to": target_agent,
        "trigger": {"type": "schedule", "cron": cron_expr},
        "action": {
            "type": "send_message",
            "from": "system",
            "to": target_agent,
            "content": f"[SCHEDULED PROMPT] {prompt}",
        },
        "active": True,
    }
    if max_runs > 0:
        payload["options"] = {"max_runs": max_runs}

    try:
        http = _get_http()
        r = await http.post("/automations", json=payload, headers=_auth_headers())
        result = r.json()
        if result.get("ok"):
            result["cron_expression"] = cron_expr
            result["interval"] = interval
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


# ---------------------------------------------------------------------------
# Capability Library
# ---------------------------------------------------------------------------


@mcp.tool(
    name="bridge_capability_library_list",
    description=(
        "List entries from the Bridge capability library of MCPs, CLI plugins, hooks, "
        "extensions, and adapters. Supports filtering by type, vendor, CLI, source, and status."
    ),
)
async def bridge_capability_library_list(
    query: str = "",
    entry_type: str = "",
    vendor: str = "",
    cli: str = "",
    task_tag: str = "",
    source_registry: str = "",
    status: str = "",
    trust_tier: str = "",
    official_vendor: str = "",
    reproducible: str = "",
    runtime_verified: str = "",
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List capability library entries via the Bridge HTTP API."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
    }
    optional_params = {
        "q": query,
        "type": entry_type,
        "vendor": vendor,
        "cli": cli,
        "task_tag": task_tag,
        "source_registry": source_registry,
        "status": status,
        "trust_tier": trust_tier,
        "official_vendor": official_vendor,
        "reproducible": reproducible,
        "runtime_verified": runtime_verified,
    }
    for key, value in optional_params.items():
        if str(value).strip():
            params[key] = value
    try:
        response = await _bridge_get("/capability-library", params=params)
        return json.dumps(response.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_capability_library_get",
    description="Get the full metadata for one capability library entry by id.",
)
async def bridge_capability_library_get(entry_id: str) -> str:
    """Get a single capability library entry by id."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        response = await _bridge_get(f"/capability-library/{entry_id}")
        return json.dumps(response.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc), "entry_id": entry_id})


@mcp.tool(
    name="bridge_capability_library_search",
    description=(
        "Search the Bridge capability library against task text or keywords. "
        "Returns ranked matches with filter support."
    ),
)
async def bridge_capability_library_search(
    query: str,
    entry_type: str = "",
    vendor: str = "",
    cli: str = "",
    task_tag: str = "",
    source_registry: str = "",
    status: str = "",
    trust_tier: str = "",
    official_vendor: str = "",
    reproducible: str = "",
    runtime_verified: str = "",
    limit: int = 10,
    offset: int = 0,
) -> str:
    """Search the capability library."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    payload: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "offset": offset,
    }
    optional_fields = {
        "type": entry_type,
        "vendor": vendor,
        "cli": cli,
        "task_tag": task_tag,
        "source_registry": source_registry,
        "status": status,
        "trust_tier": trust_tier,
        "official_vendor": official_vendor,
        "reproducible": reproducible,
        "runtime_verified": runtime_verified,
    }
    for key, value in optional_fields.items():
        if str(value).strip():
            payload[key] = value
    try:
        response = await _bridge_post("/capability-library/search", json=payload)
        return json.dumps(response.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_capability_library_recommend",
    description=(
        "Recommend capability library entries for a task. Useful when an agent wants "
        "candidate MCPs, extensions, or hooks to pull from the library."
    ),
)
async def bridge_capability_library_recommend(
    task: str,
    engine: str = "",
    cli: str = "",
    top_k: int = 10,
    official_vendor_only: bool = False,
) -> str:
    """Recommend library entries for a task."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    payload: dict[str, Any] = {
        "task": task,
        "engine": engine,
        "cli": cli,
        "top_k": top_k,
    }
    if official_vendor_only:
        payload["official_vendor_only"] = True
    try:
        response = await _bridge_post("/capability-library/recommend", json=payload)
        return json.dumps(response.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


# ---------------------------------------------------------------------------
# Semantic Memory (G9 Integration)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="bridge_memory_search",
    description=(
        "Search your semantic memory using hybrid Vector+BM25 retrieval. "
        "Finds relevant memories even when exact keywords don't match "
        "(e.g. searching 'login' finds 'authentication'). "
        "Returns top_k results ranked by relevance score."
    ),
)
async def bridge_memory_search(
    query: str,
    top_k: int = 5,
    min_score: float = 0.3,
    scope_type: str = "",
    scope_id: str = "",
) -> str:
    """Semantic memory search for the current agent."""
    if _agent_id is None:
        return json.dumps({"error": "not registered"})
    try:
        http = _get_http()
        payload: dict[str, Any] = {"query": query, "top_k": top_k, "min_score": min_score}
        if scope_type or scope_id:
            payload["scope_type"] = scope_type
            payload["scope_id"] = scope_id
        else:
            payload["agent_id"] = _agent_id
        r = await http.post(
            "/memory/search",
            json=payload,
            headers=_auth_headers(),
        )
        return json.dumps(r.json())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="bridge_memory_index",
    description=(
        "Index text into your semantic memory for later retrieval. "
        "Use this to store important learnings, decisions, patterns, or facts "
        "that you want to find later via semantic search. "
        "Text is automatically chunked and embedded."
    ),
)
async def bridge_memory_index(
    text: str,
    source: str = "",
    chunk_size: int = 500,
    scope_type: str = "",
    scope_id: str = "",
    document_id: str = "",
) -> str:
    """Index text into semantic memory for the current agent."""
    if _agent_id is None:
        return json.dumps({"error": "not registered"})
    metadata = {"source": source, "indexed_at": datetime.now(timezone.utc).isoformat()}
    try:
        http = _get_http()
        payload: dict[str, Any] = {
            "text": text,
            "metadata": metadata,
            "chunk_size": chunk_size,
        }
        if scope_type or scope_id:
            payload["scope_type"] = scope_type
            payload["scope_id"] = scope_id
            if document_id:
                payload["document_id"] = document_id
        else:
            payload["agent_id"] = _agent_id
        r = await http.post(
            "/memory/index",
            json=payload,
            headers=_auth_headers(),
        )
        return json.dumps(r.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


@mcp.tool(
    name="bridge_memory_delete",
    description=(
        "Delete a document from semantic memory. "
        "Use with explicit scope_type/scope_id for user/project/team/global scopes, "
        "or omit them to delete from the current agent scope."
    ),
)
async def bridge_memory_delete(
    document_id: str,
    scope_type: str = "",
    scope_id: str = "",
) -> str:
    """Delete a semantic-memory document."""
    if _agent_id is None:
        return json.dumps({"error": "not registered"})
    try:
        http = _get_http()
        payload: dict[str, Any] = {"document_id": document_id}
        if scope_type or scope_id:
            payload["scope_type"] = scope_type
            payload["scope_id"] = scope_id
        else:
            payload["agent_id"] = _agent_id
        r = await http.post("/memory/delete", json=payload, headers=_auth_headers())
        return json.dumps(r.json())
    except Exception as exc:
        return json.dumps({"error": _exc_message(exc)})


# ---------------------------------------------------------------------------
# Research Verification
# ---------------------------------------------------------------------------


def _check_freshness(
    published_date: str | None, threshold_days: int
) -> tuple[int | None, bool]:
    """Return (age_days, is_stale). Unknown date = warn."""
    if not published_date:
        return None, True
    try:
        dt = datetime.strptime(published_date[:10], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        age = (datetime.now(timezone.utc) - dt).days
        return age, age > threshold_days
    except (ValueError, TypeError):
        return None, True


@mcp.tool(
    name="bridge_research",
    description="Fetch a URL and return content with freshness metadata. "
    "Automatically extracts publication date and warns if content is stale.",
)
async def bridge_research(url: str, freshness_days: int = 90) -> str:
    """URL-fetch wrapper with automatic freshness metadata."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not url or not url.strip():
        return json.dumps({"error": "url is required"})

    url = url.strip()
    retrieved_at = datetime.now(timezone.utc).isoformat()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                url,
                follow_redirects=True,
                headers={"User-Agent": "Bridge-Research/1.0"},
            )
            resp.raise_for_status()
            content = resp.text
    except Exception as exc:
        return json.dumps({
            "ok": False,
            "error": f"research failed: {exc}",
            "url": url,
            "retrieved_at": retrieved_at,
        })

    published_date = _extract_page_date(content)
    age_days, is_stale = _check_freshness(published_date, freshness_days)

    warnings: list[str] = []
    if is_stale:
        if age_days is not None:
            warnings.append(
                f"Content older than {freshness_days} days ({age_days} days old)"
            )
        else:
            warnings.append(
                "Could not determine publication date — treating as potentially stale"
            )

    return json.dumps({
        "ok": True,
        "url": url,
        "retrieved_at": retrieved_at,
        "freshness_threshold_days": freshness_days,
        "content": content,
        "published_date": published_date,
        "age_days": age_days,
        "freshness_warning": is_stale,
        "warnings": warnings,
    })


# ---------------------------------------------------------------------------
# Creator Tools
# ---------------------------------------------------------------------------


def _creator_submit_target(
    job_type: str,
    source: dict[str, Any],
    workspace_dir: str,
    config: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    source = dict(source or {})
    config = dict(config or {})
    workspace_dir = str(workspace_dir or "").strip()
    if not workspace_dir:
        raise ValueError("workspace_dir is required")

    if job_type == "local_ingest":
        input_path = str(source.get("input_path", "")).strip()
        if not input_path:
            raise ValueError("source.input_path is required for local_ingest")
        return (
            "/creator/jobs/local-ingest",
            {
                "input_path": input_path,
                "workspace_dir": workspace_dir,
                "language": str(config.get("language", "de")).strip() or "de",
                "model": str(config.get("model", "")).strip(),
                "transcribe": bool(config.get("transcribe", True)),
            },
        )

    if job_type == "url_ingest":
        source_url = str(source.get("source_url", "")).strip()
        if not source_url:
            raise ValueError("source.source_url is required for url_ingest")
        return (
            "/creator/jobs/url-ingest",
            {
                "source_url": source_url,
                "workspace_dir": workspace_dir,
                "language": str(config.get("language", "de")).strip() or "de",
                "model": str(config.get("model", "")).strip(),
                "transcribe": bool(config.get("transcribe", True)),
            },
        )

    if job_type == "analyze_content":
        source_job_id = (
            str(source.get("source_job_id", "")).strip()
            or str(source.get("job_id", "")).strip()
        )
        if not source_job_id:
            raise ValueError("source.source_job_id or source.job_id is required for analyze_content")
        return (
            "/creator/jobs/analyze",
            {
                "source_job_id": source_job_id,
                "workspace_dir": workspace_dir,
                "config": config,
            },
        )

    if job_type == "publish":
        source_job_id = str(source.get("source_job_id", "")).strip()
        clip_path = str(source.get("clip_path", "")).strip()
        return (
            "/creator/jobs/publish",
            {
                "source_job_id": source_job_id,
                "clip_path": clip_path,
                "workspace_dir": workspace_dir,
                "channels": config.get("channels", source.get("channels", [])),
            },
        )

    if job_type == "voiceover":
        text = str(config.get("text", source.get("text", ""))).strip()
        video_path = str(source.get("video_path", "")).strip()
        if not text:
            raise ValueError("config.text is required for voiceover")
        return (
            "/creator/jobs/voiceover",
            {
                "text": text,
                "video_path": video_path,
                "voice_id": str(config.get("voice_id", source.get("voice_id", ""))).strip(),
                "workspace_dir": workspace_dir,
            },
        )

    if job_type == "voice_clone":
        audio_path = str(source.get("audio_path", "")).strip()
        if not audio_path:
            raise ValueError("source.audio_path is required for voice_clone")
        return (
            "/creator/jobs/voice-clone",
            {
                "audio_path": audio_path,
                "voice_name": str(config.get("voice_name", source.get("voice_name", ""))).strip(),
                "workspace_dir": workspace_dir,
            },
        )

    if job_type == "embed_content":
        video_path = str(source.get("video_path", "")).strip()
        if not video_path:
            raise ValueError("source.video_path is required for embed_content")
        return (
            "/creator/jobs/embed",
            {
                "video_path": video_path,
                "workspace_dir": workspace_dir,
                "chunk_duration_s": int(config.get("chunk_duration_s", source.get("chunk_duration_s", 120))),
                "collection": str(config.get("collection", source.get("collection", "creator_video_embeddings"))),
            },
        )

    raise ValueError(
        "Unsupported creator job_type. Supported: local_ingest, url_ingest, analyze_content, "
        "publish, voiceover, voice_clone, embed_content"
    )


@mcp.tool(
    name="bridge_creator_job_submit",
    description=(
        "Submit an asynchronous creator job via the Bridge HTTP API. "
        "Supported job types: local_ingest, url_ingest, analyze_content, publish, "
        "voiceover, voice_clone, embed_content."
    ),
)
async def bridge_creator_job_submit(
    job_type: str,
    source: dict[str, Any],
    workspace_dir: str,
    config: dict[str, Any] | None = None,
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        path, payload = _creator_submit_target(job_type, source, workspace_dir, config or {})
        resp = await _bridge_post(path, json=payload)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_job_status",
    description="Get the current state of an asynchronous creator job by job_id.",
)
async def bridge_creator_job_status(job_id: str, workspace_dir: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(job_id or "").strip():
        return json.dumps({"error": "job_id is required"})
    if not str(workspace_dir or "").strip():
        return json.dumps({"error": "workspace_dir is required"})
    try:
        resp = await _bridge_get(
            f"/creator/jobs/{job_id.strip()}",
            params={"workspace_dir": workspace_dir.strip()},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_job_cancel",
    description="Cancel a queued or running asynchronous creator job.",
)
async def bridge_creator_job_cancel(job_id: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(job_id or "").strip():
        return json.dumps({"error": "job_id is required"})
    try:
        resp = await _bridge_post(f"/creator/jobs/{job_id.strip()}/cancel", json={})
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_job_retry",
    description="Retry a failed creator job from its failed stage.",
)
async def bridge_creator_job_retry(job_id: str, workspace_dir: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(job_id or "").strip():
        return json.dumps({"error": "job_id is required"})
    if not str(workspace_dir or "").strip():
        return json.dumps({"error": "workspace_dir is required"})
    try:
        resp = await _bridge_post(
            f"/creator/jobs/{job_id.strip()}/retry",
            json={"workspace_dir": workspace_dir.strip()},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_job_list",
    description="List creator jobs in a workspace, optionally filtered by status.",
)
async def bridge_creator_job_list(workspace_dir: str, status: str = "") -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(workspace_dir or "").strip():
        return json.dumps({"error": "workspace_dir is required"})
    try:
        params = {"workspace_dir": workspace_dir.strip()}
        if status:
            params["status"] = str(status).strip()
        resp = await _bridge_get("/creator/jobs", params=params)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_publish",
    description=(
        "Submit a multi-channel publish job from a source creator job or explicit clip_path. "
        "If clip_index is non-zero, provide clip_path explicitly because source-job clip selection "
        "is not yet multi-artifact aware."
    ),
)
async def bridge_creator_publish(
    source_job_id: str,
    workspace_dir: str,
    channels: list[Any],
    clip_index: int = 0,
    clip_path: str = "",
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(workspace_dir or "").strip():
        return json.dumps({"error": "workspace_dir is required"})
    if not str(source_job_id or "").strip() and not str(clip_path or "").strip():
        return json.dumps({"error": "source_job_id or clip_path is required"})
    if int(clip_index or 0) != 0 and not str(clip_path or "").strip():
        return json.dumps(
            {
                "error": (
                    "clip_index selection is not yet supported without an explicit clip_path; "
                    "pass clip_path or use clip_index=0"
                )
            }
        )
    try:
        resp = await _bridge_post(
            "/creator/jobs/publish",
            json={
                "source_job_id": str(source_job_id or "").strip(),
                "clip_path": str(clip_path or "").strip(),
                "workspace_dir": workspace_dir.strip(),
                "channels": channels,
            },
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_campaign_create",
    description="Create a creator campaign and return campaign_id plus initial state.",
)
async def bridge_creator_campaign_create(
    title: str,
    goal: str,
    target_platforms: list[str],
    workspace_dir: str,
    owner: str = "",
    target_audience: str = "",
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(title or "").strip():
        return json.dumps({"error": "title is required"})
    if not str(workspace_dir or "").strip():
        return json.dumps({"error": "workspace_dir is required"})
    try:
        resp = await _bridge_post(
            "/creator/campaigns",
            json={
                "title": title.strip(),
                "goal": str(goal or "").strip(),
                "target_platforms": target_platforms or [],
                "workspace_dir": workspace_dir.strip(),
                "owner": str(owner or "").strip(),
                "target_audience": str(target_audience or "").strip(),
            },
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_campaign_status",
    description="Get the current state of a creator campaign by campaign_id.",
)
async def bridge_creator_campaign_status(campaign_id: str, workspace_dir: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(campaign_id or "").strip():
        return json.dumps({"error": "campaign_id is required"})
    if not str(workspace_dir or "").strip():
        return json.dumps({"error": "workspace_dir is required"})
    try:
        resp = await _bridge_get(
            f"/creator/campaigns/{campaign_id.strip()}",
            params={"workspace_dir": workspace_dir.strip()},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_voiceover",
    description="Submit a creator voiceover job (text -> TTS -> optional video merge).",
)
async def bridge_creator_voiceover(
    text: str,
    voice_id: str,
    video_path: str,
    workspace_dir: str,
) -> str:
    return await bridge_creator_job_submit(
        job_type="voiceover",
        source={"video_path": video_path},
        workspace_dir=workspace_dir,
        config={"text": text, "voice_id": voice_id},
    )


@mcp.tool(
    name="bridge_creator_voice_clone",
    description="Submit a creator voice clone job from an audio sample.",
)
async def bridge_creator_voice_clone(audio_path: str, voice_name: str, workspace_dir: str) -> str:
    return await bridge_creator_job_submit(
        job_type="voice_clone",
        source={"audio_path": audio_path},
        workspace_dir=workspace_dir,
        config={"voice_name": voice_name},
    )


@mcp.tool(
    name="bridge_creator_embed",
    description="Submit a creator embedding job for video search / retrieval.",
)
async def bridge_creator_embed(
    video_path: str,
    workspace_dir: str,
    collection: str = "creator_video_embeddings",
    chunk_duration_s: int = 120,
) -> str:
    return await bridge_creator_job_submit(
        job_type="embed_content",
        source={"video_path": video_path},
        workspace_dir=workspace_dir,
        config={"collection": collection, "chunk_duration_s": chunk_duration_s},
    )


@mcp.tool(
    name="bridge_creator_search",
    description="Search embedded creator video content synchronously by semantic query.",
)
async def bridge_creator_search(
    query: str,
    collection: str = "creator_video_embeddings",
    top_k: int = 5,
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(query or "").strip():
        return json.dumps({"error": "query is required"})
    try:
        resp = await _bridge_post(
            "/creator/search",
            json={
                "query": query.strip(),
                "collection": collection.strip() or "creator_video_embeddings",
                "top_k": int(top_k),
            },
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_voices",
    description="List available Fish Audio voices / configured creator voice options.",
)
async def bridge_creator_voices() -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_get("/creator/voices")
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_library",
    description="List embedded creator videos in the semantic search collection.",
)
async def bridge_creator_library(collection: str = "creator_video_embeddings") -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        resp = await _bridge_get(
            "/creator/library",
            params={"collection": collection.strip() or "creator_video_embeddings"},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_creator_local_ingest",
    description=(
        "Probe and optionally transcribe a local media file for content creators. "
        "Returns media metadata, extracted audio, transcript, chapters, and highlight candidates."
    ),
)
async def bridge_creator_local_ingest(
    input_path: str,
    workspace_dir: str,
    language: str = "de",
    model: str = "",
    transcribe: bool = True,
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        import creator_media

        result = await asyncio.to_thread(
            creator_media.ingest_local_media,
            input_path,
            workspace_dir,
            language=language or "de",
            model=(model.strip() or None),
            transcribe=transcribe,
        )
        return json.dumps({"ok": True, "result": result})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_creator_url_ingest",
    description=(
        "Download and ingest a creator source from a URL or YouTube link into the creator media model. "
        "Returns source metadata, local download path, media metadata, audio artifact, transcript, chapters, "
        "and highlight candidates."
    ),
)
async def bridge_creator_url_ingest(
    source_url: str,
    workspace_dir: str,
    language: str = "de",
    model: str = "",
    transcribe: bool = True,
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        import creator_media

        result = await asyncio.to_thread(
            creator_media.ingest_url_media,
            source_url,
            workspace_dir,
            language=language or "de",
            model=(model.strip() or None),
            transcribe=transcribe,
        )
        return json.dumps({"ok": True, "result": result})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_creator_write_srt",
    description="Write an SRT subtitle file from transcript segments.",
)
async def bridge_creator_write_srt(segments: list[dict[str, Any]], output_path: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        import creator_media

        result = await asyncio.to_thread(creator_media.write_srt, segments, output_path)
        return json.dumps({"ok": True, "result": result})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_creator_highlights",
    description="Score transcript segments and return highlight candidates for shorts or clips.",
)
async def bridge_creator_highlights(
    segments: list[dict[str, Any]],
    max_candidates: int = 3,
    min_duration_s: float = 2.0,
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        import creator_media

        result = await asyncio.to_thread(
            creator_media.pick_highlight_candidates,
            segments,
            max_candidates=max_candidates,
            min_duration_s=min_duration_s,
        )
        return json.dumps({"ok": True, "highlights": result, "count": len(result)})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_creator_export_clip",
    description="Trim a local media file to a clip between start_s and end_s.",
)
async def bridge_creator_export_clip(
    input_path: str,
    output_path: str,
    start_s: float,
    end_s: float,
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        import creator_media

        result = await asyncio.to_thread(
            creator_media.export_clip,
            input_path,
            output_path,
            start_s=start_s,
            end_s=end_s,
        )
        return json.dumps({"ok": True, "result": result})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_creator_social_presets",
    description="List platform-native creator export presets such as vertical, square, and landscape.",
)
async def bridge_creator_social_presets() -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        import creator_media

        presets = await asyncio.to_thread(creator_media.list_social_presets)
        return json.dumps({"ok": True, "presets": presets, "count": len(presets)})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_creator_export_social_clip",
    description=(
        "Export a creator clip in a platform preset such as youtube_short or square_post, "
        "optionally with burned subtitles."
    ),
)
async def bridge_creator_export_social_clip(
    input_path: str,
    output_path: str,
    start_s: float,
    end_s: float,
    preset_name: str = "youtube_short",
    segments: list[dict[str, Any]] | None = None,
    burn_subtitles: bool = False,
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        import creator_media

        result = await asyncio.to_thread(
            creator_media.export_social_clip,
            input_path,
            output_path,
            start_s=start_s,
            end_s=end_s,
            preset_name=preset_name,
            segments=segments,
            burn_subtitles=burn_subtitles,
        )
        return json.dumps({"ok": True, "result": result})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_creator_package_social",
    description=(
        "Generate a creator package with multiple platform-ready assets, an optional sidecar SRT, "
        "and a manifest JSON from one source clip."
    ),
)
async def bridge_creator_package_social(
    input_path: str,
    output_dir: str,
    package_name: str,
    start_s: float,
    end_s: float,
    preset_names: list[str] | None = None,
    segments: list[dict[str, Any]] | None = None,
    burn_subtitles: bool = True,
    write_sidecar_srt: bool = True,
    default_metadata: dict[str, Any] | None = None,
    metadata_by_preset: dict[str, Any] | None = None,
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        import creator_media

        result = await asyncio.to_thread(
            creator_media.create_social_package,
            input_path,
            output_dir,
            package_name=package_name,
            start_s=start_s,
            end_s=end_s,
            preset_names=preset_names,
            segments=segments,
            burn_subtitles=burn_subtitles,
            write_sidecar_srt=write_sidecar_srt,
            default_metadata=default_metadata,
            metadata_by_preset=metadata_by_preset,
        )
        return json.dumps({"ok": True, "result": result})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Data Platform Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="bridge_data_source_register",
    description="Register a local analytics data source (CSV, Excel, JSON, SQLite, Parquet).",
)
async def bridge_data_source_register(name: str, kind: str, location: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(name or "").strip():
        return json.dumps({"error": "name is required"})
    if not str(kind or "").strip():
        return json.dumps({"error": "kind is required"})
    if not str(location or "").strip():
        return json.dumps({"error": "location is required"})
    try:
        resp = await _bridge_post(
            "/data/sources",
            json={
                "name": name.strip(),
                "kind": kind.strip(),
                "location": location.strip(),
            },
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_data_source_ingest",
    description="Ingest a registered data source into canonical Parquet and return the dataset version.",
)
async def bridge_data_source_ingest(source_id: str, profile_mode: str = "fast") -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(source_id or "").strip():
        return json.dumps({"error": "source_id is required"})
    try:
        resp = await _bridge_post(
            f"/data/sources/{source_id.strip()}/ingest",
            json={"profile_mode": profile_mode.strip() or "fast"},
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_data_dataset_profile",
    description="Load the schema/profile for a dataset and optional dataset version.",
)
async def bridge_data_dataset_profile(dataset_id: str, version_id: str = "") -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(dataset_id or "").strip():
        return json.dumps({"error": "dataset_id is required"})
    params: dict[str, str] = {}
    if version_id:
        params["version_id"] = version_id.strip()
    try:
        resp = await _bridge_get(f"/data/datasets/{dataset_id.strip()}/profile", params=params or None)
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_data_run_start",
    description="Start an asynchronous analytics run over one or more dataset versions.",
)
async def bridge_data_run_start(
    question: str,
    dataset_version_ids: list[str],
    mode: str = "single_agent",
) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(question or "").strip():
        return json.dumps({"error": "question is required"})
    if not dataset_version_ids:
        return json.dumps({"error": "dataset_version_ids is required"})
    try:
        resp = await _bridge_post(
            "/data/runs",
            json={
                "question": question.strip(),
                "dataset_version_ids": dataset_version_ids,
                "mode": mode.strip() or "single_agent",
            },
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_data_run_status",
    description="Get the current state of an analytics run by run_id.",
)
async def bridge_data_run_status(run_id: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(run_id or "").strip():
        return json.dumps({"error": "run_id is required"})
    try:
        resp = await _bridge_get(f"/data/runs/{run_id.strip()}")
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_data_run_evidence",
    description="Load the evidence bundle for a completed analytics run.",
)
async def bridge_data_run_evidence(run_id: str) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(run_id or "").strip():
        return json.dumps({"error": "run_id is required"})
    try:
        resp = await _bridge_get(f"/data/runs/{run_id.strip()}/evidence")
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_data_query",
    description="Execute a sandboxed DuckDB SQL query against one or more dataset versions.",
)
async def bridge_data_query(sql: str, dataset_version_ids: list[str]) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(sql or "").strip():
        return json.dumps({"error": "sql is required"})
    if not dataset_version_ids:
        return json.dumps({"error": "dataset_version_ids is required"})
    try:
        resp = await _bridge_post(
            "/data/query",
            json={
                "sql": sql.strip(),
                "dataset_version_ids": dataset_version_ids,
            },
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


@mcp.tool(
    name="bridge_data_query_dry_run",
    description="Run SQL guard checks without executing the query.",
)
async def bridge_data_query_dry_run(sql: str, allowed_tables: list[str]) -> str:
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not str(sql or "").strip():
        return json.dumps({"error": "sql is required"})
    try:
        resp = await _bridge_post(
            "/data/query/dry-run",
            json={
                "sql": sql.strip(),
                "allowed_tables": allowed_tables or [],
            },
        )
        return json.dumps(resp.json())
    except Exception as exc:
        return json.dumps({"ok": False, "error": _exc_message(exc)})


# ---------------------------------------------------------------------------
# Voice Tools (STT / TTS)
# ---------------------------------------------------------------------------

@mcp.tool(
    name="bridge_voice_transcribe",
    description=(
        "Transcribe an audio file to text using local Whisper STT. "
        "Supports .ogg, .m4a, .mp3, .wav. Returns transcript text."
    ),
)
async def bridge_voice_transcribe(audio_path: str, language: str = "de") -> str:
    """Standalone Speech-to-Text — not WhatsApp-specific."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not audio_path or not audio_path.strip():
        return json.dumps({"error": "audio_path is required"})
    try:
        from voice_stt import transcribe_audio, TranscribeError
        result = await transcribe_audio(audio_path.strip(), language=language)
        return json.dumps({"ok": True, **result})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_voice_quota",
    description="Check ElevenLabs TTS quota (characters used/remaining).",
)
async def bridge_voice_quota() -> str:
    """Get ElevenLabs subscription quota."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        from voice_tts import get_quota
        result = await get_quota()
        return json.dumps({"ok": True, **result})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_whatsapp_voice",
    description=(
        "Send a voice message to WhatsApp: converts text to speech (ElevenLabs TTS) "
        "and sends the audio via WhatsApp. Goes through approval gate like bridge_whatsapp_send. "
        "Optional voice_id to select a specific ElevenLabs voice."
    ),
)
async def bridge_whatsapp_voice(to: str, text: str, voice_id: str = "") -> str:
    """TTS + WhatsApp Send in one step. Respects approval gate."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    if not to or not to.strip():
        return json.dumps({"error": "'to' is required"})
    if not text or not text.strip():
        return json.dumps({"error": "'text' is required"})

    # Step 1: Resolve recipient + check whitelists (same logic as bridge_whatsapp_send)
    resolved_to = _resolve_whatsapp_recipient(to.strip())
    display_name = to.strip()

    # Send-Whitelist enforcement (fail-closed)
    if not _WHATSAPP_SEND_WHITELIST:
        return json.dumps({
            "status": "blocked",
            "error": "WhatsApp Send-Whitelist ist leer. Keine Empfaenger erlaubt.",
        })
    if resolved_to not in _WHATSAPP_SEND_WHITELIST:
        return json.dumps({
            "status": "blocked",
            "error": f"Empfaenger '{display_name}' (JID: {_mask_phone(resolved_to)}) nicht in Send-Whitelist",
        })

    # Step 2: Approval gate (skip for approval-whitelisted JIDs)
    needs_approval = resolved_to not in _WHATSAPP_APPROVAL_WHITELIST

    if needs_approval:
        approval_body = {
            "agent_id": _agent_id,
            "action": "whatsapp_voice",
            "target": display_name,
            "description": f"WhatsApp Voice an {display_name}: {text[:80]}",
            "risk_level": "high",
            "payload": {
                "to": resolved_to,
                "text": text,
                "voice_id": voice_id,
            },
            "timeout_seconds": 300,
        }
        try:
            resp = await _bridge_post("/approval/request", json=approval_body)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") not in ("auto_approved", "approved"):
                return json.dumps({
                    "status": "pending_approval",
                    "request_id": data.get("request_id"),
                    "message": f"WhatsApp Voice an {display_name} wartet auf Leos Genehmigung.",
                })
        except Exception as exc:
            return json.dumps({"error": f"Approval request failed: {exc}"})

    # Step 3: TTS
    try:
        from voice_tts import synthesize_speech, SynthesizeError
        vid = voice_id.strip() if voice_id else ""
        tts_kwargs = {"text": text.strip()}
        if vid:
            tts_kwargs["voice_id"] = vid
        tts_result = await synthesize_speech(**tts_kwargs)
        audio_path = tts_result["audio_path"]
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"TTS failed: {exc}"})

    # Step 4: Send via Go Bridge
    if not _WHATSAPP_API_TOKEN:
        return json.dumps({
            "ok": False,
            "error": "WhatsApp Bridge Token nicht konfiguriert.",
        })

    try:
        headers = {"X-WhatsApp-Token": _WHATSAPP_API_TOKEN}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_WHATSAPP_BRIDGE_URL}/api/send",
                json={"recipient": resolved_to, "message": "", "media_path": audio_path},
                headers=headers,
            )
            data = resp.json()
            if data.get("success"):
                # Cleanup temp file
                try:
                    os.remove(audio_path)
                except OSError:
                    pass
                return json.dumps({
                    "ok": True,
                    "status": "sent",
                    "to": display_name,
                    "chars_used": tts_result.get("chars_used", 0),
                    "tts_elapsed_s": tts_result.get("elapsed_s", 0),
                })
            else:
                return json.dumps({
                    "ok": False,
                    "error": data.get("message", "Send failed"),
                    "source": "whatsapp_bridge",
                })
    except httpx.ConnectError:
        return json.dumps({
            "ok": False,
            "error": f"WhatsApp Bridge nicht erreichbar: {_WHATSAPP_BRIDGE_URL}",
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Git Collaboration Tools (Release-Blocker 2)
# ---------------------------------------------------------------------------

import git_collaboration as _gitcollab


@mcp.tool(
    name="bridge_git_branch_create",
    description=(
        "Create a namespaced git branch with an isolated worktree for the agent. "
        "Branch format: bridge/<instance_id>/<agent_id>/<feature>. "
        "Requires a git repo path and feature name."
    ),
)
async def bridge_git_branch_create(
    repo_dir: str,
    feature: str,
    from_ref: str = "HEAD",
    worktree_base: str = "",
) -> str:
    """Create namespaced branch + worktree."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge_config.json")
        instance_id = _gitcollab.get_instance_id(config_path=config_path)
        if not worktree_base:
            worktree_base = os.path.join(repo_dir, ".bridge", "worktrees")
        result = _gitcollab.git_branch_create(
            repo_dir=repo_dir,
            instance_id=instance_id,
            agent_id=_agent_id,
            feature=feature,
            worktree_base=worktree_base,
            from_ref=from_ref,
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_git_commit",
    description=(
        "Commit files in the agent's git worktree. "
        "Specify the worktree path, commit message, and list of files to stage."
    ),
)
async def bridge_git_commit(
    worktree_path: str,
    message: str,
    files: list[str] | None = None,
) -> str:
    """Commit in agent worktree."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        # Ownership validation: worktree must belong to this agent
        ownership = _gitcollab.validate_worktree_ownership(
            worktree_path=worktree_path,
            agent_id=_agent_id,
        )
        if not ownership.get("ok"):
            return json.dumps({"ok": False, "error": f"Ownership check failed: {ownership.get('error', 'unknown')}"})

        result = _gitcollab.git_commit(
            worktree_path=worktree_path,
            message=message,
            files=files,
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_git_push",
    description=(
        "Push current branch to remote. Checks advisory locks — "
        "push is blocked if the branch is locked by another agent."
    ),
)
async def bridge_git_push(
    worktree_path: str,
    remote: str = "origin",
) -> str:
    """Push with lock check."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        # Ownership validation: worktree must belong to this agent
        ownership = _gitcollab.validate_worktree_ownership(
            worktree_path=worktree_path,
            agent_id=_agent_id,
        )
        if not ownership.get("ok"):
            return json.dumps({"ok": False, "error": f"Ownership check failed: {ownership.get('error', 'unknown')}"})

        lock_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "git_locks.json")
        result = _gitcollab.git_push(
            worktree_path=worktree_path,
            lock_file=lock_file,
            agent_id=_agent_id,
            remote=remote,
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_git_conflict_check",
    description=(
        "Dry-run merge check: detect if merging a branch into target would cause conflicts. "
        "Uses git merge-tree — no worktree mutation. "
        "Returns clean=True/False and list of conflicting files."
    ),
)
async def bridge_git_conflict_check(
    repo_dir: str,
    branch: str,
    target: str = "main",
) -> str:
    """Conflict detection via merge-tree."""
    try:
        result = _gitcollab.git_conflict_check(
            repo_dir=repo_dir,
            branch=branch,
            target=target,
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_git_lock",
    description=(
        "Acquire advisory lock on a git branch. "
        "Prevents other agents from pushing to the branch. "
        "Lock has TTL (default 30 min) and auto-expires. "
        "Same agent can refresh its own lock."
    ),
)
async def bridge_git_lock(
    branch: str,
    ttl_seconds: int = 1800,
) -> str:
    """Acquire branch lock."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge_config.json")
        instance_id = _gitcollab.get_instance_id(config_path=config_path)
        lock_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "git_locks.json")
        result = _gitcollab.acquire_lock(
            lock_file=lock_file,
            branch=branch,
            agent_id=_agent_id,
            instance_id=instance_id,
            ttl_seconds=ttl_seconds,
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_git_unlock",
    description=(
        "Release advisory lock on a git branch. "
        "Only the lock owner can release it."
    ),
)
async def bridge_git_unlock(branch: str) -> str:
    """Release branch lock."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        lock_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "git_locks.json")
        result = _gitcollab.release_lock(
            lock_file=lock_file,
            branch=branch,
            agent_id=_agent_id,
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool(
    name="bridge_git_hook_install",
    description=(
        "Install a Bridge pre-push hook in a git repository. "
        "The hook enforces advisory branch locks by querying the Bridge server "
        "before allowing pushes. Blocks raw 'git push' when branch is locked by another agent. "
        "Will not overwrite non-Bridge hooks."
    ),
)
async def bridge_git_hook_install(repo_dir: str) -> str:
    """Install pre-push hook for lock enforcement."""
    if _agent_id is None:
        return json.dumps({"error": "Not registered. Call bridge_register first."})
    try:
        result = _gitcollab.install_pre_push_hook(repo_dir=repo_dir)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _startup_auto_register():
    """Auto-register agent when MCP server starts (not when agent calls tool).

    Solves the post-compact registration gap: after /compact, the agent loses
    context and may not call bridge_register(). This ensures the agent is always
    registered as long as the MCP server process is alive.
    """
    import asyncio
    import time as _t

    _t.sleep(3)  # Wait for MCP transport to stabilize

    agent_id = os.environ.get("BRIDGE_CLI_AGENT_ID", "").strip()
    if not agent_id:
        return

    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(bridge_register(
            agent_id,
            role=os.environ.get("BRIDGE_CLI_ROLE", "agent"),
        ))
        loop.close()
        log.info("[auto-register] Agent %s registered at MCP startup", agent_id)
    except Exception as exc:
        log.warning("[auto-register] Failed for %s: %s", agent_id, exc)
    finally:
        # P0-3 FIX: Background tasks (heartbeat, WS listener) were created on the
        # throwaway event loop which is now dead. Reset references so
        # _ensure_background_tasks() creates fresh tasks on the real MCP
        # event loop when bridge_register is called as a tool later.
        global _ws_task, _heartbeat_task
        _ws_task = None
        _heartbeat_task = None


if __name__ == "__main__":
    import threading
    threading.Thread(target=_startup_auto_register, daemon=True).start()
    mcp.run(transport="stdio")
