# FINANZBUCHHALTUNG PLATFORM SPEC

Stand: 2026-03-14
Autor: Viktor (Operative Projektleitung BRIDGE)
Revision: R3 — Battle-Review 3 Runden abgeschlossen (16 + 10 Befunde, alle adressiert)
Status: FREIGEGEBEN — Implementierungsgrundlage

---

## 1. Ziel

Die BRIDGE wird um eine Finanzbuchhaltungsplattform erweitert. Agents automatisieren Belegerfassung, Kontierung, Abstimmung und Reporting — lokal, privat, DATEV-kompatibel.

### 1.1 Produkt-Differenzierung

Warum die BRIDGE statt DATEV ($$$), sevDesk ($15/mo), lexoffice ($10/mo) oder manueller Buchhaltung:

1. **Lokal + privat** — Finanzdaten verlassen nie den Rechner. Keine Cloud-Buchhaltung, keine Drittanbieter-Abhaengigkeit fuer die Datenhaltung.
2. **Agent-gestuetzte Automatisierung** — Belege werden automatisch erkannt, kategorisiert, kontiert. Ein Agent prueft die Kontierung eines anderen.
3. **DATEV-Export** — nahtlose Uebergabe an den Steuerberater. DATEV-Format ist Pflicht fuer den deutschen Markt.
4. **E-Rechnung-konform** — Ab 2025 Pflicht in Deutschland. Die Plattform muss XRechnung/ZUGFeRD lesen und verarbeiten koennen.
5. **Keine Plattformgebuehr** — keine monatlichen Abo-Kosten. LLM-API-Kosten fallen pro Belegverarbeitung an.
6. **Bridge-native** — nutzt vorhandene Infrastruktur: Vision-Analyse fuer Belege, Knowledge Engine fuer Kontierungsregeln, Task-System fuer Pruefworkflows.
7. **Open-Source-Integration** — Firefly III (REST API), Akaunting (REST API) oder GnuCash als optionale Backend-Systeme.

### 1.2 Zielgruppen

- Freelancer und Selbstaendige in Deutschland
- KMU mit einfacher Buchhaltung (EUeR oder kleine Bilanz)
- Solo-Unternehmer, die Belege digital erfassen wollen
- Teams, die ihre Buchhaltung vor der Steuerberater-Uebergabe vorbereiten

### 1.3 Wichtiger Hinweis

Die Plattform ersetzt KEINEN Steuerberater. Sie automatisiert die Vorarbeit: Belegerfassung, Vorkontierung, Abstimmung, DATEV-Export. Die steuerliche Verantwortung liegt beim User und seinem Steuerberater.

### 1.4 6-Monats-Vision

In 6 Monaten soll ein User:

1. Belege hochladen (Foto, PDF, E-Rechnung)
2. Agent erkennt automatisch: Lieferant, Betrag, MwSt, Datum, Kategorie
3. Agent schlaegt Kontierung vor (SKR03/SKR04)
4. Zweiter Agent prueft die Kontierung
5. User bestaetigt oder korrigiert
6. Monatliche UStVA-Vorbereitung wird automatisch erstellt
7. DATEV-Export fuer den Steuerberater per Klick
8. Bankabstimmung: Kontoauszuege werden mit Belegen gematcht

---

## 2. Verifizierter Ist-Zustand

### 2.1 Was die BRIDGE heute hat (relevant fuer Buchhaltung)

| Faehigkeit | Vorhanden | Details |
|---|---|---|
| Vision-Analyse | JA | `bridge_vision_analyze` — Claude Vision fuer Beleg-OCR |
| Knowledge Engine | JA | Persistente Kontierungsregeln und Lieferanten-Mapping |
| Semantic Memory | JA | Historische Belegsuche |
| Task-System | JA | Pruefworkflows zwischen Agents |
| Approval Gates | JA | User-Freigabe fuer kritische Buchungen |
| File-Upload | JA | `CHAT_UPLOADS_DIR` fuer Belege |
| PDF-Verarbeitung | JA | Read-Tool kann PDFs lesen |
| Scheduling | JA | `bridge_cron_create` fuer monatliche Routinen |
| Multi-Channel | JA | Beleg-Erinnerungen via Telegram/Email |

### 2.2 Was NICHT vorhanden ist

| Faehigkeit | Status |
|---|---|
| Kontenrahmen (SKR03/SKR04) | NICHT VORHANDEN |
| Buchungssatz-Modell (Soll/Haben) | NICHT VORHANDEN |
| Belegerfassung-Pipeline | NICHT VORHANDEN |
| DATEV-Export | NICHT VORHANDEN |
| E-Rechnung-Parser (XRechnung/ZUGFeRD) | NICHT VORHANDEN |
| Bankabstimmung | NICHT VORHANDEN |
| UStVA-Vorbereitung | NICHT VORHANDEN |
| Kontoauszugs-Parser (CSV/MT940/CAMT) | NICHT VORHANDEN |
| Doppelte Buchfuehrung Engine | NICHT VORHANDEN |
| Steuerliche Validierungsregeln | NICHT VORHANDEN |

