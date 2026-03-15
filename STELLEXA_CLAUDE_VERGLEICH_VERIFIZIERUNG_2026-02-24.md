# Verifizierung: Stellexa vs Claude (Bridge) — Technische Analyse

Stand: 2026-02-24 (Live-Pruefung mit Systemrechten)  
Scope: Verifikation der Aussage von `stellexa`, warum `Claude/manager` in der Bridge reibungsloser wirkt als `Codex/stellexa`  
Wichtig: `Kein Code wurde geaendert.` `Keine destruktiven Operationen ausgefuehrt.`

## Methode (verifiziert)

Geprueft wurden:
- Live-APIs: `/status`, `/runtime`, `/health`, `/agents`, `/history`
- tmux-Sessions (`acw_*`), Pane-CWDs und Pane-Kommandos
- Prozessbaeume (`pstree`) fuer `manager`, `lucy`, `nova`, `viktor`, `stellexa`
- Watcher-Log (`/tmp/bridge_watcher_v2.log`)
- Relevante Codepfade in `/home/user/bridge/BRIDGE/Backend`
- Lokale und globale Config-Ebenen fuer Claude und Codex

## Kurzfazit

Die Kernaussage von `stellexa` ist `weitgehend korrekt`.

Die Hauptursachen fuer die schlechtere Reibung bei `stellexa` sind technisch:
1. Prompt-Erkennung im `bridge_watcher` ist Claude-zentriert und erkennt `stellexa` haeufig nicht als prompt-ready.
2. `output_forwarder` liefert automatische Telemetrie nur fuer `manager` (Claude), nicht fuer `stellexa`.
3. `stellexa` ist als aktiver Bridge-Agent registriert, aber nicht deckungsgleich mit dem konfigurierten Runtime-Slot `codex`.

Wichtige Praezisierung:
- Das Prompt-Erkennungsproblem betrifft nicht nur `user -> stellexa`, sondern technisch `alle -> stellexa` (auch `manager`, `lucy`, `nova`, `viktor`), weil der Watcher generell an tmux-Sessions zustellt.
- Die Aussage zu `CODEX_SANDBOX_NETWORK_DISABLED=1` war in der live geprueften Session-Umgebung nicht nachweisbar.

## Verifikation der Stellexa-Aussage (Punkt fuer Punkt)

### 1) Architektur-/Integrationsunterschied
Bewertung: `STIMMT`

Beobachtet:
- `/status` und `/runtime` zeigen `pair_mode = codex-claude`, aber Runtime-Slots `codex`, `claude`, `teamlead` sind aktuell `disconnected` / `running=false`.
- `/health` zeigt gleichzeitig:
  - `stellexa`: `status=ok`, `tmux=true`
  - `codex`: `status=fail`, `tmux=false`
- `/agents` zeigt:
  - `stellexa` als `running`
  - `codex` als `disconnected`

Abgeleitet:
- Der aktive Codex-aehnliche Bridge-Agent ist aktuell `stellexa` (eigene Agent-ID), nicht der Runtime-Slot `codex`.
- Es existieren parallel zwei Ebenen: Runtime-Konfiguration (`codex/claude/teamlead`) und operativ registrierte Agents (`manager`, `lucy`, `nova`, `viktor`, `stellexa`).

### 2) Startpfad / Workspace-Unterschied
Bewertung: `STIMMT`

Beobachtet (tmux live):
- `acw_manager`: CWD `/home/user/bridge/BRIDGE`, Command `claude`
- `acw_lucy`: CWD `/home/user/bridge/Lucy`, Command `claude`
- `acw_nova`: CWD `/home/user/bridge/Nova`, Command `claude`
- `acw_viktor`: CWD `/home/user/bridge/Viktor`, Command `claude`
- `acw_stellexa`: CWD `/home/user/bridge/Codex`, Command `node` (Codex)

Beobachtet (Prozessbaum):
- `acw_stellexa` ist eine echte Codex-CLI-Session (`node` -> `codex` binary)
- `acw_stellexa` hat `python3 /home/user/bridge/BRIDGE/Backend/bridge_mcp.py` als Child-Prozess

Abgeleitet:
- `stellexa` ist real integriert (tmux + MCP), aber mit anderem Arbeitskontext (`/CC/Codex`) als `manager` (`/CC/BRIDGE`).

### 3) BRIDGE-Agent-Erzeugung ueber `tmux_manager.py`-Pipeline
Bewertung: `WEITGEHEND STIMMIG` (indirekt belegt)

