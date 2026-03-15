# Mobile Migration Matrix

Stand: 2026-03-13

## Zweck

Diese Datei ist die kanonische Arbeitsgrundlage fuer die Mobile-App-Migration.
Sie arbeitet bewusst rueckwaerts vom gewuenschten Mobile-Root aus:

1. Standardisierte Buddy-Ansicht als Mobile-Root
2. Chat als primärer Arbeitsraum
3. Task- und Projekt-Flows als sekundäre Mobile-Screens
4. Control-Center-Funktionen als verdichtete Drilldowns statt 1:1-Desktopseite
5. Alt-/Design-/Backup-Seiten nicht still mitschleppen

## Verifizierte Runtime-Fakten

- Das aktive Frontend ist plain HTML/CSS/JS ohne Build-Step.
- Die BRIDGE liefert `Frontend/*.html` statisch aus; jedes `.html` im Ordner ist direkt oeffentlich erreichbar, wenn der Pfad bekannt ist.
- Root-Route `/` zeigt aktuell auf `control_center.html`, nicht auf Buddy.
- `Frontend_persönlich/` enthaelt derzeit keine produktiven UI-Dateien, nur Agent-Kontext.

## Mobile-Root-Entscheidung

Die Mobile-App startet nicht vom aktuellen Desktop-Root `/`, sondern von einer adaptierten Buddy-Standardansicht.

Quelle dafuer:

- funktional: `buddy_landing.html`
- gestalterisch / interaction reference: Screenshot-Zielbild plus `buddy_design*.html`
- kritisch zu haerten vor echter Uebernahme:
  - `Backend/team.json` markiert `buddy` aktuell als `active: false`
  - dedizierter Rueckkehrer-Startpfad hat am 2026-03-13 reproduzierbar `POST /agents/buddy/start -> 500`

## Dispositions-Definitionen

- `root`: Mobile-Startscreen
- `screen`: eigener Mobile-Screen
- `drilldown`: kein eigener Root-Tab, sondern Unterseite / Overlay / Sheet
- `merge`: Funktionalitaet in anderen Screen integrieren, Seite selbst nicht separat uebernehmen
- `web-only`: fuer Desktop/Web behalten, nicht Teil der Mobile-App
- `design-reference`: nur als Gestaltungsreferenz behalten
- `archive`: aus dem oeffentlich servierten `Frontend/` entfernen

## Vollstaendige Seitenmatrix

