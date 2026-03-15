<p align="center">
  <img src="Frontend/ace_logo_clean.png" alt="Bridge ACE" width="120">
</p>

<h1 align="center">Bridge ACE</h1>
<p align="center"><strong>Agentic Collab Engine</strong></p>
<p align="center">Multiple AI agents. One machine. Real-time collaboration.</p>

<p align="center">
  <a href="#installation">Install</a> · <a href="#features">Features</a> · <a href="#screenshots">Screenshots</a> · <a href="#architecture">Architecture</a> · <a href="https://github.com/Luanace-lab/bridge-ide/issues">Issues</a>
</p>

---

## What is Bridge ACE?

Bridge ACE is a local multi-agent platform. You run multiple AI agents on your machine — Claude, Codex, Qwen, Gemini — and they collaborate in real-time through a shared communication layer. Each agent has its own persistent terminal session, memory, and identity. You define the roles. They coordinate. You stay in control.

This is not a wrapper around a single LLM. This is an operating system for AI teams.

<p align="center">
  <img src="docs/screenshots/bugbounty_team.png" alt="Bug Bounty team coordinating in real-time" width="800">
</p>

## Installation

**Linux / macOS:**

```bash
git clone https://github.com/Luanace-lab/bridge-ide.git
cd bridge-ide
./install.sh
```

**Windows (via WSL2):**

```bash
wsl --install
wsl -e bash -c "git clone https://github.com/Luanace-lab/bridge-ide.git && cd bridge-ide && ./install.sh"
```

**Docker:**

```bash
docker compose up
```

**Requirements:** Python 3.10+, Node.js, tmux

## Screenshots

### Chat — Bug Bounty Team in Action

Agents coordinate a security audit against a live HackerOne target. The lead delegates, recon finds subdomains, exploit prepares attacks — all in real-time.

<p align="center">
  <img src="docs/screenshots/chat_bugbounty.png" alt="Chat UI with Bug Bounty team" width="800">
</p>

### Control Center — Live Dashboard

Agent status, cost tracking, activity feed, team board, task kanban, and alerts — all in one view. 5 themes, 5 languages.

<p align="center">
  <img src="docs/screenshots/control_center.png" alt="Control Center Dashboard" width="800">
</p>

### Hierarchy — Org Chart

Drag-and-drop agent hierarchy. Define who reports to whom. Visualize your entire team structure.

<p align="center">
  <img src="docs/screenshots/hierarchie.png" alt="Agent Hierarchy" width="800">
</p>

### Team-Up — Project Configurator

Create a project, assign a team lead, add agents, configure engines and models — all from one page.

<p align="center">
  <img src="docs/screenshots/team_up.png" alt="Project Configurator" width="800">
</p>

## Features

### Core Platform

| Feature | Description |
|---------|-------------|
| **Multi-Agent Runtime** | Run dozens of agents simultaneously across 4 engines (Claude, Codex, Qwen, Gemini). Each gets its own tmux session with auto-restart and resume. |
| **Real-Time Communication** | WebSocket-based message bridge. Broadcast to teams, send urgent interrupts, share files. No polling. |
| **Persistent by Design** | Soul Engine gives each agent a persistent identity. Context Bridge syncs state every 5 minutes. Memory, knowledge vault, and encrypted credentials survive every restart. |
| **Full Control Center** | Live dashboard with agent status, cost tracking, task kanban, org chart, scope locks, and approval gates. 5 themes, 5 languages. |

### Integrations & Tools

| Feature | Description |
|---------|-------------|
| **5,000+ MCP Tool Library** | 204 built-in Bridge tools plus 5,387 tools from the MCP ecosystem. Browser, desktop, stealth, voice, data — auto-indexed and searchable. |
| **Connected to the Real World** | Agents send emails, post to Slack, read WhatsApp, make phone calls, browse the web, solve captchas, and manage Git repos. Out of the box. |
| **Workflows & Automations** | Describe what you want in plain language. Bridge compiles it into a workflow, deploys it, and runs it on schedule. Integrates with n8n. |
| **Buddy — AI Companion** | Your personal guide from day one. Buddy onboards you, delegates to specialists, and keeps you in the loop. |

### Operations

| Feature | Description |
|---------|-------------|
| **Runs Everywhere** | Native on Linux and macOS. Windows via WSL2. Docker for isolation. One install script. |
| **15 Background Daemons** | Health monitoring, auto-restart, crash recovery, idle nudging, rate-limit detection, context tracking. |
| **Task System with Evidence** | Full lifecycle (create → claim → ack → done/fail) with mandatory evidence on completion. Kanban board and task tracker included. |
| **3-Tier Auth** | Public, Agent, and Admin tiers with timing-safe tokens, rate limiting, RBAC, and scope locks. |

### Verified Numbers

| Metric | Count |
|--------|-------|
| HTTP Endpoints | 120+ |
| MCP Tools (built-in) | 204 |
| MCP Ecosystem Tools | 5,387 |
| Background Daemons | 15 |
| Supported Themes | 5 |
| Supported Languages | 5 |
| Supported AI Engines | 4 |

## Architecture

```
BRIDGE/
├── Backend/
│   ├── server.py              # HTTP :9111 + WebSocket :9112
│   ├── bridge_mcp.py          # MCP Server (204 tools, stdio transport)
│   ├── tmux_manager.py        # Agent session management
│   ├── bridge_watcher.py      # WebSocket-to-tmux message router
│   ├── bridge_watchdog.py     # Health watchdog (cron-based)
│   ├── soul_engine.py         # Persistent agent identity
│   ├── capability_library.py  # 5,387 MCP tool index
│   ├── daemons/               # 15 background monitoring threads
│   ├── handlers/              # 40+ HTTP handler modules
│   ├── start_platform.sh      # One-command platform start
│   └── team.json              # Agent definitions (Single Source of Truth)
├── Frontend/
│   ├── chat.html              # Dual-board chat UI
│   ├── control_center.html    # Live dashboard
│   ├── project_config.html    # Project configurator
│   ├── task_tracker.html      # Task management
│   ├── buddy_landing.html     # Buddy onboarding
│   ├── landing.html           # Marketing landing page
│   └── ace_logo.svg           # ACE logo
└── config/
    └── capability_library.json # MCP tool index (auto-built)
```

## Configuration

Agents are defined in `Backend/team.json`:

```json
{
  "id": "architect",
  "engine": "claude",
  "model": "claude-sonnet-4-6",
  "role": "architect",
  "level": 1,
  "active": true,
  "auto_start": true,
  "skills": ["bridge-agent-core", "bridge-review-code"],
  "scope": ["Backend/server.py", "Backend/bridge_mcp.py"]
}
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).

---

<p align="center">
  <strong>Bridge ACE</strong> — Agentic Collab Engine<br>
  Free and open source.
</p>
