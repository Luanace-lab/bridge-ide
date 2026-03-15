# FINANCE & INVESTMENT ANALYSIS PLATFORM SPEC

Stand: 2026-03-14
Autor: Viktor (Operative Projektleitung BRIDGE)
Revision: R3 — Battle-Review 3 Runden abgeschlossen (23 + 7 Befunde, alle adressiert)
Status: FREIGEGEBEN — Implementierungsgrundlage

---

## 1. Ziel

Die BRIDGE wird um eine Finanzanalyse- und Anlageplattform erweitert. Spezialisierte Agents recherchieren, analysieren und bewerten Finanzinstrumente, Portfolios und Marktdaten — lokal, privat, ohne Cloud-Abhaengigkeit fuer die Analyse-Logik.

### 1.1 Produkt-Differenzierung

Warum die BRIDGE statt Bloomberg Terminal ($24.000/Jahr), PortfolioPilot ($29/mo) oder manueller Recherche:

1. **Lokal + privat** — Portfoliodaten, Anlagestrategien und Vermoegenswerte bleiben auf dem eigenen Rechner. Kein Upload zu Drittanbietern.
2. **Multi-Agent-Research** — nicht ein Agent, sondern ein Team: Researcher, Analyst, Risk Manager, Portfolio Advisor. Jeder prueft die anderen.
3. **Proaktive Kommunikation** — Agents melden Kursaenderungen, Risiken und Chancen selbststaendig. Kein "User fragt, Agent antwortet"-Modell.
4. **Keine Plattformgebuehr** — keine monatlichen Abo-Kosten. API-Kosten der LLM-Provider fallen pro Nutzung an. Datenprovider haben kostenlose Tiers mit Einschraenkungen (siehe Sektion 4.2).
5. **Erklaerbare Empfehlungen** — jede Anlageempfehlung wird begruendet, mit Quellen belegt und mit Risikobewertung versehen. Kein Black-Box-Score.
6. **Bridge-native** — nutzt vorhandene Infrastruktur: Task-System, Knowledge Engine, Scheduling, Multi-Channel-Benachrichtigung.
7. **Erweiterbar** — V1 funktioniert mit einer einzigen Engine (Claude). Multi-Engine (Gemini, Codex, Qwen) ist spaetere Optimierung.

### 1.2 Zielgruppen

- Privatanleger, die fundierte Entscheidungen treffen wollen ohne Bloomberg
- KMU-Finanzverantwortliche mit Portfolios in Aktien, ETFs, Anleihen
- Solo-Unternehmer, die ihre Rücklagen strategisch anlegen wollen
- Researcher, die Markt- und Branchendaten systematisch auswerten

### 1.3 Wichtiger Hinweis

Die Plattform liefert **keine Anlageberatung**. Sie liefert strukturierte Analyse, Daten und Bewertungen. Die Anlageentscheidung trifft immer der User. Dieser Disclaimer muss in jedem Report und jeder UI-Anzeige sichtbar sein.

### 1.4 6-Monats-Vision

In 6 Monaten soll ein User:

1. Sein Portfolio erfassen (manuell oder via CSV/API-Import)
2. Watchlists pflegen fuer potenzielle Investments
3. Eine Analysefrage stellen ("Soll ich NVIDIA nachkaufen?", "Wie ist mein Portfolio-Risiko?")
4. Ein Agent-Team zusammenstellen lassen
5. Die Agents arbeiten sehen (Live-Status: Research laeuft, Fundamentalanalyse laeuft, Risikocheck laeuft)
6. Einen validierten Research-Report erhalten mit Charts, Kennzahlen, Quellverweisen
7. Proaktive Alerts erhalten ("Deine Position X hat 15% verloren — Analyse laeuft")
8. Reports ueber Bridge-Kanaele teilen (PDF, Email, Telegram)

---

## 2. Verifizierter Ist-Zustand

### 2.1 Was die BRIDGE heute hat (relevant fuer Finance)

| Faehigkeit | Vorhanden | Details |
|---|---|---|
| Agent-Kommunikation | JA | bridge_send/receive, Tasks, Whiteboard |
| Knowledge Engine | JA | Markdown-Notes fuer persistente Analyse-Ergebnisse |
| Semantic Memory | JA | Vector+BM25 fuer historische Recherche-Retrieval |
| Web-Research | JA | bridge_research mit Freshness-Tracking |
| Scheduling | JA | bridge_cron_create fuer proaktive Checks |
| Multi-Channel-Benachrichtigung | JA | Email, Telegram, WhatsApp, Slack |
| PDF-Generierung | JA | weasyprint |
| Task-System | JA | Auftraege zwischen Agents |
| Scope Locks | JA | Exklusive Zugriffskontrolle |
| Approval Gates | JA | Freigaben fuer kritische Aktionen |

