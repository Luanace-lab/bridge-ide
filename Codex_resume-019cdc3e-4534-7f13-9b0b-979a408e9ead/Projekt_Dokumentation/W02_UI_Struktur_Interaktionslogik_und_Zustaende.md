# W02_UI_Struktur_Interaktionslogik_und_Zustaende

## Zweck
Dokumentation der realen UI-Flaechen, Interaktionspfade und Zustandsmodelle im `/BRIDGE`-Frontend.

## Scope
`/home/user/bridge/BRIDGE/Frontend`, insbesondere `chat.html`, `control_center.html`, `project_config.html`, `buddy_landing.html` und `i18n.js`.

## Evidenzbasis
- `/home/user/bridge/BRIDGE/Frontend/chat.html`
- `/home/user/bridge/BRIDGE/Frontend/control_center.html`
- `/home/user/bridge/BRIDGE/Frontend/project_config.html`
- `/home/user/bridge/BRIDGE/Frontend/buddy_landing.html`
- `/home/user/bridge/BRIDGE/Frontend/i18n.js`
- `/home/user/bridge/BRIDGE/docs/frontend/README.md`
- `/home/user/bridge/BRIDGE/docs/frontend/contracts.md`
- `/home/user/bridge/BRIDGE/docs/frontend/gap-analysis-vs-release.md`
- `/home/user/bridge/BRIDGE/Archiev/docs/frontend/README.md`
- `/home/user/bridge/BRIDGE/Archiev/docs/frontend/contracts.md`
- `/home/user/bridge/BRIDGE/Archiev/docs/frontend/gap-analysis-vs-release.md`

## Ist-Zustand
Das Frontend ist ein frameworkloses Multi-Page-UI aus grossen HTML/CSS/JS-Dateien:

- `chat.html` ist die zentrale Arbeitsflaeche fuer Messaging, Teams, Task-Board, Workflow-Panel, Approval-Gate, Subscriptions, Agent-Steuerung, Plattform-Start/Stopp, N8N-Snapshot und Buddy-/Onboarding-Hinweise.
- `control_center.html` ist das operative Dashboard fuer Status, Activity-Feed, Kosten, Persistence-Health, Projekt-/Team-Board, Liveboard, Task-Board, Orgchart, Workflow-Builder, Automationen und Agent-Editor.
- `project_config.html` ist die Projekt- und Runtime-Konfigurationsflaeche mit Scan-, Create-, Export- und Configure-Pfad.
- `buddy_landing.html` ist eine gesonderte Buddy-Einstiegsseite mit Onboarding-Status, CLI-Scan, Engine-Auswahl, Buddy-Home-Materialisierung, Polling-Chat, deaktiviertem Browser-TTS und persistierbarer Seitenpanel-Position.
- `i18n.js` ist ein separates Dictionary fuer 5 Sprachen, wird in der aktuellen Working Copy aber nur von `chat.html` eingebunden.
- Im aktuellen Browser-Audit sind zusaetzlich als reale, noch erreichbare Oberflaechen bestaetigt:
  - `task_tracker.html` als dedizierte Taskliste mit Detailpanel und Export
  - `landing.html` als Marketing-/Hash-Navigation
  - `buddy.html` als parallele Buddy-Oberflaeche ausserhalb des dokumentierten Frontdoors

Dokumentierte Kennzahlen aus der Working Copy:

- `chat.html`: 10654 Zeilen
- `control_center.html`: 10189 Zeilen
- `project_config.html`: 2110 Zeilen
- `buddy_landing.html`: 1487 Zeilen
- `i18n.js`: 319 Zeilen
- 23 HTML-Dateien direkt unter `Frontend/`
- Root-`docs/frontend/` ist jetzt der aktive Frontend-Auditpfad; archivierte Vorversionen liegen unter `Archiev/docs/frontend/`

## Datenfluss / Kontrollfluss
Die UIs arbeiten hybrid:

1. Initiale und zyklische Zustandsermittlung per `fetch()`.
2. `chat.html` und `control_center.html` ergaenzen Live-Zustaende ueber WebSocket auf `:9112`; `project_config.html` und `buddy_landing.html` arbeiten ohne WebSocket.
3. `chat.html`, `control_center.html`, `project_config.html` und `buddy_landing.html` injizieren fuer aufgeloeste Bridge-HTTP-Ziele optional `X-Bridge-Token` aus `window.__BRIDGE_UI_TOKEN`; WebSocket-URLs bekommen denselben Token als Query-Parameter nur dort, wo die Seite selbst WebSockets nutzt.
4. UI-lokaler Zustand liegt in Single-File-Variablen und `localStorage`, unter anderem fuer Themes, Sidebar-/Feed-Groessen, Team-Board-Collapse, Workspace-Panels, Favoriten, Welcome-Overlay, Sprache, User-ID und Buddy-Panel-Position.

