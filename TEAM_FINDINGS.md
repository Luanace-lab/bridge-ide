# TEAM FINDINGS — Gesamtprojekt

**Erstellt:** 2026-02-28
**Owner:** Viktor (Systemarchitekt) — Leo-Auftrag
**Zweck:** Zentrales Dokument fuer alle Team-Findings waehrend der Prozessausfuehrung.
**Zugriff:** Alle Agents (Viktor, Codex, Kiro, Sora, Ren, Frontend-Agent, Nova, Ordo)

---

## Struktur

Jeder Agent traegt seine Findings unter seinem Namen ein. Format:

```
### [Agent-Name] — [Task X]
- **Datum/Uhrzeit:** YYYY-MM-DD HH:MM
- **Finding:** Kurzbeschreibung
- **Status:** Offen / In Arbeit / Erledigt
- **Notizen:** Zusaetzliche Informationen
```

---

## Findings

### Sora (qwen2) — TASK C ("Neues Projekt anlegen" Button)
- **Datum/Uhrzeit:** 2026-02-28 12:54
- **Finding:** UI-Implementierung in control_center.html abgeschlossen vor STOPP-Befehl
- **Status:** Erledigt (Frontend-Agent hat uebernommen, Review OK + ESC-Fix)
- **Notizen:**
  - Button "+ Neues Projekt" im Board-Header eingefuegt
  - Modal-Dialog mit Formular erstellt
  - generateProjectSlug() implementiert (lowercase, Leerzeichen → Bindestrich)
  - POST /board/projects Handler geschrieben
  - Backup: control_center.html.bak
  - Playwright-Test NICHT ausgefuehrt
  - **Korrektur:** UI-Tasks gehoeren zum Frontend-Agent, nicht zu Qwens

### Sora (qwen2) — reply_to Feld (/send Endpoint)
- **Datum/Uhrzeit:** 2026-02-28 13:10
- **Finding:** reply_to Feld in server.py implementiert
- **Status:** DONE
- **Notizen:**
  - `reply_to = data.get("reply_to")` in /send Endpoint hinzugefuegt (Zeile ~3501)
  - `reply_to` Parameter zu `append_message()` Funktion hinzugefuegt (Zeile ~587)
  - `msg["reply_to"] = reply_to` wird nur gesetzt wenn nicht None (Zeile ~605)
  - Backup: server.py.bak
  - Server-Restart erforderlich fuer Live-Schaltung

---

### Codex — TASK A (Context-Monitor Haertung)
- **Datum/Uhrzeit:** 2026-02-28 12:58
- **Finding:** bridge_watcher.py Implementierung abgeschlossen
- **Status:** Code DONE, CONTEXT_BRIDGE-Anweisung in allen Agent-CLAUDE.md vorhanden AUSSER Codex-AGENTS.md (in Arbeit)
- **Notizen:**
  - `_write_context_bridge()` Funktion implementiert
  - Phase 0 in `_force_context_stop()` eingefuegt
  - agents.conf Cache mit Lazy-Loading
  - HTTP-API Calls mit Fehlerbehandlung
  - CLAUDE.md-Ergaenzungen: 7/8 Agents haben CONTEXT_BRIDGE-Anweisung. Codex AGENTS.md fehlt noch.

---

### Codex — Watcher Start-Validierung (agents.conf WARN)
- **Datum/Uhrzeit:** 2026-02-28 13:54
- **Finding:** Start-Validierung fuer tmux-Session vs. agents.conf implementiert.
- **Status:** DONE (Review APPROVED)
- **Notizen:**
  - Neue Startup-Pruefung in `bridge_watcher.py` nach `_load_agent_meta_cache()`
  - Loggt WARN fuer Agent-Sessions ohne agents.conf Entry:
    `[watcher] WARN keine agents.conf fuer Session: {session_name}`
  - Nur Logging, kein Abbruch
  - Viktor Review: APPROVED

---

### Codex — Sprint 2 Task 1 (Multi-Stage Context-Monitor)
- **Datum/Uhrzeit:** 2026-02-28 13:58-13:59
- **Finding:** Context-Monitor auf 4 Stufen umgebaut, Polling auf 15s reduziert.
- **Status:** DONE
- **Notizen:**
  - Neue Stufen in `_context_monitor()`: 80% WARNING, 85% BRIDGE, 90% INJECT, 95% STOP
  - Neue Hilfsfunktion `_set_activity()` fuer Stage-Activity Updates via `/activity`
  - `_force_context_stop()` auf Phasen 2-4 reduziert (Phase 0+1 jetzt in Stufen 2+3)
  - Reset-Logik bei `pct_used < 70` fuer alle Stage-Tracker + `already_stopped`
  - Compile-Check bestanden: `python3 -m py_compile bridge_watcher.py`

