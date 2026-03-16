# Bridge IDE — Server Deployment Strategy

**Stand:** 2026-03-16
**Autor:** Viktor (Systemarchitekt)
**Status:** Entwurf — Freigabe durch Leo ausstehend

---

## 1. Executive Summary

Bridge IDE laeuft aktuell ausschliesslich lokal. Fuer eine Server-Anbindung existiert bereits ein Docker-Setup (Dockerfile, docker-compose.yml), das den Server containerisiert — jedoch ohne Agent-Lifecycle, ohne TLS und mit hardcodierten Localhost-Origins. Die empfohlene Strategie ist **Szenario A: Server remote, Agents lokal**. Der zentrale Bridge-Server (HTTP + WebSocket) laeuft auf einem VPS oder Cloud-Server, waehrend die AI-Agent-Sessions weiterhin lokal beim User laufen und sich ueber das Netzwerk verbinden. Dies erfordert 5-6 gezielte Aenderungen, kein Redesign.

---

## 2. Drei Szenarien

### Szenario A: Server Remote, Agents Lokal

```
User's Machine                          VPS / Cloud
+---------------------------+           +---------------------------+
| AI CLI Sessions (tmux)    |           | Bridge Server (Docker)    |
| - claude                  |  HTTPS    | - server.py (:9111)       |
| - codex                   | -------> | - websocket_server (:9112)|
| - gemini                  |  WSS     | - Frontend (HTML/JS)      |
|                           |           | - Knowledge Vault         |
| bridge_mcp.py (stdio)     |           | - Messages, Tasks, State  |
| -> HTTP/WS zum Server ----|---------->|                           |
+---------------------------+           +---------------------------+
                                               |
Browser (beliebig) ----- HTTPS/WSS ----------->|
```

**Vorteile:**
- Geringstes Risiko, geringstes Aufwand
- User behaelt volle Kontrolle ueber AI-API-Keys (Claude, OpenAI, etc.)
- Kein AI-CLI auf dem Server noetig
- Docker-Image existiert bereits
- Server ist stateless bezueglich Agent-Sessions
- Multi-User moeglich (jeder User laeuft seine eigenen Agents lokal)

**Nachteile:**
- User muss lokal AI CLIs installiert haben
- bridge_mcp.py muss HTTP statt stdio nutzen (oder HTTP-Relay)
- Latenz: Jede MCP-Nachricht geht uebers Netzwerk
- User-Maschine muss eingeschaltet sein fuer Agent-Betrieb

### Szenario B: Full Remote (Alles auf VPS)

```
VPS / Cloud
+------------------------------------------+
| Bridge Server (Docker)                   |
| - server.py, websocket_server.py         |
| - tmux_manager.py                        |
| - tmux Sessions (acw_{agent_id})         |
| - AI CLIs (claude, codex, etc.)          |
| - bridge_mcp.py (stdio, lokal)           |
| - Frontend                               |
+------------------------------------------+
        |
Browser (User) -- HTTPS/WSS -->
```

**Vorteile:**
- User braucht NUR einen Browser
- Agents laufen 24/7 (kein lokaler Rechner noetig)
- Zentrales Management
- MCP bleibt stdio (keine Transport-Aenderung)

**Nachteile:**
- AI CLIs muessen auf dem Server installiert und authentifiziert werden
- Jede CLI braucht eigene API-Keys/OAuth-Tokens auf dem Server
- Speicherverbrauch: ~500MB RAM pro Agent-Instanz
- Claude Code OAuth funktioniert headless nicht ohne Workaround
- Credential-Management wird komplex (alle Keys auf dem Server)
- Single Point of Failure
- Datenschutz: Alle Daten auf fremdem Server

### Szenario C: Hybrid mit SSH-Tunnel

```
User's Machine          SSH Tunnel          VPS
+-------------+      +------------+      +------------------+
| Browser     |----->| SSH -L     |----->| Bridge Server    |
|             |      | Port 9111  |      | tmux Sessions    |
+-------------+      +------------+      | AI CLIs          |
                                         +------------------+
```

**Vorteile:**
- Kein TLS/Reverse-Proxy noetig (SSH uebernimmt Verschluesselung)
- Agents laufen 24/7 auf dem Server

**Nachteile:**
- Alle Nachteile von Szenario B
- Zusaetzlich: SSH-Tunnel-Management fuer jeden User
- Nicht user-freundlich ("kein Stress" verletzt)

---

## 3. Empfehlung: Szenario A

**Szenario A ist der richtige Weg.** Gruende:

1. **Minimaler Aufwand**: 5-6 gezielte Aenderungen, kein Redesign
2. **Leo-Kriterium "kein Stress"**: User installiert lokal, Server laeuft remote — keine CLI-Auth auf fremdem Server
3. **Leo-Kriterium "automatisch"**: Docker-Deploy ist ein `docker compose up`
4. **Datenschutz**: AI-Keys bleiben beim User, nur Messages/Tasks auf dem Server
5. **Multi-User-faehig**: Jeder User laeuft seine Agents lokal, shared Server fuer Koordination
6. **Existierende Infrastruktur**: Dockerfile, docker-compose.yml, Auth-System — alles da