---

## 3. Diagnostizierte Hauptprobleme

### 3.1 Kein Buchhaltungsmodell

Die Bridge hat keine Datenstruktur fuer Buchungssaetze, Konten, Belege oder Steuerperioden.

### 3.2 Kein Kontenrahmen

SKR03 und SKR04 sind die deutschen Standardkontenrahmen. Ohne sie kann keine Kontierung vorgeschlagen werden.

### 3.3 Keine Beleg-Pipeline

Heute muesste ein User einen Beleg manuell hochladen, einem Agent erklaeren was draufsteht, und die Buchung selbst erfassen. Das ist keine Automatisierung.

### 3.4 Kein DATEV-Export

Ohne DATEV-kompatiblen Export ist die Plattform fuer den deutschen Markt nicht nutzbar, da 90%+ der Steuerberater DATEV nutzen.

### 3.5 Keine E-Rechnung-Verarbeitung

Ab 2025 muessen alle Unternehmen in Deutschland E-Rechnungen empfangen koennen. XRechnung (XML) und ZUGFeRD (PDF+XML) sind die Formate.

---

## 4. Zielarchitektur

### 4.1 Grundsatz

Die Buchhaltungsplattform ist eine Erweiterung der Bridge. Sie nutzt:

- **Vision-Analyse** fuer Beleg-OCR (Claude Vision)
- **Knowledge Engine** fuer Kontierungsregeln und Lieferanten-Mapping
- **Task-System** fuer Pruefworkflows
- **Approval Gates** fuer User-Freigabe kritischer Buchungen
- **DuckDB** (aus Big Data Spec) fuer Buchungsdaten und Auswertungen
- **Gemeinsames Job-Framework** (aus Big Data/Finance Specs) fuer Pipeline-Management

Optionale Backends:
- **Firefly III** (REST API, Docker) — vollstaendige doppelte Buchfuehrung
- **Akaunting** (REST API, Laravel) — modulare Buchhaltung
- **Eigenes Buchungsmodell** (JSON + DuckDB) — leichtgewichtig, kein externer Service

### 4.2 Datenmodell

#### Kontenrahmen

```json
{
  "chart_of_accounts": "SKR03",
  "accounts": [
    {"number": "1000", "name": "Kasse", "type": "asset", "tax_relevant": true},
    {"number": "1200", "name": "Bank", "type": "asset", "tax_relevant": true},
    {"number": "1400", "name": "Forderungen aLuL", "type": "asset", "tax_relevant": true},
    {"number": "1600", "name": "Verbindlichkeiten aLuL", "type": "liability", "tax_relevant": true},
    {"number": "1776", "name": "Umsatzsteuer 19%", "type": "liability", "tax_relevant": true},
    {"number": "1571", "name": "Vorsteuer 19%", "type": "asset", "tax_relevant": true},
    {"number": "4400", "name": "Erlöse 19% USt", "type": "revenue", "tax_relevant": true},
    {"number": "6300", "name": "Sonstige betriebliche Aufwendungen", "type": "expense", "tax_relevant": true}
  ]
}
```

SKR03 und SKR04 werden als JSON-Dateien mitgeliefert. User kann eigene Konten hinzufuegen.

#### Buchungssatz (GoBD-konform)

```json
{
  "booking_id": "bk_abc123",
  "booking_number": 1042,
  "booking_date": "2026-03-14",
  "receipt_date": "2026-03-13",
  "description": "Buerobedarfskauf Amazon",
  "entries": [
    {"account": "4930", "debit": 42.02, "credit": 0.00, "bu_key": 0},
    {"account": "1571", "debit": 7.98, "credit": 0.00, "bu_key": 9},
    {"account": "1200", "debit": 0.00, "credit": 50.00, "bu_key": 0}
  ],
  "receipt_id": "rc_xyz789",
  "receipt_number": "INV-2026-4711",
  "kost1": "",
  "kost2": "",
  "status": "draft",
  "finalized": false,
  "finalized_at": null,
  "created_by": "agent:bookkeeper",
  "confirmed_by": null,
  "confirmed_at": null
}
```

Felder (GoBD-relevant):

- `booking_number`: Fortlaufend, lueckenlos (GoBD Tz. 59)
- `booking_date`: Buchungsdatum (wann gebucht)
- `receipt_date`: Belegdatum (wann Beleg ausgestellt)
- `receipt_number`: Externe Belegnummer (Rechnungsnummer des Lieferanten)
- `bu_key`: BU-Schluessel / Steuerschluessel (DATEV-kompatibel, 0-99). Beispiele: 9 = Vorsteuer 19%, 8 = Vorsteuer 7%, 0 = kein automatischer Steuerschluessel.
- `kost1`, `kost2`: Kostenstellen (optional)
- `status`: `draft` → `confirmed` → `finalized`
- `finalized`: Festschreibungskennzeichen (GoBD). Einmal `true`, IRREVERSIBEL. Keine Aenderung mehr moeglich, nur Stornobuchung.

