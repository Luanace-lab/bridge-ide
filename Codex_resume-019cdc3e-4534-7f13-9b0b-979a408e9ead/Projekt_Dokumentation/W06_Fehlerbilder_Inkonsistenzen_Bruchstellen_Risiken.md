# W06_Fehlerbilder_Inkonsistenzen_Bruchstellen_Risiken

## Zweck
Sammlung der aus statischer Analyse erkennbaren Bruchstellen, Inkonsistenzen und Risiken im `/BRIDGE`-Scope, ohne Behandlung oder Fix.

## Scope
Gesamter `/home/user/bridge/BRIDGE`-Scope mit Fokus auf Architekturgrenzen, Dokumentationsdrift, Strukturmischung und betriebliche Komplexitaet.

## Evidenzbasis
- `/home/user/bridge/BRIDGE/README.md`
- `/home/user/bridge/BRIDGE/CLAUDE.md`
- `/home/user/bridge/BRIDGE/LAUNCH_CHECKLIST.md`
- `/home/user/bridge/BRIDGE/TEAM_FINDINGS.md`
- `/home/user/bridge/BRIDGE/Archiev/docs/README.md`
- `/home/user/bridge/BRIDGE/Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`
- `/home/user/bridge/BRIDGE/pyproject.toml`
- `/home/user/bridge/BRIDGE/setup.py`
- `/home/user/bridge/BRIDGE/Backend/server.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_watcher.py`
- `/home/user/bridge/BRIDGE/Backend/output_forwarder.py`
- `/home/user/bridge/BRIDGE/Backend/start_platform.sh`
- `/home/user/bridge/BRIDGE/Backend/stop_platform.sh`
- `/home/user/bridge/BRIDGE/Backend/restart_wrapper.sh`
- `/home/user/bridge/BRIDGE/Backend/messages/bridge.jsonl`
- `/home/user/bridge/BRIDGE/Backend/logs/server.log`
- `/home/user/bridge/BRIDGE/Backend/logs/watcher.log`
- `/home/user/bridge/BRIDGE/Backend/logs/output_forwarder.log`
- `/home/user/bridge/BRIDGE/Frontend/chat.html`
- `/home/user/bridge/BRIDGE/Frontend/control_center.html`
- Root-Struktur von `/home/user/bridge/BRIDGE`

## Ist-Zustand
Die wichtigsten statisch sichtbaren Risikofelder sind:

- Architekturverdichtung:
  - `server.py` ist mit 21768 Zeilen trotz erster Runtime-Slice-Extraktion weiter sehr gross und vereinigt viele Produktbereiche.
  - `Backend/runtime_layout.py` entlastet nur einen kleinen, klaren Runtime-Helferbereich mit 308 Zeilen; die uebrigen Domaenen bleiben in `server.py` gekoppelt.
  - `bridge_mcp.py` ist mit 11333 Zeilen weiter gross; `Backend/bridge_cli_identity.py` entlastet dort erst einen kleinen, reinen Identity-/Heartbeat-Helferbereich mit 97 Zeilen.
  - `chat.html` und `control_center.html` sind mit 10632 bzw. 10071 Zeilen ebenfalls grosse Single-File-Oberflaechen.
  - `GET /` und `GET /ui` liefern real `Frontend/control_center.html`; die Root-Doku beschreibt diesen Einstieg bislang nicht.
- Strukturmischung im Root:
  - aktiver Produktcode
  - Live-/Session-Zustaende in `.agent_sessions/`
  - Resume- und Analysematerial in `Codex_resume-*` und `Dokumentation_Bridge/`
  - persoenliche oder archivierte Bereiche wie `Frontend_persönlich/` und `Archiev/`
  - viele `.bak`-Artefakte direkt neben aktiven Dateien
