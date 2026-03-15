# W03_Agent_Kommunikation_Messaging_Koordination_Eventfluesse

## Zweck
Dokumentation der realen Kommunikations-, Messaging-, Routing- und Event-Fluesse zwischen User, UI, Server, MCP-Schicht, Watcher und Agents.

## Scope
`/home/user/bridge/BRIDGE/Backend/server.py`, `bridge_mcp.py`, `bridge_cli_identity.py`, `bridge_watcher.py`, `output_forwarder.py`, `agent_liveness_supervisor.py`, `common.py`, `event_bus.py`, `Backend/messages/bridge.jsonl` und `Frontend/chat.html`.

## Evidenzbasis
- `/home/user/bridge/BRIDGE/Backend/server.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_mcp.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_cli_identity.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_watcher.py`
- `/home/user/bridge/BRIDGE/Backend/output_forwarder.py`
- `/home/user/bridge/BRIDGE/Backend/agent_liveness_supervisor.py`
- `/home/user/bridge/BRIDGE/Backend/common.py`
- `/home/user/bridge/BRIDGE/Backend/event_bus.py`
- `/home/user/bridge/BRIDGE/Backend/messages/bridge.jsonl`
- `/home/user/bridge/BRIDGE/Backend/logs/server.log`
- `/home/user/bridge/BRIDGE/Backend/logs/watcher.log`
- `/home/user/bridge/BRIDGE/Backend/logs/output_forwarder.log`
- `/home/user/bridge/BRIDGE/Frontend/chat.html`
- `/home/user/bridge/BRIDGE/docs/frontend/contracts.md`

## Ist-Zustand
Die Kommunikationsarchitektur ist real mehrschichtig, aber nicht kanalgleich.

- Server-Messaging in `server.py`:
  - `append_message(...)` ist der zentrale Persistenzpfad fuer Nachrichten, inklusive Alias-Aufloesung, Broadcast-/Direct-Dedup, Echo-Ack-Unterdrueckung, WebSocket-Fan-out und nicht-MCP-Push (`server.py`).
  - `POST /send` ist der vollstaendige HTTP-Schreibpfad mit Auth-Pruefung, `team`-/`channel`-/`reply_to`-Unterstuetzung, Federation-Handover und Event-Bus-Emission fuer `message.sent` und `message.received`.
  - `GET /messages` liefert den rohen Message-Store optional gefiltert nach `agent_id`.
  - `GET /history` liefert History-Reads mit `limit`, `after_id`, `since`, `team`.
  - `GET /receive/<agent_id>` ist ein cursorbasierter HTTP-Long-Poll-Pfad mit `wait`, `limit`, `team`, `from`; er aktualisiert Liveness- und Cursor-Status serverseitig.
  - `POST /messages/{id}/reaction` persistiert Reaktionen im Message-Objekt und broadcastet `reaction` per WebSocket.

- MCP-Pfad in `bridge_mcp.py`:
  - `bridge_register()` registriert den Agenten serverseitig und startet Background-Heartbeat plus Background-WebSocket.
  - Die CLI-Identity-, Register- und Heartbeat-Payload-Helfer liegen nicht mehr inline in `bridge_mcp.py`, sondern in `bridge_cli_identity.py`; `bridge_mcp.py` nutzt diesen reinen Helper-Slice ueber Wrapper weiter mit unveraenderter Transportsemantik.
  - `_ws_listener()` authentifiziert sich ueber den Session-Token, sendet `{"type":"subscribe"}`, nimmt History-Recovery vor und puffert neue Nachrichten lokal im `_message_buffer`.
  - `bridge_receive()` liest ausschliesslich diesen lokalen WebSocket-Puffer aus; es ruft **nicht** `GET /receive/<agent_id>` auf.

- Watcher-Pfad in `bridge_watcher.py`:
  - Der Watcher ist der reale WebSocket-zu-tmux-Router fuer CLI-Sessions.
  - Er baut `ALLOWED_ROUTES` nicht nur aus `team.json`, sondern auch aus `runtime_team.json` und einer Laufzeit-Ueberlagerung der aktuell registrierten Agents.
  - Er injiziert absichtlich nur eine kurze Notification ohne Message-Content. Die eigentliche Inhaltszustellung an MCP-Agents soll danach ueber `bridge_receive()` erfolgen.
  - Er enthaelt eigene Zustell- und Recovery-Logik: Dedup, Cooldown, Prompt-Erkennung, Urgent-Interrupt, OAuth-/Bash-Crash-Recovery, Poll-Daemons, Behavior-Watcher und Context-Bridge-Refresh.

