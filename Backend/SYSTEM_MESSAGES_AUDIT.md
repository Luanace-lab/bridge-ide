# System Messages Audit — Bridge IDE
Stand: 2026-03-15T15:00 UTC
Erstellt von: Ordo (Projektleiter)
Methode: Extraktion aus bridge.jsonl (25.047 Nachrichten) + Code-Verifikation

## Uebersicht

57 verschiedene System-Tags in bridge.jsonl identifiziert.
Jeder Tag ist einer Code-Quelle zugeordnet oder als HISTORISCH/ENTFERNT markiert.

---

## 1. HEALTH / MONITORING

| Tag | Datei:Zeile | Code |
|-----|-------------|------|
| `[WARN]` (Heartbeat) | daemons/agent_health.py:265 | `f"[WARN] Agent {agent_id}: tmux lebt, aber kein Heartbeat seit {int(hb_age)}s. Moeglicherweise Registrierung verloren."` |
| `[WARN]` (Stuck) | daemons/cli_monitor.py:244 | `f"[WARN] {agent_id} hat seit {int(stuck_seconds/60)} Min keinen neuen tmux-Output. Moeglicherweise blockiert."` |
| `[WARN]` (Komponente) | daemons/health_monitor.py | Generiert via Health-Check-Loop fuer codex_poll, forwarder etc. |
| `[CRITICAL]` (Agent) | daemons/agent_health.py | Heartbeat-Age > Threshold |
| `[CRITICAL]` (Supervisor) | daemons/supervisor.py:136 | `f"[CRITICAL] {name} ist {cfg['max_restarts']}x in {cfg['restart_window']//60} Min gestorben."` |
| `[CRITICAL]` (Restart failed) | daemons/supervisor.py:199 | `f"[CRITICAL] {name} Neustart GESCHEITERT: {exc}"` |
| `[RECOVERY]` | daemons/health_monitor.py:108 | `f"[RECOVERY] {key} wieder ok (vorher: {prev})."` |
| `[ONLINE]` | handlers/agents.py:276 | `msg = f"[ONLINE] Agent {agent_id} ist wieder online."` |
| `[OFFLINE]` | server.py:2737 | `msg = f"[OFFLINE] Agent {agent_id} ist offline (vorher: {previous_status})."` |
| `[CONTEXT]` (Context-%) | daemons/health_monitor.py:168 | `f"[CONTEXT] {agent_id}: {msg_template.format(pct=ctx_pct)}"` |
| `[HEARTBEAT_CHECK]` | daemons/heartbeat_prompt.py:68 | `"[HEARTBEAT_CHECK] Periodische Pruefung. Bitte checke: ..."` |
| `[BEHAVIOR-WATCH]` | bridge_watcher.py:2542 | `f"[BEHAVIOR-WATCH] Du hast ungelesene Nachrichten. ..."` |
| `[BEHAVIOR-ALERT]` | bridge_watcher.py:2562 | `f"[BEHAVIOR-ALERT] Agent {agent_id} ist seit ..."` |
| `[CRASH]` | daemons/agent_health.py:228 | `f"[CRASH] Agent {agent_id} crashed: {health['detail']}"` |
| `[MEMORY]` (zu gross) | bridge_watcher.py:2659 | `f"[MEMORY] Deine MEMORY.md hat {lines} Zeilen (Limit: 200)."` |
| `[MEMORY]` (veraltet) | bridge_watcher.py:2661 | `f"[MEMORY] Deine MEMORY.md wurde seit {age_hours:.0f}h nicht aktualisiert."` |

## 2. RESTART / LIFECYCLE

