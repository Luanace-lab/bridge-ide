# Competitor Gaps: Bridge IDE vs. Moltbot/OpenClaw

Stand: 2026-03-14
Quelle: Video-Analyse (youtube.com/watch?v=70MEfCwuyZA) + Web-Recherche

---

## Gaps bei Bridge (Features die Moltbot hat, Bridge nicht)

### 1. Chat-Plattformen (6 fehlende Kanaele)

| Plattform | Moltbot | Bridge |
|-----------|---------|--------|
| Discord | JA (discord.js) | NEIN |
| Signal | JA (signal-cli) | NEIN |
| iMessage | JA (macOS imsg CLI) | NEIN |
| Microsoft Teams | JA (Connector) | NEIN |
| Matrix | JA | NEIN |
| Google Chat | JA | NEIN |

**Bridge hat:** WhatsApp, Telegram, Slack, Email, Telefon (5 Kanaele)
**Moltbot hat:** 10+ Chat-Plattformen, aber kein Telefon

**Bewertung:** Mittlerer Gap. Discord und Teams sind fuer Business-Teams relevant. Signal fuer Privacy-Nutzer. iMessage nur macOS.

### 2. Cloud-Hosting

| Feature | Moltbot | Bridge |
|---------|---------|--------|
| Cloudflare Workers | JA | NEIN |
| Remote-Zugriff via Tailscale | JA | NEIN |
| Raspberry Pi Support | JA | UNKNOWN |

**Bewertung:** Kleiner Gap fuer aktuellen Use Case (Bridge laeuft lokal). Wird relevant wenn Bridge als SaaS angeboten wird.

### 3. Skills Marketplace

| Feature | Moltbot | Bridge |
|---------|---------|--------|
| ClawdHub (Community Skills) | JA (130+ Contributors) | NEIN |
| Self-writing Skills | JA (Agent schreibt eigene Skills) | Teilweise (Agent kann Code schreiben) |
| Skill-Discovery | JA (Marketplace-UI) | NEIN |

**Bewertung:** Kleiner Gap. Bridge hat Skills (`bridge_skill_*`), aber keinen oeffentlichen Marketplace.

---

## Gaps bei Moltbot (Features die Bridge hat, Moltbot nicht)

| Feature | Bridge | Moltbot |
|---------|--------|---------|
| Stealth Browser (Anti-Detection) | 10 Tools | NEIN |
| CAPTCHA Solving | Multi-Provider | NEIN |
| Desktop Automation (GUI) | 18 Tools | NEIN |
| Vision-gesteuerte Browser-Aktionen | JA | NEIN |
| Multi-Agent (verschiedene Engines parallel) | Kernfeature | NEIN |
| Team-Management | JA | NEIN |
| Task-System mit Escalation | 12 Tools | NEIN |
| Scope Locks (Concurrency Control) | JA | NEIN |
| Whiteboard (Team-Visibility) | JA | NEIN |
| Approval Gates (Governance) | JA | NEIN |
| Encrypted Credential Vault | JA | NEIN |
| Semantic Memory (Vector+BM25) | JA | NEIN |
| n8n Workflow Integration | JA | NEIN |
| Telefonie (Call, Speak, Listen) | JA | NEIN |
| Git Collaboration (Branch Locks) | 7 Tools | NEIN |
| Media Creator Pipeline | 9 Tools | NEIN |

---

## Priorisierte Handlungsempfehlung

### Prio 1 — Discord + Teams Integration
Grund: Haeufigste Business-Chat-Plattformen nach Slack. Viele Teams nutzen Discord oder Teams.

### Prio 2 — Cloud-Hosting Option
Grund: Ermoeglicht Bridge als Remote-Service. Tailscale-Integration waere niedrighaengend.

### Prio 3 — Signal Integration
Grund: Privacy-bewusste User. Technisch aehnlich wie Telegram-Integration.

### Spaeter — Skills Marketplace
Grund: Erst relevant wenn externe User Bridge nutzen.