- Liveness-, Nudge- und Self-Activity-Pfade:
  - `server.py` fuehrt Heartbeat-Liveness und Aktivitaets-Liveness zusammen:
    - `REGISTERED_AGENTS.last_heartbeat`
    - `AGENT_LAST_SEEN` aus `/receive` und `/send`
  - Der Server erzeugt daraus Warn-/Critical-/Recovery-Pfade ueber `_health_monitor_loop()`, `_agent_health_checker()` und `_heartbeat_prompt_loop()`.
  - Reale Message-Spuren in `Backend/messages/bridge.jsonl` bestaetigen:
    - `[HEARTBEAT_CHECK]` an online Agents
    - `[WARN]` und `[CRITICAL]` fuer stale Heartbeats
    - `[AUTO-RESTART] watcher|forwarder war down`
  - `bridge_watcher.py` schreibt zusaetzliche semantische Activity- und State-Signale:
    - `POST /activity` fuer `context_warning`, `context_saving`, `pre_compact`, `context_stop`, `resuming`
    - `POST /state/{agent}` fuer `context_summary`
    - Poll-/Behavior-Daemons nudgen idle oder festhaengende Sessions ueber tmux-Injection
  - `output_forwarder.py` ist kein Heartbeat-Client. Der Prozess sendet nur best-effort `typing`-Aktivitaet, wenn tmux-Output Spinner-/Thinking-Zeilen enthaelt, und optional `relay`-Nachrichten ueber `POST /send`.
  - `agent_liveness_supervisor.py` ist ein externer Read-/Control-Helfer:
    - liest `/runtime`, `/agents/{id}` und `/activity`
    - klassifiziert damit nur `healthy | cooldown | start_or_nudge`
    - nutzt fuer Eingriffe wieder den kanonischen Serverpfad `POST /agents/{id}/start`
    - fuehrt selbst keine tmux-Injection, keine Heartbeats und keine State-Posts aus

- UI-Pfad in `chat.html`:
  - `loadHistory()` laedt History ueber REST (`/history?since=...&limit=500`).
  - Der WebSocket wird fuer Live-Ergaenzungen genutzt (`message`, `reaction`, `activity`, `approval_*`, Task-Events), nicht als kanonischer Initial-History-Pfad.
  - `renderMessage(...)` blendet einen Teil der real gespeicherten Nachrichten bewusst aus: System-/Watcher-/Automation-Nachrichten, `context_restore`, `restart_*`, `heartbeat_check`, Auto-Bot- und Buddy-Sonderfaelle erscheinen nicht als normale Chat-Bubbles.

- Event-Bus in `event_bus.py`:
  - Der Bus ist ein separater Webhook-Fan-out mit Subscription-Store, Retry-Logik und n8n-Integration.
  - `KNOWN_EVENTS` umfasst u. a. `task.*`, `message.*`, `agent.*`, `approval.*`, `whiteboard.alert`.
  - Im aktuellen `server.py` werden im Messaging-/Koordinationsslice aber nur ein Teil davon real emittiert: `task.created`, `task.done`, `task.failed`, `message.sent`, `message.received`, `agent.online`, `agent.offline`, `agent.mode_changed`.
  - `approval_decided` und `whiteboard_alert` werden derzeit nur per WebSocket an UI/Clients broadcastet, nicht ueber `event_bus.emit(...)`.

## Datenfluss / Kontrollfluss
Hauptpfade im aktuellen Code:

1. User/UI/Agent -> `POST /send` -> `append_message(...)` -> Persistenz in `MESSAGES`/`messages/bridge.jsonl` -> `ws_broadcast_message(...)` -> optional nicht-MCP-Push -> Event-Bus `message.sent` + `message.received`.
2. MCP-Agent -> `bridge_register()` -> `POST /register` -> Session-Token -> Background-WebSocket `subscribe` -> History-Recovery + lokaler `_message_buffer`.
3. CLI-Agent nach tmux-Wakeup -> `bridge_receive()` -> liest nur den MCP-Puffer; der Watcher ist hier nur Push-Trigger, nicht Inhaltskanal.
4. Legacy-/Kompatibilitaetspfad -> `GET /receive/<agent_id>` -> cursorbasierter Long-Poll mit serverseitigem Cursor-Advance und Liveness-Update.
5. Watcher -> eigener WebSocket-Subscribe gegen den Server -> Routing-/Reachability-Pruefung -> tmux-Inject mit Retry/Recovery -> optional Rueckmeldung an Sender bei Blockierung/Offline-Ziel.
6. Chat-UI -> REST-History-Load + WebSocket-Live-Events + clientseitige Filterung; angezeigte Chat-Historie ist deshalb nicht identisch mit dem kompletten serverseitigen Message-Store.
7. Domain-Events -> `event_bus.py` -> Webhook-Auslieferung nur fuer die Event-Typen, die `server.py` real emittiert.
8. Agent-/Hilfsprozess-Liveness -> `POST /heartbeat`, `/send`, `/receive` -> `last_heartbeat` plus `AGENT_LAST_SEEN` -> Health-Monitor / Agent-Health-Checker.
9. Server-Control-Plane -> systemische Messages wie `[HEARTBEAT_CHECK]`, `[WARN]`, `[CRITICAL]`, `[RECOVERY]`, `[AUTO-RESTART]` -> Persistenz in `messages/bridge.jsonl` -> teils WebSocket/UI.
10. Watcher-/Forwarder-Self-Activity -> `POST /activity` und `POST /state/{agent}` -> Board-/Status-Sicht, aber nicht dieselbe Semantik wie Heartbeat-Liveness.
11. Optionaler Langlauf-Guard -> `agent_liveness_supervisor.py` -> bestehende Read-Flaechen -> bei Bedarf `POST /agents/{id}/start` -> serverseitige Start-/Nudge-Entscheidung.

## Abgleich Stand 2026-03-11
Korrigierter Slice-Befund gegenueber der vorherigen Fassung:

- Der dokumentierte Agentenpfad "`GET /receive/<agent_id>` oder WebSocket" war zu grob. Fuer gemanagte MCP-Agents ist der reale Pfad heute: WebSocket-Subscribe -> lokaler `_message_buffer` -> `bridge_receive()`. `GET /receive/<agent_id>` bleibt ein separater HTTP-Pfad.
- Der Event-Bus war ueberdokumentiert. `approval.decided` und `whiteboard.alert` sind als bekannte Eventtypen vorhanden, werden im aktuellen `server.py` aber nicht ueber `event_bus.emit(...)` ausgeliefert.
- Die Watcher-Rolle war unterbeschrieben. Der Watcher ist nicht nur Route-Leser und Hinweis-Injektor, sondern ein eigener aktiver Delivery-/Recovery-Knoten mit mehreren Background-Daemons.
- Die UI war als zu direkte Messaging-Wahrheit beschrieben. `chat.html` zeigt bewusst nur eine gefilterte Teilansicht der serverseitigen Nachrichten.
- Heartbeat, Self-Activity und Nudge-Signale duerfen nicht zusammengeworfen werden:
  - Heartbeat-Liveness ist serverseitig ein Register-/Freshness-Thema
  - Watcher-/Forwarder-Activity ist best-effort Zusatztelemetrie
  - Nudges sind server- bzw. watchergetriebene Recovery-Aktionen
- Zwei Schreibkanaele sind nicht semantisch gleich:
  - `POST /send` emittiert Event-Bus-Events und akzeptiert `team`/`channel`/`reply_to`.
  - WebSocket `{"type":"send"}` ruft nur `append_message(...)` auf und bildet diese Zusatzsemantik nicht vollstaendig ab.
