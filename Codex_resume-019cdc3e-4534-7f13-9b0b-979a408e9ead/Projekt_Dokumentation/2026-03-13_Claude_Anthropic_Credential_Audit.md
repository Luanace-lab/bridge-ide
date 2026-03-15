# 2026-03-13 Claude/Anthropic Credential Audit

## Scope

Auditgegenstand war der reale technische Ist-Zustand der aktuellen BRIDGE im Umgang mit Claude/Anthropic.

Geprueft wurden:
- gesamtes `/home/user/bridge/BRIDGE`-Repository
- relevante Konfigurationen und Startpfade
- reale lokale Claude-Config-Verzeichnisse `/home/user/.claude` und `/home/user/.claude-sub2`

Methodik:
- repo-weite Textsuche
- gezielte Codeinspektion der Claude-/Server-/MCP-/Watcher-Pfade
- redaktionssichere Inspektion real vorhandener Claude-Konfigurationsdateien ohne Geheimwerte auszugeben

## LAGE

Die aktuelle BRIDGE nutzt fuer Claude nicht nur eine lokal vorhandene offizielle Claude-CLI als Black-Box.

Die aktuelle Architektur arbeitet aktiv mit lokalen Claude-Consumer-Auth- und Onboarding-Artefakten:
- `.credentials.json`
- `.claude.json`
- `CLAUDE_CONFIG_DIR`
- OAuth-/Onboarding-Zustaenden

Gleichzeitig wurde im geprueften Repository keine Code-Evidenz gefunden, dass BRIDGE Claude-OAuth-Access- oder Refresh-Tokens ueber eigene MCP-, WebSocket-, History- oder Heartbeat-Pfade an andere Systeme weiterreicht.

Der zentrale technische Befund ist heute zweigeteilt:

- historisch war BRIDGE ein aktiver Teil des lokalen Claude-Credential-/Onboarding-Handlings
- im aktuellen Code ist der harte Claude-Datei-/Onboarding-Eingriff bereits weitgehend entfernt; verbleibend sind jetzt vor allem Profilzuordnung, offizielle `claude auth status`-Beobachtung und die Projektion manueller First-Run-/Login-Zustaende

## EVIDENZ

### Reale lokale Claude-Auth-Artefakte

Verifiziert durch Ausfuehrung.

In den realen lokalen Config-Verzeichnissen wurden folgende Dateitypen und Schluessel beobachtet:

- `/home/user/.claude/.credentials.json`
  - Top-Level: `claudeAiOauth`
  - Schluessel: `accessToken`, `refreshToken`, `expiresAt`, `rateLimitTier`, `scopes`, `subscriptionType`
- `/home/user/.claude/.claude.json`
  - Top-Level enthaelt `oauthAccount`
  - Schluessel u. a.: `emailAddress`, `billingType`, `displayName`, `accountUuid`, `subscriptionCreatedAt`
- `/home/user/.claude-sub2/.credentials.json`
  - Top-Level: `claudeAiOauth`, `mcpOAuth`
- `/home/user/.claude-sub2/.claude.json`
  - Top-Level enthaelt `oauthAccount`, `hasCompletedOnboarding`, `lastOnboardingVersion`, `projects`

Damit ist technisch belegt, dass im aktuellen lokalen Betriebszustand echte Claude-Consumer-OAuth-Artefakte vorhanden sind und dass mindestens ein Claude-Subscription-Path zusaetzlich `mcpOAuth`-Artefakte enthaelt.

### Claude-Start- und Credential-Pfade im Code

#### Historischer Vorbefund
- Die oben genannten Datei-/Patch-/Symlink-/Cache-Pfade waren im Auditstand vor dem W10-Cleanup real vorhanden und wurden gegen das damalige Repository verifiziert.

