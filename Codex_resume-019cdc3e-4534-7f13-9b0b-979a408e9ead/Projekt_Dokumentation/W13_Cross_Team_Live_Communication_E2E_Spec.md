# W13 Cross-Team Live Communication E2E Spec

## Zweck
Diese Spezifikation definiert den naechsten grossen Produktslice fuer die BRIDGE:

- Team A und Team B sollen ueber BRIDGE live miteinander kommunizieren koennen.
- Menschen und Agents sollen ueber dieselbe Control Plane sichtbar, adressierbar und steuerbar sein.
- Externe Systeme wie GitHub, Server, Tickets oder Dateispeicher bleiben externe Systeme.
- BRIDGE baut zuerst keine eigene Datei- oder Workspace-Plattform, sondern die Kommunikations- und Koordinationsschicht.

Die Spezifikation ist bewusst end-to-end und beginnt beim Zielzustand, nicht bei Einzelimplementierungen.

---

## Zielzustand

### Produktziel
Susi in Berlin und Kim in New York koennen ihre Teams ueber BRIDGE live koordinieren.

Das bedeutet konkret:

1. Beide menschlichen Principals authentifizieren sich gegen BRIDGE ueber User-/UI-Auth, nicht ueber Claude-Credentials.
2. Beide Teams sind in einem gemeinsamen Projekt- und Teammodell sichtbar.
3. Team A kann Team B live anschreiben.
4. Team B kann live antworten.
5. Tasks, Reviews, Eskalationen und Whiteboard-Signale koennen ueber Teamgrenzen uebergeben werden.
6. Artefakte werden im ersten Schritt nur referenziert oder angehaengt; BRIDGE baut dafuer keinen eigenen Workspace-Ersatz.
7. Watcher und Forwarder bleiben operative Hilfskomponenten fuer Session-Beobachtung und Output-Projektion, nicht die Quelle der fachlichen Wahrheit.
8. Die gesamte Kette ist fuer Menschen nachvollziehbar und fuer das System beobachtbar.

### E2E-Wahrheitskriterium
Die Funktion gilt erst dann als vorhanden, wenn real belegt ist:

- ein User/Team sendet,
- das Zielteam empfaengt,
- das Zielteam antwortet,
- ein Task oder Review kann uebergeben werden,
- Status oder Whiteboard wird sichtbar,
- der Fehlerfall ist fuer beide Seiten nachvollziehbar.

---

## Nicht-Ziel

- kein eigener Git-Ersatz
- kein eigener GitHub-Ersatz
- kein eigener vollwertiger Shared-Workspace im ersten Schritt
- keine Datei-Synchronisationsplattform im ersten Schritt
- keine Claude-Credential- oder Account-Wahrheit fuer Login/Auth
- keine stillen Architekturwechsel ausserhalb dieses Kommunikationsslices

---

## Verifizierter Ist-Zustand

### 1. Auth-Basis ist real vorhanden
Verifiziert durch Ausfuehrung und Codeinspektion.

In [server.py](/home/user/bridge/BRIDGE/Backend/server.py) existieren aktive Auth-Pfade:

- `_extract_auth_token()` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L12133)
- `_resolve_auth_identity()` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L12142)
- `_require_authenticated()` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L12171)
- `_path_requires_auth_get()` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L12200)
- `_path_requires_auth_post()` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L12208)

Aktive Identitaeten:

- User-Token
- UI-Session-Token
- Agent-Session-Token

Das ist die richtige Basis fuer Cross-Team-Kommunikation. Nicht Claude-Credentials.

### 2. Lokale Messaging-Kette ist real vorhanden
Verifiziert durch Codeinspektion.

- `POST /send` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L17907)
- WebSocket `type == "send"` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L21887)
- Team-Empfaenger `team:<id>` werden bereits speziell behandelt.

Damit existiert bereits eine reale lokale Kommunikationsschicht.

### 3. Team-/Projektmodell ist real vorhanden
Verifiziert durch Codeinspektion.

In [board_api.py](/home/user/bridge/BRIDGE/Backend/board_api.py):

