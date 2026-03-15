# W10_Claude_Code_Subscriptions_Buddy_Spec

## Zweck
Professionelles Entscheidungs- und Spezifikationsdokument fuer den Umbau der Claude-Anbindung.

Dieses Dokument fasst vier Ebenen zusammen:
- Problemraum rund um Anthropic-/Claude-Code-Subscriptions
- aktueller lokaler Audit-Stand
- Zielbild einer credential-blinden Bridge-Control-Plane
- konkrete Gap-/Spec-Definition fuer einen minimalistischen, reproduzierbaren Umbau

## Scope
- offizieller Claude-Code-/Anthropic-Rahmen fuer Consumer-Subscriptions und offizielle Konfigurationsflaechen
- realer lokaler Ist-Zustand im Repository `/home/leo/Desktop/CC/BRIDGE`
- Produktentscheidung:
  - Standardfall ist genau ein offizieller Claude-Account pro Nutzer
  - Mehr-Account ist optional
  - Buddy kann bei Bedarf ein weiteres offizielles Claude-Profil fuer einen Agenten vorbereiten
  - der Nutzer loggt sich in dieses Profil selbst manuell ein

Keine Rechtsberatung.
Dieses Dokument ist eine technische und produktseitige Bewertung auf Basis offizieller Quellen und realer Code-/CLI-Evidenz.

## Externe Richtlinienlage

### 1. Claude Code bleibt offizielles Produkt
- Anthropic beschreibt Claude Code als offizielles Produkt mit eigener Auth-, Session- und Settings-Logik.
- Consumer-OAuth aus Free/Pro/Max ist fuer Claude Code und Claude.ai vorgesehen, nicht fuer ein anderes Produkt oder einen anderen Dienst.
- Quelle:
  - `https://code.claude.com/docs/en/legal-and-compliance`

### 2. Offizielle Konfigurationsflaechen sind dokumentiert
- Offizielle Settings-/Projektflaechen sind:
  - `~/.claude/settings.json`
  - `.claude/settings.json`
  - `.claude/settings.local.json`
  - `CLAUDE.md`
  - `.claude/agents/`
  - Hooks
  - MCP
  - `CLAUDE_CONFIG_DIR`
- Quelle:
  - `https://docs.anthropic.com/en/docs/claude-code/settings`

### 3. MCP ist der offizielle Integrationsweg
- Externe Tools und Datenquellen sollen fuer Claude Code ueber MCP angebunden werden.
- Quelle:
  - `https://docs.anthropic.com/en/docs/claude-code/mcp`

### 4. Nutzerverantwortung fuer Consumer-Accounts bleibt beim Nutzer
- Consumer Terms und die Agent-Nutzungsrichtlinie verschieben die Verantwortung fuer Login und Accountnutzung nicht auf ein fremdes Produkt.
- Relevante offizielle Quellen:
  - `https://www.anthropic.com/legal/consumer-terms`
  - `https://support.claude.com/en/articles/12005017-using-agents-according-to-our-usage-policy`

### 5. Verbleibende Policy-Grenze bei Consumer-Automation
- Die Consumer Terms untersagen den Zugriff ueber automatisierte oder nicht-menschliche Mittel, ausser wo Anthropic dies ausdruecklich erlaubt.
- Die Claude-Code-Legal-Seite untersagt ausserdem, Free/Pro/Max-OAuth fuer ein anderes Produkt, Tool oder einen anderen Dienst zu verwenden oder Requests im Namen von Nutzern ueber diese Consumer-Credentials zu routen.
- Quellen:
  - `https://www.anthropic.com/legal/consumer-terms`
  - `https://code.claude.com/docs/en/legal-and-compliance`

## Aktueller Audit-Stand

### Reale Code-Evidenz
Verifiziert durch Ausfuehrung.

Der aktuelle Code ist fuer Claude noch nicht credential-blind:

- `Backend/tmux_manager.py`
  - setzt `CLAUDE_CONFIG_DIR`
  - nutzt fuer Claude jetzt nur noch den offiziellen groben Profilcheck `claude auth status`
  - liest, symlinkt oder patcht im aktuellen Stand keine Claude-Credential-/Onboarding-Dateien mehr
