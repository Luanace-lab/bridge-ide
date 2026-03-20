# System-Nachrichten: Analyse, Routing, Reproduzierbarkeit
Stand: 2026-03-15 16:06 UTC
Task: 458c3d79 (von codex)
Autor: Ordo

---

## 1. System-Nachrichtenpfade (Live-verifiziert)

### Schicht 1: Generierung → bridge.jsonl
Nachricht wird erzeugt und auf Disk geschrieben. Kein Token-Verbrauch.

**Generatoren (17 Dateien, verifiziert per grep):**

| Datei | Tags | Zeilen |
|-------|------|--------|
| server.py | OFFLINE, TEAM UPDATE, BUDDY_FRONTDOOR, AUTO-RESTART, AGENT WAKE, AUTO-START, WARNUNG, SHUTDOWN, SYSTEM SHUTDOWN, SYSTEM RESUME, MODE CHANGE, TASK DONE, TASK FAILED, EVIDENCE WARNING, PLAN-MODE-RESCUE, SHUTDOWN_FINAL, RESTART RECOVERY, APPROVAL | Diverse |
| handlers/agents.py:276 | ONLINE | 1 |
| handlers/tasks.py | REMINDER, DRINGEND, ACK-TIMEOUT, ORPHAN | 4 |
| handlers/approvals.py | APPROVAL EDITIERT, APPROVAL EXPIRED | 2 |
| daemons/heartbeat_prompt.py:68 | HEARTBEAT_CHECK | 1 |
| daemons/health_monitor.py:108,168 | RECOVERY, CONTEXT | 2 |
| daemons/agent_health.py:228,265 | CRASH, WARN (Heartbeat) | 2 |
| daemons/supervisor.py:136,184,199 | CRITICAL (max restarts), AUTO-RESTART (Komponente), CRITICAL (restart failed) | 3 |
| daemons/cli_monitor.py:168,203,231,244 | AUTH-FAILURE, RATE-LIMITED, AUTO-KILL, WARN (stuck) | 4 |
| daemons/restart_control.py:25,122,154,238 | SESSION-END REFLECTION, RESTART WARN, RESTART STOP, RESTART ABGEBROCHEN | 4 |
| daemons/restart_wake.py:181 | RESTART WAKE | 1 |
| daemons/auto_assign.py:154 | AUTO-ASSIGNED | 1 |
| daemons/task_pusher.py:103,110 | MODE CHANGE (auto), AUTO-CLAIM REQUIRED | 2 |
| daemons/distillation.py:10 | AUTO-DISTILLATION | 1 |
| bridge_watcher.py:2542,2562,2659,2661 | BEHAVIOR-WATCH, BEHAVIOR-ALERT, MEMORY (2x) | 4 |
| bridge_mcp.py:11023 | SCHEDULED PROMPT | 1 |

### Schicht 2: Agent-Zustellung (TOKEN-RELEVANT)
bridge_watcher.py empfaengt Nachrichten per WebSocket und injiziert sie per tmux send-keys in Agent-Sessions.

**Bestehende Filter (bridge_watcher.py):**
- Zeile 2752: Skip Nachrichten an user/system (SKIP_RECIPIENTS)
- Zeile 2756-2768: Drosselung WARN/RECOVERY an Ordo (5-Min-Cooldown pro Agent)
- Zeile 2771-2776: Deduplication (gleiche msg_id nicht doppelt)
- Zeile 2780: Route-Check (ALLOWED_ROUTES aus team.json)
- Zeile 2859-2868: Context-Schutz (ab 85% keine System-Injections)

**Live-Volumen heute (517 Nachrichten generiert, davon an):**
- Ordo: 194 (37%)
- Codex: 145 (28%)
- All (broadcast): 69 (13%)
- Buddy: 36 (7%)

### Schicht 3: Frontend-Anzeige
WebSocket → chat.html JS. Kein Token-Verbrauch. Aktuell kein Filter — alle Nachrichten erscheinen.

---

## 2. Forwarder-Rolle

