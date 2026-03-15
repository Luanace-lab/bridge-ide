# HANDOFF: Nächste Session startet mit Implementierung (Codex in BRIDGE)

Stand: 2026-02-24  
Ziel der nächsten Session: **nicht weiter analysieren**, sondern mit der Umsetzung beginnen (Patch-Iteration 1).

Wichtig:
- Diese Session hat ausreichend Fakten gesammelt.
- Die Hauptursachen sind belegt.
- Es gibt einen konkreten Patch-Plan.
- Es wurden **keine Codeänderungen** vorgenommen.

## Pflichtlektüre (Reihenfolge, nicht überspringen)

1. `STELLEXA_CLAUDE_VERGLEICH_VERIFIZIERUNG_2026-02-24.md`
2. `CODEX_CLI_TECHNIK_UND_CONTEXT_FAKTEN_2026-02-24.md`
3. `CODEX_BRIDGE_PATCH_PLAN_2026-02-24.md`
4. `SUBAGENT_READONLY_RUNS_2026-02-24.md`
5. `SUBAGENT_A_READONLY_TRANSKRIPT_2026-02-24.txt`
6. `SUBAGENT_B_READONLY_TRANSKRIPT_2026-02-24.txt`
7. `CLAUDE.md`
8. `Backend/bridge_watcher.py`
9. `Backend/output_forwarder.py`
10. `Backend/bridge_mcp.py`
11. `Backend/server.py`
12. `Backend/tests/test_watcher.py`

Hinweis:
- Die Sub-Agent-Transkripte sind keine finalen Reports, aber enthalten relevante Zusatzbelege (Logs, Diffs, Mismatchs, Statistiken).

## Was ist bereits sicher bewiesen (nicht neu analysieren)

1. `Codex kann serverseitig frei senden` (keine harte Recipient-ACL für registrierte Agents).
2. Hauptproblem ist `Integrations-/UX-Schicht`, nicht Modellfähigkeit:
   - `bridge_watcher` Prompt-Erkennung für Codex schlecht
   - `output_forwarder` manager-zentriert
   - ID-/Status-Doppelung (`codex` vs `stellexa`)
3. `project_config.html` hat einen echten Integrationsbruch:
   - Start via `:9222 /api/runtime/configure`
   - Status via `:9111 /agents`
4. Codex CLI lokal:
   - echte Persistenz (`~/.codex/sessions`, `history.jsonl`, `codex-tui.log`)
   - aktive Context-Kompaktierung (Logs + Session-Metadaten)
   - BRIDGE-MCP global konfiguriert in `~/.codex/config.toml`

## Technische Lücken (geschlossen in dieser Session)

### Lücke A: Codex-Promptbild für `bridge_watcher`-Erkennung

Live verifiziert (`tmux capture-pane -t acw_stellexa`):
- Codex-Prompt zeigt u. a.:
  - Zeile mit `› <prompt text>` (z. B. `› Find and fix a bug in @filename`)
  - darunter `? for shortcuts`
  - Context-Anzeige wie `39% context left`
- ANSI-Capture (`tmux capture-pane -e`) bestätigt dieselben Inhalte mit Escape-Sequenzen.

Implikation:
- Codex braucht ein eigenes Prompt-Profil in `bridge_watcher.py`.
- Claude-Patterns allein reichen nicht.

### Lücke B: Codex-Output-Marker für Forwarder-Profil (Startset)

In Sub-Agent-Transkripten und Pane-Ausgaben mehrfach beobachtet:
- `thinking`
- `exec`
- `codex`
- `Plan update`
- `Worked for ...`
- Prompt-/UI-Zeilen mit `? for shortcuts`, `X% context left`

Implikation:
- `output_forwarder.py` braucht parser-profile (`claude`, `codex`), nicht nur Claude-Spinner.
- Start mit konservativem Codex-Profil (throttled activity markers), dann verfeinern.

### Lücke C: „Server nicht erreichbar“ bei lokalen GETs während Analyse

Beobachtet:
- `curl`/`urllib` auf `127.0.0.1:9111` war in dieser Tool-Umgebung zeitweise inkonsistent / blockiert (`Operation not permitted`), obwohl:
  - `ss` Listener auf `9111/9112/9222` zeigte
  - tmux-/Prozess-/Log-Snapshots den laufenden Server bestätigten

Implikation:
- Für nächste Session primär auf:
  - lokale Logs
  - tmux/pids
  - serverseitige Tests
  - und gezielte End-to-End Checks im richtigen Prozesskontext stützen