- Dokumentationsdrift:
  - Root-`README.md` war vor dieser Aktualisierung nur 11 Zeilen lang und beschrieb eine leichte Wrapper-CLI statt der beobachtbaren Plattformbreite.
  - `LAUNCH_CHECKLIST.md` markiert `GETTING_STARTED.md`, `ONBOARDING.md`, `SETUP.md`, `API.md`, `ARCHITECTURE.md` und `team.json.example` als vorhanden, obwohl diese Pfade im Root nicht existieren.
  - Der aktive Root-`docs/`-Baum ist inzwischen wieder befuellt, aber archivierte Detaildoku liegt weiterhin parallel unter `Archiev/docs/`.
  - `CLAUDE.md` nennt Rollenordner wie `Projektleiter_persönlich/`, `Backend_persoenlich/`, `MobileApp_persönlich/` und `Assi/`, die im Root nicht sichtbar sind.
- Packaging-/Startdrift:
  - `pyproject.toml` und `setup.py` deklarieren weiter `bridge-ide = bridge_ide.cli:main`.
  - der fruehere Root-Bruch `bridge_ide` vs. `bridge_ide.cli` ist im aktuellen Tree behoben:
    - Root-`bridge_ide/` ist jetzt wieder vorhanden
    - `python3 setup.py bdist_wheel` lief erfolgreich
    - ein lokaler Wheel-Install nach `/tmp/bridge_pkg_target` war erfolgreich
    - `python3 -m venv --system-site-packages /tmp/bridge_pkg_venv3` plus `pip install -e . --no-deps --no-build-isolation` lief erfolgreich
    - `/tmp/bridge_pkg_venv3/bin/bridge-ide status --url http://127.0.0.1:9111` lieferte live den aktuellen Bridge-Status
- Liveness-/Supervisor-Drift:
  - `server.py` kombiniert Heartbeat-Freshness, `AGENT_LAST_SEEN`, tmux-Liveness, Context-Prozent, Health-Monitor, Agent-Health-Checker, Nudge-Logik und Prozess-Supervision.
  - `bridge_watcher.py` setzt daneben eine zweite Recovery-Ebene fuer Context, Prompt-Idle, Behavior und `agent_state`-Sync.
  - `output_forwarder.py` erzeugt zusaetzlich abgeleitete `typing`-Aktivitaet aus tmux-Spinnern.
  - Diese Signale sind real, aber nicht als eine einzige kanonische Self-Activity-/Liveness-SoT dokumentiert.

## Datenfluss / Kontrollfluss
Die grössten Bruchstellen liegen an Uebergaengen:

1. Release-/Dokumentationssicht -> reale Produktoberflaeche
2. Packaging-Metadaten -> tatsaechlich sichtbarer Root-Dateibaum
3. Root-Dokumente -> verschobene Detaildoku unter `Archiev/docs/` und `Backend/docs/`
4. Monolithische Kernfiles -> viele voneinander abhaengige Teilzustaende
5. Root-Struktur -> menschliche Orientierung bei Analyse oder Betrieb

## Abhängigkeiten
- `server.py` koppelt viele Risiken gleichzeitig, weil dort Messaging, Tasks, Teams, Whiteboard, Workflows, Memory und Runtime-Steuerung zusammenlaufen.
- `README.md`, `LAUNCH_CHECKLIST.md` und `CLAUDE.md` haengen direkt von der aktuellen Root-Struktur ab, referenzieren sie aber nur teilweise korrekt.
- `pyproject.toml` und `setup.py` bilden die Packaging-Sicht, die in dieser Working Copy nicht deckungsgleich mit dem sichtbaren Root-Baum ist.
- `Archiev/docs/README.md` und `Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md` tragen reale Detaildoku, liegen aber ausserhalb des aktiven Root-`docs/frontend/`-Pfads.

## Auffälligkeiten
- Das Repository wirkt wie ein aktiver Betriebsraum und nicht wie ein clean getrenntes Produktartefakt.
- `Archiev/` ist zugleich Archiv, Doku-Sammelpunkt und Strukturlast.
- Historische Findings (`TEAM_FINDINGS.md`) und aktuelle technische Referenzen liegen nebeneinander, aber mit unterschiedlicher Gueltigkeit.
- Der Root signalisiert zugleich Release-Wrapper, Live-Runtime, Resume-Arbeitsraum und Archiv.

