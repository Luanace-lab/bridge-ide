# DEVOPS & INCIDENT MANAGEMENT PLATFORM SPEC

Stand: 2026-03-14
Autor: Viktor (Operative Projektleitung BRIDGE)
Revision: R3 — Battle-Review 3 Runden abgeschlossen
Status: FREIGEGEBEN — Implementierungsgrundlage

---

## 1. Ziel

Die BRIDGE wird um eine DevOps- und Incident-Management-Plattform erweitert. Agents ueberwachen Systeme proaktiv, erkennen Anomalien, koordinieren Incident Response und fuehren Runbooks aus — lokal orchestriert, ueber alle Kanaele.

### 1.1 Produkt-Differenzierung

Warum die BRIDGE statt PagerDuty ($32k+/Jahr), incident.io ($27k/Jahr bei 50 Usern) oder manueller Incident Response:

1. **Self-Hosted + AI-First** — keine Cloud-Abhaengigkeit fuer die Kernlogik. Monitoring, Alerting, Incident-Koordination laufen lokal. Kein Vendor-Lock-in.
2. **Multi-Agent-Koordination nativ** — nicht ein AI-Feature auf einem Alerting-Tool, sondern Agents als Kern: ein Agent diagnostiziert, einer kommuniziert, einer fuehrt Runbooks aus. Die Bridge ist die einzige Plattform mit nativer Multi-Agent-Orchestrierung.
3. **Keine Plattformgebuehr** — LLM-API-Kosten pro Incident. Ein typischer Incident kostet $1-5 statt $27k/Jahr Lizenz.
4. **5 Kommunikationskanaele** — Email, Slack, Telegram, WhatsApp, Telefon. PagerDuty hat 3 (Email/Slack/SMS). incident.io hat 2 (Slack/Email).
5. **Bereits funktionale Infrastruktur** — Health-Monitor, Cron-Engine, Task-System, Whiteboard mit Alert-Severity, Agent-Health mit Auto-Restart, n8n-Workflow-Integration. Die Bausteine existieren — es fehlt die Komposition.
6. **Security-Diagnostik inklusive** — AASE MCP Tools fuer Security-Incident-Analyse. Kein anderes Incident-Management-Tool hat eingebaute Security-Assessment-Faehigkeiten.
7. **Incident Memory** — Knowledge Engine speichert Incident-Resolutions persistent. Agents lernen aus vergangenen Incidents ("Wissensabruf vor Handlung").

### 1.2 Zielgruppen

- DevOps-Teams (5-50 Personen) die On-Call-Rotationen und Incident Response managen
- SREs die Alert Fatigue reduzieren wollen (60-90% aller Alerts sind Noise)
- KMU mit eigener Infrastruktur aber ohne dediziertes NOC
- Startups die PagerDuty-Kosten nicht rechtfertigen koennen

### 1.3 6-Monats-Vision

In 6 Monaten soll ein User:

1. Monitoring-Quellen anbinden (Prometheus, Grafana, Custom HTTP-Health-Checks)
2. Alert-Regeln definieren (Schwellenwerte, Anomalien, Kombinationsbedingungen)
3. On-Call-Rotation konfigurieren
4. Bei Incident: Agent triagiert automatisch (Severity, betroffene Services, historische Aehnlichkeit)
5. Agent fuehrt diagnostische Runbooks aus (Logs pruefen, Metriken korrelieren, Health-Checks)
6. Agent kommuniziert Status-Updates ueber konfigurierte Kanaele
7. Agent schlaegt Remediation vor basierend auf Incident Memory
8. Nach Resolution: automatisches Postmortem mit Timeline, Root Cause, Action Items

---

## 2. Verifizierter Ist-Zustand

### 2.1 Was die BRIDGE heute hat (verifiziert im Code)