Beobachtbare Interaktionsachsen:

- `chat.html` nutzt zusaetzlich zu Messaging und History auch `/platform/status`, `/platform/start|stop`, `/board/projects`, `/n8n/executions?limit=5`, `/engines/models`, `/onboarding/status`, `/onboarding/start`, `/pick-directory` und `/chat/upload`.
- `control_center.html` nutzt zusaetzlich `/agents/{id}/persistence`, `/metrics/costs?period=...`, `/whiteboard?type=alert`, `/task/queue?view=board&include_blockers=true`, `/agents/{id}/avatar`, `PATCH /agents/{id}/parent`, `POST /workflows/deploy` und `PUT /workflows/{id}/definition`.
- `project_config.html` scannt ueber `/api/context/scan?project_path=...`, liest fuer den Create-Pfad die erlaubte Projektbasis ueber `GET /projects`, guardet Zielpfade ausserhalb dieser Basis clientseitig und erstellt Projekte ueber `/api/projects/create`; denselben Team-Config-Zustand exportiert die Seite lokal auch als JSON-Datei.
- `project_config.html` startet Runtime-Teams ueber `POST /runtime/configure` und projiziert im Fehlerfall jetzt bevorzugt den ersten `failed[].error_detail` oder `failed[].error_reason` aus der Serverantwort statt nur eines generischen Runtime-Fehlers.
- `buddy_landing.html` kombiniert `GET /cli/detect`, `POST /agents/{BUDDY_ID}/setup-home`, `POST /agents/{BUDDY_ID}/start`, `GET /onboarding/status`, `POST /send` und `GET /receive/{USER_ID}?wait=0&limit=10` mit einer Three.js-gestuetzten Einstiegsanimation.
- Die Landing erkennt jetzt mehrere verfuegbare CLIs live, laesst den User die initiale Buddy-Engine waehlen und materialisiert vor dem Start passend:
  - `CLAUDE.md`
  - `AGENTS.md`
  - `GEMINI.md`
  - `QWEN.md`
  - `BRIDGE_OPERATOR_GUIDE.md`
- Fuer den sichtbaren Frontdoor-Flow nutzt die Landing den schnellen Scan `GET /cli/detect?skip_runtime=1`; serverseitig liegt dahinter jetzt ein kurzer TTL-Cache mit Single-Flight-Guard, damit wiederholte Landing-/Widget-Scans keine widerspruechlichen Parallelprobes ausloesen.
- Wenn Buddy bereits eine weiterhin verfuegbare Engine konfiguriert hat, ueberspringt die Landing die erneute Auswahl und uebernimmt dieses Buddy-Profil direkt fuer den Start.
- Wenn Buddy vor der sichtbaren Auswahl bereits programmgesteuert gebootstrappt wird, faellt die Seite aktuell deterministisch auf `existingEngine || recommended || available[0]` zurueck.
- Live-Nachtrag 2026-03-12:
  - `control_center.html` trifft aktiv `GET /workflows` und `GET /n8n/executions?limit=5`
  - beide Endpunkte lieferten im aktuellen Laufzeitfenster real `200`
  - nach dem Read-Surface-Haertungsslice 2026-03-13 sind `GET /history?limit=1` und `GET /n8n/executions?limit=1` ohne Token real `401`, waehrend dieselben Pfade im Browser mit injiziertem `X-Bridge-Token` weiter `200` liefern
  - `GET /workflows` zeigt im aktuellen Integrationszustand `count=20`; davon bleiben `4` Bridge-managed Workflows als kanonischer Satz aktiv: Daily Report, Wochenreport, Chat-Zusammenfassung und Task-Benachrichtigung
  - parallel existiert jetzt ein echter Browservertrag fuer den Degradationspfad: `Frontend/control_center_n8n_degradation.spec.js`
  - `Frontend/chat_workflow_buttons.spec.js` verifiziert jetzt den `chat.html`-Workflow-Slice real im Browser:
    - Panel oeffnen
    - Template deployen
    - Toggle/Delete eines eindeutigen Workflows
    - Suggestion-Deploy ueber `/workflows/suggest`
  - dabei wurde ein realer UI-Bruch behoben:
    - `chat.html` filterte zuvor alle `from === 'auto'`-Nachrichten vor dem Workflow-Bot-Renderpfad weg
    - `workflow_bot.py` lieferte fuer Suggestions keine `variables`, und `buildWfDeployForm()` las `key`-basierte Variablen nicht korrekt
  - die Token-Injektion ueber den globalen `window.fetch`-Wrapper ist damit nicht nur vorhanden, sondern fuer sensible Read-Pfade real wirksam und funktional noetig
  - damit sind sowohl der gesunde Read-Pfad als auch der isolierte UI-Hinweispfad fuer `n8n nicht erreichbar` sowie der sichtbare Workflow-Button-Slice in `chat.html` testseitig abgedeckt
  - zusaetzlich lief die breitere Frontend-Matrix real gruen:
    - `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/frontend_clickpath_audit.spec.js --reporter=line` -> `5 passed`
    - `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/*.spec.js --reporter=line` -> `13 passed`
  - derselbe Clickpath-Auditlauf wurde im aktuellen Doku-Slice erneut ausgefuehrt:
    - `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/frontend_clickpath_audit.spec.js --reporter=line` -> `5 passed` auf dem laufenden Systemzustand
    - damit sind derzeit real belegt:
      - `landing.html` Hash-Navigation funktioniert, Docs-/GitHub-CTAs bleiben Platzhalter
      - `task_tracker.html` laedt, filtert, oeffnet Detailansicht und exportiert JSON/CSV ueber Browser-Downloads
      - `buddy_landing.html` ist im Frontdoor-Fluss erreichbar; die Start-/Send-Requests laufen jetzt mit UI-Token, und der Returning-User-Pfad startet Buddy aus der Landing heraus ohne vorschnellen Redirect in `chat.html`
      - `buddy_landing.html` ist zusaetzlich real als Buddy-Setup-Einstieg belegt: `Frontend/buddy_landing_setup.spec.js` pruefte CLI-Scan, explizite Engine-Wahl, `POST /agents/buddy/setup-home` und den anschliessenden Buddy-Start
      - `chat.html`-Sidebar und `control_center.html`-Top-Tabs sind klickbar

