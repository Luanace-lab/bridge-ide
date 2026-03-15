# Mobile Route Audit

Stand: 2026-03-13

## Zweck

Diese Notiz dokumentiert den real ausgefuehrten Mobile-Audit fuer `Frontend/mobile_buddy.html`.
Sie beantwortet zwei konkrete Fragen:

1. Welche Felder und Trigger bleiben bereits innerhalb der mobilen Surface?
2. Welche Navigationen verlassen den Mobile-Scope und landen noch auf Desktop-Seiten?

Wichtig fuer den weiteren Ausbau:

- dieser Audit aendert keine Originalseiten wie `chat.html`, `control_center.html`, `task_tracker.html` oder `project_config.html`
- die Zielrichtung ist mobile-native Ersatzflaechen in neuen Dateien

## Verifikation

Verifiziert durch Ausfuehrung:

- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/mobile_buddy_route_audit.spec.js --reporter=line`
  - Ergebnis: `1 passed`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/mobile_projects.spec.js --reporter=line`
  - Ergebnis: `1 passed`
- JSON-Artefakt:
  - `/tmp/mobile_buddy_route_audit.json`
- Screenshots der Zielseiten:
  - `/tmp/mobile_buddy_route_audit/*.png`

Viewport des Audits:

- `430 x 932`

## In-Page-Befunde

| Trigger in `mobile_buddy.html` | Ergebnis | Mobile-native im aktuellen Zustand | Evidenz |
| --- | --- | --- | --- |
| Logo / Drawer | oeffnet den mobilen Drawer mit Uebersicht, Gruppierungen und Settings-Zugang | Ja | `drawer.open` in `/tmp/mobile_buddy_route_audit.json` |
| `Tasks -> Buddy fragen` | fuellt den Management-Composer und bleibt auf `mobile_buddy.html` | Ja | `summary.tasks.prompt` |
| `Top 3 Tasks` | fuellt den Management-Composer und bleibt auf `mobile_buddy.html` | Ja | `prompt.top3` |
| Management-Sendefeld | kein belastbarer `/send`-Response im Audit, sichtbarer Feed-Zustand bleibt stale | Teilweise / Blocker | `management.send` mit `responseStatus:null` |
| Team-Picker | oeffnet Teamliste mit `10` Teams | Ja | `teamPicker.open` |
| Team-Auswahl | setzt aktives Team auf `Bridge IDE / Kernteam`, Zielkontakt `Ordo` | Ja | `team.select` |
| Agenten-Disclosure | oeffnet Mitgliedsleiste mit `7` Agenten | Ja | `memberToggle.open` |
| Team-Sendefeld | `POST /send -> 201`, User-Nachricht erscheint im Team-Feed | Ja | `team.send` |
| Buddy-Widget auf/zu | kompakte Sprechblase oeffnet und schliesst innerhalb des Mobile-Shells | Ja | `widget.open`, `widget.close` |
| Buddy-Widget senden | User-Bubble erscheint im Widget | Ja | `widget.send` |
| Settings | Sheet oeffnet, `black` wird in `bridge_theme` persistiert | Ja | `settings.black` |
| Buddy neu verbinden | Status bleibt im Audit auf `Bereit` | Ja | `settings.reconnect` |

## Route-Ziele aus `mobile_buddy.html`

