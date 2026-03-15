# Telegram Setup

## Ziel

Dieser Pfad richtet eine reproduzierbare Telegram-Integration ueber die Telegram Bot API ein.
Er vermeidet user-spezifische Telefonnummern oder MTProto-Session-Hacks.

## Komponenten

- Outbound/Read-Tools in `Backend/bridge_mcp.py`
- Inbound-Watcher in `Backend/telegram_watcher.py`
- Start/Stop-Integration in `Backend/start_platform.sh` und `Backend/stop_platform.sh`
- Lokaler Smoke-E2E in `Backend/verify_telegram_local_smoke.py`

## Voraussetzungen

1. Ein Telegram Bot Token von BotFather
2. Eine reale Testgruppe oder ein Testkanal
3. Die numerische Chat-ID dieses Ziels

## Konfiguration

```bash
mkdir -p ~/.config/bridge
cp Backend/telegram_config.example.json ~/.config/bridge/telegram_config.json
printf '%s\n' '123456:bot-token-from-botfather' > ~/.config/bridge/telegram_bot_token
chmod 600 ~/.config/bridge/telegram_bot_token
```

Dann `~/.config/bridge/telegram_config.json` anpassen:

- `read_whitelist`: Chats, die `bridge_telegram_read` lesen darf
- `send_whitelist`: Chats, an die `bridge_telegram_send` senden darf
- `approval_whitelist`: optionale Chats, die Approval ueberspringen
- `watch_chats`: Chats, die `telegram_watcher.py` pollen und in Bridge routen darf
- `default_route`: Bridge-Agent ohne @Mention
- `contacts`: optionale Aliase wie `team`

## Umgebungsvariablen

Optional statt Dateipfaden:

```bash
TELEGRAM_CONFIG_PATH=~/.config/bridge/telegram_config.json
TELEGRAM_BOT_TOKEN=123456:bot-token-from-botfather
TELEGRAM_API_BASE_URL=https://api.telegram.org
TELEGRAM_READ_WHITELIST=-1001234567890
TELEGRAM_SEND_WHITELIST=-1001234567890
TELEGRAM_WATCH_CHATS=-1001234567890
```

## Startpfad

`Backend/start_platform.sh` startet `telegram_watcher.py` nur, wenn:

- ein Bot Token verfuegbar ist
- mindestens ein Watch-Chat konfiguriert ist

Andernfalls wird der Watcher explizit uebersprungen.

## Lokaler Smoke-Test

Der lokale Smoke-Test verwendet:

- Fake Telegram Bot API
- Fake Bridge Approval-/Send-Endpunkte
- echten `telegram_watcher.py`-Subprozess
- temp Config + temp JSONL-Store

Ausfuehren:

```bash
python3 Backend/verify_telegram_local_smoke.py
```

Der Smoke prueft:

- `bridge_telegram_send`
- `bridge_telegram_read` gegen Live-`getUpdates`
- `telegram_watcher.py` als echten Subprozess
- `bridge_telegram_read` gegen den lokalen Watcher-Store

## Echte Live-Verifikation

Fuer den letzten externen Schritt braucht es:

1. reales Bot Token
2. reale Testgruppe/Testkanal
3. Bot ist im Zielchat vorhanden und darf Nachrichten lesen/senden

Dann:

1. `./Backend/start_platform.sh`
2. `bridge_telegram_send(to="team", message="Smoke")`
3. Eine echte Nachricht in den Watch-Chat senden
4. Bridge-Inbound in UI oder `Backend/messages/bridge.jsonl` pruefen

## Restrisiko

- Die Telegram Bot API liefert nur das, was fuer den Bot sichtbar ist.
- Kanal-/Gruppenrechte muessen real korrekt gesetzt sein.
- Ohne echte Testgruppe bleibt der externe Netzpfad `Nicht verifiziert.`