Zusaetzliche Felder:

- `storno_ref`: Referenz auf stornierten Buchungssatz (`"bk_original_id"` oder `null`). GoBD-Pflicht fuer Storno-Nachvollziehbarkeit.

Invarianten:
- Summe Soll = Summe Haben fuer jeden Buchungssatz. Ohne Gleichheit wird der Satz nicht gespeichert.
- `booking_number` wird bei Uebergang zu `confirmed` vergeben (nicht bei `draft`). Drafts haben `booking_number: null`. Lueckenlos und aufsteigend ab Vergabe.
- Nach `finalized = true` ist keine Feldaenderung mehr erlaubt.
- V1 unterstuetzt nur Kalenderjahr = Geschaeftsjahr. `WJ-Beginn` ist immer `YYYY0101`.
- V1 unterstuetzt nur EUR. Fremdwaehrungsbelege muessen manuell umgerechnet werden.

#### Audit-Trail-Modell

```json
{
  "audit_id": "au_abc123",
  "timestamp": "2026-03-14T10:15:00Z",
  "actor": "agent:bookkeeper",
  "action": "confirm",
  "entity_type": "booking",
  "entity_id": "bk_abc123",
  "old_value": {"status": "draft"},
  "new_value": {"status": "confirmed", "booking_number": 1042}
}
```

Storage: Append-only JSONL-Datei (`workspace/accounting/audit.jsonl`). Nie editierbar, nie loeschbar. Aufbewahrungsfrist: 10 Jahre.

#### Beleg

```json
{
  "receipt_id": "rc_xyz789",
  "type": "invoice",
  "source": "upload",
  "file_path": "receipts/2026/03/amazon_20260314.pdf",
  "vendor": "Amazon EU S.a r.l.",
  "date": "2026-03-14",
  "amount_gross": 50.00,
  "amount_net": 42.02,
  "tax_lines": [
    {"rate": 19, "net": 42.02, "tax": 7.98}
  ],
  "currency": "EUR",
  "extracted_at": "2026-03-14T10:10:00Z",
  "extraction_confidence": "high",
  "linked_booking_id": "bk_abc123"
}
```

### 4.3 Beleg-Pipeline

#### Stage-Modell

1. `upload` — Beleg wird hochgeladen (Foto, PDF, E-Rechnung)
2. `extract` — Agent extrahiert Daten via Vision-Analyse oder XML-Parser
3. `classify` — Agent klassifiziert: Rechnung, Gutschrift, Quittung, Kontoauszug
4. `match_vendor` — Lieferant wird gegen Knowledge Engine gematcht (bekannte Lieferanten haben gespeicherte Kontierungsregeln)
5. `propose_booking` — Agent schlaegt Buchungssatz vor (Konto, Gegenkonto, MwSt)
6. `validate` — Zweiter Agent oder Regelwerk prueft die Kontierung
7. `confirm` — User bestaetigt via Approval Gate oder korrigiert
8. `book` — Buchung wird persistent gespeichert

#### E-Rechnung-Verarbeitung

XRechnung (XML) und ZUGFeRD (PDF mit eingebettetem XML):

- XML wird direkt geparst — kein Vision/OCR noetig
- Felder: Lieferant, Rechnungsnummer, Datum, Positionen, MwSt, Gesamtbetrag
- Python-Library: `lxml` fuer XML-Parsing
- ZUGFeRD: PDF-Metadaten extrahieren, eingebettetes XML lesen

#### Vision-basierte Belegerfassung

Fuer Papierbelege und nicht-maschinenlesbare PDFs:

- `bridge_vision_analyze` mit Prompt: "Extrahiere: Lieferant, Datum, Rechnungsnummer, Nettobetrag, MwSt-Betrag, Bruttobetrag, MwSt-Satz"
- Ergebnis als strukturiertes JSON
- Konfidenz-Score pro extrahiertem Feld
- Bei Konfidenz `low`: User wird zur manuellen Pruefung aufgefordert

### 4.4 Agent-Rollen

#### Default: Single-Agent-Modus

Ein Agent uebernimmt alle Schritte: Extraktion, Klassifikation, Kontierungsvorschlag. User bestaetigt.

#### Opt-in: Zwei-Agent-Modus

- **Bookkeeper Agent**: Extrahiert und kontiert
- **Auditor Agent**: Prueft die Kontierung gegen Regeln und historische Muster

#### Kostenmodell

| Modus | Geschaetzte Kosten pro Beleg | Anwendungsfall |
|---|---|---|
| Single-Agent (Text-PDF) | $0.02 - $0.05 | E-Rechnung, maschinenlesbarer Beleg |
| Single-Agent (Vision/OCR) | $0.05 - $0.15 | Foto, gescannter Beleg |
| Zwei-Agent (mit Pruefung) | $0.10 - $0.25 | Komplexe Kontierung, hohe Betraege |

