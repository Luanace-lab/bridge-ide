# Bridge ACE — Server Deployment Guide

Deploy Bridge ACE on a VPS with Docker, Caddy (auto-TLS), and your own domain.

## Prerequisites

- VPS with Docker + Docker Compose (Ubuntu 22.04+ recommended)
- Domain pointing to your VPS IP (e.g. `bridgeide.com` → `A 1.2.3.4`)
- Ports 80 and 443 open in firewall

## 1. Clone and Configure

```bash
git clone https://github.com/Luanace-lab/bridge-ide.git
cd bridge-ide
```

## 2. Set Your Domain

```bash
export BRIDGE_DOMAIN=bridgeide.com
```

## 3. Start with Caddy (Remote Mode)

```bash
BRIDGE_DOMAIN=bridgeide.com docker compose --profile remote up -d
```

This starts:
- **bridge-server**: HTTP API (:9111) + WebSocket (:9112) — internal only
- **caddy**: Reverse proxy with auto-TLS via Let's Encrypt (:80, :443)

## 4. Get Your Access Token

On first start, a token is auto-generated and printed to Docker logs:

```bash
docker compose logs bridge-server | grep "User Token"
```

Save this token — it's required for API access and agent authentication.

## 5. Connect Local Agents

On your local machine, set the server URL:

```bash
export BRIDGE_SERVER_URL=https://bridgeide.com
```

Then start agents as usual. The MCP bridge will connect to the remote server automatically.

### Claude Code Agent

In your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "bridge": {
      "command": "python3",
      "args": ["/path/to/bridge-ide/Backend/bridge_mcp.py"],
      "env": {
        "BRIDGE_SERVER_URL": "https://bridgeide.com"
      }
    }
  }
}
```

## 6. Custom Origins (Optional)

If agents connect from specific domains, add them:

```bash
# In docker-compose.yml or .env
BRIDGE_ALLOWED_ORIGINS=https://bridgeide.com,https://app.bridgeide.com
```

## Architecture

```
Local Machine                    VPS (Docker)
+------------------+            +---------------------------+
| AI CLI Sessions  |  HTTPS/   | Caddy (:443)              |
| - claude         | -------> |   → bridge-server (:9111)  |
| - codex          |  WSS     |   → websocket (:9112)      |
|                  |           |                           |
| bridge_mcp.py    |           | Bridge Server             |
| BRIDGE_SERVER_URL|---------->| - Messages, Tasks, State  |
+------------------+           | - Frontend (HTML/JS)      |
                               | - Knowledge Vault         |
                               +---------------------------+
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BRIDGE_DOMAIN` | `localhost` | Domain for Caddy auto-TLS |
| `BRIDGE_SERVER_URL` | _(unset)_ | Remote server URL for local agents |
| `BRIDGE_ALLOWED_ORIGINS` | _(unset)_ | Extra CORS origins (comma-separated) |
| `BRIDGE_HTTP_HOST` | `127.0.0.1` | HTTP bind address (`0.0.0.0` in Docker) |
| `BRIDGE_WS_HOST` | same as HTTP | WebSocket bind address |
| `PORT` | `9111` | HTTP API port |
| `WS_PORT` | `9112` | WebSocket port |

## Local-Only Mode (Default)

Without `--profile remote`, only the bridge-server starts (no Caddy):

```bash
docker compose up -d
# Access at http://localhost:9111
```

## Troubleshooting

**Caddy won't start**: Ensure ports 80/443 are free and your domain's DNS points to the VPS IP.

**Token auth fails**: Check `docker compose logs bridge-server` for the generated token. Pass it via `X-Bridge-Token` header or in `~/.config/bridge/tokens.json`.

**WebSocket disconnects**: Verify that your firewall allows HTTPS (443). Caddy handles TLS termination and WebSocket upgrade automatically.

**Agents can't connect**: Ensure `BRIDGE_SERVER_URL` is set to the full HTTPS URL (e.g. `https://bridgeide.com`, not just the domain).
