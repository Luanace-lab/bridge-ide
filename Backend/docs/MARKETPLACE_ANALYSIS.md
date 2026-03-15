# Marketplace-Analyse: Skills, MCPs und Plugins fuer die Bridge

Stand: 2026-03-14
Autor: Viktor

---

## 1. Marketplace-Uebersicht

### 1.1 Plugin-Marketplaces (Claude Code)

| Marketplace | Typ | Umfang | URL |
|---|---|---|---|
| **claude-plugins-official** | Anthropic-offiziell | ~80 Plugins | github.com/anthropics/claude-plugins-official |
| **claude-code** | Anthropic-intern | ~10 Plugins | github.com/anthropics/claude-code/plugins |
| **claudemarketplaces.com** | Community-Aggregator | 9.000+ | claudemarketplaces.com |
| **buildwithclaude.com** | Community | 488+ | buildwithclaude.com |
| **claudecodemarketplace.com** | Community | UNKNOWN | claudecodemarketplace.com |

### 1.2 MCP-Server-Verzeichnisse

| Verzeichnis | Umfang | Aktualisierung | URL |
|---|---|---|---|
| **PulseMCP** | 10.400+ Server | Taeglich | pulsemcp.com/servers |
| **Glama** | 7.800+ Server | Taeglich | glama.ai/mcp/servers |
| **Smithery** | Groesster Marktplatz | Laufend | smithery.ai |
| **mcpservers.org** | Kuratiert | Laufend | mcpservers.org |
| **modelcontextprotocol/servers** | Offiziell (Anthropic) | Laufend | github.com/modelcontextprotocol/servers |
| **awesome-mcp-servers** (punkpeye) | Community-kuratiert | Laufend | github.com/punkpeye/awesome-mcp-servers |
| **best-of-mcp-servers** | 410 Server, Ranked | Woechentlich | github.com/tolkonepiu/best-of-mcp-servers |

### 1.3 Skills-Marketplaces

| Marketplace | Umfang | URL |
|---|---|---|
| **SkillsMP** | Multi-Agent (Claude, Codex, ChatGPT) | skillsmp.com |
| **awesome-claude-skills** (travisvn) | Kuratiert | github.com/travisvn/awesome-claude-skills |
| **Antigravity Awesome Skills** | 1.234+ Skills | Community |
| **awesome-claude-skills** (ComposioHQ) | Kuratiert | github.com/ComposioHQ/awesome-claude-skills |

---

## 2. Bridge-relevante Plugins (claude-plugins-official)

Bereits auf dem System installierbar. Sortiert nach Relevanz fuer die Bridge-Plattformen.

### Direkt relevant

| Plugin | Relevanz | Bridge-Plattform |
|---|---|---|
| **legalzoom** | `/review-contract` Workflow als Skill uebernehmbar | Legal |
| **security-guidance** | Security Best Practices | Cyber-Security |
| **code-review** | Code-Review-Workflows | DevOps |
| **pagerduty** | Incident-Management-Integration | DevOps |
| **sentry** | Error-Tracking-Integration | DevOps |
| **slack** | Slack-Integration (bereits in Bridge) | Customer Support, Marketing |
| **github** | GitHub-Integration | DevOps |
| **gitlab** | GitLab-Integration | DevOps |
| **linear** | Issue-Tracking | DevOps |
| **asana** | Projekt-Management | DevOps |
| **postman** | API-Testing | Cyber-Security, DevOps |
| **stripe** | Payment-Integration | Finanzbuchhaltung |
| **supabase** | Database-Integration | Big Data |
| **firebase** | Backend-Integration | DevOps |
| **data** | Datenanalyse | Big Data |
| **semgrep** | SAST Code-Security | Cyber-Security |
| **posthog** | Product Analytics | Marketing |
| **firecrawl** | Web-Scraping/Crawling | Cyber-Security (Recon) |
| **vercel** | Deployment | DevOps |
| **railway** | Deployment | DevOps |
| **playwright** | Browser-Automation (bereits installiert) | Alle |

