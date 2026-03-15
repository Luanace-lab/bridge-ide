#!/usr/bin/env bash
# Bridge IDE — Setup / Preflight Check
# Prueft alle Voraussetzungen fuer ein frisches System.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
ERRORS=0

ok()   { echo -e "  ${GREEN}[OK]${NC}   $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; ERRORS=$((ERRORS + 1)); }

echo "=== Bridge IDE — Preflight Check ==="
echo ""

# --- System Tools ---
echo "--- System Tools ---"
for cmd in python3 tmux curl bash setsid pgrep; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$cmd $(command -v "$cmd")"
    else
        fail "$cmd nicht gefunden"
    fi
done

# Python Version (>= 3.10)
PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
    ok "Python ${PY_VERSION}"
else
    fail "Python >= 3.10 erforderlich (gefunden: ${PY_VERSION})"
fi

echo ""

# --- Optional Tools ---
echo "--- Optionale Tools ---"
for cmd in n8n node npm ffmpeg ffprobe gnome-screenshot xdotool; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$cmd"
    else
        warn "$cmd nicht gefunden (optional)"
    fi
done

echo ""

# --- Python Packages ---
echo "--- Python Packages ---"
REQUIRED_PKGS=(cryptography httpx mcp numpy)
OPTIONAL_PKGS=(duckdb chromadb sentence_transformers patchright playwright nacl)

for pkg in "${REQUIRED_PKGS[@]}"; do
    if python3 -c "import $pkg" 2>/dev/null; then
        ok "python3: $pkg"
    else
        fail "python3: $pkg fehlt (pip install -r requirements.txt)"
    fi
done

for pkg in "${OPTIONAL_PKGS[@]}"; do
    if python3 -c "import $pkg" 2>/dev/null; then
        ok "python3: $pkg (optional)"
    else
        warn "python3: $pkg nicht installiert (optional)"
    fi
done

echo ""

# --- Directories ---
echo "--- Verzeichnisse ---"
for dir in logs pids messages domain_engine domain_packs handlers; do
    if [ -d "${SCRIPT_DIR}/${dir}" ]; then
        ok "$dir/"
    else
        fail "$dir/ fehlt"
    fi
done

echo ""

# --- Core Files ---
echo "--- Core Files ---"
for f in server.py bridge_mcp.py tmux_manager.py bridge_watcher.py common.py team.json start_platform.sh stop_platform.sh restart_wrapper.sh; do
    if [ -f "${SCRIPT_DIR}/${f}" ]; then
        ok "$f"
    else
        fail "$f fehlt"
    fi
done

echo ""

# --- Config ---
echo "--- Konfiguration ---"
CONFIG_DIR="${HOME}/.config/bridge"
if [ -d "$CONFIG_DIR" ]; then
    ok "$CONFIG_DIR/"
else
    warn "$CONFIG_DIR/ fehlt (wird beim ersten Start erstellt)"
    mkdir -p "$CONFIG_DIR"
    ok "$CONFIG_DIR/ erstellt"
fi

TOKEN_FILE="${CONFIG_DIR}/tokens.json"
if [ -f "$TOKEN_FILE" ]; then
    ok "tokens.json"
else
    warn "tokens.json fehlt (wird beim ersten Start generiert)"
fi

echo ""

# --- Syntax Check (core modules) ---
echo "--- Syntax-Check ---"
SYNTAX_OK=0
for f in server.py bridge_mcp.py common.py tmux_manager.py bridge_watcher.py; do
    if python3 -m py_compile "${SCRIPT_DIR}/${f}" 2>/dev/null; then
        ok "$f kompiliert"
    else
        fail "$f Syntax-Fehler"
        SYNTAX_OK=1
    fi
done

echo ""
echo "=== Ergebnis ==="
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}Alle Pflicht-Checks bestanden.${NC} Plattform kann gestartet werden."
    echo "  → bash start_platform.sh"
else
    echo -e "${RED}${ERRORS} Fehler gefunden.${NC} Bitte beheben vor Start."
    echo "  → pip install -r requirements.txt"
fi

exit "$ERRORS"