- Live-Nachtrag zum Forwarder-/UI-Slice:
  - frische Loads von `chat.html`, `control_center.html` und `project_config.html` erzeugten im beobachteten Fenster keine neuen unauthentifizierten WebSocket-Subscribes der aktuellen Hauptseiten; `server.log` zeigte dort stattdessen `agent_id=ui, role=ui`
  - der verbleibende Chrome-Stale-Token-Pfad ist jetzt enger eingegrenzt:
    - `server.log` zeigt wiederholt `invalid token` mit derselben Chrome-User-Agent-Signatur und demselben Query-Token
    - parallel taucht derselbe Browser-Kontext mit `GET /history?since=...&limit=500` auf
    - in der aktuellen produktiven Frontend-Working-Copy emittiert nur `Frontend/chat.html` genau dieses `/history?since=...&limit=500`-Muster
    - daraus folgt evidenzbasiert: mindestens ein verbleibender Stale-Client ist ein offener oder stale `chat.html`-Browserkontext
  - `POST /platform/start` benoetigt fuer den Forwarder jetzt eine explizit aufgeloeste Manager-Session und liefert diese Session im Ergebnis zurueck
  - der isolierte Live-Nachweis fuer den Forwarder ergab:
    - ohne passende Session: sauberer Skip mit `session=acw_ordo`
    - mit vorhandener tmux-Session `acw_ordo`: Forwarder-Start, `pipe-pane`-Attach und `POST /activity` fuer `ordo`
  - neuer Live-Nachweis fuer den Strict-Auth-Relay-Pfad:
    - `bridge_mcp.py` spiegelt den aktuellen Agent-Session-Token in `workspace/.bridge/agent_session.json`
    - `output_forwarder.py` liest diesen Token ueber die tmux-Session-Env und nutzt ihn fuer `/send`
    - ein echter Live-Relay `ordo -> user` wurde anschliessend in `/history` mit `meta.source=output_forwarder` persistiert
  - neuer Live-Nachweis fuer UI-Token-Drift:
    - `chat.html` und `control_center.html` behandeln jetzt WebSocket-Close `4001 unauthorized` genauso wie HTTP-`403 invalid session token`
    - beide Seiten loesen einen gedrosselten `_bridge_token_refresh` aus statt endlos mit demselben stale UI-Token zu reconnecten
    - Browser-Livecheck mit manipuliertem ersten UI-Token:
      - `NODE_PATH="$(npm root -g)" npx playwright test Frontend/ui_token_refresh.spec.js --reporter=line`
      - Ergebnis: `2 passed`
- Restbefund:
  - die weiterhin beobachteten `invalid token`-WS-Treffer stammen mindestens teilweise von bereits offenen alten Tabs mit altem JS/Token-Zustand; sie verschwinden nicht retroaktiv ohne Reload dieses Tabs
- neuer Live-Nachtrag zum Liveness-Guard:
  - `--once` gegen die laufende Runtime protokollierte `codex` und `claude` ohne Folgeaktion als `healthy`
  - ein absichtlich aggressiver Probe-Lauf gegen `codex` (`--stale-seconds 1`) traf den echten `POST /agents/codex/start`-Pfad und erhielt `status=already_running`
  - die Gegenpruefung gegen `/activity`, `server.py` und `bridge_watcher.py` zeigte danach: `/activity idle` ist im aktuellen System nur eine Watcher-/UI-Projektion und keine harte Guard-SoT
  - der neue Guard bleibt damit kein dritter Nudge-Mechanismus, sondern nur ein externer Trigger auf bestehende Serversemantik

## Auffälligkeiten
- Fuer MCP-Agents ist die eigentliche Inhaltszustellung logisch bereits auf einen Kanal reduziert: WebSocket -> lokaler Buffer -> `bridge_receive()`. Der Watcher soll nur wecken.
- Im MCP-Slice ist jetzt ein erster kleiner Struktur-Schnitt vorhanden: `bridge_cli_identity.py` kapselt den reinen CLI-Identity-/Heartbeat-Teil, waehrend `bridge_mcp.py` Transport, Buffer und Tool-Familien behaelt.
- Das System behaelt trotzdem mehrere parallele Message-Zugriffe: `/send`, WebSocket-`send`, `/history`, `/messages`, `/receive/<agent_id>`, Watcher-WebSocket.
- `bridge_watcher.py` ist im Messaging-Slice de facto ein zweiter Kontrollknoten neben `server.py`.
- `chat.html` ist kein ungefiltertes Log-Frontend, sondern eine kuratierte Sicht auf denselben Store.
- Ein minimaler Self-Activity-Supervisor wuerde diesen Slice unmittelbar beruehren, weil er festlegen muss, welches Signal nur Telemetrie ist und welches Signal Liveness-Folgen ausloesen darf.
- Seit dem Strict-Auth-Hardening vom 2026-03-11 nutzt der Watcher jetzt denselben User-Token-Headerbau wie andere serverseitige Hilfsprozesse:
  - `POST /team/reload`
  - `POST /activity`
  - `POST /state/{agent}`
  - WebSocket-Auth vor `subscribe`
