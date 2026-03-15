# BIG DATA ANALYSIS PLATFORM SPEC

Stand: 2026-03-14
Autor: Viktor (Operative Projektleitung BRIDGE)
Revision: R3 — Battle-Review 3 Runden abgeschlossen (15 + 7 Befunde, alle adressiert)
Status: FREIGEGEBEN — Implementierungsgrundlage

---

## 1. Ziel

Die BRIDGE wird um eine Big-Data-Analyseplattform erweitert. Mehrere spezialisierte Agents arbeiten proaktiv zusammen, um grosse Datenmengen zuverlaessig zu analysieren — lokal, privat, ohne Cloud-Abhaengigkeit.

### 1.1 Produkt-Differenzierung

Warum die BRIDGE statt Julius AI ($24/mo), Tableau, oder manueller Analyse:

1. **Lokal + privat** — keine Daten verlassen den Rechner. Kein Upload zu Drittanbietern. Compliance by design.
2. **Multi-Agent-Analyse** — nicht ein einzelner Agent, sondern ein Team: Data Engineer, Analyst, Validator, Reporter. Jeder Agent hat eine Rolle, prueft die Arbeit der anderen.
3. **Proaktive Kommunikation** — Agents fragen einander, melden Anomalien, eskalieren Unsicherheiten. Kein stummer Pipeline-Durchlauf.
4. **Keine Plattformgebuehr** — keine monatlichen Abo-Kosten. API-Kosten der LLM-Provider fallen pro Nutzung an. Single-Agent-Modus minimiert Kosten fuer einfache Analysen.
5. **Heterogene Datenquellen** — CSV, Excel, JSON, SQLite, PostgreSQL, APIs, Logfiles, Markdown — alles in einer Plattform.
6. **Erklaerbare Ergebnisse** — jeder Analyseschritt wird dokumentiert, jede Schlussfolgerung begruendet. Kein Black-Box-Dashboard.
7. **Bridge-native** — nutzt vorhandene Bridge-Infrastruktur: Task-System, Knowledge Engine, Semantic Memory, Scope Locks, Approval Gates.

### 1.2 Zielgruppen

- KMU ohne Data-Team, die ihre Geschaeftsdaten verstehen wollen
- Solo-Unternehmer mit Daten in 10+ Tools (CRM, Buchhaltung, Shop, Marketing)
- Entwicklerteams, die Logs und Metriken analysieren muessen
- Researcher, die grosse Datensaetze systematisch auswerten

### 1.3 6-Monats-Vision

In 6 Monaten soll ein User:

1. Datenquellen anbinden (CSV hochladen, DB verbinden, API konfigurieren)
2. Eine Analysefrage in natuerlicher Sprache stellen
3. Ein Agent-Team zusammenstellen lassen (automatisch oder manuell)
4. Die Agents arbeiten sehen (Live-Status, Kommunikation, Zwischenergebnisse)
5. Einen validierten Report erhalten mit Visualisierungen, Quellverweisen und Konfidenzangaben
6. Den Report ueber Bridge-Kanaele teilen (Email, Slack, Telegram, PDF)

---

## 2. Verifizierter Ist-Zustand

### 2.1 Vorhandene Datenfaehigkeiten

Die BRIDGE besitzt heute:

#### Knowledge Engine (`knowledge_engine.py`, 658 Zeilen)

- Obsidian-inspirierter Vault: `BRIDGE/Knowledge/`
- Markdown-Notes mit YAML-Frontmatter
- Read/Write/Search/List/Delete auf Note-Ebene
- Projekt-/Agent-/Team-Scopes
- MCP-Tools: `bridge_knowledge_read`, `bridge_knowledge_write`, `bridge_knowledge_search`, `bridge_knowledge_list`, `bridge_knowledge_search_replace`

#### Semantic Memory (`semantic_memory.py`, 506 Zeilen)

- Vector + BM25 Hybrid-Retrieval
- sentence-transformers (`all-MiniLM-L6-v2`, 384 dim)
- Per-Scope-Indizes unter `~/.config/bridge/memory/`
- Chunk-basierte Indexierung (500 Zeichen, 50 Overlap)
- Max 50.000 Chunks pro Agent
- MCP-Tools: `bridge_memory_search`, `bridge_memory_index`, `bridge_memory_delete`

#### Agent-Kommunikation

- `bridge_send` / `bridge_receive` — direkter Nachrichtenaustausch
- `bridge_task_create` / `bridge_task_claim` / `bridge_task_done` — strukturierte Auftraege
- `bridge_whiteboard_post` / `bridge_whiteboard_read` — geteilte Notizen
- `bridge_scope_lock` / `bridge_scope_check` — exklusive Zugriffskontrolle
- `bridge_approval_request` / `bridge_approval_check` — Freigabe-Gates

#### Weitere relevante Tools

- `bridge_research` — Web-Recherche mit Freshness-Tracking
- `bridge_vision_analyze` — Screenshot-Analyse via Claude Vision
- `bridge_capability_library_list` — MCP/Plugin-Katalog
- `bridge_cron_create` — zeitgesteuerte Ausfuehrung

### 2.2 Was NICHT vorhanden ist