Basis: Claude Sonnet fuer Standard-Kontierung, Claude Opus fuer komplexe Faelle.

### 4.5 Lernende Kontierung

Die Knowledge Engine speichert Kontierungsregeln pro Lieferant:

```json
{
  "vendor": "Amazon EU S.a r.l.",
  "default_account": "6815",
  "default_tax_rate": 19,
  "frequency": 12,
  "last_used": "2026-03-14",
  "confidence": "high"
}
```

Nach 3+ identischen Kontierungen fuer denselben Lieferanten wird die Kontierung automatisch vorgeschlagen mit `confidence: high`. Der Agent lernt aus den User-Korrekturen.

### 4.6 DATEV-Export

#### DATEV-Buchungsstapel-Format (Version 13.0+)

Primaerquelle: DATEV-Schnittstellenbeschreibung (datev.de/dnlexom). Das Format hat 116+ Felder pro Buchungszeile. V1 implementiert die Pflichtfelder:

**Header-Record (Zeile 1):**

| Feld | Beschreibung | Beispiel |
|---|---|---|
| Formatversion | EXTF | `"EXTF"` |
| Versionsnummer | 700 | `700` |
| Datenkategorie | 21 (Buchungsstapel) | `21` |
| Formatname | Buchungsstapel | `"Buchungsstapel"` |
| Erzeugt am | YYYYMMDDHHMMSS | `"20260314120000"` |
| Berater-Nr | 7-stellig | `"1234567"` |
| Mandanten-Nr | 5-stellig | `"12345"` |
| WJ-Beginn | YYYYMMDD | `"20260101"` |
| Sachkontenlaenge | 4 | `4` |
| Datum von | YYYYMMDD | `"20260301"` |
| Datum bis | YYYYMMDD | `"20260331"` |

**Buchungszeile (Pflichtfelder V1):**

| Feld-Nr | Feldname | Typ | Beschreibung |
|---|---|---|---|
| 1 | Umsatz | Dezimal | Bei BU > 0: Bruttobetrag (DATEV rechnet Steuer heraus). Bei BU = 0: Nettobetrag. |
| 2 | Soll/Haben | S oder H | Kennzeichen |
| 3 | WKZ Umsatz | Text | Waehrung (EUR) |
| 7 | Konto | Zahl | Gegenkonto (Kreditor/Debitor oder Sachkonto) |
| 8 | Gegenkonto | Zahl | Sachkonto |
| 9 | BU-Schluessel | Zahl | Steuerschluessel (0-99) |
| 10 | Belegdatum | DDMM | Datum des Belegs |
| 11 | Belegfeld 1 | Text | Rechnungsnummer |
| 14 | Buchungstext | Text | Beschreibung |
| 36 | KOST1 | Text | Kostenstelle 1 (optional) |
| 37 | KOST2 | Text | Kostenstelle 2 (optional) |
| 114 | Festschreibung | 0 oder 1 | GoBD-Festschreibungskennzeichen |

**BU-Schluessel-Tabelle (Auszug):**

| BU | Bedeutung |
|---|---|
| 0 | Kein automatischer Steuerschluessel |
| 2 | Umsatzsteuer 7% |
| 3 | Umsatzsteuer 19% |
| 8 | Vorsteuer 7% |
| 9 | Vorsteuer 19% |
| 40 | Innergemeinschaftliche Lieferung |

Vollstaendige BU-Schluessel-Tabelle wird als JSON mitgeliefert.

Python-Library: Eigenentwicklung (DATEV-Format ist dokumentiert). Akzeptanztest: DATEV-Import bei realem Steuerberater muss ohne Fehler durchlaufen (Phase D).

#### Workflow

1. User waehlt Zeitraum (Monat/Quartal/Jahr)
2. System exportiert alle bestaetigten Buchungen im DATEV-Format
3. Begleitende Belegdateien werden als ZIP-Archiv bereitgestellt
4. Export via `GET /accounting/datev-export?period=2026-03`

### 4.7 Bankabstimmung

#### Kontoauszugs-Import

- MT940/CAMT-Import als primaere Formate (standardisiert, zuverlaessig parsbar)
- CSV-Import mit explizitem Spalten-Mapping pro Bank (kein Auto-Detect — Formate sind zu unterschiedlich)
- Vorkonfigurierte Mappings fuer gaengige Banken (Sparkasse, ING, DKB, Commerzbank)

#### Matching-Logik

1. Exakter Match: Betrag + Datum + Verwendungszweck → eindeutiger Beleg
2. Fuzzy Match: Betrag + Zeitfenster (±3 Tage) + Lieferantenname im Verwendungszweck
3. Kein Match: Agent markiert als "offen", User muss manuell zuordnen

#### Abstimmungsergebnis

