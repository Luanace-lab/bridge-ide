# CUSTOMER SUPPORT & HELPDESK PLATFORM SPEC

Stand: 2026-03-14
Autor: Viktor (Operative Projektleitung BRIDGE)
Revision: R3 — Battle-Review 3 Runden abgeschlossen
Status: FREIGEGEBEN — Implementierungsgrundlage

---

## 1. Ziel

Die BRIDGE wird um eine Customer-Support-Plattform erweitert. Agents triagieren Tickets, beantworten Standard-Anfragen, eskalieren komplexe Faelle und koordinieren Support ueber alle Kanaele — lokal, AI-first, ohne Aufpreis pro Kanal.

### 1.1 Produkt-Differenzierung

Warum die BRIDGE statt Zendesk ($59-115/Agent/Monat + $50 AI Add-on), Freshdesk ($49-79/Agent + $29 AI) oder Intercom ($85-132/Agent + $0.99/Resolution):

1. **Self-Hosted + AI-First** — AI ist Kern-Architektur, nicht Add-on. Keine Cloud-Abhaengigkeit. Kundendaten bleiben lokal.
2. **Multi-Channel ohne Aufpreis** — Email, Slack, Telegram, WhatsApp, Telefon (Voice-Spec) in einer Plattform. Zendesk berechnet pro Kanal extra.
3. **Keine Plattformgebuehr** — LLM-API-Kosten pro Ticket. Geschaetzt $0.02-$0.10 pro Auto-Antwort vs. $50+/Agent/Monat bei Zendesk AI.
4. **Multi-Agent-Support** — spezialisierte Agents pro Support-Bereich (Billing-Agent, Technical-Agent, Onboarding-Agent). Nicht ein generischer Bot.
5. **Approval-Gates** — Agent antwortet nicht unkontrolliert. Kritische Antworten durchlaufen Freigabe. Kein Wettbewerber hat das.
6. **Task-Lifecycle mit Evidenz** — Tickets sind Bridge-Tasks mit Create → Claim → Ack → Done/Fail + Evidenzpflicht. Nicht nur "open/closed".
7. **Knowledge-basiert** — Agent durchsucht Knowledge Engine fuer Antworten. Kein separates Knowledge-Base-Tool noetig.

### 1.2 Zielgruppen

- KMU mit 1-20 Support-Mitarbeitern
- SaaS-Startups die skalieren ohne pro-Seat-Kosten zu explodieren
- E-Commerce-Unternehmen mit Multi-Channel-Anfragen
- Unternehmen mit Datenschutz-Anforderungen (Gesundheit, Recht, Finanzen)

### 1.3 6-Monats-Vision

In 6 Monaten soll ein User:

1. Support-Kanaele konfigurieren (Email-Adresse, Telegram-Bot, WhatsApp-Nummer, Slack-Channel)
2. Knowledge Base aufbauen (FAQ, Produkt-Docs, Standard-Antworten in Knowledge Engine)
3. Eingehende Anfragen werden automatisch triagiert: vordefinierte Kategorien (<20), Konfidenz-Score pro Ticket, Low-Confidence → Eskalation. Feedback-Loop: Mensch korrigiert Triage → LLM lernt (Few-Shot-Aktualisierung).
4. Standard-Anfragen werden automatisch beantwortet (mit Approval-Gate fuer erste N Antworten)
5. Komplexe Anfragen werden an menschlichen Support eskaliert mit Kontext-Zusammenfassung
6. Ticket-Lifecycle: Open → In Progress → Waiting → Resolved → Closed
7. Dashboard mit offenen Tickets, SLA-Status, Antwortzeiten

---

## 2. Verifizierter Ist-Zustand

### 2.1 Was die BRIDGE heute hat

| Faehigkeit | Tool | Details |
|---|---|---|
| Email-Empfang | `bridge_email_read` | Gmail MCP — Emails lesen, suchen |
| Email-Senden | `bridge_email_send` | Mit Approval-Gate |
| Slack | `bridge_slack_send/read` | Channel lesen, antworten, mit Approval |
| Telegram | `bridge_telegram_send/read` | Bot-Token, Whitelist, Approval, Kontakt-Mapping |
| WhatsApp | `bridge_whatsapp_send/read` | Go-Bridge, SQLite-Store, Whitelist, Approval, Voice |
| Task-System | `bridge_task_create/claim/ack/done/fail` | Vollstaendiger Lifecycle mit Evidenzpflicht |
| Knowledge Engine | `bridge_knowledge_read/write/search` | FAQ, Docs, Standard-Antworten |
| Semantic Memory | `bridge_memory_search/index` | Historische Ticket-Suche |
| Scheduling | `bridge_cron_create` | Regelmaessige Inbox-Checks |
| Approval | `bridge_approval_request/check/wait` | Kontrolle ueber Agent-Antworten |

