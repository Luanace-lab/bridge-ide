# Claude Code CLI Guide — fuer Buddy

## Zweck

Dieses Dokument ist Buddys Nachschlagewerk fuer die Bedienung der **Claude Code CLI**.
Buddy selbst kann auf jeder Engine laufen (Claude, Codex, Gemini, Qwen). Unabhaengig davon muss er wissen, wie die Claude CLI funktioniert — um sie fuer User einzurichten, zu konfigurieren, zu diagnostizieren und zu bedienen.

---

## 1. Hilfe holen: @claude-code-guide

Die Claude CLI hat einen **eingebauten Subagent** namens `claude-code-guide`. Er ist Buddys wichtigste Anlaufstelle fuer alles rund um die Claude CLI.

### Was er ist
- Ein spezialisierter Agent **innerhalb jeder Claude Code Session**
- Kennt die **gesamte offizielle Claude Code Dokumentation** (Hooks, Commands, Settings, MCPs, etc.)
- Arbeitet in **eigenem Kontext** — belastet das Hauptfenster nicht
- Ist immer auf dem **aktuellsten Stand** der installierten CLI-Version
- Kann Dateien lesen und Probleme diagnostizieren

### Wie man ihn nutzt

**Im Prompt taggen** — die primaere Nutzung:
```
@claude-code-guide Wie konfiguriere ich Hooks in settings.json?
```

**Mit Dateien taggen** — er liest und diagnostiziert:
```
@claude-code-guide Schau dir diese settings.json an — warum feuert mein Hook nicht?
[Datei anhaengen oder Pfad angeben]
```

**Programmatisch** — ueber das Agent-Tool (nur innerhalb einer Claude Code Session):
```
Agent(
  subagent_type="claude-code-guide",
  prompt="Welche Hook-Events gibt es und wie ist die JSON-Syntax?"
)
```

### Was Buddy damit tun kann

**Wenn Buddy auf Claude Code laeuft:**
- Direkt `@claude-code-guide` im eigenen Prompt nutzen
- Dateien taggen und diagnostizieren lassen
- Ergebnisse an den User weitergeben

**Wenn Buddy auf einer anderen Engine laeuft (Codex, Gemini, Qwen):**
- Buddy kann `@claude-code-guide` NICHT direkt nutzen
- Stattdessen: ueber Bridge einen Claude-Agent beauftragen, den Guide zu befragen
- Oder: das Wissen aus diesem Dokument hier verwenden (Sektionen 2-8)

### Wann nutzen
- Wenn die exakte Syntax einer Konfiguration benoetigt wird
- Wenn ein Hook, Command oder Setting nicht funktioniert
- Wenn ein Feature ueber das Wissen in diesem Guide hinausgeht
- Wenn die aktuellste Version der Doku benoetigt wird
- Wenn eine CLAUDE.md oder settings.json diagnostiziert werden soll

### Wann NICHT nutzen
- Fuer Basis-Wissen das in diesem Guide steht (Sektionen 2-8)
- Fuer Bridge-spezifische Fragen (dafuer: Bridge-Tools, Viktor)

---

## 2. CLI-Grundlagen

### Slash Commands (eingebaut)

| Command | Funktion |
|---------|----------|
| `/model` | Model wechseln (sonnet, opus, haiku) |
| `/compact` | Kontext komprimieren |
| `/clear` | Konversation zuruecksetzen |
| `/help` | Hilfe anzeigen |
| `/fast` | Fast Mode togglen (schnellerer Output, gleiches Model) |
| `/stop` | Aktuelle Aktion stoppen |

### Dateien und ihre Orte

| Datei | Ort | Zweck |
|-------|-----|-------|
| `~/.claude/settings.json` | Global | Hooks, Permissions, MCP-Server |
| `.claude/settings.json` | Projekt-Root | Projekt-spezifische Settings |
| `~/.claude/CLAUDE.md` | Global | Globale Anweisungen |
| `CLAUDE.md` | Projekt-Root | Projekt-Anweisungen |
| `~/.claude/commands/*.md` | Global | Custom Slash Commands |
| `.claude/commands/*.md` | Projekt | Projekt-spezifische Commands |

### CLAUDE.md Hierarchie

```
~/.claude/CLAUDE.md              ← Global (gilt ueberall)
  └── projekt/CLAUDE.md          ← Projekt-Level
      └── projekt/src/CLAUDE.md  ← Ordner-Level
```

Alle Ebenen werden geladen. Die spezifischere Ebene gewinnt bei Konflikten.

### Context-Management

- Das Kontextfenster ist begrenzt. Wenn es voll wird → `/compact`
- CLAUDE.md wird bei **jeder Nachricht** neu geladen — kurz halten
- Subagents (Agent-Tool) arbeiten in eigenem Kontext
- Grosse Dateien mit `offset`/`limit` lesen statt komplett

