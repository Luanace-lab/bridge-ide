# Konkreter Patch-Plan: Codex in BRIDGE (freie Kommunikation + reales UX)

Stand: 2026-02-24  
Basis:
- `STELLEXA_CLAUDE_VERGLEICH_VERIFIZIERUNG_2026-02-24.md`
- `CODEX_CLI_TECHNIK_UND_CONTEXT_FAKTEN_2026-02-24.md`
- Sub-Agent-Snapshots:
  - `SUBAGENT_A_READONLY_TRANSKRIPT_2026-02-24.txt`
  - `SUBAGENT_B_READONLY_TRANSKRIPT_2026-02-24.txt`

Wichtig:
- Dies ist ein **Patch-Plan**, keine Umsetzung.
- Ziel ist ein sicherer Umbau ohne Regression im Claude/Manager-Pfad.

## Zielzustand (klar definiert)

1. Codex hat **eine kanonische Bridge-Identitaet** (keine Doppelrealitaet `codex` vs `stellexa` ohne Alias-Regel).
2. Codex kann **frei** mit `manager`, `lucy`, `nova`, `viktor`, `user` kommunizieren (via Bridge-MCP).
3. `user -> codex` fuehlt sich **chatartig/real** an:
   - schnelle ACKs / sichtbare Aktivitaet
   - keine haeufigen Zustellverzoegerungen durch Prompt-Erkennung
4. Codex hat eine **saubere Context-Strategie** (Workspace, Persistenz, Kompaktierung, Regeln/Skills).
5. Claude/Manager bleibt stabil und unveraendert im Verhalten (oder verbessert ohne Regression).

## Nicht-Ziele (fuer diesen Patch-Plan)

- Kein kompletter Architekturumbau der gesamten Plattform in einem Schritt
- Kein Ersatz der bestehenden BRIDGE-Multi-Agent-Logik durch Codex-eigene Multi-Agent-Features
- Kein Overengineering mit neuer komplexer Workflow-Engine nur fuer Kommunikation

## Hauptbefunde, auf denen der Plan basiert (kompakt)

1. `bridge_watcher.py` ist prompt-seitig Claude-zentriert; `stellexa` wird haeufig als `nicht am Prompt` erkannt.
2. `output_forwarder.py` ist Manager-zentriert (Session, Sender, Parser, PID-Verhalten) und nicht parallel Codex-faehig.
3. Freie Sends sind serverseitig bereits moeglich; es fehlt primär Discovery/UX/Integrationsqualitaet.
4. Es gibt eine reale Identitaets-/Status-Asymmetrie (`codex` Runtime-Slot vs `stellexa` aktiver Agent).
5. Codex-Context wird lokal stark/persistent verwaltet (Sessions/History/Logs, Compaction aktiv) und braucht BRIDGE-seitig klare Regeln.

---

## Patch-Plan (Phasen)

## Phase 0 — Guardrails + Messbasis (vor funktionalen Patches)

Ziel:
- Vorher/Nachher messbar machen
- sichere Rueckrollbarkeit vorbereiten

### P0.1 Baseline-Metriken erfassen (read-only helper / script)
Dateien:
- neu: `Backend/tools/bridge_diagnostics_codex.py` (oder `Backend/tools/bridge_diag.py`)

Inhalt:
- Auswertung `watcher`-Log:
  - `direct_prompt`, `not_prompt`, `force` pro Zielagent
- Auswertung `bridge.jsonl`:
  - Status-Messages nach Sender (`output_forwarder`)
  - Message-Routen `user<->codex`, `manager<->codex`, `user<->stellexa`
- Optional:
  - `is_agent_at_prompt(agent)` Snapshots

Warum zuerst:
- Damit jede Aenderung am Watcher/Forwarder objektiv bewertbar ist.

Abnahme:
- Script liefert reproduzierbare Kennzahlen ohne Schreibzugriffe auf BRIDGE-Datenpfade.

