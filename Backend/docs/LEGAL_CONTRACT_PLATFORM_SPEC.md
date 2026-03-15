# LEGAL & CONTRACT ANALYSIS PLATFORM SPEC

Stand: 2026-03-14
Autor: Viktor (Operative Projektleitung BRIDGE)
Revision: R3 — Battle-Review 3 Runden abgeschlossen
Status: FREIGEGEBEN — Implementierungsgrundlage

---

## 1. Ziel

Die BRIDGE wird um eine Legal/Vertragsanalyse-Plattform erweitert. Agents lesen Vertraege, extrahieren Klauseln, identifizieren Risiken, vergleichen mit Standards und generieren Redline-Vorschlaege — lokal, privat, ohne Cloud-Abhaengigkeit.

### 1.1 Produkt-Differenzierung

Warum die BRIDGE statt Ironclad ($25k-$150k/Jahr), Spellbook ($40-179/User/Monat) oder manueller Vertragspruefung:

1. **Lokal + privat** — Mandantendaten und Vertraege verlassen nie den Rechner. Anwaltliche Verschwiegenheitspflicht ist architektonisch gesichert, nicht nur per Policy.
2. **Multi-Agent-Analyse** — Klausel-Agent extrahiert, Risiko-Agent bewertet, Compliance-Agent prueft DSGVO/DPA, Redline-Agent schlaegt Aenderungen vor. Kein Single-Model-Pipeline.
3. **Keine Plattformgebuehr** — LLM-API-Kosten pro Vertrag. Geschaetzt $5-$15 pro 40-Seiten-Vertrag (5 Stages × ~25k Input-Tokens + Output). Single-Agent am unteren Ende, Multi-Agent am oberen. Kein $25k/Jahr Lizenzvertrag.
4. **Knowledge Vault fuer Vertraege** — Knowledge Engine speichert Vertraege, Klausel-Bibliotheken, Playbooks und Praezedenzfaelle mit semantischer Suche.
5. **Vision-Pipeline fuer Scans** — `bridge_vision_analyze` verarbeitet gescannte Vertraege per OCR. Kein externer OCR-Service noetig.
6. **CUAD-Taxonomie** — 41 Klauseltypen aus dem CUAD-Dataset (NeurIPS 2021) als Erkennungs-Taxonomie. Risikobewertung ist eine eigene LLM-basierte Schicht oberhalb der Erkennung — CUAD liefert keine Risiko-Scores, nur Klausel-Klassifikation.

### 1.2 Zielgruppen

- Solo-Anwaelte und kleine Kanzleien (1-10 Anwaelte)
- KMU-Rechtsabteilungen ohne CLM-Budget
- Freelancer die Vertraege pruefen muessen (NDAs, Dienstleistungsvertraege)
- Startups die Standard-Vertraege schnell reviewen wollen
- Compliance-Teams die DPA/DSGVO-Konformitaet pruefen muessen

### 1.3 Wichtiger Hinweis

Die Plattform ersetzt KEINE anwaltliche Beratung. Sie automatisiert die Vorarbeit: Klausel-Extraktion, Risiko-Identifikation, Standard-Vergleich. Die rechtliche Bewertung und Entscheidung liegt beim User oder seinem Anwalt.

### 1.4 6-Monats-Vision

In 6 Monaten soll ein User:

1. Vertrag hochladen (PDF, DOCX, gescanntes Dokument)
2. Agent extrahiert automatisch: Parteien, Laufzeit, Kuendigungsfristen, Haftung, Gerichtsstand, Vertraulichkeit
3. Agent identifiziert Risiken (fehlende Klauseln, unuebliche Formulierungen, einseitige Bedingungen)
4. Agent vergleicht mit Klausel-Bibliothek und Playbook
5. Agent generiert Redline-Vorschlaege
6. Bei DPA/DSGVO-Vertrag: automatische Pruefung gegen Art. 28 DSGVO
7. Report mit Risikobewertung, Klausel-Analyse und Empfehlungen

---

## 2. Verifizierter Ist-Zustand

### 2.1 Was die BRIDGE heute hat