### 2.2 Was NICHT vorhanden ist

| Faehigkeit | Status |
|---|---|
| Marktdaten-Anbindung (Kurse, Fundamentaldaten, News) | NICHT VORHANDEN |
| Portfolio-Datenmodell | NICHT VORHANDEN |
| Watchlist-Management | NICHT VORHANDEN |
| Finanz-Kennzahlen-Berechnung (KGV, KBV, DCF, Sharpe Ratio) | NICHT VORHANDEN |
| Backtesting-Engine | NICHT VORHANDEN |
| Chart-Generierung (Candlestick, Performance, Allocation) | NICHT VORHANDEN |
| Proaktive Monitoring-Loops (Kurs-Alerts, Rebalancing-Trigger) | NICHT VORHANDEN |
| Risikobewertung (VaR, Max Drawdown, Korrelationsanalyse) | NICHT VORHANDEN |
| Historische Daten-Persistenz | NICHT VORHANDEN |
| Regulatorische Disclaimers | NICHT VORHANDEN |

---

## 3. Diagnostizierte Hauptprobleme

### 3.1 Kein Zugriff auf Finanzdaten

Die Bridge hat keinen integrierten Weg, Aktienkurse, Fundamentaldaten oder Wirtschaftsindikatoren abzurufen.

### 3.2 Kein Portfolio-Modell

Es gibt keine Datenstruktur fuer "User besitzt 50 NVIDIA-Aktien zu Durchschnittskurs 120 EUR". Ohne Portfolio-Modell keine Portfolio-Analyse.

### 3.3 Keine proaktive Ueberwachung

Die Bridge hat `bridge_cron_create`, aber keinen Workflow, der regelmaessig Kurse prueft und bei Schwellenwerten Agents aktiviert.

### 3.4 Keine Finanz-spezifischen Berechnungen

KGV, DCF, Sharpe Ratio, Monte-Carlo-Simulationen — das muss alles implementiert oder ueber Libraries angebunden werden.

---

## 4. Zielarchitektur

### 4.1 Grundsatz

Die Finance-Plattform ist eine Erweiterung der Bridge. Sie nutzt:

- **Task-System** fuer Research-Auftraege
- **Knowledge Engine** fuer persistente Analysen und Entscheidungshistorie
- **Semantic Memory** fuer historische Research-Retrieval
- **Scheduling** fuer proaktive Kursueberwachung
- **Multi-Channel** fuer Alerts und Report-Distribution
- **DuckDB** (aus Big Data Spec) fuer historische Daten-Analyse

### 4.2 Data Layer — Finanzdaten-Quellen

#### Daten-APIs (Agent-nutzbar)

**Primaere Datenquelle: yfinance**

yfinance ist ein Web-Scraper fuer Yahoo Finance. Es hat KEIN offizielles API-Agreement. Yahoo kann jederzeit das Format aendern oder Zugang blockieren. Das ist ein bekanntes Ausfallrisiko.

Vorteile: Kostenlos, kein Rate-Limit fuer moderate Nutzung, Batch-Abfragen moeglich (`yf.download(["NVDA","AMD","INTC"], period="1d")`), split-adjustierte Kurse, Fundamentaldaten, Earnings-Kalender.

Fallback-Strategie: Wenn yfinance ausfaellt → Alpha Vantage oder EODHD als Fallback. DuckDB-Cache liefert letzte bekannte Daten mit Warnung.

| Quelle | Daten | Zugriff | Kosten | Rolle |
|---|---|---|---|---|
| **yfinance** | Kurse, Fundamentaldaten, Optionen, ETFs, Earnings | Python-Library | Kostenlos (Scraper, kein SLA) | PRIMAER |
| **Alpha Vantage** | Kurse, Fundamentaldaten, Forex, Crypto | REST API + MCP-Server | Free: 25 Calls/Tag, Paid: ab $49/mo | FALLBACK + spezifische Daten |
| **Financial Datasets** | Income Statements, Balance Sheets, Cash Flow | MCP-Server | Free Tier verfuegbar | ERGAENZEND |
| **EODHD** | Historische Kurse, Fundamentaldaten, Intraday | MCP-Server | Free Tier verfuegbar | FALLBACK |
| **FRED** | Wirtschaftsindikatoren (Inflation, Zinsen, GDP) | REST API | Kostenlos | ERGAENZEND |