| Faehigkeit | Tool/Modul | Details |
|---|---|---|
| Health-Monitoring | `daemons/health_monitor.py` | 60s-Intervall, Alert-Cooldown 300s, Severity ok/warn/critical/recovery |
| Agent-Health | `daemons/agent_health.py` | Heartbeat-Check, tmux-Session-Alive, Auto-Restart bei Crash, Context-Threshold-Alerts (80/90/95%) |
| Cron-Engine | `bridge_cron_create/list/delete` | Zeitgesteuerte Actions: `send_message` oder `http`. Cron-Expressions. |
| Loop-Engine | `bridge_loop` | Wiederkehrende Prompts (5m, 2h, 1d) |
| Task-System | `bridge_task_create/claim/ack/done/fail/checkin/update` | Vollstaendiger Task-Lifecycle fuer Incident-Tickets |
| Whiteboard | `bridge_whiteboard_post/read/delete` | Typen: status, blocker, result, **alert**, escalation_response. Severity: info, warning, **critical** |
| Eskalation | `bridge_escalation_resolve` | Eskalations-Aufloesung |
| Scope-Locking | `bridge_scope_lock/unlock/check` | Verhindert Konflikte bei paralleler Arbeit |
| Approval-System | `bridge_approval_request/check/wait` | Human-in-the-Loop fuer kritische Aktionen |
| Email | `bridge_email_send/execute/read` | Mit Approval-Flow |
| Slack | `bridge_slack_send/execute/read` | Mit Approval-Flow |
| Telegram | `bridge_telegram_send/execute/read` | Mit Approval-Flow |
| WhatsApp | `bridge_whatsapp_send/execute/read` | Mit Approval-Flow, Whitelist |
| Telefon | `bridge_phone_call/speak/listen/hangup` | Stubs — kein Backend (wie in Voice-Spec dokumentiert) |
| n8n-Workflows | `bridge_workflow_compile/deploy/execute` | Webhook-basierte Runbook-Ausfuehrung |
| Knowledge Engine | `bridge_knowledge_read/write/search` | Persistentes Incident-Wissen |
| Context-Save | `bridge_save_context` | Agent-Zustand sichern |
| Research | `bridge_research` | Web-Recherche fuer Incident-Kontext |
| Vision/Desktop | `bridge_vision_analyze/bridge_desktop_observe` | Visuelle Verifikation |
| Git-Integration | `bridge_git_*` | Branch, Commit, Push fuer Hotfixes |
| AASE | `aase_api_scan/attack/recon/web_scan` | Separater MCP, Security-Diagnostik |

### 2.2 Was NICHT vorhanden ist

| Faehigkeit | Status |
|---|---|
| Alert-Routing und Escalation Policies | NICHT VORHANDEN |
| On-Call-Schedule-Management | NICHT VORHANDEN |
| Incident-Datenmodell (Timeline, Status, Assignee, Postmortem) | NICHT VORHANDEN |
| Status-Page-Generator | NICHT VORHANDEN |
| Prometheus/Grafana-Alert-Webhook-Empfang | NICHT VORHANDEN (Webhook-Infrastruktur aus Voice-Spec nutzbar) |
| Automatische Alert-Korrelation (Noise Reduction) | NICHT VORHANDEN |
| Runbook-Bibliothek | NICHT VORHANDEN (n8n-Workflows existieren als Engine) |
| Postmortem-Generator | NICHT VORHANDEN |

### 2.3 Externe MCP-Server (verfuegbar, Produktionsreife variiert)

| MCP-Server | Faehigkeit | Quelle |
|---|---|---|
| **incident.io MCP** | Incident-Management, Slack-native | MIT-Lizenz, GitHub |
| **PagerDuty MCP** | Alert-Routing, On-Call, Escalation | Offizielles Plugin |
| **Azure DevOps MCP** | Azure Monitor Integration | Open Source, Microsoft |

---

## 3. Diagnostizierte Hauptprobleme

### 3.1 Keine Komposition der Bausteine

Die Bridge hat Health-Monitor, Cron, Tasks, Whiteboard, Multi-Channel, Knowledge Engine, n8n — alles einzeln funktional. Aber es gibt keinen Incident-Workflow, der diese Bausteine zusammenfuehrt: Alert → Triage → Diagnose → Kommunikation → Remediation → Postmortem.

### 3.2 Kein Incident-Datenmodell

Es gibt kein `Incident`-Objekt mit Timeline, Status, Assignee, betroffenen Services, Severity, Resolution.

### 3.3 Keine Alert-Korrelation

Wenn Prometheus 50 Alerts gleichzeitig feuert (weil ein Upstream-Service down ist), braucht es Korrelation. Die Bridge hat keinen Mechanismus dafuer.

### 3.4 Kein On-Call-Management

Wer wird wann benachrichtigt? Eskalation nach 5 Minuten an wen? Rotationsplaene? Fehlend.

---