| Faehigkeit | Vorhanden | Details |
|---|---|---|
| Vision/Bildanalyse | JA, aber KEIN Dokumenten-OCR | `bridge_vision_analyze` ist ein UI-Screenshot-Analyser. Fuer gescannte Vertraege: PDF → Bilder (pdf2image/poppler) → seitenweise Vision-API. Pipeline muss gebaut werden. |
| Knowledge Engine | JA | Vault fuer Vertraege, Klausel-Bibliotheken, Playbooks |
| Semantic Memory | JA | Semantische Suche ueber historische Vertraege |
| PDF-Lesen | JA | Read-Tool kann PDFs lesen |
| Multi-Agent | JA | Agent-Koordination, Task-System, Whiteboard |
| Multi-Channel | JA | Report-Distribution via Email, Telegram |

### 2.2 Was NICHT vorhanden ist

| Faehigkeit | Status |
|---|---|
| Klausel-Extraktion (NER fuer Legal) | NICHT VORHANDEN |
| Risiko-Scoring pro Klausel | NICHT VORHANDEN |
| Klausel-Bibliothek / Playbook-System | NICHT VORHANDEN |
| Redline-Generierung | NICHT VORHANDEN |
| DPA/DSGVO-Pruefung | NICHT VORHANDEN |
| DOCX-Verarbeitung | NICHT VORHANDEN (pdfplumber fuer PDF, python-docx fuer DOCX noetig) |
| Vertragsvergleich (Diff) | NICHT VORHANDEN |

### 2.3 LegalZoom Plugin (verifiziert am 2026-03-14)

Das `legalzoom`-Plugin ist im Claude Code Marketplace gelistet (`claude-plugins-official`). Repository: `github.com/legalzoom/claude-plugins` (public, Lizenz: PROPRIETARY).

**Zwei Commands:**

| Command | Typ | MCP-Calls | Fuer uns nutzbar |
|---|---|---|---|
| `/review-contract` | **Reines Prompt-Template** (146 Zeilen Markdown) | KEINE — reine AI-Analyse | **JA — Workflow 1:1 uebertragbar als Bridge-Skill** |
| `/attorney-assist` | LegalZoom-Anwaltsvermittlung ($43.17/Monat) | JA — `legalzoom.com/mcp/claude/v1` | NEIN — braucht LegalZoom-Account, proprietaerer MCP-Server |

**Was `/review-contract` konkret tut (verifiziert im Quellcode):**
1. Vertrag empfangen (PDF, DOCX, Text, Dateipfad)
2. Kontext sammeln (Rolle des Users, Deal-Groesse, Prioritaeten)
3. Vertragstyp, Governing Law, Parteien identifizieren
4. Klausel-fuer-Klausel-Analyse: Liability, Indemnification, IP, Data/Privacy, Confidentiality, Warranties, Term/Termination, Dispute Resolution, Payment, Assignment
5. Pro Klausel: GREEN/YELLOW/RED + Confidence 0-100% + Vergleich mit Marktstandard + praktischer Impact
6. Redline-Vorschlaege fuer YELLOW/RED Items mit Prioritaet (Essential/Important/Preferred)
7. Attorney-Review-Empfehlung bei: RED Findings, Confidence <70%, Deal >$100k, Regulatory Overlay

**Integration in die Bridge:**

Der `/review-contract` Workflow wird als Bridge-Skill nachgebaut unter `~/.claude/skills/contract-review/SKILL.md`. Die Prompt-Logik ist frei einsehbar und nicht durch MCP-Calls geschuetzt. Keine LegalZoom-Abhaengigkeit.

Die Bridge ERWEITERT den Workflow um:
- Multi-Agent-Koordination (Review-Agent + DPA-Agent + Compliance-Agent)
- Persistente Klausel-Bibliothek in Knowledge Engine
- Historische Vertragssuche via Semantic Memory
- DPA/DSGVO-spezifische Pruefung (nicht im LegalZoom-Plugin)
- Multi-Channel Report-Distribution

**Hinweis:** Plugin-Installation scheitert aktuell an SSH-Key-Konfiguration (git@github.com Permission denied). Repository ist via HTTPS public erreichbar. Manueller Clone funktioniert: `git clone https://github.com/legalzoom/claude-plugins.git`

### 2.4 Weitere verfuegbare Tools