#### Aktueller Codezustand
- `Backend/tmux_manager.py`
  - verwendet fuer Claude jetzt `_check_claude_auth_status(...)` ueber den offiziellen CLI-Befehl `claude auth status`
  - liest dabei keine `.credentials.json`
  - patcht keine `.claude.json`
  - symlinkt keine Claude-Credential-Dateien in per-Agent-Profile
  - loescht keine Claude-OAuth-/MCP-Auth-Caches
- `Backend/server.py`
  - liest fuer Claude-Subscriptions keine lokalen `.claude.json`-/`.credentials.json`-Metadaten mehr nach
  - beantwortet `GET /subscriptions` fuer Claude jetzt ueber offizielle Profilbeobachtung:
    - `profile_status`
    - `profile_probe=claude auth status`
    - `profile_note`
    - `observed_email`
    - `observed_subscription_type`
- `Backend/server.py`
  - fuehrt fuer Claude keine nicht-interaktive Runtime-Probe ueber `claude -p ok` mehr aus
  - `_probe_cli_runtime_status("claude", ...)` liefert jetzt bewusst `status=unknown`, weil dafuer kein verifizierter offizieller Non-Interactive-Probe mehr konfiguriert ist
- Der eigentliche Claude-Start bleibt ein offizieller CLI-Start mit `CLAUDE_CONFIG_DIR=...` in `tmux`.

### Server-/API-Pfade mit Claude-Credential-Bezug

- Historischer Vorbefund:
  - `Backend/server.py` las beim Laden von `team.json`-Subscriptions `.claude.json` und `.credentials.json` und reicherte daraus Claude-Account-/Plan-Felder an.
- Aktueller Stand:
  - dieser Dateipfad ist im aktiven Serverpfad entfernt
  - `GET /subscriptions` nutzt fuer Claude nur noch `claude auth status`
  - auto-detected Codex/Gemini/Qwen-Profile werden im aktiven Serverpfad nicht mehr aus `~/.codex/auth.json`, `~/.gemini/google_accounts.json` oder `~/.qwen/oauth_creds.json` angereichert
- `Backend/server.py:6953-6999`
  - `_get_runtime_config_dir()` versucht `CLAUDE_CONFIG_DIR` aus der laufenden tmux-Session zu lesen und faellt sonst auf `team.json` bzw. bekannte `~/.claude*`-Pfade zurueck.
- `Backend/server.py:7692-7699`, `8744-8766`, `9097-9130`
  - Der Server erkennt Claude-OAuth-Prompts (`Paste code here if prompted`) und behandelt sie als Auth-Fehler-/Restart-Fall.
- `Backend/server.py:11768-11803`, `13358-13388`, `20441-20448`
  - `config_dir`, `subscription_id` und daraus abgeleitete Subscription-Metadaten werden ueber API-Pfade projiziert.

### Watcher-/Recovery-Pfade

- `Backend/bridge_watcher.py:758-788`
  - Der Watcher erkennt explizit den Claude-OAuth-Prompt.
- `Backend/bridge_watcher.py:946-969`
  - Bei OAuth-Stuck-State killt der Watcher die Session und triggert `POST /agents/{id}/start`.

### Memory-/Config-Kopplung an Claude-Config-Pfade

- `Backend/persistence_utils.py:154-190`
  - Memory-Suche faellt auf `~/.claude-agent-{id}`, `~/.claude-sub2` und `~/.claude` zurueck.
  - `find_agent_memory_path()` sucht unter `config_dir/projects/.../memory/MEMORY.md`.

### Separate Anthropic-API-Key-Pfade

- `Backend/bridge_mcp.py:8016-8112`
  - `bridge_vision_analyze` spricht `https://api.anthropic.com/v1/messages` direkt an und nutzt dafuer `ANTHROPIC_API_KEY`.
- `Backend/bridge_mcp.py:8217-8263`, `8336-8338`
  - Weitere Vision-/Action-Pfade verwenden ebenfalls `ANTHROPIC_API_KEY`.

Das ist technisch ein eigener Anthropic-API-Key-Pfad und nicht dasselbe wie Claude.ai-Consumer-OAuth.