## Bugs / Risiken / Inkonsistenzen
- Inkonsistenz zwischen dokumentierter Wrapper-CLI-Sicht und realer Plattformbreite.
- die verbleibende Packaging-Risikolage liegt nicht mehr im Python-Entry-Point selbst, sondern in der Umgebungsparitaet zwischen Shell-Start, Packaging-CLI und Docker-Pfad.
- Inkonsistenz zwischen `LAUNCH_CHECKLIST.md` und den real vorhandenen Root-Dokumentpfaden.
- Risiko der Fehlinterpretation von `Archiev/`, Backup-Dateien und persoenlichen Verzeichnissen als aktive Produktteile.
- Risiko hoher Seiteneffekte wegen zentraler Logikbuendelung in wenigen Dateien.
- Real verifizierter Auth-Befund auf der lokalen HTTP-Flaeche nach dem Read-Surface-Haertungsslice:
  - geschlossen:
    - `GET /logs?name=server&lines=1` liefert ohne Auth jetzt real `401 {"error":"authentication required"}`
    - `GET /messages?limit=1` liefert ohne Auth jetzt real `401`
    - `GET /history?limit=1` liefert ohne Auth jetzt real `401`
    - `GET /task/queue?limit=1` liefert ohne Auth jetzt real `401`
    - `GET /agents` liefert ohne Auth jetzt real `401`
    - `GET /agent/config?project_path=/home/user/bridge/BRIDGE&engine=claude` liefert ohne Auth jetzt real `401`
    - `GET /n8n/workflows` liefert ohne Auth jetzt real `401`
    - `GET /n8n/executions?limit=1` liefert ohne Auth jetzt real `401`
    - `GET /automations` liefert ohne Auth jetzt real `401`
    - `GET /workflows/tools` liefert ohne Auth jetzt real `401`
    - `GET /events/subscriptions` liefert ohne Auth jetzt real `401`
    - dieselben Pfade liefern mit gueltigem `X-Bridge-Token` weiter real `200`
    - `bridge_watcher.py` liest `/messages` und `/history` nach dem Restart weiter erfolgreich; `server.log` zeigt dafuer erneut echte `200`-Reads
  - Restrisiko:
    - nicht jeder denkbare GET-Pfad und nicht jede exotische Proxy-Topologie wurde in demselben Slice separat neu auditiert
- Reduzierte, aber nicht vollstaendig aufgeloeste Semantikdrift in der Agent-Projektion:
  - `Backend/team.json` speichert fuer `viktor` `active:true` und `auto_start:false`
  - nach Fix liefern `GET /agents/viktor`, `GET /agents`, `GET /agents?source=team` und `GET /team/orgchart` live getrennt `active:true`, `online:false` und `auto_start:false`
  - der konkrete `auto_start`-Mapping-Bug und die Kern-Doppeldeutigkeit im Hauptpfad sind damit behoben; Restunsicherheit liegt nur noch in nicht separat neu geprueften Downstream-Consumern
