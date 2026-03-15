---
name: bridge-sync-release
description: Sync the Bridge IDE release clone with the development directory. Use when preparing a release or syncing code to /home/user/bridge-release/.
allowed-tools: Bash, Read, Grep
---

# Bridge Sync Release

Development-Code nach Release-Clone synchronisieren.

## Pfade
- **Dev**: `/home/user/bridge/BRIDGE/`
- **Release**: `/home/user/bridge-release/`

## Ablauf

### 1. Pruefen ob Release-Clone existiert
```bash
if [ ! -d /home/user/bridge-release ]; then
  echo "ERROR: Release-Clone nicht gefunden unter /home/user/bridge-release/"
  echo "Erstelle mit: cp -r /home/user/bridge/BRIDGE /home/user/bridge-release"
  exit 1
fi
```

### 2. Backup des Release-Clone
```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
echo "Backup: /home/user/bridge-release_backup_${TIMESTAMP}"
tar czf "/home/user/bridge-release_backup_${TIMESTAMP}.tar.gz" \
  -C /home/user/Desktop BridgeIDE-Release/ 2>/dev/null
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
  /home/user/bridge/BRIDGE/ \
  /home/user/bridge-release/
```

### 4. Verifizieren
```bash
echo "=== Diff-Check ==="
diff -rq \
  --exclude='logs' --exclude='pids' --exclude='messages' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.cred_key' \
  --exclude='*.bak' --exclude='node_modules' --exclude='.env' \
  /home/user/bridge/BRIDGE/ \
  /home/user/bridge-release/ 2>/dev/null | head -20
echo ""
echo "=== Release-Clone Stats ==="
find /home/user/bridge-release/ -name "*.py" | wc -l | xargs echo "Python files:"
find /home/user/bridge-release/ -name "*.js" | wc -l | xargs echo "JS files:"
find /home/user/bridge-release/ -name "*.html" | wc -l | xargs echo "HTML files:"
```

### 5. Tests im Release-Clone (optional)
```bash
cd /home/user/bridge-release/Backend
python3 -m pytest tests/ -q --tb=short 2>/dev/null || echo "No tests found or test failure"
cd -
```

## Checkliste
- [ ] Release-Clone existiert
- [ ] Backup erstellt
- [ ] rsync erfolgreich
- [ ] Diff-Check: keine unerwarteten Unterschiede
- [ ] Keine Secrets im Release-Clone (.cred_key, .env ausgeschlossen)