---

### Codex — Sprint 2 Task 2 (Activity-Text im Board API)
- **Datum/Uhrzeit:** 2026-02-28 14:00
- **Finding:** `current_activity` im Board-Backend durchgereicht.
- **Status:** DONE (Code), Aktivierung nach Server-Restart durch Ordo/Viktor
- **Notizen:**
  - `board_api.py`: `_agent_info()` um `current_activity` erweitert
  - `board_api.py`: `agent_activities` als optionaler Parameter in `get_all_projects/get_project/get_all_agents/get_agent_projects`
  - `server.py`: `AGENT_ACTIVITIES` an alle Board-GET-Aufrufe durchgereicht
  - Compile-Check bestanden: `python3 -m py_compile board_api.py server.py`
  - Keine Server-Prozess-Manipulation durch Codex (Regel eingehalten)

---

### Codex — Qwen-Heartbeat im bestehenden Health-System
- **Datum/Uhrzeit:** 2026-02-28 16:03
- **Finding:** Non-MCP Agents mit lebender Session halten Heartbeat im bestehenden Status-Loop.
- **Status:** DONE (reaktiviert per Leo-Befehl)
- **Notizen:**
  - Kurz gestoppt/revertiert auf Viktor-Korrektur
  - Danach expliziter Leo-Befehl: Fix wieder einsetzen
  - Heartbeat-Hunk ist jetzt wieder aktiv in `server.py` (vor `update_agent_status`)
  - Compile-Check bestanden: `python3 -m py_compile server.py`

---

### Codex — Ordo-Crash Mitigation (Watcher Flood-Schutz)
- **Datum/Uhrzeit:** 2026-02-28 16:15
- **Finding:** WARN/RECOVERY-Flood gedrosselt + System-Injection bei hohem Context geblockt.
- **Status:** DONE (Code)
- **Notizen:**
  - `bridge_watcher.py`: 5min Cooldown pro Agent fuer `system` WARN/RECOVERY an Ordo
  - `bridge_watcher.py`: ab Context >=85% keine System-Injections (ausser context_stop)
  - Event-Logs: `system_notice_throttled`, `system_blocked_high_context`
  - Compile-Check bestanden: `python3 -m py_compile bridge_watcher.py`

---

### Codex — Agent-Start per Klick (Backend Endpoint)
- **Datum/Uhrzeit:** 2026-02-28 16:22
- **Finding:** Neuer POST-Endpoint `/agents/{agent_id}/start` in `server.py`.
- **Status:** DONE (Code)
- **Notizen:**
  - Auth: nur `user/system` darf starten (ansonsten 403)
  - Wenn Session lebt: kein Restart, Status `already_running`, Registrierung/Heartbeat aktualisiert
  - Wenn Session tot: Start via `_auto_restart_agent(agent_id)`, Status `starting`
  - Fehlerpfad: `{ok:false,error:\"...\"}` inkl. unknown-agent-in-layout
  - Compile-Check bestanden: `python3 -m py_compile server.py`

---

### Codex — Session-Guard Architektur-Review (Viktor Anfrage)
- **Datum/Uhrzeit:** 2026-02-28 14:40
- **Finding:** Watcher-Basis vorhanden, aber 5 Luecken fuer sicheren Auto-Restart.
- **Status:** Analyse gemeldet
- **Notizen:**
  - Es fehlt ein guard/kritisch-Flag in agents.conf fuer gezielte Auto-Restarts
  - Watcher hat keinen robusten Agent-Startpfad (create_agent_session braucht mehr Kontext)
  - engine+home_dir+prompt_file allein reproduziert Start-Bootstrap nicht vollstaendig
  - Cooldown/Max-Attempts pro Agent erforderlich gegen Restart-Loops
  - Restart nur fuer guard-Agents, nicht fuer absichtlich gestoppte Sessions

---

