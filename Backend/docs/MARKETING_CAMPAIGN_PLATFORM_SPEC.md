# MARKETING & CAMPAIGN MANAGEMENT PLATFORM SPEC

Stand: 2026-03-14
Autor: Viktor (Operative Projektleitung BRIDGE)
Revision: R3 — Battle-Review 3 Runden abgeschlossen
Status: FREIGEGEBEN — Implementierungsgrundlage

---

## 1. Ziel

Die BRIDGE wird um eine Marketing/Campaign-Management-Plattform erweitert. Agents erstellen Content, planen Kampagnen, publishen ueber alle Kanaele und tracken Performance — lokal orchestriert, aufbauend auf der Creator-Pipeline.

### 1.1 Produkt-Differenzierung

Warum die BRIDGE statt Hootsuite ($99-249/Monat), HubSpot ($800/Monat Pro) oder Buffer ($5/Kanal/Monat):

1. **Creator-to-Publish Pipeline** — die Bridge hat bereits: Video-Ingest → Transkription → Clip-Extraktion → Multi-Format-Export → Subtitle-Generierung. Kein Wettbewerber integriert Content-Produktion und Publishing in einem System.
2. **Multi-Channel nativ** — Email, Slack, Telegram, WhatsApp, Voice (TTS). Plus Social-Media-Publishing via Postiz MCP (Open Source, 13+ Plattformen). Kein Aufpreis pro Kanal.
3. **Keine Plattformgebuehr** — LLM-API-Kosten pro Content-Piece. Geschaetzt $0.05-$0.30 vs. $99-800/Monat.
4. **Agent-gestuetzte Content-Erstellung** — Agents schreiben Texte, erstellen Captions, schlagen Hashtags vor, optimieren pro Plattform. Multi-Agent: einer recherchiert, einer schreibt, einer reviewt.
5. **Self-Hosted + Privacy** — Content-Strategie, Analytics, Kundendaten bleiben lokal.
6. **Approval-Gate** — kein unkontrolliertes Posten. Jeder externe Post durchlaeuft Freigabe.
7. **Scheduling-Engine** — bridge_cron_create fuer beliebige Automationen. Nicht nur Post-Scheduling.

### 1.2 Zielgruppen

- Solo-Unternehmer und Freelancer die Content auf 3-5 Plattformen publizieren
- KMU-Marketing-Teams (1-5 Personen)
- Agenturen die Client-Content managen
- Creator die ihre Video-Pipeline mit Publishing verbinden wollen

### 1.3 6-Monats-Vision

In 6 Monaten soll ein User:

1. Social-Media-Accounts verbinden (via Postiz oder direkte APIs)
2. Content erstellen: Text, Bild-Beschreibung, Video-Clip (aus Creator-Pipeline)
3. Agent optimiert Content pro Plattform (Laenge, Hashtags, Format)
4. Content in Kalender planen (Scheduling via Cron)
5. Approval-Gate vor jedem Post
6. Multi-Plattform-Publishing (Instagram, X, LinkedIn, TikTok, YouTube, Facebook)
7. Performance-Tracking (Engagement, Reach — via Plattform-APIs)
8. Woechentlicher Performance-Report

---

## 2. Verifizierter Ist-Zustand

### 2.1 Was die BRIDGE heute hat

| Faehigkeit | Tool | Details |
|---|---|---|
| Creator-Pipeline | `bridge_creator_*` | Video-Ingest, Transkription, Clip-Export, Multi-Format (YouTube Short, Instagram Reel, Square, Landscape), SRT, Social Package |
| Email | `bridge_email_send` | Mit Approval |
| Telegram | `bridge_telegram_send` | Mit Approval + Whitelist |
| WhatsApp | `bridge_whatsapp_send/voice` | Mit Approval + Whitelist + TTS |
| Slack | `bridge_slack_send` | Mit Approval |
| Cron-Engine | `bridge_cron_create` | Zeitgesteuerte Aktionen |
| Knowledge Engine | `bridge_knowledge_*` | Content-Kalender, Kampagnen-Planung |
| n8n-Workflows | `bridge_workflow_execute` | Automation, 400+ Integrationen |

### 2.2 Was NICHT vorhanden ist

| Faehigkeit | Status |
|---|---|
| Social-Media-API-Integration (Instagram, X, LinkedIn, TikTok, YouTube) | NICHT VORHANDEN |
| Content Calendar UI | NICHT VORHANDEN |
| Campaign-Datenmodell | NICHT VORHANDEN |
| Analytics/Performance-Tracking | NICHT VORHANDEN |
| A/B-Testing | NICHT VORHANDEN |
| Content-Library / Asset-Management | NICHT VORHANDEN |
| Hashtag-Optimierung | NICHT VORHANDEN |