## Abhängigkeiten
- Gemeinsame Laufzeitauflösung über `Frontend/bridge_runtime_urls.js`
- Lokal verifizierter Dev-Pfad:
  - Seiten auf `127.0.0.1:8787` sprechen API `http://127.0.0.1:9111` und WebSocket `ws://127.0.0.1:9112`
  - Seiten auf `localhost:8787` sprechen API `http://localhost:9111` und WebSocket `ws://localhost:9112`
- Nicht-lokaler Pfad:
  - derselbe Host nutzt Same-Origin-HTTP und hostgleiche WebSocket-URLs (`wss` bei `https`)
- Backend-API-Verfuegbarkeit fuer Plattform-Status, Teams, Tasks, Workflows, Automationen, Health, Activity, Agent-Zustaende, Persistence-Health und Uploads
- `i18n.js` fuer mehrsprachige Schluessel in `chat.html`
- `buddy_widget.js` in `chat.html`, `control_center.html` und `project_config.html`
- Three.js-CDN in `buddy_landing.html`

## Auffälligkeiten
- Die beiden Hauptseiten sind jeweils selbst grosse Anwendungscontainer ohne Build-Schritt.
- `chat.html` vereint Chat, Team-Panel, Task-Erstellung, Workflow-Panel, Approval-Flaechen, Plattform-Steuerung und Onboarding-Trigger in einer Datei.
- `control_center.html` enthaelt neben Projekt-Board, Team-Gruppierung, Task- und Workflow-Flaechen auch Persistence-Health, Kosten-Widget, Liveboard, Agent-Editor und Automation-Builder in einer Datei.
- Die aktiven Frontends teilen seit dem Host-Neutral-Slice denselben Laufzeit-Resolver `Frontend/bridge_runtime_urls.js` statt separater Hardcodings fuer API- und WS-Basen.
- Das Verzeichnis enthaelt viele `.bak`-Varianten und visuelle Artefakte neben den aktiven UI-Dateien.
- `tasks.html` existiert nur als deaktivierte oder Backup-Variante, waehrend Task-Oberflaechen in andere Seiten integriert sind.
- Die bisherige Frontend-Doku lag archiviert unter `Archiev/docs/frontend/`; der aktive Root-Pfad `docs/frontend/` ist jetzt befuellt und mit realen Browserchecks unterlegt.
- Mehrsprachigkeit ist real vorhanden, aber aktuell nicht seitenweit: `control_center.html`, `project_config.html` und `buddy_landing.html` laden `i18n.js` nicht.

## Bugs / Risiken / Inkonsistenzen
- Die UI-Oberflaeche ist funktional breit, aber organisatorisch schwer zu trennen, weil viele Features in sehr grossen Single Files sitzen.
- Viele Backup-Dateien im gleichen Verzeichnis erschweren die Lesbarkeit des aktiven Frontend-Bestands.
- Die bisherige Dokumentation beschrieb zentrale UI-Bereiche nur teilweise: Plattformsteuerung, Persistence-Health, Liveboard, Avatar-Upload, Workflow-Builder-Deploy und Onboarding-Autostart fehlten oder waren unpraezise.
- Es besteht weiter Archivdrift zwischen aktivem Root-`docs/frontend/` und den archivierten Doku-Dateien unter `Archiev/docs/frontend/`.
- Vertragsdrift war real sichtbar, zum Beispiel bei `PATCH /agents/{id}/parent` statt dokumentiertem `POST`.
- Degradationsdrift im Workflow-Slice ist real sichtbar:
  - die fruehere stille Gleichsetzung von `n8n nicht erreichbar` und `keine Workflows` war real vorhanden
