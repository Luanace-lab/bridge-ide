# Strategie: System-Nachrichten Reduktion (v2)
Stand: 2026-03-15 15:32 UTC
Autor: Ordo
Review: Leo (15:32 UTC) — Korrekturen eingearbeitet

## Ausgangslage

517 System-Nachrichten heute. Aufschlag nach Typ (Live-Daten):

| Tag | Anzahl | Anteil |
|-----|--------|--------|
| CONTEXT RESTORE | 73 | 14% |
| HEARTBEAT_CHECK | 72 | 14% |
| AUTO-RESTART | 69 | 13% |
| WARN | 68 | 13% |
| RECOVERY | 65 | 13% |
| RESTART WARN | 63 | 12% |
| ONLINE | 54 | 10% |
| Rest | 53 | 10% |

**Grundannahme (Leo-Korrektur):** Restarts sind KEIN Bug. Sie sind gewollter/zu haertender Normalbetrieb. Die Strategie muss auf restart-heavy Betrieb ausgelegt sein.

## Ist-Zustand (aktuelle Konfiguration)

| Parameter | Wert | Datei |
|-----------|------|-------|
| Heartbeat-Intervall | 300s (5 Min) | daemons/heartbeat_prompt.py:6 |
| Health-Monitor-Intervall | 60s | daemons/health_monitor.py:6 |
| System-Notice-Cooldown (Ordo) | 300s | bridge_watcher.py:456 |
| Context-Block ab | 85% | bridge_watcher.py:2860 |
| Restart-Frequenz | ~14 Min | Gewollter Normalbetrieb (Haertung) |

---

## Massnahme 1: HEARTBEAT_CHECK 300s → 900s

**Status:** LEO FREIGEGEBEN

**Was:** Intervall von 5 auf 15 Minuten erhoehen.
**Datei:** daemons/heartbeat_prompt.py:6 — `_HEARTBEAT_PROMPT_INTERVAL = 900`
**Risiko:** Keins. Passive Monitoring (tmux-Output, Heartbeat-Age) laeuft weiterhin alle 60s.
**Ersparnis:** ~48 Checks/Tag weniger → ~50.000 Tokens/Tag

---

## Massnahme 2: CONTEXT RESTORE komprimieren

**Status:** LEO PRINZIPIELL EINVERSTANDEN (Format-Details offen)

**Problem:** server.py `_should_send_context_restore()` bettet CONTEXT_BRIDGE.md + SOUL.md + MEMORY.md + CLI_JOURNAL komplett ein. ~8KB pro Nachricht × 73/Tag = ~580KB = ~145.000 Tokens.

**Vorschlag:** Nur CONTEXT_BRIDGE.md einbetten + Hinweis "Lies SOUL.md und MEMORY.md von Disk". Der Agent hat die Dateien lokal — sie muessen nicht per Nachricht kommen.

**Format (kompakt, ~1KB statt ~8KB):**
```
[CONTEXT RESTORE] Dein letzter Zustand:
- Status: {status}
- Modus: {modus}
- Letzte Aktivitaet: {aktivitaet}
- Offene Tasks: {tasks}
PFLICHT: Lies SOUL.md, CONTEXT_BRIDGE.md und MEMORY.md von Disk.
Dann: bridge_register() + bridge_receive()
```

**Datei:** server.py, Funktion um Zeile 7298 (Registration-Flow)
**Risiko:** Gering. Agent muss Dateien selbst lesen (tut er ohnehin per CLAUDE.md-Anweisung).
**Ersparnis:** ~130.000 Tokens/Tag (von 145K auf ~15K)

---

## Massnahme 3: Routenmatrix nach Schweregrad

**Status:** NEU (Leo-Anforderung)

**Problem:** Derzeit werden WARN/RECOVERY/ONLINE an Manager UND betroffenen Agent gesendet. Kein differenziertes Routing nach Schweregrad.

**Routenmatrix:**