| Quelle | Reales Ziel nach Klick | Mobile-native | Mobile-Befund |
| --- | --- | --- | --- |
| `Tasks -> Tracker` | `mobile_tasks.html` | Ja | dedizierte Mobile-Taskliste; verifiziert ueber `Frontend/mobile_tasks.spec.js` inkl. Navigation aus `mobile_buddy.html` |
| `Projekte -> Projektstart` | `mobile_projects.html` | Ja | kein horizontales Overflow (`430 == 430`), einspaltige Mobile-Projektflaeche mit Scan, Projektanlage, Export und Teamstart |
| `Workflows -> Workflows` | `control_center.html?tab=workflows` | Nein | landet auf Desktop-Control-Center; im Audit blockierte zusaetzlich das Welcome-Modal |
| Drawer `Chat` | `chat.html` | Nein | verlaesst Mobile-Root und springt in die originale Browser-Chatseite |
| Drawer `Control Center` | `control_center.html` | Nein | Desktop-Operationsseite, kein eigener Mobile-Screen |
| Drawer `Task Tracker` | `mobile_tasks.html` | Ja | mobile-native Taskliste, Detail-Sheet, Export und Filter |
| Drawer `Neues Projekt` | `mobile_projects.html` | Ja | identisch zum Summary-Link, mobile-native Projektflaeche ohne horizontalen Overflow |
| Drawer `Aufgaben` | `mobile_tasks.html#aufgaben` | Ja | teilt sich denselben mobilen Task-Screen statt Desktop-Control-Center-Tab |
| Drawer `Teams & Hierarchie` | `control_center.html?tab=hierarchie` | Nein | Desktop-Control-Center-Tab; im Audit zusaetzlich Welcome-Modal |
| Drawer `Workflows` | `control_center.html?tab=workflows` | Nein | Desktop-Control-Center-Tab; nicht mobile-native |

## Verifizierte Schlussfolgerung

Der aktuelle Mobile-Scope ist nicht mehr nur auf `mobile_buddy.html` begrenzt.

Sobald der Nutzer aus dem Root heraus in den Projektpfad navigiert, bleibt er jetzt im mobilen Scope.
Alle anderen Drawer-/Summary-Exits landen weiterhin auf Originalseiten der Browser-App.
Damit gilt:

- `mobile_buddy.html` ist bereits ein echter mobiler Root
- `mobile_projects.html` ist ein echter mobiler Folge-Screen
- `mobile_tasks.html` ist jetzt der zweite echte mobile Folge-Screen
- `Workflows`, `Teams`, `Control Center` und `Chat` sind noch keine Mobile-App

## Konkrete Mobile-Folgescreens aus diesem Audit

Die aktuellen Desktop-Ziele muessen durch neue Mobile-Dateien ersetzt werden, ohne die Originalseiten umzubauen:

- `mobile_workflows.html`
  - ersetzt den Workflow-Zugriff aus `control_center.html?tab=workflows`
- `mobile_teams.html`
  - ersetzt `control_center.html?tab=hierarchie`
- `mobile_control_center.html`
  - optional als verdichtete Operations-Uebersicht, wenn `Control Center` im Drawer als eigener Mobile-Screen bestehen soll

## Produktentscheidung aus der Nutzerintention

Die Nutzerintention ist jetzt klar:

- Buddy bleibt die zentrale Steuerfigur
- Mobile-Folgescreens muessen verdichtet und nativ sein
- Funktionen duerfen nicht verschwinden
- Original-BRIDGE-Dateien bleiben unangetastet

Daraus folgt fuer die aktuelle Navigation:

- `Chat` sollte auf Mobile nicht mehr zu `chat.html` fuehren
- `Workflows`, `Teams`, `Aufgaben` und `Tracker` duerfen auf Mobile nicht dauerhaft auf Desktop-HTML verlinken
- `Projektstart` und Drawer `Neues Projekt` sind jetzt auf `mobile_projects.html` umgehaengt
- `Tasks -> Tracker`, Drawer `Task Tracker` und Drawer `Aufgaben` sind jetzt auf `mobile_tasks.html` umgehaengt

## Aktive Blocker aus dem Audit

1. `management.send`
   - im Audit kein belastbarer `/send`-Response
   - der Management-Composer braucht vor weiterer Mobile-Portierung eine gezielte Verifikation bzw. Reparatur
2. `control_center.html?tab=workflows`
   - im Mobile-Viewport nicht als nativer Workflow-Screen nutzbar
3. `control_center.html?tab=hierarchie`
   - im Mobile-Viewport kein brauchbarer Ersatz fuer eine native Team-/Hierarchieansicht

## Naechster sauberer Slice

Der naechste kleine saubere Mobile-Slice ist nicht weiteres Root-Styling, sondern der naechste Ersatzscreen:

1. `mobile_workflows.html` als naechster echter Folge-Screen
2. danach `Teams & Hierarchie` mobil ersetzen
3. Originalseiten unveraendert lassen
