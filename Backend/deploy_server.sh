#!/usr/bin/env bash
# Bridge IDE — One-Click Server Deployment
# Usage: ./deploy_server.sh <domain>
# Example: ./deploy_server.sh bridgeide.com
set -euo pipefail

# ── Colors ──────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[bridge]${NC} $*"; }
ok()    { echo -e "${GREEN}[  ok ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

# ── Domain ──────────────────────────────────────────────
DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
    echo ""
    echo "  Bridge IDE — Server Deployment"
    echo "  Usage: $0 <domain>"
    echo "  Example: $0 bridgeide.com"
    echo ""
    exit 1
fi

# ── Project Root (one level up from Backend/) ──────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
info "Project root: $PROJECT_ROOT"

# ── Prerequisites ───────────────────────────────────────
info "Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    fail "Docker is not installed. Install: https://docs.docker.com/get-docker/"
fi
ok "Docker found: $(docker --version | head -1)"

if docker compose version &>/dev/null; then
    COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE="docker-compose"
else
    fail "Docker Compose not found. Install: https://docs.docker.com/compose/install/"
fi
ok "Compose found: $($COMPOSE version | head -1)"

if ! docker info &>/dev/null 2>&1; then
    fail "Docker daemon is not running. Start it first."
fi
ok "Docker daemon running"

# ── Port Check ──────────────────────────────────────────
for port in 80 443; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || \
       netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        warn "Port $port is already in use. Caddy needs ports 80+443 for TLS."
    fi
done

# ── Deploy ──────────────────────────────────────────────
info "Deploying Bridge IDE for domain: $DOMAIN"

export BRIDGE_DOMAIN="$DOMAIN"

# Build and start with remote profile (includes Caddy)
$COMPOSE --profile remote up -d --build

ok "Containers started"

# ── Wait for Health ─────────────────────────────────────
info "Waiting for server to become healthy..."
MAX_WAIT=60
ELAPSED=0
while [[ $ELAPSED -lt $MAX_WAIT ]]; do
    if curl -fs http://127.0.0.1:9111/status >/dev/null 2>&1; then
        ok "Server is healthy"
        break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    printf "."
done
echo ""

if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    warn "Server did not become healthy within ${MAX_WAIT}s"
    warn "Check logs: $COMPOSE --profile remote logs bridge-server"
fi

# ── Show Tokens (first start only) ─────────────────────
info "Checking for first-start tokens..."
TOKENS=$($COMPOSE logs bridge-server 2>&1 | grep -A5 "First Start Token Setup" || true)
if [[ -n "$TOKENS" ]]; then
    echo ""
    echo "$TOKENS"
    echo ""
    warn "Save these tokens now — they won't be shown again!"
else
    info "Tokens were generated on a previous start. Check: docker volume inspect bridge-tokens"
fi

# ── Result ──────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Bridge IDE is live!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  Local:   http://127.0.0.1:9111"
echo "  Public:  https://$DOMAIN"
echo "  WS:      wss://$DOMAIN/ws"
echo ""
echo "  Logs:    $COMPOSE --profile remote logs -f"
echo "  Stop:    $COMPOSE --profile remote down"
echo "  Restart: $COMPOSE --profile remote restart"
echo ""
echo -e "${GREEN}============================================${NC}"