Beobachtet:
- `/home/user/bridge/BRIDGE/.agent_sessions/` ist aktuell leer.
- Kein sichtbarer Workspace unter `/home/user/bridge/BRIDGE/.agent_sessions/stellexa`.
- `Backend/tmux_manager.py` erzeugt Standard-Agent-Workspaces unter `.agent_sessions/<agent_id>` und schreibt dort:
  - engine-spezifische Instruktionsdatei
  - engine-spezifische Runtime-Config
  - `.mcp.json`
  - tmux-Session mit CWD = Agent-Workspace

Code-Belege:
- `Backend/tmux_manager.py:192` (`create_agent_session(...)`)
- `Backend/tmux_manager.py:222` (Workspace `.agent_sessions/<agent_id>`)
- `Backend/tmux_manager.py:248` (Runtime-Config)
- `Backend/tmux_manager.py:255` (`.mcp.json`)
- `Backend/tmux_manager.py:275` (`tmux new-session ... -c <workspace>`)

Abgeleitet:
- `stellexa` laeuft aktuell nicht sichtbar im standardisierten BRIDGE-Agent-Workspace-Modell.
- Streng beweisbar ist der aktuelle Zustand, nicht die gesamte Historie (also nicht sicher beweisbar: "nie ueber tmux_manager erstellt").

### 4) Telemetrie-/Forwarder-Asymmetrie ("Lebendigkeit")
Bewertung: `STIMMT`

Beobachtet:
- Es laeuft ein `output_forwarder.py` Prozess.
- `Backend/output_forwarder.py` ist standardmaessig auf `acw_manager` verdrahtet:
  - `TMUX_SESSION = os.environ.get("FORWARDER_SESSION", "acw_manager")`
- `send_to_bridge(...)` sendet fest als:
  - `"from": "manager"`
  - `"to": "user"`
  - `meta.source = "output_forwarder"`

Code-Belege:
- `Backend/output_forwarder.py:32`
- `Backend/output_forwarder.py:170`
- `Backend/output_forwarder.py:177`

Live-Historie (letzte 300 Messages):
- `output_forwarder` Statusmeldungen (`meta.source=output_forwarder`, `meta.type=status`):
  - `manager`: `134`
  - `stellexa`: `0`

Abgeleitet:
- `manager` wirkt in der UI kontinuierlich "lebendig/proaktiv", selbst ohne finale Antwort.
- `stellexa` hat diese automatische Sichtbarkeit aktuell nicht.

### 5) Prompt-Erkennung im `bridge_watcher` (groesste technische Ursache)
Bewertung: `STIMMT` (stark belegt)

Beobachtet (Code):
- `is_agent_at_prompt(...)` ist Claude-zentriert dokumentiert und implementiert.
- Claude-spezifische Erkennungsmarker enthalten u. a.:
  - `"bypass permissions"`
  - `"What should Claude do"`

Code-Belege:
- `Backend/bridge_watcher.py:53`
- `Backend/bridge_watcher.py:56`
- `Backend/bridge_watcher.py:83`
- `Backend/bridge_watcher.py:87`

Beobachtet (Live-Funktionscheck):
- `manager -> True`
- `lucy -> True`
- `nova -> True`
- `viktor -> True`
- `stellexa -> False`

Beobachtet (Watcher-Log `/tmp/bridge_watcher_v2.log`):
- Fuer `stellexa` haeufig:
  - `nicht am Prompt (Versuch 1/3 ... 3/3)`
  - `force-injiziert (nicht am Prompt)`
- Fuer `manager` haeufig:
  - `injiziert (Versuch 1, am Prompt)`

Quantifizierung (Watcher-Log Gesamt):
- `manager`: `269x direct_prompt`
- `lucy`: `28x direct_prompt`
- `nova`: `16x direct_prompt`
- `viktor`: `17x direct_prompt`
- `stellexa`: `148x not_prompt`, `37x force`

Quantifizierung (Tail-Sample):
- `stellexa`: weiterhin `148x not_prompt`, `37x force` (im geprueften Tail)
- `manager`: `32x direct_prompt`
- `lucy`: `10x direct_prompt`
- `nova`: `10x direct_prompt`
- `viktor`: `11x direct_prompt`

Abgeleitet:
- `stellexa` wird durch den Watcher systematisch schlechter als prompt-ready erkannt.
- Das fuehrt zu mehr Retries, spaeteren Injektionen und schlechterem Reaktionsgefuehl.

### 6) Gilt das nur fuer `user -> stellexa`?
Bewertung: `NEIN` (wichtige Praezisierung)

Beobachtet (Code):
- Der `bridge_watcher` verarbeitet generell WebSocket-Messages vom Typ `message` und injiziert an tmux-Sessions.
- Er skippt `recipient in {"user","system",""}` und routet ansonsten an Ziel-Sessions.