- Nicht zu viel Zeit auf Tool-/Sandbox-Netzwerk-Inkonsistenzen verlieren.

## Was noch offen ist (fachliche Entscheidungen, nicht Analyse-Lücke)

1. Kanonische technische Codex-ID:
   - `codex` oder `stellexa`
2. `project_config.html` Runtime-Startpfad:
   - bei `:9222` bleiben oder auf BRIDGE-Runtime (`:9111`) vereinheitlichen
3. BRIDGE-MCP für Codex als `required` erzwingen oder nur empfohlen lassen
4. Persistenz-Policy:
   - welche Codex-Agenten dürfen persistent laufen
   - wann `ephemeral` / `disable_response_storage`

Wichtig:
- Diese Punkte blockieren nicht den Start von Iteration 1 (Discovery + Watcher-Prompt-Profil + Tests).

## Nächste Session: Implementierungsstart (ohne neue Analyse-Schleife)

### Startregel (verbindlich)

- **Keine breite Re-Analyse.**
- Direkt in `Iteration 1` aus `CODEX_BRIDGE_PATCH_PLAN_2026-02-24.md` einsteigen.

### Iteration 1 (konkret umsetzen)

1. `Backend/bridge_mcp.py`
- `bridge_list_agents()` MCP-Tool hinzufügen
- `bridge_send`-Beschreibung aktualisieren (registrierte Agent-IDs + `user/system/all`)

2. `Backend/bridge_watcher.py`
- Codex-spezifisches Prompt-Profil additiv einführen (Feature-Flag)
- Claude-Verhalten unverändert lassen

3. `Backend/tests/test_watcher.py`
- Codex-Prompt-Fälle ergänzen (inkl. `› ...`, `? for shortcuts`, Context-Anzeige)

### Definition of Done für Iteration 1

- Codex kann Agent-Liste via MCP abrufen
- `bridge_send`-Toolbeschreibung ist nicht mehr irreführend
- `is_agent_at_prompt(stellexa/codex)` trifft im Test neue Codex-Prompts
- Bestehende Claude-Prompt-Tests bleiben grün

## Implementierungsleitplanken (nicht verletzen)

1. Claude-Pfad nicht brechen
- Änderungen additiv und codex-spezifisch
- Feature-Flags wo sinnvoll

2. Keine destruktiven Server-Operationen im Live-System
- kein `cleanup`, kein breites `runtime/configure`, kein Kill von laufenden Team-Sessions ohne Freigabe

3. Kleine Patches, schnelle Verifikation
- nach jedem Teilpatch Tests / lokale Funktionstests

4. Beobachtet vs Abgeleitet sauber trennen
- besonders bei Live-Verhalten in dieser Tool-Umgebung

## Relevante Dateien für den Start (Quicklist)

- `Backend/bridge_mcp.py`
- `Backend/bridge_watcher.py`
- `Backend/tests/test_watcher.py`
- `Backend/tests/test_tmux_manager_adapter.py`
- `Backend/output_forwarder.py` (erst Iteration 2)
- `Frontend/project_config.html` (später, nach Iteration 1/2)

## Schnelle Verifikationskommandos (nächste Session)

Read-only / Tests:
- `python3 Backend/tests/test_watcher.py`
- `pytest -q Backend/tests/test_tmux_manager_adapter.py`

Promptbild prüfen:
- `tmux capture-pane -t acw_stellexa -p | tail -n 80`
- `tmux capture-pane -e -t acw_stellexa -p | tail -n 80`

Watcher-Log prüfen:
- `tail -n 120 /tmp/bridge_watcher_v2.log`

MCP-Agent-Discovery (nach Patch):
- via Codex/CLI oder Test-Harness `bridge_list_agents()`

## Anti-Pattern (unbedingt vermeiden)

- Noch eine große Analyse-Runde starten
- Weitere Sub-Agent-Schleifen ohne harten Abschluss
- Patch-Plan erneut neu schreiben statt Iteration 1 zu implementieren
- Alles gleichzeitig anfassen (Watcher + Forwarder + UI + Runtime + IDs)

## Zusammenfassung für die nächste Session (1 Satz)

Die Faktenlage ist ausreichend: **Starte mit Patch-Iteration 1 (MCP-Discovery + `bridge_send`-Docfix + Codex-Prompt-Erkennung im Watcher + Tests), Claude unangetastet, keine neue Analyse-Schleife.**

