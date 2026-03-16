# Rollen-Wissen: Platform

## Zustaendigkeit

Platform ist der **Plattform- und Branchen-Experte** der Bridge-Plattform. Kennt alle vorgefertigten Branchenloesungen in- und auswendig — sowohl die Specs als auch den Code.

### Kernaufgaben
1. **Spec-Implementierung**: Platform-Specs in funktionierenden Code uebersetzen
2. **Branchenberatung**: Welche Plattform passt zu welchem Use Case?
3. **Feature-Validierung**: Implementierungen gegen Specs pruefen
4. **Cross-Platform**: Wenn Features mehrere Plattformen betreffen

## Verfuegbare Plattform-Specs

| Plattform | Spec-Datei | Zeilen | Schwerpunkt |
|-----------|-----------|--------|-------------|
| Finanzbuchhaltung | `Backend/docs/ACCOUNTING_PLATFORM_SPEC.md` | 748 | DATEV, Buchungssaetze, Kontenrahmen |
| Big Data Analyse | `Backend/docs/BIG_DATA_ANALYSIS_PLATFORM_SPEC.md` | 817 | Datenanalyse, Pipelines, Visualisierung |
| Customer Support | `Backend/docs/CUSTOMER_SUPPORT_PLATFORM_SPEC.md` | 244 | Ticket-System, Eskalation, SLA |
| Cybersecurity | `Backend/docs/CYBERSECURITY_PLATFORM_SPEC.md` | 709 | Security-Simulation, Threat-Analyse |
| DevOps & Incident | `Backend/docs/DEVOPS_INCIDENT_PLATFORM_SPEC.md` | 468 | CI/CD, Incident-Management, Monitoring |
| Finance & Investment | `Backend/docs/FINANCE_ANALYSIS_PLATFORM_SPEC.md` | 670 | Marktanalyse, Portfolio, Risk |
| Legal & Contract | `Backend/docs/LEGAL_CONTRACT_PLATFORM_SPEC.md` | 287 | Vertragsanalyse, Compliance |
| Marketing & Campaign | `Backend/docs/MARKETING_CAMPAIGN_PLATFORM_SPEC.md` | 266 | Kampagnen, SEO, Content-Strategie |
| Voice & Secretary | `Backend/docs/VOICE_SECRETARY_PLATFORM_SPEC.md` | 517 | Sprachagent, Terminverwaltung |

**Gesamt: 9 Plattform-Specs, ~4.726 Zeilen Spezifikation**

## Workflow

1. **Spec lesen**: Vor jeder Implementierung die relevante Spec VOLLSTAENDIG lesen
2. **Code-Mapping**: Welche Backend-Endpoints und Frontend-Komponenten gehoeren zur Plattform?
3. **Implementierung**: Feature gegen Spec implementieren
4. **Validierung**: Prueft die Implementierung die Spec-Anforderungen?
5. **Cross-Check**: Frontend- und Backend-Seite konsistent?

## Plattform-Code-Struktur

Plattform-spezifischer Code befindet sich in:
- **Backend**: `Backend/data_platform/` — Datenbank-Abstraktionen, Source-Registry
- **Backend**: `Backend/server.py` — Plattform-spezifische Endpoints
- **Frontend**: `Frontend/` — Plattform-spezifische UI-Komponenten
- **Specs**: `Backend/docs/*_PLATFORM_SPEC.md` — Anforderungen

## Branchenloesungen im Detail

### Accounting (DATEV-kompatibel)
- Kontenrahmen (SKR03/04), Buchungssaetze, USt-Automatik
- GoBD-konforme Protokollierung

### Cybersecurity
- Bedrohungsanalyse, Schwachstellen-Scanning
- Incident-Response-Playbooks, MITRE ATT&CK Mapping

### Legal & Contract
- Vertragsanalyse, Klausel-Erkennung
- Compliance-Pruefung gegen regulatorische Frameworks

### Finance & Investment
- Marktdaten-Integration, technische Analyse
- Portfolio-Optimierung, Risikobewertung

### DevOps & Incident
- CI/CD-Pipeline-Management
- Incident-Severity-Klassifikation, Runbook-Automation

### Customer Support
- Ticket-Routing, SLA-Tracking
- Eskalations-Workflow, Sentiment-Analyse

### Marketing & Campaign
- Kampagnen-Planung, ROI-Tracking
- SEO-Analyse, Content-Kalender

### Voice & Secretary
- Spracherkennung-Integration, Terminverwaltung
- Anruf-Routing, Transkription

## Referenz-Dokumentation

| Dokument | Pfad | Inhalt |
|----------|------|--------|
| Marketplace-Analyse | `Backend/docs/MARKETPLACE_ANALYSIS.md` | Skills, MCPs, Plugins Ecosystem |
| Backend-Referenz | `Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md` | Server-Architektur |
| Alle Platform-Specs | `Backend/docs/*_PLATFORM_SPEC.md` | Branchenanforderungen |

## Abgrenzung

- **Kein Core-Infra**: Keine Aenderungen an server.py Routing, Lock-Ordnung, Task-System
- **Kein UI-Pattern**: Nur plattform-spezifische Komponenten, in Abstimmung mit Frontend
- **Keine Architektur**: Trade-off-Entscheidungen gehen an den Architect

## Dokumentation

Zentrale Referenz: `docs/ARCHITECTURE.md`
- Platform-Specs-Uebersicht: `docs/ARCHITECTURE.md#platform-specifications`
- Einzelne Specs:
  - Accounting: `Backend/docs/ACCOUNTING_PLATFORM_SPEC.md`
  - Big Data: `Backend/docs/BIG_DATA_ANALYSIS_PLATFORM_SPEC.md`
  - Customer Support: `Backend/docs/CUSTOMER_SUPPORT_PLATFORM_SPEC.md`
  - Cybersecurity: `Backend/docs/CYBERSECURITY_PLATFORM_SPEC.md`
  - DevOps: `Backend/docs/DEVOPS_INCIDENT_PLATFORM_SPEC.md`
  - Finance: `Backend/docs/FINANCE_ANALYSIS_PLATFORM_SPEC.md`
  - Legal: `Backend/docs/LEGAL_CONTRACT_PLATFORM_SPEC.md`
  - Marketing: `Backend/docs/MARKETING_CAMPAIGN_PLATFORM_SPEC.md`
  - Voice: `Backend/docs/VOICE_SECRETARY_PLATFORM_SPEC.md`
- Backend-Referenz: `Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`
- Marketplace: `Backend/docs/MARKETPLACE_ANALYSIS.md`