- Gematcht: Beleg ↔ Bankbewegung verbunden
- Differenz: Betrag stimmt nicht ueberein → Warnung
- Offen: Bankbewegung ohne Beleg → User-Aktion noetig
- Doppelt: Mehrere Belege fuer eine Bankbewegung → Warnung

### 4.8 UStVA-Vorbereitung

Automatische Berechnung der Umsatzsteuer-Voranmeldung aus festgeschriebenen Buchungen.

Pflicht-Kennzahlen (V1):

| KZ | Beschreibung | Berechnung aus |
|---|---|---|
| 81 | Steuerpflichtige Umsaetze 19% | Konten mit BU 3 |
| 86 | Steuerpflichtige Umsaetze 7% | Konten mit BU 2 |
| 66 | Vorsteuerbetraege | Konten mit BU 8, 9 |
| 83 | Verbleibende USt-Vorauszahlung (Zahllast) | KZ 81*0.19 + KZ 86*0.07 - KZ 66 |

Erweiterung (V2+, fuer EU-Geschaeft):

| KZ | Beschreibung |
|---|---|
| 21 | Innergemeinschaftliche Lieferungen |
| 46 | Nicht steuerbare sonstige Leistungen |
| 67 | Vorsteuer innergemeinschaftlicher Erwerb |

Export als PDF oder CSV.
KEIN automatisches ELSTER-Filing — nur Vorbereitung fuer den Steuerberater.

### 4.9 Fehlerbehandlung

Uebernahme aus dem gemeinsamen Job-Framework (siehe Big Data / Finance Specs):

| Parameter | Default |
|---|---|
| `max_retries_per_stage` | 3 |
| `stage_timeout_s` | 120 |
| `job_timeout_s` | 600 |

Buchhaltungs-spezifisch:

| Fehler | Verhalten |
|---|---|
| Beleg nicht lesbar (Vision) | Status `extraction_failed`, User wird informiert |
| Soll ≠ Haben | Buchungssatz wird abgelehnt, Agent muss korrigieren |
| Unbekanntes Konto | Warnung, Vorschlag des naechstliegenden Kontos |
| Doppelter Beleg (gleicher Lieferant, gleiches Datum, gleicher Betrag) | Warnung, User muss bestaetigen |
| Agent-Ausfall (Auditor antwortet nicht innerhalb stage_timeout) | Buchung wird `validation_timeout`, User zur manuellen Pruefung aufgefordert |
| Agent-Ausfall (Bookkeeper antwortet nicht) | Job failt mit `agent_timeout`, User wird informiert |

---

## 4B. GoBD-Konformitaet

Primaerquelle: BMF-Schreiben vom 28.11.2019 (IV A 4 - S 0316/19/10003:001).

### Anforderungen und Umsetzung

| GoBD-Anforderung | Umsetzung in der Plattform |
|---|---|
| Nachvollziehbarkeit | Audit-Trail: Wer hat wann was gebucht/geaendert/storniert (append-only Log) |
| Nachpruefbarkeit | Jeder Buchungssatz referenziert einen Beleg. Beleg ist persistent gespeichert. |
| Unveraenderbarkeit | Festschreibung (`finalized = true`, irreversibel). Aenderungen nur via Stornobuchung. |
| Vollstaendigkeit | Fortlaufende, lueckenlose Belegnummern. Soll = Haben Invariante. |
| Richtigkeit | Agent-Kontierung + Pruefung (Zwei-Agent oder Approval Gate) |
| Zeitnaehe | Buchungsdatum wird automatisch gesetzt. Belegdatum wird aus Beleg extrahiert. |
| Ordnung | Kontenrahmen SKR03/SKR04 als Ordnungsstruktur |
| Aufbewahrungsfristen | 10 Jahre fuer Buchungsbelege und Buchungen. 6 Jahre fuer Geschaeftskorrespondenz. Technisch: kein automatisches Loeschen vor Ablauf der Frist. |
| Maschinelle Auswertbarkeit | Daten in DuckDB/JSON. DATEV-Export. Filterbar nach Konto, Periode, Betrag. |
| Verfahrensdokumentation | Pflichtdokument fuer V1: beschreibt die maschinelle Belegverarbeitung, Kontierungslogik, Festschreibungsprozess und DATEV-Exportverfahren. |
| Internes Kontrollsystem | Single-Agent: Approval Gate als Vier-Augen-Ersatz. Zwei-Agent: Bookkeeper + Auditor. Betraege ueber konfigurierbarer Schwelle (Default: 500 EUR): Approval Gate. Bekannte Lieferanten mit `confidence: high` koennen ausgenommen werden (opt-in). |

## 5. Nicht verhandelbare Anforderungen

### Regulatorisch