### 2.2 Was NICHT vorhanden ist

| Faehigkeit | Status |
|---|---|
| Ticket-Datenmodell (Kunde, Kanal, Kategorie, SLA) | NICHT VORHANDEN |
| Auto-Triage (Kategorisierung, Prioritaet, Sentiment) | NICHT VORHANDEN |
| Auto-Response mit Knowledge-Base-Lookup | NICHT VORHANDEN |
| SLA-Management | NICHT VORHANDEN |
| Kunden-Datenbank (Historie, Praeferenzen) | NICHT VORHANDEN |
| Canned Responses / Templates | NICHT VORHANDEN |
| Multi-Channel-Inbox (unified view) | NICHT VORHANDEN |
| CSAT/NPS-Umfragen | NICHT VORHANDEN |

### 2.3 Integrierbarer Tool-Stack

| Tool | Zweck | Integration |
|---|---|---|
| **Zammad** | Open-Source Helpdesk, REST API, Docker | API-Integration als optionales Backend |
| **FreeScout** | Open-Source Zendesk-Alternative | API + Webhooks |
| **Open Ticket AI** | AI-Klassifizierung (Docker, lokale LLMs) | Docker, Ollama-basiert |

---

## 3. Zielarchitektur

### 3.1 Ticket-Datenmodell

```json
{
  "ticket_id": "tkt_abc123",
  "customer": {"name": "Max Mustermann", "email": "max@example.com", "channel": "email"},
  "subject": "Rechnung nicht erhalten",
  "category": "billing",
  "priority": "medium",
  "sentiment": "frustrated",
  "status": "open",
  "sla": {"first_response_target_m": 60, "resolution_target_h": 24},
  "messages": [
    {"ts": "2026-03-14T10:00:00Z", "from": "customer", "channel": "email", "content": "..."},
    {"ts": "2026-03-14T10:02:00Z", "from": "agent:support_bot", "channel": "email", "content": "..."}
  ],
  "bridge_task_id": "task_xyz789",
  "created_at": "2026-03-14T10:00:00Z",
  "first_response_at": null,
  "resolved_at": null
}
```

### 3.2 Support-Pipeline

```
Eingehende Nachricht (Email/Telegram/WhatsApp/Slack)
  → Cron-Job prueft Inbox (bridge_cron_create, alle 5 Min)
  → Agent triagiert: Kategorie, Prioritaet, Sentiment
  → Knowledge-Base-Lookup (bridge_knowledge_search)
  → Match gefunden?
    → JA: Auto-Antwort generieren → Approval Gate → Senden
    → NEIN: Ticket erstellen (bridge_task_create) → An menschlichen Support eskalieren
  → Benachrichtigung an Support-Team via konfiguriertem Kanal
```

### 3.3 Agent-Modi

**Default: Single-Agent.** Ein Agent triagiert und antwortet. Kosten: $0.02-$0.10 pro Ticket.

**Opt-in: Spezialisierte Agents.** Pro Support-Bereich ein Agent:
- Billing-Agent — Rechnungsfragen, Zahlungsprobleme
- Technical-Agent — Produktfragen, Bugs, Feature-Requests
- Onboarding-Agent — Einrichtungshilfe, Getting-Started

### 3.4 Kostenvergleich

| Loesung | 10 Agents, 500 Tickets/Monat | Kosten/Monat |
|---|---|---|
| Zendesk (Pro + AI) | $115 + $50 AI = $165/Agent | **$1.650** |
| Freshdesk (Pro + Freddy) | $49 + $29 AI = $78/Agent | **$780** |
| Intercom (Advanced + AI) | $85 + ~$500 AI-Resolutions | **$1.350** |
| **Bridge** | $0 Plattform + ~$25-50 LLM-API (+ Self-Hosting-Aufwand, kein SLA, kein Managed Support) | **$25-50 LLM** |

TCO-Hinweis: Bridge gewinnt bei tech-savvy Teams und Datenschutz-Anforderungen. Zendesk gewinnt bei Zero-Ops-Anforderung (KMU ohne DevOps).

### 3.5 Fehlerbehandlung

