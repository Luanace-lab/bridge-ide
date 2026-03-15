# 02_Gap_Map

## Zweck
Verdichtung der Luecken zwischen Produktvision und realem Codezustand im `/BRIDGE`-Scope, ohne Fixes vorwegzunehmen.

## Scope
Visionselemente einer belastbaren Live-Orchestrierungsplattform gegen den beobachteten Ist-Zustand von `/home/user/bridge/BRIDGE`.

## Evidenzbasis
- `/home/user/bridge/BRIDGE/Backend/server.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_mcp.py`
- `/home/user/bridge/BRIDGE/Backend/bridge_watcher.py`
- `/home/user/bridge/BRIDGE/Backend/team.json`
- `/home/user/bridge/BRIDGE/Backend/tasks.json`
- `/home/user/bridge/BRIDGE/Backend/workflow_registry.json`
- `/home/user/bridge/BRIDGE/Backend/automations.json`
- `/home/user/bridge/BRIDGE/docs/*`
- `W01` bis `W08` in diesem Ordner

## Ist-Zustand
Die Kernvision ist nicht nur theoretisch vorhanden; wesentliche Plattformteile existieren real. Die Umsetzung ist aber ungleichmaessig verteilt, mehrfach ueberlagert und teilweise dokumentations- oder zustandsseitig fragil.