| Tag | Schweregrad | → Agent | → Manager (Ordo) | → User | → Dashboard (/health) |
|-----|-------------|---------|-------------------|--------|----------------------|
| [CRASH] | CRITICAL | ja | ja | ja | ja |
| [CRITICAL] (Supervisor) | CRITICAL | — | ja | ja | ja |
| [CRITICAL] (Heartbeat) | HIGH | ja | nein* | nein | ja |
| [WARN] (Heartbeat) | MEDIUM | ja | nein* | nein | ja |
| [WARN] (Stuck) | HIGH | ja | ja | nein | ja |
| [RECOVERY] | LOW | — | nein | nein | ja |
| [ONLINE] | INFO | — | nein** | nein | ja |
| [OFFLINE] | MEDIUM | — | ja | nein | ja |
| [CONTEXT RESTORE] | HIGH | ja | nein | nein | — |
| [HEARTBEAT_CHECK] | LOW | ja | nein | nein | — |
| [RESTART WARN] | HIGH | ja (all) | ja | nein | ja |
| [RESTART WAKE] | INFO | ja (all) | nein | nein | ja |
| [AUTO-RESTART] | MEDIUM | — | nein | ja | ja |
| [MODE CHANGE] | HIGH | ja | nein | nein | — |
| [TASK DONE/FAILED] | HIGH | creator | ja | ja*** | ja |
| [APPROVAL *] | CRITICAL | requester | — | ja | — |
| [BEHAVIOR-WATCH/ALERT] | MEDIUM | ja | nein | nein | ja |
| [MEMORY] | LOW | ja | nein | nein | — |
| [BUDDY_FRONTDOOR] | HIGH | buddy | nein | nein | — |

*) Heartbeat WARN/CRITICAL fuer einzelne Agents: nur an Dashboard — Manager sieht es bei Bedarf per /health.
**) ONLINE: nur an Dashboard. Peers die dem Agent geschrieben haben koennten optional benachrichtigt werden.
***) TASK DONE/FAILED an User: nur wenn User der Creator ist.

**Implementierung:**
1. Neue Funktion `_route_system_message(tag, severity, affected_agent)` in server.py oder daemons/health_monitor.py
2. Jeder System-Message-Generator ruft `_route_system_message()` statt direkt `append_message()` auf
3. Routing-Tabelle als Config (nicht hardcodiert) — z.B. in `config.py` oder eigene `routing_config.json`

**Ersparnis:** ~60.000 Tokens/Tag (RECOVERY, ONLINE, Heartbeat-WARN nicht mehr an Manager injiziert)

---

## Zusammenfassung

| Massnahme | Status | Ersparnis/Tag | Risiko |
|-----------|--------|---------------|--------|
| Heartbeat 300→900s | FREIGEGEBEN | ~50.000 Tk | Keins |
| CONTEXT RESTORE komprimieren | PRINZIPIELL OK | ~130.000 Tk | Gering |
| Routenmatrix | NEU — Leo-Review erforderlich | ~60.000 Tk | Mittel |
| **Gesamt** | | **~240.000 Tk** | |

## Was NICHT geaendert werden darf

- [CONTEXT RESTORE] nach Compact IMMER senden (Agent hat sonst keinen Kontext)
- [RESTART WARN] bleibt an alle Agents (Context sichern)
- [MODE CHANGE] bleibt an betroffenen Agent
- [TASK *] bleibt (Task-Lifecycle)
- [APPROVAL *] bleibt (User-Entscheidungen)
- [CRASH] / [CRITICAL] (Supervisor) an User bleibt

## Delta zu v1

| Was | v1 | v2 |
|-----|----|----|
| Restart-Annahme | "Bug/Loop — fixen" | "Gewollter Normalbetrieb — Strategie darauf ausrichten" |
| WARN/RECOVERY Routing | "Nur an betroffenen Agent" | Routenmatrix nach Schweregrad × Empfaenger |
| Live-Daten | 488 (teilweise geschaetzt) | 517 (exakte Zahlen von Leo) |
| ONLINE Routing | "Nur an relevante Peers" | Dashboard-only + optionale Peer-Notification |
| Neues Element | — | Routing-Config als separierbare Tabelle |