#### API-Budget-Strategie

| Datentyp | Abruffrequenz | Quelle | Cache-TTL |
|---|---|---|---|
| Aktueller Kurs | Alle 4h (Alerts) oder on-demand | yfinance Batch | 4 Stunden |
| Fundamentaldaten | 1x pro Quartal (nach Earnings) | yfinance oder Alpha Vantage | 90 Tage |
| Historische Kurse | 1x taeglich | yfinance | 24 Stunden |
| Wechselkurse | 1x taeglich | yfinance (`EURUSD=X`) | 24 Stunden |
| Nachrichten | On-demand bei Analyse | yfinance + bridge_research | 1 Stunde |
| Earnings-Kalender | 1x woechentlich | yfinance `.earnings_dates` | 7 Tage |

Durch aggressives Caching in DuckDB bleibt der API-Verbrauch fuer ein 20-Positionen-Portfolio unter 50 Calls/Tag (yfinance Batch = 1 Call fuer alle Kurse).

#### Premium-Daten (optional)

| Quelle | Daten | Zugriff | Kosten |
|---|---|---|---|
| **LSEG** | Institutionelle Marktdaten | MCP-Server | Enterprise |
| **Alpaca** | Real-time Kurse, Trading | MCP-Server | Free Tier + Paid |
| **Polygon.io** | Real-time Kurse, Ticks | REST API | Ab $29/mo |

#### Verfuegbare MCP-Server (Stand Maerz 2026, Repositories existieren — Produktionsreife UNKNOWN)

- `financial-datasets/mcp-server` — Income Statements, Balance Sheets, Cash Flow, Preise, News
- `Alpha Vantage MCP` — Real-time + historische Kurse, Fundamentaldaten
- `EODHD MCP Server` — Historische Kurse, Intraday, Fundamentaldaten
- `alpacahq/alpaca-mcp-server` — Trading, Datenanalyse, Strategien in natuerlicher Sprache
- `LSEG MCP Server` — Institutionelle Daten (Enterprise)

Diese koennen direkt in die Bridge-Agent-Konfiguration eingetragen werden. Ein Agent kann dann in natuerlicher Sprache Finanzdaten abfragen.

### 4.3 Python Finance Stack (Agent-nutzbar via Code-Execution)

| Library | Zweck | Status |
|---|---|---|
| **yfinance** | Marktdaten-Download, Fundamentaldaten | pip install |
| **pandas** | DataFrame-Verarbeitung, Zeitreihen | Bereits vorhanden |
| **numpy** | Numerische Berechnungen | Bereits vorhanden |
| **matplotlib** | Charts (Line, Candlestick, Allocation Pie) | Standard-Library |
| **mplfinance** | Candlestick-Charts, technische Analyse Plots | pip install |
| **quantstats** | Portfolio-Performance-Reports, Sharpe, Drawdown | pip install |
| **backtrader** | Backtesting-Engine | NICHT V1 — letztes Release 2019, Maintenance UNKNOWN. Alternative: vectorbt oder bt |
| **QuantLib-Python** | Derivate-Pricing, Zinsstrukturkurven | NICHT V1 — Zielgruppe braucht keine Derivate-Pricing |
| **scipy** | Monte-Carlo-Simulation, Optimierung | Bereits vorhanden (numpy-Dependency) |

### 4.4 Portfolio-Datenmodell

```json
{
  "portfolio_id": "pf_main",
  "name": "Hauptdepot",
  "currency": "EUR",
  "positions": [
    {
      "symbol": "NVDA",
      "exchange": "NASDAQ",
      "shares": 50,
      "avg_cost_local": 120.00,
      "cost_currency": "USD",
      "added_at": "2025-06-15"
    }
  ],
  "transactions": [
    {
      "date": "2025-06-15",
      "type": "buy",
      "symbol": "NVDA",
      "shares": 50,
      "price": 120.00,
      "currency": "USD",
      "fees": 1.50,
      "exchange_rate_to_portfolio_currency": 0.92
    },
    {
      "date": "2025-12-15",
      "type": "dividend",
      "symbol": "NVDA",
      "amount": 25.00,
      "currency": "USD"
    }
  ],
  "watchlist": [
    {
      "symbol": "ASML",
      "reason": "Semiconductor-Exposure Europa",
      "added_at": "2026-03-01"
    }
  ],
  "alerts": [
    {
      "symbol": "NVDA",
      "type": "price_drop",
      "threshold_pct": -10,
      "active": true
    }
  ]
}
```

