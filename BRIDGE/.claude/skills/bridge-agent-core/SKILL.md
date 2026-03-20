---
name: bridge-agent-core
description: Core skill for all Bridge IDE agents. This skill should be used for bridge communication, task management, agent coordination, and understanding the Bridge IDE platform. Covers bridge_register, bridge_send/receive, task lifecycle, approval gates, and team coordination patterns.
allowed-tools: Read, Bash, Grep
---

# Bridge Agent Core

Grundwissen fuer jeden Bridge IDE Agent.

## Bridge Kommunikation

### Registrierung (PFLICHT nach Start)
```
bridge_register(agent_id="<deine_id>", role="<deine_rolle>")
```
Startet WebSocket-Listener + automatischen Heartbeat (30s).

### Nachrichten
```
bridge_send(to="<empfaenger>", content="<nachricht>")
bridge_receive()  # Gepufferte Nachrichten abholen
```

### Routing
| Empfaenger | Wer | Wofuer |
|-----------|-----|--------|
| user | Owner | Entscheidungen, Freigaben |
| viktor | Systemarchitekt | Technik, Reviews, Architektur |
| nova | Kreativ-Strategin | Vision, UX, Strategie |
| ordo / manager | Projektleiter | Koordination, Auftraege |
| backend | Senior Backend Dev | server.py, API, MCP |
| frontend | Senior Frontend Dev | UI, CSS, Client-JS |
| kai | Real-World Integration | Externe Dienste, Accounts |
| all | Broadcast | NUR fuer kritische Team-Info |

### Broadcast-Regeln
VERBOTEN als Broadcast: "Ich bin online", Status ohne Informationswert, Wiederholungen.
NUR: Kritische Bugs, Blocker, fertige Ergebnisse die alle betreffen.

## Task-System

### Task abholen
```
bridge_task_queue(state='created')  # Offene Tasks
bridge_task_claim(task_id)          # Task uebernehmen
bridge_task_checkin(task_id, note)  # Heartbeat waehrend Arbeit
bridge_task_done(task_id, result)   # Fertig melden
bridge_task_fail(task_id, reason)   # Gescheitert melden
```

### Task-Lifecycle
created → claimed → in_progress → done/failed

### Ergebnis melden
1. `bridge_task_done` — System benachrichtigt Creator
2. `bridge_send` an Creator — ausfuehrlicher Bericht
3. NICHT an Owner/user — es sei denn der Owner hat den Task erstellt

## Approval Gates

Fuer irreversible externe Aktionen (Email senden, Geld ausgeben, Account loeschen):
```
bridge_approval_request(action, details, risk_level)
bridge_approval_wait(request_id, timeout=300)
```
Risk Levels: low, medium, high. Timeout: 5 Min default.

## Guardrails (NICHT VERHANDELBAR)

1. Keine Dateien ausserhalb deines Bereichs aendern
2. Backup vor jeder Aenderung: `cp datei datei.bak`
3. Keine Secrets in Code/Logs
4. Keine Annahmen — UNKNOWN markieren, verifizieren
5. Evidenz-basiert — keine Behauptungen ohne Beleg
6. bridge_receive nach JEDER Aufgabe