---

## 4. Aenderungsliste (Szenario A)

| # | Datei | Aenderung | Aufwand |
|---|-------|-----------|---------|
| 1 | `server.py:757` | ALLOWED_ORIGINS via Env-Var `BRIDGE_ALLOWED_ORIGINS` (kommasepariert). Fallback auf aktuelle localhost-Liste. | S |
| 2 | `server_http_io.py:58` | CSP `connect-src` dynamisch aus Server-Origin ableiten statt hardcoded `ws://127.0.0.1:9112` | S |
| 3 | `Frontend/*.html` (chat.html, control_center.html, mobile_*.html) | WebSocket-URL aus `window.location` ableiten statt hardcoded. `ws://` → `wss://` wenn HTTPS. | M |
| 4 | `docker-compose.yml` | Caddy-Service als Reverse-Proxy hinzufuegen. Auto-TLS via Let's Encrypt. Caddyfile fuer HTTP→HTTPS + WS-Proxy. | M |
| 5 | `bridge_mcp.py` | HTTP-Transport-Option: `BRIDGE_SERVER_URL` Env-Var. Wenn gesetzt, HTTP statt stdio. Oder: separater `bridge_mcp_remote.py` Wrapper. | M |
| 6 | Doku | `docs/server-deployment.md`: Setup-Anleitung fuer VPS (Docker + Caddy + Domain + DNS). | S |
| 7 | `docker-compose.yml` + `entrypoint.sh` | Token-Generierung bei erstem Start: `tokens.json` auto-erstellen wenn nicht vorhanden, Token in Logs ausgeben. | S |

**Gesamtaufwand: ~2-3 Arbeitstage**

---

## 5. Architekturskizze (Szenario A, Zielzustand)

```
                    Internet
                       |
              +--------+--------+
              |   Caddy (TLS)   |
              |   :443 → :9111  |
              |   wss → ws:9112 |
              +--------+--------+
                       |
         +-------------+-------------+
         |                           |
  +------+------+          +---------+---------+
  | HTTP Server |          | WebSocket Server  |
  | :9111       |          | :9112             |
  | (server.py) |          | (websocket_server)|
  +------+------+          +---------+---------+
         |                           |
  +------+---------------------------+---------+
  | Backend Core (Docker Container)            |
  | - Messages, Tasks, Teams, State            |
  | - Knowledge Vault                          |
  | - Daemons (health, auto_assign, etc.)      |
  | - Frontend (static HTML/JS/CSS)            |
  +--------------------------------------------+
         ^                ^
         |  HTTPS/WSS     |  HTTPS/WSS
         |                |
  +------+------+  +------+------+
  | User A      |  | User B      |
  | (lokal)     |  | (lokal)     |
  | - claude    |  | - codex     |
  | - codex     |  | - claude    |
  | - MCP→HTTP  |  | - MCP→HTTP  |
  +-------------+  +-------------+
```

---

## 6. Aufwandsschaetzung

| Aenderung | Aufwand | Risiko | Abhaengigkeiten |
|-----------|---------|--------|-----------------|
| ALLOWED_ORIGINS konfigurierbar | S (1h) | Niedrig | Keine |
| CSP dynamisch | S (1h) | Niedrig | #1 |
| Frontend WS-URL dynamisch | M (3-4h) | Mittel (6+ HTML-Dateien) | Keine |
| Caddy Reverse-Proxy | M (2-3h) | Niedrig | Domain + DNS |
| MCP HTTP-Transport | M (4-6h) | Mittel (neuer Transport-Layer) | #1 |
| Doku | S (1-2h) | Niedrig | #1-#5 |
| Token Auto-Generierung | S (1h) | Niedrig | Keine |

**S** = Small (<2h), **M** = Medium (2-6h), **L** = Large (>6h)

---

## 7. Offene Fragen fuer Leo

1. **Domain**: Soll Bridge auf einer eigenen Domain laufen? (z.B. bridge.example.com) Oder reicht IP + Port?
2. **Multi-User**: Soll der Server mehrere User unterstuetzen? Aktuell: single-user. Multi-User braucht User-Isolation (separate team.json, separate Message-Namespaces).
3. **VPS-Provider**: Praeferenz? (Hetzner, DigitalOcean, etc.) Hetzner empfohlen: CAX11 ARM (4 vCPU, 8GB RAM, 3.29 EUR/Monat).
4. **Agents 24/7**: Sollen Agents auch auf dem Server laufen koennen (Szenario B)? Oder reicht Server-Only (Szenario A)?
5. **Budget**: Wie viel darf die Server-Infrastruktur kosten?
6. **Timeline**: Wann wird Server-Deployment gebraucht? MVP oder langfristig?
7. **Credential-Handling**: Wie sollen AI-API-Keys fuer Remote-Agents verteilt werden? (Nur relevant wenn spaeter Szenario B gewuenscht.)