- Buddy-/Frontdoor-Gaps sind im aktuellen Live-Zustand weiter real, aber in anderer Form:
  - vor dem Frontdoor-Lauf zeigten `GET /agents/buddy` und `GET /onboarding/status?user_id=user` konsistent `offline` bzw. `buddy_running:false`
  - `Frontend/buddy_frontdoor_returning_user.spec.js` startete Buddy danach real aus `buddy_landing.html`
  - `GET /agents/buddy` zeigte unmittelbar danach live `status=waiting`, `active=true`, `tmux_alive=true`, `phantom=true`
  - `POST /agents/cleanup {"ttl_seconds":0}` entfernte Buddy bei lebender `acw_buddy`-Session nicht mehr
  - das fruehere Write-Auth-Mismatch in `buddy_landing.html` bleibt geschlossen
  - das Buddy-Home war vorher unvollstaendig (`BRIDGE_OPERATOR_GUIDE.md` fehlte, Home-Doks waren CLI-spezifisch nicht kanonisch)
  - live verifiziert ist jetzt ein kanonischer Setup-Pfad ueber `GET /cli/detect` plus `POST /agents/buddy/setup-home`
  - `GET /cli/detect` ist fuer den Frontdoor-Pfad inzwischen ueber einen kurzen TTL-Cache plus Single-Flight gegen widerspruechliche Parallelprobes gehaertet
  - `POST /agents/buddy/setup-home` materialisierte im Buddy-Home real `BRIDGE_OPERATOR_GUIDE.md`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` und `QWEN.md`
  - der zuletzt erneut verifizierte Live-Zustand konvergierte danach zu `phantom:false` und `cli_identity_source=cli_register`; das verbleibende Risiko ist damit keine dauerhafte Frontdoor-Fehlfunktion mehr, sondern nur ein kurzer Register-/Heartbeat-Uebergang waehrend des Boots
  - `POST /agents/buddy/start` behandelt den zuletzt reproduzierten tmux-Start-Race jetzt als `already_running` statt als Fehler, wenn die Session zwischenzeitlich aktiv wurde
  - der sichtbare Mehr-CLI-Fall bietet jetzt eine echte Auswahl, aber fruehe programmatische Bootstrap-Pfade koennen weiterhin deterministisch `existingEngine || recommended || available[0]` ziehen
  - verbleibendes Setup-Risiko: `gemini` und `qwen` werden im Scan derzeit bewusst nur als verfuegbar mit `auth_status=unknown` ausgewiesen, weil dafuer in diesem Slice kein offizieller nicht-interaktiver Login-Probe-Pfad verifiziert wurde
- Frontend-Topologie ist im aktiven Hauptpfad entkoppelt, aber nicht universell bewiesen:
  - `Frontend/bridge_runtime_urls.js` loest API-/WS-Basen fuer `chat.html`, `control_center.html`, `project_config.html`, `task_tracker.html`, `buddy_landing.html` und `buddy_widget.js`
  - `Frontend/bridge_runtime_urls.spec.js` belegte den Resolver real fuer `127.0.0.1`, `localhost` und Same-Origin-Proxys
  - Restrisiko bleibt fuer nicht separat gepruefte exotische Proxy- oder Path-Prefix-Topologien
- Risiko falscher Aktivitaetsbilder:
  - spinnerbasierte `typing`-Impulse des Forwarders zeigen Arbeit an, ohne Heartbeat oder semantischen Fortschritt zu beweisen
  - tmux-Lebenszeichen koennen Heartbeat-Verlust ueberdecken
  - `AGENT_LAST_SEEN` kann einen Agenten als live erscheinen lassen, obwohl kein frischer Heartbeat vorliegt
- Risiko unvollstaendiger Sicht fuer Nutzer:
  - `messages/bridge.jsonl` enthaelt `[HEARTBEAT_CHECK]`, `[WARN]`, `[CRITICAL]`, `[RECOVERY]` und `[AUTO-RESTART]`
  - `chat.html` filtert einen Teil dieser System-/Heartbeat-Nachrichten aus der normalen Bubble-Sicht
- Risiko stiller Prozessvertragsbrueche:
  - `start_platform.sh`, `server.py`-Supervisor, `restart_wrapper.sh` und `stop_platform.sh` kennen heute konkret `watcher` und `forwarder`
  - ein neuer Self-Activity-Supervisor als eigener Prozess muesste in allen vier Vertraegen plus Tests nachgezogen werden, sonst entsteht ein neuer Orphan-/Restart-Blindfleck
- Der neu eingefuehrte `agent_liveness_supervisor.py` vermeidet im aktuellen Stand nur einen Teil dieses Drifts bewusst:
  - kein Auto-Start
  - kein Eintrag in Wrapper-/Stop-Vertraegen
  - nur expliziter Opt-in-Loop
  - Doppelstarts werden jetzt ueber einen PID-Lock abgefangen
  - dadurch kein neuer Pflichtprozess, aber auch keine automatische Langlauf-Haertung im Standardboot
  - die Gegenpruefung gegen `server.py`, `bridge_watcher.py` und Live-`/activity` zeigte: ein Guard-Nudge direkt auf `/activity idle` waere systemisch falsch, weil dieses Signal nur Projektion und nicht operative SoT ist
  - live verifiziert bleibt der Guard in seiner Default-Reichweite auf `/runtime` begrenzt und ist damit kein globaler Supervisor fuer alle aktiven Agents:
    - `GET /runtime` lieferte am 2026-03-12 nur `agent_ids=["codex","claude"]`
    - `GET /agents` und `GET /agents/codex_3` zeigten parallel mindestens `codex_3` als `active=true`, `status=waiting`, `tmux_alive=true`
    - der laufende Langlaufprozess `python3 Backend/agent_liveness_supervisor.py --interval 60 --duration-seconds 28800 --pid-file Backend/pids/agent_liveness_supervisor.pid` schrieb in `Backend/logs/agent_liveness_supervisor.autonomous.log` dennoch nur Iterationen fuer `codex` und `claude`
  - daraus folgt: der Helper ist kanonisch nur fuer den bestehenden Server-Eingriffspfad `POST /agents/{id}/start`, aber nicht als kanonische Systemaufsicht ueber alle live aktiven CLI-Agents
- Operatives Restrisiko im aktuellen Live-Betrieb:
  - `ordo` ist im aktuellen Live-Zustand weiter ein echter Startblocker:
    - `GET /agents/ordo` zeigt `status=offline`, `tmux_alive=false`, `config_dir=/home/user/.claude-sub2`, `subscription_id=""`
    - `server.log` zeigt weiter `WARN: OAuth token expired ... for ordo` und `Credential validation failed for ordo. Token expired or missing`
  - der fruehere `runtime/configure`-Engpass des kanonischen Startpfads ist fuer den aktuellen Shell-Entry-Point reduziert: `start_platform.sh` uebergibt jetzt `stabilize_seconds=30` und lief im verifizierten Live-Neustart mit Exit-Code `0` bis `configured=true`
  - `server.log` zeigt aktuell zwei getrennte Klassen von `invalid token`-WebSocket-Treffern:
    - einen aelteren regulaeren Chrome-Treffer mit normaler Chrome-UA
    - die aktuelle wiederholte Serie fuer `stale-ui-token-for-ws-refresh-test` mit HeadlessChrome-UA aus den UI-Token-Refresh-Tests
  - vor dem aktuellen Fix existierten fuer den Forwarder zwei konkurrierende Startwahrheiten: `start_platform.sh` loeste die Manager-Session aus `team.json`, `server.py` trug dagegen einen separaten Startpfad; dieser Drift ist jetzt fuer `/platform/start` und den Supervisor behoben, bleibt aber als Befund fuer die Architekturhistorie relevant
  - der optionale Forwarder-Relay-Pfad `RELAY_AGENTS` -> `POST /send` ist jetzt live verifiziert; offenes Restrisiko ist nur noch seine optionale Produktnutzung und nicht mehr der Auth-Pfad selbst
  - `stop_platform.sh` bereinigte vor dem aktuellen Fix keine nackten BRIDGE-CLI-Prozesse ausserhalb von tmux; ein realer `claude --resume ...`-Orphan mit `BRIDGE_CLI_SESSION_NAME=acw_claude_probe` blieb deshalb ueber Neustarts stehen
  - dieser Gap ist jetzt live verifiziert und behoben:
    - `stop_platform.sh` killt BRIDGE-CLI-Orphans nun ueber Session-/Incarnation-Abgleich
    - im Live-Stop erschien `stopping orphan bridge_cli (pid=3220839 session=acw_claude_probe)`
  - `runtime/configure` kann kanonisch scheitern, wenn ein Runtime-Agent in `team.json` keine gueltige Subscription-/`config_dir`-Zuordnung traegt
    - historischer Recovery-Befund:
      - `claude` hatte `config_dir=""`, `subscription_id=""`
      - Folge: Fallback auf `~/.claude`
      - historischer `server.log`-Befund: `Credential validation failed for claude. Token expired or missing`
    - kanonische Recovery:
      - `PUT /agents/claude/subscription` -> `sub2`
      - danach wieder `configured=true`
  - historischer Live-Nachtrag vor dem aktuellen Cleanup:
    - `claude` war zwischenzeitlich wieder sauber auf `subscription_id=sub2` und `config_dir=/home/user/.claude-sub2` gemappt
    - beide lokalen Claude-Profile `/home/user/.claude` und `/home/user/.claude-sub2` enthielten dabei nicht abgelaufene `.credentials.json`-Token
    - die damals noch aktive Headless-Prevalidation `claude -p ok --output-format text` scheiterte in diesem Zwischenstand mit `You've hit your limit · resets Mar 16, 2am (Europe/Berlin)`
  - aktueller Live-Nachtrag nach dem Credential-Blind-Cleanup:
    - `tmux_manager.py` fuehrt fuer Claude keine Credential-/Onboarding-Dateioperationen und keine nicht-interaktive `claude -p ok`-Prevalidation mehr aus
    - `POST /agents/claude/start` projiziert im aktuellen Live-Lauf stattdessen offizielle Sessionzustaende wie `manual_setup_required`
    - `POST /runtime/configure` fail-closed projiziert den verbleibenden Runtime-Blocker jetzt explizit als:
      - `error_stage=interactive_setup`, `error_reason=login_required`
      - oder spaeter `error_stage=runtime_stabilization`, `error_reason=registration_missing`
    - der aktuelle Runtime-Blocker ist damit kein Dateicredential- oder Limit-Read der Bridge mehr, sondern eine noch nicht abgeschlossene offizielle Claude-Session-Interaktion bzw. fehlende Registration
  - Restinkonsistenz:
    - `ordo` erschien im aktuellen Statusfenster kurz als registriert, waehrend `tmux_alive=false` war
    - damit ist `online` im Moment nicht strikt gleichbedeutend mit `gesunde tmux-Inkarnation`
  - Doku-Folgerisiko fuer den minimalen Supervisor-Slice:
  - der Guard ist nach wie vor kein globaler Produktivitaetsregler und bleibt ein reiner Liveness-/Startpfad-Helfer
  - wenn nur Messaging-Doku oder nur Runtime-Doku aktualisiert wird, entsteht sofort neue Drift
  - der Slice beruehrt mindestens Architekturfluss, Event-/Liveness-Semantik, Risiken und Start-/Stop-Vertrag gleichzeitig
  - neuer Workflow-/n8n-Befund im aktuellen Integrations-Endzustand:
    - `GET /workflows` und `GET /n8n/executions?limit=5` liefern wieder `200`
    - nach dem bereinigenden Delete-Lauf zeigt `GET /events/subscriptions` jetzt `count=1`
    - Bridge-managed Event-Subscriptions sind damit wieder aktiv und auf einen einzelnen kanonischen Task-Notification-Webhook reduziert
    - der Schreibpfad n8n -> Bridge bleibt unter Strict Auth headerpflichtig:
      - `POST /send` ohne `X-Bridge-Token` liefert real `401 {"error":"authentication required"}`
      - der aktuelle Live-Zustand ist aber repariert: `python3 Backend/repair_n8n_bridge_auth.py --dry-run --limit 250` liefert `repaired_count=0`
    - realer Folgefehler, der im Integrationslauf sichtbar wurde:
      - mehrfache Template-Deploys und Builder-Probes fuehrten zu doppelten Reports und doppelten Task-Benachrichtigungen
      - diese Artefakte wurden per `DELETE /workflows/{id}` entfernt; `workflow_registry.json` blieb danach mit genau `3` Bridge-managed Records zurueck
      - ein frischer Probe-Task erzeugte danach wieder genau eine userseitige Task-Benachrichtigung
  - neuer Live-Befund zum minimalen Guard:
    - kurze Live-Loops und der echte `POST /agents/{id}/start`-Pfad sind verifiziert
    - der autonome tmux-Lauf schrieb einen echten Exit mit `uptime_seconds=66336.4` und uebertraf damit 8h deutlich
    - ein paralleler Doppelstart wurde live durch den PID-Lock blockiert

