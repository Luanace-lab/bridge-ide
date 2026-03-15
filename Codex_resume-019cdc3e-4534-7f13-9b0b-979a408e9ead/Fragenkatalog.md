Ja. Ich habe den Master Index, den Gesamtüberblick, die Gap-Map und die Themen-Dokumente W01–W08 ausgewertet. Das Bild ist ziemlich klar: `/BRIDGE` hat bereits reale Plattformbreite, aber die härtesten offenen Punkte liegen bei kanonischem Startpfad, harter SoT, Agent-Identität über Session-Grenzen, Synchronität der dateibasierten Stores und der Semantik der parallelen Kommunikationskanäle. Meine zentrale Schlussfolgerung ist deshalb: Für dein Ziel „immer derselbe Agent“ ist die Kernfrage nicht Feature-Breite, sondern Kontinuität.      

Ich trenne den Katalog bewusst in zwei Logiken:
Deine Perspektive fragt: **Was muss für dich als Produktversprechen zuverlässig wahr sein?**
Die Senior-Dev-Perspektive fragt: **Wodurch wird dieses Versprechen technisch hart und beweisbar?**

## 1) Fragenkatalog aus deiner Perspektive

Ich priorisiere hier Identität, Resume, SoT und Tagebuchfähigkeit, weil die Doku zwar eine dokumentierte Hauptquelle (`team.json`) zeigt, zugleich aber Overlays, Fallbacks und mehrere Laufzeit-/Log-Artefakte nebeneinander existieren: `runtime_team.json`, `projects.json`-Fallback, `agent_state`, `messages/bridge.jsonl`, `execution_runs`, `whiteboard`, `scope_locks`. Genau dort entscheidet sich, ob ein Agent über Sessions hinweg wirklich „derselbe“ bleibt oder nur denselben Namen trägt.    

### P0 – Produktkern: Was heißt „immer derselbe Agent“?

1. Was ist für dich die harte Definition von „derselbe Agent“?
   Geht es um dieselbe `agent_id`, dieselbe Persona, dieselbe Inbox, dieselben offenen Aufgaben, dieselbe Zuständigkeit, dasselbe Gedächtnis – oder um alles zusammen?

2. Welche Invarianten dürfen über Session-Grenzen niemals brechen?
   Zum Beispiel: ID, Rolle, Zuständigkeiten, offene Tasks, Memory-Kontext, Dateiverantwortung, zuletzt bekannte Entscheidungen.

3. Ab wann gilt ein Resume als erfolgreich?
   Reicht „gleiche ID wieder online“, oder muss der Agent auch seinen letzten Arbeitskontext, offene Aufgaben, Locks und Verlauf wiederhaben?

4. Darf es jemals zwei laufende Prozesse mit derselben logischen Agent-Identität geben?
   Wenn nein: Was ist das sichtbare Produktverhalten bei einem Konflikt?

5. Was ist aus Nutzersicht schlimmer:
   derselbe Agent mit unvollständigem Gedächtnis oder ein neuer Agent mit sauberem Start?
   Diese Frage ist hart, weil sie dein eigentliches Qualitätskriterium definiert.

6. Soll der Nutzer jederzeit fragen können:
   „Wer bist du, woran arbeitest du, was weißt du noch, was schuldet du noch?“
   Und muss die Antwort aus persistenter Wahrheit rekonstruiert werden, nicht aus Zufallskontext?

### P0 – Harte SoT

7. Was ist die kanonische SoT für Agent-Existenz und Teamstruktur?
   `team.json` nur für Konfiguration – oder auch für operative Wahrheit?

8. Was ist die kanonische SoT für Laufzeitidentität?
   Ein Registry-Store, `agent_state`, tmux-Session, Heartbeat-Register oder etwas Eigenes?

9. Was ist die kanonische SoT für Ownership?
   Task-Assignee, Team-Zuordnung, Scope-Lock oder Whiteboard?

10. Was ist die kanonische SoT für „was gerade passiert“?
    Message-Log, Task-State, Execution-Journal, Agent-State oder UI-Snapshot?

11. Welche Wahrheit soll im Konfliktfall gewinnen, wenn Stores auseinanderlaufen?

### P1 – Start, Restart, Recovery

Die Doku zeigt mehrere reale Startpfade: CLI, `start_platform.sh`, Docker, manueller Direktstart. Gleichzeitig laufen Runtime und Kommunikation über Server, WebSocket, MCP, Watcher und tmux-nahe Sessions. Daraus folgt: Dein eigentliches Produktversprechen hängt an Restart-Semantik, nicht nur an „Server startet“.   

12. Welcher Startpfad soll operativ der kanonische Pfad sein?

13. Welche Restart-Arten musst du robust beherrschen?
    Nur Server-Neustart? Nur Agent-Neustart? Gesamtplattform-Neustart? Container-Neustart? Host-Neustart?

14. Was muss ein Agent nach Server-Neustart automatisch tun?
    Re-register? Resume? Offene Messages replayen? Pending Tasks wieder einlesen?