#### Waehrungsumrechnung

- Portfolio hat eine Basiswaehrung (`currency`)
- Positionen haben eine Transaktionswaehrung (`cost_currency`)
- Bewertung erfolgt in Portfolio-Basiswaehrung
- Wechselkurse werden via yfinance (`EURUSD=X`) abgerufen und in DuckDB gecacht
- Historische Wechselkurse fuer Performance-Berechnung: Tageskurs zum jeweiligen Transaktionsdatum

#### Transaktionsmodell

- Jede Kauf-/Verkaufs-/Dividenden-Aktion wird als Transaktion gespeichert
- `avg_cost_local` wird automatisch aus Transaktionen berechnet (FIFO oder Durchschnitt, konfigurierbar)
- Split-Bereinigung: yfinance liefert split-adjustierte Kurse. Bei einem Split werden historische `avg_cost` und `shares` adjustiert.
- Realisierte Gewinne/Verluste werden aus Verkaufstransaktionen berechnet

Persistenz: `workspace/finance/portfolios/{portfolio_id}/portfolio.json`

### 4.5 Agent-Modi

#### Default: Single-Agent-Modus

Fuer einfache Analysen (Einzelaktien-Bewertung, Portfolio-Ueberblick) genuegt ein einzelner Agent. Dieser uebernimmt alle Rollen: Research, Analyse, Validierung, Report.

#### Opt-in: Multi-Agent-Modus

Fuer komplexe Analysen (Szenario-Modellierung, Tiefenanalyse mit Peer-Comparison) kann ein Agent-Team via `"mode": "multi_agent"` aktiviert werden.

#### Kostenmodell

| Modus | Geschaetzte Kosten pro Analyse | Anwendungsfall |
|---|---|---|
| Single-Agent | $0.10 - $0.80 | Einzelaktien-Check, Portfolio-Ueberblick |
| Multi-Agent (4 Agents) | $0.80 - $4.00 | Tiefenanalyse, Szenario, Peer-Comparison |
| Proaktiver Alert (Single) | $0.05 - $0.20 | Kurs-Check + kurze Einschaetzung |

Basis: Claude Sonnet API-Kosten. Opus fuer Tiefenanalyse, Haiku fuer Routine-Checks.

#### Fehlerbehandlung und Timeouts

Uebernahme aus dem gemeinsamen Job-Framework (siehe `SHARED_JOB_FRAMEWORK.md` — noch zu erstellen, referenziert auch im Big Data Spec):

| Parameter | Default | Konfigurierbar |
|---|---|---|
| `max_retries_per_stage` | 3 | Ja |
| `stage_timeout_s` | 300 | Ja |
| `job_timeout_s` | 1800 | Ja |
| `max_validation_rounds` | 3 | Ja |

Finance-spezifische Fehlerbehandlung:

| Fehler | Verhalten |
|---|---|
| API-Rate-Limit erreicht | Retry mit Backoff, dann Fallback auf Cache |
| Datenprovider nicht erreichbar | Fallback auf gecachte Daten mit Warnung "Daten von [Datum]" |
| Agent-Timeout | Job failt mit `agent_timeout`, kein stiller Fehler |
| Kein Kurs verfuegbar fuer Symbol | Klarer Fehler, kein erfundener Kurs |
| Waehrungskurs nicht abrufbar | Letzter bekannter Kurs aus Cache mit Warnung |

### 4.6 Agent-Rollen (Multi-Agent-Modus)

#### Planner (uebernommen durch Portfolio Advisor)

Der Portfolio Advisor uebernimmt die Planner-Rolle: er empfaengt die User-Frage, zerlegt sie in Sub-Tasks und delegiert an die Spezialisten.

#### Market Researcher

- Recherchiert aktuelle Nachrichten, Earnings, SEC Filings
- Nutzt `bridge_research` fuer Web-Recherche
- Nutzt Finance-MCP-Server fuer Fundamentaldaten
- Liefert strukturierte Research-Notes an Knowledge Engine

#### Fundamental Analyst

- Berechnet Kennzahlen: KGV, KBV, EV/EBITDA, Free Cash Flow Yield
- Fuehrt DCF-Bewertung durch (via Python-Code)
- Vergleicht mit Branchendurchschnitt
- Liefert Fair-Value-Schaetzung mit Konfidenzband