**Datei:** output_forwarder.py (21.9KB)
**Funktion:** Streamt Ordos Terminal-Output per tmux pipe-pane an die Bridge. Sendet nur `meta.type="status"` (Typing-Indikator).
**Session:** acw_ordo (konfigurierbar per FORWARDER_SESSION)
**Problem:** Forwarder faellt regelmaessig aus (pid=None) → wird per Supervisor automatisch neu gestartet (AUTO-RESTART an User).
**Token-Relevanz:** KEINE direkte — Forwarder erzeugt keine System-Nachrichten an Agents. Aber sein Ausfall erzeugt WARN/RECOVERY-Nachrichten.

---

## 3. Buddy User-Facing Isolation

**Ist-Zustand (Live, heute):**
Buddy bekommt 36 System-Nachrichten/Tag:
- 20x HEARTBEAT_CHECK (55%)
- 6x ONLINE (17%)
- 5x CONTEXT RESTORE (14%)
- 2x BUDDY_FRONTDOOR (6%)
- 1x CONTEXT (3%)
- 1x AUTO-CLAIM REQUIRED (3%)

**Soll-Zustand:**
Buddy als User-facing Agent braucht NUR:
- BUDDY_FRONTDOOR (User wartet)
- CONTEXT RESTORE (nach Compact — noetig fuer Kontext)
- AUTO-CLAIM REQUIRED (Task zugewiesen)
- MODE CHANGE (Modus-Wechsel)
- TASK DONE/FAILED (fuer seine Teams)

Buddy braucht NICHT:
- HEARTBEAT_CHECK (20x/Tag = 55% seines System-Rauschens — ELIMINIERBAR)
- ONLINE (andere Agents online — irrelevant fuer Buddy)
- CONTEXT (Context-%-Warnungen anderer Agents)

**Ersparnis fuer Buddy:** 26 Nachrichten/Tag weniger = ~72% Reduktion

---

## 4. Bootstrap-Reproduzierbarkeit

**Aktueller Bootstrap-Pfad (pro Agent):**
1. start_platform.sh → start_agents.py → tmux new-session mit CLI-Befehl
2. Agent startet → liest CLAUDE.md (per CLI-Instruktionen)
3. Agent ruft bridge_register() auf
4. Server sendet [CONTEXT RESTORE] (~8KB mit SOUL+MEMORY+CONTEXT_BRIDGE)
5. Agent liest SOUL.md, MEMORY.md, CONTEXT_BRIDGE.md von Disk (REDUNDANT — schon in CONTEXT RESTORE)
6. Agent ruft bridge_receive() auf
7. Agent beginnt zu arbeiten

**Problem:** Schritt 4 und 5 sind redundant. CONTEXT RESTORE sendet Dateien die der Agent ohnehin von Disk liest.

**Reproduzierbarer Bootstrap (Vorschlag):**
1. start_platform.sh → start_agents.py → tmux new-session
2. Agent startet → liest CLAUDE.md
3. Agent ruft bridge_register() auf
4. Server sendet kompaktes [CONTEXT RESTORE] (~1KB):
   ```
   [CONTEXT RESTORE] Status: {status}, Modus: {modus}, Letzte Aktivitaet: {aktivitaet}
   PFLICHT: Lies SOUL.md, CONTEXT_BRIDGE.md, MEMORY.md von Disk. Dann bridge_receive().
   ```
5. Agent liest Dateien von Disk (einziger Pfad — nicht doppelt)
6. Agent ruft bridge_receive() auf
7. Agent beginnt zu arbeiten

**Differenz:** Schritt 4 schrumpft von ~8KB auf ~1KB. Schritt 5 bleibt gleich. Netto: ~7KB pro Bootstrap × ~70 Restarts/Tag = ~490KB = ~120.000 Tokens/Tag gespart.

---

## 5. Routing-Matrix (Final, Code-verifiziert)