### Potenziell nuetzlich

| Plugin | Relevanz |
|---|---|
| **Notion** | Knowledge-Management, Docs |
| **figma** | Design-Integration |
| **greptile** | Codebase-Verstaendnis |
| **sourcegraph** | Code-Suche |
| **coderabbit** | Code-Review AI |
| **qodo-skills** | Testing-Skills |
| **superpowers** | Agent-Produktivitaet |
| **pr-review-toolkit** | PR-Review |
| **feature-dev** | Feature-Entwicklung |
| **hookify** | Hook-Management |

---

## 3. Bridge-relevante MCP-Server (extern)

Aus PulseMCP, Glama, awesome-mcp-servers. Sortiert nach Bridge-Plattform.

### Big Data / Analytics

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **postgres-mcp** (pgEdge) | PostgreSQL Schema + Queries | github.com/pgedge |
| **mysql-mcp** | MySQL Queries | Community |
| **bigquery-mcp** | Google BigQuery | Community |
| **snowflake-mcp** | Snowflake Queries | Community |
| **supabase-mcp** | Supabase/PostgreSQL | Community |
| **duckdb-mcp** | DuckDB direkt | Community |
| **genai-toolbox** (Google) | Multi-DB (PG, MySQL, MSSQL, Neo4j, BigQuery) | googleapis |
| **datasette-mcp** | Datasette JSON API | Community |

### Finance / Accounting

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **Alpha Vantage MCP** | Real-time + historische Kurse | mcp.alphavantage.co |
| **Financial Datasets MCP** | Income Statements, Balance Sheets, Cash Flow | github.com/financial-datasets |
| **EODHD MCP** | Historische Kurse, Fundamentaldaten | eodhd.com |
| **Alpaca MCP** | Trading, Datenanalyse | github.com/alpacahq |
| **LSEG MCP** | Institutionelle Marktdaten (Enterprise) | lseg.com |
| **Pennylane MCP** | Buchhaltung + Finanzen | Community |
| **Norman Finance MCP** | Accounting + Steuern | Community |
| **LedgerAI MCP** | Ledger CLI Double-Entry Accounting | Community |
| **Xero MCP** | Xero Accounting API | Community |
| **Stripe MCP** | Payment-Daten | stripe.com |

### Cyber-Security

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **pentest-mcp** (DMontgomery40) | Nmap, Nikto, SQLMap, Hydra, JtR | github.com |
| **mcp-for-security** (cyproxio) | SQLMap, FFUF, Nmap, Masscan | github.com |
| **PentestThinkingMCP** | Reasoning-Engine, Attack-Path-Planning | github.com |
| **pentestMCP** (ramkansal) | 20+ Security-Tools | github.com |
| **Kali Linux MCP** (offiziell) | Nmap, Gobuster, Nikto, Hydra, Metasploit | Kali-Paket |
| **secops-mcp** | All-in-one Security Toolbox | Community |
| **MCP Security Auditor** | npm Dependency Audit | Community |

### DevOps / Incident Management

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **incident.io MCP** | Incident Management (MIT-Lizenz) | github.com/incident-io |
| **PagerDuty MCP** | Alerting, On-Call | Offizielles Plugin |
| **Azure DevOps MCP** | Work Items, Repos, PRs | github.com/microsoft |
| **Prometheus MCP** | Metriken-Abfrage | Community |
| **Grafana MCP** | Dashboard-Integration | Community |

### Customer Support

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **Gorgias MCP** | E-Commerce Helpdesk | Community |
| **Zendesk MCP** | Ticket-Management | Community |
| **Intercom MCP** | Chat-Support | Community |

### Marketing / Social Media

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **Postiz MCP** | 13+ Social Plattformen, Open Source | postiz.com |
| **Ayrshare MCP** | 13+ Social APIs | ayrshare.com |
| **OpenTweet MCP** | Twitter/X Lifecycle | Community |
| **Vista Social MCP** | 15+ Netzwerke | Community |
| **LinkedIn MCP** | LinkedIn Posts | Community |