## 4. Zielarchitektur

### 4.1 Grundsatz

Die Incident-Plattform ist eine Komposition bestehender Bridge-Bausteine plus neuer Incident-spezifischer Module. Keine Neuerfindung — Orchestrierung des Vorhandenen.

### 4.2 Incident-Datenmodell

```json
{
  "incident_id": "inc_abc123",
  "title": "API Response Time > 5s",
  "severity": "critical",
  "status": "investigating",
  "source": {"type": "prometheus", "alert_name": "APIHighLatency", "labels": {"service": "api-gateway"}},
  "assignee": "oncall:devops-team",
  "timeline": [
    {"ts": "2026-03-14T10:00:00Z", "event": "alert_received", "details": "Prometheus alert fired"},
    {"ts": "2026-03-14T10:00:05Z", "event": "triage_started", "agent": "incident_agent"},
    {"ts": "2026-03-14T10:00:30Z", "event": "diagnosis", "details": "Database connection pool exhausted"},
    {"ts": "2026-03-14T10:01:00Z", "event": "runbook_executed", "runbook": "restart_db_pool"},
    {"ts": "2026-03-14T10:02:00Z", "event": "resolved", "details": "Latency normalized"}
  ],
  "affected_services": ["api-gateway", "postgres-primary"],
  "related_alerts": ["inc_def456"],
  "postmortem": null,
  "created_at": "2026-03-14T10:00:00Z",
  "resolved_at": "2026-03-14T10:02:00Z",
  "ttd_s": 5,
  "ttr_s": 120
}
```

Status-Flow: `triggered` → `acknowledged` → `investigating` → `mitigating` → `resolved` → `postmortem_pending` → `closed`

### 4.3 Alert-Pipeline

```
Prometheus/Grafana/Custom
  → Webhook an Bridge: POST /incidents/webhook (Rate-Limited: max 100 req/min)
  → Maintenance-Window-Check: aktives Fenster? → Suppression, kein Incident
  → Deduplizierung: gleicher Alert (Name + Labels) innerhalb 5 Min? → Zaehler erhoehen, kein neuer Incident
  → Flap-Detection: >3 Zustandswechsel in 10 Min? → als "flapping" markieren, 1 Incident
  → Korrelation Stufe 1 (regelbasiert, KEIN LLM): Alerts mit gleichen Labels innerhalb 60s = ein Incident
  → Severity-Bestimmung (aus Alert-Labels, regelbasiert)
  → On-Call-Lookup → Benachrichtigung (erst Slack, nach 5 Min Telegram, nach 10 Min Telefon)
  → NUR bei unbekanntem Pattern oder komplexer Triage: LLM-Agent-Analyse
```

Architekturprinzip: **Regelbasierte Vorfilterung fuer bekannte Patterns. LLM nur fuer unbekannte Incidents.** Das verhindert Kostenexplosion bei hohem Alert-Volumen.

### 4.4 Agent-Modi

#### Default: Single-Agent-Modus

Ein Agent uebernimmt alles: Triage, Diagnose, Kommunikation, Runbook-Ausfuehrung, Postmortem.

#### Kostenmodell

Architekturprinzip: Regelbasierte Alerts kosten $0 LLM-API. Nur echte Triage/Analyse braucht LLM.

| Modus | LLM-Kosten | Anwendungsfall |
|---|---|---|
| Bekannter Alert (regelbasiert) | **$0** | Deduplizierung, Korrelation, Auto-Resolve — kein LLM-Call |
| Unbekannter Incident (LLM-Triage) | $1 - $5 | Neue Pattern, komplexe Diagnose |
| Postmortem-Draft | $2 - $5 | Timeline + Hypothesen generieren |

TCO bei realistischem Volumen:

| Alerts/Tag | Regelbasiert (90%) | LLM-Triage (10%) | LLM-Kosten/Monat |
|---|---|---|---|
| 100 | 90 × $0 | 10 × $2 = $20/Tag | **$600** |
| 500 | 450 × $0 | 50 × $2 = $100/Tag | **$3.000** |
| 1000 | 900 × $0 | 100 × $2 = $200/Tag | **$6.000** |

Cost-Ceiling: Konfigurierbar. Default: $50/Tag. Bei Ueberschreitung: nur noch regelbasierte Verarbeitung, LLM-Triage wird pausiert.

