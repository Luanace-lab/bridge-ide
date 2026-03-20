---
name: bridge-status
description: Show Bridge IDE system status — health, active agents, open tasks, and server info. Use when checking system health or asking "what's running?".
allowed-tools: Bash, Read
---

# Bridge Status

Vollstaendiger System-Ueberblick in einem Aufruf.

## Ausfuehren

### 1. Server Health
```bash
curl -s http://127.0.0.1:9111/health | python3 -m json.tool
```

### 2. Aktive Agents
```bash
curl -s http://127.0.0.1:9111/agents | python3 -c "
import json, sys
data = json.load(sys.stdin)
agents = data.get('agents', [])
online = [a for a in agents if a.get('online')]
offline = [a for a in agents if not a.get('online') and a.get('active', True)]
print('=== ONLINE AGENTS ===')
for a in online:
    engine = a.get('engine', '?')
    print(f\"  {a['id']:20s} {a.get('role',''):40s} [{engine}]\")
print(f\"\n  Total online: {len(online)}\")
if offline:
    print('\n=== OFFLINE (aber active in team.json) ===')
    for a in offline:
        print(f\"  {a['id']:20s} {a.get('role','')}\")
"
```

### 3. Agent-Aktivitaet
```bash
curl -s http://127.0.0.1:9111/activity | python3 -c "
import json, sys
data = json.load(sys.stdin)
for act in data.get('activities', []):
    idle = ' [IDLE]' if act.get('idle') else ''
    print(f\"  {act.get('agent_id','?'):20s} {act.get('action',''):15s} {act.get('target','')}{idle}\")
"
```

### 4. Offene Tasks
```bash
curl -s 'http://127.0.0.1:9111/task/queue?state=created' | python3 -c "
import json, sys
data = json.load(sys.stdin)
tasks = data.get('tasks', [])
print(f'=== OFFENE TASKS ({len(tasks)}) ===')
for t in tasks:
    assigned = t.get('assigned_to', 'unassigned')
    print(f\"  [{t.get('priority','?')}] {t['title'][:60]:60s} → {assigned}\")
"
```

### 5. Server-Info
```bash
curl -s http://127.0.0.1:9111/status | python3 -c "
import json, sys
data = json.load(sys.stdin)
uptime = data.get('uptime_seconds', 0)
hours = int(uptime // 3600)
mins = int((uptime % 3600) // 60)
print(f\"Server: {data.get('status','?')} | Port: {data.get('port','?')} | Uptime: {hours}h {mins}m | Messages: {data.get('messages_total', 0)}\")
"
```

## Output-Format

Der Skill liefert eine strukturierte Zusammenfassung:
```
Server: running | Port: 9111 | Uptime: 2h 30m | Messages: 1847
Online: 5 agents | Offline: 2 agents | Tasks: 3 open
```