- `Backend/server.py`
  - hat den Cleanup der serverseitigen Claude-Datei-Projektion bereits hinter sich
  - beantwortet `/subscriptions` fuer Claude jetzt ueber `claude auth status`
  - verwaltet weiter `subscription_id` und `config_dir` als produktive Claude-Profilzuordnung
  - auto-detektiert nicht-Claude-Profile jetzt nur noch ueber Profilverzeichnis-Praesenz (`~/.codex`, `~/.gemini`, `~/.qwen`) und nicht mehr ueber lokale Auth-Artefakte
  - strippt historische auto-detected Account-Metadaten fuer Codex/Gemini/Qwen aus `team.json`, damit `/subscriptions` dafuer keine lokale Auth-Dateiwahrheit mehr projiziert

Die Details sind im kanonischen Audit dokumentiert:
- `2026-03-13_Claude_Anthropic_Credential_Audit.md`

### Reale offizielle CLI-Evidenz
Verifiziert durch Ausfuehrung.

Offizielle Claude-CLI-Oberflaechen sind lokal vorhanden:
- `claude --help`
- `claude auth --help`
- `claude mcp --help`

Wichtiger Live-Befund:
- `env CLAUDE_CONFIG_DIR=/home/leo/.claude claude auth status`
- `env CLAUDE_CONFIG_DIR=/home/leo/.claude-sub2 claude auth status`

Beide offiziellen CLI-Statusabfragen lieferten aktuell:
- `loggedIn: true`
- `authMethod: "claude.ai"`
- `email: "lube.trading@outlook.de"`
- `subscriptionType: "max"`

Damit ist aktuell offiziell belegt:
- beide konfigurierten Claude-Profilpfade sind lokal getrennte Verzeichnisse
- sie melden sich aber derzeit gegen denselben offiziell sichtbaren Claude-Account

Zusatzbefund:
- `env CLAUDE_CONFIG_DIR=/home/leo/.claude claude -p ok --output-format text`
- `env CLAUDE_CONFIG_DIR=/home/leo/.claude-sub2 claude -p ok --output-format text`

lieferten beide aktuell:
- `You've hit your limit · resets Mar 16, 2am (Europe/Berlin)`

## Problemdefinition

### Problem A: Bridge ist aktuell kein credential-blinder Wrapper
Die Bridge ist fuer Claude heute deutlich naeher am credential-blinden Wrapper als im historischen Auditstand, aber noch nicht vollstaendig im Zielbild.

Das betrifft insbesondere:
- verbleibende Produktsemantik rund um Profile, Zuordnung und Runtime-Status
- fail-closed Verhalten bei offiziellen First-Run-/Login-Zustaenden
- noch nicht vollstaendig auf Buddy verlagerten Multi-Profil-Betrieb

Fuer die weiteren lokal unterstuetzten CLIs liegt die Restluecke jetzt nicht mehr in serverseitigem Auth-Dateilesen, sondern in uneinheitlicher offizieller Auth-/Ready-Beobachtung.

### Problem B: Subscription-Wahrheit ist instabil
`Backend/team.json` fuehrt aktuell `sub1` und `sub2` als unterschiedliche Claude-Subscriptions mit unterschiedlichen Nutzeridentitaeten.

Die offizielle CLI-Evidenz zeigt jedoch aktuell:
- beide Profilpfade melden denselben Claude-Account

Damit ist die heutige serverseitige Subscription-/Account-Wahrheit nicht robust genug, um als belastbare Produkt-SoT fuer Multi-Account-Steuerung zu gelten.

### Problem C: Reproduzierbarkeit leidet
Das aktuelle Modell setzt lokales Wissen und lokale Credential-Dateien voraus.

Fuer einen Fremdnutzer ist das schlecht reproduzierbar, weil:
- Claude natuerlich selbst installiert und eingeloggt sein muss
- die Bridge heute zusaetzlich lokale Credential-/Onboarding-Strukturen interpretiert
- diese Interpretation nicht kanonisch genug ist

