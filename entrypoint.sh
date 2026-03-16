#!/usr/bin/env bash
set -euo pipefail

BACKEND_DIR="/app/Backend"

# Initialize data files if missing
if [[ ! -f "${BACKEND_DIR}/team.json" ]]; then
    echo '{"agents":[],"teams":[],"hierarchy":{"levels":[]}}' > "${BACKEND_DIR}/team.json"
    echo "[bridge] Initialized team.json"
fi

if [[ ! -f "${BACKEND_DIR}/automations.json" ]]; then
    echo '{"automations":[]}' > "${BACKEND_DIR}/automations.json"
    echo "[bridge] Initialized automations.json"
fi

# Ensure directories exist
mkdir -p "${BACKEND_DIR}/logs" "${BACKEND_DIR}/pids" "${BACKEND_DIR}/messages"

# Auto-generate tokens.json on first Docker start
TOKENS_FILE="${TOKENS_FILE:-/data/tokens.json}"
if [[ ! -f "${TOKENS_FILE}" ]]; then
    USER_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > "${TOKENS_FILE}" <<TOKEOF
{"user_token": "${USER_TOKEN}", "admin_token": "${ADMIN_TOKEN}"}
TOKEOF
    echo ""
    echo "============================================"
    echo "  Bridge IDE — First Start Token Setup"
    echo "============================================"
    echo "  User Token:  ${USER_TOKEN}"
    echo "  Admin Token: ${ADMIN_TOKEN}"
    echo ""
    echo "  Save these tokens! They won't be shown again."
    echo "  Config: ${TOKENS_FILE}"
    echo "============================================"
    echo ""
else
    echo "[bridge] tokens.json exists — not overwriting."
fi

# Make tokens available to the server
export BRIDGE_TOKENS_FILE="${TOKENS_FILE}"

exec python3 -u "${BACKEND_DIR}/server.py" "$@"
