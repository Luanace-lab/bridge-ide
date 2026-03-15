# W12 Shared Workspace Multi-Principal Blueprint

## Zweck
Kanonischer Blueprint fuer einen gemeinsamen BRIDGE-Arbeitsraum, in dem mehrere menschliche Principals ihre Agenten und Teams an einem gemeinsamen Projekt koordinieren koennen.

Dieser Blueprint trennt bewusst:

- **Phase 1:** gemeinsamer Multi-User-/Multi-Team-Workspace in **einer** BRIDGE-Instanz
- **Phase 2:** optionale Federation zwischen **mehreren** BRIDGE-Instanzen

## Scope
- `/home/leo/Desktop/CC/BRIDGE/Backend/server.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/board_api.py`
- `/home/leo/Desktop/CC/BRIDGE/Backend/team.json`
- `/home/leo/Desktop/CC/BRIDGE/Frontend/chat.html`
- `/home/leo/Desktop/CC/BRIDGE/Frontend/control_center.html`
- `/home/leo/Desktop/CC/BRIDGE/Frontend/buddy_landing.html`
- `/home/leo/Desktop/CC/BRIDGE/Knowledge/Users/`
- `/home/leo/Desktop/CC/BRIDGE/Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W02_UI_Struktur_Interaktionslogik_und_Zustaende.md`
- `/home/leo/Desktop/CC/BRIDGE/Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W03_Agent_Kommunikation_Messaging_Koordination_Eventfluesse.md`
- `/home/leo/Desktop/CC/BRIDGE/Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W04_Tasks_Workflows_Zuweisung_Reservierung_Ownership.md`
- `/home/leo/Desktop/CC/BRIDGE/Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W05_Datenmodelle_Persistenz_APIs_Schnittstellen_Stores.md`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/plans/release_blocker_3_federation_plan_spec_2026-03-11.md`
- `/home/leo/Desktop/CC/BRIDGE/Archiev/Projektleiter_persönlich/RESEARCH_MULTI_AGENT_FRAMEWORKS.md`

## Zielbild
### Kurzform
Susi und Kim sind zwei menschliche Principals in derselben BRIDGE-Control-Plane. Beide orchestrieren eigene Agenten und Teams, arbeiten aber an einem gemeinsamen Projekt und in einem gemeinsamen Arbeitsraum.

### Produktbild
- Jeder Principal hat einen eigenen kanonischen User-Scope.
- Ein Projekt kann mehrere Teams und mehrere menschliche Principals tragen.
- Agenten werden Teams und Projekten zugeordnet, nicht implizit nur einem einzelnen Nutzer.
- Kommunikation, Tasks, Workflows, Whiteboard und Scope-Locks bleiben BRIDGE-dominiert.
- Buddy bleibt Frontdoor und Concierge, aber nicht als alleinige SoT fuer Projekt-/Teamzustand.
- Datei- und Artefaktfluss wird projektbezogen und nachvollziehbar modelliert.

### Ausdruecklich nicht Ziel dieses W12-Slices
- Keine sofortige Cross-Internet-Federation als Primarloesung.
- Kein E2EE-/Relay-/Pairing-Produkt in diesem ersten Zielbild.
- Kein Ersatz der BRIDGE-Control-Plane durch reines Chat- oder File-Sharing.

## Verifizierter Ist-Zustand
### 1. Mehrere User-Sopes sind prinzipiell vorgesehen
- `server.py` pflegt kanonische User-Sopes unter `Users/<user_id>/USER`.
- Verifiziert vorhanden:
  - `Knowledge/Users/leo/USER.md`
  - `Knowledge/Users/susi/USER.md`
  - `Knowledge/Users/user/USER.md`
- Nicht vorhanden:
  - `Knowledge/Users/kim/USER.md`

### 2. Projekte, Teams und Agents existieren bereits als gemeinsame Control-Plane-Objekte
- `Backend/team.json` enthaelt aktuell:
  - `2` Projekte
  - `14` Teams
  - `59` Agents
- Beispielprojekte:
  - `bridge-ide`
  - `bug-bounty`
- `board_api.py` und `GET /board/projects` projizieren Projekte mit Teams und Mitgliedern.
- `GET /team/projects` projiziert Projekte mit Team- und Member-Aufloesung.

### 3. Kommunikations- und Koordinationspfade sind real vorhanden
- `POST /send`, `GET /history`, WebSocket-Liveevents, Tasks, Whiteboard und Scope-Locks sind im aktiven Produktpfad belegt.
- `W03` dokumentiert die reale Mehrkanal-Kommunikation innerhalb einer Instanz.

### 4. Buddy-Frontdoor und User-Frontdoor sind real vorhanden
- `buddy_landing.html` nutzt `GET /onboarding/status?user_id=...`, `POST /agents/buddy/start`, `POST /send`, `GET /receive/<user_id>`.
- `server.py` fuehrt `_seed_buddy_user_scope()`, `_get_buddy_frontdoor_status()` und `_ensure_buddy_frontdoor()`.

### 5. Upload existiert, aber noch nicht als echter Shared-Workspace
- `POST /chat/upload` speichert generische Chat-Anhaenge unter `Backend/uploads/`.
- `POST /projects/upload` speichert Dateien unter `<project>/.bridge/uploads/`.
- Der aktuelle Uploadpfad modelliert noch keine:
  - Principal-Zugehoerigkeit
  - Team-Zugehoerigkeit
  - Artefakt-Typen
  - Bearbeitungshistorie
  - Konfliktlogik

### 6. Federation ist nur als Plan vorhanden
- `release_blocker_3_federation_plan_spec_2026-03-11.md` beschreibt eine moegliche Instanz-zu-Instanz-Federation.
- Verifiziert im selben Dokument:
  - kein Code umgesetzt
  - keine API erweitert
  - keine Transport-/Crypto-Implementierung gestartet

## Problemdefinition
Das Repository hat bereits viele Bausteine fuer gemeinsames Arbeiten, aber kein kanonisches Modell fuer:

- mehrere menschliche Principals in einem gemeinsamen Projekt
- gemeinsame Projekt-Arbeitsraeume mit klarer Verantwortlichkeit
- teamuebergreifende Zusammenarbeit an Dateien/Artefakten
- klare Trennung zwischen lokalem Shared Workspace und spaeterer Federation

Aktuell sind mehrere Dinge schon da, aber noch nicht sauber zusammengebunden:
- User-Scope
- Buddy-Frontdoor
- Team-/Projekt-Board
- Messaging
- Task-/Workflow-System
- Uploads

## Architekturentscheidung
### Entscheidung
Der erste Produktpfad fuer das Szenario Susi + Kim ist **eine gemeinsame BRIDGE-Instanz mit mehreren menschlichen Principals**.

### Begruendung
- Dafuer existieren bereits reale Bausteine im Code.
- Die Komplexitaet ist deutlich geringer als bei Federation.
- Reproduzierbarkeit und Release-Pfad sind besser kontrollierbar.
- Dateifreigabe, Teamkoordination und Agentenzuordnung lassen sich innerhalb einer Instanz sauberer modellieren.

### Folge
Federation bleibt ein spaeterer, eigener Auftrag und wird nicht still in diesen Scope gezogen.

## Gap-Matrix
| Bereich | Ist-Zustand | Luecke | Risiko | Prioritaet |
| --- | --- | --- | --- | --- |
| Human Principals | `leo`, `susi`, `user` als User-Sopes vorhanden | kein kanonisches Multi-Principal-Modell; `kim` fehlt | User-/Projektzuordnung bleibt implizit | hoch |
| Projektmodell | Projekte und Teams sind vorhanden | kein explizites Modell `project owners / collaborators / participating teams` | gemeinsame Verantwortung bleibt unklar | hoch |
| Teammodell | Teams und Mitglieder sind vorhanden | Teams sind keine eigenstaendige Kollaborationseinheit zwischen Principals | Cross-team Zusammenarbeit bleibt informell | hoch |
| Messaging | intra-instance Messaging real vorhanden | kein kanonischer Principal-zu-Principal-/Team-zu-Team-Arbeitsfluss | Nutzerperspektive bleibt unscharf | hoch |
| Upload | `/chat/upload` und `/projects/upload` vorhanden | kein Shared-Workspace-Dateimodell | Dateien bleiben Anhänge statt Projektartefakte | kritisch |
| Ownership | Scope-Locks und Tasks vorhanden | keine kanonische Gesamtregel fuer Datei-/Task-/Team-/User-Ownership | Konflikte schwer aufloesbar | hoch |
| Buddy | Frontdoor vorhanden | Buddy weiss noch nicht kanonisch, wie Multi-Principal-/Shared-Workspace-Flows laufen | Concierge bleibt partiell | mittel |
| Federation | nur Spec | keine reale Umsetzung | verteilte Zusammenarbeit nicht verfuegbar | mittel, aber spaeter |

## Zielarchitektur fuer Phase 1
### 1. Principal-Modell
Neue kanonische Produktsemantik:
- `user` = menschlicher Principal
- `team` = organisatorische Arbeitsgruppe von Agents
- `project` = gemeinsamer Arbeitsgegenstand
- `workspace` = projektbezogener kollaborativer Artefaktraum

Minimalanforderung:
- ein Projekt kann mehrere Principals und mehrere Teams tragen
- jeder Principal kann mehrere Teams fuehren oder mittragen

### 2. Shared Project Model
Projekt soll explizit modellieren:
- `owners`
- `collaborators`
- `team_ids`
- `workspace_root`
- `shared_artifacts_root`
- `visibility`

### 3. Shared Workspace Model
Uploads und Dateien muessen projektbezogen werden:
- nicht nur generische Chat-Dateien
- sondern Artefakte mit:
  - `project_id`
  - `uploaded_by`
  - `team_id` optional
  - `artifact_type`
  - `created_at`
  - `origin` (`chat`, `project_upload`, spaeter `workflow`, `agent_output`)

### 4. Coordination Model
Zusammenarbeit soll auf bestehenden BRIDGE-Pfaden bleiben:
- Messaging
- Tasks
- Whiteboard
- Scope-Locks
- Projekt-/Team-Boards

Keine neue Parallelwelt neben der BRIDGE-Control-Plane.

### 5. Buddy-Rolle
Buddy soll:
- Shared-Workspace-Setup erklaeren
- Principals und Teams durch den Setup-Prozess fuehren
- Projekte/Teams ueber kanonische Produktpfade anlegen
- Nutzerfragen zum gemeinsamen Projekt beantworten

Buddy soll dafuer keine eigene Sonder-SoT bekommen.

## Taskliste
### Phase A — Multi-Principal-Modell kanonisieren
1. `team.json`- und API-Semantik um `project owners` / `project collaborators` erweitern.
2. `Knowledge/Users/kim/USER.md` als zweites reales Principal-Beispiel einfuehren.
3. Kanonische Principal-vs-Team-vs-Project-Regeln dokumentieren.

### Phase B — Shared Project Workspace definieren
1. Projektmodell um `workspace_root` und `shared_artifacts_root` erweitern.
2. `POST /projects/upload` in ein echtes Projekt-Artefaktmodell ueberfuehren.
3. Metadaten fuer hochgeladene Projektartefakte persistieren.

### Phase C — Ownership sauber machen
1. Eine kanonische Regel fuer:
   - Principal-Ownership
   - Team-Ownership
   - Task-Ownership
   - File-/Artifact-Ownership
   - Scope-Locks
   festziehen.
2. Konfliktfaelle dokumentieren:
   - Team A und Team B arbeiten an demselben Projekt
   - Susi und Kim orchestrieren unterschiedliche Teams auf dieselbe Datei-/Task-Flaeche

### Phase D — Buddy in den Shared-Workspace-Pfad integrieren
1. Buddy-Home und Operator-Doku auf Multi-Principal-/Shared-Workspace erweitern.
2. Buddy-Landing und Buddy-Frontdoor sollen gemeinsames Projekt-Setup erklaeren und begleiten koennen.

### Phase E — E2E-Produktpfad
1. Susi erstellt oder oeffnet gemeinsames Projekt.
2. Kim wird als Collaborator hinzugefuegt.
3. Teams werden dem Projekt zugeordnet.
4. Ein Projektartefakt wird hochgeladen.
5. Ein Team erzeugt daraus einen Task.
6. Zweites Team reagiert darauf ueber denselben Projektkontext.

## Verifikationsplan
Jeder Umsetzungsslice soll mindestens real pruefen:

1. API-Read:
- `GET /board/projects`
- `GET /team/projects`
- `GET /team/orgchart`

2. API-Write:
- Projekt anlegen oder aktualisieren
- Team zu Projekt hinzufuegen
- Projektartefakt hochladen

3. UI:
- Buddy-Landing oder relevante Frontdoor
- Projekt-/Team-Board
- Upload-Pfad

4. Koordination:
- Message oder Task zwischen zwei Teams innerhalb desselben Projekts
- sichtbarer Whiteboard-/Task-/Board-Nachweis

5. Persistenz:
- `team.json`
- Projektartefakte auf Disk
- gegebenenfalls Metadatenstore

## Abnahmekriterien fuer Phase 1
Phase 1 ist erreicht, wenn:

1. zwei menschliche Principals in einer BRIDGE-Instanz kanonisch modelliert sind
2. ein gemeinsames Projekt mehrere Teams und mehrere Principals tragen kann
3. projektbezogene Uploads als Artefakte statt nur als lose Dateien modelliert sind
4. Buddy den gemeinsamen Projektpfad erklaeren und ausloesen kann
5. ein realer End-to-End-Fluss zwischen zwei Teams im selben Projekt verifiziert ist

## Nicht Bestandteil dieses Blueprints
- sofortige E2EE- oder Internet-Federation
- globales `agent@instance`-Routing
- Relay-Server
- Key-Management
- Pairing
- Cross-instance Offline-Store-and-forward

Diese Themen bleiben im separaten Federation-Spec-Artefakt.

## Verdichtetes Urteil
Die Idee ist tragfaehig, aber nur dann sauber, wenn sie **erst lokal als gemeinsamer Multi-Principal-Workspace** gebaut wird.

Der verifizierte Ist-Zustand zeigt:
- viel vorhandene BRIDGE-Substanz
- aber noch kein kanonisches gemeinsames Principal-/Workspace-Modell

Der kleinste saubere Produktpfad ist deshalb:
- **erst Shared Workspace in einer Instanz**
- **spaeter Federation**