### Problem D: Das heutige Modell bleibt policy-seitig zu nah an "Produkt steuert Consumer-Credentials"
Auch wenn der OAuth-Login nicht von der Bridge ausgestellt wird, nutzt die aktuelle Bridge lokale Consumer-Credential-Artefakte operativ und projiziert daraus Produktwahrheit.

Das ist deutlich naeher an einem "anderen Produkt/Tool/Service", das Consumer-Credentials operationalisiert, als an einem rein beobachtenden lokalen Wrapper.

## Zielbild

## Leitsatz
Bridge besitzt Produktlogik und Orchestrierung.
Claude Code besitzt Auth, Session, Credentials und Runtime-Identitaet.

## Produktprinzip
Der einfache und kanonische Produktfall ist:
- ein Nutzer
- ein offiziell eingeloggter Claude-Code-Account
- beliebig viele Claude-Agents auf diesem einen offiziellen Profil

Mehr-Account ist kein Standardfall, sondern ein optionaler Erweiterungsfall.
Wenn ein Nutzer bewusst ein zweites offizielles Claude-Profil verwenden will, dann:
- bereitet Buddy dieses zusaetzliche Profil vor
- fordert den Nutzer zum manuellen Login auf
- und haengt erst danach gezielt neue oder verschobene Agents an dieses Profil

### 1. Bridge wird credential-blind gegenueber Claude
Die Bridge darf fuer Claude:
- Prozesse starten
- Prozesse beobachten
- `tmux`-Sessions verwalten
- Arbeitsverzeichnisse und offizielle Projektflaechen vorbereiten
- MCP, Hooks, `CLAUDE.md` und `.claude/settings*.json` nutzen

Die Bridge darf fuer Claude nicht mehr:
- `.credentials.json` lesen
- `.claude.json` patchen oder als Account-Truth lesen
- OAuth-Caches loeschen oder Onboarding umgehen
- Billing-/Plan-/Display-Metadaten aus lokalen Claude-Dateien projizieren

### 2. Buddy wird der offizielle User-Delegate
Buddy uebernimmt Multi-Profile-Steuerung und Concierge-Aufgaben ueber offizielle Wege.

Das bedeutet:
- Buddy darf alles, was der User in Claude Code offiziell tun darf
- Buddy arbeitet ueber offizielle CLI-/Session-Oberflaechen
- der User loggt sich weiterhin selbst manuell ein und bestaetigt sensible Schritte
- Buddy ist dabei nicht auf Claude festgelegt: der aktive Setup-Entry scannt mehrere installierte CLIs und materialisiert engine-spezifische Home-Dateien (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `QWEN.md`) plus `BRIDGE_OPERATOR_GUIDE.md` fuer das Buddy-Home
- der aktuelle Setup-Stand nutzt dafuer den kanonischen Endpunkt `GET /cli/detect`; `buddy_landing.html` verwendet die schnelle Form `skip_runtime=1`, waehrend der Backend-Endpunkt denselben Scan mit kurzem TTL-Cache und Single-Flight stabilisiert
- dadurch bleibt die Bridge Wrapper und Setup-Control-Plane auch dann, wenn Buddy selbst spaeter auf Codex, Claude, Gemini oder Qwen laufen soll

### 3. Multi-Profile werden als offizielle Profile behandelt
`subscription_id` und `config_dir` duerfen nicht mehr semantisch als aus Dateien "bewiesene Accounts" behandelt werden.

Stattdessen:
- Profile sind zunaechst opake offizielle Claude-Profile
- ihr Zustand wird ueber offizielle CLI-Ausgabe ermittelt
- Buddy kann Agents zwischen Profilen verschieben
- Buddy kann bei Bedarf ein neues offizielles Zielprofil fuer einen neuen Agenten vorbereiten
- die Produktwahrheit lautet dann:
  - welchem Profil ist ein Agent zugeordnet
  - ist das Profil offiziell eingeloggt
  - ist das Profil aktuell bereit, limitiert oder degradiert

## Was funktional erhalten bleiben kann

### Erhaltbar ohne Kernverlust
- Boards
- Tasks
- Whiteboard
- Messaging
- Buddy
- Workflows / n8n-Wrapper
- Scope-Locks
- `tmux`-basierte Agent-Runtime
- Multi-Agent-Orchestrierung
- Bridge-MCP als Tool-Layer

