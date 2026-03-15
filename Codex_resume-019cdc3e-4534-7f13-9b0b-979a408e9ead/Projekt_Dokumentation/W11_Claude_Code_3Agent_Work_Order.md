# W11_Claude_Code_3Agent_Work_Order

## Zweck

Arbeitsauftrag fuer Claude Code, um mit drei parallel laufenden Claude-Agents eine saubere Analyse- und Planungsphase fuer den Credential-Cleanup-/Buddy-Umbau durchzufuehren.

Dieser Auftrag ist bewusst **kein Implementierungsauftrag im ersten Schritt**.
Er ist ein Analyse-, Planungs- und Dokumentationsauftrag mit anschliessender Freigabe durch den Projektleiter.

## Rahmen

- Repository: `/home/leo/Desktop/CC/BRIDGE`
- Arbeitsprinzipien:
  - evidenzbasiert
  - repository-first
  - keine Behauptung ohne Nachweis
  - keine Implementierung vor sauberer Analyse
  - keine Scope-Flucht
- Kanonische SoT-Doku im Repo:
  - `/home/leo/Desktop/CC/BRIDGE/Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation`

## Pflichtlektüre fuer jeden der 3 Claude-Agents

Jeder Agent muss **vor jeder Codeanalyse** lesen:

1. `/home/leo/Desktop/CC/BRIDGE/AGENTS.md`
2. den gesamten kanonischen Doku-Satz unter:
   - `/home/leo/Desktop/CC/BRIDGE/Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation`
3. insbesondere:
   - `W10_Claude_Code_Subscriptions_Buddy_Spec.md`
   - `2026-03-13_Claude_Anthropic_Credential_Audit.md`
   - `02_Gap_Map.md`

Erst danach darf Code geprueft werden.

## Dokumentationspflicht in /Viktor

Jeder Claude-Agent dokumentiert seine Ergebnisse **zwingend** in seinem Ordner unter `/Viktor`.

Pflichtinhalt je Agent:
- gelesene Artefakte
- gepruefter Ist-Zustand
- belegte Evidenz
- offene Luecken
- Risiken
- konkrete Empfehlungen fuer den Plan

Jeder Agent schreibt nachvollziehbar und so, dass der Projektleiter danach Doku und Code gegenpruefen kann.

## Zielauftrag fuer Claude

Der Scope ist exakt:

1. `tmux_manager.py` auf Claude-Credential-/Onboarding-/Symlink-/Patch-Pfade analysieren
2. `server.py` auf verbleibende Account-/Subscription-/Credential-Projektion analysieren
3. Buddy-Setup-/Home-/Frontdoor-Pfad gegen das Zielbild pruefen
4. daraus einen **konkreten Migrationsplan in kleinen reversiblen Schritten** erstellen

Nicht Teil dieses ersten Claude-Auftrags:
- sofortige Implementierung
- Refactoring ausserhalb des Credential-/Buddy-Slices
- Umbauten an Task-/Workflow-/Messaging-Kern

## Aufteilung auf 3 Claude-Agents

### Agent 1 — Runtime/Credential-Pfade

Prueft:
- `Backend/tmux_manager.py`
- relevante Start-/Restart-Aufrufer in `Backend/server.py`

Liefert:
- exakte Liste aller verbleibenden Credential-/Onboarding-/Patch-/Symlink-Pfade
- kleinster sauberer Entfernungsplan
- Validierungsstrategie fuer jeden Schritt

### Agent 2 — Server-/API-/Datenprojektion

Prueft:
- `Backend/server.py`
- `Backend/team.json`
- `GET /subscriptions`, `PUT /agents/{id}/subscription`, verwandte Projektionen

Liefert:
- exakte Trennung zwischen offizieller Profil-Zuordnung und verbotener Account-Wahrheit
- Vorschlag, wie `subscription_id`/`config_dir` semantisch umzubauen sind
- Risikoanalyse fuer UI-/API-Callsites

### Agent 3 — Buddy-/Frontdoor-/Home-Doku

Prueft:
- `Frontend/buddy_landing.html`
- Buddy-Home unter `/home/leo/Desktop/CC/Buddy`
- generierte Dateien wie `BRIDGE_OPERATOR_GUIDE.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `QWEN.md`

Liefert:
- ob Buddy schon hinreichend als Concierge/Superagent dokumentiert ist
- welche konkreten Luecken im Buddy-Home noch bestehen
- wie Buddy deterministisch Teams/Agents/Setups ueber bestehende Bridge-Pfade ausloesen soll

## Erwartetes Ergebnis nach Analysephase

Claude soll **einen gemeinsamen Plan** liefern mit:

- priorisierten Slices
- minimaler Reihenfolge
- betroffenen Dateien
- Risiken pro Schritt
- Validierung pro Schritt
- Rueckbau-/Rollback-Idee pro Schritt

## Gate-Regel

Claude implementiert **nicht sofort**.

Ablauf:
1. Drei Agents analysieren und dokumentieren in `/Viktor`
2. Daraus entsteht ein gemeinsamer Plan
3. Der Projektleiter prueft:
   - den Plan
   - die Dokumentation
   - die referenzierten Codepfade
4. Erst danach erfolgt Freigabe oder Korrektur

## Bewertungsstandard fuer den Plan

Der Plan ist nur akzeptabel, wenn:

- er sich auf reale Artefakte stuetzt
- er den Scope haelt
- er keine neuen Nebenarchitekturen baut
- er den Wrapper-Charakter der Bridge staerkt
- er Buddy nicht einschraenkt
- er die Reproduzierbarkeit fuer Fremdnutzer verbessert
- er keine versteckte Credential-Logik neu einfuehrt

## Kurzfassung fuer Claude

Kurzauftrag:

> Aktiviere 3 Claude-Agents zur Analyse. Jeder liest zuerst `AGENTS.md` und die vollstaendige Repo-SoT-Doku. Danach analysiert jeder seinen Slice, dokumentiert zwingend in `/Viktor`, und gemeinsam erstellt ihr einen minimalen, sauberen Migrationsplan fuer den Credential-Cleanup-/Buddy-Umbau. Keine Implementierung vor Planfreigabe.