| Seite | Aktuelle Rolle | Mobile-Disposition | Naechste Behandlung |
| --- | --- | --- | --- |
| `mobile_buddy.html` | neuer mobiler Root-Prototyp fuer Buddy | `root` | als kanonische Mobile-Startoberflaeche weiterhaerten |
| `mobile_projects.html` | neuer mobiler Projekt-Screen als Ersatz fuer `project_config.html` | `screen` | erster verifizierter Folge-Screen; Routing in `mobile_buddy.html` bereits umgehaengt |
| `buddy_landing.html` | Buddy-Frontdoor, Onboarding, Send/Poll-Loop | `root` | In Mobile-Root uebernehmen und technisch haerten |
| `chat.html` | Hauptarbeitsraum fuer Messaging, Workflows, Panels | `screen` | Als primären Arbeitsscreen mobile-first zerlegen |
| `task_tracker.html` | Listen-/Detail-Ansicht fuer Tasks | `screen` | Desktop-SoT behalten; mobile Ersatzflaeche ist jetzt `mobile_tasks.html` |
| `project_config.html` | Projekt- und Runtime-Wizard | `screen` | Desktop-SoT behalten; mobile Ersatzflaeche ist jetzt `mobile_projects.html` |
| `control_center.html` | breite Desktop-Operationsflaeche | `drilldown` | in mehrere Mobile-Subscreens aufsplitten |
| `landing.html` | Marketing-/Web-Landingpage | `web-only` | fuer Web behalten, nicht als In-App-Screen fuehren |
| `buddy_designs.html` | Design-Uebersicht | `design-reference` | nur als Referenz behalten |
| `buddy_design_focus.html` | Designvariante A | `design-reference` | nur als Referenz behalten |
| `buddy_design_tabs.html` | Designvariante B | `design-reference` | nur als Referenz behalten |
| `buddy_design_quiet.html` | Designvariante C | `design-reference` | nur als Referenz behalten |
| `mockup_reply.html` | isolierter Mockup-Screen | `design-reference` | nur als Referenz behalten |
| `buddy_onboarding.html` | frueher Buddy-Onboarding-Stand | `merge` | relevante Copy/Steps in Mobile-Root pruefen, Seite selbst nicht uebernehmen |
| `buddy_onboarding_network.html` | Netzwerk-/Onboarding-Experiment | `merge` | nur Inhalte pruefen, keine Route uebernehmen |
| `buddy_onboarding_v1_network.html` | frueher Onboarding-Stand | `merge` | nur Inhalte pruefen, keine Route uebernehmen |
| `buddy_onboarding_v2_network.html` | frueher Onboarding-Stand | `merge` | nur Inhalte pruefen, keine Route uebernehmen |
| `buddy_onboarding_v3_living.html` | spaeterer Onboarding-Stand | `merge` | nur Inhalte pruefen, keine Route uebernehmen |
| `buddy_onboarding_v3_chaos_backup.html` | Backup-Snapshot | `archive` | aus `Frontend/` entfernen |
| `buddy_onboarding_v3_corona_backup.html` | Backup-Snapshot | `archive` | aus `Frontend/` entfernen |
| `buddy_onboarding_v3_maxsharp_backup.html` | Backup-Snapshot | `archive` | aus `Frontend/` entfernen |
| `buddy_onboarding_v3_pokemon_backup.html` | Backup-Snapshot | `archive` | aus `Frontend/` entfernen |
| `buddy_onboarding_v3_round_backup.html` | Backup-Snapshot | `archive` | aus `Frontend/` entfernen |
| `buddy_onboarding_v3_sharp_backup.html` | Backup-Snapshot | `archive` | aus `Frontend/` entfernen |

## Erste Mobile-Informationsarchitektur

- Root: Buddy Standard View
- Primäre Navigation im Drawer:
  - Buddy Home
  - Chat
  - Control Center
  - Task Tracker
  - Neues Projekt
- Sekundaere Navigation / Drilldowns aus Desktop-Control-Center:
  - Health / Activity
  - Teams / Org Chart
  - Workflows / Automations
  - Alerts / Scope Locks / Costs
- Erste mobile Sidebar-Gruppierung:
  - `Start`: Buddy Home
  - `Arbeitsraeume`: Chat, Control Center, Task Tracker, Neues Projekt
  - `Bridge`: Aufgaben, Teams & Hierarchie, Workflows ueber `control_center.html?tab=...`
  - `System`: lokale Settings-Sheet plus Buddy-Reconnect

## Harte Befunde, die vor UI-Portierung geklaert werden muessen

1. Buddy ist aktuell in `Backend/team.json` deaktiviert.
2. Die dedizierte Buddy-Returning-User-Strecke ist heute nicht stabil genug fuer einen Mobile-Root.
3. `mobile_buddy.html` behandelt Startfehler bewusst fail-closed; dieser Pfad muss spaeter mit realem Buddy-Lifecycle harmonisiert werden.
4. Zu viele historische HTML-Dateien liegen noch im produktiv servierten `Frontend/`.
5. `control_center.html` ist als Desktop-Seite zu breit fuer direkte 1:1-Uebernahme.
6. Der verifizierte Routen-Audit aus `mobile_buddy.html` zeigte initial: alle Navigationsziele verliessen den Mobile-Scope und landeten auf Desktop-Dateien.
7. Nach Slice 13 sind `Projektstart` / Drawer `Neues Projekt` auf `mobile_projects.html` und `Tasks -> Tracker` / Drawer `Task Tracker` / Drawer `Aufgaben` auf `mobile_tasks.html` umgehaengt; offen bleiben weiterhin `control_center.html?tab=hierarchie`, `control_center.html?tab=workflows`, `control_center.html` und `chat.html`.