1. Jeder Buchungssatz erfuellt GoB und GoBD (siehe Sektion 4B).
2. Belege werden nie geloescht, nur storniert. Festgeschriebene Buchungen sind irreversibel.
3. Aufbewahrungsfristen: 10 Jahre fuer Buchungen und Belege. Kein automatisches Loeschen.
4. DATEV-Export muss vom Steuerberater ohne Nacharbeit importierbar sein.
5. Disclaimer: "Maschinelle Vorkontierung — keine steuerliche Beratung. Pruefung durch Steuerberater empfohlen."
6. Verfahrensdokumentation ist Pflichtbestandteil von V1.

### Qualitaet

5. Jeder Buchungssatz hat Soll = Haben (Invariante, nicht verhandelbar).
6. Kontierungsvorschlaege haben Konfidenz-Score (high/medium/low).
7. Bei Konfidenz `low` oder Betrag > 500 EUR: Approval Gate vor Buchung.
8. Audit-Trail: Wer hat wann was gebucht/geaendert/storniert.

### Technisch

9. Belege werden lokal gespeichert unter `workspace/accounting/receipts/YYYY/MM/`.
10. Buchungsdaten in DuckDB (oder JSON als V1-Fallback).
11. SKR03 und SKR04 als JSON mitgeliefert.
12. E-Rechnungen (XRechnung/ZUGFeRD) koennen ohne Vision-API verarbeitet werden.

---

## 6. API-Spec

### 6.1 Belege

- `POST /accounting/receipts/upload` — Beleg hochladen (PDF, Bild, XML)
- `GET /accounting/receipts` — alle Belege auflisten
- `GET /accounting/receipts/{id}` — Beleg-Details mit Extraktionsergebnis
- `POST /accounting/receipts/{id}/reextract` — erneute Extraktion ausloesen

### 6.2 Buchungen

- `POST /accounting/bookings` — Buchungssatz erstellen
- `GET /accounting/bookings` — alle Buchungen (filterbar nach Periode, Konto, Status)
- `GET /accounting/bookings/{id}` — Buchungsdetails
- `PUT /accounting/bookings/{id}/confirm` — User bestaetigt
- `POST /accounting/bookings/{id}/storno` — Stornobuchung erstellen (erzeugt Gegenbuchung mit `storno_ref` auf Original)
- `PUT /accounting/bookings/{id}/finalize` — Festschreibung (irreversibel, GoBD)
- `POST /accounting/bookings/finalize-period?period=YYYY-MM` — Alle bestaetigten Buchungen einer Periode festschreiben
- `GET /accounting/audit?entity_id={id}` — Audit-Trail fuer eine Buchung/Beleg abrufen
- `GET /accounting/audit?period=YYYY-MM` — Audit-Trail fuer eine Periode

### 6.3 Kontenrahmen

- `GET /accounting/chart` — aktiver Kontenrahmen
- `POST /accounting/chart/accounts` — eigenes Konto hinzufuegen

### 6.4 Export

- `GET /accounting/datev-export?period=YYYY-MM` — DATEV-Export
- `GET /accounting/ustva?period=YYYY-MM` — UStVA-Vorbereitung
- `GET /accounting/journal?period=YYYY-MM` — Buchungsjournal als PDF

### 6.5 Bankabstimmung

- `POST /accounting/bank/import` — Kontoauszug importieren (CSV/MT940/CAMT)
- `GET /accounting/bank/unmatched` — nicht zugeordnete Bankbewegungen
- `POST /accounting/bank/match` — manuelle Zuordnung Beleg ↔ Bankbewegung

### 6.6 MCP-Tools (fuer Agents)

- `bridge_accounting_receipt_extract` — Beleg-Daten extrahieren
- `bridge_accounting_booking_propose` — Buchungssatz vorschlagen
- `bridge_accounting_booking_validate` — Buchungssatz pruefen
- `bridge_accounting_datev_export` — DATEV-Export erstellen

---

## 7. Integrierbarer Tool-Stack

### 7.1 Open-Source-Backends (optional)

| Tool | Zweck | Integration | Staerke |
|---|---|---|---|
| **Firefly III** | Doppelte Buchfuehrung, Konten, Transaktionen | REST API, Docker | Ausgereift, aktive Community, gute API |
| **Akaunting** | Modulare Buchhaltung, Invoicing | REST API, Laravel | Modern, modular, App Store |
| **GnuCash** | Desktop-Buchhaltung | Datei-basiert (kein API) | Etabliert, aber kein Web-API |

V1-Empfehlung: Eigenes leichtgewichtiges Modell (JSON + DuckDB). Firefly III als optionale Integration fuer User, die ein vollstaendiges Buchhaltungssystem wollen.

### 7.2 Python-Libraries

| Library | Zweck | Status |
|---|---|---|
| **lxml** | XRechnung/ZUGFeRD XML-Parsing | pip install |
| **pdfplumber** | PDF-Textextraktion (maschinenlesbare PDFs, kein OCR) | pip install |
| **pytesseract** | OCR fuer gescannte Belege/Fotos (Privacy-First-Modus) | pip install + tesseract-ocr System-Package |
| **pandas** | Kontoauszugs-Verarbeitung, Aggregation | Bereits vorhanden |
| **DuckDB** | Buchungsdaten-Speicher und Auswertungen | Geteilt mit Big Data / Finance |