Vergleich PagerDuty: $32k/Jahr ist ein All-inclusive-Preis (Infrastruktur, Support, Mobile App, SOC2). Bridge hat keine Plattformgebuehr, aber LLM-Kosten + Self-Hosting-Aufwand. Bei <500 Alerts/Tag ist Bridge guenstiger. Bei >1000 Alerts/Tag ist PagerDuty kompetitiv.

### 4.5 On-Call-Management

```json
{
  "schedule_id": "oncall_devops",
  "name": "DevOps Team",
  "rotation": "weekly",
  "members": [
    {"name": "Alice", "channels": [{"type": "telegram", "target": "+49..."}, {"type": "email", "target": "alice@..."}]},
    {"name": "Bob", "channels": [{"type": "slack", "target": "@bob"}, {"type": "phone", "target": "+49..."}]}
  ],
  "escalation_policy": {
    "timeout_s": 300,
    "escalate_to": "oncall_leads"
  },
  "business_hours": {"start": "08:00", "end": "22:00", "timezone": "Europe/Berlin"},
  "after_hours": {"escalate_immediately_to": "oncall_leads"}
}
```

Persistenz in Knowledge Engine unter `Shared/OnCall/`.

### 4.6 Runbook-Engine

Runbooks sind n8n-Workflows, die via `bridge_workflow_execute` ausgefuehrt werden.

Runbook-Interface:
- **Name**: z.B. `restart_service`
- **Parameter-Schema**: `{"service": "string", "host": "string"}` — Agent muss Parameter aus Incident-Kontext ableiten
- **Dry-Run**: Optional — zeigt was passieren wuerde ohne Ausfuehrung
- **Output-Format**: JSON mit `success`, `output`, `duration_s`
- **Fallback bei n8n-Unavailability**: Runbook-Schritte als manuelle Checkliste an On-Call-Person eskalieren

Beispiel-Runbooks:
- `restart_service(service, host)` — Service via SSH/Docker neustarten
- `check_database_connections(db_host)` — DB Connection Pool pruefen
- `scale_up(deployment, replicas)` — Kubernetes Replicas erhoehen
- `rollback_deployment(deployment, version)` — Letztes Deployment zurueckrollen

Agent entscheidet basierend auf Diagnose, welches Runbook ausgefuehrt wird. Bei kritischen Runbooks (Rollback, Scale-Down): Approval Gate.

### 4.7 Postmortem-Generator

Nach Resolution erstellt der Agent ein Postmortem-DRAFT (Status: `draft`, NICHT `accepted`):

1. **Timeline** — automatisch aus Incident-Events
2. **Root Cause Hypothesen** — Agent-Analyse basierend auf Logs, Metriken, Diagnose-Ergebnissen. Markiert als "Hypothese", nicht als Fakt. Konfidenz-Level pro Hypothese.
3. **Impact** — Dauer, betroffene Services, betroffene User (geschaetzt)
4. **Action Items** — Agent schlaegt praventive Massnahmen vor (NICHT verbindlich bis Human-Review)
5. **Lessons Learned** — gespeichert in Knowledge Engine fuer zukuenftige Incidents

**Human-Review ist PFLICHT** bevor Postmortem auf `accepted` gesetzt wird. LLMs koennen kausale Zusammenhaenge in verteilten Systemen nicht zuverlaessig beweisen. Sie koennen Hypothesen formulieren — der Mensch validiert.

Format: Markdown → PDF via Report-Engine.

### 4.8 Fehlerbehandlung

Uebernahme aus dem gemeinsamen Job-Framework:

| Parameter | Default |
|---|---|
| `alert_correlation_window_s` | 60 |
| `escalation_timeout_s` | 300 |
| `runbook_timeout_s` | 300 |
| `max_runbook_retries` | 2 |
| `incident_auto_close_after_s` | 86400 (24h) |

| Fehler | Verhalten |
|---|---|
| Monitoring-Quelle nicht erreichbar | Alert `monitoring_source_unreachable`, Incident-Agent wird informiert |
| On-Call-Person antwortet nicht | Eskalation nach `escalation_timeout_s` an naechste Stufe |
| Runbook schlaegt fehl | Retry, bei erneutem Fehlschlag: Eskalation mit Fehlermeldung |
| Agent-Timeout | Incident wird `stale` markiert, naechster verfuegbarer Agent uebernimmt |

---

