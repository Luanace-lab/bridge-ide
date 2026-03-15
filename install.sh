#!/usr/bin/env bash
set -euo pipefail

# Bridge IDE — Local Installation Script
# Installs dependencies and prepares the environment for running Bridge IDE locally.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/Backend"
PYTHON="${PYTHON:-python3}"

echo "=== Bridge IDE — Installation ==="
echo ""

# Check Python version
PYVER=$("${PYTHON}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PYMAJOR=$(echo "${PYVER}" | cut -d. -f1)
PYMINOR=$(echo "${PYVER}" | cut -d. -f2)

if [[ "${PYMAJOR}" -lt 3 || ("${PYMAJOR}" -eq 3 && "${PYMINOR}" -lt 10) ]]; then
    echo "ERROR: Python 3.10+ required (found ${PYVER})"
    echo "Set PYTHON=python3.x to use a specific version."
    exit 1
fi
echo "[OK] Python ${PYVER}"

# Install tmux (required for agent sessions)
if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux not found — installing (required for agent sessions)..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y tmux
    elif command -v brew >/dev/null 2>&1; then
        brew install tmux
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y tmux
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm tmux
    else
        echo "ERROR: Cannot auto-install tmux. Please install manually:"
        echo "  Ubuntu/Debian: sudo apt install tmux"
        echo "  macOS:         brew install tmux"
        echo "  Fedora:        sudo dnf install tmux"
        exit 1
    fi
fi
echo "[OK] tmux available"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
"${PYTHON}" -m pip install --quiet -r "${SCRIPT_DIR}/requirements.txt"
echo "[OK] Dependencies installed"

# Create runtime directories
mkdir -p "${BACKEND_DIR}/logs" "${BACKEND_DIR}/pids" "${BACKEND_DIR}/messages"
echo "[OK] Runtime directories created"

# Initialize empty data files if missing
if [[ ! -f "${BACKEND_DIR}/team.json" ]]; then
    echo '{"agents":[],"teams":[],"hierarchy":{"levels":[]}}' > "${BACKEND_DIR}/team.json"
    echo "[OK] team.json initialized"
fi

if [[ ! -f "${BACKEND_DIR}/automations.json" ]]; then
    echo '{"automations":[]}' > "${BACKEND_DIR}/automations.json"
    echo "[OK] automations.json initialized"
fi

echo ""
echo "=== Installation complete ==="
echo ""
echo "Start Bridge IDE:"
echo "  ${PYTHON} -u ${BACKEND_DIR}/server.py"
echo ""
echo "Or with Docker:"
echo "  cd ${SCRIPT_DIR} && docker compose up --build"
echo ""
echo "Access UI: http://127.0.0.1:9111"
echo "API:       http://127.0.0.1:9111/status"
echo "WebSocket: ws://127.0.0.1:9112"
echo ""
echo "Optional WhatsApp setup:"
echo "  ${SCRIPT_DIR}/docs/whatsapp-setup.md"
echo ""
echo "Optional Telegram setup:"
echo "  ${SCRIPT_DIR}/docs/telegram-setup.md"