### 2.3 Verfuegbare MCP-Server und Tools

| Tool | Typ | Integration |
|---|---|---|
| **Postiz** | Open-Source Social Scheduler, 13+ Plattformen, MCP-Server | MCP-Config, Self-Hosted |
| **Mixpost** | Open-Source Social Management, One-Time-Payment | REST API |
| **Ayrshare** | Social Media API (13+ Plattformen in einem Endpoint) | REST API / MCP |

**Architekturentscheidung V1: n8n ZUERST, Postiz SPAETER.**

n8n ist bereits in die Bridge integriert (`bridge_workflow_execute`). n8n hat native Social-Media-Nodes fuer X, LinkedIn, Facebook, Instagram. Das ist der schnellere Pfad als Postiz-Integration (die 0% implementiert ist).

Postiz ist ein Self-Hosted Social Scheduler mit MCP-Server — aber: er existiert NIRGENDS im Bridge-Code (0 Treffer). Integration bedeutet: Postiz deployen, konfigurieren, MCP-Adapter schreiben/integrieren. Das ist 2-4 Wochen Aufwand.

V1-Pfad: n8n-Social-Nodes → Bridge-Cron-Scheduling → Approval-Gate → Publishing. Postiz als Phase C/D-Alternative wenn n8n-Nodes nicht ausreichen.

---

## 3. Zielarchitektur

### 3.1 Campaign-Datenmodell

```json
{
  "campaign_id": "cmp_abc123",
  "name": "Produktlaunch Q2 2026",
  "status": "active",
  "content_pieces": [
    {
      "content_id": "cnt_001",
      "type": "social_post",
      "text": "...",
      "media": ["/clips/launch_teaser_youtube_short.mp4"],
      "platforms": ["instagram", "linkedin", "x"],
      "scheduled_at": "2026-04-01T09:00:00Z",
      "status": "scheduled",
      "approval_status": "approved"
    }
  ],
  "channels": ["instagram", "linkedin", "x", "telegram", "email"],
  "created_at": "2026-03-14T10:00:00Z"
}
```

### 3.2 Content-Pipeline

```
Idee/Brief
  → Agent erstellt Content (Text, Caption, Hashtags)
  → Agent optimiert pro Plattform (Zeichenlimit, Format, Tone)
  → Wenn Video: Creator-Pipeline → Clip → Multi-Format-Export
  → Content in Kalender planen (bridge_cron_create)
  → Approval-Gate
  → Publishing via n8n-Social-Nodes / bridge_telegram_send / bridge_email_send
  → Performance-Tracking (Engagement via Plattform-API)
```

### 3.3 Agent-Modi

**Default: Single-Agent.** Ein Agent erstellt und plant Content. Kosten: $0.05-$0.30 pro Post.

**Opt-in: Content-Team.**
- Researcher-Agent — Trends, Wettbewerber, Themen-Recherche
- Writer-Agent — Content erstellen, pro Plattform optimieren
- Editor-Agent — Review, Tone-Check, Brand-Konsistenz

### 3.4 Kostenvergleich

| Loesung | 5 Social Accounts, 20 Posts/Monat | Kosten/Monat |
|---|---|---|
| Hootsuite (Professional) | $99 | **$99** |
| Buffer (Essentials) | $5 × 5 = $25 | **$25** |
| HubSpot (Marketing Pro) | $800 (3 Seats) | **$800** |
| **Bridge + n8n** | $0 Plattform + ~$4-6 LLM-API (+ Self-Hosting, Setup, Wartung — kein SLA, kein Managed Service) | **$4-6 LLM** |

TCO-Hinweis: Bridge ist guenstiger bei laufenden Kosten, aber erfordert technisches Setup. Buffer bei $25/Monat ist fuer nicht-technische User sofort nutzbar. Bridge gewinnt bei Datenschutz, Creator-Pipeline-Integration und Agentur-Skalierung.

### 3.5 Fehlerbehandlung

| Fehler | Verhalten |
|---|---|
| Social-API nicht erreichbar | Retry mit Backoff, Post wird "pending" |
| Postiz-Server nicht erreichbar | Fallback auf direkte Telegram/Email-Distribution |
| Media-Upload fehlgeschlagen | Retry, bei erneutem Fehler: Post ohne Media + Warnung |
| Approval abgelehnt | Agent ueberarbeitet Content basierend auf Feedback |
| Scheduled Post verpasst | Sofort posten + Warnung an User |

---

## 4. API-Spec