- `get_all_projects()` [board_api.py](/home/user/bridge/BRIDGE/Backend/board_api.py#L268)
- `create_project()` [board_api.py](/home/user/bridge/BRIDGE/Backend/board_api.py#L325)
- `add_team()` [board_api.py](/home/user/bridge/BRIDGE/Backend/board_api.py#L430)
- `add_member()` [board_api.py](/home/user/bridge/BRIDGE/Backend/board_api.py#L563)
- `remove_member()` [board_api.py](/home/user/bridge/BRIDGE/Backend/board_api.py#L612)

`Backend/team.json` enthaelt aktuell reale `projects`, `teams` und `agents`.

### 4. User-Frontdoor ist teilweise real vorhanden
Verifiziert durch Ausfuehrung und Codeinspektion.

- `_seed_buddy_user_scope()` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L8152)
- `_get_buddy_frontdoor_status()` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L8221)
- `_ensure_buddy_frontdoor()` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L8287)

Live geprueft:

- `GET /onboarding/status?user_id=susi` liefert `known_user=true`
- `buddy_running=true`

Vorhanden im Vault:

- [Knowledge/Users/leo/USER.md](/home/user/bridge/BRIDGE/Knowledge/Users/leo/USER.md)
- [Knowledge/Users/susi/USER.md](/home/user/bridge/BRIDGE/Knowledge/Users/susi/USER.md)
- [Knowledge/Users/user/USER.md](/home/user/bridge/BRIDGE/Knowledge/Users/user/USER.md)

Nicht vorhanden:

- `Knowledge/Users/kim/USER.md`

### 5. Watcher und Forwarder sind real vorhanden, aber lokal zentriert
Verifiziert durch Codeinspektion.

Watcher:

- WebSocket-Subscription in [bridge_watcher.py](/home/user/bridge/BRIDGE/Backend/bridge_watcher.py#L2673)
- Routing ueber `ALLOWED_ROUTES` in [bridge_watcher.py](/home/user/bridge/BRIDGE/Backend/bridge_watcher.py#L87)
- Tmux-Injection in [bridge_watcher.py](/home/user/bridge/BRIDGE/Backend/bridge_watcher.py#L726)

Forwarder:

- lokale Tmux-Session-Erkennung in [output_forwarder.py](/home/user/bridge/BRIDGE/Backend/output_forwarder.py#L270)
- Session-Env-Auswertung in [output_forwarder.py](/home/user/bridge/BRIDGE/Backend/output_forwarder.py#L282)
- Relay-Nachrichten in [output_forwarder.py](/home/user/bridge/BRIDGE/Backend/output_forwarder.py#L208)
- Pipe-Pane-Logik in [output_forwarder.py](/home/user/bridge/BRIDGE/Backend/output_forwarder.py#L328)

Beide Komponenten sind fuer lokale Sessions ausgelegt. Sie sind keine allgemeine Team-zu-Team-Foederationsschicht.

### 6. Federation-Hooks sind real im Code, aber nicht als Produktpfad verifiziert
Verifiziert durch Codeinspektion.

In [server.py](/home/user/bridge/BRIDGE/Backend/server.py):

- `_is_federation_target()` [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L6249)
- `_handle_federation_inbound()` [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L6277)
- `_federation_send_outbound()` [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L6340)

In [federation_runtime.py](/home/user/bridge/BRIDGE/Backend/federation_runtime.py):

- persistente Relay-Authentifizierung
- Queueing
- Reconnect
- Health

Wichtig:
Die alte Archiv-Spec unter [release_blocker_3_federation_plan_spec_2026-03-11.md](/home/user/bridge/BRIDGE/Archiev/plans/release_blocker_3_federation_plan_spec_2026-03-11.md) ist fuer den aktuellen Codezustand zu alt. Aktiver Code ist weiter als dieses Papier.

### 7. Artefakt-Pfade existieren, aber kein echter Shared Workspace
Verifiziert durch Codeinspektion.

- `POST /projects/upload` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L19107)
- `POST /chat/upload` in [server.py](/home/user/bridge/BRIDGE/Backend/server.py#L19162)

Das sind Upload-Pfade, aber noch kein gemeinsames, versioniertes, berechtigtes Workspace-Modell.

---

## Produktentscheidung

### Entscheidung A
Der erste grosse Produktslice fuer dieses Thema ist **nicht** ein eigener Workspace.

### Entscheidung B
Der erste grosse Produktslice ist **Cross-Team Live Communication and Coordination**.

### Entscheidung C
Das Produktziel wird in zwei Stufen geschnitten:

#### Stufe 1 – Zentrale gemeinsame BRIDGE-Instanz
Beide Teams arbeiten gegen dieselbe BRIDGE-Instanz.

Vorteile:

- hoehere Verifizierbarkeit
- geringeres Architektur-Risiko
- vorhandene Messaging-/Task-/Whiteboard-/Board-Pfade koennen direkt genutzt werden
- schnellerer Produktwert

#### Stufe 2 – Optionale Federation zwischen Instanzen
Erst wenn Stufe 1 sauber traegt, wird Instanz-zu-Instanz-Kommunikation produktisiert.

Vorteile:

- organisatorische Entkopplung moeglich
- globale Teams und Unternehmensgrenzen besser adressierbar

Risiko:

- deutlich hoehere E2E-Komplexitaet
- Sicherheits-/Routing-/Replay-/Observability-Anforderungen steigen stark

---

## Was fuer den Zielzustand benoetigt wird

### A. Identitaeten
- `user`
- `team`
- `agent`
- optional spaeter `instance`

### B. Auth
- User-/UI-Auth fuer menschliche Principals
- Agent-Auth fuer Agents
- keine Claude-Credentials fuer BRIDGE-Login/Auth

### C. Adressierung
- User zu Team
- Agent zu Team
- Team zu Projekt
- spaeter optional `team@instance` und `agent@instance`

### D. Kommunikationsprimitive
- Nachricht
- Task-Uebergabe
- Review-Anforderung
- Whiteboard-/Status-Signal
- Eskalation

### E. Sichtbarkeit
- was gesendet wurde
- was zugestellt wurde
- was angenommen wurde
- was fehlgeschlagen ist
- wer woran arbeitet

### F. Artefaktbezug
- zuerst nur Referenzen oder Upload-Artefakte
- kein eigener Workspace als Voraussetzung fuer Kommunikation

---

## Gap-Matrix

| Themenblock | Zielzustand | Was wir haben | Luecke | Prioritaet |
| --- | --- | --- | --- | --- |
| User/Auth | zwei menschliche Principals koennen sich sauber anmelden | User-/UI-Token, Frontdoor, User-Scopes | kein kanonisches Multi-Principal-Produktmodell | Hoch |
| Teams/Projekt | Team A und Team B in gemeinsamem Projekt | Projekte, Teams, Mitglieder in `board_api.py` | kein expliziter Cross-Team-E2E-Flow dokumentiert | Hoch |
| Live-Nachricht | Team A -> Team B -> Antwort | `/send`, WS `send`, History, Team-Routing | nicht als harter Cross-Team-E2E-Produktpfad verifiziert | Hoch |
| Task-Handover | Team-uebergreifende Task-Uebergabe | Task-System vorhanden | kein kanonischer Cross-Team-Handover-Flow verifiziert | Hoch |
| Whiteboard/Status | gegenseitige Sichtbarkeit | Whiteboard/Eventsystem vorhanden | kein klares Team-A-zu-Team-B-Statusbild als Produktflow | Mittel |
| Watcher | lokale Session-Zustellung/Wakeup | vorhanden | lokal zentriert, nicht Produkt-SoT fuer Cross-Team | Mittel |
| Forwarder | lokale Output-Projektion | vorhanden | lokal zentriert, kein Remote-Team-Transport | Mittel |
| Federation | Instanz-zu-Instanz-Kommunikation | aktive Hooks und Runtime-Komponenten | kein belastbar verifizierter Produktpfad | Mittel |
| Artefakte | Referenzen/Uploads genuegen fuer V1 | Upload-Endpunkte vorhanden | kein kanonisches Artefaktmodell mit Ownership/Provenance | Mittel |
| Multi-Principal-Vault | Susi und Kim als Principals | `susi` vorhanden | `kim` fehlt, Rollenmodell nicht voll kanonisiert | Hoch |

---

## Priorisierte Taskliste

### Phase 1 – Kanonisches V1-Ziel festziehen
1. Zentrale gemeinsame BRIDGE-Instanz als V1-Produktziel festschreiben.
2. `user`, `team`, `project`, `agent` als kanonische Produktobjekte fuer diesen Slice definieren.
3. `kim` als realen User-Scope anlegen.

### Phase 2 – Cross-Team-Nachrichtenfluss hart verifizieren
1. Projekt mit Team A und Team B als Testaufbau materialisieren.
2. Menschlicher Principal A sendet an Team B.
3. Team B empfängt sichtbar.
4. Antwort von Team B an Team A.
5. Fehlerpfad pruefen:
   - unbekanntes Team
   - fehlende Mitgliedschaft
   - fehlende Auth

### Phase 3 – Team-zu-Team-Koordination statt nur Chat
1. Cross-Team-Task-Handover definieren.
2. Review-Anforderung zwischen Teams definieren.
3. Whiteboard-/Status-Signal teamuebergreifend pruefen.

### Phase 4 – Beobachtbarkeit und Betriebsgrenzen
1. watcher/forwarder fuer diesen Slice explizit als lokale Hilfskomponenten dokumentieren.
2. Klar machen, was Messaging-SoT ist und was nur lokale Zustellmechanik ist.
3. Verifizierte Fehler- und Debug-Pfade festziehen.

### Phase 5 – Federation nur als Phase 2
1. Aktiven Federation-Code gegen den V1-Zielpfad abgrenzen.
2. E2E-Spec fuer `team@instance` erst nach erfolgreicher V1-Kommunikation schreiben.

---

## Verifikationsplan

### Verifikation V1 Login/Auth
Verifiziert ist V1 erst, wenn real ausgefuehrt:

- User A kann sich gegen BRIDGE anmelden.
- User B kann sich gegen BRIDGE anmelden.
- beide koennen ihre Frontdoor-/Teamansicht laden.
- keine Claude-Credentials sind dafuer Teil des Auth-Pfads.

### Verifikation V1 Messaging
Verifiziert ist V1 erst, wenn real ausgefuehrt:

- A -> Team B ueber `/send`
- B sieht die Nachricht
- B antwortet
- A sieht die Antwort
- History/Live-View stimmen zusammen

### Verifikation V1 Koordination
Verifiziert ist V1 erst, wenn real ausgefuehrt:

- Cross-Team-Task wird erzeugt
- Zielteam sieht sie
- Statusaenderung ist sichtbar
- Whiteboard oder vergleichbare Projektion zeigt den Zustand

### Verifikation V1 Fehlerfaelle
Verifiziert ist V1 erst, wenn real ausgefuehrt:

- unauthenticated send wird abgewiesen
- falscher Sender wird abgewiesen
- unbekanntes Ziel wird nachvollziehbar abgewiesen
- Event-/History-Zustand bleibt konsistent

---

## Harte Stop-Regeln

Stoppe und eskaliere, wenn:

- Cross-Team-Kommunikation nur mit Scope-Bruch erreichbar waere
- Auth dafuer Claude-Credential-Pfade wieder oeffnen wuerde
- watcher/forwarder still zur fachlichen SoT gemacht werden muessten
- V1 und Federation unklar vermischt werden

---

## Konkrete naechste Ausfuehrungsschritte

1. `kim` als User-Scope materialisieren.
2. Projekt-/Team-Testaufbau fuer Team A und Team B in einer Instanz anlegen.
3. harten Cross-Team-Messaging-E2E-Test definieren und laufen lassen.
4. danach erst Cross-Team-Task-/Review-/Whiteboard-Slice.
5. Federation vorerst nicht implementieren, sondern nur aktiv vom V1-Scope abgrenzen.

---

## Abnahmekriterien

Der Slice gilt erst als erreicht, wenn:

1. zwei menschliche Principals in einer gemeinsamen BRIDGE-Instanz sauber existieren
2. zwei Teams in einem Projekt sichtbar sind
3. Team-zu-Team-Live-Nachrichten end-to-end real funktionieren
4. Task- oder Review-Uebergabe zwischen Teams real funktioniert
5. Auth nicht ueber Claude-Credentials laeuft
6. watcher und forwarder nicht als fachliche Hauptwahrheit missverstanden werden
7. die Kette fuer Nutzer nachvollziehbar und fuer das System debugbar bleibt

---

## Restrisiko

Nicht verifiziert.

- Ein realer Cross-Team-E2E-Flow mit `susi` und `kim`
- ein realer Task-Handover zwischen zwei Teams
- ein realer Review-/Whiteboard-Flow zwischen zwei Teams
- der aktive Federation-Code als produktionsreifer Instanz-zu-Instanz-Pfad

Diese Spezifikation schafft die Basis fuer genau diese naechsten Verifikationen.