| Faehigkeit | Status |
|---|---|
| Datenquellen-Anbindung (CSV, Excel, SQLite, PostgreSQL) | NICHT VORHANDEN |
| Schema-Erkennung und -Validierung | NICHT VORHANDEN |
| SQL-Ausfuehrung gegen lokale Daten | NICHT VORHANDEN |
| Datenvisualisierung (Charts, Plots) | NICHT VORHANDEN |
| Report-Generierung (PDF, HTML, Markdown) | NICHT VORHANDEN |
| Analyse-Job-Pipeline (analog Creator-Jobs) | NICHT VORHANDEN |
| Agent-Rollen-Templates fuer Datenanalyse | NICHT VORHANDEN |
| Data-Lineage / Provenance-Tracking | NICHT VORHANDEN |
| Chunked Processing fuer grosse Dateien | NICHT VORHANDEN |
| Konfidenz-/Unsicherheitsangaben pro Ergebnis | NICHT VORHANDEN |
| Natural Language to SQL/Code | VORHANDEN (Agent-Faehigkeit, nicht plattformintegriert) |

### 2.3 Harte technische Grenzen

- **LLM-Kontextfenster**: Ein Agent kann maximal ~200k Tokens in einem Durchlauf verarbeiten. Ein 1-GB-CSV passt nicht in den Kontext.
- **Kein lokaler SQL-Engine**: Die Bridge hat heute keinen integrierten SQL-Executor.
- **Kein Datei-Upload-Workflow**: `CHAT_UPLOADS_DIR` existiert, aber nur fuer Chat-Attachments, nicht fuer strukturierte Datenquellen.
- **Semantic Memory ist textbasiert**: Der Embedding-Index arbeitet auf Text-Chunks, nicht auf tabellarischen Daten.

---

## 3. Diagnostizierte Hauptprobleme

### 3.1 Kein Datenzugriffspfad

Die Bridge hat Agents, aber keinen Weg, diese Agents an strukturierte Daten heranzufuehren. Ein Agent kann heute:
- Dateien lesen (Read-Tool)
- Code ausfuehren (Bash-Tool)
- Wissen speichern (Knowledge Engine)

Was fehlt:
- Schema-aware Datenzugriff
- SQL-Queries gegen lokale Daten
- Chunk-weises Lesen grosser Dateien
- Tabellarische Ergebnisformate

### 3.2 Kein Analyse-Workflow

Heute muesste ein User manuell:
1. CSV auf die Maschine kopieren
2. Einem Agent via Chat erklaeren, was er tun soll
3. Der Agent schreibt ein Python-Skript
4. Der User fuehrt es aus
5. Der Agent interpretiert die Ausgabe

Das ist nicht "Big Data Analyse". Das ist "ein Agent hilft beim Scripting".

### 3.3 Keine Validierung

Wenn ein Agent ein Ergebnis liefert ("Umsatz Q1 ist 1.2M"), gibt es keine Gegenprüfung. Kein zweiter Agent validiert die Abfrage. Kein Schema-Check. Keine Konfidenzangabe. Kein Audit-Trail.

### 3.4 Keine Skalierung fuer grosse Daten

Ein 500-MB-CSV in den LLM-Kontext zu schicken funktioniert nicht. Es braucht:
- Chunked Sampling
- SQL-basierte Aggregation
- Schema + Statistiken statt Rohdaten
- Iterative Vertiefung (Drill-Down)

### 3.5 Kein Report-Output

Die Bridge kann Nachrichten senden, aber keine strukturierten Reports erzeugen. Kein PDF, kein HTML-Dashboard, keine Visualisierungen.

---

## 4. Zielarchitektur

### 4.1 Grundsatz

Die Big-Data-Plattform ist kein separates Produkt. Sie ist eine Erweiterung der Bridge, die vorhandene Infrastruktur nutzt:

- **Task-System** fuer Analyse-Auftraege
- **Agent-Kommunikation** fuer Multi-Agent-Workflows
- **Knowledge Engine** fuer persistente Ergebnisse
- **Scope Locks** fuer exklusive Datenzugriffe
- **Approval Gates** fuer kritische Operationen

Neu hinzu kommt:
- **Data Layer** — Datenzugriff, Schema, SQL
- **Analysis Pipeline** — Job-basierte Analyse-Workflows
- **Visualization Engine** — Charts und Reports
- **Agent Roles** — spezialisierte Analyse-Agents

### 4.2 Data Layer

#### DuckDB als lokaler SQL-Engine

DuckDB ist eine geeignete Wahl fuer lokale analytische SQL-Queries:

- Direkte SQL-Queries auf CSV, Parquet, JSON, Excel ohne Import
- Spaltenorientiert, optimiert fuer analytische Workloads
- In-Process, kein separater Server noetig
- pip-installierbar (`pip install duckdb`)
- Unterstuetzt Window Functions, CTEs, Aggregationen
- Kann Dateien >RAM verarbeiten (streaming)

Warum DuckDB statt SQLite:
- SQLite ist row-oriented → langsam fuer Aggregationen ueber Millionen Zeilen
- DuckDB ist column-oriented → optimiert fuer `GROUP BY`, `JOIN`, `SUM`, `AVG` auf grossen Tabellen
- DuckDB kann direkt auf CSV/Parquet/JSON operieren ohne vorherigen Import

#### Datenquellen-Registry

Neue Entitaet: `data_source`