| Tool | Zweck | Lizenz |
|---|---|---|
| **CUAD Dataset** | 41 Klauseltypen, 510 Vertraege, 13.000+ Labels | CC BY 4.0 |
| **claude-legal-skill** | CUAD Risk Detection + Redlines fuer Claude Code | Open Source (GitHub: evolsb) |
| **spaCy** | NER, Dependency Parsing, Transformer-Pipelines | MIT |
| **pdfplumber** | PDF-Textextraktion mit Layout | MIT |
| **python-docx** | DOCX-Verarbeitung | MIT |
| **sentence-transformers** | Semantische Klausel-Aehnlichkeit | Apache 2.0 |

---

## 3. Zielarchitektur

### 3.1 Vertragspruefungs-Pipeline

#### Stage-Modell (V1: 5 Stages)

1. `extract` — Text aus PDF/DOCX/Scan extrahieren (pdfplumber, python-docx, Vision-API)
2. `analyze` — Klauseln identifizieren, Parteien/Laufzeit/Bedingungen extrahieren
3. `risk_assess` — Risiken bewerten gegen CUAD-Benchmark und Playbook
4. `redline` — Aenderungsvorschlaege generieren
5. `report` — Zusammenfassung mit Risiko-Matrix und Empfehlungen

### 3.2 Agent-Modi

**Default: Single-Agent.** Ein Agent durchlaeuft alle Stages. Kosten: $3-$8 pro Vertrag (kurze Vertraege <10 Seiten am unteren Ende, 40+ Seiten am oberen).

**Opt-in: Multi-Agent.** Fuer komplexe Vertraege (M&A, Lizenzvertraege):
- Extraction Agent — Dokument-Parsing
- Risk Agent — CUAD-basierte Risikobewertung
- Compliance Agent — DSGVO/DPA-Pruefung
- Redline Agent — Aenderungsvorschlaege

### 3.3 Klausel-Bibliothek

Gespeichert in Knowledge Engine unter `Shared/Legal/`:

```
Shared/Legal/
├── Playbooks/
│   ├── NDA_Standard.md
│   ├── Dienstleistungsvertrag_Standard.md
│   └── DPA_Art28_Checklist.md
├── Klauseln/
│   ├── Haftungsbeschraenkung_DE.md
│   ├── Gerichtsstand_DE.md
│   └── Kuendigungsfristen_Standard.md
└── Templates/
    ├── NDA_Template.md
    └── DPA_Template.md
```

User kann eigene Playbooks und Klauseln hinzufuegen. Agent vergleicht jeden Vertrag gegen das relevante Playbook.

### 3.4 DPA/DSGVO-Pruefung

Automatische Pruefung von Auftragsverarbeitungsvertraegen gegen Art. 28 DSGVO:

| Pflicht-Klausel (Art. 28 Abs. 3) | Pruefung |
|---|---|
| Gegenstand und Dauer der Verarbeitung | Vorhanden? Konkret genug? |
| Art und Zweck der Verarbeitung | Vorhanden? |
| Art der personenbezogenen Daten | Kategorien genannt? |
| Kategorien betroffener Personen | Genannt? |
| Weisungsgebundenheit | Klausel vorhanden? |
| Vertraulichkeit | Mitarbeiterverpflichtung? |
| Technische und organisatorische Massnahmen | Konkret beschrieben? |
| Unterauftragsverarbeiter | Regelung vorhanden? Genehmigungsvorbehalt? |
| Unterstuetzung bei Betroffenenrechten | Geregelt? |
| Loeschung/Rueckgabe nach Vertragsende | Geregelt? |
| Nachweispflichten und Audits | Geregelt? |

### 3.5 Fehlerbehandlung

| Parameter | Default |
|---|---|
| `extraction_timeout_s` | 120 |
| `analysis_timeout_s` | 300 |
| `max_pages` | 200 |

| Fehler | Verhalten |
|---|---|
| PDF nicht lesbar | Fallback auf Vision-API (OCR) |
| DOCX korrupt | Fehlermeldung, kein stiller Fehlschlag |
| Vertrag >200 Seiten | Chunked Processing (kapitelweise) |
| Unbekannte Sprache | Warnung, Analyse auf Englisch/Deutsch beschraenkt (V1) |
| Agent-Timeout | Job failt mit klarer Fehlermeldung |

---

