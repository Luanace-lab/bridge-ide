# W04_Tasks_Workflows_Zuweisung_Reservierung_Ownership

## Zweck
Dokumentation des realen Task-, Workflow-, Zuweisungs-, Reservierungs- und Ownership-Modells im `/BRIDGE`-Scope.

Hinweis: Der geplante Worker-W04 wurde real gestartet, aber ohne verwertbaren Abschluss unterbrochen. Diese Datei ist daher ein sequentieller Hauptagent-Fallback auf Basis primaerer Evidenz, nicht auf Basis erfundener Worker-Ergebnisse.

## Scope
`/home/user/bridge/BRIDGE/Backend`, relevante UI-Verbraucher in `Frontend/` und die persistierten Task-/Workflow-Artefakte.

## Evidenzbasis
- `/home/user/bridge/BRIDGE/Backend/server.py`
- `/home/user/bridge/BRIDGE/Backend/tasks.json`
- `/home/user/bridge/BRIDGE/Backend/workflow_registry.json`
- `/home/user/bridge/BRIDGE/Backend/automations.json`
- `/home/user/bridge/BRIDGE/Backend/scope_locks.json`
- `/home/user/bridge/BRIDGE/Backend/whiteboard.json`
- `/home/user/bridge/BRIDGE/Backend/board_api.py`
- `/home/user/bridge/BRIDGE/Backend/workflow_builder.py`
- `/home/user/bridge/BRIDGE/Frontend/chat.html`
- `/home/user/bridge/BRIDGE/Frontend/control_center.html`

## Ist-Zustand
Das reale Ownership- und Arbeitsmodell ist datei- und endpointgetrieben:

- Tasks leben in `Backend/tasks.json` als Objekt, dessen Schluessel Task-UUIDs sind.
- Projekte und Team-Zuordnung kommen primar aus `Backend/team.json`; `board_api.py` projiziert daraus Board-Strukturen mit `projects[].team_ids`, Teams und Mitgliedern.
- Scope-Reservierungen und koordinative Sperren liegen in `Backend/scope_locks.json`.
- Whiteboard-Status und Ergebnis-Signale liegen in `Backend/whiteboard.json`.
- Workflows werden in `Backend/workflow_registry.json` persistiert.
- Automationen werden in `Backend/automations.json` persistiert.

Momentaufnahme aus den persistierten Artefakten:

- `tasks.json`: 2279 Eintraege
- Task-Statusverteilung: 2029 `failed`, 231 `done`, 19 `deleted`
- `workflow_registry.json`: aktuell `4` Bridge-persistierte Workflow-Eintraege; jeder Record ist template-basiert und enthaelt `workflow_id`, `bridge_spec`, optional `bridge_subscription`, optional `tool_registered` und `compiled_workflow`
- `automations.json`: 4 persistierte Automationen; 2 davon sind aktuell `active=true`
- `scope_locks.json`: 0 aktive Reservierungen
- `whiteboard.json`: 8 Eintraege; nur 1 aktueller Eintrag ist direkt an eine `task_id` gebunden
- `event_subscriptions.json`: aktuell `1` persistierte Event-Subscription; sie liegt nicht in `workflow_registry.json`, sondern in einem separaten Store

## Datenfluss / Kontrollfluss
Task-Fluss:

1. `POST /task/create` in `server.py` validiert Titel, Team, Prioritaet, Labels, Attachments und optional `assigned_to`.
2. Beim Create werden Task-Objekt, State-History und Persistenz geschrieben; danach folgen Fan-out-Nebenwirkungen: `ws_broadcast("task_created")`, `append_message(...)` an den Assignee, Event-Bus-Emission, optional Mode-Wechsel und `ensure_agent_online`.
3. `POST /task/{id}/claim`, `/ack`, `/done`, `/fail`, `/verify` treiben den Lebenszyklus weiter.
4. `POST /task/{id}/done` erzwingt fuer `success` und `partial` sowohl `result_summary` als auch ein `evidence`-Objekt; fuer `code_change` ist zusaetzlich `reviewed_by` Pflicht.
5. Beim Done-Pfad folgen weitere Seiteneffekte: WebSocket-Event, Event-Bus, Whiteboard-Eintrag, Scope-Unlock und Benachrichtigung an den Task-Ersteller.
6. `GET /task/queue` liefert `_claimability` nur dann frisch berechnet, wenn `?check_agent=` gesetzt ist; ohne diesen Query-Parameter bleiben bereits persistierte `_claimability`-Felder aus `tasks.json` unveraendert im Snapshot sichtbar.
7. Die aktuell sichtbaren Frontend-Schreibpfade decken nur einen Teil des Lebenszyklus ab: `chat.html` erzeugt Tasks, `control_center.html` erzeugt, aendert, loescht und liest Task-History, aber keine der beiden Seiten ruft `claim`, `ack`, `done`, `fail` oder `verify` auf.

Workflow-Fluss:

1. `control_center.html` besitzt den vollstaendigeren Workflow-Pfad mit Bridge-Builder, Definition-Reload und Template-Deploy; `chat.html` bietet nur Suggestions, Template-Deploy und Toggle/Delete fuer bereits sichtbare Workflows.
2. `workflow_builder.py` kompiliert Bridge-Spezifikationen in n8n-Payloads; unterstuetzte kanonische Bridge-Knoten sind `bridge.trigger.schedule`, `bridge.trigger.event`, `bridge.action.send_message`, `bridge.action.create_task` und `n8n.raw`.
3. `bridge.action.create_task` erzeugt HTTP-Requests auf `/task/create`; Workflow-Ausfuehrung bleibt damit datenmaessig an den Task- und Nachrichtenschichten des Servers gekoppelt.
4. Der aktuelle Read-Pfad `GET /workflows` liest jedoch nicht aus `workflow_registry.json`, sondern proxyt live gegen n8n und mischt nur Registry-Metadaten in die Antwort. Persistenz in `workflow_registry.json` ist damit kein vollstaendig eigenstaendiger Read-SoT.
5. Live-Nachtrag 2026-03-12:
   - `GET /workflows` lieferte im aktuellen Runtime-Zustand wieder `200`
   - `GET /n8n/executions?limit=5` lieferte ebenfalls `200`
   - `GET /events/subscriptions` zeigte nach dem Duplicate-Cleanup `{"count": 1}`; Bridge-managed Event-Subscriptions sind also aktiv, aber nicht mehr mehrfach fuer denselben Produktfall angehaeuft
   - `workflow_registry.json` und `event_subscriptions.json` beschreiben unterschiedliche Teilmengen derselben Workflow-Welt: Bridge-Metadaten vs. Webhook/Event-Fan-out
   - zusaetzlicher Live-Befund: `POST /send` ohne `X-Bridge-Token` liefert unter `BRIDGE_STRICT_AUTH=true` real `401 {"error":"authentication required"}`
   - `python3 Backend/repair_n8n_bridge_auth.py --dry-run --limit 250` liefert im aktuellen Endzustand `repaired_count=0`; aktive n8n-Workflows mit lokalen Bridge-Write-Pfaden tragen derzeit also die erwarteten Bridge-Header
  - vier Workflows wurden im aktuellen Integrationslauf ueber `POST /workflows/deploy-template` real konfiguriert und verifiziert:
    - `TXDHkBWw2JxHjt88` `Bridge: Daily Status Report`
    - `LNX09wVWFu3weiil` `Bridge: Wochenreport`
    - `XuyJQMbdQSqUujSP` `Bridge: Taegliche Chat-Zusammenfassung`
    - `ddvmNgWDKGlffSGd` `Bridge: Task-Benachrichtigung`
   - der erste kollidierte Task-Notification-Deploy `4hGIOryxTltccRhg` blieb `active=false` und wurde spaeter bewusst per `DELETE /workflows/{id}` samt Subscription-/Tool-Cleanup entfernt
  - Weekly Report wurde danach real zeitgetriggert verifiziert:
    - erster Testlauf `uG9peP8nowlQGFfc` zeigte den realen Zaehlfehler `Agents: 0/59 online`
    - Ursache: Template las `/agents` statt `/status`
    - korrigierter Live-Deploy `LNX09wVWFu3weiil` lief erfolgreich in Execution `1223`
    - Bridge-Nachricht `70951` enthielt danach korrekt `Agents: 4/4 online`
  - die zusaetzlich entstandenen Probe- und Doppel-Deploys wurden ebenfalls geloescht; `workflow_registry.json` ist damit wieder auf einen kanonischen Bridge-managed Satz von vier Workflows reduziert
  - `Frontend/chat_workflow_buttons.spec.js` verifizierte zusaetzlich die sichtbaren Workflow-Aktionen in `chat.html` gegen den Live-Backendpfad