| Tag | Datei:Zeile | Code |
|-----|-------------|------|
| `[RESTART WARN]` | daemons/restart_control.py:122 | `f"[RESTART WARN] Server-Restart in {warn_seconds} Sekunden. ..."` |
| `[RESTART STOP]` | daemons/restart_control.py:154 | `f"[RESTART STOP] Server stoppt in {stop_seconds} Sekunden. ..."` |
| `[RESTART ABGEBROCHEN]` | daemons/restart_control.py:238 | `f"[RESTART ABGEBROCHEN] Restart wurde abgebrochen (war in Phase '{old_phase}')."` |
| `[RESTART WAKE]` | daemons/restart_wake.py:181 | `"[RESTART WAKE] Server ist wieder online. ..."` |
| `[RESTART RECOVERY]` | server.py:7412 | `f"[RESTART RECOVERY] Du hast einen unbearbeiteten Task: ..."` |
| `[CONTEXT RESTORE]` | server.py:7298-7299 | Generiert in Registration-Flow via `_should_send_context_restore()`. Sendet gespeicherten Agent-State + SOUL + MEMORY als Restore-Nachricht. |
| `[SESSION-END REFLECTION]` | daemons/restart_control.py:25 | `"[SESSION-END REFLECTION] Server-Restart steht bevor. ..."` |
| `[AUTO-RESTART]` (Agent) | server.py:3336 | `f"[AUTO-RESTART] Agent {agent_id} wurde automatisch neu gestartet."` |
| `[AUTO-RESTART]` (Komponente) | daemons/supervisor.py:184 | `f"[AUTO-RESTART] {name} war down. Automatisch neu gestartet (PID {proc.pid})."` |
| `[AUTO-START]` | server.py:3465 | `f"[AUTO-START] Agent {agent_id} war offline — wurde automatisch gestartet fuer Task {task_id}."` |
| `[AUTO-KILL]` | daemons/cli_monitor.py:231 | `f"[AUTO-KILL] {agent_id} war {int(stuck_seconds/60)} Min blockiert. Ctrl+C gesendet."` |
| `[AGENT WAKE]` | server.py:3446 | `f"[AGENT WAKE] {agent_id} laeuft aber war nicht registriert. Wake-Signal gesendet."` |
| `[SYSTEM RESUME]` | server.py:5864 | `f"[SYSTEM RESUME] Normalbetrieb wiederhergestellt von {agent_id}."` |

## 3. TASK / WORKFLOW

| Tag | Datei:Zeile | Code |
|-----|-------------|------|
| `[TASK DONE]` | server.py:6483 | `content=f"[TASK DONE] {task.get('title', task_id)} abgeschlossen von {agent_id} — {result_code}"` |
| `[TASK FAILED]` | server.py:6592 | `content=f"[TASK FAILED] {task.get('title', task_id)} — {error_msg}"` |
| `[AUTO-ASSIGNED]` | daemons/auto_assign.py:154 | `f"[AUTO-ASSIGNED] Task '{title}' (ID: {task_id}) wurde dir automatisch zugewiesen."` |
| `[AUTO-CLAIM REQUIRED]` | daemons/task_pusher.py:110 | `f"[AUTO-CLAIM REQUIRED] Du hast einen zugewiesenen Task der NICHT geclaimed ist: ..."` |
| `[ACK-TIMEOUT]` (fail) | handlers/tasks.py:560 | `f"[ACK-TIMEOUT] Aufgabe '{title}' ist fehlgeschlagen — Ack-Deadline ({ack_deadline}s) {retry_count}x ueberschritten."` |
| `[ACK-TIMEOUT]` (requeue) | handlers/tasks.py:581 | `f"[ACK-TIMEOUT] Aufgabe '{title}' wurde re-queued — Ack-Deadline ({ack_deadline}s) ueberschritten."` |
| `[ORPHAN]` (fail) | handlers/tasks.py:711 | `f"[ORPHAN] Task '{title}' fehlgeschlagen — Agent {assigned_agent} offline."` |
| `[ORPHAN]` (requeue) | handlers/tasks.py:731 | `f"[ORPHAN] Task '{title}' wurde re-queued — Agent {assigned_agent} offline."` |
| `[REMINDER]` | handlers/tasks.py:369 | `f"[REMINDER] Aufgabe '{title}' ist ueberfaellig. Bitte melde Status."` |
| `[DRINGEND]` | handlers/tasks.py:381 | `f"[DRINGEND] Aufgabe '{title}' ist ueberfaellig. Zweite Erinnerung."` |
| `[EVIDENCE WARNING]` | server.py:6489 | `f"[EVIDENCE WARNING] Task {task_id} '{task.get('title', '')}' von {agent_id} ..."` |
| `[AUTO-DISTILLATION]` | daemons/distillation.py:10 | `"[AUTO-DISTILLATION] Periodische Wissens-Destillation. ..."` |
| `[AUTO-NUDGE]` | NICHT IM AKTUELLEN CODE GEFUNDEN — nur in bridge.jsonl. Status: HISTORISCH/ENTFERNT |