### 7.3 Referenz-Tools

| Tool | Inspiration | Was wir uebernehmen |
|---|---|---|
| **TaxHacker** (GitHub: vas3k/TaxHacker) | Self-hosted AI Belegerfassung | Prompt-basierte Kategorisierung mit Custom-Rules |
| **BuchhaltungsButler** | AI-Kontierung mit DATEV-Export | Lernende Kontierung pro Lieferant |
| **sevDesk** | E-Rechnung + Bankanbindung | UX-Referenz fuer Beleg-Pipeline |

---

## 8. Sicherheit

### 8.1 Datenschutz

Buchungsdaten, Portfolio-Daten und Kontenrahmen bleiben lokal. Belege haben zwei Verarbeitungsmodi:

**Modus 1: E-Rechnung (XRechnung/ZUGFeRD) — vollstaendig lokal**
- XML wird lokal geparst (lxml). Keine externen API-Calls.
- Keine Daten verlassen den Rechner.
- Empfohlener Standard-Modus.

**Modus 2: Vision-basierte Belegerfassung — sendet Daten an Anthropic**
- Belegbilder werden base64-kodiert an die Anthropic Vision API gesendet.
- Belege SIND Finanzdaten (Firmenname, Steuernummer, Bankverbindung, Betraege).
- Anthropic speichert Eingaben fuer Abuse-Monitoring (30 Tage, Stand Anthropic Usage Policy).
- Fuer deutsche Finanzdaten gelten DSGVO Art. 28 und GoBD Tz. 104.
- User muss diesem Modus explizit zustimmen (Approval Gate beim ersten Beleg).

**Modus 3: Privacy-First-Fallback — lokal, reduzierte Genauigkeit**
- Maschinenlesbare PDFs: pdfplumber (Textextraktion, kein OCR)
- Gescannte Belege/Fotos: Tesseract OCR (lokal, Open Source)
- Kontierung: lokales LLM (UNKNOWN ob ausreichend genau fuer Produktivbetrieb)
- Kein API-Call, keine Daten verlassen den Rechner

User waehlt den Modus bei Einrichtung. Default: Modus 1 (E-Rechnung) + Modus 2 (Vision mit Zustimmung).

### 8.2 Unveraenderlichkeit

- Buchungssaetze werden nie ueberschrieben, nur storniert
- Stornobuchungen referenzieren den Originalsatz
- Audit-Log ist append-only

---

## 9. Test-Spec

### 9.1 Pflicht-Testmatrix

#### Belegtypen

- PDF-Rechnung (maschinenlesbar)
- Foto-Quittung (Vision-basiert)
- XRechnung (XML)
- ZUGFeRD (PDF + XML)
- Amazon-Rechnung, Telekom-Rechnung (haeufige Lieferanten)

#### Buchungstypen

- Einfache Ausgabe (1 Konto + MwSt + Bank)
- Erloes mit 19% und 7% MwSt
- Innergemeinschaftlicher Erwerb
- Stornobuchung

#### Bankabstimmung

- CSV-Import (Sparkasse-Format, ING-Format)
- Exakter Match
- Fuzzy Match
- Kein Match

### 9.2 Acceptance Criteria

1. E-Rechnung (XRechnung) wird ohne Vision-API korrekt verarbeitet in <5s
2. PDF-Rechnung wird via Vision korrekt extrahiert in <15s
3. Kontierungsvorschlag fuer bekannten Lieferanten hat Konfidenz `high`
4. DATEV-Export fuer 100 Buchungen wird in <10s erstellt
5. Soll ≠ Haben wird in jedem Fall abgelehnt (Invariante)
6. Bankabstimmung matcht 80%+ der Transaktionen automatisch

---

## 10. Umsetzungs-Slices

### Phase A — Datenmodell

#### Slice A1 — Kontenrahmen + Buchungsmodell

- SKR03/SKR04 als JSON
- Buchungssatz-Modell mit Soll/Haben-Invariante
- CRUD-Endpoints fuer Buchungen
- DuckDB-Speicher (oder JSON-Fallback)

#### Slice A2 — Belegmodell + Upload

- Beleg-Upload-Pipeline
- Beleg-Metadaten-Modell
- Verknuepfung Beleg ↔ Buchung

### Phase B — Intelligenz

#### Slice B1 — Beleg-Extraktion

- Vision-basierte Extraktion fuer Fotos/PDFs
- XRechnung/ZUGFeRD XML-Parser
- Konfidenz-Scoring
- Knowledge-Engine-basiertes Lieferanten-Mapping

#### Slice B2 — Lernende Kontierung

