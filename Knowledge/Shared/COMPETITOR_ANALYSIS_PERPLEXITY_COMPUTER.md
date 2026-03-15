# Competitor Analysis: Bridge IDE vs. Perplexity Computer

Stand: 2026-03-14
Quellen: 3 YouTube-Videos (EHpAQwXmseQ, wfKPIvdJHOc, 2c7FXXQ2-SA), Perplexity Blog, Builder.io Review, eesel.ai Guide, The AI Corner Guide, TechCrunch, VentureBeat, 9to5Mac

---

## Was ist Perplexity Computer?

Ein **cloud-basierter Multi-Model AI Agent** von Perplexity AI. Kein physischer Computer — ein Orchestrierungssystem das 19 AI-Modelle gleichzeitig koordiniert. Launched 25.02.2026.

**Kernkonzept:** User gibt ein Ziel ein ("Build me a marketing report") → System zerlegt es in Subtasks → weist jedem Task das beste Modell zu → Sub-Agents arbeiten parallel → fertiges Ergebnis wird geliefert.

**Preis:** $200/Monat (Perplexity Max), 10.000 Credits/Monat.

---

## Architektur-Vergleich

| Aspekt | Bridge IDE | Perplexity Computer |
|--------|-----------|---------------------|
| **Typ** | Self-hosted Multi-Agent Platform | Cloud-hosted Multi-Model Orchestrator |
| **Hosting** | Lokal (eigene Hardware) | Perplexity Cloud (isolierte Linux-Sandbox) |
| **Sandbox** | 2 vCPU, 8GB RAM pro Task | Eigene Maschine, unbegrenzte Ressourcen |
| **Kosten** | API-Kosten der genutzten Engines | $200/Monat + Credit-System |
| **Modelle** | 4+ Engines (Claude, Codex/OpenAI, Gemini, Qwen) + LiteLLM | 19 Modelle (Opus 4.6, Gemini, GPT-5.2, Grok, Nano Banana, Veo 3.1, etc.) |
| **Model-Routing** | JA — engine_routing.py (Task→Engine nach Kategorie) | JA — Opus routet automatisch |
| **Open Source** | Proprietaer (Leo's Projekt) | Proprietaer (Perplexity AI) |
| **Datensouveraenitaet** | Vollstaendig (lokal) | Cloud (Perplexity's Server) |
| **Federation** | JA — verteilte Instanzen mit Ed25519/X25519 Crypto | NEIN |
| **Eigene MCP-Tools** | 179 Tools in bridge_mcp.py | Closed Source |
| **Capability Library** | 592 Eintraege (570 MCP-Registry + 16 Official + 6 Runtime) | Nicht vorhanden |
| **HTTP-Endpunkte** | 208+ | Nicht offen |
| **Backend-Module** | ~90 Module, ~73K LoC | Closed Source |

---

## Feature-Vergleich 1:1

### Multi-Model / Multi-Agent

| Feature | Bridge IDE | Perplexity Computer |
|---------|-----------|---------------------|
| **Anzahl Modelle** | 4+ Engines (Claude, Codex/OpenAI, Gemini, Qwen) + LiteLLM-Adapter | 19 Modelle |
| **Automatisches Routing** | JA — engine_routing.py (8 TaskCategories: code_review, research, etc.) | JA — Opus routet automatisch |
| **Sub-Agents** | JA — beliebig viele, persistent | JA — automatisch gespawnt pro Task |
| **Parallele Ausfuehrung** | JA — Agents arbeiten gleichzeitig | JA — Sub-Agents parallel |
| **Agent-Persistenz** | JA — Agents laufen dauerhaft, haben Memory | NEIN — Sub-Agents leben nur fuer den Task |
| **Agent-zu-Agent Kommunikation** | JA — WebSocket, bridge_send/receive | NEIN — nur via Orchestrator |
| **Teams** | JA — formale Team-Struktur | NEIN |
| **Task-System mit Escalation** | JA — 12 Tools, 3-stufige Eskalation | NEIN — nur internes Task-Splitting |
| **Verschiedene Rollen** | JA — Frontend, Backend, Concierge, etc. | NEIN — alle Sub-Agents sind generisch |

**Fazit:** Bridge hat **persistente, spezialisierte Agents mit Kommunikation**. Perplexity hat **mehr Modelle mit automatischem Routing**, aber Sub-Agents sind ephemer und rollenlos.

---

### Browser-Automatisierung

| Feature | Bridge IDE | Perplexity Computer |
|---------|-----------|---------------------|
| **Stealth Browser (Anti-Detection)** | JA — 10 Tools, Fingerprint-Evasion | NEIN |
| **CDP (Chrome DevTools Protocol)** | JA — Real Chrome, Session-Persistenz | NEIN — nur Screenshot-basiert |
| **Screenshot-basierte Navigation** | JA — bridge_vision_act | JA — Screenshot → Aktion Loop |
| **Semantic Element Refs** | JA — stabile Refs statt CSS-Selektoren | NEIN |
| **CAPTCHA Solving** | JA — reCAPTCHA, hCaptcha, Turnstile | NEIN |
| **Browser Sessions persistent** | JA — Login-Status bleibt erhalten | NEIN — Sandbox wird zerstoert |
| **Web Research** | JA — bridge_research mit Freshness | JA — 7 parallele Suchtypen (Web, Academic, Social, etc.) |

**Fazit:** Bridge dominiert bei **technischer Browser-Kontrolle** (Stealth, CDP, CAPTCHA). Perplexity dominiert bei **Research-Breite** (7 Suchtypen parallel, akademische Quellen).

---

### Desktop-Automatisierung

| Feature | Bridge IDE | Perplexity Computer |
|---------|-----------|---------------------|
| **Maus/Keyboard** | JA — 18 Tools | NEIN |
| **Window Management** | JA | NEIN |
| **Clipboard** | JA | NEIN |
| **Lokale Apps steuern** | JA | NEIN (Cloud-Sandbox) |
| **Personal Computer (lokal)** | N/A | JA — Mac Mini mit lokaler App-Steuerung (separates Produkt) |

**Fazit:** Bridge hat volle Desktop-Kontrolle. Perplexity Computer (Cloud) hat keine. Perplexity **Personal Computer** (separates Produkt, Mac-only) kann lokale Apps steuern — aber ist ein anderes Produkt.

---

### Kommunikation

| Kanal | Bridge IDE | Perplexity Computer |
|-------|-----------|---------------------|
| **Email (Gmail/Outlook)** | JA — Send/Read + Approval Gate | JA — via OAuth Connector |
| **Slack** | JA — Send/Read + Approval Gate | JA — via Connector |
| **WhatsApp** | JA — Send/Read/Voice + Approval Gate | NEIN |
| **Telegram** | JA — Send/Read + Approval Gate | NEIN |
| **Telefon** | JA — Call, Speak, Listen | NEIN |
| **Discord** | NEIN | JA — via Connector |
| **Notion** | NEIN | JA — via Connector |
| **Google Drive** | NEIN | JA — via Connector |
| **Canva** | NEIN | JA — via Connector |
| **Netlify** | NEIN | JA — Deployment direkt |
| **GitHub/Linear** | NEIN (nur Git-Tools) | JA — via Connector |
| **Snowflake/Databricks** | NEIN | JA — Enterprise Connector |
| **Todoist** | JA | NEIN |
| **Gesamt eigene Channels** | 5 Channels + Todoist + Telefon | 400+ OAuth Connectors (beworben) |
| **Capability Library** | 592 durchsuchbare MCP-Server (auto-installierbar) | Nicht vorhanden |

**Fazit:** Perplexity hat 400+ eingebaute OAuth-Connectors. Bridge hat 5 tiefe Channels (WhatsApp, Telegram, Slack, Email, Telefon mit Approval Gates) PLUS eine **Capability Library mit 592 MCP-Servern** die on-demand installiert werden koennen. Viele Perplexity-Connectors sind laut Reviews fehlerhaft.

---

### Content-Erstellung

| Feature | Bridge IDE | Perplexity Computer |
|---------|-----------|---------------------|
| **Video-Generierung** | NEIN | JA — Veo 3.1 |
| **Bild-Generierung** | NEIN | JA — Nano Banana |
| **Web-App-Erstellung** | NEIN (nicht als Feature) | JA — baut + hosted Apps |
| **PDF-Reports** | JA — via Skills | JA — automatisch |
| **Office Automation (Word/Excel/PPT)** | JA — office_automation.py (docx, xlsx, pptx) | NEIN (nur PDF) |
| **Media Pipeline (Ingest/Export/Social)** | JA — 9 Creator-Tools | NEIN |
| **Dashboard-Erstellung** | NEIN | JA — interaktive Dashboards |
| **App Hosting/Sharing** | NEIN | JA — Share-Links, Netlify-Deploy |

**Fazit:** Perplexity dominiert bei **generativer Content-Erstellung** (Video, Bild, Apps, Hosting). Bridge dominiert bei **Office-Dokumenten** (Word/Excel/PPT) und **Media-Pipeline** (Ingest/Clip/Social).

---

### Sicherheit & Governance

| Feature | Bridge IDE | Perplexity Computer |
|---------|-----------|---------------------|
| **Approval Gates** | JA — jede externe Aktion | Teilweise — User muss Aktionen bestaetigen |
| **Credential Vault (verschluesselt)** | JA | NEIN — OAuth-Token bei Perplexity |
| **Scope Locks** | JA | NEIN |
| **Audit Trail** | JA — Message Logs, Task History | JA — beworben |
| **Datensouveraenitaet** | JA — alles lokal | NEIN — Cloud |
| **Sandbox-Isolation** | Engine-Isolation + Scope Locks | Linux-Sandbox (2 vCPU, 8GB) |

**Fazit:** Bridge hat **volle lokale Kontrolle + Governance**. Perplexity hat **Cloud-Sicherheit aber keine Datensouveraenitaet**.

---

### Memory & Knowledge

| Feature | Bridge IDE | Perplexity Computer |
|---------|-----------|---------------------|
| **Persistent Memory** | JA — Semantic (Vector+BM25) + Markdown | JA — Session Memory |
| **Cross-Session Memory** | JA — Knowledge Vault | JA — User-Profil |
| **Agent-uebergreifend** | JA — Shared Knowledge Vault | NEIN — nur innerhalb eines Threads |
| **Knowledge Vault** | JA — 9 Tools | NEIN |
| **User Model** | JA — USER.md + Semantic | JA — lernt aus Interaktionen |

---

### Scheduling & Workflows

| Feature | Bridge IDE | Perplexity Computer |
|---------|-----------|---------------------|
| **Cron Jobs** | JA — bridge_cron_* | JA — "Weekly Briefing" Scheduling |
| **Loops** | JA — bridge_loop | NEIN |
| **n8n Workflows** | JA — Deploy/Execute | NEIN |
| **Langzeit-Tasks (Wochen)** | JA — persistent Agents | JA — beworben ("weeks, months") |
| **Parallele Projekte** | JA — Multi-Agent | JA — "dozens of Computers simultaneously" |

---

## Gaps bei Bridge (was Perplexity kann, Bridge nicht)

| Gap | Perplexity | Relevanz |
|-----|-----------|----------|
| **19 Modelle gleichzeitig** | Opus, Gemini, GPT-5.2, Grok, Nano Banana, Veo 3.1 | MITTEL — Bridge hat 4+ Engines + LiteLLM |
| **Video-Generierung** | Veo 3.1 integriert | MITTEL |
| **Bild-Generierung** | Nano Banana integriert | MITTEL |
| **Web-App bauen + hosten** | Baut Apps, hostet mit Share-Link | MITTEL |
| **400+ SaaS-Connectors** | OAuth-basiert (Gmail, Notion, GitHub, Canva, Netlify, etc.) | HOCH |
| **7 parallele Suchtypen** | Web, Academic, People, Image, Video, Shopping, Social | MITTEL |
| **Dashboard-Generierung** | Interaktive Charts + Share | NIEDRIG |
| **Cloud-Hosting** | Laeuft in Perplexity-Cloud | NIEDRIG fuer aktuellen Use Case |

## Gaps bei Perplexity (was Bridge kann, Perplexity nicht)

| Gap | Bridge | Relevanz |
|-----|--------|----------|
| **Stealth Browser (Anti-Detection)** | 10 Tools + Fingerprint-Evasion | Spezifisch |
| **CDP Real Browser (Login-Persistenz)** | Session bleibt erhalten | HOCH |
| **CAPTCHA Solving** | Multi-Provider | Spezifisch |
| **Desktop Automation (GUI)** | 18 Tools, Maus/Keyboard/Windows | HOCH |
| **WhatsApp/Telegram/Telefon** | Send/Read/Voice + Approval Gates | HOCH |
| **Persistente spezialisierte Agents** | Frontend, Backend, Concierge mit Memory | HOCH |
| **Agent-zu-Agent Kommunikation** | WebSocket, Echtzeit | HOCH |
| **Team-Management** | Formale Teams mit Rollen | HOCH |
| **Task-Escalation-System** | 3-stufig mit Timeouts | MITTEL |
| **Encrypted Credential Vault** | Lokal verschluesselt | HOCH |
| **Scope Locks (Concurrency)** | File-Level Locking | MITTEL |
| **Datensouveraenitaet** | Alles lokal | HOCH |
| **n8n Workflow Integration** | Deploy + Execute | MITTEL |
| **Media Creator Pipeline** | Ingest/Clip/Social/SRT | MITTEL |
| **Approval Gates (Governance)** | Jede externe Aktion | HOCH |
| **Federation (Multi-Instanz)** | Ed25519-signiert, X25519-verschluesselt, Relay-Routing | HOCH |
| **Office Automation** | Word, Excel, PowerPoint (python-docx/openpyxl/python-pptx) | MITTEL |
| **Execution Journal** | Immutable JSONL Audit Trail mit Signatur | MITTEL |
| **Agent Soul/Growth** | Persistente Identitaet, Growth-Protokoll, Self-Reflection | MITTEL |
| **Guardrails** | Policy-Presets (safe/permissive/restricted), Violation-Tracking | HOCH |
| **Event Bus + Message Bus** | Publisher-Subscriber, Priority Queues, At-Least-Once Delivery | MITTEL |

---

## Gesamtbewertung

| Dimension | Bridge IDE | Perplexity Computer | Gewinner |
|-----------|-----------|---------------------|----------|
| **Multi-Model Breite** | 4+ Engines + LiteLLM + Auto-Routing | 19 Modelle + Auto-Routing | Perplexity |
| **Agent-Tiefe** | Persistent, spezialisiert, kommunizierend, Soul-System | Ephemer, generisch | Bridge |
| **Browser Technical** | Stealth + CDP + CAPTCHA | Screenshot-basiert | Bridge |
| **Browser Research** | 1 Suchtyp | 7 parallele Suchtypen | Perplexity |
| **Desktop** | Vollstaendig | Nicht vorhanden | Bridge |
| **SaaS-Integrationen** | 5 Channels + Telefon | 400+ Connectors | Perplexity |
| **Content Generation** | Media Pipeline | Video + Bild + Apps + Hosting | Perplexity |
| **Sicherheit/Governance** | Approval Gates + Vault + Locks + Guardrails + Audit Journal | Cloud-Sandbox | Bridge |
| **Datensouveraenitaet** | Lokal, volle Kontrolle | Cloud, Perplexity hat Zugriff | Bridge |
| **Federation** | Multi-Instanz mit Crypto | Nicht vorhanden | Bridge |
| **Office Automation** | Word/Excel/PPT nativ | Nur PDF | Bridge |
| **Kosten** | API-Kosten (~$20-100/Monat) | $200/Monat fix | Bridge |
| **Setup-Aufwand** | Hoch (Self-Hosted) | Null (Browser-Login) | Perplexity |
| **Zielgruppe** | Power-User, Entwickler, Teams | Knowledge Worker, Content Creator | Verschieden |

---

## Strategische Einordnung

Bridge und Perplexity Computer sind **keine direkten Konkurrenten** — sie bedienen verschiedene Segmente:

- **Perplexity Computer** = "Managed AI Workforce" fuer Knowledge Worker die Content, Reports und Apps brauchen. Cloud-first, Zero-Setup, $200/Monat.
- **Bridge IDE** = "Self-Hosted AI Operations Platform" fuer technische Teams die volle Kontrolle, Sicherheit und spezialisierte Agents brauchen. Lokal, sovereign, API-Kosten.

Die **relevantesten Gaps** fuer Bridge sind:
1. **Mehr SaaS-Connectors** (OAuth-basiert: Notion, GitHub Issues, Google Drive, Canva, Netlify)
2. **Generative Content-Modelle** (Bild/Video-Generierung als Bridge-Tools)
3. **App Hosting/Sharing** (Web-Apps deployen und per Link teilen)

**KORREKTUR gegenueber frueherer Analyse:** Bridge hat bereits automatisches Engine-Routing (engine_routing.py mit 8 TaskCategories). Die vorherige Behauptung "nur manuelle Zuweisung" war falsch.