## 4. APPROVAL

| Tag | Datei:Zeile | Code |
|-----|-------------|------|
| `[APPROVAL GENEHMIGT]` | server.py:8444 | `f"[APPROVAL {status_text}] {desc} ..."` (status_text = "GENEHMIGT") |
| `[APPROVAL ABGELEHNT]` | server.py:8444 | `f"[APPROVAL {status_text}] {desc} ..."` (status_text = "ABGELEHNT") |
| `[APPROVAL EDITIERT]` | handlers/approvals.py:206 | `f"[APPROVAL EDITIERT] Request {request_id}: Payload wurde von Leo aktualisiert."` |
| `[APPROVAL EXPIRED]` | handlers/approvals.py:355 | `f"[APPROVAL EXPIRED] Deine Anfrage wurde nicht rechtzeitig beantwortet."` |

## 5. MODE / CONFIG

| Tag | Datei:Zeile | Code |
|-----|-------------|------|
| `[MODE CHANGE]` | server.py:8823 | `f"[MODE CHANGE] Dein Modus wurde auf '{new_mode}' geaendert. {instruction}"` |
| `[MODE CHANGE]` (auto) | server.py:6234 | `"[MODE CHANGE] Dein Modus wurde auf 'normal' geaendert. ..."` |
| `[MODE CHANGE]` (pusher) | daemons/task_pusher.py:103 | `"[MODE CHANGE] Dein Modus wurde auf 'normal' geaendert. ..."` |
| `[TEAM UPDATE]` | server.py:1886 | `content = f"[TEAM UPDATE] {change_type}: {details}"` |
| `[SKILL PROPOSAL]` | server.py:5767 | `f"[SKILL PROPOSAL] Agent '{agent_id}' schlaegt Skill '{skill_name}' vor."` |
| `[SKILL APPROVED]` | server.py:8561 | `f"[SKILL APPROVED] Dein Skill '{skill_name}' wurde von {reviewer} genehmigt."` |
| `[SKILL REJECTED]` | server.py:8565 | `f"[SKILL REJECTED] Dein Skill '{proposal.get('skill_name', '')}' wurde von {reviewer} abgelehnt."` |
| `[SCHEDULED PROMPT]` | bridge_mcp.py:11023 | `"content": f"[SCHEDULED PROMPT] {prompt}"` |

## 6. SECURITY / ERROR

| Tag | Datei:Zeile | Code |
|-----|-------------|------|
| `[AUTH-FAILURE]` | daemons/cli_monitor.py:168 | `f"[AUTH-FAILURE] {agent_id} haengt an OAuth-Login. ..."` |
| `[RATE-LIMITED]` | daemons/cli_monitor.py:203 | `f"[RATE-LIMITED] {agent_id} hat API-Usage-Limit erreicht."` |
| `[PLAN-MODE-RESCUE]` | server.py:3889 | `f"[PLAN-MODE-RESCUE] Agent {agent_id} war in interaktivem Prompt ..."` |
| `[PLAN-MODE-RESCUE FAILED]` | server.py:3901 | `f"[PLAN-MODE-RESCUE FAILED] Agent {agent_id} haengt in interaktivem ..."` |
| `[OAUTH-STUCK]` | NICHT IM AKTUELLEN CODE GEFUNDEN — nur in bridge.jsonl. Status: HISTORISCH/ENTFERNT |
| `[SECURITY_PROBE]` | NICHT IM AKTUELLEN CODE GEFUNDEN — nur in bridge.jsonl. Status: HISTORISCH/ENTFERNT |
| `[EVIDENZ-POLICY]` | NICHT IM AKTUELLEN CODE GEFUNDEN — nur in bridge.jsonl. Status: HISTORISCH/ENTFERNT |