- Automatischer Kontierungsvorschlag basierend auf Lieferant + Betrag + Historie
- Zwei-Agent-Pruefung (optional)
- Approval Gate fuer unsichere Kontierungen

### Phase C — Export (Pflicht)

#### Slice C1 — DATEV-Export + UStVA

- DATEV-ASCII-Export
- UStVA-Vorbereitung
- Buchungsjournal-PDF

#### Slice C2 — Bankabstimmung (optional, kann auf V2 verschoben werden)

- MT940/CAMT-Import als primaere Formate (standardisiert, zuverlaessig parsbar)
- CSV-Import als sekundaer mit expliziter Format-Konfiguration pro Bank (Spalten-Mapping, kein Auto-Detect)
- Matching-Algorithmus (exakt, fuzzy, manuell)

### Phase D — Haertung

#### Slice D1 — E2E-Tests

- Vollstaendiger Beleg-zu-DATEV-Durchlauf
- Steuerberater-Akzeptanztest (DATEV-Import bei echtem Steuerberater)
- Fehler-Injection (unleserlicher Beleg, falscher MwSt-Satz, Doppelbuchung)

### Priorisierung

Phase A: Ohne Datenmodell keine Buchung.
Phase B: Der Kern — Agent-gestuetzte Automatisierung.
Phase C: Der Nutzwert — ohne DATEV-Export und Bankabstimmung keine Praxisrelevanz.
Phase D: Produktionshaertung.

### Abhaengigkeiten

- DuckDB-Integration (aus Big Data Phase A) als Voraussetzung oder JSON-Fallback fuer V1
- Gemeinsames Job-Framework (aus Big Data/Finance) fuer Pipeline-Management
- Vision-API ist bereits verfuegbar (`bridge_vision_analyze`)

---

## 11. Synergien

| Komponente | Geteilt mit Big Data / Finance |
|---|---|
| DuckDB | Ja — eigenes Schema `accounting` |
| Job-Framework | Ja — Beleg-Pipeline als Job-Typ |
| Report-Engine | Ja — PDF-Generierung via weasyprint |
| Knowledge Engine | Ja — Kontierungsregeln unter `Projects/accounting/` |
| Vision-API | Ja — `bridge_vision_analyze` fuer Beleg-OCR |
| Fehlerbehandlung | Ja — gemeinsame Timeouts und Retry-Logik |

---

## 12. Abgrenzung

### Was die Plattform NICHT ist

- Kein ERP-System (keine Warenwirtschaft, keine Lagerhaltung)
- Kein Lohnbuchhaltungssystem (keine Gehaltsabrechnungen)
- Kein Steuerberater-Ersatz (keine steuerliche Beratung)
- Kein ELSTER-Client (kein direktes Filing beim Finanzamt)
- Kein Invoicing-System (keine Rechnungsstellung/Ausgangsrechnungen in V1). E-Rechnungs-Sendepflicht ab 2027/2028 ist spaeterer Erweiterungspunkt.
- Kein Firefly-III-Ersatz in V1 (eigenes leichtgewichtiges Modell. Firefly III als optionale Integration, wobei Firefly III dann SoT fuer Buchungen ist, Bridge liest via REST API.)

### Was sie IST

- Eine lokale, private, Agent-gestuetzte Buchhaltungs-Vorbereitungsplattform
- Fuer die Automatisierung von Belegerfassung, Kontierung und DATEV-Export
- Mit erklaerbaren, pruefbaren Buchungsvorschlaegen
- Die Freelancern und KMU die Buchhaltungs-Vorarbeit abnimmt

---

## 13. Marktrecherche-Quellen

Recherche durchgefuehrt am 2026-03-14.

- TaxHacker: Self-hosted AI Belegerfassung — github.com/vas3k/TaxHacker
- Firefly III: REST API, Docker, Open Source — firefly-iii.org
- Akaunting: REST API, Laravel, modular — akaunting.com
- Bigcapital: Open-Source Buchhaltung, QuickBooks-Alternative — github.com/bigcapitalhq/bigcapital
- DATEV-Schnittstellenbeschreibung: datev.de/dnlexom (Primaerquelle)
- GoBD: BMF-Schreiben vom 28.11.2019 (IV A 4 - S 0316/19/10003:001) (Primaerquelle)
- E-Rechnung: Wachstumschancengesetz vom 22.03.2024 (BGBl. 2024 I Nr. 108) (Primaerquelle). Empfangspflicht B2B ab 01.01.2025, Sendepflicht gestaffelt ab 2027/2028.
- DATEV-Marktanteil: Branchenkenntnis, keine verifizierbare Primaerquelle fuer "90%+".
- AI in Accounting: 90% der Finance-Funktionen nutzen bis 2026 mindestens eine AI-Technologie — dualentry.com
- BuchhaltungsButler: AI-Kontierung mit DATEV-Level Kontrolle — norman.finance
- sevDesk/lexoffice: UX-Referenz fuer deutsche KMU-Buchhaltung — norman.finance