## 5. Nicht verhandelbare Anforderungen

### Technisch

1. Webhook-Empfang fuer Prometheus/Grafana Alerts (analog Voice-Spec: oeffentliche URL via ngrok/Cloudflare Tunnel fuer externe Monitoring-Quellen, localhost fuer interne).
2. Incident-Timeline ist append-only und nicht loeschbar (Audit-Trail).
3. Runbook-Ausfuehrung mit Approval Gate fuer destruktive Aktionen.
4. Deduplizierung + Korrelation + Flap-Detection reduzieren Alert-Volumen. Zielwert abhaengig von Alert-Profil des Users — kein pauschales 50%-Versprechen.

### Qualitaet

5. Jeder Incident hat ein automatisches Postmortem.
6. Incident Memory in Knowledge Engine — Agents pruefen historische Incidents vor Diagnose.
7. TTD (Time to Detect) und TTR (Time to Resolve) werden pro Incident getrackt.

### Produkt

8. On-Call-Rotation muss konfigurierbar sein (woechentlich, taeglich, custom).
9. Eskalation muss automatisch funktionieren (Timeout → naechste Stufe).
10. Status-Updates ueber alle konfigurierten Kanaele.

---

## 6. API-Spec

Alle Endpoints durch Bridge 3-Tier Auth geschuetzt.

### 6.1 Incidents

- `POST /incidents/webhook` — Alert-Empfang (Prometheus/Grafana/Custom)
- `GET /incidents` — alle Incidents (filterbar nach Status, Severity, Zeitraum)
- `GET /incidents/{id}` — Incident-Details mit Timeline
- `PUT /incidents/{id}/acknowledge` — Incident bestaerigen
- `PUT /incidents/{id}/resolve` — Incident loesen
- `GET /incidents/{id}/postmortem` — Postmortem abrufen

### 6.2 On-Call

- `GET /oncall/current` — aktuell zustaendige Person
- `GET /oncall/schedules` — alle Rotationsplaene
- `PUT /oncall/schedules/{id}` — Rotationsplan anpassen

### 6.3 Runbooks

- `GET /runbooks` — verfuegbare Runbooks auflisten
- `POST /runbooks/{id}/execute` — Runbook manuell ausfuehren

### 6.4 MCP-Tools (fuer Agents)

- `bridge_incident_create` — Incident manuell erstellen
- `bridge_incident_update` — Status/Severity aendern
- `bridge_incident_diagnose` — Diagnostik-Ergebnis eintragen
- `bridge_oncall_lookup` — Aktuell zustaendige Person abfragen

---

## 7. Umsetzungs-Slices

### Phase A — Incident-Kern

#### Slice A1 — Incident-Datenmodell + Alert-Webhook

- Incident-Modell (JSON auf Disk / DuckDB)
- Webhook-Endpoint fuer Prometheus Alertmanager
- Alert-Korrelation (zeitfenster-basiert)
- Incident-Status-Machine

#### Slice A2 — Deduplizierung + Maintenance-Windows

- Alert-Deduplizierung (gleicher Name + Labels innerhalb 5 Min = Zaehler, kein neuer Incident)
- Flap-Detection (>3 Zustandswechsel in 10 Min = 1 Incident als "flapping")
- Maintenance-Window-Konfiguration (Zeitfenster in dem Alerts suppressed werden)
- Rate-Limiting auf Webhook-Endpoint (100 req/min)

#### Slice A3 — On-Call + Eskalation

- On-Call-Schedule-Modell in Knowledge Engine
- Eskalations-Policies
- Multi-Channel-Benachrichtigung bei neuem Incident

### Phase B — Intelligenz

#### Slice B1 — Triage + Diagnose Agent

- Automatische Severity-Bestimmung
- Historische Incident-Suche in Knowledge Engine
- Diagnostik via Health-Checks und Log-Analyse
- Runbook-Vorschlag basierend auf Diagnose

#### Slice B2 — Runbook-Ausfuehrung

- n8n-Workflow-basierte Runbooks
- Approval Gate fuer destruktive Aktionen
- Ergebnis-Feedback in Incident-Timeline

### Phase C — Lifecycle

#### Slice C1 — Postmortem + Incident Memory

- Automatischer Postmortem-Generator
- Persistenz in Knowledge Engine
- Trend-Analyse (wiederkehrende Incidents, MTTR-Entwicklung)

