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
# PEP 668: Ubuntu 24.04+ blocks global pip installs. Use --break-system-packages
# as Bridge is typically installed on a dedicated system or container.
echo ""
echo "Installing Python dependencies..."
PIP_ARGS="--quiet"
if "${PYTHON}" -m pip install --help 2>&1 | grep -q "break-system-packages"; then
  PIP_ARGS="${PIP_ARGS} --break-system-packages"
fi
"${PYTHON}" -m pip install ${PIP_ARGS} -r "${SCRIPT_DIR}/requirements.txt"
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

# Check Node.js (optional but recommended)
if command -v node &>/dev/null; then
    NODE_VER=$(node --version 2>/dev/null || echo "unknown")
    echo "[OK] Node.js found: ${NODE_VER}"
else
    echo "[WARN] Node.js not found — some features may be limited"
    echo "       Install: https://nodejs.org/ or: sudo apt install nodejs"
fi

# Scan for AI CLI tools
echo ""
echo "=== AI CLI Detection ==="
_cli_found=0
_cli_list=""
for cli_name in claude codex gemini qwen; do
    cli_path="$(command -v "${cli_name}" 2>/dev/null || true)"
    if [[ -n "${cli_path}" ]]; then
        if [[ "${cli_name}" == "claude" ]]; then
            echo "[OK] ${cli_name} (recommended) — ${cli_path}"
        else
            echo "[OK] ${cli_name} — ${cli_path}"
        fi
        _cli_found=$((_cli_found + 1))
        _cli_list="${_cli_list:+${_cli_list}, }${cli_name}"
    else
        echo "[--] ${cli_name} — not found"
    fi
done
echo ""
if [[ "${_cli_found}" -eq 0 ]]; then
    echo "WARNING: No AI CLI found. You need at least one to run agents."
    echo "  Install Claude Code: npm install -g @anthropic-ai/claude-code"
    echo "  Install Codex:       npm install -g @openai/codex"
elif [[ "${_cli_found}" -eq 1 ]]; then
    echo "Detected ${_cli_found} AI CLI: ${_cli_list}"
else
    echo "Detected ${_cli_found} AI CLIs: ${_cli_list}"
    echo "Claude Code is the recommended default engine."
fi

echo ""
echo "=== Installation complete ==="
echo ""

# Auto-start platform unless --no-start was passed
if [[ "${BRIDGE_NO_START:-0}" != "1" ]] && [[ " $* " != *" --no-start "* ]]; then
    echo "Starting Bridge platform..."
    echo ""
    if "${BACKEND_DIR}/start_platform.sh"; then
        echo ""
        echo "Bridge is running! Buddy is ready to greet you."
        echo ""
        echo "  Open in your browser:  http://127.0.0.1:9111"
        echo "  On your phone:         http://<your-ip>:9111/mobile_buddy.html"
    else
        echo ""
        echo "Platform start failed. You can start manually:"
        echo "  cd ${SCRIPT_DIR} && ./Backend/start_platform.sh"
    fi
else
    echo "Next steps:"
    echo ""
    echo "  1. Start the platform:"
    echo "     cd ${SCRIPT_DIR} && ./Backend/start_platform.sh"
    echo ""
    echo "  2. Open in your browser:"
    echo "     http://127.0.0.1:9111"
    echo ""
    echo "  3. On your phone (same network):"
    echo "     http://<your-ip>:9111/mobile_buddy.html"
fi
echo ""
echo "Or with Docker:"
echo "  cd ${SCRIPT_DIR} && docker compose up --build"
echo ""
echo "Deploy to a server (auto-HTTPS):"
echo "  ./Backend/deploy_server.sh your-domain.com"
echo ""
echo "Optional WhatsApp setup:"
echo "  ${SCRIPT_DIR}/docs/whatsapp-setup.md"
echo ""
echo "Optional Telegram setup:"
echo "  ${SCRIPT_DIR}/docs/telegram-setup.md"