| Fehler | Verhalten |
|---|---|
| Kanal nicht erreichbar | Ticket wird erstellt, Retry bei naechstem Cron-Lauf |
| Spam/Abuse (100+ Emails in 5 Min) | Rate-Limiting pro Absender (max 10 Tickets/Stunde), Spam-Erkennung als Teil der Triage |
| LLM-Cost-Ceiling erreicht | Nur noch regelbasierte Triage, keine Auto-Responses bis Reset |
| Knowledge-Base leer | Keine Auto-Antwort, direktes Eskalieren |
| Approval abgelehnt | Agent ueberarbeitet Antwort oder eskaliert |
| SLA-Verletzung droht | Automatische Eskalation + Alert an Team-Lead |

---

## 4. API-Spec

- `POST /support/tickets` — Ticket manuell erstellen
- `GET /support/tickets` — Tickets auflisten (filterbar)
- `GET /support/tickets/{id}` — Ticket-Details
- `PUT /support/tickets/{id}/reply` — Antwort senden
- `PUT /support/tickets/{id}/status` — Status aendern
- `GET /support/stats` — SLA-Metriken, offene Tickets, Antwortzeiten

MCP-Tools:
- `bridge_support_triage` — Nachricht triagieren
- `bridge_support_reply` — Antwort mit Knowledge-Base-Kontext generieren
- `bridge_support_escalate` — An menschlichen Support eskalieren

---

## 5. Nicht verhandelbare Anforderungen

1. Kundendaten bleiben lokal.
2. Approval-Gate fuer automatische Antworten (konfigurierbar: immer, erste N, nur bei low confidence).
3. Jede Kundeninteraktion wird in Ticket-Historie gespeichert.
4. SLA-Tracking: First Response Time, Resolution Time.
5. Disclaimer bei Auto-Antworten optional konfigurierbar.
6. Kein unkontrolliertes Senden — alle outbound-Nachrichten durch Bridge-Approval-System.

---

## 6. Umsetzungs-Slices

### Phase A — Ticket-Kern
- Ticket-Datenmodell
- Multi-Channel-Inbox (Cron-basiert)
- Triage-Agent (Kategorie, Prioritaet)

### Phase B — Auto-Response
- Knowledge-Base-Lookup + Antwort-Generierung
- Approval-Gate-Integration
- Template-System fuer Standard-Antworten

### Phase C — Lifecycle
- SLA-Management
- Eskalations-Workflows
- Kunden-Historie
- CSAT-Umfragen nach Resolution

### Phase D — Haertung
- Zammad/FreeScout als optionales Backend
- Analytics-Dashboard
- Multi-Agent-Spezialisierung

---

## 7. Synergien

| Komponente | Geteilt mit |
|---|---|
| Multi-Channel (Email/Telegram/WhatsApp/Slack) | Voice-Secretary |
| Task-System (Ticket-Lifecycle) | Alle Specs |
| Knowledge Engine (FAQ) | Alle Specs |
| Approval-Gates | Alle Specs |
| Cron-Engine (Inbox-Checks) | DevOps (Alert-Checks), Finance (Kurs-Checks) |
| Semantic Memory (Ticket-Suche) | Big Data |

---

## 8. Abgrenzung

- Kein CRM (keine Sales-Pipeline, kein Lead-Scoring)
- Kein Live-Chat-Widget (V1 — Messaging-basiert, kein Echtzeit-Chat)
- Kein Call-Center (Telefon-Support via Voice-Secretary-Spec, nicht dieses Spec)

---

## 9. Marktrecherche-Quellen

Recherche durchgefuehrt am 2026-03-14.

- Zendesk: $59-115/Agent + $50 AI Add-on — zendesk.com
- Freshdesk: $15-79/Agent + $29 Freddy AI — freshdesk.com
- Intercom: $29-132/Agent + $0.99/Resolution — intercom.com
- Zammad: Open Source, REST API, Docker — zammad.com
- FreeScout: Open Source Zendesk-Alternative — freescout.net
- Open Ticket AI: AI-Klassifizierung, Docker, lokale LLMs — open-ticket-ai.com
- Helpdesk-Markt: $14.3B (2025) → $35B (2035), CAGR 9.4% — businessresearchinsights.com
- 65% der Kunden muessen Support mehrfach kontaktieren — chargebacks911.com
- AI koennte Contact-Center-Kosten um $80B bis 2026 senken — teneo.ai
- 87% der Senior Leaders planen AI-Investitionen fuer Customer Service — sparrowdesk.com
