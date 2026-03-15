# Implementierungsvorlage: System-Nachrichten Reduktion
Stand: 2026-03-15 15:36 UTC
Autor: Ordo

## 3-Schichten-Modell

| Schicht | Was | Wo | Token-Kosten | Kontrollpunkt |
|---------|-----|-----|-------------|---------------|
| 1. Generierung | Nachricht wird erzeugt und in bridge.jsonl gespeichert | Backend (server.py, daemons/, handlers/) | 0 (nur Disk) | Intervall, Cooldown |
| 2. Agent-Zustellung | Nachricht wird per Watcher in tmux injiziert | bridge_watcher.py | TOKEN-RELEVANT — Agent verarbeitet die Nachricht | Routing-Config, Context-Block |
| 3. Frontend-Anzeige | Nachricht erscheint in chat.html | Frontend (WebSocket → JS) | 0 (nur Rendering) | Filter/Suppression in JS |

**Kernaussage:** Token-Kosten entstehen NUR in Schicht 2 (Agent-Zustellung). Schicht 1 und 3 sind kostenlos. Die Strategie muss auf Schicht 2 fokussieren.

---

## A) Routing-Config-Struktur

Neue Datei: `Backend/system_message_routing.json`

```json
{
  "_version": 1,
  "_description": "Routing-Regeln fuer System-Nachrichten. Steuert Schicht 2 (Agent-Zustellung).",
  "routes": {
    "CRASH":            { "severity": "critical", "to_agent": true,  "to_manager": true,  "to_user": true  },
    "CRITICAL_SUPER":   { "severity": "critical", "to_agent": false, "to_manager": true,  "to_user": true  },
    "CRITICAL_HB":      { "severity": "high",     "to_agent": true,  "to_manager": false, "to_user": false },
    "WARN_HB":          { "severity": "medium",   "to_agent": true,  "to_manager": false, "to_user": false },
    "WARN_STUCK":       { "severity": "high",     "to_agent": true,  "to_manager": true,  "to_user": false },
    "RECOVERY":         { "severity": "low",      "to_agent": false, "to_manager": false, "to_user": false },
    "ONLINE":           { "severity": "info",     "to_agent": false, "to_manager": false, "to_user": false },
    "OFFLINE":          { "severity": "medium",   "to_agent": false, "to_manager": true,  "to_user": false },
    "CONTEXT_RESTORE":  { "severity": "high",     "to_agent": true,  "to_manager": false, "to_user": false },
    "HEARTBEAT_CHECK":  { "severity": "low",      "to_agent": true,  "to_manager": false, "to_user": false },
    "RESTART_WARN":     { "severity": "high",     "to_agent": true,  "to_manager": true,  "to_user": false },
    "RESTART_WAKE":     { "severity": "info",     "to_agent": true,  "to_manager": false, "to_user": false },
    "AUTO_RESTART":     { "severity": "medium",   "to_agent": false, "to_manager": false, "to_user": true  },
    "MODE_CHANGE":      { "severity": "high",     "to_agent": true,  "to_manager": false, "to_user": false },
    "TASK_DONE":        { "severity": "high",     "to_agent": true,  "to_manager": true,  "to_user": true  },
    "TASK_FAILED":      { "severity": "high",     "to_agent": true,  "to_manager": true,  "to_user": true  },
    "APPROVAL":         { "severity": "critical", "to_agent": true,  "to_manager": false, "to_user": true  },
    "BEHAVIOR_WATCH":   { "severity": "medium",   "to_agent": true,  "to_manager": false, "to_user": false },
    "MEMORY":           { "severity": "low",      "to_agent": true,  "to_manager": false, "to_user": false },
    "BUDDY_FRONTDOOR":  { "severity": "high",     "to_agent": true,  "to_manager": false, "to_user": false },
    "SCHEDULED_PROMPT": { "severity": "low",      "to_agent": true,  "to_manager": false, "to_user": false }
  },
  "defaults": {
    "to_agent": true,
    "to_manager": false,
    "to_user": false
  }
}
```

**Semantik:**
- `to_agent`: Nachricht wird per Watcher in die tmux-Session des betroffenen Agents injiziert (TOKEN-RELEVANT)
- `to_manager`: Nachricht wird an Ordo/Manager injiziert (TOKEN-RELEVANT)
- `to_user`: Nachricht erscheint im User-Chat-Panel (kein Token-Verbrauch, nur Frontend)
- Alles wird IMMER in bridge.jsonl geschrieben (Schicht 1) — Routing steuert nur Schicht 2+3

---

## B) Betroffene Generatoren/Dateien

### Schicht 1: Generierung (Intervall/Inhalt aendern)

| Aenderung | Datei | Zeile | Was genau |
|-----------|-------|-------|-----------|
| Heartbeat 300→900s | daemons/heartbeat_prompt.py | 6 | `_HEARTBEAT_PROMPT_INTERVAL = 300` → `900` |
| CONTEXT RESTORE komprimieren | server.py | ~7298 | In `_should_send_context_restore()` / Registration-Flow: Nur CONTEXT_BRIDGE.md Felder einbetten, SOUL+MEMORY weglassen, Hinweis "Lies von Disk" |