### Legal

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **LegalZoom MCP** | Attorney Consultation (proprietaer) | legalzoom.com/mcp/claude/v1 |

### Voice / Telephony

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **Retell AI MCP** | Voice-Agent, Anrufsteuerung | retellai.com |
| **Vapi MCP** | Voice-Agent API | vapi.ai |
| **Vonage Telephony MCP** | Anrufe, SMS, SIP | developer.vonage.com |
| **VoiceMode MCP** | Sprachkonversation mit Claude | github.com/mbailey |

### Produktivitaet / Allgemein

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **Google Drive MCP** | Dateizugriff | google |
| **Google Calendar MCP** | Kalender (bereits in Bridge) | google |
| **Gmail MCP** | Email (bereits in Bridge) | google |
| **Slack MCP** | Messaging (bereits in Bridge) | slack |
| **Notion MCP** | Knowledge-Base | notion |
| **Todoist MCP** | Task-Management | todoist |
| **Obsidian MCP** | Vault-Management | Community |

---

## 4. Empfehlungen: Was die Bridge integrieren sollte

### Sofort (bereits verfuegbar, hoher Impact)

| Was | Warum | Aufwand |
|---|---|---|
| **pagerduty** Plugin installieren | DevOps-Spec referenziert PagerDuty-Integration | `claude plugin install pagerduty` |
| **sentry** Plugin installieren | Error-Tracking fuer DevOps | `claude plugin install sentry` |
| **semgrep** Plugin installieren | SAST fuer Cyber-Security | `claude plugin install semgrep` |
| **data** Plugin installieren | Datenanalyse fuer Big Data | `claude plugin install data` |
| **postman** Plugin installieren | API-Testing fuer CyberSec/DevOps | `claude plugin install postman` |
| **legalzoom** Plugin (manuell) | `/review-contract` Workflow | Manueller Clone via HTTPS |

### Kurzfristig (MCP-Server konfigurieren)

| Was | Warum | Aufwand |
|---|---|---|
| **Financial Datasets MCP** | Finance-Spec braucht Fundamentaldaten | MCP-Config in .mcp.json |
| **Alpha Vantage MCP** | Finance-Spec Fallback-Datenquelle | MCP-Config |
| **incident.io MCP** | DevOps-Spec Incident-Management | MCP-Config (MIT-Lizenz) |
| **Postiz MCP** | Marketing-Spec Social Publishing (Phase C) | MCP-Config + Postiz Self-Host |
| **pentest-mcp** | CyberSec-Spec zusaetzliche Security-Tools | MCP-Config |

### Mittelfristig (evaluieren)

| Was | Warum |
|---|---|
| **duckdb-mcp** | Wenn DuckDB als MCP statt Python-Import sinnvoller |
| **Xero/Pennylane MCP** | Buchhaltungs-Backend-Alternative zu eigenem Modell |
| **Prometheus/Grafana MCP** | DevOps Monitoring-Integration |
| **Obsidian MCP** | Synergie mit Knowledge Engine |

---

## 5. Quellen

- [Claude Code Plugin Docs](https://code.claude.com/docs/en/discover-plugins)
- [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official)
- [PulseMCP — 10.400+ MCP Server](https://www.pulsemcp.com/servers)
- [Glama MCP Registry](https://glama.ai/mcp/servers)
- [Smithery MCP Marketplace](https://smithery.ai)
- [mcpservers.org](https://mcpservers.org)
- [awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers)
- [best-of-mcp-servers — 410 Ranked](https://github.com/tolkonepiu/best-of-mcp-servers)
- [SkillsMP — Multi-Agent Skills](https://skillsmp.com)
- [awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills)
- [buildwithclaude.com — 488+ Extensions](https://buildwithclaude.com)
- [awesome-claude-plugins — 43 Marketplaces, 834 Plugins](https://github.com/Chat2AnyLLM/awesome-claude-plugins)