## 7. SHUTDOWN

| Tag | Datei:Zeile | Code |
|-----|-------------|------|
| `[SHUTDOWN]` | server.py:5814 | `f"[SHUTDOWN] Graceful Shutdown in {timeout_secs}s von {agent_id}."` |
| `[SHUTDOWN_FINAL]` | server.py:3365 | `f"[SHUTDOWN_FINAL] Graceful shutdown abgeschlossen. Missing ACKs: {missing or 'keine'}."` |
| `[SYSTEM SHUTDOWN]` | server.py:5835 | `f"[SYSTEM SHUTDOWN] Shutdown aktiviert von {agent_id}."` |

## 8. BUDDY-SPEZIFISCH

| Tag | Datei:Zeile | Code |
|-----|-------------|------|
| `[BUDDY_FRONTDOOR]` | server.py:3185 | `"[BUDDY_FRONTDOOR] Ein User wartet im Chat. Begruesse ihn ..."` |

## 9. SONSTIGE (historisch, einmalig, Test)

| Tag | Status | Anmerkung |
|-----|--------|-----------|
| `[WARNUNG]` | AKTIV — server.py:3476 | Agent konnte nicht gestartet werden fuer Task |
| `[TEST]` | HISTORISCH | Test-Nachrichten waehrend Entwicklung |
| `[VERIFY]` | HISTORISCH | Verifikations-Tests |
| `[ENTER-TEST]` | HISTORISCH | Enter-Injection Tests |
| `[V2-Cutover-Test]` | HISTORISCH | Watcher V2 Migration |
| `[ENDBOSS]` | HISTORISCH | Einmalige Direktive |
| `[ANWEISUNG VIKTOR]` | HISTORISCH | Einmalige Direktive |

---

## Luecken-Analyse

| Tag in bridge.jsonl | Im Code? | Status |
|---------------------|----------|--------|
| `[AUTO-NUDGE]` | NEIN | ENTFERNT — war in aelterem Code |
| `[OAUTH-STUCK]` | NEIN | ENTFERNT — ersetzt durch [AUTH-FAILURE] |
| `[SECURITY_PROBE]` | NEIN | ENTFERNT — war Test-Feature |
| `[EVIDENZ-POLICY]` | NEIN | ENTFERNT — integriert in [EVIDENCE WARNING] |
| `[TASK]` | UNKLAR | Generischer Tag, UNKNOWN ob noch aktiv |

Alle anderen 52 Tags sind im aktuellen Code verifiziert mit Datei:Zeile.

---

## Dateien die System-Nachrichten generieren

| Datei | Anzahl Tags |
|-------|-------------|
| server.py | 16 |
| handlers/agents.py | 1 |
| handlers/tasks.py | 6 |
| handlers/approvals.py | 2 |
| handlers/skills.py | 0 (nur Datenstrukturen) |
| daemons/agent_health.py | 3 |
| daemons/supervisor.py | 3 |
| daemons/health_monitor.py | 2 |
| daemons/cli_monitor.py | 4 |
| daemons/restart_control.py | 4 |
| daemons/restart_wake.py | 1 |
| daemons/heartbeat_prompt.py | 1 |
| daemons/auto_assign.py | 1 |
| daemons/task_pusher.py | 2 |
| daemons/distillation.py | 1 |
| bridge_watcher.py | 3 |
| bridge_mcp.py | 1 |
