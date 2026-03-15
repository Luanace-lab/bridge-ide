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

exec python3 -u "${BACKEND_DIR}/server.py" "$@"
