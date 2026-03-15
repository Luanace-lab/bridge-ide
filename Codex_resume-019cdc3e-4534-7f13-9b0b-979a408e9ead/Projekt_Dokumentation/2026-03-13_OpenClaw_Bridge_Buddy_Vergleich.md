# OpenClaw vs BRIDGE vs Buddy

## Zweck
Evidenzbasierte Vergleichsbasis fuer:

- BRIDGE vs OpenClaw
- Buddy vs OpenClaw
- BRIDGE + Buddy vs OpenClaw

Stand der Recherche: 2026-03-13.

## Wichtige Namensklarstellung
Die offizielle OpenClaw-Lore beschreibt die Reihenfolge:

- `Clawd`
- `Moltbot`
- `OpenClaw`

Nicht umgekehrt.

Laut offizieller Lore erfolgte die Umbenennung von `Moltbot` zu `OpenClaw` am `30. Januar 2026`.

## Methodik
Die Vergleichsbasis kombiniert:

1. lokale BRIDGE-/Buddy-Dokumentation aus `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead`
2. reale Codeanalyse der aktiven BRIDGE-Artefakte
3. frische Laufzeitproben gegen die lokale BRIDGE-Instanz auf `http://127.0.0.1:9111`
4. offizielle OpenClaw-Primärquellen

## Lokale BRIDGE-/Buddy-Evidenz

### Architektur und Betriebsmodell
- `Backend/server.py` hat `21970` Zeilen.
- `Backend/bridge_mcp.py` hat `11370` Zeilen.
- `Frontend/chat.html` hat `10654` Zeilen.
- `Frontend/control_center.html` hat `10189` Zeilen.
- Die aktive Runtime war bei der Live-Probe `configured=true` im Pair-Mode `codex-claude`.
- `GET /runtime` meldete am 2026-03-13 zwei laufende Runtime-Agents (`codex`, `claude`) plus verfuegbare Engines `claude`, `codex`, `gemini`, `qwen`.

### Buddy als reales Produktartefakt
- `Backend/team.json` definiert `buddy` als `concierge` mit eigenem Home `/home/leo/Desktop/CC/Buddy`.
- Buddy ist im aktuellen Team-Config-Zustand `active:false` und `auto_start:false`.
- `GET /agents/buddy` lieferte live `status:"offline"`, `tmux_alive:false`, `resume_id:""`, `cli_identity_source:"team_home_fallback"`.
- `GET /onboarding/status?user_id=user` lieferte live `known_user:true`, `buddy_running:false`, `should_auto_start:false`.
- Buddy fuehrt in `Backend/team.json` reale Teams:
  - `trading-team`
  - `marketing-team`
  - `legal-team`

### BRIDGE-Tool- und Orchestrierungsflaeche
`Backend/bridge_mcp.py` expose-t im aktiven Code unter anderem:

- Registrierung, Messaging und Inbox
- Task-Lifecycle, Queue, Check-ins
- Scope-Locks und Whiteboard
- Approval-Gates
- E-Mail, Slack, WhatsApp, Todoist, Telefonie
- Browser-Automation und Browser-Research
- Desktop-Automation
- Knowledge Vault und semantisches Memory
- Teams, Projekte, Runtime-Konfiguration
- Workflow-Compile/Deploy/Execute
- Git-Branching, Push-Checks und Locks

### Live-Orchestrierung
- `GET /task/queue?limit=2` lieferte live echte Task-Daten mit Lifecycle-Historie.
- `GET /workflows` lieferte live `20` Workflows.
- `GET /workflows/templates` lieferte live `5` Template-Workflows.

## Offizielle OpenClaw-Evidenz

### Produktbild
OpenClaw beschreibt sich offiziell als persoenlichen AI-Assistenten auf den eigenen Geraeten. Laut GitHub-README beantwortet OpenClaw Nutzer auf vielen bereits genutzten Kanaelen; der Gateway sei nur die Control Plane, das eigentliche Produkt sei der Assistent.

### Agentenmodell
Die offizielle Agent-Runtime-Doku beschreibt:

- einen zentralen Agent-Workspace als `cwd`
- injizierte Bootstrap-Dateien:
  - `AGENTS.md`
  - `SOUL.md`
  - `TOOLS.md`
  - `BOOTSTRAP.md`
  - `IDENTITY.md`
  - `USER.md`
- JSONL-Sessiontranskripte unter `~/.openclaw/agents/<agentId>/sessions/<SessionId>.jsonl`
- stabile, von OpenClaw gewaehlte Session-IDs
- Skills aus drei Ebenen:
  - bundled
  - `~/.openclaw/skills`
  - `<workspace>/skills`

### Memory-Modell
Die offizielle Memory-Doku beschreibt:

- Markdown im Agent-Workspace als Source of Truth
- zwei Standard-Layer:
  - `memory/YYYY-MM-DD.md` als taegliches append-only Log
  - `MEMORY.md` als kuratierter Long-Term-Layer
- agent-facing Tools:
  - `memory_search`
  - `memory_get`
