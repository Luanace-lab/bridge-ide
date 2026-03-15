---
name: bridge-agent-restart
description: Restart a Bridge IDE agent by ID. Use when an agent is stuck, crashed, or needs to be restarted. Accepts agent ID as argument (e.g. /agent-restart backend).
allowed-tools: Bash, Read
---

# Bridge Agent Restart

Agent stoppen und neu starten. Argument: Agent-ID (z.B. `backend`, `frontend`, `kai`).

## Ablauf

### 1. Agent-Status pruefen
```bash
AGENT_ID="${1:-}"
if [ -z "$AGENT_ID" ]; then
  echo "Usage: /agent-restart <agent_id>"
  echo "Available agents:"
  curl -s http://127.0.0.1:9111/agents | python3 -c "
import json, sys
for a in json.load(sys.stdin).get('agents', []):
    status = 'ONLINE' if a.get('online') else 'OFFLINE'
    print(f\"  {a['id']:20s} {status}\")
"
  exit 1
fi
curl -s "http://127.0.0.1:9111/agents?source=combined" | python3 -c "
import json, sys
data = json.load(sys.stdin)
agent = next((a for a in data.get('agents',[]) if a['id'] == '$AGENT_ID'), None)
if agent:
    print(f\"Agent: {agent['id']}\")
    print(f\"Status: {'ONLINE' if agent.get('online') else 'OFFLINE'}\")
    print(f\"Role: {agent.get('role','?')}\")
    print(f\"Engine: {agent.get('engine','?')}\")
else:
    print(f'Agent $AGENT_ID not found')
"
```

### 2. tmux-Session pruefen
```bash
tmux capture-pane -t "$AGENT_ID" -p 2>/dev/null | tail -5
```

Moegliche Zustaende:
- **Bash-Prompt ($)**: Agent ist tot → Kill + Restart
- **"esc to interrupt"**: Agent arbeitet → Nur restart wenn noetig
- **OAuth/Enter-Prompt**: Agent haengt → `tmux send-keys -t "$AGENT_ID" Enter`

### 3. Restart via API
```bash
curl -s -X POST "http://127.0.0.1:9111/agents/$AGENT_ID/restart" \
  -H "Content-Type: application/json" \
  -d '{"from":"viktor"}' | python3 -m json.tool
```

### 4. Alternativ: Start (wenn nicht laeuft)
```bash
curl -s -X POST "http://127.0.0.1:9111/agents/$AGENT_ID/start" \
  -H "Content-Type: application/json" \
  -d '{"from":"viktor"}' | python3 -m json.tool
```

### 5. Verifizieren (nach 15s warten)
```bash
sleep 15
tmux capture-pane -t "$AGENT_ID" -p 2>/dev/null | tail -3
curl -s http://127.0.0.1:9111/agents | python3 -c "
import json, sys
agent = next((a for a in json.load(sys.stdin).get('agents',[]) if a['id'] == '$AGENT_ID'), None)
if agent:
    print(f\"{agent['id']}: {'ONLINE' if agent.get('online') else 'OFFLINE'}\")
"
```

## Sonderfaelle

### Agent haengt bei OAuth
```bash
tmux send-keys -t "$AGENT_ID" Enter
sleep 5
tmux capture-pane -t "$AGENT_ID" -p | tail -3
```

### Agent komplett tot (tmux Session weg)
```bash
curl -s -X POST "http://127.0.0.1:9111/agents/$AGENT_ID/start" \
  -H "Content-Type: application/json" \
  -d '{"from":"viktor"}'
```

## Wichtig
- Vor Restart: tmux-Status pruefen (Agent koennte arbeiten)
- Nach Restart: 15s warten, dann verifizieren
- MCP-Prozesse laden sich bei Agent-Restart automatisch neu