Code-Belege:
- `Backend/bridge_watcher.py:222`
- `Backend/bridge_watcher.py:225`
- `Backend/bridge_watcher.py:234`
- `Backend/bridge_watcher.py:245`
- `Backend/bridge_watcher.py:268`

Beobachtet (Watcher-Log-Verteilung nach Sendern -> `stellexa`):
- `user -> stellexa`: `114x not_prompt`, `38x force`
- `manager -> stellexa`: `15x not_prompt`, `5x force`
- `lucy -> stellexa`: `6x not_prompt`, `2x force`
- `nova -> stellexa`: `9x not_prompt`, `3x force`
- `viktor -> stellexa`: `6x not_prompt`, `2x force`

Abgeleitet:
- Das technische Prompt-Erkennungsproblem betrifft `alle -> stellexa`.
- Dass es subjektiv beim `user` staerker auffaellt, ist plausibel (direkter Dialog + fehlende Telemetrie), aber nicht exklusiv.

### 7) `cli_adapters.py` (Claude vs Codex) Asymmetrie
Bewertung: `STIMMT` (repo-seitig), aber `nicht Hauptursache im aktuellen Stellexa-Pfad`

Beobachtet (Code):
- `ClaudeAdapter`:
  - Streaming (`stream-json`)
  - `--resume <session_id>`
- `CodexAdapter`:
  - one-shot `codex exec`
  - kein Resume
  - isolierte Calls

Code-Belege:
- `Backend/cli_adapters.py:68`
- `Backend/cli_adapters.py:91`
- `Backend/cli_adapters.py:94`
- `Backend/cli_adapters.py:141`
- `Backend/cli_adapters.py:144`
- `Backend/cli_adapters.py:192`

Beobachtet (Prozessbaum live):
- `stellexa` laeuft aktuell als interaktive tmux-Codex-CLI, nicht sichtbar ueber den `cli_adapters.py` One-shot-Pfad.

Abgeleitet:
- Diese Adapter-Asymmetrie ist real und relevant fuer bestimmte Pfade.
- Fuer das aktuelle `stellexa`-Reibungsproblem ist sie eher sekundär gegenueber Watcher/Forwarder-Asymmetrien.

### 8) Permissions-/Sandbox-Ebene (`CODEX_SANDBOX_NETWORK_DISABLED=1`)
Bewertung: `AKTUELL UNBELEGT`

Beobachtet:
- In den live geprueften Umgebungsvariablen der laufenden `codex`-Prozesse (`stellexa` und weiterer Codex-Prozess) wurde `CODEX_SANDBOX_NETWORK_DISABLED=1` nicht gefunden.
- Sichtbar war u. a. `CODEX_MANAGED_BY_NPM=1`.

Abgeleitet:
- Der konkrete Claim ist fuer die gepruefte Session-Umgebung nicht belegt.
- Das schliesst nicht aus, dass ein solcher Wert in anderen Subprozessen/Run-Kontexten auftreten kann.

### 9) Eigener Ausfuehrungsfehler / Disziplin bei offenen Zusagen
Bewertung: `NICHT rein technisch verifizierbar`

Beobachtet:
- Das ist primär ein Verhaltens-/Prozesspunkt, kein Architekturmerkmal.

Abgeleitet:
- Technisch kann ich hier keine harte Ja/Nein-Verifikation liefern.

## Vergleichsmatrix (Claude/Manager vs Codex/Stellexa)