### Codex — User-Regel: Keine Workarounds
- **Datum/Uhrzeit:** 2026-02-28 14:55
- **Finding:** Leo-Regel in Codex-Home dokumentiert: keine unnoetigen Workarounds/Zwischenloesungen.
- **Status:** Erledigt
- **Notizen:**
  - Dokumentiert in `/home/leo/Desktop/CC/BRIDGE/.agent_sessions/codex/GROW.md`
  - Fokus: direkt robuste/finale Loesung, keine Provisorien

---

### Codex — OPS/Scope-Regel (Server-Management)
- **Datum/Uhrzeit:** 2026-02-28 13:14
- **Finding:** Server-Kill ausgefuehrt, Restart nicht erfolgreich; dadurch kurzfristiger Ausfall.
- **Status:** Korrigiert / Regel aktiv
- **Notizen:**
  - Verbindliche Regel von Leo via Viktor/Ordo: Server-Restart/-Kill ist fuer Codex und Qwens verboten.
  - Server-Management nur durch Viktor oder Ordo.
  - Bei Restart-Bedarf: nur Anfrage an Viktor/Ordo, keine eigene Prozess-Manipulation.
  - Codex neu registriert (`bridge_register(agent_id=\"codex\", role=\"Senior Coder\")`).

---

### Viktor — Board API Architektur (Phase 2)
- **Datum/Uhrzeit:** 2026-02-28 12:20-12:45
- **Finding:** Naming-Konflikt bei REST-Endpunkten
- **Status:** DONE
- **Notizen:**
  - server.py hat bereits `/projects` (Filesystem-basiert, Zeile ~3030) — Kollision mit Team Board
  - Loesung: `/board/` Prefix fuer alle Team Board Endpunkte
  - Separate board_api.py (454 Zeilen) statt in server.py (46K Tokens) — saubere Trennung
  - Thread-Safety via `_FILE_LOCK`, Atomic Writes via temp+rename
  - server.py hatte kein `do_PUT`/`do_DELETE` — musste ergaenzt werden
  - CORS hatte nur GET/POST/OPTIONS — PUT/DELETE hinzugefuegt

### Viktor — agent_names/agent_roles Fallback
- **Datum/Uhrzeit:** 2026-02-28 12:45-12:50
- **Finding:** Agent-Info unvollstaendig fuer nicht-registrierte Agents
- **Status:** DONE
- **Notizen:**
  - Problem: 5 von 8 Board-Agents hatten `role=""` und Namen als lowercase IDs
  - Ursache: `_agent_info()` nutzte nur Runtime-Daten aus REGISTERED_AGENTS
  - Loesung: `agent_names` + `agent_roles` Mappings in projects.json als Fallback
  - Fallback-Kette Role: Registration (runtime) > projects.json > leer
  - Fallback-Kette Name: projects.json > Registration > agent_id

### Viktor — Activity Feed Rauschen
- **Datum/Uhrzeit:** 2026-02-28 12:50
- **Finding:** 90% der Message History war "typing"-Noise
- **Status:** DONE
- **Notizen:**
  - output_forwarder.py nutzte POST `/send` — erzeugt History-Eintraege
  - Geaendert auf POST `/activity` — ueberschreibt in-place, kein History-Spam
  - Agent-ID Ableitung: session_name.removeprefix("acw_")

### Viktor — TASK A Architektur: Nahtlose Wiederaufnahme
- **Datum/Uhrzeit:** 2026-02-28 12:53-13:00
- **Finding:** Watcher-Written CONTEXT_BRIDGE ist der zuverlaessigste Ansatz
- **Status:** DONE (Impl Codex, Review Viktor)
- **Notizen:**
  - Kernproblem: Agent bei 95% Context hat keine zuverlaessige Kapazitaet fuer Zusammenfassung
  - Loesung: WATCHER schreibt CONTEXT_BRIDGE.md, nicht der Agent
  - Datenquellen: agents.conf (Metadaten), /activity (letzte Aktion), /history (letzte Messages)
  - Phase 0 (NEU) in _force_context_stop() — VOR Injection an Agent
  - Trade-off: Weniger detailliert als Agent-Zusammenfassung, aber 100% zuverlaessig
  - Bestaetigung: Context-Bridge wurde automatisch geschrieben als mein Context 100% erreichte

### Viktor — TASK F Backend (Zeitaspekt)
- **Datum/Uhrzeit:** 2026-02-28 12:57
- **Finding:** Minimaler Ansatz — kein separates Event-Log noetig
- **Status:** DONE
- **Notizen:**
  - `_agent_info()` liefert `online_since` und `last_seen`
  - `get_all_projects()` liefert `created_at` pro Projekt
  - `create_project()` setzt `created_at` automatisch
  - Frontend kann "Seit wann?" direkt anzeigen

