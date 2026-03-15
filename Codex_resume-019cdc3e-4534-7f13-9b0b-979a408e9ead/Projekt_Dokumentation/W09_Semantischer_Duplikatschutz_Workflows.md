# W09_Semantischer_Duplikatschutz_Workflows

## Zweck
Dokumentation des real beobachteten Problems, dass verschiedene Workflow-Deploys fachlich dieselbe Wirkung mehrfach ausloesen koennen, obwohl sie technisch verschiedene Workflow-Objekte sind.

## Scope
`/home/leo/Desktop/CC/BRIDGE/Backend/server.py`, `Backend/workflow_registry.json`, `Backend/event_subscriptions.json`, n8n-Workflows und die Workflow-UIs in `chat.html` sowie `control_center.html`.

## Evidenzbasis
- `/home/leo/Desktop/CC/BRIDGE/Backend/server.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/workflow_registry.json`
- `/home/leo/Desktop/CC/BRIDGE/Backend/event_subscriptions.json`
- `/home/leo/Desktop/CC/BRIDGE/Backend/messages/bridge.jsonl`
- Live-Endpunkte:
  - `GET /workflows`
  - `GET /events/subscriptions`
  - `POST /workflows/deploy-template`
  - `DELETE /workflows/{id}`
  - `POST /task/create`

## Ist-Zustand
Die Bridge verhindert aktuell technische Duplikate nur punktuell:

- Event-Subscriptions werden bei identischem `event_type + webhook_url` dedupliziert.
- Tool-Namen enthalten eine Workflow-ID und sind deshalb nur technisch pro Workflow eindeutig.
- Workflow-Deploys koennen trotzdem mehrfach denselben fachlichen Zweck erzeugen, wenn Name, Template, Trigger oder Wirkung semantisch gleich bleiben, aber als neue Workflow-Objekte angelegt werden.

## Reale Beobachtung
Verifiziert durch Ausfuehrung.

Im Workflow-Integrationslauf am 2026-03-12 entstanden parallel mehrere fachlich gleiche Bridge-managed Workflows:

- mehrere `Bridge: Daily Status Report`
- mehrere `Bridge: Taegliche Chat-Zusammenfassung`
- mehrere `Bridge: Task-Benachrichtigung`

Der erste kollidierte Task-Notification-Deploy `4hGIOryxTltccRhg` blieb zwar `active=false`, hinterliess aber zunaechst trotzdem Subscription-/Tool-Artefakte. Weitere Probe- und Produktdeploys fuehrten dazu, dass ein einzelnes `task.created`-Event mehrfach an den Nutzer gemeldet wurde.

Konkrete Live-Evidenz:

- Vor Cleanup erzeugte ein Probe-Task mehrere userseitige Benachrichtigungen mit demselben fachlichen Inhalt.
- Nach `DELETE /workflows/{id}` fuer kollidierte und probeweise duplizierte Workflows und dem anschliessenden sauberen Redeploy des Wochenreports blieb:
  - `workflow_registry.json`: `4` Bridge-managed Records
  - `event_subscriptions.json`: `1` aktive Event-Subscription
- Danach erzeugte `workflow-clean-probe-1773351020` wieder genau eine userseitige Task-Benachrichtigung.

## Problemdefinition
Das Problem ist nicht primar „gleiche Workflow-ID“, sondern „gleiche fachliche Wirkung“.

Beispiele fuer moegliche semantische Duplikate:

- zwei Task-Benachrichtigungs-Workflows fuer dasselbe `task.created`-Event und denselben Empfaenger
- zwei Daily-Reports mit gleicher Zielgruppe und gleichem Zweck, aber unterschiedlichen Workflow-IDs
- ein Builder-Workflow und ein Template-Workflow, die denselben Event-Fan-out doppelt ausloesen

## Warum das ein Produktproblem ist
Der notwendige Schutz ist nicht rein technisch ableitbar.

Folgende Fragen sind Produktlogik:

- Wann sind zwei Workflows „gleich“?
- Zaehlt derselbe Template-Typ bereits als Duplikat?
- Oder erst gleiche Trigger plus gleiche Zielwirkung?
- Sind gleiche Workflows mit unterschiedlichen Zeitfenstern erlaubt?
- Sind gleiche Workflows mit unterschiedlichem Ziel-Channel erlaubt?
- Soll das System hart blockieren, warnen oder nur markieren?

Ohne diese Definition waere ein automatischer Blocker in `server.py` eine nicht verifizierte Produktentscheidung.

## Aktueller Minimalzustand
Der aktuelle Minimalzustand ist operativ bereinigt, aber nicht produktseitig geloest:

- doppelte Workflows wurden real entfernt
- der kanonische aktive Satz ist reduziert auf:
  - Daily Report
  - Wochenreport
  - Chat-Zusammenfassung
  - Task-Benachrichtigung
- das System besitzt aber noch keinen generischen semantischen Duplicate-Schutz

## Risiken
- Doppelte Reports oder doppelte Task-Benachrichtigungen koennen erneut entstehen
- Nutzer sehen mehrere formal verschiedene, aber fachlich gleiche Workflows
- Registry, Event-Subscriptions und n8n-UI koennen dadurch wieder auseinanderlaufen

## Nicht verifiziert
- Nicht verifiziert, nach welcher finalen Produktregel semantische Gleichheit im Workflow-System definiert werden soll.
- Nicht verifiziert, ob harte Blockierung, Warnung oder nur Sichtbarmachung die richtige Produktentscheidung ist.