| Aspekt | Claude / `manager` | Codex / `stellexa` | Andere Claude-Agents (`lucy/nova/viktor`) | Belegt | Wirkung auf Reibungslosigkeit |
|---|---|---|---|---|---|
| Bridge-Agent aktiv registriert | Ja | Ja | Ja | Ja | Grundfunktion vorhanden |
| Runtime-Slot deckungsgleich mit aktivem Agent | `claude`-Slot aktuell disconnected | `codex`-Slot disconnected, aktiv ist `stellexa` | n/a | Ja | Integrationspfade getrennt |
| tmux-Session vorhanden | `acw_manager` | `acw_stellexa` | `acw_lucy/nova/viktor` | Ja | Alle laufen real |
| Session-CWD | `/CC/BRIDGE` | `/CC/Codex` | jeweilige `/CC/*` Homes | Ja | Kontext-/Pfadasymmetrie |
| `bridge_mcp.py` Child-Prozess | Ja | Ja | Ja | Ja | MCP-Grundfaehigkeit vorhanden |
| Sichtbarer BRIDGE-Standard-Workspace `.agent_sessions/<id>` | fuer Runtime-Slots derzeit nicht aktiv | fuer `stellexa` nicht vorhanden | nicht sichtbar | Ja | Stellexa nicht im Standard-Workspace-Modell sichtbar |
| Prompt-Erkennung `is_agent_at_prompt(...)` | `True` | `False` | `True` | Ja | zentraler Reibungsfaktor |
| Watcher-Injektion | meist direkt (`am Prompt`) | haeufig Retries + `force-injiziert` | meist direkt | Ja | mehr Latenz/Friktion bei Stellexa |
| Auto-Telemetrie (`output_forwarder`) | Ja (manager-zentriert) | Nein | Nein | Ja | Manager wirkt proaktiver |
| Forwarder-Status in Historie (letzte 300) | `134` | `0` | `0` | Ja | starke UX-Asymmetrie |
| Repo-Adapter (CLI) | Streaming + Resume | one-shot / kein Resume | n/a | Ja | relevant je nach Pfad |
| Aktueller Live-Pfad nutzt One-shot-Adapter primär | Nicht gezeigt | Nein (interaktive tmux-Codex-CLI) | n/a | Ja | Adapter-Asymmetrie hier nicht Hauptursache |

## Live-Befunde (kompakt)

### `/status` / `/runtime`
- `pair_mode = codex-claude`
- Runtime-Slots:
  - `codex` (`acw_codex`) disconnected / `tmux_alive=false`
  - `claude` (`acw_claude`) disconnected / `tmux_alive=false`
  - `teamlead` (`acw_teamlead`) disconnected / `tmux_alive=false`

### `/health`
- `manager`: `ok`, `tmux=true`
- `lucy`: `ok`, `tmux=true`
- `nova`: `ok`, `tmux=true`
- `viktor`: `ok`, `tmux=true`
- `stellexa`: `ok`, `tmux=true`
- `codex`: `fail`, `tmux=false`

### `/agents`
- `manager`, `lucy`, `nova`, `viktor`, `stellexa` registriert und heartbeat-aktiv
- `codex` registriert, aber `disconnected`

## Konfigurationsebene (Claude vs Codex)

### Codex (`stellexa`)
Beobachtet:
- `/home/user/bridge/Codex` enthaelt `AGENTS.md`, `SOUL.md`, `GROW.md`
- keine lokale `.codex/`-Config in `/home/user/bridge/Codex/.codex`
- keine lokale `.mcp.json` in `/home/user/bridge/Codex/.mcp.json`
- globale Codex-Config vorhanden mit Bridge-MCP:
  - `/home/user/.codex/config.toml` enthaelt `[mcp_servers.bridge]`
  - `command = "python3"`
  - `args = ["/home/user/bridge/BRIDGE/Backend/bridge_mcp.py"]`

### Claude (`manager`, `lucy`, `nova`, `viktor`)
Beobachtet:
- `/home/user/bridge/BRIDGE/.claude/settings.local.json` hat explizite `mcp__bridge*`/`mcp__playwright*`-Freigaben und `defaultMode = bypassPermissions`
- `lucy/nova/viktor` haben keine lokalen `.claude/settings.local.json` (in ihren Homes nicht vorhanden)
- gemeinsame MCP-Konfig auf `/home/user/bridge/.mcp.json` enthaelt `bridge` und `playwright`
- globale Claude-Config in `/home/user/.claude/settings.json` vorhanden (breite Permissions, Plugins)

Abgeleitet:
- Claude-Agents nutzen hier sichtbar eine etablierte gemeinsame Konfigurationsebene (`/CC/.mcp.json` + globale Claude-Settings), waehrend `stellexa` auf globale Codex-Config setzt und lokal schlanker konfiguriert ist.
- Das ist eine Asymmetrie, aber nicht der staerkste belegte Reibungsfaktor (staerker: Watcher/Forwarder).

## Harte Schlussfolgerungen (nur technisch)

1. `Codex/Stellexa kann Bridge-MCP technisch nutzen.`  
Beleg: `bridge_mcp.py` Child-Prozess unter `acw_stellexa`, Bridge-Registrierung/Heartbeat im `/health` und `/agents`.

2. `Das Hauptproblem ist nicht fehlende Codex-Faehigkeit, sondern Bridge-Integrationsasymmetrie.`  
Beleg: Prompt-Erkennung + Watcher-Log + manager-zentrierter Forwarder.

3. `Claude wirkt "proaktiver", weil die Plattform ihn sichtbarer und prompt-kompatibler behandelt.`  
Beleg: `output_forwarder` nur fuer `manager`, `is_agent_at_prompt(manager)=True`, `is_agent_at_prompt(stellexa)=False`.