### Teilweise erhaltbar nur ueber offizielle CLI-Wege
- Login-Status
- sichtbare Email
- grober Subscription-Typ
- Ready-/Limit-/Degraded-Zustand

Die offizielle CLI zeigt heute bereits mindestens:
- `loggedIn`
- `email`
- `subscriptionType`
- offizielle Session-Zustaende im laufenden Betrieb, die BRIDGE jetzt direkt projiziert:
  - `manual_setup_required`
  - `login_required`
  - `registration_missing`

### Nicht 1:1 garantiert erhaltbar
- `billing_type`
- `display_name`
- `rate_limit_tier`
- `account_created_at`

Fuer diese Felder ist in diesem Audit kein offizieller CLI-Nachweis als stabile Produktoberflaeche erbracht.

## Gap-/Spec-Definition

## Bewertung gegen Anthropic-/Claude-Richtlinien

### Was das Buddy-Modell klar verbessert
Das vorgeschlagene Buddy-Modell wuerde den aktuellen Hauptkonflikt deutlich reduzieren, weil dann:
- die Bridge keine Claude-Credential-Dateien mehr liest
- die Bridge keine Claude-Onboarding-Dateien mehr patcht
- die Bridge keine Consumer-Account-Metadaten mehr aus lokalen Dateien projiziert
- der Nutzer selbst offiziell in Claude Code eingeloggt bleibt
- Buddy nur ueber offizielle Claude-Code-Oberflaechen, Session-I/O und dokumentierte Konfigurationsflaechen arbeitet

Damit waere das Zielbild technisch und policy-seitig deutlich naeher an:
- lokalem User-Delegate
- offiziellem Claude-Code-Einsatz
- reproduzierbarer BYO-Claude-Code-Nutzung

### Was damit nicht automatisch abschliessend geklaert ist
Nicht verifiziert.

Auch im Buddy-Modell bleibt eine Restunsicherheit:
- Wenn die Bridge als Produkt Consumer-Claude-Code-Sessions automatisiert, koordiniert und operativ fuer Multi-Agent-Arbeit nutzt, kann das weiter als automatisierte oder nicht-menschliche Nutzung eines Consumer-Dienstes bewertet werden.
- Diese Restfrage verschwindet nicht allein dadurch, dass Credential-Dateien nicht mehr gelesen werden.

### Technische Arbeitsannahme fuer einen sauberen Zielpfad
Annahme:
Je lokaler, expliziter, usergesteuerter und credential-blinder der Betrieb ist, desto eher bewegt sich die Bridge in einen technisch und policy-seitig vertretbaren Bereich.

Das bedeutet fuer einen vorsichtigen Zielpfad:
- lokale Ausfuehrung auf dem Rechner des Nutzers
- manueller Login durch den Nutzer
- keine serverseitige Credential-Projektion
- keine verdeckte Auth-/Onboarding-Magie
- Buddy als expliziter User-Delegate
- keine Behauptung, dass die Bridge selbst Claude.ai-Login oder Consumer-Routing anbietet

### Harte Schlussfolgerung
Das Buddy-Modell macht das Zielbild wesentlich sauberer.
Es macht es aber nicht automatisch und abschliessend rechtssicher.

Fuer eine Produktfreigabe mit geringem Policy-Risiko braucht ihr daher zusaetzlich eine klare Produktgrenze:
- Bridge ist lokales Orchestrierungswerkzeug ueber offiziell laufendem Claude Code
- nicht ein gehosteter Dienst, der Consumer-Claude-Nutzung fuer Dritte vermittelt

### MUSS 1
Alle Claude-Credential-/Onboarding-/Trust-Pfade muessen fuer den Claude-Pfad stillgelegt oder entfernt werden:
- Lesen von `.credentials.json`
- Lesen von `.claude.json` fuer Account-/Plan-Projektion
- Symlinking dieser Dateien in per-Agent-Profile
- Onboarding-/Trust-Patching
- Loeschen von OAuth-/MCP-Auth-Caches

### MUSS 2
Claude-Profile muessen als offizielle Bedienprofile behandelt werden, nicht als serverseitig verifizierte Account-Dateiobjekte.