```json
{
  "source_id": "ds_abc123",
  "name": "Umsatzdaten 2025",
  "type": "csv",
  "path": "/data/umsatz_2025.csv",
  "schema": {
    "columns": [
      {"name": "datum", "type": "DATE", "nullable": false},
      {"name": "produkt", "type": "VARCHAR", "nullable": false},
      {"name": "umsatz", "type": "DOUBLE", "nullable": false},
      {"name": "region", "type": "VARCHAR", "nullable": true}
    ],
    "row_count": 145000,
    "size_bytes": 12400000
  },
  "registered_at": "2026-03-14T10:00:00Z",
  "last_profiled_at": "2026-03-14T10:00:05Z"
}
```

#### Schema-Profiling

Bei Registrierung einer Datenquelle wird automatisch:

- Schema erkannt (Spaltentypen, Nullable, Unique)
- Basisstatistiken berechnet (Min, Max, Mean, Median, NULL-Anteil, Distinct Count)
- Sample-Rows extrahiert (erste 5 + zufaellige 5)
- Ergebnis in Knowledge Engine persistiert

Dieses Profil ist der Kontext, den Agents erhalten — nicht die Rohdaten.

### 4.3 Analysis Pipeline

#### Analyse-Job-Modell

Das Creator-Spec (`CREATOR_PLATFORM_RELIABILITY_SPEC.md`) beschreibt ein aehnliches Job-Modell, das ebenfalls noch nicht implementiert ist. Beide Specs koennen ein gemeinsames Job-Framework nutzen. Struktur:

```json
{
  "job_id": "aj_abc123",
  "job_type": "analysis",
  "question": "Welches Produkt hat den hoechsten Umsatz pro Region in Q1 2025?",
  "data_sources": ["ds_abc123"],
  "status": "running",
  "stage": "execute",
  "agents": {
    "planner": "analyst_planner",
    "executor": "data_engineer",
    "validator": "qa_validator",
    "reporter": "report_writer"
  },
  "plan": { ... },
  "results": { ... },
  "validation": { ... },
  "report": { ... },
  "events": [ ... ]
}
```

#### Stage-Modell (V1: 5 Stages)

1. `plan` — Frage verstehen, Datenquellen identifizieren, Analyseplan erstellen
2. `execute` — SQL-Queries ausfuehren via DuckDB, Rohergebnisse sammeln
3. `validate` — Ergebnisse gegen Schema und Plausibilitaet pruefen, Konfidenz-Score vergeben
4. `report` — Erkenntnisse formulieren, Charts erzeugen, Report zusammenstellen
5. `publish` — Report ueber Kanaele verteilen (optional)

Spaetere Erweiterung (V2+): `plan` kann in `question_parse` + `source_identify` + `plan_create` + `plan_review` aufgespalten werden, wenn die Basis stabil laeuft.

#### Fehlerbehandlung und Timeouts

| Parameter | Default | Konfigurierbar |
|---|---|---|
| `max_retries_per_stage` | 3 | Ja |
| `stage_timeout_s` | 300 | Ja |
| `job_timeout_s` | 1800 | Ja |
| `max_query_duration_s` | 60 | Ja |
| `max_validation_rounds` | 3 | Ja (Validator → Engineer Ping-Pong) |

Verhalten bei Ueberschreitung:

- Stage-Timeout: Stage wird als `failed` markiert, Job geht in `failed` mit Fehlermeldung
- Job-Timeout: alle laufenden Stages werden abgebrochen, Job wird `failed`
- Max-Retries erreicht: Stage wird `failed`, kein weiterer Retry
- Max-Validation-Rounds erreicht: Ergebnis wird mit `confidence: low` und Warnung ausgeliefert statt Endlosschleife
- Agent-Ausfall (keine Antwort innerhalb stage_timeout): Job failt mit `agent_timeout` Fehler

Kein stiller Fehler. Jeder Fehler wird in `events.jsonl` geloggt und dem User angezeigt.

### 4.4 Agent-Modi

#### Default: Single-Agent-Modus

Fuer einfache Analysen (Aggregationen, Vergleiche, Zeitreihen) genuegt ein einzelner Agent. Dieser Agent uebernimmt alle Rollen: Plan erstellen, Query ausfuehren, Ergebnis validieren, Report schreiben.

Vorteile:
- Geringste API-Kosten (1 Agent-Session statt 4)
- Schnellste Ausfuehrung
- Geringste Komplexitaet

#### Opt-in: Multi-Agent-Modus

Fuer komplexe, mehrstufige Analysen (Szenario-Modellierung, Portfolio-Analyse, Korrelationsstudien) kann ein Agent-Team aktiviert werden. Aktivierung explizit via `"mode": "multi_agent"` im Analyse-Request.

#### Kostenmodell (Transparenz)

| Modus | Geschaetzte Kosten pro Query | Anwendungsfall |
|---|---|---|
| Single-Agent | $0.05 - $0.50 | Einfache Aggregation, Vergleich |
| Multi-Agent (4 Agents) | $0.50 - $3.00 | Mehrstufige Analyse, Szenario |
| Batch (10 Fragen, Single) | $0.50 - $5.00 | Serienanalyse |

Basis: Claude API-Kosten Stand Maerz 2026 ($15/$75 pro MTok Input/Output fuer Opus). Haiku oder Sonnet reduzieren Kosten um Faktor 5-10x.

### 4.5 Agent-Rollen (Multi-Agent-Modus)

#### Analyst Planner