#### Risk Manager

- Berechnet Portfolio-Risikokennzahlen: VaR, Max Drawdown, Sharpe Ratio, Sortino Ratio
- Prueft Korrelationen zwischen Positionen
- Identifiziert Klumpenrisiken (Branche, Region, Waehrung)
- Fuehrt Monte-Carlo-Simulation fuer Szenarien durch

#### Portfolio Advisor

- Empfaengt Input von Researcher, Analyst und Risk Manager
- Formuliert Handlungsempfehlungen mit Begruendung
- Unterscheidet zwischen "Analyseergebnis" und "Empfehlung"
- Fuegt Disclaimer ein
- Erstellt den finalen Report

### 4.6 Analyse-Workflow

```
User: "Soll ich NVIDIA nachkaufen?"
  │
  ├─→ Market Researcher
  │     ├─ bridge_research("NVIDIA Q1 2026 earnings results")
  │     ├─ Finance MCP: GET /income-statements/NVDA
  │     ├─ Finance MCP: GET /prices/NVDA?period=1y
  │     └─ bridge_send(to=fundamental_analyst, content=research_data)
  │
  ├─→ Fundamental Analyst
  │     ├─ Berechnet KGV, DCF, Free Cash Flow
  │     ├─ Vergleicht mit AMD, INTC, AVGO
  │     ├─ Fair Value: $XXX (Konfidenz: medium)
  │     └─ bridge_send(to=risk_manager, content=valuation)
  │
  ├─→ Risk Manager
  │     ├─ Liest Portfolio: User hat bereits 50 NVDA
  │     ├─ Berechnet: Nachkauf wuerde Semiconductor-Anteil auf 35% erhoehen
  │     ├─ Monte Carlo: Worst Case -XX% in 12 Monaten
  │     └─ bridge_send(to=portfolio_advisor, content=risk_assessment)
  │
  └─→ Portfolio Advisor
        ├─ Zusammenfassung: Research + Bewertung + Risiko
        ├─ Empfehlung mit Begruendung
        ├─ Disclaimer: "Keine Anlageberatung"
        └─ Report → User (PDF + Telegram)
```

### 4.7 Proaktive Ueberwachung

#### Kurs-Alerts

- Konfigurierbare Schwellenwerte pro Position (z.B. -10%, +20%)
- Bridge-Cron-Job prueft regelmaessig (Default: alle 4 Stunden)
- Implementierung: Cron sendet HTTP-Call an `POST /finance/alert-check`. Dieser Endpoint prueft Kurse via yfinance Batch, vergleicht mit Schwellenwerten und startet bei Bedarf einen Analyse-Job via `POST /finance/analyze`.
- Hinweis: `bridge_cron_create` unterstuetzt `action_type: "http"`. Die Agent-Aktivierung erfolgt indirekt ueber den HTTP-Endpoint, nicht durch direktes Agent-Spawning.
- Benachrichtigung ueber konfigurierte Kanaele

#### Portfolio-Health-Check

- Woechentlicher automatischer Check:
  - Performance vs. Benchmark (z.B. MSCI World)
  - Rebalancing-Bedarf
  - Korrelationsaenderungen
  - Neue Risiken (Earnings, regulatorische Aenderungen)

#### Earnings Calendar

- Datenquelle: yfinance `.earnings_dates` (kostenlos, kein zusaetzlicher API-Call)
- Woechentlicher Sync der Earnings-Termine fuer alle Portfolio-Positionen
- Pre-Earnings-Research 3 Tage vor Termin (via Cron → HTTP → Analyse-Job)
- Post-Earnings-Analyse am Tag danach

### 4.8 Visualisierung

#### Pflicht-Chart-Typen

- Portfolio-Allocation Pie Chart
- Performance-Line-Chart vs. Benchmark
- Candlestick-Chart (via mplfinance)
- Korrelationsmatrix Heatmap
- Risk/Return Scatter Plot
- Sektor-/Regionen-Verteilung

### 4.9 Report-Engine

Reports werden analog zum Big Data Spec erzeugt (Markdown → PDF/HTML).

Finance-spezifische Elemente:

- Disclaimer-Block am Anfang und Ende
- Kennzahlen-Tabelle
- Fair-Value-Analyse mit Konfidenzband
- Quellverweise (welcher Datenprovider, welches Datum)
- Historischer Vergleich mit frueheren Analysen (via Knowledge Engine)

---

## 5. Nicht verhandelbare Anforderungen