## Offene Punkte
- Ob `Archiev/docs/` nur Zwischenablage oder der faktische Archiv-Home fuer Alt-Doku ist, ist nicht formalisiert.
- Welche Root-Artefakte explizit als "historisch", "persoenlich" oder "operativ" markiert werden sollen, ist nicht formalisiert.
- Ob zusaetzlich zur jetzt verifizierten Container-Control-Plane auch ein vollwertiger nativer CLI-Runtime-Pfad im selben Containerprofil Produktziel sein soll, bleibt eine Folgeentscheidung.

## Produktkritische Einordnung
- Fuer den aktuell verifizierten Host-Betrieb ist diese Grenze kein akuter Produktionsausfall: die echte Agent-Runtime laeuft dort bewusst host-nativ ueber `tmux`, `codex` und `claude`.
- Fuer einen fremden Nutzer auf einem anderen Rechner wird dieselbe Grenze aber release-kritisch, sobald Docker/Compose als vollstaendiger Ein-Kommando-Installations- oder Betriebsweg versprochen wird.
- Ohne hostseitig installierte und eingeloggte nativen CLIs kann ein fremder Nutzer die BRIDGE dann zwar als Control Plane starten, aber keine echte Agent-Runtime im selben Containerprofil ausfuehren.
- Der technische Grund ist im aktuellen Code belegt:
  - `Backend/tmux_manager.py` startet die operative Agent-Runtime ueber native `codex`-/`claude`-CLI-Prozesse in `tmux`
  - das verifizierte Container-Image enthaelt diese nativen CLIs bewusst nicht