Risiko:
- sehr niedrig

Rollback:
- Datei entfernen / ignorieren

### P0.2 Feature-Flags/Schalter fuer codex-spezifischen Rollout vorbereiten
Dateien:
- `Backend/bridge_watcher.py`
- `Backend/output_forwarder.py`

Schalter (ENV):
- `WATCHER_ENABLE_CODEX_PROMPT_PROFILES=0/1`
- `FORWARDER_PROFILE=claude|codex`
- `FORWARDER_SENDER=<agent_id>`

Warum:
- Codex-Pfade aktivieren, ohne Claude-Pfad zu beruehren.

Abnahme:
- Standardverhalten unveraendert bei nicht gesetzten ENV-Variablen.

Risiko:
- niedrig

Rollback:
- Flags aus, altes Verhalten bleibt

---

## Phase 1 — Identitaet und freie Adressierung (kanonische Kommunikation)

Ziel:
- eindeutige Agent-ID-Logik
- Codex kann andere Agents frei adressieren, ohne zu raten

### P1.1 Kanonische Codex-Identitaet festlegen (mit Alias-Regel)
Entscheidung (fachlich noetig, dann Patch):
- Option A (empfohlen): `codex` = kanonische technische ID, `Stellexa` = Anzeigename/Rolle
- Option B: `stellexa` = kanonische technische ID, Runtime/Frontend entsprechend angleichen

Patch-Orte (je nach Entscheidung):
- `Backend/server.py` (Runtime-Slot IDs / Default-Runtime-Layout falls betroffen)
- `Frontend/chat.html` (Default-Targets / Labeling)
- `Frontend/control_center.html`
- `Frontend/project_config.html`
- ggf. `Backend/tmux_manager.py` (Session-Naming nur falls ID-Aenderung)

Empfohlene technische Loesung:
- Alias-Mapping serverseitig einfuehren (optional):
  - Anzeige-ID vs kanonische ID
  - Routing immer ueber kanonische ID

Abnahme:
- Es gibt in `/agents`, `/health`, `bridge.jsonl` und UI nur noch **ein** konsistentes Codex-Zielbild (oder explizite Alias-Darstellung).

Risiko:
- mittel (UI/Runtime/Logs muessen konsistent bleiben)

Rollback:
- Alias-Feature deaktivieren / vorherige IDs wiederverwenden

### P1.2 Agent-Discovery im Bridge-MCP ergaenzen (frei kommunizieren ohne Raten)
Dateien:
- `Backend/bridge_mcp.py`
- optional `Backend/server.py` (nur falls neuer Endpoint noetig)

Patch:
- Neues MCP-Tool `bridge_list_agents()` (oder `bridge_agents()`)
  - nutzt `GET /agents`
  - liefert `agent_id`, `status`, `role`, `last_heartbeat`
- Optional Filter:
  - `only_active`
  - `include_user`

Warum:
- Codex soll selbststaendig und korrekt Ziele waehlen koennen.

Abnahme:
- Codex kann vor Send eine aktuelle Agentenliste abrufen.
- Kein Raten auf Basis veralteter Namen.

Risiko:
- niedrig

Rollback:
- Tool entfernen; vorhandene Tools bleiben intakt

### P1.3 `bridge_send`-Toolbeschreibung korrigieren (Docs/UX-Patch)
Datei:
- `Backend/bridge_mcp.py`

Patch:
- Beschreibung von `bridge_send` aktualisieren
- veraltete Recipient-Liste (`claude_a`, `claude_b`) ersetzen durch:
  - "any registered agent ID plus `user/system/all`"
- Hinweis auf `bridge_list_agents()` aufnehmen (wenn P1.2 umgesetzt)

Abnahme:
- Toolbeschreibung entspricht dem echten Serververhalten.

Risiko:
- sehr niedrig

Rollback:
- Docstring revert

---

## Phase 2 — Zustellung stabilisieren: Codex-Prompt-Erkennung im Watcher