## 4. API-Spec

Alle Endpoints durch Bridge 3-Tier Auth geschuetzt.

- `POST /legal/analyze` — Vertrag hochladen und Analyse starten
- `GET /legal/jobs/{id}` — Analyse-Status
- `GET /legal/jobs/{id}/report` — Report abrufen (PDF/HTML/JSON)
- `GET /legal/playbooks` — verfuegbare Playbooks auflisten
- `POST /legal/playbooks` — eigenes Playbook hinzufuegen
- `POST /legal/compare` — zwei Vertraege vergleichen (Diff)

MCP-Tools:
- `bridge_legal_analyze` — Vertragsanalyse starten
- `bridge_legal_risk_check` — Risikobewertung fuer spezifische Klausel
- `bridge_legal_dpa_check` — DPA gegen Art. 28 DSGVO pruefen

---

## 5. Nicht verhandelbare Anforderungen

1. Vertragsdaten: Die Analyse-Pipeline sendet Vertragsinhalte an die Claude API. Das ist NICHT lokal. Fuer anwaltlich privilegierte Dokumente (§43a Abs. 2 BRAO, §2 BORA) muss der MANDANT (nicht der Anwalt) der Cloud-Verarbeitung zustimmen. Anthropic Data Processing Addendum muss geprueft werden. Alternative: lokales LLM (Ollama) fuer maximale Vertraulichkeit — mit reduzierter Qualitaet. V1-Empfehlung: Cloud-API mit expliziter Aufklaerung und Mandanten-Einwilligung.
2. Disclaimer: "Maschinelle Vertragsanalyse — keine anwaltliche Beratung."
3. Risikobewertungen haben Konfidenz-Score (high/medium/low).
4. Playbooks sind vom User anpassbar.
5. V1: Deutsch und Englisch. Weitere Sprachen spaeter.

---

## 6. Umsetzungs-Slices

### Phase A — Extraktion
- PDF/DOCX-Text-Extraktion (pdfplumber, python-docx)
- Vision-Fallback fuer Scans
- Klausel-Segmentierung

### Phase B — Analyse
- Risikobewertung gegen CUAD-Benchmark
- Playbook-Vergleich
- DPA/DSGVO-Pruefung

### Phase C — Output
- Redline-Generierung
- Report-Engine (PDF/HTML)
- Vertragsvergleich (Diff)

### Phase D — Haertung
- Klausel-Bibliothek-Management
- Multi-Sprach-Erweiterung
- Historische Vertragssuche via Semantic Memory

---

## 7. Synergien

| Komponente | Geteilt mit |
|---|---|
| Vision-API (OCR) | Accounting (Belegerfassung) |
| Knowledge Engine (Playbooks) | Alle Specs |
| Report-Engine | Alle Specs |
| Job-Framework | Alle Specs |
| Semantic Memory (Vertragssuche) | Big Data |
| PDF-Verarbeitung | Accounting |

---

## 8. Abgrenzung

- Kein CLM (kein Vertragserstellungs-Workflow, kein Signatur-Management)
- Kein Anwaltsersatz (keine rechtliche Beratung)
- Keine Vertragsverhandlung (keine automatische Kommunikation mit Gegenpartei)

---

## 9. Marktrecherche-Quellen

Recherche durchgefuehrt am 2026-03-14.

- Ironclad: $25k-$150k/Jahr, Gartner Leader 2025 — ironclad.com
- Spellbook: $40-179/User/Monat, MS Word Integration — spellbook.legal
- Luminance: Eigener Legal Pre-Trained Transformer, 150M+ Dokumente — luminance.com
- CUAD Dataset: 41 Klauseltypen, 510 Vertraege, CC BY 4.0 — atticusprojectai.org
- claude-legal-skill: CUAD Risk Detection fuer Claude — github.com/evolsb
- LexNLP: Legal NLP Python-Library — github.com/LexPredict
- Corporate Legal AI-Adoption: 23% (2024) → 54% (2025) — lawnext.com
- 9.2% Umsatzverlust durch Vertragsreibung — sirion.ai
- Anthropic Legal Plugin: Feb 2026 — anthropic.com
- Anwaltliche Verschwiegenheitspflicht als Treiber fuer Self-Hosted — artificiallawyer.com