4. `Die Aussage "Agent->Agent zuverlaessig, user<->stellexa problematisch" ist UX-seitig plausibel, aber technisch unvollstaendig.`  
Beleg: Watcher-Log zeigt Prompt-Probleme auch bei `manager/lucy/nova/viktor -> stellexa`.

## Offene Punkte / Unbelegt (mit aktuellem Stand)

- `CODEX_SANDBOX_NETWORK_DISABLED=1` in der laufenden Stellexa-Session konnte ich nicht nachweisen.
- Verhaltensaussage zu "Ausfuehrungsdisziplin" ist nicht rein technisch verifizierbar.
- Historische Frage, ob `stellexa` jemals via `tmux_manager` erstellt wurde, ist mit aktuellem Snapshot allein nicht absolut beweisbar. Der aktuelle Zustand spricht jedoch klar fuer einen anderen Pfad.

## Referenzstellen im Code (fuer spaetere Nacharbeit)

- Prompt-Erkennung / Watcher-Injection:
  - `Backend/bridge_watcher.py:53`
  - `Backend/bridge_watcher.py:83`
  - `Backend/bridge_watcher.py:165`
  - `Backend/bridge_watcher.py:202`
  - `Backend/bridge_watcher.py:234`
  - `Backend/bridge_watcher.py:245`
- Manager-Forwarder / Telemetrie:
  - `Backend/output_forwarder.py:32`
  - `Backend/output_forwarder.py:170`
  - `Backend/output_forwarder.py:177`
- Standardisierte Agent-Session-Erzeugung:
  - `Backend/tmux_manager.py:192`
  - `Backend/tmux_manager.py:222`
  - `Backend/tmux_manager.py:248`
  - `Backend/tmux_manager.py:255`
  - `Backend/tmux_manager.py:275`
- CLI-Adapter-Asymmetrie (Claude vs Codex):
  - `Backend/cli_adapters.py:68`
  - `Backend/cli_adapters.py:91`
  - `Backend/cli_adapters.py:94`
  - `Backend/cli_adapters.py:141`
  - `Backend/cli_adapters.py:144`
  - `Backend/cli_adapters.py:192`