## Verifizierte Container-Grenze
- Der Docker-/Compose-Pfad ist jetzt real end-to-end verifiziert, aber bewusst nur als Control-Plane-/n8n-Proxy-Profil.
  - verifiziert:
    - `docker run --rm hello-world` lief erfolgreich
    - der erste Docker-Build schob wegen unvollstaendigem `.dockerignore` mehr als `7 GB` Kontext
    - nach `.dockerignore`-Fix plus explizitem `rm -f Backend/runtime_team.json` im `Dockerfile` fiel der reale Build-Kontext auf rund `270 MB`, und der isolierte Compose-Container startete ohne eingebranntes Runtime-Overlay
    - `docker/compose:1.29.2 config` loeste `docker-compose.yml` mit env-gesteuerten Published-Ports erfolgreich auf
    - `docker/compose:1.29.2 up -d --build` startete den isolierten Compose-Lauf erfolgreich
    - `GET /status` auf `http://127.0.0.1:19111/status` lieferte real `200`
    - `GET /runtime` auf `http://127.0.0.1:19111/runtime` lieferte real `configured=false`, `running_count=0`, `agent_ids=[]`
    - `GET /workflows` und `GET /n8n/executions?limit=5` lieferten im Compose-Lauf mit gueltigem `X-Bridge-Token` real `200`
    - `GET /n8n/executions?limit=1` lieferte im Compose-Lauf ohne Token real `401 {"error":"authentication required"}`
    - direkte Containerinspektion zeigte:
      - `/root/.config/bridge/tokens.json` vorhanden
      - `/root/.config/bridge/n8n.env` vorhanden
      - `missing:codex`
      - `missing:claude`
      - `missing:n8n`
  - daraus folgt:
    - der Containerpfad ist jetzt als ehrlicher Bridge-Control-Plane-Pfad verifiziert
    - er bildet aber bewusst nicht den host-nativen CLI-Runtime-Pfad nach, weil die nativen CLIs im Image fehlen
  - lokaler Tooling-Nachtrag:
    - `docker compose` ist im Hostpfad dieses Agenten weiter kein direkter Befehl
    - die reale Compose-Ausfuehrung lief erfolgreich ueber `docker/compose:1.29.2`

## Offene Punkte
- Welche der sichtbaren Risiken bereits durch externe Betriebsregeln kompensiert werden.
- Welche der zahlreichen Backup-Dateien fuer Menschen noch Teil des realen Entscheidungsprozesses sind.
- Welches konkrete Browserfenster oder welcher konkrete Tab den aelteren regulaeren Chrome-`invalid token`-Treffer aktuell haelt.
- Warum `ordo` im aktuellen Neustartfenster trotz fehlender `acw_ordo`-Session noch kurz als registriert erschien; der Befund ist beobachtet, die Ursache in diesem Slice aber nicht weiter eingegrenzt.