- Empfaengt die User-Frage
- Liest Schema-Profile der Datenquellen
- Erstellt einen strukturierten Analyseplan
- Identifiziert Mehrdeutigkeiten und stellt Rueckfragen
- Kommuniziert den Plan an Data Engineer und Validator

#### Data Engineer

- Uebersetzt den Analyseplan in SQL-Queries
- Fuehrt Queries gegen DuckDB aus
- Liefert Rohergebnisse als strukturiertes JSON
- Meldet Fehler und unerwartete Ergebnisse

#### QA Validator

- Prueft jeden Query auf Korrektheit (Schema-Konformitaet, Join-Logik)
- Validiert Ergebnisse gegen Plausibilitaet (Summen, Grenzwerte, NULL-Anteile)
- Fuehrt Gegenqueries aus (z.B. Summe aller Teile = Gesamtsumme?)
- Gibt Konfidenz-Score pro Ergebnis (high/medium/low mit Begruendung)
- Kann den Data Engineer zurueckweisen und Neuberechnung fordern

#### Report Writer

- Empfaengt validierte Ergebnisse
- Erzeugt Visualisierungen (via matplotlib/plotly)
- Schreibt den Report (Markdown → PDF/HTML)
- Fuegt Quellverweise und Methodenbeschreibung ein

### 4.5 Kommunikationsfluss

```
User: "Welches Produkt hat den hoechsten Umsatz pro Region in Q1 2025?"
  │
  ├─→ Analyst Planner
  │     ├─ liest Schema-Profil von ds_abc123
  │     ├─ erstellt Plan: 2 Queries + 1 Aggregation
  │     ├─ bridge_send(to=data_engineer, content=plan)
  │     └─ bridge_send(to=qa_validator, content=plan)
  │
  ├─→ QA Validator
  │     ├─ reviewt Plan
  │     ├─ bridge_send(to=analyst_planner, content="Plan OK" oder "Aenderung noetig: ...")
  │
  ├─→ Data Engineer
  │     ├─ uebersetzt Plan in SQL
  │     ├─ fuehrt Queries aus via DuckDB
  │     ├─ bridge_send(to=qa_validator, content=results)
  │
  ├─→ QA Validator
  │     ├─ validiert Ergebnisse
  │     ├─ fuehrt Gegenquery aus
  │     ├─ bridge_send(to=report_writer, content=validated_results)
  │
  └─→ Report Writer
        ├─ erzeugt Charts
        ├─ schreibt Report
        └─ bridge_send(to=user, content=report_link)
```

### 4.6 Skalierungsstrategie fuer grosse Daten

#### Problem: LLM-Kontextfenster vs. Datenmenge

Ein 1-GB-CSV hat ~10 Millionen Zeilen. Das passt nicht in den Agent-Kontext.

#### Loesung: Schema + SQL + Sampling

Agents arbeiten NICHT auf Rohdaten. Agents arbeiten auf:

1. **Schema-Profile** — Spaltentypen, Statistiken, Sample-Rows (~500 Tokens)
2. **SQL-Ergebnisse** — Aggregierte Ergebnisse, nicht Einzelzeilen (~200 Tokens fuer ein GROUP BY)
3. **Iteratives Drill-Down** — Agent stellt Folgequeries basierend auf Zwischenergebnissen

#### Chunked Processing fuer Daten ausserhalb von DuckDB

Fuer unstrukturierte Daten (Logfiles, Freitext, Markdown-Korpora):

- Chunked Reading (analog Creator-Pipeline)
- Semantic Memory Indexierung fuer Suche
- Map-Reduce-Pattern: jeder Chunk wird einzeln analysiert, Ergebnisse werden aggregiert

### 4.7 Visualisierung

#### Minimal Viable: matplotlib

- Standard-Python-Library, keine externe Abhaengigkeit
- Erzeugt PNG/SVG
- Ausreichend fuer Bar Charts, Line Charts, Scatter Plots, Heatmaps

#### Ziel: plotly (interaktiv)

- HTML-basierte interaktive Charts
- Exportierbar als standalone HTML
- Einbettbar in Reports

#### Chart-Typen (Pflicht fuer V1)

- Bar Chart (horizontal/vertikal)
- Line Chart (Zeitreihen)
- Pie Chart (Anteile)
- Table (formatiert)
- Scatter Plot (Korrelationen)

### 4.8 Report-Engine

Reports werden als Markdown erzeugt und in folgende Formate konvertiert:

- **Markdown** — fuer Knowledge Engine und Agent-Kontext
- **HTML** — fuer Browser-Ansicht und Standalone-Export
- **PDF** — fuer formale Weitergabe (via weasyprint, bereits im Projekt)

Report-Struktur:

1. Executive Summary
2. Methodik (welche Daten, welche Queries, welche Agents)
3. Ergebnisse mit Visualisierungen
4. Validierung (Konfidenz-Scores, Gegenprüfungen)
5. Limitierungen und offene Fragen
6. Quellverweise (Data-Lineage)

---

## 4B. Integrierbarer Tool-Stack

### Grundsatz

Die Bridge baut nicht alles selbst. Sie integriert bewährte Tools, die Agents nutzen koennen. Die Bridge ist der Orchestrator — die Tools sind die Werkzeuge.

### 4B.1 Datenbank-MCP-Server (bereits verfuegbar, Stand Maerz 2026)