15. Was muss nach Restart zwingend erhalten bleiben?
    Nachrichtenverlauf, Agent-Zustand, offene Tasks, Locks, Whiteboard, Approval-Status, Workflow-Kontext?

16. Ab wann gilt das System für dich als „robust restartbar“?
    Einmaliger Happy Path oder mehrfache idempotente Restarts ohne Drift?

17. Was ist das gewünschte Verhalten bei halber Recovery?
    Beispiel: ID kommt zurück, aber offene Locks fehlen.

### P1 – Tagebuch und Wissenskontinuität

18. Soll das System aus Session-Logs ein echtes Agent-Tagebuch führen?
    Nicht nur Chat-Historie, sondern Entscheidungen, Task-Wechsel, Ergebnisse, Irrtümer, offene Enden.

19. Soll dieses Tagebuch append-only sein oder nachträglich kuratierbar?

20. Soll das Tagebuch agentenzentriert, taskzentriert oder sessionzentriert aufgebaut sein?

21. Welche Mindestfrage muss das Tagebuch später beantworten können?
    Etwa: „Warum hat Agent X gestern Entscheidung Y getroffen?“

22. Soll ein Agent vor jeder relevanten Aktion verpflichtet sein, vorhandenes Wissen abzurufen?

23. Falls ja: Was zählt als Pflichtabruf?
    Messages, Task-Kontext, Whiteboard, Execution-Runs, Team-Kontext, frühere Ergebnisse?

24. Muss der Agent dem Nutzer sichtbar nachweisen, dass er den Kontext wirklich gelesen hat?

### P2 – Bedienlogik

25. Welche UI ist für den Alltag kanonisch:
    `chat.html`, `control_center.html` oder je nach Zweck beides?
    Solange das nicht klar ist, bleibt auch unklar, wo Kontinuität für den Nutzer sichtbar wird.  

26. Wo soll der Nutzer die persistente Agent-Identität sehen?
    Im Chat, im Control Center, im Profil, im Task-Panel, im Agent-Status?

27. Welcher eine Screen muss im Zweifel beweisen:
    „Das ist wirklich derselbe Agent wie gestern“?

---

## 2) Fragenkatalog aus Senior-Dev-Perspektive

Die Doku zeigt einen monolithischen `server.py`, große Single-File-UIs, mehrere Kommunikationswege (HTTP, WebSocket, MCP, Watcher, Event Bus), mehrere Startpfade und viele dateibasierte Stores im Repo-Baum. Der technische Kern ist deshalb nicht „mehr Features bauen“, sondern Invarianten explizit machen: Identität, Zustandsübergänge, Store-Präzedenz, Restart-Verhalten, Replay/Dedupe und Tracing.      

### P0 – Lifecycle und Start-Invarianten

1. Was ist der eine kanonische Boot-Graph?
   Nicht nur „was kann starten“, sondern: welche Prozesse, in welcher Reihenfolge, mit welchen Side Effects.

2. Welcher Entry-Point besitzt die Orchestrierungsautorität?
   Sollen alle anderen Startpfade nur noch delegieren?

3. Ist Start idempotent?
   Was passiert bei doppeltem `start` direkt hintereinander?

4. Ist Restart idempotent?
   Was passiert bei „Server down, tmux lebt weiter“?

5. Wie werden stale PIDs, stale Heartbeats, stale Online-Flags und stale Locks bereinigt?

6. Gibt es eine explizite Agent-Lifecycle-State-Machine?
   `configured -> started -> registered -> online -> idle -> active -> stale -> offline -> resumed -> re-registered`

### P0 – Identitätsmodell

7. Was ist der Unterschied zwischen logischer Agent-Identität und physischer Session?
   `agent_id`, `session_id`, tmux-Name, Prozess-ID, Nonce, Heartbeat-Key dürfen nicht semantisch vermischt bleiben.

8. Welcher persistente Schlüssel bindet den logischen Agenten über Restarts hinweg an seine Historie?

9. Kann derselbe `agent_id` parallel mehrfach registriert werden?
   Falls ja: Was entscheidet Primat, und wie wird Split-Brain verhindert?

10. Wie sieht der exakte Resume-Handshake aus?
    Wer erkennt „ich bin derselbe Agent“ – der Server, MCP, Watcher, tmux oder ein Dateistore?

11. Welche Artefakte sind für Resume notwendig und welche nur hilfreich?

### P0 – Store-Klassifikation und harte SoT

12. Erzeugt das System bereits eine saubere Matrix aus
    **primary / derived / cache / log / archive**
    für `team.json`, `runtime_team.json`, `projects.json`-Fallback, `tasks.json`, `scope_locks.json`, `whiteboard.json`, `messages/bridge.jsonl`, `agent_state/*`, `execution_runs/*`, `workflow_registry.json`, `automations.json`?

13. Wenn zwei Stores widersprechen: Welche Präzedenzregel gilt pro Domäne?

14. Sind die JSON-/JSONL-Writes atomar und prozesssicher genug für parallele Writer?

15. Welche Stores müssen nach Crash zwingend konsistent sein, damit Resume noch vertrauenswürdig ist?