### Abgrenzung zum Bridge-eigenen Credential Store

- `Backend/credential_store.py:1-120`
  - Der BRIDGE-Credential-Store verschluesselt eigene Geheimnisse unter `~/.config/bridge/credentials`.
  - Zulaessige Services sind `google`, `github`, `email`, `wallet`, `phone`, `custom`.
- `Backend/server.py:12989-13023`, `15715-15744`
  - Die API-Endpunkte `/credentials/...` verwenden diesen Store.

Im geprueften Code wurde kein eigener `claude`- oder `anthropic`-Service im Bridge-Credential-Store gefunden.

## AUTH-FLUSS

Der beobachtbare technische Auth-/Startfluss fuer Claude ist aktuell:

1. `Backend/team.json` weist einem Claude-Agenten ein offizielles Profilverzeichnis ueber `config_dir` zu.
2. Ein Startpfad wie `POST /agents/{id}/start` oder `POST /runtime/configure` reicht dieses Profil an den offiziellen Claude-CLI-Start in `tmux` weiter.
3. `Backend/tmux_manager.py` prueft den groben Profilzustand vorab nur noch ueber `claude auth status`.
4. BRIDGE liest oder patcht dabei keine Claude-Credential-Dateien mehr.
5. Wenn Claude in der Session offiziell manuelle Interaktion braucht, wird dieser Zustand jetzt aus der sichtbaren Session-Ausgabe projiziert, nicht aus lokalen Credential-Dateien:
   - `manual_setup_required`
   - `login_required`
   - `registration_missing`
6. `GET /subscriptions` beobachtet Claude-Profile ueber `claude auth status` und nicht mehr ueber `.claude.json`/`.credentials.json`.

Damit ist der aktuelle Claude-Pfad deutlich naeher an einem credential-blinden Wrapper; die verbleibende Kopplung liegt jetzt im Profil- und Session-Handling, nicht mehr in lokaler Credential-Dateisurgery.

## BRIDGE-ROLLE

Die aktuelle BRIDGE steuert Claude weiter aktiv als lokale Control Plane, aber nicht mehr ueber direkte Credential-Datei-Operationen.

Technisch sichtbar ist folgende Rolle:
- BRIDGE startet Claude in tmux.
- BRIDGE setzt `CLAUDE_CONFIG_DIR`.
- BRIDGE beobachtet den offiziellen Profilzustand ueber `claude auth status`.
- BRIDGE projiziert sichtbare Session-Zustaende wie `manual_setup_required`, `login_required` und `registration_missing`.
- BRIDGE projiziert in `/subscriptions` nur noch offizielle Profilbeobachtung statt lokaler Account-/Plan-Dateiwahrheit.

Damit ist BRIDGE aktuell kein vollstaendig neutraler Black-Box-Starter, aber der aktive Umgang mit Claude-Consumer-Credential-/Onboarding-Dateien ist im geprueften Hauptpfad entfernt.

Technisch nicht belegt ist dagegen, dass BRIDGE selbst den OAuth-Login ausstellt oder selbst OAuth-Tokens fuer Claude mintet.

## MCP-/SERVER-BEZUG

### Beobachteter Claude-Bezug in der Server-Schicht

- Historisch las der Server Claude-Credential-Dateien fuer Subscription-/Account-Metadaten.
- Verifiziert durch Ausfuehrung: Der erste Cleanup-Slice ist jetzt umgesetzt; `load_team_config()` liest fuer Claude-Subscriptions nicht mehr `.claude.json` oder `.credentials.json`, um `email`, `display_name`, `billing_type`, `plan` oder `rate_limit_tier` nachzureichern.
- Der Server verwendet `config_dir` als zentrales Claude-Start- und Zuordnungsfeld.
- Der Server erkennt Claude-OAuth-Stuck-States und steuert Restart-/Recovery.
- Der Server unterdrueckt regelmaessig `mcp-needs-auth-cache.json` in Claude-Config-Pfaden.