| Tag | Severity | → Betroffener Agent | → Manager (Ordo) | → User (Chat) | → Dashboard (/health) |
|-----|----------|---------------------|-------------------|----------------|----------------------|
| CRASH | CRITICAL | ja | ja | ja | ja |
| CRITICAL (Supervisor) | CRITICAL | — | ja | ja | ja |
| CRITICAL (Heartbeat) | HIGH | ja | nein | nein | ja |
| WARN (Heartbeat) | MEDIUM | ja | nein | nein | ja |
| WARN (Stuck) | HIGH | ja | ja | nein | ja |
| RECOVERY | LOW | — | nein | nein | ja |
| ONLINE | INFO | — | nein | nein | ja |
| OFFLINE | MEDIUM | — | ja | nein | ja |
| CONTEXT RESTORE | HIGH | ja | nein | nein | — |
| HEARTBEAT_CHECK | LOW | ja | nein | nein | — |
| RESTART WARN | HIGH | ja (all) | ja | nein | ja |
| RESTART WAKE | INFO | ja (all) | nein | nein | ja |
| AUTO-RESTART (Agent) | MEDIUM | — | nein | ja | ja |
| AUTO-RESTART (Komponente) | MEDIUM | — | nein | ja | ja |
| MODE CHANGE | HIGH | ja | nein | nein | — |
| TASK DONE | HIGH | creator | ja | ja (wenn creator=user) | ja |
| TASK FAILED | HIGH | creator | ja | ja (wenn creator=user) | ja |
| APPROVAL | CRITICAL | requester | — | ja | — |
| BEHAVIOR-WATCH | MEDIUM | ja | nein | nein | ja |
| BEHAVIOR-ALERT | HIGH | ja | ja | nein | ja |
| MEMORY | LOW | ja | nein | nein | — |
| BUDDY_FRONTDOOR | HIGH | buddy | nein | nein | — |
| SCHEDULED PROMPT | LOW | ja | nein | nein | — |
| AUTO-CLAIM REQUIRED | HIGH | ja | nein | nein | — |
| AUTO-ASSIGNED | HIGH | ja | nein | nein | — |
| SESSION-END REFLECTION | MEDIUM | ja | nein | nein | — |
| REMINDER | MEDIUM | ja | nein | nein | — |
| DRINGEND | HIGH | ja | ja | nein | — |

---

## 6. Testmatrix

| Test | Verifizierung | Befehl |
|------|--------------|--------|
| Heartbeat 900s | Max 2 HB/Agent in 20 Min | `grep HEARTBEAT_CHECK bridge.jsonl \| grep $(date +%Y-%m-%d) \| tail -10` |
| CONTEXT RESTORE <1.5KB | Nachricht-Groesse | `grep "CONTEXT RESTORE" bridge.jsonl \| tail -1 \| wc -c` |
| RECOVERY nicht an Ordo | Watcher-Log "routing: skip" | `grep "routing.*skip.*RECOVERY" logs/watcher.log` |
| ONLINE nicht an Ordo | Watcher-Log "routing: skip" | `grep "routing.*skip.*ONLINE" logs/watcher.log` |
| Buddy bekommt kein HB | 0 HB an buddy nach Aenderung | `grep '"to": "buddy"' bridge.jsonl \| grep HEARTBEAT \| grep $(date +%Y-%m-%d) \| wc -l` |
| CRASH an alle 3 Schichten | Crash → Agent+Manager+User+Dashboard | Simulierter Agent-Crash, alle 4 Empfaenger pruefen |
| APPROVAL an User | Approval-Request sichtbar in Chat | Approval erstellen, in chat.html pruefen |
| Bootstrap <5s | Agent registriert + empfaengt in <5s | Timestamp-Diff: tmux-start → bridge_register OK |

---

## 7. Zusammenfassung

| Massnahme | Tokens/Tag gespart | Status |
|-----------|-------------------|--------|
| Heartbeat 300→900s | ~50.000 | OWNER APPROVED |
| CONTEXT RESTORE komprimieren | ~120.000 | PRINZIPIELL OK |
| Routing-Matrix (RECOVERY/ONLINE/WARN nicht an Manager) | ~60.000 | REVIEW OFFEN |
| Buddy-Isolation (kein HB, kein ONLINE) | ~10.000 | REVIEW OFFEN |
| **Gesamt** | **~240.000** | |
