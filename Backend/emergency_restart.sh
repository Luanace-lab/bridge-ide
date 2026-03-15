#!/bin/bash
# EMERGENCY RESTART — Alle kritischen Bridge-Prozesse neustarten
# Verwendung: bash emergency_restart.sh
# Von: Ordo (2026-03-01) — Leos Notfall-Knopf
#
# Startet: Bridge Server, Watcher, Forwarder, WhatsApp Watcher
# Optional: --kill-zombies (toetet alte Playwright-Prozesse)

set -e

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="/tmp"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== BRIDGE EMERGENCY RESTART ===${NC}"
echo "$(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Kill Playwright-Zombies wenn --kill-zombies Flag
if [[ "$1" == "--kill-zombies" ]]; then
    echo -e "${RED}Killing Playwright zombie processes...${NC}"
    pkill -f "playwright-mcp" 2>/dev/null && echo "  Playwright processes killed." || echo "  No Playwright processes found."
    echo ""
fi

# 1. Bridge Server
echo -e "${YELLOW}[1/4] Bridge Server (port 9111)...${NC}"
if curl -s http://127.0.0.1:9111/health > /dev/null 2>&1; then
    echo -e "  ${GREEN}ALREADY RUNNING${NC}"
else
    echo -e "  ${RED}DOWN — restarting...${NC}"
    cd "$BACKEND_DIR"
    nohup python3 -u server.py >> "$LOG_DIR/bridge_server.log" 2>&1 &
    sleep 3
    if curl -s http://127.0.0.1:9111/health > /dev/null 2>&1; then
        echo -e "  ${GREEN}STARTED (PID $!)${NC}"
    else
        echo -e "  ${RED}FAILED TO START${NC}"
    fi
fi
echo ""

# 2. Bridge Watcher
echo -e "${YELLOW}[2/4] Bridge Watcher...${NC}"
WATCHER_PID=$(pgrep -f "python3.*bridge_watcher.py" 2>/dev/null | head -1)
if [[ -n "$WATCHER_PID" ]]; then
    echo -e "  ${GREEN}ALREADY RUNNING (PID $WATCHER_PID)${NC}"
else
    echo -e "  ${RED}DOWN — restarting...${NC}"
    cd "$BACKEND_DIR"
    nohup python3 -u bridge_watcher.py >> "$LOG_DIR/bridge_watcher.log" 2>&1 &
    sleep 2
    WATCHER_PID=$(pgrep -f "python3.*bridge_watcher.py" 2>/dev/null | head -1)
    if [[ -n "$WATCHER_PID" ]]; then
        echo -e "  ${GREEN}STARTED (PID $WATCHER_PID)${NC}"
    else
        echo -e "  ${RED}FAILED TO START${NC}"
    fi
fi
echo ""

# 3. Output Forwarder
echo -e "${YELLOW}[3/4] Output Forwarder...${NC}"
FWD_PID=$(pgrep -f "python3.*output_forwarder.py" 2>/dev/null | head -1)
if [[ -n "$FWD_PID" ]]; then
    echo -e "  ${GREEN}ALREADY RUNNING (PID $FWD_PID)${NC}"
else
    echo -e "  ${RED}DOWN — restarting...${NC}"
    cd "$BACKEND_DIR"
    nohup python3 -u output_forwarder.py >> "$LOG_DIR/output_forwarder.log" 2>&1 &
    sleep 2
    FWD_PID=$(pgrep -f "python3.*output_forwarder.py" 2>/dev/null | head -1)
    if [[ -n "$FWD_PID" ]]; then
        echo -e "  ${GREEN}STARTED (PID $FWD_PID)${NC}"
    else
        echo -e "  ${RED}FAILED TO START${NC}"
    fi
fi
echo ""

# 4. WhatsApp Watcher
echo -e "${YELLOW}[4/4] WhatsApp Watcher...${NC}"
WA_PID=$(pgrep -f "python3.*whatsapp_watcher.py" 2>/dev/null | head -1)
if [[ -n "$WA_PID" ]]; then
    echo -e "  ${GREEN}ALREADY RUNNING (PID $WA_PID)${NC}"
else
    echo -e "  ${RED}DOWN — restarting...${NC}"
    cd "$BACKEND_DIR"
    nohup python3 -u whatsapp_watcher.py >> "$LOG_DIR/whatsapp_watcher.log" 2>&1 &
    sleep 2
    WA_PID=$(pgrep -f "python3.*whatsapp_watcher.py" 2>/dev/null | head -1)
    if [[ -n "$WA_PID" ]]; then
        echo -e "  ${GREEN}STARTED (PID $WA_PID)${NC}"
    else
        echo -e "  ${RED}FAILED TO START${NC}"
    fi
fi
echo ""

# Status-Zusammenfassung
echo -e "${YELLOW}=== STATUS ===${NC}"
echo -e "Server:    $(curl -s http://127.0.0.1:9111/health > /dev/null 2>&1 && echo -e "${GREEN}OK${NC}" || echo -e "${RED}DOWN${NC}")"
echo -e "Watcher:   $(pgrep -f "python3.*bridge_watcher.py" > /dev/null 2>&1 && echo -e "${GREEN}OK${NC}" || echo -e "${RED}DOWN${NC}")"
echo -e "Forwarder: $(pgrep -f "python3.*output_forwarder.py" > /dev/null 2>&1 && echo -e "${GREEN}OK${NC}" || echo -e "${RED}DOWN${NC}")"
echo -e "WA Watch:  $(pgrep -f "python3.*whatsapp_watcher.py" > /dev/null 2>&1 && echo -e "${GREEN}OK${NC}" || echo -e "${RED}DOWN${NC}")"
echo ""
echo -e "${GREEN}Emergency restart complete.${NC}"