### Beobachteter Claude-Bezug in MCP-Pfaden

Im geprueften Repository wurde keine Code-Evidenz gefunden, dass BRIDGE-MCP Claude.ai-OAuth-Access- oder Refresh-Tokens ueber folgende Pfade transportiert:
- Register
- Heartbeat
- Receive
- History
- WebSocket-Push

Die Bridge-MCP-Schicht hat allerdings zwei andere relevante Secret-/Auth-Aspekte:

- Eigene BRIDGE-Register-/Session-Tokens in `~/.config/bridge/...`
- direkte Anthropic-API-Key-Nutzung ueber `ANTHROPIC_API_KEY` fuer Vision-Funktionen

### Browser-/Cookie-Bezug

`Backend/bridge_mcp.py` enthaelt generische Browser-Cookie-Persistenz unter `~/.config/bridge/browser_cookies`.

Im geprueften Code wurde keine harte Bindung dieser Cookie-Persistenz an Claude.ai-/Anthropic-Consumer-Login gefunden.

## Historischer Live-Nachtrag 2026-03-13 vor Cleanup-Slice 2

Verifiziert durch Ausfuehrung.

- `/home/user/.claude/.credentials.json` und `/home/user/.claude-sub2/.credentials.json` enthalten aktuell nicht abgelaufene Token-Expiries.
- Die operative Headless-Pruefung
  - `env CLAUDE_CONFIG_DIR=/home/user/.claude claude -p ok --output-format text`
  - `env CLAUDE_CONFIG_DIR=/home/user/.claude-sub2 claude -p ok --output-format text`
  scheitert auf beiden Profilen derzeit gleichlautend mit:
  - `You've hit your limit · resets Mar 16, 2am (Europe/Berlin)`
- Die offizielle Statuspruefung
  - `env CLAUDE_CONFIG_DIR=/home/user/.claude claude auth status`
  - `env CLAUDE_CONFIG_DIR=/home/user/.claude-sub2 claude auth status`
  liefert derzeit fuer beide Profilpfade:
  - `loggedIn: true`
  - `authMethod: "claude.ai"`
  - `email: "owner@example.com"`
  - `subscriptionType: "max"`
- Damit ist aktuell offiziell belegt:
  - beide Profilpfade sind lokal getrennte Verzeichnisse
  - die heutige `sub1`-/`sub2`-Wahrheit in `team.json` bildet aber nicht zwei unterschiedliche offiziell sichtbare Claude-Accounts ab
  - die serverseitige Subscription-/Account-Projektion aus lokalen Claude-Dateien ist damit nicht belastbar genug, um als kanonische Multi-Account-Truth zu gelten
- Der damalige Runtime-Blocker fuer den nativen `codex-claude`-Pfad war damit nicht primaer ein fehlender oder abgelaufener OAuth-Token, sondern ein realer Claude-CLI-Limitzustand.
- `POST /runtime/configure` projizierte diesen Zwischenstand damals explizit als:
  - `error_stage=credential_prevalidation`
  - `error_reason=usage_limit_reached`
  - `error_detail=You've hit your limit · resets Mar 16, 2am (Europe/Berlin)`
- Dieser Abschnitt ist historisch; der aktuelle Post-Cleanup-Zustand steht im folgenden Cleanup-Slice-2-Nachtrag.

## Live-Nachtrag 2026-03-13 — Cleanup-Slice 1

Verifiziert durch Ausfuehrung.

- `Backend/server.py` wurde in diesem Slice so geaendert, dass `load_team_config()` Claude-Subscriptions nicht mehr aus `.claude.json` oder `.credentials.json` anreichert.
- Neuer Vertragstest:
  - `Backend/tests/test_subscription_metadata_contract.py`
  - beweist, dass eine Claude-Subscription ohne gesetzte Felder nach `load_team_config()` nicht mehr mit Daten aus lokalen Credential-Dateien befuellt wird.