- Die Frontend-Topologie ist fuer die aktiven Hauptseiten nicht mehr hart auf `127.0.0.1`/`localhost` verdrahtet:
  - `Frontend/bridge_runtime_urls.spec.js` lief real erfolgreich (`3 passed`)
  - `Frontend/frontend_clickpath_audit.spec.js` blieb danach real gruen (`5 passed`)
  - der verbleibende Restpunkt liegt nicht mehr in den aktiven Seiten, sondern nur noch in nicht separat belegten Fremdtopologien
  - der aktuelle gesunde Live-Pfad ist wiederhergestellt, aber weitere Workflowfehler koennen weiterhin inhaltlich aus n8n selbst stammen statt aus dem UI-Transport
  - mehrfache Test- und Probe-Deploys koennen die UI sonst als legitime Workflows anzeigen; im aktuellen Slice wurde der Bridge-managed Satz deshalb explizit auf vier aktive Produkt-Workflows bereinigt
- Reale UI-/Layoutbrueche bleiben sichtbar:
  - `chat.html`: der Approval-Footer ist fuer einen schmal gezogenen Sidebar-State (`--sw:88px`) jetzt real stabilisiert; `Frontend/chat_sidebar_footer.spec.js` lief erfolgreich und zeigt keinen Overlap zwischen Approval-Badge und User-Name mehr
  - `chat.html`: die Management-Board-Dots folgen jetzt der Laufzeitwahrheit statt der alten `active`-Doppeldeutigkeit; `Frontend/chat_management_bar_status.spec.js` pruefte real gruen fuer laufend, orange fuer wartend/idle und rot fuer offline/disconnected
  - `control_center.html`: die Fusszeilenmetrik mischt Gesamt-Agentenzahl mit gruener Live-Pulse-Optik und konfundiert dadurch Inventar mit Liveness
  - seitenuebergreifend sind sichtbare Select-/Form-Stile nicht harmonisiert (`task_tracker.html`, `project_config.html`, `buddy.html` zeigen unterschiedliche Hoehen, Radien und Flaechen)
- `buddy_landing.html` bleibt als reale Produktluecke bestehen:
  - die Seite ist heute nicht mehr durch CSP blockiert
  - ihr eigener Start-/Send-Pfad ist jetzt auth-konsistent zum restlichen UI-Modell
  - der Returning-User-Pfad ist real gegen `buddy_running:false` verifiziert und leitet in diesem Zustand nicht mehr vorschnell nach `chat.html?agent=buddy` weiter
  - nach dem Frontdoor-Start kann `GET /agents/buddy` kurz `phantom:true`, `tmux_alive:true`, `active:true` zeigen; der zuletzt erneut verifizierte Live-Zustand konvergierte danach aber zu `phantom:false` und `cli_identity_source=cli_register`
  - `POST /agents/cleanup {"ttl_seconds":0}` entfernt Buddy in diesem Boot-Fenster nicht mehr, solange die `acw_buddy`-Session lebt
  - der Scan-Endpunkt ist inzwischen gegen Parallelaufrufe gehaertet, aber fruehe programmatische Bootstrap-Pfade koennen weiterhin ohne harte sichtbare Choice-Pflicht `existingEngine || recommended || available[0]` ziehen
  - fuer `gemini` und `qwen` ist der aktuelle Setup-Scan bezueglich Login-Zustand noch bewusst konservativ: die Seite zeigt diese Engines als verfuegbar, aber `Auth nicht verifiziert`, weil fuer diesen Slice kein offizieller nicht-interaktiver Probe-Pfad verifiziert wurde

## Offene Punkte
- Welche HTML-Dateien ausser `chat.html`, `control_center.html`, `project_config.html` und `buddy_landing.html` noch produktiv verlinkt oder nur historisch sind, ist nicht durch eine aktive Navigationsmatrix dokumentiert.
- Welche UI-Pfade derzeit im Alltag dominieren, ist ohne Laufzeiterhebung offen.
- Ob die Archiv-Doku unter `Archiev/docs/frontend/` kuenftig entfernt, gespiegelt oder nur historisch markiert wird, ist im aktuellen Working Copy nicht entschieden.

## Offene Punkte
- Ob alle visuell vorhandenen Controls ausser des explizit getesteten Workflow-/n8n-Slices im aktuellen Runtime-Zustand end-to-end beschaltet sind.
- Welche `.bak`-Dateien rein historisch und welche noch operative Referenzpunkte fuer Menschen sind.