Ziel:
- `not_prompt`/`force-injiziert` fuer Codex drastisch reduzieren
- reale Reaktionsqualitaet verbessern

### P2.1 Prompt-Erkennung profilbasiert machen (Claude/Codex getrennt)
Datei:
- `Backend/bridge_watcher.py`

Patch:
- `is_agent_at_prompt(agent_id)` refactoren:
  - gemeinsamer Capture-Pfad
  - engine-/agent-profile fuer Prompt-Erkennung
- Neue Struktur (Beispiel):
  - `_detect_prompt_claude(lines)`
  - `_detect_prompt_codex(lines)`
  - `_detect_prompt_generic(lines)`
- Mapping:
  - Session-/Agent-spezifisch (`acw_stellexa`, spaeter `acw_codex`)
  - fallback generisch

Wichtig:
- Claude-Patterns unveraendert beibehalten (Canary-Schutz)
- Codex-Patterns zuerst additiv, nicht ersetzend

Abnahme:
- `is_agent_at_prompt(stellexa/codex)` liefert in Live-Stichproben haeufig `True`
- Watcher-Log:
  - weniger `not_prompt`
  - deutlich weniger `force-injiziert`

Risiko:
- mittel (falsche Prompt-Erkennung kann Fehlinjektionen erzeugen)

Rollback:
- codex-Profil deaktivieren (Feature-Flag)
- Fallback auf altes Verhalten

### P2.2 Watcher-Tests erweitern (Codex-Faelle)
Datei:
- `Backend/tests/test_watcher.py`

Patch:
- Testfaelle fuer Codex-Prompt-Renderings / TUI-Ausgaben
- Negative Tests gegen false positives
- Tests fuer `smart_inject`-Retries bleiben erhalten

Abnahme:
- Testdatei deckt Claude + Codex Prompt-Erkennung ab

Risiko:
- niedrig

Rollback:
- Testfaelle entfernen

### P2.3 Watcher-Observability erweitern (optional, empfohlen)
Datei:
- `Backend/bridge_watcher.py`

Patch:
- Statistiken im Log vereinheitlichen (optional)
- z. B. periodischer Snapshot pro Agent:
  - `direct_prompt`, `force`, `not_prompt`

Abnahme:
- Metriken ohne manuelles Parsen leichter auswertbar

Risiko:
- niedrig

Rollback:
- Logging reduzieren

---

## Phase 3 — Telemetrie/„Lebendigkeit“: Forwarder v2 (parallel Claude + Codex)

Ziel:
- Codex sendet sichtbare Status-/Typing-Signale wie Manager
- Claude bleibt unangetastet nutzbar

### P3.1 `output_forwarder.py` enthaerten (Session/Sender nicht hardcoded)
Datei:
- `Backend/output_forwarder.py`

Patch:
- `TMUX_SESSION` bleibt ENV-gesteuert
- `FORWARDER_SENDER` neu (statt hardcoded `"manager"`)
- `FORWARDER_RECIPIENT` optional (Default `user`)
- `FORWARDER_PROFILE` (`claude` / `codex`) fuer Parser/Spinner

Konkrete Fixpunkte:
- `TMUX_SESSION` default aktuell `acw_manager` (`Backend/output_forwarder.py:32`)
- `from: "manager"` hardcoded (`Backend/output_forwarder.py:177`)

Abnahme:
- Ein Forwarder kann identisch fuer `manager` oder `codex/stellexa` gestartet werden.

Risiko:
- mittel (falscher Sender/Recipient verursacht UI-Rauschen)

Rollback:
- ENV nicht setzen -> altes Manager-Verhalten

### P3.2 Multi-Instance-Betrieb ermoeglichen (kein gegenseitiges Killen)
Datei:
- `Backend/output_forwarder.py`