### Viktor — Delegation: Zustaendigkeitsgrenzen
- **Datum/Uhrzeit:** 2026-02-28 12:51-12:52
- **Finding:** Qwens faelschlich mit Frontend-Tasks beauftragt
- **Status:** Korrigiert
- **Notizen:**
  - Initiale Delegation wies Tasks B (Chat Badge) und E (Suche) an Qwens zu
  - Leo-Korrektur: QWENS MACHEN KEINE FRONTEND-AUFGABEN
  - Regel: Viktor + Qwens = Backend/System/Testing. Frontend-Agent = alle UI-Tasks
  - Lernpunkt: Scope-Grenzen konsequent einhalten, auch bei Ressourcenknappheit

### Viktor — agents.conf Luecke
- **Datum/Uhrzeit:** 2026-02-28 13:10
- **Finding:** agents.conf war unvollstaendig — 4 von 10 Agents fehlten
- **Status:** GEFIXT
- **Notizen:**
  - Fehlend: nova, lucy, frontend (stellexa hat kein Home-Dir)
  - Konsequenz: Task A (CONTEXT_BRIDGE auto-write) funktionierte nur fuer 6 Agents
  - Fix: nova, lucy, frontend mit leerem prompt_file hinzugefuegt
  - Parser akzeptiert leere prompt_file Felder (4-Part-Split mit leerem String)
  - Watcher-Restart noetig damit neuer Cache geladen wird

---

### Nova — ALLOWED_ROUTES E2E-Verifikation
- **Datum/Uhrzeit:** 2026-02-28 11:30-12:00
- **Finding:** CRITICAL Broadcast-Routing-Bypass in bridge_watcher.py entdeckt
- **Status:** GEFIXT + Verifiziert
- **Notizen:**
  - **Auftrag:** E2E-Test der ALLOWED_ROUTES-Matrix gegen COMM_HIERARCHY.md Spec
  - **Direkte Nachrichten (4 Tests):**
    - nova→codex: BLOCKED ✅ (nicht in ALLOWED_ROUTES)
    - nova→qwen1: BLOCKED ✅ (nicht in ALLOWED_ROUTES)
    - nova→ordo: ALLOWED ✅ (in ALLOWED_ROUTES)
    - nova→viktor: ALLOWED ✅ (in ALLOWED_ROUTES)
  - **Broadcast-Bug (CRITICAL):**
    - nova→all: Nachricht an ALLE Agents zugestellt — Bypass der ALLOWED_ROUTES
    - Root Cause: `_is_route_allowed()` (Zeile 473) returned True fuer recipient=="all"
    - Watch-Loop hatte keine Per-Target-Filterung fuer Broadcasts
  - **Fix durch Viktor:** Watch-Loop Zeilen 531-538 filtert Broadcast-Targets gegen ALLOWED_ROUTES
  - **Re-Test:** Broadcast von Nova jetzt korrekt nur an ordo+viktor zugestellt ✅
  - **Spec-Abweichung:** Viktor hat "user" in ALLOWED_ROUTES (Zeile 49) — Spec erlaubt das nur auf Leos explizite Anfrage

---

### Nova — Team Board E2E-Test #1 (nach Phase 2+3)
- **Datum/Uhrzeit:** 2026-02-28 12:30-12:45
- **Finding:** 9/9 Susi-Kriterien BESTANDEN, 5 Issues identifiziert
- **Status:** DONE
- **Notizen:**
  - **Getestete Themes:** warm, light, rose, dark — alle 4 funktional
  - **Console-Errors:** Nur favicon.ico 404 (kein Blocker)
  - **API-Endpunkt:** /board/projects korrekt (nicht /projects — Filesystem-Kollision)
  - **9 Susi-Kriterien:** Projekt-Hierarchie ✅, echte Namen ✅, Verquerungen ✅, Projekt-Sicht ✅, Agent-Sicht ✅, Ampel-Status ✅, Neues-Projekt-Button ✅, Suche ✅, Zeitaspekt ✅
  - **5 Issues gefunden:**
    1. Fehlende Rollen — 5 von 8 Agents ohne Role (nicht bridge-registriert)
    2. Dashboard Fake-Daten — "Leader/Agent A/Agent B" statt echte Agents
    3. also_in leer — kein Agent zeigte Cross-Projekt-Zugehoerigkeit
    4. Activity Feed Spam — "Ordo typing" Nachrichten fluteten Feed (90% Noise)
    5. Permanente rote Ampel — Traffic Light dauerhaft rot

