---
name: bridge-sync-release
description: Sync the Bridge IDE release clone with the development directory. Use when preparing a release or syncing code to /home/leo/Desktop/BridgeIDE-Release/.
allowed-tools: Bash, Read, Grep
---

# Bridge Sync Release

Development-Code nach Release-Clone synchronisieren.

## Pfade
- **Dev**: `/home/leo/Desktop/CC/BRIDGE/`
- **Release**: `/home/leo/Desktop/BridgeIDE-Release/`

## Ablauf

### 1. Pruefen ob Release-Clone existiert
```bash
if [ ! -d /home/leo/Desktop/BridgeIDE-Release ]; then
  echo "ERROR: Release-Clone nicht gefunden unter /home/leo/Desktop/BridgeIDE-Release/"
  echo "Erstelle mit: cp -r /home/leo/Desktop/CC/BRIDGE /home/leo/Desktop/BridgeIDE-Release"
  exit 1
fi
```

### 2. Backup des Release-Clone
```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
echo "Backup: /home/leo/Desktop/BridgeIDE-Release_backup_${TIMESTAMP}"
tar czf "/home/leo/Desktop/BridgeIDE-Release_backup_${TIMESTAMP}.tar.gz" \
  -C /home/leo/Desktop BridgeIDE-Release/ 2>/dev/null
echo "Backup erstellt."
```

### 3. Sync (rsync, ohne lokale Config/Logs/PIDs)
```bash
rsync -av --delete \
  --exclude='logs/' \
  --exclude='pids/' \
  --exclude='messages/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.cred_key' \
  --exclude='*.bak' \
  --exclude='node_modules/' \
  --exclude='.env' \
  /home/leo/Desktop/CC/BRIDGE/ \
  /home/leo/Desktop/BridgeIDE-Release/
```

### 4. Verifizieren
```bash
echo "=== Diff-Check ==="
diff -rq \
  --exclude='logs' --exclude='pids' --exclude='messages' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.cred_key' \
  --exclude='*.bak' --exclude='node_modules' --exclude='.env' \
  /home/leo/Desktop/CC/BRIDGE/ \
  /home/leo/Desktop/BridgeIDE-Release/ 2>/dev/null | head -20
echo ""
echo "=== Release-Clone Stats ==="
find /home/leo/Desktop/BridgeIDE-Release/ -name "*.py" | wc -l | xargs echo "Python files:"
find /home/leo/Desktop/BridgeIDE-Release/ -name "*.js" | wc -l | xargs echo "JS files:"
find /home/leo/Desktop/BridgeIDE-Release/ -name "*.html" | wc -l | xargs echo "HTML files:"
```

### 5. Tests im Release-Clone (optional)
```bash
cd /home/leo/Desktop/BridgeIDE-Release/Backend
python3 -m pytest tests/ -q --tb=short 2>/dev/null || echo "No tests found or test failure"
cd -
```

## Checkliste
- [ ] Release-Clone existiert
- [ ] Backup erstellt
- [ ] rsync erfolgreich
- [ ] Diff-Check: keine unerwarteten Unterschiede
- [ ] Keine Secrets im Release-Clone (.cred_key, .env ausgeschlossen)