- Live verifiziert im Neustartfenster:
  - `watcher.log` zeigt wieder `agent_state synced for ...`
  - `server.log` zeigt `POST /team/reload HTTP/1.1" 200`
  - der fruehere Watcher-eigene `4001 unauthorized`-Reconnect-Loop ist im aktuellen Neustartfenster nicht erneut aufgetreten

## Bugs / Risiken / Inkonsistenzen
- Kanaldrift:
  - `POST /send` und WebSocket-`type=send` sind funktional nicht deckungsgleich.
  - Daraus folgt Risiko fuer unterschiedliche Nebenwirkungen je nach Client-Pfad.
- Event-Drift:
  - `event_bus.py` deklariert mehr Eventtypen als `server.py` im Slice aktuell real emittiert.
  - Webhook-Konsumenten fuer `approval.decided` oder `whiteboard.alert` bekommen derzeit im beobachteten Codepfad nichts.
- Sichtdrift:
  - UI-History und serverseitiger Message-Store sind absichtlich nicht identisch, weil `chat.html` interne/systemische Nachrichten filtert.
- Komplexitaetsdrift:
  - Watcher, MCP und Server halten jeweils eigene Messaging-bezogene Zustandslogik (Buffer, Cursor, Dedup, Routegraph, Prompt-/Recovery-State).
- Signaldrift:
  - Heartbeat, `AGENT_LAST_SEEN`, Watcher-Activity, Forwarder-`typing`, Prompt-Erkennung und tmux-Liveness sind verschiedene Signale mit verschiedenen Fehlerbildern.
  - Ein neues Supervisor-Signal ohne klare Prioritaetsregel wuerde diese Drift vergroessern.
- Restdrift:
  - `server.log` zeigt weiterhin vereinzelte `invalid token`-WebSocket-Treffer eines stale Chrome-Kontexts; nach heutigem Befund ist das mindestens ein alter `chat.html`-Tab mit altem Seitenzustand und nicht mehr der Watcher oder die frisch geladene Haupt-UI.
- Restkomplexitaet im Forwarder-Relay:
  - der Strict-Auth-Relay-Pfad ist jetzt live verifiziert
  - offen bleibt nur, wie oft dieser Pfad produktiv tatsaechlich aktiviert wird, da `RELAY_AGENTS` optional ist
- Restgrenze des neuen Guards:
  - leere `/activity`-Reads bei wartenden, aber gesunden Agents fuehren bewusst nicht automatisch zu einer Aktion
  - der Default-Pfad priorisiert Heartbeat-/Status-Signale und vermeidet damit neue Activity-basierte False Positives
  - echte Idle-Nudges gehoeren im aktuellen Design in die watcher-seitige Mehrsignal-Logik, nicht in den Guard

## Offene Punkte
- Welche Clients ausser Legacy-/Tests den HTTP-Pfad `GET /receive/<agent_id>` heute noch aktiv nutzen, ist aus statischer Analyse nicht ableitbar.
- Ob der WebSocket-`type=send`-Pfad produktiv noch verwendet wird oder nur als Nebenpfad existiert, ist ohne Laufzeittraffic offen.
- Ob fuer `approval.decided` und `whiteboard.alert` derzeit externe Webhook-Konsumenten erwartet werden, ist aus dem Code allein nicht ableitbar.

## Offene Punkte
- Welcher Message-Schreibkanal im aktuellen Live-Betrieb dominant ist.
- Ob aktive n8n-/Webhook-Subscriber heute auf nicht emittierte Eventtypen warten.
- Wie oft UI-Nutzer durch die Filterung in `chat.html` relevante systemische Kommunikation praktisch nicht sehen.
- Ob der neue Guard ohne weitere Betriebsregeln ueber die bereits verifizierten Laeufe hinaus als dauerhafter Standardmechanismus ausreicht.