| Visionselement | Realer Befund | Evidenz | Luecke | Risiko |
|---|---|---|---|---|
| Live-Orchestrierungsserver | Vorhanden | `Backend/server.py`, `Backend/bridge_mcp.py`, `Backend/bridge_watcher.py` | Monolithische Ballung in `server.py` | Hohe Kopplung |
| Persistente Agent-Runtime | Vorhanden | tmux-basierte Startpfade in `server.py`, `start_platform.sh`, `start_agents.py` | Mehrere konkurrierende Startpfade | Drift zwischen Startvarianten |
| Multi-Agent-Kommunikation | Teilweise belastbar | `POST /send`, `/receive/{agent_id}`, WebSocket, MCP-Listener, Watcher | Mehrfachkanaele ohne eindeutige Primat-Dokumentation | Zustands- und Zustellungsinkonsistenz |
| Read-Surface / Auth-Grenzen | Teilweise vorhanden | Die zuvor offene lokale Read-Surface ist auf den erneut verifizierten Kernpfaden jetzt geschlossen: `GET /logs?name=server.log&lines=1`, `/messages?limit=1`, `/history?limit=1`, `/task/queue?limit=1`, `/agents`, `/n8n/workflows`, `/n8n/executions?limit=1`, `/automations` und `/workflows/tools` liefern ohne Auth real `401`; dieselben Pfade lieferten mit Token real `200`. `GET /agent/config` lieferte im Gegentest ohne Auth `401` und mit dem verwendeten Token `403`, also strenger statt offener. | Nicht jeder denkbare GET-Pfad und nicht jede exotische Proxy-Topologie wurde in diesem Slice separat neu auditiert. | Kern-Read-Surface-Haertung ist real belegt; Restrisiko liegt eher in Randpfaden als im zuvor offenen Hauptpfad |
| UI fuer operative Steuerung | Vorhanden | `Frontend/chat.html`, `Frontend/control_center.html`, `project_config.html` | Zwei sehr grosse Hauptseiten, zusaetzliche Nebenoberflaechen | UI-Sources-of-Truth fragmentieren |
| Buddy als Frontdoor | Teilweise vorhanden | `GET /agents/buddy` lieferte vor dem Frontdoor-Lauf `offline/active:false/phantom:false`; `GET /onboarding/status?user_id=user` -> `known_user:true`, `buddy_running:false`, `should_auto_start:false`; der echte Browserlauf `Frontend/buddy_frontdoor_returning_user.spec.js` startete Buddy aus `buddy_landing.html` heraus erfolgreich; zusaetzlich pruefte `Frontend/buddy_landing_setup.spec.js` real den schnellen Scan `GET /cli/detect?skip_runtime=1`, `POST /agents/buddy/setup-home` und den anschliessenden Buddy-Start; die Landing bietet damit bei mehreren CLIs entweder eine explizite Engine-Auswahl oder uebernimmt fuer Returning Users eine bereits konfigurierte Buddy-Engine direkt; serverseitig ist `/cli/detect` jetzt gegen Parallelaufrufe ueber TTL-Cache plus Single-Flight stabilisiert; `POST /agents/buddy/setup-home` materialisierte live `BRIDGE_OPERATOR_GUIDE.md`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` und `QWEN.md` im Buddy-Home; ein Sofort-Check zeigte danach kurz `phantom:true`, `tmux_alive:true`, und `POST /agents/cleanup {\"ttl_seconds\":0}` entfernte Buddy bei lebender Session nicht mehr; der aktuelle Folgezustand zeigt live `status:waiting`, `online:true`, `phantom:false`, `cli_identity_source:cli_register`, `engine:codex` | Der verifizierte Frontdoor-Pfad deckt jetzt den Buddy-Setup-Schritt, den Returning-User-Fall mit vorhandener Engine und den stabilisierten Scan-Endpunkt ab. Offen bleiben ein kurzer Startfenster-Drift, die konservative `unknown`-Behandlung des Login-Zustands fuer `gemini` und `qwen` sowie der Umstand, dass fruehe programmatische Bootstrap-Wege weiterhin deterministisch auf `existingEngine || recommended || available[0]` zurueckfallen koennen. | Concierge-/Onboarding-Luecke ist stark reduziert; verbleibend ist vor allem ein kurzer Bootstrapping-Race, ein noch nicht voll belegter Multi-CLI-Auth-Scan und eine weiche statt harte Choice-Pflicht im fruehen Bootstrap |
| Agent-Detail-API als Control-Plane-Truth | Teilweise vorhanden | `Backend/team.json` enthaelt fuer `viktor` `active:true` und `auto_start:false`; nach Fix liefern `GET /agents/viktor`, `GET /agents`, `GET /agents?source=team` und `GET /team/orgchart` live getrennt `active:true`, `online:false`, `auto_start:false` | Die Kernprojektionen sind jetzt semantisch getrennt; nicht jeder Downstream-Consumer wurde in diesem Slice separat neu auditiert | Migrations- und Callsite-Risiko bleibt ausserhalb der neu geprueften Hauptprojektionen |
| Task-System mit Ownership | Vorhanden | `tasks.json`, Task-Endpunkte in `server.py`, Team-Projektion in `board_api.py` | Persistenzsnapshot zeigt sehr viele `failed`-Tasks | Rueckstau- oder Althistorienrisiko |
| Reservierung / Scope-Locks | Vorhanden | `scope_locks.json`, UI-Endpunkte, Scope-Unlock im Done-Pfad | Keine kanonische Gesamtregeldatei fuer Ownership-Kollisionen | Konflikt- und Drift-Risiko |
| Workflows / Automationen | Teilweise vorhanden | `workflow_builder.py`, `workflow_registry.json`, `automations.json` | Persistierte Nutzung im Snapshot sehr schmal | Feature-Tiefe > reale Nutzung |
| Beobachtbarkeit / Evidence | Vorhanden | `evidence/`, `messages/bridge.jsonl`, Whiteboard, Logs | Artefakte verteilt ueber viele Ordner | Hoher Navigationsaufwand |
| Packaging / Install / Run | Teilweise vorhanden | `pyproject.toml`, `bridge_ide/cli.py`, `install.sh`, Docker-Artefakte, verifizierter Compose-Lauf auf `19111/19112` | Shell-/CLI-Pfad und Docker-Control-Plane-Pfad sind jetzt getrennt verifiziert; nur die nativen CLI-Runtimes bleiben hostgebunden. Das ist fuer Host-Betrieb tragfaehig, aber release-kritisch, wenn Fremdnutzer Docker als vollstaendigen Ein-Kommando-Pfad erwarten. | Verwechslungsrisiko zwischen Control Plane und CLI-SoT |
| Claude-Code-Integration / Multi-Profile-Steuerung | Teilweise vorhanden | `Backend/tmux_manager.py`, `Backend/server.py`, `Backend/team.json`, `2026-03-13_Claude_Anthropic_Credential_Audit.md`, offizielles `claude auth status`, reale `POST /agents/claude/start`- und `POST /runtime/configure`-Laeufe | Der harte Claude-Datei-/Onboarding-Eingriff ist im Hauptpfad weitgehend entfernt: `tmux_manager.py` liest/symlinkt/patched keine Claude-Credential-Dateien mehr, `server.py` beantwortet `/subscriptions` fuer Claude ueber `claude auth status`, der Startpfad projiziert jetzt offizielle Session-Zustaende wie `manual_setup_required`, `login_required`, `usage_limit_reached` und `registration_missing`, und auto-detected Codex/Gemini/Qwen-Profile werden im Subscription-Pfad nicht mehr aus lokalen Auth-Dateien angereichert. Offen bleiben die produktive Multi-Profil-Semantik (`sub1`/`sub2` melden aktuell denselben offiziell sichtbaren Account), der Buddy-getriebene Operatorpfad und der fail-closed Runtime-Blocker, solange Claude manuelle Session-Interaktion braucht. | Compliance-/Reproduzierbarkeits- und Steuerungsrisiko bleibt, aber jetzt eher durch Profil- und Betriebssemantik als durch direkte Credential-Dateisurgery |
| Host-neutrale Frontend-Topologie | Teilweise vorhanden | `Frontend/bridge_runtime_urls.js` loest fuer `chat.html`, `control_center.html`, `project_config.html`, `task_tracker.html`, `buddy_landing.html` und `buddy_widget.js` API-/WS-Basen jetzt hostneutral auf; Playwright-Spec `Frontend/bridge_runtime_urls.spec.js` pruefte reale Browserpfade fuer `127.0.0.1`, `localhost` und Same-Origin-Proxy | Der lokale Dev-Mapping-Pfad auf `9111/9112` und derselbe Host hinter Reverse Proxy sind jetzt sauber belegt; nicht jede moegliche Fremdtopologie ist separat geprueft | Deutlich reduziertes Deployment-/Reproduzierbarkeitsrisiko, aber kein Freibrief fuer beliebige Proxy-Topologien |
| Gesamt-Dokumentation als SoT | Teilweise vorhanden | `docs/frontend/*`, `docs/config/team-json.md`, Root-Dokus | Keine aktive, kanonische Gesamtarchitektur- und API-Doku | Orientierungsverlust |

## Datenfluss / Kontrollfluss
Die Gap-Map entsteht aus dem Vergleich von Vision und beobachtetem Fluss:

1. Vision verlangt einen klar steuerbaren Live-Kern.
2. Real existiert dieser Kern, aber verteilt ueber Monolith, MCP, Watcher, tmux und dateibasierte Stores.
3. Vision verlangt nachvollziehbare Zustandsmodelle.
4. Real existieren diese, aber in vielen getrennten Dateien und Projektionen.
5. Vision verlangt belastbare Nutzerfuehrung.
6. Real existieren UI und Doku, aber ohne durchgehend kanonische Gesamterklaerung.

## Abhängigkeiten
- technische Kernabhaengigkeiten des Backends und der Agent-Runtime
- dateibasierte Persistenz
- optionale externe Systeme wie n8n
- operative UI-Verbraucher

## Auffälligkeiten
- Die groessten Luecken liegen weniger im kompletten Fehlen grosser Features als in Ueberlagerung, Fragmentierung und Dokumentationsdrift.
- Mehrere Visionselemente sind gleichzeitig "vorhanden" und "fragil", weil sie auf mehreren Kontrollpfaden beruhen.
- Die Plattform wirkt code- und featureschwerer als ihre aktive Root-Dokumentation.

## Bugs / Risiken / Inkonsistenzen
- Register-, Claim- und Runtime-Inkonsistenzen sind real belegt.
- Das Ownership-Modell verteilt Verantwortung auf Team-Hierarchie, Task-Zuweisung, Scope-Lock und Whiteboard.
- Die Start- und Persistenzpfade sind nicht aus einem einzigen SoT ableitbar.
- Dokumentierte und reale Artefakte laufen teilweise auseinander.
- Die aktuelle Claude-Subscription-/Account-Wahrheit ist nicht sauber an offizielle CLI-Evidenz gebunden.

## Offene Punkte
- Welche Luecken als produktkritisch und welche als dokumentarisch-kognitiv priorisiert werden sollen, ist eine Folgeentscheidung ausserhalb dieser Analyse.
- Ob die groessten Risiken derzeit aus Laufzeit, Root-Struktur oder Doku-Drift kommen, braeuchte Live-Evidenz fuer eine harte Priorisierung.
- Das Zielbild fuer Claude ist jetzt in `W10_Claude_Code_Subscriptions_Buddy_Spec.md` konkretisiert; offen bleibt die Produktentscheidung, wann der Legacy-Credential-Pfad zugunsten des Buddy-/Official-Mode wirklich herausgenommen wird.

## Offene Punkte
- Wie viele der hier markierten Luecken im aktuellen Live-Betrieb bereits aktiv stoeren.
- Ob weitere ungesichtete Teilbereiche des Root-Baums zusaetzliche kanonische Artefakte enthalten.