#### Slice C2 — Status Pages

- Oeffentliche Status-Page-Generierung
- Automatische Updates bei Incident-Status-Aenderung
- HTML-Export als Standalone-Seite

### Phase D — Haertung

#### Slice D1 — Advanced Alert-Korrelation

- ML-basierte Anomaly Detection (optional)
- Cross-Service-Korrelation
- Predictive Alerting (Trend-basiert)

### Priorisierung

Phase A: Ohne Incident-Modell und Alerting keine Plattform.
Phase B: Der Kern — Agent-gestuetzte Triage und Runbook-Ausfuehrung.
Phase C: Nachhaltigkeit — Postmortems und Incident Memory.
Phase D: Intelligenz-Erweiterung.

### Abhaengigkeiten

- Webhook-Infrastruktur (geteilt mit Voice-Spec, Slice A0)
- Gemeinsames Job-Framework
- n8n fuer Runbook-Ausfuehrung (bereits integriert)

---

## 8. Synergien

| Komponente | Geteilt mit |
|---|---|
| Webhook-Infrastruktur | Voice-Secretary Spec |
| Job-Framework | Alle Specs |
| Report-Engine (Postmortem → PDF) | Alle Specs |
| Knowledge Engine (Incident Memory) | Alle Specs |
| Multi-Channel-Alerts | Voice-Secretary, Finance (Alerts) |
| AASE (Security-Diagnostik) | Cyber-Security Spec |
| n8n-Workflows (Runbooks) | Bestehende Bridge-Integration |
| DuckDB (Incident-Historie) | Big Data, Finance, Accounting |
| Health-Monitor | Bereits in Bridge vorhanden |
| Cron-Engine | Bereits in Bridge vorhanden |

---

## 9. Abgrenzung

### Was die Plattform NICHT ist

- Kein SIEM (kein Log-Ingestion im grossen Massstab, kein Splunk-Ersatz)
- Kein APM (kein Code-Level-Tracing, kein Datadog-Ersatz)
- Kein Monitoring-System (kein Prometheus-Ersatz — nutzt Prometheus als Quelle)
- Kein NOC (kein 24/7-Betrieb durch AI allein — Agents eskalieren an Menschen)

### Was sie IST

- Eine lokale, Agent-gestuetzte Incident-Management-Plattform
- Die bestehende Monitoring-Tools (Prometheus, Grafana) als Datenquellen nutzt
- Und Multi-Agent-Koordination fuer Triage, Diagnose, Kommunikation und Remediation bietet
- Die On-Call-Teams entlastet statt sie zu ersetzen

---

## 10. Test-Spec

### Acceptance Criteria

1. Prometheus Alertmanager Webhook wird korrekt empfangen und Incident erstellt in <5s
2. 10 gleichzeitige Alerts zum selben Service werden zu 1 Incident korreliert
3. On-Call-Person wird innerhalb von 30s ueber konfigurierten Kanal benachrichtigt
4. Eskalation erfolgt automatisch nach konfiguriertem Timeout
5. Runbook wird bei Diagnose-Match automatisch vorgeschlagen
6. Postmortem wird innerhalb von 60s nach Resolution generiert
7. Historischer Incident mit aehnlichem Pattern wird bei Triage gefunden

---

## 11. Marktrecherche-Quellen

Recherche durchgefuehrt am 2026-03-14.

- PagerDuty: $32k+/Jahr, AIOps, MCP-Plugin — pagerduty.com
- incident.io: $45/User/Monat, Slack-native, MCP-Server MIT-lizensiert — incident.io
- Rootly: AI-Powered, Slack-native — rootly.com
- OneUptime: Open Source, Self-Hosted, Monitoring + Incidents + Status Pages — oneuptime.com
- Grafana OnCall: OSS in Maintenance Mode seit 2025-03, Archivierung 2026-03-24 — grafana.com
- AWS DevOps Agent: Multi-Agent-Architektur (Lead + Sub-Agents) — infoq.com
- Azure SRE Agent: Memory System fuer vergangene Incidents — techcommunity.microsoft.com
- Alert Fatigue: 60-90% aller Alerts sind Noise — devops.com
- On-Call Burnout: 70% der SREs berichten Burnout — relvy.ai (Catchpoint 2025 Report)
- Claude Agent SDK SRE Cookbook — platform.claude.com