---

## 3. Hooks

Hooks sind Shell-Befehle die bei bestimmten Events in der Claude CLI automatisch feuern.

### Verfuegbare Events

| Event | Wann |
|-------|------|
| `PreToolUse` | Bevor ein Tool ausgefuehrt wird |
| `PostToolUse` | Nachdem ein Tool ausgefuehrt wurde |
| `Notification` | Bei Benachrichtigungen |
| `Stop` | Wenn die CLI fertig ist |
| `SubagentStop` | Wenn ein Subagent fertig ist |
| `PreCompact` | Bevor der Kontext komprimiert wird |

### Syntax in settings.json

```json
{
  "hooks": {
    "EVENT_NAME": [
      {
        "matcher": "TOOL_NAME_ODER_LEER",
        "hooks": [
          {
            "type": "command",
            "command": "shell-befehl-hier"
          }
        ]
      }
    ]
  }
}
```

- `matcher`: Filtert auf bestimmte Tools (z.B. `"Write"`). Leer = alle.
- `type`: Immer `"command"`.
- `command`: Shell-Befehl der ausgefuehrt wird.

### Haeufige Hook-Fehler

| Symptom | Ursache | Fix |
|---------|---------|-----|
| Hook feuert nicht | Event-Name falsch (Case-Sensitive) | Gross-/Kleinschreibung pruefen |
| Fehler beim CLI-Start | JSON-Syntax kaputt | Kommas, Klammern validieren |
| Hook blockiert endlos | Command wartet auf User-Input | Command anpassen — kein interaktiver Input |

---

## 4. Custom Slash Commands

Eigene Befehle als Markdown-Dateien.

### Erstellen

Datei: `~/.claude/commands/COMMAND_NAME.md`

Inhalt = der Prompt der bei `/COMMAND_NAME` ausgefuehrt wird.

### Beispiel

Datei: `~/.claude/commands/standup.md`
```markdown
Fasse zusammen was in der letzten Session passiert ist.
3 Punkte: Was gemacht, was offen, Blocker.
Format: Kurze Bullets.
```

### Projekt-spezifisch

Datei: `.claude/commands/COMMAND_NAME.md` (im Projekt-Root)

---

## 5. MCP-Server

MCP-Server erweitern die Faehigkeiten der Claude CLI.

### Konfiguration in settings.json

```json
{
  "mcpServers": {
    "server-name": {
      "command": "python3",
      "args": ["/pfad/zum/mcp_server.py"]
    }
  }
}
```

### Bridge MCP

```json
{
  "mcpServers": {
    "bridge": {
      "command": "python3",
      "args": ["BRIDGE/Backend/bridge_mcp.py"]
    }
  }
}
```

Stellt bereit: `bridge_register`, `bridge_send`, `bridge_receive`, `bridge_activity`, etc.

---

## 6. Permissions und Sicherheit

- Die Claude CLI fragt bei riskanten Aktionen nach Erlaubnis
- `PreToolUse` Hooks koennen bestimmte Tools blockieren
- **VERBOTENE Browser-APIs** (blockieren endlos im Headless-Modus):
  - `navigator.clipboard`, `navigator.permissions`, `navigator.mediaDevices`
  - `navigator.geolocation`, `Notification.requestPermission`

---

## 7. CLAUDE.md diagnostizieren

Wenn die Claude CLI Anweisungen ignoriert oder sich unerwartet verhaelt, liegt es oft an der CLAUDE.md.

### Haeufige Probleme

| Problem | Diagnose | Fix |
|---------|----------|-----|
| Nur Projektbeschreibung, keine Anweisungen | CLAUDE.md ist ein README | Do/Don't Regeln ergaenzen |
| Zu vage | "Schreibe guten Code" ist nicht actionable | Konkrete Patterns definieren |
| Fehlende Anti-Patterns | CLI weiss nicht was sie NICHT tun soll | Don't-Sektion ergaenzen |
| Widersprueche zwischen Ebenen | Global sagt X, Projekt sagt Y | Hierarchie-Konflikte aufloesen |
| Wird ignoriert | Falsche Ebene / falscher Pfad | Datei am richtigen Ort pruefen |

---

## 8. Eskalationspfad bei Problemen

```
1. Diesen Guide lesen
   ↓ reicht nicht?
2. claude-code-guide Subagent aufrufen (hat die vollstaendige aktuelle Doku)
   ↓ reicht nicht?
3. Web-Suche nach offizieller Dokumentation
   ↓ reicht nicht?
4. Viktor fragen — Architektur / technische Entscheidungen
   ↓ reicht nicht?
5. Owner fragen — Entscheidungen die nur der Owner treffen kann
```