16. Welche Stores sind nur Beobachtungsartefakte und dürfen nie als operative Wahrheit gelesen werden?

### P1 – Messaging-, Replay- und Event-Semantik

17. Welcher Kanal ist die kanonische Inbox-Wahrheit?
    `/receive/<agent_id>`, WebSocket-Push, MCP-Buffer oder `messages/bridge.jsonl`?

18. Welche Zustellgarantie gibt es pro Kanal?
    At-most-once, at-least-once, best effort?

19. Wie wird Reihenfolge garantiert?
    Pro Agent, pro Thread, pro Task oder gar nicht?

20. Wie werden Replay und Dedupe nach Reconnect behandelt?

21. Sind Watcher-Injections und Systemnachrichten erste Klasse im Verlauf oder bloße Nebenwirkungen?

22. Ist der Event-Bus transaktional an State-Änderungen gekoppelt oder kann er vor/nach dem Commit driften?

### P1 – Task-, Lock- und Workflow-Konsistenz

Der Snapshot zeigt `tasks.json` mit 2279 Einträgen, davon 2029 `failed`, 231 `done`, 19 `deleted`, plus dokumentierte Seiteneffekte im Done-Pfad über Whiteboard, Scope-Unlock, Event-Bus und Benachrichtigungen. Außerdem ist in mindestens einem Fall `_claimability.reason` nicht konsistent mit dem finalen Task-Status. Das macht Task- und Ownership-Fragen zu einem Kernfeld, nicht zu einem Randthema. 

23. Ist der Task-Lifecycle als kanonische State-Machine dokumentiert oder nur verteilt implementiert?

24. Ist `_claimability` ein abgeleiteter Read-View oder persistierte, potenziell stale Daten?

25. Ist `done/fail` transaktional genug gegenüber `tasks.json`, `whiteboard`, `scope_locks`, Event-Emission und Benachrichtigung?

26. Was gewinnt bei Konflikten zwischen Team-Hierarchie, Task-Assignee und Scope-Lock?

27. Wie werden workflow-erzeugte Tasks sauber an Execution-Journal und Agent-Historie zurückgebunden?

28. Bedeutet der aktuelle Failed-Snapshot Archivlast oder laufende Betriebsstörung?
    Das ist technisch und operativ eine völlig andere Klasse von Problem.

### P1 – Observability und Beweisbarkeit

29. Kann heute schon ein lückenloser Agent-Timeline-Trace rekonstruiert werden:
    Identität, Start, Register, Heartbeats, Messages, Tasks, Entscheidungen, Restart, Resume?

30. Kann heute schon ein lückenloser Task-Trace rekonstruiert werden:
    Create, Claim, Ack, Done/Fail, Unlock, Whiteboard, Event-Bus, Notify?

31. Welche minimale Telemetrie fehlt, um „derselbe Agent nach Restart“ beweisbar zu machen?

32. Welche Logs sind kanonisch, welche bloß forensisch hilfreich?

### P2 – Betriebs- und Doku-Klarheit

33. Welche Startvariante ist operativ kanonisch – lokal, Shell, CLI oder Docker?
    Solange das offen ist, bleibt auch jede Robustheitsaussage weich. 

34. Reicht die Docker-Volume-Abdeckung für die real benutzten Stores wirklich aus?

35. Welche Root-Bereiche sind aktiv, welche historisch, welche persönlich?
    Ohne diese Klassifikation bleibt jede Analyse unnötig teuer.   

36. Welche Dokumente sind kanonisch und welche nur historische Spuren?
    Die Doku selbst markiert bereits Drift und Unterbeschreibung.  

---

## 3) Die 8 Fragen mit dem höchsten Hebel

Diese acht würde ich als Nächstes zuerst klären lassen, bevor ihr weiter „finalisiert“:

1. Was ist die harte Definition von „derselbe Agent“?
2. Welcher Store ist die kanonische SoT für Agent-Identität und Resume?
3. Welcher Startpfad ist operativ kanonisch?
4. Wie sieht der exakte Resume-Handshake derselben `agent_id` nach Restart aus?
5. Welche Stores müssen einen Restart zwingend überleben?
6. Welcher Kanal ist die kanonische Inbox-/Verlauf-Wahrheit?
7. Kann aus den bestehenden Logs bereits ein belastbares Agent-Tagebuch rekonstruiert werden?
8. Ist Wissensabruf technisch erzwungen oder nur kulturell erwartet?

Mein Arbeitsurteil nach den Dokus:
**Dein Produktkern steht oder fällt an einem expliziten Identitäts- und Resume-Vertrag.**
Solange der nicht hart definiert und technisch einer klaren SoT zugeordnet ist, bleibt „persistenter Agent“ eher Hoffnung als belastbare Systemeigenschaft. Diese Schlussfolgerung stützt sich vor allem auf die dokumentierten Mehrfach-Startpfade, Mehrfach-Kanäle und Mehrfach-Stores.     

Im nächsten Schritt kann ich daraus direkt einen **Codex-Prüfauftrag** machen: erst als scharfen Fragebogen, dann als gestaffelten Live-Verifikationsplan.
__________________________________________________

