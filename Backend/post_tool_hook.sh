#!/bin/bash
# post_tool_hook.sh — PostToolUse Hook fuer Bridge-Agents
#
# Drei Funktionen:
# 1. Periodische Erinnerung an bridge_receive (alle 15 Tool-Calls)
# 2. Periodische Erinnerung an bridge_task_queue (alle 30 Tool-Calls)
# 3. Context-Warnung bei kritischem Context-Level (>95%)
#
# Signal-Datei wird von context_statusline.sh geschrieben.

# --- Hook-Input einlesen ---
HOOK_INPUT=$(cat 2>/dev/null) || HOOK_INPUT="{}"
SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null)

# --- Configurable via environment (no more hardcoded values) ---
BRIDGE_PORT="${BRIDGE_PORT:-9111}"
BRIDGE_MANAGER_ID="${BRIDGE_MANAGER_ID:-ordo}"

# --- R6: Restart-WARN Check (VOR Context-Check) ---
RESTART_WARN_FILE="/tmp/bridge_restart_warn_${SESSION_ID:-global}"
if [ -f "$RESTART_WARN_FILE" ]; then
    WARN_SECS=$(cat "$RESTART_WARN_FILE" 2>/dev/null || echo "60")
    echo "{\"decision\":\"approve\",\"message\":\"[RESTART WARN] Server-Restart in ${WARN_SECS}s! PFLICHT: 1) CONTEXT_BRIDGE.md schreiben (Status, offene Tasks, naechste Schritte). 2) Memory/MEMORY.md aktualisieren. 3) bridge_activity(action='checkpoint_saved') ausfuehren. Dein Zustand wird sonst verloren!\"}"
    exit 0
fi

# --- Context-Critical Check ---
# Nur eigene Signal-Dateien pruefen — keine Cross-Contamination
if [ -n "$SESSION_ID" ]; then
    SIGNAL_80="/tmp/context_warn_80_${SESSION_ID}"
    SIGNAL_90="/tmp/context_warn_90_${SESSION_ID}"
    SIGNAL_FILE="/tmp/context_critical_${SESSION_ID}"

    # 95% — Critical (bestehend + Memory-Flush Pflicht)
    if [ -f "$SIGNAL_FILE" ]; then
        PCT=$(cat "$SIGNAL_FILE" 2>/dev/null)
        if [ -n "$PCT" ]; then
            AGENT_NAME=$(echo "$HOOK_INPUT" | jq -r '.cwd // "unknown"' 2>/dev/null | grep -oP '\.agent_sessions/\K[^/]+' || echo "unknown")
            curl -sf -X POST "http://127.0.0.1:${BRIDGE_PORT}/send" \
                -H "Content-Type: application/json" \
                -d "{\"from\":\"system\",\"to\":\"${BRIDGE_MANAGER_ID}\",\"content\":\"CONTEXT WARNUNG: Agent '${AGENT_NAME}' hat ${PCT}% Context belegt. Agent wird zum Compact aufgefordert.\"}" \
                >/dev/null 2>&1 &
            echo "{\"decision\":\"approve\",\"message\":\"CONTEXT KRITISCH (${PCT}% belegt)! Du MUSST jetzt: 1) Memory aktualisieren (PFLICHT). 2) CONTEXT_BRIDGE.md schreiben mit komplettem Status. 3) bridge_send an manager mit Pfad. 4) /compact ausfuehren. Bei Ueberlauf geht dein gesamter Kontext verloren.\"}"
            exit 0
        fi
    fi

    # 90% — Dringende Warnung
    if [ -f "$SIGNAL_90" ]; then
        PCT=$(cat "$SIGNAL_90" 2>/dev/null)
        if [ -n "$PCT" ]; then
            echo "{\"decision\":\"approve\",\"message\":\"Context bei ${PCT}%! SOFORT Memory aktualisieren und CONTEXT_BRIDGE.md schreiben. Naechster Compact droht.\"}"
            exit 0
        fi
    fi

    # 80% — Hinweis
    if [ -f "$SIGNAL_80" ]; then
        PCT=$(cat "$SIGNAL_80" 2>/dev/null)
        if [ -n "$PCT" ]; then
            echo "{\"decision\":\"approve\",\"message\":\"Context bei ${PCT}%. Bitte Memory und CONTEXT_BRIDGE.md aktualisieren.\"}"
            exit 0
        fi
    fi
fi

# --- Periodische bridge_receive Erinnerung ---
COUNTER_FILE="/tmp/bridge_tool_counter_${PPID}"

# Counter lesen oder initialisieren (robust gegen leere/korrupte Datei)
COUNT=0
if [ -f "$COUNTER_FILE" ]; then
    COUNT=$(cat "$COUNTER_FILE" 2>/dev/null)
    # Sicherstellen dass COUNT eine Zahl ist
    case "$COUNT" in
        ''|*[!0-9]*) COUNT=0 ;;
    esac
fi

# Counter erhoehen
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNTER_FILE" 2>/dev/null

# Alle 30 Aufrufe: Task-Queue pruefen, alle 15: bridge_receive
if [ $((COUNT % 30)) -eq 0 ]; then
    echo '{"decision":"approve","message":"[Task-Reminder] Pruefe offene Tasks: bridge_task_queue(state=\"created\"). Unclaimed Tasks claimen mit bridge_task_claim. Dann bridge_receive() fuer Nachrichten."}'
elif [ $((COUNT % 15)) -eq 0 ]; then
    echo '{"decision":"approve","message":"[Bridge-Reminder] Du hast 15 Tool-Calls gemacht ohne bridge_receive zu pruefen. Rufe jetzt bridge_receive() auf um neue Nachrichten zu empfangen."}'
else
    echo '{"decision":"approve"}'
fi