Patch:
- `_kill_existing_forwarders()` verfeinern oder ersetzen
- PID/FIFO-Dateien session-spezifisch machen:
  - z. B. `output_forwarder_<session>.pid`
  - `bridge_forwarder_<session>.fifo` ist bereits sessionbezogen; PID-Datei aktuell nicht

Warum:
- Aktuell killt ein neu gestarteter Forwarder andere Forwarder-Prozesse.

Abnahme:
- `manager`- und `codex`-Forwarder koennen parallel laufen.

Risiko:
- mittel (Doppel-Forwarding/dupes, falls pipe-pane nicht sauber verwaltet)

Rollback:
- nur Manager-Forwarder weiter betreiben

### P3.3 Parser-Profil fuer Codex (Typing-Erkennung) implementieren
Datei:
- `Backend/output_forwarder.py`

Patch:
- Claude-Spinner-Parser beibehalten
- Codex-spezifische Aktivitaets-/Thinking-Marker als separates Profil
- Fallback minimal:
  - nur generische Status-Impulse bei Output-Aktivitaet (throttled)

Abnahme:
- Codex erzeugt Statusmeldungen sichtbar in Bridge-Historie
- Keine Prosa-Duplikation

Risiko:
- mittel (Spam oder Fehlklassifikation)

Rollback:
- Codex-Profil deaktivieren; nur Claude-Forwarder weiter

### P3.4 Forwarder-Tests / Simulation (neu)
Dateien:
- neu: `Backend/tests/test_output_forwarder.py` (empfohlen)

Patch:
- Testen:
  - Sender/Recipient-Konfiguration
  - Claude-/Codex-Profil-Parsing
  - no-spam Cooldown/Throttle

Abnahme:
- Grundfunktionen automatisiert pruefbar

Risiko:
- niedrig

Rollback:
- Testdatei entfernen

---

## Phase 4 — Runtime/UI-Pfade konsistent machen (BRIDGE operativ sauber)

Ziel:
- weniger Status-/UX-Widersprueche im Frontend
- klare Start-/Statuspfade fuer Teams

### P4.1 `project_config.html`: Startpfad vs Statuspfad angleichen
Datei:
- `Frontend/project_config.html`

Ist-Zustand (belegt):
- Start Team via `:9222 /api/runtime/configure`
- Status via `:9111 /agents`

Patch-Optionen:
- Option A (empfohlen kurzfristig): UI macht den Split explizit sichtbar (welcher Server steuert was)
- Option B (sauberer): Team-Start auf denselben Runtime-Pfad verlegen wie Live-Status (BRIDGE-Server)
- Option C: API-Server und BRIDGE-Server enger koppeln (groesserer Umbau)

Abnahme:
- Kein "Team gestartet" bei gleichzeitig disconnected Live-Agents ohne Erklaerung.

Risiko:
- mittel bis hoch (abhängig von gewaehlter Option)

Rollback:
- UI-Text/Statuslogik revert

### P4.2 Legacy-UI-Root (`ui.html`) bereinigen
Datei:
- `Backend/server.py`

Ist-Zustand (belegt):
- Root verweist auf `Backend/ui.html` (legacy), aktuelle UIs liegen in `Frontend/*.html`

Patch:
- `/` und `/ui` auf aktuelles Frontend routen (z. B. `Frontend/chat.html`)
- weitere aktuelle Seiten explizit serven oder statisches Frontend sauber mounten

Abnahme:
- `http://127.0.0.1:9111/` liefert aktuelles UI statt Legacy-Deadpath

Risiko:
- niedrig bis mittel (Routing/relative Pfade)

Rollback:
- alter Root-Handler wiederherstellen

### P4.3 Startscript-Konsistenz (`server.py` + `api_server.py`)
Datei:
- `Backend/start_platform.sh`

Ist-Zustand (belegt):
- `server.py` startet, `api_server.py` nicht zwingend
- `project_config.html` braucht `:9222`