Ownership- und Reservierungsfluss:

1. Team-/Projekt-Zuordnung kommt aus `team.json` plus `board_api.py`-Projektion.
2. File-Ownership und Koordinationskonflikte werden ueber Scope-Locks getrennt modelliert.
3. Task-Abschluss loest Scope-Unlocks aus; Ownership ist damit nicht nur personell, sondern auch dateibezogen modelliert.

## Abhängigkeiten
- `server.py` als zentraler Lebenszyklus- und Persistenzkoordinator
- `board_api.py` fuer Projekt-/Team-Projection
- `workflow_builder.py` und n8n fuer Workflow-Kompilation und -Ausfuehrung
- `chat.html` und `control_center.html` als Hauptverbraucher fuer Task-, Team-, Workflow- und Lock-Zustaende
- JSON-/JSONL-Dateien als persistente Stores

## Auffälligkeiten
- Der Task-Done-Pfad ist fan-out-stark: Persistenz, Whiteboard, Event-Bus, Scope-Unlock und Messaging liegen in einem Kontrollpfad.
- `workflow_builder.py` behandelt Workflows als kanonische Bridge-Spezifikationen, waehrend n8n nur Ausfuehrungsziel ist.
- `board_api.py` synthetisiert zusaetzlich ein Management-Team aus `level <= 1`; Ownership ist damit nicht nur dateibasiert, sondern auch durch Hierarchieprojektion beeinflusst.
- In den UI-Pfaden werden Aufgaben, Teamboards, Workflows und Locks parallel dargestellt, aber nicht symmetrisch veraendert: Scope-Locks sind in den geprueften Frontends nur lesbar, und der operative Task-Lifecycle jenseits von Create/Patch/Delete bleibt API-/MCP-zentriert.
- `workflow_registry.json` speichert heute nicht nur eine ID-Liste, sondern Bridge-spezifische Zusatzmetadaten; zugleich bleibt die UI-Liste von einer erreichbaren n8n-API abhaengig.