### Schicht 2: Agent-Zustellung (Routing aendern)

| Aenderung | Datei | Zeile | Was genau |
|-----------|-------|-------|-----------|
| Routing-Config laden | bridge_watcher.py | NEU | `_load_routing_config()` — liest system_message_routing.json |
| Routing anwenden | bridge_watcher.py | ~2755-2868 | Vor Injection: Tag aus Content parsen → Routing-Config nachschlagen → skip wenn `to_agent=false` fuer diesen Empfaenger |
| ONLINE nicht injizieren | handlers/agents.py | 276 | Generierung bleibt (bridge.jsonl), aber Watcher injiziert nicht (routing: `to_agent=false`) |
| RECOVERY nicht injizieren | daemons/health_monitor.py | 108 | Generierung bleibt, Watcher injiziert nicht |
| WARN (Heartbeat) nicht an Manager | daemons/agent_health.py | 265 | Generierung sendet nur an betroffenen Agent, nicht an Manager |

### Schicht 3: Frontend-Suppression (UX aendern)

| Aenderung | Datei | Was genau |
|-----------|-------|-----------|
| System-Nachrichten filtern | Frontend/chat.html | JS: Nachrichten mit `from=system` nach Tag filtern. Nur Tags mit `to_user=true` in der Routing-Config anzeigen. Rest: nur in System-Log, nicht im Chat. |
| Severity-Badge | Frontend/chat.html | Optional: CRITICAL rot, HIGH orange, MEDIUM grau, LOW/INFO versteckt |

---

## C) Testmatrix

### Test 1: Heartbeat-Intervall

| Schritt | Aktion | Erwartung |
|---------|--------|-----------|
| 1 | `_HEARTBEAT_PROMPT_INTERVAL = 900` setzen | — |
| 2 | Server restarten | — |
| 3 | 20 Minuten warten | — |
| 4 | `grep HEARTBEAT_CHECK bridge.jsonl \| grep "$(date +%Y-%m-%d)" \| wc -l` | Max 2 pro Agent (statt 4) |
| 5 | Agent antwortet auf HEARTBEAT_CHECK | Agent-Funktion nicht beeintraechtigt |

### Test 2: CONTEXT RESTORE Kompression

| Schritt | Aktion | Erwartung |
|---------|--------|-----------|
| 1 | CONTEXT RESTORE Format aendern (nur CONTEXT_BRIDGE.md Felder) | — |
| 2 | Server restarten | — |
| 3 | Agent registriert sich | [CONTEXT RESTORE] Nachricht ~1KB (statt ~8KB) |
| 4 | Agent liest SOUL.md + MEMORY.md von Disk | Agent hat vollen Kontext |
| 5 | `wc -c` auf CONTEXT RESTORE Nachrichten | < 1500 Bytes pro Nachricht |

### Test 3: Routing-Config WARN/RECOVERY/ONLINE

| Schritt | Aktion | Erwartung |
|---------|--------|-----------|
| 1 | system_message_routing.json deployed | — |
| 2 | Watcher liest Config | Log: "routing config loaded" |
| 3 | Agent geht offline → online | [ONLINE] in bridge.jsonl JA, in Ordo-tmux NEIN |
| 4 | Health-Monitor meldet RECOVERY | [RECOVERY] in bridge.jsonl JA, in Agent-tmux NEIN |
| 5 | Agent CRASH | [CRASH] in bridge.jsonl JA, in Ordo-tmux JA, in User-Chat JA |
| 6 | APPROVAL Request | In User-Chat JA, in Agent-tmux JA |

### Test 4: Frontend-Suppression

| Schritt | Aktion | Erwartung |
|---------|--------|-----------|
| 1 | Frontend-Filter deployed | — |
| 2 | System sendet [RECOVERY] | NICHT im User-Chat sichtbar |
| 3 | System sendet [CRASH] | IM User-Chat sichtbar (rot) |
| 4 | System sendet [TASK DONE] | IM User-Chat sichtbar |
| 5 | System sendet [HEARTBEAT_CHECK] | NICHT im User-Chat sichtbar |

---

## Implementierungs-Reihenfolge

| Prio | Was | Aufwand | Risiko |
|------|-----|---------|--------|
| 1 | Heartbeat 300→900s | 1 Zeile | Keins |
| 2 | CONTEXT RESTORE komprimieren | ~30 Zeilen server.py | Gering |
| 3 | system_message_routing.json + Watcher-Integration | ~100 Zeilen | Mittel |
| 4 | Frontend-Suppression | ~50 Zeilen JS | Gering |

Prio 1+2 sind Quick Wins (Backend-Only, kein Watcher/Frontend-Umbau noetig).
Prio 3+4 sind das nachhaltige Routing-System.