- `POST /marketing/campaigns` — Kampagne erstellen
- `GET /marketing/campaigns` — Kampagnen auflisten
- `POST /marketing/content` — Content-Piece erstellen
- `POST /marketing/content/{id}/schedule` — Content planen
- `POST /marketing/content/{id}/publish` — Content sofort publizieren
- `GET /marketing/analytics` — Performance-Metriken
- `GET /marketing/calendar` — Content-Kalender

MCP-Tools:
- `bridge_marketing_create_content` — Content generieren lassen
- `bridge_marketing_schedule` — Content planen
- `bridge_marketing_analytics` — Performance abrufen

---

## 5. Nicht verhandelbare Anforderungen

1. Approval-Gate vor jedem externen Post (konfigurierbar: immer, nur neue Plattformen, nur bei low confidence).
2. Kein unkontrolliertes Posten — Bridge-Approval-System enforced.
3. Content-Kalender ist persistent (Knowledge Engine oder DuckDB).
4. Multi-Format-Export aus Creator-Pipeline nahtlos nutzbar.
5. Postiz oder alternatives Social-Backend ist austauschbar (kein Vendor-Lock-in).

---

## 6. Umsetzungs-Slices

### Phase A — Social Publishing
- n8n-Social-Nodes als primaerer Publishing-Pfad (bereits integriert via bridge_workflow_execute)
- Content-Datenmodell
- Scheduling via bridge_cron_create
- Approval-Gate vor Publishing

### Phase B — Content-Erstellung
- Agent-gestuetzte Text-Erstellung
- Plattform-Optimierung (Zeichenlimits, Hashtags, Tone)
- Creator-Pipeline → Social Publishing Verbindung
- Template-System

### Phase C — Analytics + Kampagnen
- Performance-Tracking: V1 OHNE automatisches Analytics. Jede Plattform hat eigene Analytics-API mit separatem OAuth + Datenformat — das ist ein eigenstaendiges Projekt. V1: manuelle Eingabe oder Screenshot-basierte Analyse.
- Campaign-Datenmodell
- Woechentliche Performance-Reports
- A/B-Testing (2 Varianten, Performance vergleichen)

### Phase D — Haertung
- Content-Library / Asset-Management
- Evergreen-Content-Recycling
- Multi-Agent Content-Team
- Brand-Voice-Konsistenz via Knowledge Engine

### Priorisierung

Phase A: Ohne Publishing kein Marketing-Tool.
Phase B: Der Kern — AI-gestuetzte Content-Erstellung.
Phase C: Der Mehrwert — Datengetriebene Optimierung.
Phase D: Professionalitaet.

### Abhaengigkeiten

- Creator-Pipeline (CREATOR_PLATFORM_SPEC) fuer Video-Content
- n8n (bereits integriert) als Social-Publishing-Backend. Postiz als spaetere Alternative (Phase C/D).
- bridge_cron_create fuer Scheduling

---

## 7. Synergien

| Komponente | Geteilt mit |
|---|---|
| Creator-Pipeline (Video → Clips → Social) | Creator Spec (direkte Abhaengigkeit) |
| Multi-Channel (Telegram/WhatsApp/Email/Slack) | Voice-Secretary, Customer Support |
| Cron-Engine | DevOps, Finance, Voice-Secretary |
| Knowledge Engine (Content-Kalender, Brand-Voice) | Alle Specs |
| Approval-Gates | Alle Specs |
| Report-Engine (Performance Reports) | Alle Specs |

---

## 8. Abgrenzung

- Kein Social-Media-Management-Tool im Sinne von Hootsuite (keine Social Listening, kein Inbox-Management fuer Social DMs)
- Kein CRM (keine Kunden-Pipeline)
- Kein Ad-Management (keine Google Ads / Meta Ads Verwaltung)
- Kein Influencer-Management

---

## 9. Marktrecherche-Quellen

Recherche durchgefuehrt am 2026-03-14.

- Hootsuite: $30-249/Monat, OwlyWriter AI, 150M Datenquellen — hootsuite.com
- Buffer: Free-$5/Kanal, AI-Ideation — buffer.com
- HubSpot: $9-800/Monat, Breeze AI, Revenue Attribution — hubspot.com
- Postiz: Open Source, MCP-Server, 13+ Plattformen, Self-Hosted — postiz.com, github.com/gitroomhq/postiz-app
- Mixpost: Open Source, One-Time-Payment — mixpost.app
- Tool-Fragmentierung: 12-20 Tools pro Organisation, 65.7% Datenintegrationsprobleme — thedigitalbloom.com
- 8-12h/Woche Tool-Switching — beasleydirect.com
- AI-Marketing ROI: $5.44 pro $1.00 investiert (544% ueber 3 Jahre) — enrichlabs.ai
- Agentic AI Markt: $7.29B (2025), $9.14B (2026) — enrichlabs.ai