Empfehlung von Stellexa
Konkrete Optimierungsliste (Kommunikation, schlank, nur auf Claude-Niveau)\n\nZiel: Stellexa soll kommunikativ so wirken wie Claude/Manager: sichtbar aktiv, klare Statuswechsel, keine stillen offenen Zusagen.\n\nPRIO 0 (muss zuerst)\n\n1) EIN Betriebsmodell fuer Stellexa (kein Parallelpfad)\n- Entscheidung: Stellexa nur noch als BRIDGE-verwalteter tmux-Agent ODER nur noch als externe Codex-Session. Nicht beides gleichzeitig.\n- Empfehlung: BRIDGE-verwalteter tmux-Agent (wie Manager/Claude-Verhalten).\n- Warum: Der Parallelpfad (`acw_stellexa` in /CC/Codex + BRIDGE-Runtime-Slots) erzeugt Status-/Tracing-Widersprueche.\n- Erfolgskriterium: In BRIDGE gibt es genau 1 aktive Identitaet fuer mich (stellexa) + ein konsistentes tmux/running/heartbeat-Bild.\n\n2) Stellexa bekommt dieselbe Live-Telemetrie wie Claude (Typing-Forwarder)\n- Aktuell ist der Output-Forwarder auf `acw_manager` zentriert.\n- Minimal-Loesung: gleichen Forwarder fuer `acw_stellexa` aktivieren (oder multi-session faehig machen), gleiche `typing`-Statusmeldungen in die Bridge.\n- Warum: Claude wirkt reibungslos, weil du Aktivitaet live siehst. Bei mir fehlt diese Sichtbarkeit.\n- Erfolgskriterium: Wenn ich in tmux schreibe/denke, siehst du in der Bridge denselben `typing`-Status wie beim Manager.\n\n3) Verbindlicher Open-Commitment-Mechanismus (minimal)\n- Wenn ich Leo etwas zusage ("ich recherchiere", "ich melde mich"), wird ein offener Punkt gesetzt.\n- Vor idle MUSS geprueft werden: offene Zusage ja/nein.\n- Bei offenem Punkt nur 3 erlaubte Wege: weiterarbeiten / blockiert melden / erledigt melden.\n- Warum: Das war der zentrale Fehler im Test.\n- Erfolgskriterium: Kein idle mehr mit offener Leo-Zusage ohne Statusmeldung.\n\nPRIO 1 (macht es stabil und angenehm)\n\n4) Einfache Status-Sprache (kein Spam)\n- Nur diese Typen fuer Leo:\n  - ACK (verstanden, starte jetzt)\n  - WORKING (nur bei laengeren Tasks oder relevantem Zwischenstand)\n  - BLOCKED (mit konkretem Blocker)\n  - DONE (Ergebnis + naechster Schritt)\n- Warum: verhindert Status-Looping, aber haelt dich informiert.\n- Erfolgskriterium: Weniger Nachrichten, aber jede hat Substanz.\n\n5) "Idle" semantisch trennen (wichtig fuer Vertrauen)\n- `idle_waiting_user` = ok\n- `idle_with_open_commitment` = Fehler / Alarm\n- `active_tool_run` = arbeitet\n- Warum: "idle" allein ist zu grob und fuehrt zu Missverstaendnissen.\n- Erfolgskriterium: Wenn du trace liest, weisst du sofort, ob ich nur warte oder etwas vergessen habe.\n\n6) Start-Check fuer Berechtigung/Settings (1x pro Session)\n- Zu Sessionbeginn ein kurzer Selbstcheck an Leo/Bridge:\n  - Workspace\n  - effektive Tool-Sandbox (ja/nein)\n  - Codex config/trust ok\n  - MCP bridge erreichbar\n- Warum: erspart Diskussionen wie beim Playwright-Thema (Rollenrechte vs Tool-Sandbox).\n- Erfolgskriterium: Rechte-/Sandbox-Lage ist zu Beginn transparent.\n\nPRIO 2 (optional, nur wenn ihr wollt)\n\n7) Ein schlanker "Long Task"-Timer fuer proaktive Rueckmeldung\n- Nur fuer Tasks > X Minuten: automatische Erinnerung an mich selbst, Leo proaktiv zu updaten oder Blocker zu melden.\n- Warum: Schuetzt gegen Wegdriften in stilles Arbeiten.\n- Erfolgskriterium: Keine verschwundenen langen Tasks ohne Rueckmeldung.\n\nWAS ICH NICHT EMPFEHLE (Overengineering)\n- Kein komplexes neues Workflow-System nur fuer Kommunikation\n- Kein permanentes Spam-Heartbeat im Sekunden-Takt\n- Keine riesige State-Maschine, bevor PRIO 0 sauber steht\n\nWenn du nur 3 Dinge machst (minimaler Hebel, Claude-aequivalent):\n1) ein einziger Betriebsmodus (BRIDGE-tmux)\n2) Typing-Forwarder auch fuer Stellexa\n3) Open-Commitment-Check vor idle + Pflichtmeldung bei DONE/BLOCKED


## Handlungsempfehlung von Codex (Originaltext, 1:1)

Ja. Ich habe Stellexas Empfehlung jetzt mit eigener technischer Analyse ergänzt und bewerte sie aus Systemsicht.

Wichtig vorweg:
- `Codex kann heute schon frei senden` (serverseitig gibt es keine harte Empfänger-ACL für registrierte Agents).
- Das Problem ist aktuell primär `Zustellung/UX/Integrationsqualität`, nicht fehlende Sendefähigkeit.

Beleg dafür:
- `bridge_mcp.py` sendet mit registrierter Agent-ID (`bridge_send`) und Tokenbindung (`Backend/bridge_mcp.py:251`, `Backend/bridge_mcp.py:257`)
- Server `/send` erlaubt Empfänger frei (registrierte Agenten + `user/system/all`), bei unbekanntem Empfänger nur Warnung (`Backend/server.py:3178`, `Backend/server.py:3183`, `Backend/server.py:3200`)
- Anti-Impersonation ist aktiv (Token bindet `from`) und sollte bleiben (`Backend/server.py:3160`, `Backend/server.py:3171`)

**Was in Stellexas Empfehlung noch fehlt (technisch wichtig)**
Stellexas Empfehlung ist gut, aber sie lässt ein paar harte technische Punkte aus, die für „maximal frei + reales UX“ entscheidend sind.

1. `bridge_watcher`-Prompt-Erkennung für Codex ist der größte Reibungsfaktor und muss explizit als eigener Punkt rein
- Das ist aktuell der stärkste belegte technische Engpass.
- `is_agent_at_prompt('stellexa') = False`, Claude-Agents `True`.
- Watcher-Log zeigt massiv `nicht am Prompt` + `force-injiziert` für `stellexa`.
- Code ist Claude-zentriert (`Backend/bridge_watcher.py:53`, `Backend/bridge_watcher.py:83`, `Backend/bridge_watcher.py:87`).
- Ohne diesen Fix bleibt es auch mit Telemetrie „ruckelig“.

