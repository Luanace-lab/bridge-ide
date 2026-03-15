#!/bin/bash
# stop_hook.sh — Persistenter Agent Stop-Hook mit Idle-Detection
# Blockiert freiwillige Stops, laesst erzwungene durch (API-Limit, Context-Erschoepfung)
# V2: Idle-Counter verhindert endloses Polling bei leerer Queue
# Ref: KNOWN_ISSUES.md ISSUE-001, ISSUE-002

INPUT=$(cat 2>/dev/null) || INPUT=""

# Robust JSON parsing with explicit error handling
if [ -z "$INPUT" ]; then
    echo '{"continue":false,"stopReason":"STOP BLOCKIERT (leerer Hook-Input). bridge_receive() aufrufen und weiterarbeiten."}'
    exit 0
fi

STOP_ACTIVE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('stop_hook_active', False))" 2>/dev/null)
PARSE_OK=$?

if [ $PARSE_OK -ne 0 ]; then
    echo "{\"continue\":true,\"stopReason\":\"JSON-Parse-Fehler im Stop-Hook. Agent wird durchgelassen.\"}" >&2
    echo '{"continue":true}'
    exit 0
fi

if [ "$STOP_ACTIVE" = "True" ]; then
    # Vorheriger Block war erfolglos (API-Limit, Context voll, etc.) → durchlassen
    echo '{"continue":true}'
    exit 0
fi

# --- IDLE-DETECTION (ISSUE-002 V2 Fix) ---
# Track consecutive stop attempts per agent via temp file
AGENT_ID="${CLAUDE_AGENT_ID:-unknown}"
IDLE_FILE="/tmp/bridge_idle_counter_${AGENT_ID}"
MAX_IDLE=5  # Nach 5 blocked stops: Standby-Modus

# Read current counter
IDLE_COUNT=0
if [ -f "$IDLE_FILE" ]; then
    IDLE_COUNT=$(cat "$IDLE_FILE" 2>/dev/null || echo 0)
fi
IDLE_COUNT=$((IDLE_COUNT + 1))
echo "$IDLE_COUNT" > "$IDLE_FILE"

if [ "$IDLE_COUNT" -ge "$MAX_IDLE" ]; then
    # Agent hat MAX_IDLE-mal versucht zu stoppen — keine Arbeit da.
    # Mode auf standby setzen und Agent durchlassen (controlled stop).
    curl -s -X PATCH "http://127.0.0.1:9111/agents/${AGENT_ID}/mode" \
        -H "Content-Type: application/json" \
        -d "{\"mode\":\"standby\",\"from\":\"system\"}" >/dev/null 2>&1
    # Reset counter
    echo "0" > "$IDLE_FILE"
    # Let the agent stop gracefully — it will be restarted when needed
    echo '{"continue":true,"stopReason":"Idle-Detection: Keine Arbeit nach '"$MAX_IDLE"' Versuchen. Modus auf standby gesetzt. Kontrollierter Stop."}'
    exit 0
fi

# Calculate backoff wait time based on idle count
WAIT_SECONDS=$((10 * IDLE_COUNT))  # 10s, 20s, 30s, 40s
if [ "$WAIT_SECONDS" -gt 60 ]; then
    WAIT_SECONDS=60
fi

# Normaler Fall: Agent will freiwillig stoppen → blockieren mit Backoff
echo "{\"continue\":false,\"stopReason\":\"STOP BLOCKIERT. Du bist ein persistenter Agent. WICHTIG: ${WAIT_SECONDS} Sekunden warten (Idle-Zaehler: ${IDLE_COUNT}/${MAX_IDLE}), dann: 1) bridge_receive() aufrufen. 2) bridge_task_queue(state='created', limit=50) pruefen. 3) Wenn beides leer: KURZ warten und erneut pruefen. Nicht in Endlosschleife — Wartezeit einhalten!\"}"