Patch:
- `api_server.py` optional/konfigurierbar mitstarten
- klare Konsolenhinweise (welche UI braucht welchen Port)
- stale Hinweise bereinigen (z. B. `operator_console.py`)

Abnahme:
- Startpfad entspricht realen UI-Abhaengigkeiten

Risiko:
- niedrig

Rollback:
- Script revert

---

## Phase 5 — Codex-Context-Strategie fuer BRIDGE (wichtig fuer langfristige Stabilitaet)

Ziel:
- reproduzierbares Codex-Verhalten
- kontrollierte Persistenz
- weniger Kontextdrift

### P5.1 BRIDGE-Codex-Profile definieren (Config/Runtime)
Dateien:
- `Backend/tmux_manager.py` (generierte `.codex/config.toml`)
- optional Projektdatei fuer Profile/Defaults (neu)

Patch:
- role-/agent-spezifische Codex-Profile definieren (z. B. manager, architect, implementer, reviewer)
- pro Profil:
  - model
  - reasoning effort
  - sandbox/approval
  - search
  - MCP `bridge` required (wenn gewollt)

Abnahme:
- tmux-gestartete Codex-Agents starten mit konsistentem Verhalten pro Rolle

Risiko:
- mittel (falsche Defaults koennen UX oder Rechte beeinflussen)

Rollback:
- auf globales `~/.codex/config.toml` / Minimal-Config zurueckfallen

### P5.2 Context-Budgeting explizit machen (Rules/Docs/Hook)
Dateien:
- `Backend/tmux_manager.py` (Agent-Instruktionen)
- `Backend/post_tool_hook.sh`
- ggf. `Agents/...` bzw. BRIDGE-Regeldokumente

Patch:
- explizite Context-Regeln in Agent-Instruktionen:
  - `/compact` bei Schwellenwerten
  - Zwischenberichte / CONTEXT-Dokumente
  - offene Zusagen melden
- Hook-Meldungen engine-neutral bzw. codex-kompatibel pruefen

Abnahme:
- konsistente Context-Hygiene auch fuer Codex-Agents

Risiko:
- niedrig bis mittel (zu aggressive Hinweise koennen nerven)

Rollback:
- Hook-/Instruktionsanpassungen revert

### P5.3 Persistenz-Policy festlegen (interaktiv vs batch)
Dokument/Code:
- neue Policy-Doku (empfohlen in `/Planung` oder Root)
- optional BRIDGE-Launcher-Parameter fuer Codex jobs

Patch-Inhalt (organisatorisch + technisch):
- Interaktive Langlaeufer: Persistenz erlaubt (Debugging/Resume)
- Sensible Einmaljobs:
  - `codex exec --ephemeral`
  - optional `disable_response_storage`
- klare Vorgaben, welche Agenten in persistenten Homes laufen duerfen

Abnahme:
- dokumentierte und technisch abbildbare Policy vorhanden

Risiko:
- niedrig

Rollback:
- Policy-Doku revert

---

## Phase 6 — Validierung / Abnahme / Rollout

Ziel:
- Codex-Verbesserung messbar, Claude unveraendert stabil

### P6.1 Testmatrix (manuell + automatisiert)

Manuell (Live):
1. `user -> codex` (ACK / Antwort / sichtbare Typing-Signale)
2. `manager -> codex`
3. `codex -> manager`
4. `codex -> lucy/nova/viktor`
5. `broadcast -> codex`
6. Parallelbetrieb `manager` + `codex` Forwarder

Automatisiert (ergänzen):
- `Backend/tests/test_watcher.py` (Codex prompt detection)
- `Backend/tests/test_tmux_manager_adapter.py` (Codex runtime config/start path)
- neuer `test_output_forwarder.py`
- `bridge_mcp` Tests fuer `bridge_list_agents` (falls P1.2 umgesetzt)

### P6.2 Abnahmekriterien (hart)

1. Watcher-Log:
- `force-injiziert` fuer Codex signifikant reduziert
- `direct_prompt` fuer Codex nachweisbar haeufiger