Agents koennen ueber MCP-Protokoll direkt auf externe Datenbanken zugreifen. Diese MCP-Server sind verfuegbar (Stabilitaet und Produktionsreife variiert, Community-Projekte sind nicht garantiert stabil):

| MCP-Server | Datenbank | Faehigkeiten | Integration |
|---|---|---|---|
| `postgres-mcp` (pgEdge) | PostgreSQL | Schema-Introspection, SQL-Queries, Constraints | MCP-Config in `.mcp.json` |
| `mysql-mcp` (designcomputer) | MySQL | List Tables, Read Data, Execute Queries | MCP-Config |
| `mssql-mcp` (RichardHan) | SQL Server | Schema Discovery, Secure Query | MCP-Config |
| `sqlite-mcp` | SQLite | Local DB, Schema + Query | MCP-Config |
| `bigquery-mcp` (LucasHild) | BigQuery | Schema Exploration, Query | MCP-Config + Auth |
| `snowflake-mcp` (isaacwasserman) | Snowflake | SQL Queries, Schema Context | MCP-Config + Auth |
| `supabase-mcp` (Community) | Supabase/PostgreSQL | Schema + Query + RLS | MCP-Config |
| `genai-toolbox` (Google) | Multi-DB (PG, MySQL, MSSQL, Neo4j, BigQuery, Spanner) | Connection Pooling, Auth, Multi-DB | MCP-Config |

**Bridge-Integration:** Diese MCP-Server koennen in die Bridge-Agent-Konfiguration eingetragen werden. Ein Data Engineer Agent kann dann direkt SQL gegen eine Produktions-DB ausfuehren — ohne eigene DB-Anbindung zu implementieren.

### 4B.2 Python Data Stack (lokal, Agent-nutzbar via Code-Execution)

Agents koennen Python-Code ausfuehren. Diese Libraries sind integrierbar:

| Tool | Zweck | Status |
|---|---|---|
| **DuckDB** | Analytische SQL auf CSV/Parquet/JSON/Excel | Primaerer SQL-Engine fuer lokale Dateien |
| **Polars** | DataFrame-Verarbeitung, 5-10x schneller als Pandas | Optional, fuer komplexe Transformationen |
| **Pandas** | DataFrame-Verarbeitung, breitestes Oekosystem | Bereits verfuegbar (numpy ist Dependency) |
| **matplotlib** | Statische Charts (Bar, Line, Scatter, Pie) | Standard-Library |
| **plotly** | Interaktive HTML-Charts | Optional, fuer Reports |
| **openpyxl** | Excel-Lesen/Schreiben | Fuer .xlsx Support |
| **weasyprint** | PDF-Generierung aus HTML/Markdown | Bereits im Projekt |

### 4B.3 Externe BI-Tools (optional, via API/Embedding)

Fuer fortgeschrittene Dashboards koennen Open-Source-BI-Tools lokal betrieben und via API angebunden werden:

| Tool | Zweck | Integration |
|---|---|---|
| **Metabase** | Visual Query Builder, Dashboards, Embedding | REST API, Docker, iframe-Embedding |
| **Evidence** | Code-First BI (SQL + Markdown → Reports) | CLI, Git-basiert |
| **Apache Superset** | Enterprise-BI, Dashboards, Charts | REST API, Docker |
| **Datasette** | Instant JSON API fuer SQLite/CSV | CLI, Docker, Plugin-System |

**Bridge-Integration:** Die Bridge startet diese Tools bei Bedarf als Docker-Container und leitet Agent-Queries an deren APIs weiter. Das ist NICHT fuer V1 — aber die Architektur muss diese Erweiterung ermoeglichen.

### 4B.4 Daten-Import-Werkzeuge

| Tool | Zweck | Agent-Nutzung |
|---|---|---|
| **csvkit** | CSV-Analyse, Konvertierung, SQL-auf-CSV | CLI, Agent via Bash |
| **jq** | JSON-Transformation | CLI, Agent via Bash |
| **xsv** | Schnelle CSV-Statistiken (Rust-basiert) | CLI, Agent via Bash |
| **dbt** | Daten-Transformation (SQL-basiert) | CLI, fuer fortgeschrittene Pipelines |

### 4B.5 CLI-native Faehigkeiten der gewrappten Engines

Die BRIDGE wrappt vier CLIs. Jede bringt eigene Data-Analyse-Faehigkeiten mit, die wir nutzen koennen:

#### Claude Code

- **Core-Tools**: Read, Write, Edit, Bash, Glob, Grep — kein eingebetteter Code-Interpreter
- **Python via Bash**: Agent schreibt Python-Script und fuehrt es via Bash-Tool aus. pandas, matplotlib, DuckDB sind nutzbar wenn installiert.
- **File-Handling**: Kann Dateien via Read-Tool lesen (Text, CSV, JSON). Binaerformate (Excel) nur via Python-Script.
- **MCP-Support**: Ja, vollstaendig. Kann externe MCP-Server nutzen.
- **Staerke**: Staerkstes Reasoning, breitestes Tool-Set, MCP-Support

Hinweis: Claude.ai (Web-App) hat ein separates "Analysis Tool" mit eingebettetem Code-Interpreter. Claude Code (CLI) hat dieses Tool NICHT. Analyse erfolgt ueber Bash + Python.

Bridge-Integration: Claude-Agents nutzen Read-Tool fuer Dateien und Bash-Tool fuer Python/DuckDB-Scripts.

