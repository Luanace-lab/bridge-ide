---
name: bridge-review-code
description: Structured code review workflow for Bridge IDE. Use when reviewing code changes, PRs, or agent-submitted work. Checks architecture, invariants, security, and quality.
allowed-tools: Read, Grep, Glob, Bash
---

# Bridge Code Review

Strukturierter Code-Review nach Bridge-Standards.

## Review-Checkliste

### 1. Scope identifizieren
Welche Dateien wurden geaendert? Gehoeren sie zum Zustaendigkeitsbereich des Autors?
```bash
# Wenn git-basiert:
git diff --name-only HEAD~1
# Oder spezifische Dateien lesen
```

### 2. Architektur-Pruefung
- [ ] **Zustaendigkeitsgrenzen**: Frontend-Code nur in Frontend/, Backend nur in Backend/
- [ ] **Keine Cross-Boundary Changes**: Agent hat nur seinen Bereich angefasst
- [ ] **Schichten-Integritaet**: Keine Schicht-Verletzungen (UI → API → Data)
- [ ] **Abhaengigkeiten**: Keine zirkulaeren Imports, keine unnoetigen Kopplungen

### 3. Invarianten-Check
- [ ] **Atomare Writes**: Tempfile + os.replace (nicht direktes Schreiben)
- [ ] **Lock-Ordnung**: TASK_LOCK → ESCALATION_LOCK, TEAM_CONFIG_LOCK fuer Mutations
- [ ] **Error-Handling**: Keine silent catches, keine bare `except:`
- [ ] **Resource Cleanup**: Dateien/Sockets/Locks werden geschlossen
- [ ] **Thread-Safety**: Shared State nur unter Lock

### 4. Security-Check
- [ ] **Keine Secrets in Code**: API-Keys, Tokens, Passwoerter
- [ ] **Input-Validation**: User-Input wird validiert/escaped
- [ ] **Path Traversal**: Keine unkontrollierten Pfad-Konstruktionen
- [ ] **Command Injection**: Kein `os.system()` / `subprocess.call(shell=True)` mit User-Input
- [ ] **XSS**: HTML-Output escaped

### 5. Code-Qualitaet
- [ ] **Keine Over-Engineering**: Einfachste Loesung die funktioniert
- [ ] **Keine toten Code-Pfade**: Unreachable Code, unused Imports
- [ ] **Keine Duplikation**: Copy-Paste Code → Funktion extrahieren
- [ ] **Naming**: Variablen/Funktionen sind selbsterklaerend
- [ ] **Error Messages**: Hilfreich, nicht generisch

### 6. Evidenz-Pruefung (bei Task-Ergebnissen)
- [ ] **Tests**: Wurden Tests geschrieben/ausgefuehrt?
- [ ] **evidence_type**: Korrekt gewaehlt (test > log > screenshot > code > manual)
- [ ] **evidence_ref**: Konkreter Beleg (nicht "tested and works")
- [ ] **Verifikation reproduzierbar**: Kann ein anderer Agent den Beweis nachvollziehen?

## Review-Ergebnis

### APPROVED
Code ist korrekt, sicher, wartbar. Keine Bedenken.

### APPROVED WITH COMMENTS
Kleinigkeiten (Style, Naming), aber funktional korrekt. Kein Blocker.

### CHANGES REQUESTED
Probleme gefunden. Konkrete Aenderungen benennen:
```
1. [Datei:Zeile] Problem — Vorgeschlagene Loesung
2. [Datei:Zeile] Problem — Vorgeschlagene Loesung
```

### REJECTED
Architektur-Verstoss, Security-Issue, oder fundamentaler Design-Fehler.
Begruendung mit Beleg. Zurueck an Autor.

## Review melden
```
bridge_send(to="<autor>", content="[CODE REVIEW] <datei>: <APPROVED|CHANGES_REQUESTED|REJECTED>\n<Details>")
```