2. Historie:
- Codex-Statusmeldungen (Forwarder) sichtbar wie beim Manager (qualitativ vergleichbar, kein Spam)

3. Kommunikation:
- `codex` kann `manager`, `lucy`, `nova`, `viktor`, `user` gezielt adressieren
- keine Recipient-Warnungen im Normalfall (bei korrekter ID)

4. Identitaet:
- keine verwirrende Doppelrealitaet in `/agents`, `/health`, UI, Logs (oder Alias explizit/sauber)

5. Regression:
- `manager`/Claude Verhalten bleibt stabil

### P6.3 Rollback-Plan (pro Phase)

- P1 (Identitaet/Discovery):
  - Alias/ID-Änderungen per Config/Mapping deaktivieren
- P2 (Watcher Prompt):
  - codex-Profile via Feature-Flag aus
- P3 (Forwarder v2):
  - nur Manager-Forwarder starten; Codex-Forwarder aus
- P4 (UI/Runtime):
  - UI-Routing/Startpfad auf vorherige Version zurueck
- P5 (Context):
  - Profile/Hook-Anpassungen revert; Minimal-Config nutzen

---

## Reihenfolgeempfehlung (minimaler Hebel, geringstes Risiko)

1. **P0** Messbasis + Feature-Flags
2. **P1.2 + P1.3** MCP-Discovery + `bridge_send`-Beschreibung (niedriges Risiko, hoher Kommunikationsnutzen)
3. **P2** Codex-Prompt-Erkennung im Watcher (groesster UX-Hebel)
4. **P3.1/P3.2/P3.3** Forwarder v2 fuer Codex-Telemetrie
5. **P1.1** Identitaetskonsolidierung (`codex` vs `stellexa`) mit klarer Alias-Regel
6. **P4** UI/Runtime-Pfadkonsistenz (`9111`/`9222`, Legacy-Root)
7. **P5** Context-Strategie/Profile/Persistenz-Policy
8. **P6** Vollabnahme und Rollout

Warum diese Reihenfolge:
- Erst Kommunikationsfreiheit + Zustellung + Sichtbarkeit verbessern
- Dann Identitaet/UI/Runtime aufraeumen
- Context/Persistenz danach strukturiert und ohne Zeitdruck ausrollen

---

## Konkrete erste Patches (Startpaket, 1-2 Iterationen)

### Iteration 1 (sehr hoher Hebel, relativ sicher)
- `Backend/bridge_mcp.py`
  - `bridge_list_agents()` hinzufuegen
  - `bridge_send`-Beschreibung korrigieren
- `Backend/bridge_watcher.py`
  - codex-Profil-Prompt-Erkennung additiv einfuehren (Feature-Flag)
- `Backend/tests/test_watcher.py`
  - Codex Prompt-Faelle

### Iteration 2 (UX-Lebendigkeit)
- `Backend/output_forwarder.py`
  - Sender/session/profile parameterisieren
  - keine globalen Forwarder-Kills
  - Codex-Profil parser
- optional Tests

### Iteration 3 (Konsolidierung)
- Identitaets-/Alias-Regel (`codex` vs `stellexa`)
- `project_config.html` Runtime/Status-Konsistenz
- `server.py` Root-UI-Routing auf aktuelles Frontend

---

## Offene fachliche Entscheidungen vor Umsetzung

1. Welche technische ID soll kanonisch sein: `codex` oder `stellexa`?
2. Soll BRIDGE-MCP fuer Codex als `required` gelten (harte Kommunikationspflicht)?
3. Soll `project_config.html` weiterhin bewusst den API-Server (`:9222`) nutzen oder auf BRIDGE-Server-Runtime vereinheitlicht werden?
4. Welche Persistenz-Policy gilt fuer produktive Codex-Agenten (voll persistent vs gemischt vs batch-ephemeral)?