#### Gemini CLI

- **BigQuery Engine Agent**: Natural Language → SQL gegen BigQuery
- **Cloud SQL Studio**: Gemini-assistiertes SQL direkt im Cloud SQL Editor
- **MCP-Support**: Database MCP fuer Natural Language Queries gegen lokale/remote DBs
- **File-Handling**: CSV/Excel-Verarbeitung, statistische Visualisierung
- **Staerke**: Google-Cloud-Integration, BigQuery-Anbindung

Bridge-Integration: Gemini-Agents koennen via MCP auf Datenbanken zugreifen. Fuer lokale Analyse: Gemini kann Python-Code ausfuehren via Shell.

#### Codex CLI

- **Code-Execution**: Sandboxed Code-Ausfuehrung lokal
- **MCP-Support**: UNKNOWN — Codex dokumentiert MCP-Support, Umfang und Stabilitaet nicht verifiziert
- **AGENTS.md**: Konfigurierbare Rollen und Tool-Zugriff
- **Staerke**: Schnelle iterative Code-Aenderungen, Sandbox-Sicherheit

Bridge-Integration: Codex-Agents koennen Python-Analyse-Skripte schreiben und ausfuehren. Sandbox-Modus schuetzt vor unbeabsichtigten Seiteneffekten.

#### Qwen Code

- **Tool Calling**: Native Function-Call-Support, MCP-kompatibel
- **Kontextfenster**: 256K nativ. Erweiterbarkeit auf 1M ist dokumentiert (Qwen3-Coder), aber UNKNOWN ob in Bridge-Konfiguration nutzbar.
- **Agentic Coding**: Speziell optimiert fuer mehrstufige Planung und Tool-Nutzung
- **Staerke**: Grosses Kontextfenster, kostenguenstig fuer parallele Analysen

Bridge-Integration: Qwen-Agents eignen sich fuer Hilfsaufgaben (Schema-Profiling, Datenbereinigung) wo der grosse Kontext vorteilhaft ist.

#### Strategische Nutzung in der Bridge

| Rolle | Empfohlene Engine | Begruendung |
|---|---|---|
| Analyst Planner | Claude | Staerkstes Reasoning, beste Planungsfaehigkeit |
| Data Engineer | Claude oder Codex | Code-Execution, SQL-Generierung |
| QA Validator | Claude | Kritisches Denken, Gegenprüfung |
| Schema Profiler | Qwen | Grosser Kontext, kostenguenstig fuer Massenverarbeitung |
| Report Writer | Claude | Beste Textqualitaet, Visualisierung |
| BigQuery/Cloud-Anbindung | Gemini | Native Google-Cloud-Integration |

Die BRIDGE muss die richtige Engine fuer die richtige Aufgabe einsetzen. Das ist der Multi-Engine-Vorteil gegenueber Single-Provider-Plattformen.

### 4B.6 Bridge-Native Integration fuer Agents

Die wichtigste Erkenntnis: Agents muessen diese Tools nicht manuell konfigurieren. Die Bridge stellt sie als MCP-Tools bereit (ZIEL — noch zu implementieren):

- `bridge_data_register` → Datenquelle registrieren und Schema-Profil erstellen
- `bridge_data_profile` → Schema-Profil einer registrierten Quelle abrufen
- `bridge_data_query` → SQL-Query gegen registrierte Datenquelle ausfuehren (via DuckDB)
- `bridge_data_analyze` → Analyse-Job starten
- `bridge_data_report` → Report-Status und Ergebnis abrufen

Der Agent muss nicht wissen, ob DuckDB, ein externer MCP-Server oder Pandas dahinterliegt. Die Bridge abstrahiert.

Hinweis: Diese 5 Tools bilden das kanonische Set. Die HTTP-API (Sektion 6) bietet zusaetzliche Endpunkte fuer Power-User (direktes SQL, Upload, Batch).

---

## 5. Nicht verhandelbare Anforderungen

### Infrastruktur

1. Alle Daten bleiben lokal. Kein Upload zu Cloud-Services fuer die Analyse.
2. DuckDB als SQL-Engine. Kein externer Datenbankserver noetig.
3. Analyse-Jobs sind persistent und audit-trailed. Resumierbarkeit (Fortsetzen ab Stage X) ist Phase-D-Ziel. V1 markiert unterbrochene Jobs als `failed` mit Retry-Option.
4. Jede SQL-Query wird geloggt mit Timestamp, Agent-ID und Ergebnis-Hash.
5. Grosse Dateien werden via Schema + SQL + Sampling verarbeitet, nie vollstaendig in den Agent-Kontext geladen.
6. Vorbedingung: server.py-Modularisierung (aktuell durch Codex in Arbeit) muss abgeschlossen sein. Data-API-Endpunkte leben in eigenem Modul, nicht in server.py.
7. Authentifizierung V1: localhost-only, kein Auth. Fuer spaetere Netzwerk-Exposition: API-Key oder Session-Token vorsehen.

### Datenquellen-Lebenszyklus

8. Re-Profiling ist manuell via `POST /data/sources/{id}/profile`.
9. Bei Query gegen eine nicht mehr existierende Datei: klarer Fehler "Datenquelle nicht mehr verfuegbar".
10. Kein automatisches File-Watch in V1. User muss Re-Profiling manuell ausloesen bei Datenaenderungen.

### Qualitaet