- Hybrid Search `BM25 + vector`
- optionalen QMD-Backend-Pfad, bei dem Markdown trotzdem die Source of Truth bleibt

### Multi-Agent-Modell
Die offizielle Multi-Agent-Doku beschreibt:

- mehrere isolierte Agents in einem Gateway
- pro Agent getrennte `workspace`, `agentDir` und Session-Store
- Bindings und Routing-Regeln pro Kanal/Account/Peer
- per-agent Sandbox- und Tool-Konfiguration

### Subagents und Browser
- Die offizielle Subagent-Doku beschreibt Sub-Agents als Hintergrundlaeufe mit eigener Session `agent:<agentId>:subagent:<uuid>`.
- Die Browser-Login-Doku empfiehlt manuelle Logins im Host-Browserprofil und warnt explizit vor automatisierten Logins wegen Anti-Bot-Risiken.

### Sicherheit und Erweiterbarkeit
- Die Security-Doku beschreibt DM-Allowlist-/Group-Allowlist-Mechanik und `allowFrom`.
- Die Security-Doku beschreibt Trusted-Proxy-/Reverse-Proxy-Hardening.
- Die Plugin-Doku beschreibt installierbare offizielle Plugins ueber `openclaw plugins install`.
- Das GitHub-README beschreibt die Gateway-Installation als laufenden Daemon via `launchd/systemd user service`.

## Verdichtetes Urteil

### BRIDGE vs OpenClaw
BRIDGE ist die breitere Orchestrierungs- und Integrationsmaschine. OpenClaw ist das koharentere Endnutzer-Agent-Produkt.

### Buddy vs OpenClaw
OpenClaw ist im dokumentierten Produktzuschnitt und in der Assistenz-Koharenz staerker. Buddy ist als Persona und Concierge gut definiert, haengt aber aktuell real an einer BRIDGE-Integration, die Buddy im Live-Zustand nicht automatisch hochzieht.

### BRIDGE + Buddy vs OpenClaw
BRIDGE + Buddy hat das hoehere agentische Ceiling:

- Multi-Agent-Koordination
- Task-/Workflow-/Locking-System
- Desktop plus Browser plus Real-World-Integrationen
- Approval-Gates fuer reale Aktionen

OpenClaw bleibt aber das rundere integrierte Personal-Agent-Paket, solange Buddy als Frontdoor im Live-Zustand offline und nicht auto-startend bleibt.

## Hauptdifferenzen

### 1. Produktschnitt
- OpenClaw: Personal-Agent-Produkt mit Gateway als Control Plane
- BRIDGE: Multi-Agent-Orchestrierungsplattform
- Buddy: Concierge-Agent auf BRIDGE, nicht die Plattform selbst

### 2. Source of Truth
- OpenClaw: dokumentiert Markdown-/Workspace-first
- BRIDGE: Zielbild `CLI als SoT`, real aber mehrere dateibasierte Stores und Projektionen

### 3. Orchestrierungstiefe
- OpenClaw: stark in pers. Assistent, Channel-, Memory-, Session- und Multi-Agent-Isolation
- BRIDGE: deutlich staerker in Tasks, Workflows, Scope-Locks, Whiteboard, Runtime-Steuerung und reale Integrationen

### 4. Aktuelle Produktkoharenz
- OpenClaw: koharenter dokumentierter Personal-Agent-Stack
- Buddy: gute Rolle, aber live aktuell nicht selbsttragend als stabile Frontdoor

## Quellen

### Lokale Dateien
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Fragenkatalog.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Antworten.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/01_Gesamtueberblick.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/02_Gap_Map.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W01_Systemarchitektur_und_Laufzeitfluss.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W05_Datenmodelle_Persistenz_APIs_Schnittstellen_Stores.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/Persistenz_CLI_SoT_Implementierung.md`
- `Backend/server.py`
- `Backend/bridge_mcp.py`
- `Backend/tmux_manager.py`
- `Backend/team.json`
- `Frontend/buddy_landing.html`
- `Frontend/buddy_widget.js`
- `/home/leo/Desktop/CC/Buddy/CLAUDE.md`
- `/home/leo/Desktop/CC/Buddy/SOUL.md`

### Live-Proben
- `GET /status`
- `GET /runtime`
- `GET /agents/buddy`
- `GET /onboarding/status?user_id=user`
- `GET /task/queue?limit=2`
- `GET /workflows`
- `GET /workflows/templates`

### Externe Primärquellen
- `https://docs.openclaw.ai/start/lore`
- `https://docs.openclaw.ai/concepts/agent`
- `https://docs.openclaw.ai/concepts/memory`
- `https://docs.openclaw.ai/concepts/multi-agent`
- `https://docs.openclaw.ai/tools/subagents`
- `https://docs.openclaw.ai/tools/browser-login`
- `https://docs.openclaw.ai/gateway/security`
- `https://docs.openclaw.ai/tools/plugin`
- `https://github.com/clawdbot/clawdbot`