## Reproduzierbare Verifikation fuer diese Matrix

Ausgefuehrt am 2026-03-13:

- `curl -i -s http://127.0.0.1:9111/health`
  - Ergebnis: `200`, Status `degraded`, Server/WebSocket/Watcher `ok`, Forwarder `warn`
- `curl -i -s http://127.0.0.1:9111/`
  - Ergebnis: `200`, HTML-Titel `Bridge – Control Center`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/frontend_clickpath_audit.spec.js --reporter=line`
  - Ergebnis: `5 passed`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/buddy_frontdoor_returning_user.spec.js --reporter=line`
  - Ergebnis: `1 failed`
  - Fehler: `POST /agents/buddy/start` antwortete mit `500`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/mobile_buddy_route_audit.spec.js --reporter=line`
  - Ergebnis: `1 passed`
  - Artefakte: `/tmp/mobile_buddy_route_audit.json`, `/tmp/mobile_buddy_route_audit/*.png`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/mobile_projects.spec.js --reporter=line`
  - Ergebnis: `1 passed`

## Naechster kleine Slice

Slice 02 baute die echte Mobile-Standardansicht als erste produktive Mobile-Oberflaeche.

Ziel fuer Slice 02:

- eigener Mobile-Screen fuer Buddy
- visuell an Screenshot orientiert
- funktional nur der kleinste sichere Umfang:
  - Nachrichtenliste
  - Eingabefeld
  - Send
  - Zustandsanzeige
- noch keine volle Desktop-Feature-Portierung

Stand dieses Slices:

- `Frontend/mobile_buddy.html` angelegt
- `Frontend/mobile_buddy.spec.js` als Live-Smoke-Test angelegt

## Slice 03 - Navigation Shell

Ziel fuer Slice 03:

- top-left mobile Drawer statt versteckter Desktop-Sidebar-Kopie
- echte Verweise auf die vorhandenen BRIDGE-Hauptseiten
- tiefe Desktop-Control-Plane-Pfade als verdichtete Drilldowns
- lokale Settings-Sheet statt leerer Settings-Attrappe

Stand dieses Slices:

- `Frontend/mobile_buddy.html` erweitert um Drawer, Settings-Sheet und Theme-Persistenz
- `Frontend/mobile_buddy.spec.js` erweitert um Drawer-/Settings-Klickpfad

## Slice 04 - Buddy-first Briefing

Ziel fuer Slice 04:

- Buddy bleibt Root und zentrale Steuerfigur
- andere Bereiche erscheinen zuerst nur als verdichtete Lage statt als volle Seitenwechsel
- Funktionen bleiben sichtbar, aber komprimiert und ueber Buddy ansteuerbar

Stand dieses Slices:

- `Frontend/mobile_buddy.html` erweitert um Live-Briefing fuer Tasks, Projekte, Workflows und einen kompakten Task-Feed
- direkte Buddy-Prompts eingefuehrt statt nur statischer Navigation
- Workflow-Karte zeigt degradierte n8n-Lage explizit statt sie zu verstecken

## Slice 05 - Kanonische Browser-Themes

Ziel fuer Slice 05:

- Mobile nutzt keine eigenen Theme-Namen oder Farbwerte
- Theme-Wechsel bleibt identisch zur Browser-App
- dieselbe lokale Theme-Persistenz wie im bestehenden Frontend

Stand dieses Slices:

- `Frontend/mobile_buddy.html` nutzt jetzt die aus `chat.html` / `control_center.html` / `project_config.html` gelesenen Themes `warm`, `light`, `rose`, `dark`, `black`
- `bridge_mobile_theme` wurde entfernt; Mobile nutzt jetzt denselben `bridge_theme`-Key wie das Browser-Frontend

## Slice 06 - Drawer-Overview plus gestapelte Boards

Ziel fuer Slice 06:

- verdichtete Lage nicht mehr im Chat-Viewport rendern
- Mobile-Chat optisch an `chat.html` angleichen, aber fuer kleine Displays vertikal stapeln
- Buddy als obere Management-Figur halten und das Team darunter nur verdichtet sichtbar machen

Stand dieses Slices:

- `Frontend/mobile_buddy.html` nutzt jetzt eine gestapelte Hauptflaeche aus `Management-Board` oben und `Team-Board` unten
- die verdichtete Lage fuer Tasks, Projekte, Workflows und letzte Tasks wurde aus dem Chat in den Drawer verschoben
- das obere Board rendert Buddy-Dialog aus `/history` plus `/send`
- das untere Board rendert einen verdichteten Team-Feed aus `/board/projects`, `/team/orgchart` und `/history`
- Team-Nachrichten gehen im Mobile-Slice bewusst an den aktuell ermittelten Team-Lead statt an die volle Desktop-Zielmatrix
- der permanente Namensbalken im unteren Board ist entfernt; Teams und Agenten sind jetzt getrennte, standardmaessig eingeklappte Disclosure-Flaechen
- die Warm-Farblogik folgt jetzt direkt `chat.html`: `--bg:#fbf8f1`, Board-Huelle `#fdfcfa`, Chatflaechen `#ffffff`, Agent-Bubbles mit derselben Ridge-/Border-/Shadow-Kombination wie im Browser-Chat
- der sichtbare Header ist auf das Bridge-Logo reduziert; Titel-, Unterzeilen- und Status-Text sind nicht mehr im Mobile-Root, damit die Chatflaeche direkt unter dem Logo beginnt
- der Mobile-Shell selbst ist jetzt dichter und produktnutzbarer: weniger Rahmenflaeche, hoeheres Gewichtsverhaeltnis fuer das `Management-Board`, kompaktere Composer-Zeilen, leere Zustaende als Card statt als weisse Leere und ein tiefer gestartetes Buddy-FAB

## Slice 07 - Logo-Drawer plus Buddy-Einzelchat

Ziel fuer Slice 07:

- den Drawer nicht mehr ueber einen eigenen Hamburger, sondern ueber das kanonische Bridge-Logo oeffnen
- den mobilen Buddy-Einzelchat nicht als neue Sonderlogik erfinden, sondern das bestehende `buddy_widget.js` aus `chat.html` wiederverwenden
- das Widget auf Mobile standardmaessig eingeklappt halten, aber weiterhin beweglich und direkt auf Buddy fokussiert anbieten

Stand dieses Slices:

- `Frontend/mobile_buddy.html` nutzt jetzt `ace_logo.svg` oben links als Drawer-Trigger
- `Frontend/mobile_buddy.html` bindet `Frontend/buddy_widget.js` ein und schaltet auf Mobile nur das initiale Auto-Aufpoppen ab
- das Buddy-Widget bleibt beweglich, laesst sich per Icon auf- und zuklappen und nutzt weiter den dedizierten Buddy-DM-Pfad
- `Frontend/buddy_widget.js` zieht Buddy-Antworten nach dem Senden jetzt zusaetzlich per History-Poll nach, statt ausschliesslich auf WebSocket-Zustellung zu warten

## Slice 08 - Buddy-Cloud im App-Shell

Ziel fuer Slice 08:

- das Buddy-Icon standardmaessig auf der mobilen Oberflaeche und nicht ausserhalb des App-Rahmens halten
- den Buddy-Einzelchat als kompakte Nachrichtenwolke statt als Desktop-Floating-Window darstellen
- das Icon weiter beweglich halten, aber die geoeffnete Wolke direkt am Icon verankern

Stand dieses Slices:

- `Frontend/buddy_widget.js` unterstuetzt jetzt einen `cloudMode` mit `mountSelector`, eigenem Storage-Namespace und surface-lokalem Positionieren
- `Frontend/mobile_buddy.html` mountet das Buddy-Widget in `#shell` und startet es mit einer mobilen Standardposition nahe der rechten Headerkante
- die Buddy-Flaeche wurde im naechsten Schritt von der Wolken-Mischform auf eine echte `Sprechblase` reduziert; sie klappt per Icon auf und wieder zu
- die Kontrastlogik ist jetzt direkt aus `chat.html` abgeleitet: helle Theme-Flaechen bekommen eine weisse Bubble mit Ridge/Shadow, dunkle Theme-Flaechen eine sidebar-getoente Bubble mit denselben Kanten- und Schattenprinzipien
- ein Headless-Screenshot verifiziert die geoeffnete Sprechblase innerhalb des mobilen Shell-Rahmens unter `/tmp/mobile_buddy_speech_bubble.png`

## Slice 09 - Mobile Route Audit und Scope-Freeze

Ziel fuer Slice 09:

- `mobile_buddy.html` nicht nur optisch, sondern routing-seitig hart pruefen
- jede aktive Aktion unter Mobile-Viewport einmal real ausfuehren
- sauber trennen zwischen bereits mobile-nativen Interaktionen und Desktop-Weiterleitungen
- den Mobile-Ausbau explizit auf neue Mobile-Dateien begrenzen, ohne Originalseiten umzubauen

Stand dieses Slices:

- `Frontend/mobile_buddy_route_audit.spec.js` angelegt
- der Audit fuehrt reale In-Page-Interaktionen und alle aktiven Drawer-/Summary-Zielrouten unter `430 x 932` aus
- initiales Ergebnis: nur In-Page-Interaktionen bleiben wirklich mobile-native
- aus dem initialen Audit ergaben sich als noch offene Desktop-Ziele:
  - `chat.html`
  - `control_center.html`
  - `control_center.html?tab=aufgaben`
  - `control_center.html?tab=hierarchie`
  - `control_center.html?tab=workflows`
  - `task_tracker.html`
  - `project_config.html`
- daraus folgte fuer den weiteren Mobile-Ausbau:
  - `mobile_tasks.html`
  - `mobile_projects.html`
  - `mobile_workflows.html`
  - `mobile_teams.html`
  - optional `mobile_control_center.html`

## Slice 10 - Resizable Split und Board-Fokus

Ziel fuer Slice 10:

- den statischen vertikalen Split zwischen `Management-Board` und `Team-Board` in eine direkt manipulierbare Mobile-Interaktion ueberfuehren
- pro Board einen klaren Fokus-Zustand anbieten:
  - Management ausblenden -> Team vollflaechig
  - Team ausblenden -> Management vollflaechig
  - zweiter Klick -> zurueck in den neutralen Split
- die neuen Kern-Controls an Mobile-Touch-Groessen ausrichten

Stand dieses Slices:

- `Frontend/mobile_buddy.html` hat jetzt einen echten Drag-Splitter zwischen beiden Boards
- `Frontend/mobile_buddy.html` hat jetzt pro Board einen Header-Toggle fuer Fokus/Neutralzustand
- der Splitter ist pointer- und keyboard-bedienbar
- die Board-Toggle-Buttons sind als 48px-Touch-Targets ausgefuehrt
- `teamPicker` und `Agenten`-Disclosure wurden auf groessere Touch-Flaechen angehoben
- `Frontend/mobile_buddy_board_controls.spec.js` verifiziert Drag-Resize, Management-Fokus, Team-Fokus und Rueckkehr in den neutralen Zustand

## Slice 11 - Mobile Attachments und Widget-Bubble

Ziel fuer Slice 11:

- den Buddy-Widget-Zipfel nur im Mobile-Root entfernen, ohne `buddy_widget.js` fuer Desktop zu veraendern
- beide mobilen Composer mit echten `+`-Upload-Buttons ausstatten
- exakt denselben Upload-Pfad wie `chat.html` nutzen: `/chat/upload` plus `meta.attachments`

Stand dieses Slices:

- `Frontend/mobile_buddy.html` unterdrueckt den Widget-Connector nur lokal im Mobile-Scope per CSS-Override
- `Frontend/mobile_buddy.html` hat jetzt fuer `Management-Board` und `Team-Board` je einen eigenen `+`-Button, Hidden-File-Input und Attachment-Vorschau
- Attachment-Send laeuft im Mobile-Root jetzt ueber `/chat/upload` und anschliessend `/send`
- Attachment-Nachrichten werden in beiden Board-Feeds gerendert
- `Frontend/mobile_buddy.spec.js` verifiziert die sichtbaren `+`-Buttons, Vorschau, Attachment-Send in beiden Boards und den entfernten Buddy-Widget-Zipfel per Headless-Browserlauf

## Slice 12 - Mobile Projects als erster echter Folge-Screen

Ziel fuer Slice 12:

- den ersten verifizierten Drawer-/Summary-Exit aus dem Desktop-Scope holen
- `project_config.html` nicht anfassen, sondern eine mobile-native Ersatzoberflaeche bauen
- dieselben Backend-Endpunkte behalten:
  - `GET /projects`
  - `GET /engines/models`
  - `GET /api/context/scan`
  - `POST /api/projects/create`
  - `POST /runtime/configure`
  - `GET /status`

Stand dieses Slices:

- `Frontend/mobile_projects.html` angelegt
- die Seite nutzt dieselbe Theme-Quelle `bridge_theme` und dieselbe Bridge-Token-Auth-Injektion wie die Desktop-Seiten
- `mobile_buddy.html` verweist fuer `Projektstart` und Drawer `Neues Projekt` jetzt auf `mobile_projects.html`
- `Frontend/mobile_projects.html` ist bewusst mobile-native statt Desktop-Wizard:
  - einspaltige Projektflaeche
  - native Mobile-Selects statt Desktop-Select-Skin
  - bekannte Projekte als Quick-Picks aus `GET /projects`
  - kompakte Scan-Ergebnisse
  - kollabierbare Rollen-Karten fuer Leiter und Agenten
  - Footer-Aktionen fuer Export und Teamstart
- `Frontend/mobile_projects.spec.js` verifiziert:
  - kein horizontales Overflow bei `430 x 932`
  - Scan eines echten Projektpfads
  - Runtime-Configure-Feedback ueber `POST /runtime/configure`
  - Agent-Hinzufuegen
  - Export-Download
  - echte Projektanlage ueber `POST /api/projects/create`
  - Navigation von `mobile_buddy.html` in den neuen Screen

## Slice 13 - Mobile Tasks als zweiter echter Folge-Screen

Ziel fuer Slice 13:

- `task_tracker.html` und den Aufgaben-Zugriff nicht mobilisieren, sondern durch eine neue Mobile-Datei ersetzen
- dieselben Backend-Endpunkte behalten:
  - `GET /task/tracker`
  - Fallback `GET /task/queue`
  - Export ueber `format=csv|json` auf dem aktuell aktiven Endpunkt
- die Task-Exits aus `mobile_buddy.html` gezielt in den Mobile-Scope holen

Stand dieses Slices:

- `Frontend/mobile_tasks.html` angelegt
- die Seite nutzt dieselbe Theme-Quelle `bridge_theme`, dieselbe Bridge-Token-Auth-Injektion und dieselbe Buddy-Shell-Sprache wie `mobile_buddy.html`
- `mobile_buddy.html` verweist fuer `Tasks -> Tracker`, Drawer `Task Tracker` und Drawer `Aufgaben` jetzt auf `mobile_tasks.html`
- `Frontend/mobile_tasks.html` ist bewusst mobile-native statt Desktop-Tabelle:
  - kompakter Status-Block
  - mobile Filterflaeche statt Toolbar
  - card-basierte Taskliste statt Tabellenraster
  - Bottom-Sheet fuer Details statt rechter Sidebar
  - CSV-/JSON-Export und Auto-Refresh bleiben erhalten
- `Frontend/mobile_tasks.spec.js` verifiziert:
  - kein horizontales Overflow bei `430 x 932`
  - initiales Laden der Taskliste
  - Filter-Aufruf gegen `task/tracker` oder Fallback `task/queue`
  - Detail-Sheet fuer einen echten Task
  - CSV- und JSON-Download
  - Auto-Refresh-Toggle
  - Navigation von `mobile_buddy.html` ueber Drawer `Task Tracker`, Summary `Tracker` und Drawer `Aufgaben`
