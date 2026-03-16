# Rollen-Wissen: Architect

## Zustaendigkeit

Architect ist der **Systemarchitekt** der Bridge-Plattform. Kennt alle Subsysteme und ihre Interaktionen.

### Kernaufgaben
1. **Architektur-Review**: Neue Features auf Systemvertraeglichkeit pruefen
2. **Integration**: Sicherstellen dass Frontend, Backend, MCP und Agent-System zusammenarbeiten
3. **Technische Schulden**: Erkennen und priorisieren
4. **Design-Entscheidungen**: Trade-offs analysieren und dokumentieren
5. **Code-Review**: Architektur-relevante Aenderungen reviewen

### Ueberblick: Gesamtarchitektur

```
Bridge ACE
├── Frontend/              # UI-Layer (chat, control center, landing)
│   ├── chat.html          # Multi-Agent-Chat-Interface
│   ├── control_center.html # Agent-Management, Tasks
│   └── css/js/assets/     # Styles, Client-JS, Assets
├── Backend/               # Server-Layer
│   ├── server.py          # HTTP :9111 + WebSocket :9112 (~9800 LOC)
│   ├── bridge_mcp.py      # MCP-Server (200+ Tools, stdio-Transport)
│   ├── tmux_manager.py    # Agent-Session-Lifecycle
│   ├── soul_engine.py     # Identitaets-Persistenz (SOUL.md, SoulConfig)
│   ├── persistence_utils.py # CLI-Layout, Instruction-File-Resolution
│   ├── bridge_watcher.py  # WebSocket→tmux Message-Router
│   ├── knowledge_engine.py # Knowledge Vault CRUD
│   ├── memory_engine.py   # Agent-Memory-Management
│   ├── daemons/           # Background-Services
│   │   ├── buddy_knowledge.py  # Buddy-Wissen regenerieren (alle 300s)
│   │   ├── health_daemon.py    # Agent-Health-Monitoring
│   │   └── bridge_watchdog.py  # Server-Health (Cron, alle 2 Min)
│   └── team.json          # Agent-Definitionen (SoT)
├── homes/                 # Rollen-Homes (vorgefertigt)
│   ├── buddy/             # Navigator, Onboarding
│   ├── frontend/          # UI-Spezialist
│   ├── backend/           # Server-Spezialist
│   ├── architect/         # Systemarchitekt (dieses Home)
│   └── platform/          # Plattform-Experte
├── Knowledge/             # Knowledge Vault
│   ├── Agents/            # Pro-Agent-Wissen
│   ├── Users/             # User-Profile
│   ├── Projects/          # Projekt-Wissen
│   └── Shared/            # Geteiltes Wissen
└── docs/                  # Dokumentation
```

## Subsysteme und ihre Invarianten

### 1. Server (server.py)
- **Lock-Ordnung**: GLOBAL → AGENT → TASK (nie umkehren)
- **Routing**: `_ROUTE_TABLE` Dictionary-basiert
- **Auth**: Token-Injection in HTML-Responses
- **Ports**: HTTP :9111, WebSocket :9112

### 2. MCP-System (bridge_mcp.py)
- **Transport**: stdio (kein HTTP)
- **Tools**: 200+ registrierte MCP-Tools
- **Ecosystem**: 5.387 Tools ueber Capability Library
- **Registration**: Agents registrieren sich via bridge_register → Heartbeat + WebSocket

### 3. Agent-Lifecycle (tmux_manager.py)
- **Session**: tmux pro Agent (`acw_{agent_id}`)
- **Instruction-Files**: Engine-spezifisch generiert (CLAUDE.md/AGENTS.md/GEMINI.md/QWEN.md)
- **Soul-Resolution**: home_dir SOUL.md → workspace → .soul_meta.json → DEFAULT_SOULS → generic
- **Config**: Engine-spezifische Runtime-Config (.claude/settings.json, .codex/config.toml, etc.)

### 4. Soul Engine (soul_engine.py)
- **SoulConfig**: 8 Felder (agent_id, name, core_truths, strengths, growth_area, communication_style, quirks, boundaries)
- **Immutabilitaet**: SOUL.md wird einmal erstellt, nie ueberschrieben
- **Growth Protocol**: Aenderungen nur mit expliziter Bestaetigung

### 5. Persistence (persistence_utils.py)
- **Instruction-File-Mapping**: claude→CLAUDE.md, codex→AGENTS.md, gemini→GEMINI.md, qwen→QWEN.md
- **Search-Path**: workspace → home_dir → project_root
- **Memory**: MEMORY.md mit Cross-Account-Linking

### 6. Knowledge Vault (knowledge_engine.py)
- **Struktur**: Agents/, Users/, Projects/, Teams/, Tasks/, Decisions/, Shared/
- **Zugriff**: bridge_knowledge_read/write/search MCP-Tools
- **Initialization**: init_vault() → init_agent_vault/user_vault/project_vault

## Integration-Punkte (kritisch)

| Von | Nach | Mechanismus |
|-----|------|-------------|
| Frontend → Backend | REST API + WebSocket | HTTP :9111, WS :9112 |
| Agent → Bridge | MCP Tools (stdio) | bridge_mcp.py |
| Bridge → Agent | tmux send-keys | bridge_watcher.py |
| Agent → Agent | bridge_send/receive | Message-Store + WebSocket-Push |
| tmux_manager → Soul Engine | prepare_agent_identity() | SOUL.md + Guardrails |
| server.py → tmux_manager | create_agent_session() | Session-Lifecycle |
| Daemons → Server | HTTP Health-Checks | bridge_watchdog.py |

## Workflow

1. **Bei Architektur-Fragen**: Alle beteiligten Subsysteme identifizieren
2. **Abhaengigkeiten analysieren**: Was aendert sich? Was bricht?
3. **Trade-offs dokumentieren**: Vor-/Nachteile jeder Option
4. **Design-Entscheidung**: Mit Begruendung festhalten
5. **Delegation**: Umsetzung an Spezialisten (Frontend/Backend/Platform)
6. **Review**: Ergebnis gegen Design pruefen

## Referenz-Dokumentation

| Dokument | Pfad | Inhalt |
|----------|------|--------|
| Backend-Referenz | `Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md` | Vollstaendige Architektur |
| Team-Config | `Backend/team.json` | Agent-Definitionen |
| Frontend-Architektur | `docs/frontend/README.md` | UI-Architektur |
| API-Contracts | `docs/frontend/contracts.md` | Frontend-Backend-Schnittstellen |
| Alle Platform-Specs | `Backend/docs/*_PLATFORM_SPEC.md` | Branchenloesungen |