## Bugs / Risiken / Inkonsistenzen
- Die aktuelle Task-Snapshot-Verteilung zeigt keine offenen `created`-, `claimed`- oder `acked`-Tasks, aber sehr viele `failed`-Tasks. Das ist ein reales Zustandsbild, aber keine Aussage ueber beabsichtigten Betriebsmodus.
- In mehreren realen Beispieltasks ist `_claimability.reason` auf `state=acked` gesetzt, obwohl der persistierte Endzustand `failed` ist. Das ist eine verifizierte Snapshot-Inkonsistenz; die API korrigiert `_claimability` nur im Pfad `GET /task/queue?check_agent=...`.
- Der Done-Pfad koppelt viele Seiteneffekte; das erhoeht Risiko fuer Teilzustandsdrift zwischen Task-Store, Whiteboard, Scope-Locks und Benachrichtigungen.
- Workflow- und Automation-Funktionen existieren real, aber die Read-/Write-SoT ist nicht einheitlich: Workflows werden fuer die UI live aus n8n gelesen, waehrend Bridge-Zusatzmetadaten in `workflow_registry.json` und Event-Fan-out-Zustaende getrennt in `event_subscriptions.json` leben; Automationen werden parallel aus dem Automation-Subsystem geladen.
- n8n ist im aktuellen Projektzustand wieder erreichbar, aber die Bridge-managed Automationskette ist noch nicht vollstaendig belastbar:
  - `~/.config/bridge/n8n.env` enthaelt `N8N_BASE_URL=http://localhost:5678` und einen gesetzten `N8N_API_KEY`
  - `GET /workflows` und `GET /n8n/executions?limit=5` liefern real `200`
  - `GET /events/subscriptions` lieferte nach Cleanup `count=1`
  - Bridge-Schreibpfade wie `/send` und `/task/create` bleiben unter Strict Auth headerpflichtig; aktive Live-Workflows sind im aktuellen Zustand repariert, aber der Deploy-Pfad bleibt auf die Laufzeitinjektion aus `server._inject_bridge_workflow_auth_headers()` angewiesen
- Verifiziert durch Ausfuehrung:
  - Daily Report `TXDHkBWw2JxHjt88` lief erfolgreich in Execution `1191`
  - Chat Summary `XuyJQMbdQSqUujSP` lief erfolgreich in Execution `1195`
  - Task Notification `ddvmNgWDKGlffSGd` lief nach Cleanup erfolgreich in Execution `1210`
  - ein frischer Probe-Task `workflow-clean-probe-1773351020` erzeugte danach genau eine userseitige Task-Benachrichtigung statt doppelter Meldungen
- Reservierung/Ownership ist auf mehrere Schichten verteilt: Team-Hierarchie, Task-Assignee, Scope-Lock, Whiteboard, Agent-Status.
- Die geprueften Frontends bilden Ownership nur teilweise ab: fuer Tasks existieren Create/Patch/Delete/History, fuer Scope-Locks nur Read-Views. Damit ist der sichtbare UI-Pfad fuer Ownership-Konflikte unvollstaendig.

## Offene Punkte
- Ob die hohe Zahl fehlgeschlagener Tasks fachlich erwartetes Althistorienmaterial oder operativ problematischer Rueckstand ist, ist aus dem Snapshot allein nicht ableitbar.
- Welche Ownership-Regeln im Alltag vorrangig gelten, wenn Team-Zuordnung, Task-Zuordnung und Scope-Lock kollidieren, ist nicht in einem kanonischen Einzelartefakt beschrieben.
- Ob Workflow- und Automation-Objekte in der Laufzeit haeufiger existieren als die aktuelle Persistenzmomentaufnahme zeigt, ist offen.
- Ob der Workflow-Read-Pfad bei n8n-Ausfall bewusst fail-closed sein soll oder ob `workflow_registry.json` kuenftig als degradierter Fallback dienen muss, ist im aktuellen Codepfad nicht geklaert.
- Ob `docker-compose.yml` kuenftig einen n8n-Dienst explizit mitstarten soll oder ob n8n bewusst extern bleiben soll, ist im aktuellen Tree nicht dokumentiert.
- Ob Bridge-managed Template-Deploys kuenftig gegen doppelte Namen oder doppelte Semantik automatisch dedupliziert werden sollen, ist weiterhin eine Produktentscheidung ausserhalb dieses Minimalfix-Slices.

## Offene Punkte
- Ob die aktuelle Laufzeit dieselbe Task-/Workflow-Lage wie die Dateien auf Disk zeigt.
- Wie haeufig Scope-Lock-Konflikte, Requeues oder Verify-Pfade im Live-Betrieb auftreten.
- Ob es ausserhalb von `chat.html` und `control_center.html` weitere produktive UI-Pfade fuer `claim`, `ack`, `done`, `fail`, `verify` oder `scope/lock` gibt.
