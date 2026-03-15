#!/bin/bash
# context_statusline.sh — Agent-Statusline mit Context-Monitoring
#
# Zeigt Model, Context-Prozent und Agent-Bridge-Status.
# Bei >95% Context-Nutzung: Schreibt Signal-Datei fuer den PostToolUse-Hook.
#
# Konfiguration in Agent-Settings:
# "statusLine": {"type": "command", "command": "/path/to/context_statusline.sh"}

input=$(cat 2>/dev/null) || input="{}"

# Felder extrahieren (mit Fallback bei fehlerhaftem JSON)
MODEL=$(echo "$input" | jq -r '.model.display_name // "?"' 2>/dev/null) || MODEL="?"
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' 2>/dev/null | cut -d. -f1) || PCT=0
REMAINING=$(echo "$input" | jq -r '.context_window.remaining_percentage // 100' 2>/dev/null | cut -d. -f1) || REMAINING=100
SESSION_ID=$(echo "$input" | jq -r '.session_id // "unknown"' 2>/dev/null) || SESSION_ID="unknown"
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0' 2>/dev/null) || COST=0
# Sicherstellen dass PCT eine Zahl ist
case "$PCT" in ''|*[!0-9]*) PCT=0 ;; esac

# Farben
RED='\033[31m'
YELLOW='\033[33m'
GREEN='\033[32m'
CYAN='\033[36m'
RESET='\033[0m'

# Context-Farbe bestimmen
if [ "$PCT" -ge 95 ]; then
    CTX_COLOR="$RED"
    CTX_ICON="!!"
elif [ "$PCT" -ge 80 ]; then
    CTX_COLOR="$YELLOW"
    CTX_ICON="!"
else
    CTX_COLOR="$GREEN"
    CTX_ICON=""
fi

# Progress-Bar
BAR_WIDTH=10
FILLED=$((PCT * BAR_WIDTH / 100))
EMPTY=$((BAR_WIDTH - FILLED))
BAR=""
[ "$FILLED" -gt 0 ] && BAR=$(printf "%${FILLED}s" | tr ' ' '█')
[ "$EMPTY" -gt 0 ] && BAR="${BAR}$(printf "%${EMPTY}s" | tr ' ' '░')"

# Statusline ausgeben
COST_FMT=$(LC_NUMERIC=C printf '$%.2f' "$COST")
printf '%b' "${CYAN}[$MODEL]${RESET} ${CTX_COLOR}${BAR} ${PCT}%${CTX_ICON}${RESET} | ${YELLOW}${COST_FMT}${RESET}\n"

# S4: Context threshold signals (80%, 90%, 95%)
SIGNAL_80="/tmp/context_warn_80_${SESSION_ID}"
SIGNAL_90="/tmp/context_warn_90_${SESSION_ID}"
SIGNAL_FILE="/tmp/context_critical_${SESSION_ID}"

if [ "$PCT" -ge 95 ] 2>/dev/null; then
    echo "$PCT" > "$SIGNAL_FILE" 2>/dev/null
elif [ -f "$SIGNAL_FILE" ]; then
    rm -f "$SIGNAL_FILE" 2>/dev/null
fi
if [ "$PCT" -ge 90 ] 2>/dev/null; then
    echo "$PCT" > "$SIGNAL_90" 2>/dev/null
elif [ -f "$SIGNAL_90" ]; then
    rm -f "$SIGNAL_90" 2>/dev/null
fi
if [ "$PCT" -ge 80 ] 2>/dev/null; then
    echo "$PCT" > "$SIGNAL_80" 2>/dev/null
elif [ -f "$SIGNAL_80" ]; then
    rm -f "$SIGNAL_80" 2>/dev/null
fi

# Write PCT for watcher to read (per tmux session)
if [ -n "$TMUX" ]; then
    _SESSION=$(tmux display-message -p '#{session_name}' 2>/dev/null)
    if [ -n "$_SESSION" ]; then
        echo "$PCT" > "/tmp/context_pct_${_SESSION}" 2>/dev/null
    fi
fi