6. Jedes Analyseergebnis hat einen Konfidenz-Score (high/medium/low) mit Begruendung.
7. Ein QA-Validator-Agent prueft jedes Ergebnis vor Report-Erstellung.
8. Bei Konfidenz `low` wird der User explizit gewarnt.
9. Data-Lineage: jedes Ergebnis ist bis zur Quell-Query und Quell-Datei zurueckverfolgbar.

### Produkt

10. Ein User kann eine Analysefrage in natuerlicher Sprache stellen.
11. Die Plattform muss CSV, Excel (.xlsx), JSON und SQLite-Dateien ohne Konfiguration unterstuetzen.
12. Reports muessen als PDF und HTML exportierbar sein.
13. Reports muessen ueber Bridge-Kanaele verteilbar sein.
14. Batch-Analysen (mehrere Fragen auf denselben Datenquellen) muessen moeglich sein.

---

## 6. API-Spec

### 6.1 Datenquellen-Management

- `POST /data/sources/register` — Datenquelle registrieren (Pfad, Typ)
- `GET /data/sources` — alle registrierten Quellen auflisten
- `GET /data/sources/{source_id}` — Schema-Profil abrufen
- `POST /data/sources/{source_id}/profile` — Schema-Profiling erneut ausfuehren
- `DELETE /data/sources/{source_id}` — Datenquelle entfernen
- `POST /data/sources/upload` — Datei hochladen und registrieren

### 6.2 Analyse-Jobs

- `POST /data/analyze` — Analyse-Job starten (Frage + Datenquellen)
- `GET /data/jobs/{job_id}` — Job-Status und Ergebnis
- `GET /data/jobs/{job_id}/events` — Event-Log
- `GET /data/jobs/{job_id}/report` — fertigen Report abrufen
- `POST /data/jobs/{job_id}/retry` — fehlgeschlagene Stage wiederholen
- `POST /data/jobs/{job_id}/cancel` — Job abbrechen
- `POST /data/analyze/batch` — mehrere Fragen auf einmal

### 6.3 SQL-Zugriff (fuer Power-User)

- `POST /data/query` — direkte SQL-Query gegen registrierte Datenquelle
- `GET /data/query/{query_id}/result` — Ergebnis abrufen

### 6.4 MCP-Tools (fuer Agents)

- `bridge_data_register` — Datenquelle registrieren
- `bridge_data_profile` — Schema-Profil abrufen
- `bridge_data_query` — SQL-Query ausfuehren
- `bridge_data_analyze` — Analyse-Job starten
- `bridge_data_report` — Report-Status abrufen

---

## 7. Runtime- und Sicherheitsregeln

### 7.1 SQL-Sandbox

DuckDB-Queries werden in einer Sandbox ausgefuehrt:

Technische Umsetzung — Zwei-Phasen-Modell:

**Phase 1: Registrierung (privilegiert, nur Bridge-Server-Prozess):**
- `enable_external_access = true`
- Views werden angelegt: `CREATE VIEW src_abc AS SELECT * FROM read_csv_auto('/registered/path.csv')`
- Nur der Bridge-Server fuehrt dies aus, nicht die Agents
- Nach View-Erstellung wird die Connection geschlossen

**Phase 2: Agent-Queries (sandboxed):**
- Neue Connection mit `enable_external_access = false`
- Agents querien nur gegen existierende Views
- Kein `read_csv_auto()`, kein `read_parquet()`, kein `ATTACH` mit freien Pfaden
- Kein `COPY TO`, kein `CREATE TABLE` ausserhalb von temp
- Timeout pro Query: 60s (konfigurierbar)
- Ergebnis-Limit: 100.000 Rows (konfigurierbar)
- Ergebnis-Groesse: max 50 MB (konfigurierbar)

Warum zwei Phasen: `enable_external_access = false` blockiert auch `read_csv_auto()`. Die View-Erstellung braucht Dateizugriff, Agent-Queries nicht. Die Trennung verhindert, dass Agents beliebige Dateipfade oeffnen koennen.

### 7.2 Resource Limits

- max. parallele Analyse-Jobs: konfigurierbar (Default: 2)
- max. Datenquellengroesse: konfigurierbar (Default: 10 GB)
- max. Query-Ergebnis: konfigurierbar (Default: 50 MB)
- max. Chunks fuer unstrukturierte Analyse: 10.000

### 7.3 Audit

- jede Query wird in `analysis_audit.jsonl` geloggt
- jede Agent-Kommunikation laeuft ueber Bridge-Messaging (bereits auditiert)
- jeder Job hat eine vollstaendige Event-Historie

---

## 8. Test-Spec

### 8.1 Pflicht-Testmatrix

#### Datenquellen

- CSV (klein: 100 Rows, mittel: 100k Rows, gross: 10M Rows)
- Excel (.xlsx, mehrere Sheets)
- JSON (flach und nested)
- SQLite-Datenbank

#### Fragetypen

- Einfache Aggregation ("Wie viel Umsatz in Q1?")
- Vergleich ("Welche Region hat den hoechsten Umsatz?")
- Zeitreihe ("Wie entwickelt sich der Umsatz monatlich?")
- Korrelation ("Gibt es einen Zusammenhang zwischen X und Y?")
- Drill-Down ("Warum ist Q3 niedriger als Q2?")

#### Agent-Interaktion