### Regulatorisch

1. Jeder Report enthaelt den Disclaimer: "Maschinell generierte Analyse — keine professionelle Finanzberatung. Alle Informationen dienen ausschliesslich der persoenlichen Analyse. Anlageentscheidungen liegen ausschliesslich beim User."
2. Die Plattform fuehrt KEINE Trades aus (V1). Kein Broker-Zugang, kein Order-Routing.
3. Datenquellen und Abrufdatum werden in jedem Report genannt.
4. Ergebnisse werden als "Analyseergebnis" formuliert, nie als "Kauf-/Verkaufsempfehlung".
5. Keine personalisierten Rebalancing-Vorschlaege ohne expliziten User-Opt-in und Disclaimer.
6. Vor Veroeffentlichung: rechtliche Pruefung der Formulierungen durch Fachanwalt empfohlen (MiFID II, WpHG).

### Qualitaet

4. Jede Kennzahl wird mit Berechnungsformel und Eingabedaten dokumentiert.
5. Fair-Value-Schaetzungen haben ein Konfidenzband (optimistisch/base/pessimistisch).
6. Risk Manager prueft jede Empfehlung vor Auslieferung.
7. Historische Analysen werden in Knowledge Engine persistiert fuer Backtesting der eigenen Empfehlungen.

### Technisch

8. Finanzdaten werden lokal gecacht (DuckDB), nicht bei jedem Request neu abgerufen.
9. API-Rate-Limits der kostenfreien Provider werden respektiert.
10. Portfolio-Daten liegen verschluesselt auf Disk (optional, aber architektonisch vorbereitet).
11. Proaktive Alerts sind konfigurierbar und abschaltbar.

---

## 6. API-Spec

### 6.1 Portfolio-Management

- `POST /finance/portfolios` — Portfolio erstellen
- `GET /finance/portfolios` — alle Portfolios auflisten
- `GET /finance/portfolios/{id}` — Portfolio mit aktuellen Kursen
- `PUT /finance/portfolios/{id}/positions` — Positionen aktualisieren
- `POST /finance/portfolios/{id}/import` — CSV-Import (Pflichtfelder: date, type, symbol, shares, price, currency. Optional: fees, exchange_rate. Duplikate: gleiche date+symbol+type+shares+price = Warnung, kein Auto-Import)
- `DELETE /finance/portfolios/{id}` — Portfolio loeschen

### 6.2 Watchlist

Watchlist ist eigenstaendig (nicht Portfolio-gebunden), da User Symbole beobachten wollen bevor sie ein Portfolio haben.

- `POST /finance/watchlist` — Symbol hinzufuegen
- `GET /finance/watchlist` — Watchlist mit aktuellen Kursen
- `DELETE /finance/watchlist/{symbol}` — Symbol entfernen

### 6.3 Analyse

- `POST /finance/analyze` — Analyse-Job starten (Frage + Portfolio/Symbol)
- `GET /finance/jobs/{job_id}` — Job-Status
- `GET /finance/jobs/{job_id}/report` — fertigen Report abrufen

### 6.4 Marktdaten

- `GET /finance/quote/{symbol}` — aktueller Kurs
- `GET /finance/fundamentals/{symbol}` — Fundamentaldaten
- `GET /finance/history/{symbol}` — historische Kurse
- `GET /finance/news/{symbol}` — aktuelle Nachrichten

### 6.5 Alerts

- `POST /finance/alerts` — Alert konfigurieren
- `GET /finance/alerts` — alle Alerts auflisten
- `DELETE /finance/alerts/{id}` — Alert loeschen

### 6.6 MCP-Tools (fuer Agents)

- `bridge_finance_quote` — Kurs abrufen
- `bridge_finance_fundamentals` — Kennzahlen abrufen
- `bridge_finance_portfolio` — Portfolio-Status abrufen
- `bridge_finance_analyze` — Analyse-Job starten
- `bridge_finance_alert_check` — Alert-Status pruefen

---

## 7. CLI-native Faehigkeiten

V1 funktioniert vollstaendig mit Claude als einziger Engine. Multi-Engine ist spaetere Optimierung.

| Rolle | V1 Engine | Spaetere Alternative | Begruendung |
|---|---|---|---|
| Alle Rollen (Single-Agent) | Claude | — | Staerkstes Reasoning, MCP-Support, Python via Bash |
| Daten-Aggregation | Claude | Qwen | Grosser Kontext bei Qwen, kostenguenstiger |
| Cloud-Daten | Claude | Gemini | Native Google-Integration bei Gemini |