### MUSS 3
Buddy wird der kanonische Multi-Profile-Operator.

Minimaler Buddy-Aktionsraum:
- Profilstatus offiziell pruefen
- neues offizielles Profil fuer einen Agenten vorbereiten
- Session starten/attachen
- Ziel-Agent auf anderes Profil umhaengen
- den Nutzer zum manuellen Login oder zur manuellen Bestaetigung fuehren
- Session-/CLI-Ausgabe lesen und zurueckprojizieren

### MUSS 4
Die Bridge darf nur noch grobe, offiziell beobachtbare Claude-Zustaende projizieren:
- `ready`
- `login_required`
- `usage_limit_reached`
- `degraded`

### MUSS 5
Produktive Claude-Informationen muessen aus offiziellen Oberflaechen stammen:
- `claude auth status`
- reale CLI-Ausgabe
- Prozess-/Exit-Zustaende
- Session-Beobachtung
- offizielle Projektflaechen

### SOLL 1
Die Bridge soll ihre Produktlogik weiter ueber MCP an Claude exponieren:
- Tasks
- Messaging
- Whiteboard
- Workflows
- Reviews
- Statusreports

### SOLL 2
Die UI soll die neue Wahrheit sichtbar machen:
- Profilzuordnung
- `ready` / `login_required` / `usage_limit_reached` / `degraded`
- Buddy als Operatorpfad
- keine vorgespielte Account-Wahrheit aus lokalen Dateien

## Minimaler Migrationsplan

### Schritt 1 - Credential Freeze
- alle Claude-Dateioperationen hinter klaren Kompatibilitaetsgrenzen isolieren
- neuen official-Claude-Mode vorbereiten
- keine neue Logik mehr auf `.credentials.json`/`.claude.json` bauen

### Schritt 2 - Buddy Multi-Profile Operator
- Standardfall bleibt ein einziges offizielles Claude-Profil pro Nutzer
- Buddy bekommt den kanonischen Bedienpfad fuer offizielle Claude-Profile
- Buddy kann bei Bedarf ein zusaetzliches offizielles Profil fuer einen Agenten vorbereiten
- User bleibt fuer Login/Bestaetigung in der Schleife
- Agent-Zuordnung zu Profilen wird ueber Bridge-Produktlogik gepflegt

### Schritt 3 - Subscription-Projektion umbauen
- `/subscriptions` und zugehoerige UI muessen von "serverseitig aus Datei abgeleiteter Account-Truth" auf "offizielle Profile + beobachteter Zustand" umgestellt werden

### Schritt 4 - Legacy entfernen
- Claude-Credential-Reads/Writes/Patches entfernen
- alte Account-/Billing-Projektion entfernen oder klar als Legacy markieren

## Abnahmekriterien

Das Zielbild ist erreicht, wenn:

1. repo-weite Suche fuer den Claude-Pfad keine Credential-Dateisurgery mehr zeigt
2. Buddy Agents zwischen offiziellen Claude-Profilen verschieben kann
3. der User fuer Login/Bestaetigung explizit im Loop bleibt
4. die Bridge nur noch offiziell beobachtbare Claude-Zustaende projiziert
5. Boards, Tasks, Buddy, Messaging, Workflows und `tmux`-Runtime weiter real funktionieren
6. ein Fremdnutzer die Bridge reproduzierbar aufsetzen kann, ohne versteckte lokale Claude-Dateioperationen zu verstehen

## Urteil

Ja, dieses Zielbild ist professionell.

Es ist professionell, weil es:
- das aktuelle Problem klar vom Zielbild trennt
- auf offizieller Produktoberflaeche aufbaut
- die reale lokale Evidenz einbezieht
- Funktionserhalt explizit bewertet
- eine kontrollierte Migration statt eines Totalumbaus vorgibt

Nicht professionell waere:
- weiter lokale Claude-Dateien als versteckte Produkt-SoT zu behandeln
- Buddy nur halb zu denken
- oder "Multi-Account" zu behaupten, obwohl die offizielle CLI aktuell fuer beide Profilpfade denselben Account meldet