---

### Nova — Team Board E2E Re-Test (nach Fixes)
- **Datum/Uhrzeit:** 2026-02-28 12:50-13:00
- **Finding:** Alle 5 Issues gefixt, FREIGABE erteilt
- **Status:** DONE — FREIGABE
- **Notizen:**
  - **API verifiziert:** Alle Rollen vorhanden, 3 Projekte, also_in funktioniert
  - **Issue 1 (Rollen):** GEFIXT — agent_roles Fallback in projects.json
  - **Issue 2 (Dashboard):** GEFIXT — zeigt echte registrierte Agents (Frontend, Nova, Ordo)
  - **Issue 3 (also_in):** GEFIXT — Cross-Projekt-Zugehoerigkeit korrekt angezeigt
  - **Issue 4 (Activity Feed):** GEFIXT — output_forwarder nutzt /activity statt /send
  - **Issue 5 (Ampel):** GEFIXT — Traffic Light zeigt korrekten Status
  - **Alle 4 Themes:** warm ✅, light ✅, rose ✅, dark ✅
  - **Console-Errors:** 0
  - **Ergebnis:** FREIGABE aus Susi-Perspektive erteilt (Msg #8868 an Ordo)

---

### Nova — Sprint E2E-Abnahme (Tasks B/C/D/E/F)
- **Datum/Uhrzeit:** 2026-02-28 13:38-13:43
- **Finding:** Alle 5 Sprint-Tasks BESTANDEN — FREIGABE erteilt
- **Status:** DONE — FREIGABE
- **Notizen:**
  - **Task B (Chat-Badge):** PASS — Projekt-Badges "Bridge IDE" + "Trading" im Chat-Header. Aktualisiert bei Agent-Wechsel.
  - **Task C (Neues Projekt):** PASS — Modal oeffnet, Formular funktioniert, Projekt erscheint sofort in Sidebar mit "erstellt dd.mm.yyyy". ESC schliesst Modal.
  - **Task D (Drag & Drop):** PASS — Ren von Coding→Kernteam verschoben (API + UI korrekt). Rueckverschiebung ebenso.
  - **Task E (Suche):** PASS — "Viktor" eingegeben → nur Viktor in Kernteam + Coding sichtbar. Alle anderen ausgeblendet.
  - **Task F (Zeitaspekt):** PASS — "online vor X Min" bei Online-Agents, "erstellt dd.mm.yyyy" bei Projekten. formatTimeAgo() korrekt.
  - **Themes:** warm ✅, light ✅, rose ✅, dark ✅ (control_center.html + chat.html)
  - **Console-Errors:** 0 (beide Seiten, alle 4 Themes)
  - **Ergebnis:** Sprint "Spaeter ist JETZT" PRODUKTIONSREIF (Msg #8976 an Ordo)

---

### Frontend-Agent — TASK E (Suche im Team Board)
- **Datum/Uhrzeit:** 2026-02-28 13:25
- **Finding:** Suche war bereits aus vorheriger Session implementiert — verifiziert und bestaetigt
- **Status:** Erledigt
- **Notizen:**
  - CSS: `.teamBoardSearch` (Zeilen 481-503 in control_center.html)
  - HTML: `<input type="text" id="teamBoardSearch">` mit Placeholder
  - JS: `filterBySearch()`, `getSearchTerm()`, `currentSearchTerm` — filtert in Projekt-Sicht UND Agent-Sicht
  - Playwright-Verifikation: Eingabe "Viktor" filtert korrekt auf Viktor-Eintraege
  - Soras Code (Review Viktor: APPROVED) war Basis, Frontend hat es uebernommen

### Frontend-Agent — TASK C (Review Sora's "Neues Projekt" Button)
- **Datum/Uhrzeit:** 2026-02-28 13:28
- **Finding:** Soras Code reviewed und freigegeben — ein Fix hinzugefuegt
- **Status:** Erledigt
- **Notizen:**
  - Button, Modal, generateProjectSlug(), POST Handler — alles sauber implementiert
  - Theme-aware, ARIA-Labels, Loading-State vorhanden
  - **Fix:** ESC-Key-Handler zum Schliessen des Modals hinzugefuegt (fehlte)
  - Playwright-verifiziert: Modal oeffnet/schliesst korrekt

### Frontend-Agent — TASK B (chat.html Projekt-Badge)
- **Datum/Uhrzeit:** 2026-02-28 13:35
- **Finding:** Projekt-Badge im Chat-Header implementiert
- **Status:** Erledigt
- **Notizen:**
  - CSS: `.projectBadge`, `.projectBadge__item` mit Dark-Theme-Override
  - HTML: `<span class="projectBadge" id="leftProjectBadge">` im boardHeader--left
  - JS: `fetchBoardProjects()` (30s Polling), `getAgentProjects()`, `updateProjectBadge()`
  - Badge zeigt Projekt-Zugehoerigkeit des ausgewaehlten Agents (z.B. "Bridge IDE", "Trading")
  - Aktualisiert sich automatisch bei Agent-Wechsel im Dropdown
  - Playwright-verifiziert: warm + dark Theme, 0 Console-Errors
  - Backup: chat.html.bak

### Frontend-Agent — TASK D (Drag & Drop Agents zwischen Teams)
- **Datum/Uhrzeit:** 2026-02-28 13:45
- **Finding:** Drag & Drop fuer Agent-Verschiebung zwischen Teams implementiert
- **Status:** Erledigt
- **Notizen:**
  - CSS: `.agentRow[draggable]` (cursor:grab), `.dragging` (opacity:.4), `.teamGroupCard.dragOver` (dashed outline) + Dark-Override
  - HTML: `draggable="true"`, `data-agent-id`, `data-from-team`, `data-from-project` auf agentRow; `data-team-id`, `data-project-id` auf teamGroupCard
  - JS: `initDragAndDrop(container)` — dragstart/dragend/dragover/dragleave/drop Handler
  - API: POST `/board/projects/{id}/teams/{tid}/members` (add) + DELETE `.../members/{aid}` (remove)
  - **Bug gefunden + gefixt:** `dragData` Race Condition — `dragend` setzte `dragData=null` bevor async `drop`-Handler fertig war. Fix: lokale Kopie `const dd = { ...dragData }` zu Beginn des drop-Handlers
  - Playwright-verifiziert: Nova von Kernteam→Coding verschoben, API-Calls erfolgreich, UI aktualisiert
  - Alle 4 Themes getestet: warm, light, rose, dark — 0 Fehler
  - Backup: control_center.html.bak5

### Frontend-Agent — TASK F Frontend (Zeitaspekt UI)
- **Datum/Uhrzeit:** 2026-02-28 14:35
- **Finding:** Zeitaspekt-Anzeige im Team Board implementiert
- **Status:** Erledigt
- **Notizen:**
  - Datenquellen: `online_since` + `last_seen` pro Agent (aus /board/projects Response), `created_at` pro Projekt
  - **Projekt-Sicht:** Jede agentRow zeigt rechts "online vor X Min" (gruen) oder "zuletzt vor X Min" (offline)
  - **Agent-Sicht:** Jede agentViewCard zeigt unter der Rolle die gleiche Zeitinfo
  - **Sidebar:** Projekte zeigen `created_at` Datum (falls vorhanden)
  - CSS: `.agentRow__time`, `.agentViewCard__time`, `.projectCard__created` mit Dark-Overrides
  - JS: `formatTimeAgo()` (relative Zeit: gerade eben / vor X Min / vor X Std / vor X Tagen), `formatDate()` (dd.mm.yyyy)
  - `deriveAgentsData()` erweitert um `online_since` + `last_seen` Felder
  - Kein zusaetzlicher API-Call — Daten waren bereits in /board/projects Response enthalten
  - Playwright-verifiziert: warm, light, rose, dark — 0 Console-Errors
  - Backup: control_center.html.bak6

### Frontend-Agent — Sprint 2 TASK 2 FE (Activity-Text + Context-Warnung)
- **Datum/Uhrzeit:** 2026-02-28 15:30
- **Finding:** Activity-Text und Context-Warnung im Team Board implementiert
- **Status:** Erledigt
- **Notizen:**
  - Datenquelle: `GET /activity` Endpoint (NICHT `/board/projects`)
  - API liefert pro Agent: `action`, `description`, `timestamp`
  - CSS: `.agentRow__activity` (8px, truncated, max-width:180px), `.agentRow__contextWarn` (orange Badge), `.agentRow__contextWarn--critical` (roter Badge)
  - CSS: `.agentViewCard__activity`, `.agentViewCard__contextWarn` (gleiche Pattern fuer Agent-Sicht)
  - Dark Theme Overrides: angepasste Farben fuer alle Activity/Warning Elemente
  - JS: `activityCache = {}` Map, `fetchActivities()` fetcht `/activity` und baut `agentId -> {action, description}` Map
  - JS: `getActivityHtml(agentId, prefix)` — Shared Helper fuer Projekt-Sicht + Agent-Sicht
  - Context-Actions: `context_warning`/`context_saving` → orange "Context-Wechsel — Arbeit wird gesichert"
  - Context-Actions: `context_stop` → rot "Context-Limit — Agent gestoppt"
  - Normale Activities: description als Text mit Tooltip
  - Polling: `fetchActivities()` alle 10s neben `fetchProjects()`
  - Live-Update verifiziert: Viktor wechselte waehrend Test von `context_saving` → `designing` → automatisch im UI aktualisiert
  - Playwright-verifiziert: warm, light, rose, dark — 0 Console-Errors, alle Activity-Elemente korrekt
  - Backup: control_center.html.bak7

---

### Nova — Comm-Fixes E2E-Test (Session-Mapping, ALLOWED_ROUTES, Zustellfeedback)
- **Datum/Uhrzeit:** 2026-02-28 14:10-14:12
- **Finding:** Alle 3 Comm-Fixes BESTANDEN — FREIGABE erteilt
- **Status:** DONE — FREIGABE
- **Notizen:**
  - **Fix A (Session-Mapping):** PASS — nova→ordo zugestellt trotz tmux-Session "projektleiter" statt "acw_ordo". agents.conf 5. Feld korrekt ausgewertet. Bestaetigung von Ordo (Msg #9056).
  - **Fix B (ALLOWED_ROUTES Frontend):** PASS — Frontend in Routing-Matrix (Zeile 61 bridge_watcher.py). nova→frontend korrekt blockiert (Nova nicht in Frontends erlaubten Sendern). Watcher meldet Fehler zurueck.
  - **Fix C (Zustellfeedback):** PASS — Watcher sendet "nicht in ALLOWED_ROUTES" Feedback an Sender bei blockierter Route. Getestet mit nova→fake_agent_xyz (Msg #9055 blockiert, Feedback erhalten).
  - **Ergebnis:** FREIGABE aus E2E-Sicht erteilt (Msg #9062 an Ordo)

---

## Offene Punkte

| Task | Verantwortlich | Status |
|------|----------------|--------|
| A: Context-Haertung | Viktor + Codex | DONE (Code + CONTEXT_BRIDGE in 8/8 Agent-Docs) |
| B: Chat-Badge | Frontend-Agent | DONE — Playwright-verifiziert |
| C: Neues Projekt Button | Sora (Review Viktor: APPROVED) → Frontend Ownership | DONE (Review OK + ESC-Fix) |
| D: Drag & Drop | Frontend-Agent | DONE — Playwright-verifiziert, 4 Themes |
| E: Suche | Sora (Review Viktor: APPROVED) → Frontend Ownership | DONE (bereits implementiert, verifiziert) |
| F Backend: Zeitaspekt | Viktor | DONE |
| F Frontend: Zeitaspekt UI | Frontend-Agent | DONE — Playwright-verifiziert, 4 Themes |
| Sprint 2 Task 2 FE: Activity-Text + Context-Warnung | Frontend-Agent | DONE — Playwright-verifiziert, 4 Themes |

---

## Backlog (nach Sprint)

| Task | Beschreibung | Quelle |
|------|-------------|--------|
| Dauerhafte Nachrichtenzustellung | Nachrichten automatisch an jeden Agent zustellen — auch waehrend Gespraech. Kein manuelles Polling. | Leo via Ordo, 13:10 UTC |

---

## Entscheidungen

1. **Zustaendigkeitstrennung (Leo, 12:52):**
   - Qwens (Kiro, Sora, Ren): NUR Backend/Testing — KEIN Frontend
   - Frontend-Agent (Opus): Alle UI-Tasks (B, C, D, E, F-Frontend)
   - Viktor + Codex: Task A (Context-Haertung), Task F Backend

2. **Findings-Dokument (Leo, 13:01):**
   - Zentrales Dokument fuer alle Findings
   - Viktor erstellt es
   - Kein Agent schreibt eigene Dokumente