2. „Ein zweiter Forwarder für Stellexa starten“ ist aktuell nicht einfach startbar, weil der Forwarder technisch auf Single-Instance/Manager gebaut ist
- `output_forwarder.py` hat Default-Session `acw_manager` (`Backend/output_forwarder.py:32`)
- Er sendet hardcoded `from: "manager"` (`Backend/output_forwarder.py:177`)
- Er hat Claude-spezifische Spinner-Erkennung (`Backend/output_forwarder.py:62`)
- Er killt andere Forwarder-Prozesse beim Start (`Backend/output_forwarder.py:207`, `Backend/output_forwarder.py:262`)
- Fazit: „Forwarder auch für Stellexa“ ist richtig als Ziel, aber braucht einen echten technischen Umbau (Multi-Instance oder Multi-Session-fähig).

3. Identität/Adressierung fehlt als eigener Architekturpunkt (`codex` vs `stellexa`)
- Aktuell gibt es Status-/Routing-Verwirrung durch getrennte Identitäten (`codex` Runtime-Slot vs `stellexa` aktiver Agent).
- Das ist nicht nur „Betriebsmodell“, sondern konkret ein `Adressierungsproblem` für User/UI/Agenten.
- Für „frei kommunizieren“ braucht Codex eine kanonische ID (oder Alias-System mit eindeutiger Auflösung).

4. MCP-Toolbeschreibung für `bridge_send` ist veraltet und kann Codex künstlich einschränken
- `bridge_send`-Beschreibung nennt nur `user, teamlead, claude_a, claude_b, all` (`Backend/bridge_mcp.py:248`)
- Tatsächlich erlaubt der Server jede registrierte Agent-ID (`Backend/server.py:3178`, `Backend/server.py:3183`)
- Das kann dazu führen, dass Codex sich selbst unnötig beschränkt („darf ich `lucy/viktor/nova/manager/stellexa` direkt anschreiben?“)

5. Roster/Agent-Discovery fehlt im MCP-Workflow (für freie Kommunikation wichtig)
- `bridge_mcp` hat `bridge_health`, `bridge_history`, `bridge_check_activity`, aber kein dediziertes `bridge_list_agents`.
- Für „selbständig Agents frei kontaktieren“ braucht Codex eine klare, aktuelle Liste erreichbarer IDs.
- Sonst sendet Codex eher zögerlich oder in falsche IDs.

6. Silent-Drop-Risiko im `bridge_receive`-Puffer fehlt in der Empfehlung
- `_message_buffer` ist `deque(maxlen=500)` (`Backend/bridge_mcp.py:38`, `Backend/bridge_mcp.py:57`)
- Bei hoher Last werden alte Nachrichten still verworfen (deque maxlen-Verhalten)
- `bridge_receive()` leert den kompletten Puffer (`Backend/bridge_mcp.py:285`, `Backend/bridge_mcp.py:288`)
- Wenn Codex wegen Prompt-/Watcher-Friktion nicht rechtzeitig liest, kann das Zuverlässigkeit drücken

7. Latenztreiber im Watcher (Retry/Cooldown) fehlen als UX-Punkt
- `INJECTION_COOLDOWN = 2.0`, `RETRY_DELAYS = [1,2,4]` (`Backend/bridge_watcher.py:46`, `Backend/bridge_watcher.py:49`)
- Das bedeutet bei `not_prompt` schnell mehrere Sekunden Verzögerung
- Für „real chat feeling“ muss das gemessen und ggf. codex-spezifisch optimiert werden (nach Prompt-Erkennung-Fix)

**Klare Handlungsempfehlung (strukturiert, mit Zielbild)**
Ziel: `Codex` soll sich wie ein echter, lebendiger Agent anfühlen, frei mit dir und anderen Agents kommunizieren können, ohne Claude/Manager zu destabilisieren.

**Zielbild (was „maximal frei“ praktisch heißt)**
1. Eine kanonische Codex-Identität in der Bridge (keine Doppelrealität).
2. Codex kann `manager`, `lucy`, `nova`, `viktor`, `user` direkt adressieren.
3. Eingehende Nachrichten an Codex werden zuverlässig und prompt wirksam (ohne häufiges `force-injiziert`).
4. Codex sendet sichtbare Aktivitätssignale (Typing/Working), damit sich das UX real anfühlt.
5. Keine Regression bei `manager`/Claude.