- Planner erstellt Plan, Validator lehnt ab → Planner ueberarbeitet
- Data Engineer liefert Fehler → automatischer Retry
- QA Validator findet Inkonsistenz → Rueckweisung an Data Engineer

### 8.2 Acceptance Criteria

1. Eine einfache Aggregation auf 100k-Row-CSV liefert korrektes Ergebnis in <30s
2. Ein Multi-Step-Analyse-Job durchlaeuft alle Stages bis zum Report
3. QA Validator erkennt eine absichtlich falsche Query und weist zurueck
4. Report wird als PDF und HTML exportiert mit korrekten Charts
5. Server-Neustart: laufende Jobs werden als `failed` markiert mit Retry-Option. Echtes Resume (weitermachen ab Stage X) ist Phase D, nicht V1.
6. Ein 10M-Row-CSV wird ohne Memory-Overflow verarbeitet

---

## 9. Umsetzungs-Slices

### Phase A — Data Layer

#### Slice A1 — DuckDB-Integration + Datenquellen-Registry

- DuckDB als Python-Dependency einbinden
- Datenquellen-Registry mit Schema-Profiling
- `POST /data/sources/register`, `GET /data/sources`, `GET /data/sources/{id}`
- MCP-Tool: `bridge_data_register`, `bridge_data_profile`
- Schema-Profiling: Spaltentypen, Statistiken, Samples

#### Slice A2 — SQL-Sandbox + Query-Engine

- SQL-Query-Executor mit Sandbox (read-only, timeout, row-limit)
- `POST /data/query` + `bridge_data_query`
- Query-Audit-Log
- Ergebnis als JSON (Spalten + Rows)

### Phase B — Analysis Pipeline

#### Slice B1 — Analyse-Job-Modell

- Job-Modell mit Stages (analog Creator-Jobs)
- `POST /data/analyze` → 202 Accepted
- Persistenter Job-State auf Disk
- Event-Log pro Job

#### Slice B2 — Agent-Rollen + Multi-Agent-Workflow

- Agent-Rolle-Templates: Planner, Engineer, Validator, Reporter
- Workflow-Orchestrierung via Bridge-Tasks
- Kommunikationsfluss ueber `bridge_send`/`bridge_receive`
- Fallback: Single-Agent-Modus wenn kein Team verfuegbar

### Phase C — Output

#### Slice C1 — Visualisierung

- matplotlib-basierte Chart-Generierung
- Chart-Typen: Bar, Line, Pie, Table, Scatter
- Export als PNG/SVG
- Spaeter: plotly fuer interaktive HTML-Charts

#### Slice C2 — Report-Engine

- Markdown-Report-Generierung mit eingebetteten Charts
- PDF-Export via weasyprint
- HTML-Export als Standalone-Datei
- Publishing ueber Bridge-Kanaele

### Phase D — Haertung

#### Slice D1 — Skalierung

- 10M-Row-CSV Test
- Chunked Processing fuer unstrukturierte Daten
- Memory-Monitoring und Backpressure

#### Slice D2 — Validierung + Konfidenz

- Konfidenz-Scoring-Framework
- Gegenquery-Mechanismus
- Data-Lineage-Tracking
- Audit-Report-Generierung

### Priorisierung

Phase A ist Voraussetzung. Ohne Datenzugriff kein Analyse-Feature.
Phase B ist der Kern. Ohne Multi-Agent-Workflow ist es nur ein SQL-Tool.
Phase C macht Ergebnisse sichtbar. Ohne Reports kein Nutzwert.
Phase D macht es produktionsreif. Ohne Validierung kein Vertrauen.

---

## 10. Abgrenzung

### Was die BRIDGE Big Data Plattform NICHT ist

- Kein Data Warehouse (kein ETL, kein Star-Schema)
- Kein BI-Tool (kein Drag-and-Drop Dashboard Builder)
- Kein Ersatz fuer Tableau/PowerBI bei 50-User-Enterprise-Deployments
- Kein Streaming-System (keine Echtzeit-Datenverarbeitung)

### Was sie IST

- Eine lokale, private, Agent-gestuetzte Analyseplattform
- Fuer strukturierte Fragen auf strukturierten und semi-strukturierten Daten
- Mit erklaerbaren, validierten Ergebnissen
- Die ein Team aus AI-Agents nutzt, um zuverlaessiger zu sein als ein einzelner Agent

---

## 11. Marktrecherche-Quellen

Recherche durchgefuehrt am 2026-03-14.

- Multi-Agent-Frameworks: LangGraph v1.0 GA, CrewAI v1.10.1, AutoGen/Semantic Kernel RC — o-mega.ai, openagents.org
- Gartner (Sekundaerquelle, Originalreport nicht verifiziert): 40% der Enterprise-Apps werden bis Ende 2026 AI-Agents einbetten — via kpmg.com
- Gartner (Sekundaerquelle, Originalreport nicht verifiziert): 1.445% Anstieg bei Multi-Agent-System-Anfragen Q1 2024 → Q2 2025 — via techzine.eu
- DuckDB als Standard fuer lokale analytische SQL: QueryVeil, LAMBDA — queryveil.com
- SME Pain Points: 10+ Tools, keine Integration, manuelle Reports — hydrogenbi.com
- Data Agents Survey: arxiv.org/html/2509.23988v1
- NVIDIA Data Agent Blueprint: developer.nvidia.com
- OpenAI In-house Data Agent: openai.com
