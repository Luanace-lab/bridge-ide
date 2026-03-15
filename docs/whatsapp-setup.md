# WhatsApp Setup

Dieser Pfad beschreibt den kleinsten reproduzierbaren Bootstrap fuer die WhatsApp-Integration in dieser Working Copy. Ziel ist kein lokaler Sonderfall, sondern ein fremder Rechner mit expliziter Konfiguration.

## Scope

Diese Integration besteht aus drei getrennten Teilen:

- Go Bridge mit HTTP API auf `http://localhost:8080`
- Bridge-Backend mit MCP-Tools in `Backend/bridge_mcp.py`
- Inbound-Watcher in `Backend/whatsapp_watcher.py`

Die BRIDGE wrappt die externe WhatsApp-Infrastruktur. Die externe Bridge und ihre SQLite-DB bleiben die operative SoT fuer WhatsApp-Nachrichten.

## Voraussetzungen

- Python 3.10+
- `tmux`
- laufende BRIDGE (`Backend/server.py` oder `Backend/start_platform.sh`)
- externe WhatsApp-Go-Bridge mit QR-Pairing
- SQLite-Message-Store der Go-Bridge
- optional fuer Voice:
  - `~/.config/bridge/whatsapp_bridge_token` oder `WHATSAPP_API_TOKEN`
  - ElevenLabs-Key fuer `bridge_whatsapp_voice`
  - Whisper/ffmpeg fuer STT im Watcher

## Kanonische Konfiguration

1. Lege die WhatsApp-Konfiguration ausserhalb des Repos an:

```bash
mkdir -p ~/.config/bridge
cp Backend/whatsapp_config.example.json ~/.config/bridge/whatsapp_config.json
```

2. Passe mindestens diese Werte an:

- `watch_group_jid`: Gruppen-JID fuer eingehende Nachrichten im Watcher
- `sender_filter`: optionaler Senderfilter fuer denselben Chat
- `read_whitelist`: JIDs fuer `bridge_whatsapp_read`
- `send_whitelist`: JIDs fuer `bridge_whatsapp_send` und `bridge_whatsapp_voice`
- `approval_whitelist`: JIDs, die ohne Approval direkt gesendet werden duerfen
- `contacts`: optionale Aliasnamen fuer Tools wie `bridge_whatsapp_send(to="owner")`

3. Lege die relevanten Variablen in `Backend/.env` oder deiner Shell fest:

```bash
WHATSAPP_CONFIG_PATH=~/.config/bridge/whatsapp_config.json
WHATSAPP_DB_PATH=~/.config/bridge/whatsapp-bridge/store/messages.db
WHATSAPP_BRIDGE_URL=http://localhost:8080
WHATSAPP_GROUP_JID=120363000000000000@g.us
WHATSAPP_API_TOKEN=
WHATSAPP_WEBHOOK_ACTIVE=0
```

Hinweis: `WHATSAPP_GROUP_JID` kann alternativ aus `watch_group_jid` in der Config kommen. Fuer fremde Rechner sollte die Variable oder die externe Config bewusst gesetzt werden. Keine repo-lokalen Defaults voraussetzen.

## Startreihenfolge

1. Externe WhatsApp-Go-Bridge starten und QR-Pairing abschliessen.
2. Sicherstellen, dass die SQLite-DB existiert:

```bash
test -f ~/.config/bridge/whatsapp-bridge/store/messages.db
```

3. BRIDGE starten:

```bash
cd Backend
./start_platform.sh
```

Der Startpfad startet `whatsapp_watcher` nur noch, wenn:

- die WhatsApp-DB existiert
- eine Watch-Gruppe konfiguriert ist

Fehlt eine dieser Voraussetzungen, wird der Watcher mit einer expliziten Skip-Meldung nicht gestartet.

## Smoke Checks

### Outbound

```bash
curl -fsS http://127.0.0.1:9111/status
```

Dann ein Agent-Tool wie `bridge_whatsapp_send(...)` oder `bridge_whatsapp_voice(...)` ausfuehren.

### Reproduzierbarer lokaler Smoke

Ohne echte WhatsApp-Nachricht kann die interne Strecke lokal mit temp Config, temp SQLite und Fake-HTTP-Servern verifiziert werden:

```bash
python3 Backend/verify_whatsapp_local_smoke.py
```

Der Smoke prueft real:

- `bridge_whatsapp_read` gegen eine temp SQLite-DB
- `bridge_whatsapp_send` gegen eine Fake-Go-Bridge
- den internen Sendepfad von `bridge_whatsapp_voice` mit lokal gestubbter TTS
- `whatsapp_watcher.py` als echten Subprozess gegen temp DB + Fake-Bridge `/send`

Der Smoke prueft bewusst nicht den echten ElevenLabs- oder WhatsApp-Netzpfad.

### Inbound Watcher

```bash
tmux ls
tmux capture-pane -pt whatsapp_watcher
```

Erwartung:

- Session `whatsapp_watcher` existiert nur bei erfuellten Voraussetzungen
- der Watcher loggt DB, Gruppe und Bridge-Ziel
- bei fehlender DB oder fehlender Gruppe beendet er sich fail-closed

## Bekannte Grenzen dieses Slices

- Die externe Go-Bridge ist weiterhin ein separater Bestandteil und wird durch dieses Repo nicht automatisch installiert.
- Docker-Compose bootstrappt die WhatsApp-Go-Bridge noch nicht.
- Die live im Repo vorhandene `Backend/whatsapp_config.json` ist kein sauberer Release-Artefaktpfad und sollte fuer einen Release nicht die kanonische Konfigurationsquelle sein.