**Priorisierte Maßnahmen (ohne Claude zu stören)**
1. `MUSS`: Ein Betriebsmodell + eine kanonische ID festlegen
- Empfohlen: `codex` als kanonische Bridge-ID, `Stellexa` als Anzeigename/Rolle.
- Alternative: `stellexa` als kanonische ID, aber dann überall konsistent.
- Keine parallele Runtime-ID plus separate manuelle Codex-ID mehr.

2. `MUSS`: Codex-spezifische Prompt-Erkennung im `bridge_watcher`
- Eigener Erkennungszweig für `acw_stellexa`/Codex (statt Claude-Pattern).
- Ziel: `is_agent_at_prompt(stellexa)` wird zuverlässig `True`, weniger Retries/Force.
- Das ist der größte technische Hebel für reales Chat-Verhalten.

3. `MUSS`: Forwarder-Architektur von „Manager-only“ auf „profilbasiert/multi-session“ umbauen
- Nicht nur Session umschalten.
- Erforderlich:
  - Sender nicht hardcoded (`manager`)
  - Multi-Instance nicht gegenseitig killen
  - Parser-Profil je Engine/Session (Claude vs Codex)
- Ziel: `manager` und `codex` können parallel Telemetrie senden, ohne sich zu stören.

4. `MUSS`: MCP-Discovery für freie Agent-Kommunikation verbessern
- `bridge_send`-Toolbeschreibung aktualisieren (keine veralteten Recipient-Beispiele)
- Zusätzlich MCP-Tool für Agent-Liste/Status (`bridge_list_agents`) oder klare Nutzung von `/agents` via bestehendem Tool erweitern
- Ziel: Codex kennt erreichbare IDs zuverlässig und handelt proaktiv

5. `SOLLTE`: Puffer-/Zuverlässigkeit absichern
- Overflow sichtbar machen (z. B. `dropped_count`)
- Optional `bridge_receive(peek=false)`/`bridge_peek`-Semantik, damit Codex nicht versehentlich konsumiert ohne Verarbeitung
- Ziel: keine stillen Verluste bei hoher Last

6. `SOLLTE`: Open-Commitment-Mechanismus (Stellexa-Empfehlung) als Betriebsregel einführen
- Das ist kein Architekturfix, aber entscheidend für Vertrauen/Flow
- ACK / WORKING / BLOCKED / DONE-Statussprache ist sinnvoll und schlank

**Was ich als „Minimalpaket“ empfehle (maximaler Effekt, geringes Risiko)**
1. Kanonische Codex-ID + ein Betriebsmodell
2. Codex-Prompt-Erkennung im `bridge_watcher`
3. Codex-Telemetrie (Forwarder v2, parallel zu Manager)
4. MCP-Agent-Discovery / Recipient-Info korrigieren
5. Open-Commitment-Regel

Das bringt:
- echte Reaktionsfähigkeit
- sichtbare Aktivität
- freie Agent-Kommunikation
- weniger Verwirrung bei IDs
- keine Claude-Regression, wenn codex-spezifisch eingeführt

**Wichtige technische Leitplanken (für „maximal frei“, aber sicher)**
- Beibehalten: Anti-Impersonation via Token (`Backend/server.py:3160`)
- Beibehalten: freie Sendefähigkeit an registrierte Agents (`Backend/server.py:3178`)
- Ergänzen: bessere Discovery statt mehr Restriktion
- Ergänzen: Observability statt Blindflug (Latenz/Force-Rate/Overflow-Metriken)

**Abnahmekriterien (objektiv, damit „real“ messbar wird)**
1. `is_agent_at_prompt('codex' oder 'stellexa')` in Stichproben meist `True`
2. Watcher-Log: `force-injiziert` für Codex drastisch reduziert
3. Forwarder-Historie: Codex sendet Statusmeldungen ähnlich sichtbar wie Manager
4. `user -> codex` fühlt sich direkt an (ACK schnell, Zwischenstatus sichtbar)
5. `codex -> manager/lucy/nova/viktor` ohne Recipient-Warnungen im Normalfall
6. Keine Änderung des Manager-Verhaltens (Forwarder/Watcher für Claude unverändert stabil)

**Zusatz zu deiner Zielsetzung „Codex soll Agents frei kontaktieren können“**
Technisch ist das heute schon grundsätzlich möglich. Was fehlt, ist:
- saubere Agent-Discovery
- eindeutige Identität
- zuverlässige Zustellung/Prompt-Nudge
- sichtbare Telemetrie

Das ist ein Integrationsproblem, kein Modellproblem.

Wenn du willst, formuliere ich dir als Nächstes eine konkrete Umsetzungsreihenfolge als `Patch-Plan` (nur Plan, keine Änderungen) mit `Risiko`, `Rollback`, `Abnahme` pro Schritt.
