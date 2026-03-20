---
name: bridge-deploy
description: Deploy Bridge IDE — Server-Restart mit Health-Check und Agent-Benachrichtigung. Use when deploying changes, restarting the server, or applying backend updates.
allowed-tools: Bash, Read, Grep
---

# Bridge Deploy

Server-Restart mit koordinierter Agent-Benachrichtigung und Health-Verification.

## Ablauf

### 1. Agents warnen (30s Vorlauf)
```bash
curl -s -X POST http://127.0.0.1:9111/send \
  -H "Content-Type: application/json" \
  -d '{"from":"system","to":"all","content":"[DEPLOY] Server-Restart in 30s. CONTEXT_BRIDGE.md jetzt sichern."}'
```

### 2. Warten (30 Sekunden)
Agents brauchen Zeit fuer CONTEXT_BRIDGE.md Updates.
```bash
sleep 30
```

### 3. Server-Restart ausfuehren
**Option A: Graceful Restart (bevorzugt)**
```bash
curl -s -X POST http://127.0.0.1:9111/server/restart \
  -H "Content-Type: application/json" \
  -d '{"reason":"deploy","from":"viktor"}'
```

**Option B: Force Restart (nur bei Blockade)**
```bash
curl -s -X POST http://127.0.0.1:9111/server/restart/force \
  -H "Content-Type: application/json" \
  -d '{"reason":"deploy-force","from":"viktor"}'
```

### 4. Restart-Status pruefen
```bash
curl -s http://127.0.0.1:9111/server/restart-status | python3 -m json.tool
```

### 5. Health-Check (nach Restart)
Warte bis Server wieder erreichbar ist, dann:
```bash
for i in $(seq 1 10); do
  if curl -sf http://127.0.0.1:9111/health > /dev/null 2>&1; then
    echo "Server healthy after attempt $i"
    curl -s http://127.0.0.1:9111/health | python3 -m json.tool
    break
  fi
  echo "Attempt $i: waiting..."
  sleep 3
done
```

### 6. Agent-Status verifizieren
```bash
curl -s http://127.0.0.1:9111/agents | python3 -c "
import json, sys
data = json.load(sys.stdin)
agents = data.get('agents', [])
for a in agents:
    status = 'ONLINE' if a.get('online') else 'OFFLINE'
    print(f\"  {a['id']:20s} {status:8s} {a.get('role','')}\")
print(f\"\nTotal: {len(agents)} agents\")
"
```

### 7. Erfolg melden
```bash
curl -s -X POST http://127.0.0.1:9111/send \
  -H "Content-Type: application/json" \
  -d '{"from":"system","to":"all","content":"[DEPLOY] Server-Restart abgeschlossen. Health: OK."}'
```

## Checkliste
- [ ] Agents gewarnt (30s Vorlauf)
- [ ] Server neugestartet
- [ ] Health-Check bestanden
- [ ] Agents wieder online
- [ ] Erfolg gemeldet

## Wichtig
- KEIN Force-Restart ohne vorherige Warnung
- Health-Check MUSS bestanden werden
- Bei Fehler: `curl -s http://127.0.0.1:9111/server/restart/cancel` zum Abbrechen