---

## 8. Sicherheit und Compliance

### 8.1 Kein Trading in V1

Die Plattform fuehrt KEINE Trades aus. Kein Order-Routing, kein Broker-Zugang, keine Alpaca-Integration in V1.

Begruendung: In der EU (MiFID II) und in Deutschland (WpHG) erfordert automatisierter Wertpapierhandel regulatorische Klaerung. Ein Open-Source-Projekt ohne BaFin-Erlaubnis darf keine personalisierten Handelsauftraege ausfuehren.

Trading kann in einer spaeteren Version als optionales Feature evaluiert werden — erst nach rechtlicher Pruefung.

### 8.2 Datenschutz

- Portfolio-Daten bleiben lokal
- API-Keys fuer Datenprovider werden in Bridge Credential Store gespeichert (nicht im Klartext)
- Keine Telemetrie, kein Tracking

---

## 9. Test-Spec

### 9.1 Pflicht-Testmatrix

#### Datenquellen

- yfinance: Kurs, Fundamentaldaten, historische Daten
- Alpha Vantage MCP: Income Statement, Balance Sheet
- Financial Datasets MCP: Cash Flow, Preise

#### Analysetypen

- Einzelaktien-Analyse ("Ist NVDA fair bewertet?")
- Portfolio-Risiko ("Wie ist mein Risikoprofil?")
- Vergleich ("NVDA vs. AMD — welche ist attraktiver?")
- Szenario ("Was passiert bei 20% Marktkorrektur?")

#### Agent-Interaktion

- Researcher liefert, Analyst berechnet, Risk Manager warnt → Advisor fasst zusammen
- Risk Manager weist Empfehlung zurueck → Analyst ueberarbeitet
- Datenprovider nicht erreichbar → Fallback auf Cache

### 9.2 Acceptance Criteria

1. Einzelaktien-Analyse liefert korrekten KGV, KBV und DCF in <60s
2. Portfolio-Health-Check mit 20 Positionen laeuft in <120s
3. Risikokennzahlen (Sharpe, Drawdown, Volatilitaet) fuer 20-Positionen-Portfolio in <30s
4. Proaktiver Alert wird innerhalb von 5 Minuten nach Kursaenderung ausgeloest
5. Report wird als PDF und HTML mit korrekten Charts exportiert
6. Disclaimer ist in jedem Report vorhanden

---

## 10. Umsetzungs-Slices

### Phase A — Data Layer

#### Slice A1 — Finanzdaten-Anbindung

- yfinance-Integration (Python-Library)
- Finance-MCP-Server-Konfiguration (Alpha Vantage, Financial Datasets)
- Lokaler DuckDB-Cache fuer historische Daten
- `GET /finance/quote`, `GET /finance/fundamentals`, `GET /finance/history`

#### Slice A2 — Portfolio-Modell

- Portfolio-Datenstruktur (JSON auf Disk)
- CRUD-Endpoints
- CSV-Import
- Aktuelle Bewertung via yfinance

### Phase B — Analyse-Engine

#### Slice B1 — Fundamentalanalyse

- KGV, KBV, EV/EBITDA, FCF Yield Berechnung
- DCF-Modell (via Python-Code)
- Peer-Comparison
- Agent-Rollen: Researcher + Analyst

#### Slice B2 — Risikoanalyse

- V1: Historische Volatilitaet, Max Drawdown, Sharpe Ratio, Sortino Ratio (pandas-basiert, kein Monte-Carlo)
- V1: Korrelationsmatrix zwischen Positionen
- V2+: Monte-Carlo-Simulation (nach Validierung der Basismetriken)
- Agent-Rolle: Risk Manager

### Phase C — Proaktive Features

#### Slice C1 — Alerts + Monitoring

- Kurs-Alert-System via bridge_cron_create
- Earnings-Calendar-Integration
- Automatische Agent-Aktivierung bei Trigger
- Multi-Channel-Benachrichtigung

#### Slice C2 — Portfolio Health Check

- Woechentlicher automatischer Check
- Performance vs. Benchmark
- Rebalancing-Vorschlaege
- Report-Generierung

### Phase D — Output + Haertung

#### Slice D1 — Visualisierung + Reports

- mplfinance fuer Candlestick-Charts
- Portfolio-Allocation-Pie, Performance-Lines
- PDF/HTML-Report mit Disclaimer
- Publishing ueber Bridge-Kanaele

#### Slice D2 — Historisierung + Rueckblick