- Reale Ausfuehrung:
  - `python3 -m py_compile Backend/server.py Backend/tests/test_subscription_metadata_contract.py`
  - `pytest -q Backend/tests/test_subscription_metadata_contract.py Backend/tests/test_buddy_setup_contract.py Backend/tests/test_agent_start_contract.py`
  - kanonischer Neustart ueber `Backend/stop_platform.sh` und `Backend/start_platform.sh`
  - `GET /subscriptions` blieb danach real funktionsfaehig
- Reale Log-Evidenz:
  - im aktuellen `Backend/logs/server.log` wurde nach diesem Neustart kein erneutes `Auto-detected email for ...` aus dem entfernten Claude-Metadatenpfad beobachtet

Damit ist der Server fuer Claude noch nicht credential-blind, aber die serverseitige Account-/Plan-Projektion aus lokalen Claude-Dateien ist als eigener erster Cleanup-Slice entfernt.

## Live-Nachtrag 2026-03-13 — Cleanup-Slice 2

Verifiziert durch Ausfuehrung.

- `Backend/tmux_manager.py` enthaelt im aktuellen Stand keine aktiven Claude-Dateioperationen mehr fuer:
  - `.credentials.json` lesen
  - `.claude.json` patchen
  - Credential-Symlinks
  - `mcp-needs-auth-cache.json` loeschen
  - `claude -p ok` als Start-Prevalidation
- reproduzierter Testlauf:
  - `pytest -q Backend/tests/test_persistence_hardening.py Backend/tests/test_tmux_manager_adapter.py Backend/tests/test_codex_resume.py`
  - Ergebnis: `90 passed`
- `GET /subscriptions` liefert fuer Claude-Profile aktuell nur noch:
  - leere Legacy-Felder `email`, `plan`, `billing_type`, `display_name`, `account_created_at`, `rate_limit_tier`
  - plus offizielle Beobachtung:
    - `profile_status`
    - `profile_probe=claude auth status`
    - `profile_note`
    - `observed_email`
    - `observed_subscription_type`
- `Backend/server.py` sanitisiert seit dem Folgeslice auch bereits persistierte auto-detected Nicht-Claude-Profile:
  - `codex`, `gemini` und `qwen` bleiben als erkannte Profile sichtbar
  - `email`, `plan`, `billing_type`, `display_name`, `account_created_at`, `rate_limit_tier` werden fuer diese auto-detected Profile nicht mehr aus lokalen Auth-Dateien als Produktwahrheit gehalten
  - `GET /subscriptions` zeigte dies danach real mit leeren Legacy-Feldern fuer `codex`, `gemini` und `qwen`
- `GET /cli/detect?skip_runtime=0` behandelt Claude-Runtime aktuell bewusst konservativ:
  - `auth_status=authenticated`
  - `runtime_status=unknown`
  - `runtime_note=No verified non-interactive runtime probe configured for Claude`
- `POST /agents/claude/start` lieferte im aktuellen Live-Lauf:
  - `status=manual_setup_required`
  - `message=Claude Code first-run setup requires a manual theme selection in the session.`
- `POST /runtime/configure` lieferte im aktuellen Live-Lauf nach dem Cleanup explizit:
  - `failed[0].error_stage=interactive_setup`
  - `failed[0].error_reason=login_required`
  - `failed[0].error_detail=Claude Code is waiting for official login confirmation in the session.`
- ein weiterer verifizierter Lauf zeigte denselben Fail-Closed-Pfad spaeter als:
  - `failed[0].error_stage=runtime_stabilization`
  - `failed[0].error_reason=registration_missing`
  - `failed[0].error_detail=Agent session did not register with the Bridge within the stabilization window.`
- Der Health-/Startpfad behandelt den offiziellen Claude-Login-Prompt im aktuellen Code nicht mehr als verdeckten Restart-Fall; der manuelle Nutzerzustand wird jetzt explizit projiziert.

## OFFENE PUNKTE

### 1. Live-Traffic-Nachweis fuer ausgehende Token-Emission durch BRIDGE

`Nicht verifiziert.`

Harter Blocker:
- Der aktuelle Audit-Scope war Repository plus relevante Konfigurationen.
- Eine belastbare Aussage ueber reale Netzwerk-Emissionen der laufenden Prozesse wuerde zusaetzliche Live-Traffic- oder Syscall-Instrumentierung erfordern.

Bereits versucht:
- repo-weite Suche nach Claude-/OAuth-/Header-/Token-/Cookie-Pfaden
- gezielte Inspektion der relevanten Server-, MCP-, Watcher- und Startpfade

Warum aktuell nicht weiter aufloesbar:
- Ohne Laufzeitinstrumentierung waere jede weitergehende Behauptung ueber reale Netzwerkausleitung spekulativ.

Welche minimale Zusatzvoraussetzung zur Verifikation fehlt:
- ein instrumentierter Live-Start eines Claude-Agenten mit Prozess-/Netzwerk-Trace des BRIDGE-Server- und tmux-Startpfads

### 2. Externe unversionierte Hilfsskripte ausserhalb des geprueften Scope

`Nicht verifiziert.`

Harter Blocker:
- Der Audit bezog sich auf das Repository und relevante bekannte Konfigurationen.
- Unversionierte lokale Automationen ausserhalb dieses Scope sind nicht vollstaendig beweisbar abgedeckt.

Bereits versucht:
- repo-weite Code- und Doku-Suche
- Inspektion der relevanten lokalen Claude-Konfigurationsverzeichnisse

Warum aktuell nicht weiter aufloesbar:
- Eine systemweite Suche ausserhalb des definierten Scope waere eine Scope-Erweiterung.

Welche minimale Zusatzvoraussetzung zur Verifikation fehlt:
- Freigabe fuer eine explizite systemweite Suche ausserhalb des Repository-Scope

## URTEIL

Technisch im Hauptpfad deutlich bereinigt, aber noch nicht vollstaendig credential-blind im Gesamtprodukt

## BEGRUENDUNG

Diese Einstufung basiert auf beobachteter technischer Evidenz, nicht auf rechtlicher Interpretation.

Der aktuelle Hauptpfad ist gegenueber dem historischen Ausgangszustand deutlich bereinigt:
- `tmux_manager.py` liest, symlinkt oder patcht im aktuellen Stand keine Claude-Credential- oder Onboarding-Dateien mehr
- `server.py` reichert Claude-Subscriptions nicht mehr aus `.claude.json` oder `.credentials.json` an
- `/subscriptions` beobachtet Claude-Profile ueber `claude auth status`
- der Start-/Runtime-Pfad projiziert jetzt offizielle Sessionzustaende wie `manual_setup_required`, `login_required` und `registration_missing`

Nicht abgeschlossen ist der Gesamtumbau dennoch, weil:
- `team.json`-/`subscription_id`-/`config_dir`-Semantik weiterhin produktiv fuer Claude-Profile genutzt wird
- Buddy noch nicht der kanonische offizielle Operatorpfad fuer diese Profile ist
- die Gesamtarchitektur fuer Multi-Profil-/Multi-Account-Steuerung noch nicht auf das in W10 beschriebene Zielbild reduziert ist

## EMPFOHLENER NAECHSTER SCHRITT

Der kleinste saubere naechste Verifikationsschritt ist:

Den verbleibenden Claude-Startpfad weiter ueber offizielle Sessionsignale zu pruefen:
- `POST /agents/{id}/start`
- `POST /runtime/configure`
- reale `tmux`-Pane-Ausgabe

und danach den Buddy-/Profil-Operatorpfad so zu bauen, dass weitere manuelle Claude-Interaktion nicht mehr verdeckt von der Bridge, sondern explizit ueber den Nutzer bzw. Buddy erfolgt.