- Historische Analyse-Ergebnisse in Knowledge Engine persistieren
- "Wie gut waren meine Analysen?" — Rueckblick-Funktion (tatsaechliche Kursentwicklung vs. damalige Einschaetzung)
- Backtesting ist NICHT V1. Wenn spaeter benoetigt: vectorbt oder bt als moderne Alternativen zu backtrader evaluieren.

### Priorisierung

Phase A: Ohne Daten keine Analyse.
Phase B: Der Kern — Multi-Agent-Analyse mit Validierung.
Phase C: Der Differenziator — proaktive Ueberwachung statt reaktiver Abfrage.
Phase D: Sichtbarkeit und Lernfaehigkeit.

---

## 11. Abgrenzung

### Was die Plattform NICHT ist

- Kein Broker (kein Order-Routing, kein Margin, kein Trading in V1)
- Kein Robo-Advisor (keine automatischen Anlageentscheidungen)
- Kein Bloomberg-Ersatz (kein Real-time Tick-Level Data)
- Kein Hochfrequenz-Trading-System
- Keine Anlageberatung (alle Ergebnisse sind maschinelle Analysen, keine professionelle Beratung)

### Synergien mit Big Data Spec

Beide Specs teilen gemeinsame Infrastruktur. Ein gemeinsames `SHARED_JOB_FRAMEWORK_SPEC.md` (noch zu erstellen) definiert:

| Komponente | Geteilt | Finance-spezifisch | Big-Data-spezifisch |
|---|---|---|---|
| Job-Lifecycle (Stages, Status, Events) | JA | — | — |
| Fehlerbehandlung (Timeouts, Retries) | JA | API-Rate-Limit-Retry | — |
| DuckDB-Integration | JA (eine Instanz, getrennte Schemas) | Schema `finance` | Schema `data` |
| SQL-Sandbox (2-Phasen) | JA | — | — |
| Report-Engine (Markdown→PDF/HTML) | JA | Disclaimer, Kennzahlen | — |
| Chart-Engine | Basis: matplotlib | +mplfinance (Candlestick) | +plotly (interaktiv) |
| Agent-Rollen | Basis-Framework geteilt | Researcher/Analyst/Risk/Advisor | Planner/Engineer/Validator/Reporter |
| Knowledge Engine Scopes | JA | `Projects/finance/` | `Projects/data/` |

Abhaengigkeit: Big Data Phase A (DuckDB-Integration) muss vor Finance Phase A stehen. Finance nutzt DuckDB als Cache. Alternativ: Finance V1 startet mit JSON-Cache und migriert spaeter zu DuckDB.

### Was sie IST

- Eine lokale, private, Agent-gestuetzte Finanzanalyse-Plattform
- Fuer fundierte Anlageentscheidungen auf Basis strukturierter Multi-Agent-Analyse
- Mit erklaerbaren, validierten Bewertungen und proaktiver Ueberwachung
- Die Retail-Investoren Zugang zu institutioneller Analysequalitaet gibt — ohne institutionelle Kosten

---

## 12. Marktrecherche-Quellen

Recherche durchgefuehrt am 2026-03-14.

- Finance MCP-Server: financial-datasets/mcp-server, Alpha Vantage MCP, EODHD MCP, Alpaca MCP, LSEG MCP — github.com, mcp.alphavantage.co, eodhd.com, alpacahq/alpaca-mcp-server
- Claude Financial Services: Anthropic Financial Plugins, DCF-Modelle, IC-Memos — anthropic.com/news/claude-for-financial-services
- Python Finance Stack: yfinance, backtrader, QuantLib, quantstats — analyzingalpha.com, quantlib.org
- Retail Investor Pain Points: Bloomberg $24k/Jahr unerschwinglich — io-fund.com. (SPIVA-Daten zu Fonds-Underperformance sind Primaerquelle fuer die haeufig zitierte 79%-Zahl, beziehen sich aber auf aktiv verwaltete Fonds, nicht direkt auf Retail-Investoren.)
- AI Trading Market: $11.23B (2024) → $33.45B (2030), CAGR 20% — grandviewresearch.com. (Bezieht sich auf den Gesamtmarkt, nicht auf lokale Analyse-Tools.)
- Multi-Agent Investment Research: AWS Bedrock Multi-Agent Investment Assistant — aws.amazon.com
- awesome-quant: Kuratierte Liste von 200+ Quant-Finance-Libraries — github.com/wilsonfreitas/awesome-quant
