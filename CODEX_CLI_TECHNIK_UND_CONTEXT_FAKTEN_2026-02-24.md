# Codex CLI Technik + Context-Management (Faktenstand)

Stand: 2026-02-24  
Ort: `/home/leo/Desktop/CC/BRIDGE`  
Zweck: Verifizierte Fakten zu `Codex CLI` (offizielle Quellen + lokale Installation auf diesem Rechner) als Basis fuer spaetere Plattform-Entscheidungen in BRIDGE.  
Wichtig: `Kein Code wurde geaendert.` `Keine destruktiven Operationen ausgefuehrt.`

## Scope

Dieses Dokument enthaelt:
- A) Offizielle/aktuelle Fakten aus primaeren Quellen (OpenAI Developers Docs, OpenAI GitHub/CLI-Hilfe)
- B) Lokale Fakten zur installierten Codex CLI auf diesem Rechner (Version, Paketaufbau, Config, Persistenz, Laufzeit)
- C) Fakten zur Context-Verwaltung (offiziell + lokal beobachtbar)

Dieses Dokument enthaelt bewusst noch **keine** finale Handlungsempfehlung / Priorisierung.

---

## A) Offizielle Fakten (Codex CLI / Docs)

### A1. Codex CLI: Betriebsmodi und Kommandos (offiziell + lokal CLI-Hilfe)

Verifiziert:
- Codex CLI unterstuetzt interaktiven Modus (ohne Subcommand) und mehrere Subcommands, u. a.:
  - `exec` (nicht-interaktiv)
  - `review`
  - `resume`
  - `fork`
  - `mcp`
  - `mcp-server`
  - `app-server` (experimentell)
  - `sandbox`
  - `features`
  - `cloud` (experimentell)
- Wichtige globale Optionen:
  - `--profile`
  - `--sandbox` (`read-only`, `workspace-write`, `danger-full-access`)
  - `--ask-for-approval`
  - `--full-auto`
  - `--dangerously-bypass-approvals-and-sandbox`
  - `--search`
  - `--add-dir`
  - `-C/--cd`

Relevanz fuer BRIDGE:
- Codex kann als interaktiver Agent (tmux/TUI) und als nicht-interaktiver Worker (`exec`, `review`) betrieben werden.
- Es gibt bereits eingebaute Konzepte fuer Session-Fortsetzung (`resume`) und Abzweigung (`fork`), was fuer Kontextkontinuitaet wichtig ist.

### A2. Sicherheitsmodell / Sandbox / Approvals (offizielle Docs)

Verifiziert (Docs + lokale Hilfe):
- Linux-Sandbox basiert auf Landlock + seccomp (`codex sandbox linux`; Security Docs).
- `workspace-write` ist ein eigener Sandbox-Typ; `danger-full-access` existiert.
- Approvals sind konfigurierbar (`untrusted`, `on-request`, `never`, etc.).
- `--full-auto` steht fuer low-friction Automation in sandboxed Modus.
- Security Docs nennen geschuetzte Pfade fuer Workspace-Write-Sandbox (u. a. `.git/`, `.env`, `.codex/`).
- Security Docs nennen explizit zusaetzliche Absicherung durch externe Container/VM als sinnvollen Schutz fuer riskante Workloads.

Relevanz fuer BRIDGE:
- BRIDGE-"volle Rechte" und Codex-Sandbox sind zwei verschiedene Ebenen.
- Selbst bei "bypass permissions"/Rollenfreigaben kann Codex intern noch durch Sandbox-Policy begrenzt sein.
- `.codex/` ist in Workspace-Write-Sandbox als geschuetzter Pfad relevant (betrifft lokale Runtime-Config/Trust-Dateien).

### A3. Konfiguration: Hierarchie, Profiles, Projektvertrauen (offizielle Docs)

Verifiziert:
- Codex CLI nutzt `~/.codex/config.toml` als zentrale Konfiguration.
- `-c key=value` ueberschreibt Config-Werte ad hoc (dot-paths moeglich).
- `--profile` waehlt Profile aus `config.toml`.
- Docs beschreiben Projektvertrauen (`[projects."<path>"].trust_level`) und per-Projekt-Einstellungen.
- Docs enthalten `project_doc_max_bytes` / `project_doc_fallback_files` fuer geladene Projektdokumente.
- Docs unterstuetzen Regeldateien in mehreren Namen/Varianten (Rules/AGENTS/CLAUDE, je nach Programm).

Relevanz fuer BRIDGE:
- BRIDGE kann pro Agent/Role systematisch unterschiedliche Profile nutzen (z. B. `manager`, `coder`, `reviewer`).
- Projekt-/Workspace-Vertrauen ist zentral fuer reibungsarme tmux-Starts (Trust-Dialoge vermeiden).
- `project_doc_max_bytes` ist ein direkter Hebel fuer Context-Kosten und Stabilitaet.

### A4. Rules / AGENTS / Skills (offizielle Docs)

Verifiziert:
- Rules-Docs nennen unterstuetzte Regeldateien (inkl. `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `codex.md` je nach Programm).
- Rules werden aus aktueller Datei und Elternverzeichnissen aggregiert (hierarchische Anwendung).
- Skills-Docs beschreiben strukturierte Skills (mit `SKILL.md`) als wiederverwendbare Anweisungs-/Workflow-Bloecke.
- Skills koennen inkludierte Dateien/Assets/skriptbasierte Hilfen enthalten.
- Multi-agent Docs beschreiben eingebaute Child-Agents / Agent-Delegation (experimental feature/config vorhanden).

Relevanz fuer BRIDGE:
- BRIDGE kann Kontext sauber aufteilen:
  - Projektregeln in Root (`CLAUDE.md` / `AGENTS.md`)
  - Agentenspezifische Regeln im jeweiligen Agent-Workspace
  - Wiederkehrende Workflows als Skills
- Das reduziert Prompt-Muell in Nachrichten und erhoeht Konsistenz.

### A5. MCP-Unterstuetzung (offizielle Docs + lokale Hilfe)

Verifiziert:
- Codex CLI kann externe MCP-Server verwalten (`codex mcp list/get/add/remove/login/logout`).
- Docs zeigen `mcp_servers`-Konfiguration mit stdio und streamable HTTP.
- Docs nennen `mcp_servers.<name>.required` (MCP-Server als erforderlich markieren).
- `codex mcp add` unterstuetzt:
  - stdio (`-- <COMMAND>`)
  - HTTP (`--url`)
  - Bearer-Token aus ENV (`--bearer-token-env-var`)
- `codex mcp-server` existiert (Codex selbst als MCP-Server).

Relevanz fuer BRIDGE:
- BRIDGE-MCP laesst sich offiziell/stabil als MCP-Server in Codex einhaengen.
- `required=true` ist ein relevanter Hebel, wenn BRIDGE-Kommunikation Pflicht sein soll.
- Zukunftspfad moeglich: BRIDGE als HTTP-MCP statt nur stdio (wenn gewollt).

### A6. Non-interactive Mode / JSON / Review (offizielle Docs + lokale Hilfe)

Verifiziert:
- `codex exec` unterstuetzt `--json` (JSONL Events), `--ephemeral`, `--output-last-message`.
- `codex review` ist eigener non-interaktiver Review-Subcommand.
- `exec` kann ausserhalb eines Git-Repos mit `--skip-git-repo-check` laufen.

Relevanz fuer BRIDGE:
- Nicht-interaktive Jobs (Build-Checks, Review, Batch-Tasks) koennen sauber vom interaktiven Agentenpfad getrennt werden.
- `--json` ist wertvoll fuer maschinenlesbare Integration/Observability in BRIDGE.
- `--ephemeral` ist wichtig fuer datensparsame/isolierte Runs.

### A7. Context-Management (offizielle Hinweise)

Verifiziert (Docs):
- Codex Features enthalten Slash-Commands wie `/compact` (Kontext verdichten).
- Prompting-Guide betont:
  - klare Spezifikation
  - explizite Constraints
  - Verifikation / Acceptance-Kriterien
  - iterative Arbeitsweise
- Long-Horizon-Task-Doku betont:
  - Arbeit in Etappen
  - Zwischenstati/Checkpoints
  - Verifikation und Fortschrittskontrolle
  - sauberes Planen bei langen Aufgaben
- Config-Reference enthält `project_doc_max_bytes`, `model_context_window`, `disable_response_storage`, `experimental_resume`.

Relevanz fuer BRIDGE:
- Context-Management ist kein einzelnes Feature, sondern Kombination aus:
  - Session/Resume
  - Kompaktierung (`/compact`)
  - Regel-/Skills-Dateien
  - strukturierter Aufgabenfuehrung
  - begrenzter Projekt-Dokugroesse
  - bewusstem Persistenzverhalten

---

## B) Lokale Codex CLI auf diesem Rechner (Fakten)

### B1. Installation / Version / Paketaufbau

Verifiziert:
- CLI-Pfad: `/home/leo/.nvm/versions/node/v24.11.1/bin/codex`
- Version: `codex-cli 0.104.0`
- Node: `v24.11.1`
- npm: `11.6.2`
- Global installiert als npm-Paket: `@openai/codex@0.104.0`

Paketaufbau (verifiziert):
- npm-Wrapper-Paket `@openai/codex` (Node/ESM) mit `bin/codex.js`
- Plattformspezifisches optionales Paket installiert:
  - `@openai/codex-linux-x64` (`0.104.0-linux-x64`)
- Wrapper startet native Binary aus `vendor/.../codex/codex`

Binary (verifiziert):
- Linux Binary ist `ELF 64-bit ... static-pie linked, stripped`
- `ldd` zeigt `statically linked`

### B2. Lokaler Wrapper (bin/codex.js) - Verhalten

Verifiziert aus lokalem `bin/codex.js`:
- Wrapper erkennt Plattform/Architektur und waehlt passendes Plattformpaket.
- Fallback auf lokales `vendor/` wenn optional dependency fehlt.
- Setzt `PATH` fuer zusaetzliche vendor-Tools.
- Setzt `CODEX_MANAGED_BY_NPM=1` (bzw. `CODEX_MANAGED_BY_BUN=1` bei bun).
- Spawned native Binary asynchron und leitet Signale (`SIGINT`, `SIGTERM`, `SIGHUP`) weiter.

Relevanz fuer BRIDGE:
- tmux-/Supervisor-Signalverhalten ist planbar (Wrapper forwardet sauber).
- Node ist nur Launcher; das eigentliche Verhalten steckt in der nativen Binary.

### B3. Verfuegbare lokale CLI-Kommandos / Features (dieses System)

Verifiziert (lokale Hilfe):
- Kommandos vorhanden: `exec`, `review`, `resume`, `fork`, `mcp`, `mcp-server`, `app-server`, `sandbox`, `features`, `cloud`, `debug`, `apply`
- `sandbox linux` explizit verfuegbar (Landlock+seccomp)
- `mcp add/get/list/login` verfuegbar

Verifiziert (`codex features list`, lokale Installation):
- Aktiv (u. a.):
  - `shell_tool`
  - `unified_exec`
  - `shell_snapshot`
  - `enable_request_compression`
  - `steer`
  - `collaboration_modes`
  - `personality`
- Inaktiv/experimentell (u. a.):
  - `multi_agent` (experimental, false)
  - `apps` (experimental, false)
  - `runtime_metrics` (under development, false)
  - `memory_tool` (under development, false)

Relevanz fuer BRIDGE:
- BRIDGE sollte sich nicht auf lokale experimentelle Codex-Features verlassen (`multi_agent=false`).
- BRIDGE-eigene Multi-Agent-Logik bleibt sinnvoll.

### B4. Lokale Codex-Konfiguration (`~/.codex/config.toml`)

Verifiziert:
- Globalmodell: `model = "gpt-5.3-codex"`
- `model_reasoning_effort = "xhigh"`
- `personality = "pragmatic"`
- Projekt-Trust-Eintraege fuer viele Pfade, u. a.:
  - `/home/leo/Desktop/CC`
  - `/home/leo/Desktop/CC/BRIDGE`
  - `/home/leo/Desktop/CC/Codex`
  - historische BRIDGE-Agent-Workspaces `.agent_sessions/...`
- MCP-Server konfiguriert:
  - `bridge` (stdio -> `python3 .../Backend/bridge_mcp.py`)
  - `ace` (stdio -> Python-Modul mit `ACE_PROJECT_ROOT` env)
- Notice-Eintrag `hide_rate_limit_model_nudge = true`

Relevanz fuer BRIDGE:
- BRIDGE-MCP ist auf diesem Rechner bereits global in Codex registriert.
- Trust fuer BRIDGE-/Codex-Pfade ist vorhanden (hilft gegen Start-Reibung).
- Globale MCP-Konfig kann lokale Agent-Workspaces beeinflussen (Asymmetrie moeglich, wenn BRIDGE lokale `.codex/`/`.mcp.json` erwartet).

### B5. Auth / Version-Dateien (ohne Secrets)

Verifiziert (nur Struktur):
- `~/.codex/auth.json` vorhanden mit Keys:
  - `tokens` (`access_token`, `refresh_token`, `id_token`, `account_id`)
  - `last_refresh`
  - `OPENAI_API_KEY` (in dieser Datei aktuell `null`)
- `~/.codex/version.json` vorhanden (letzter Version-Check + `latest_version`)

Relevanz fuer BRIDGE:
- Lokale Codex-Auth ist persistent.
- Betrieb eines Plattform-Agenten nutzt lokale Benutzer-Identitaet/Token, sofern keine alternative Isolierung genutzt wird.

### B6. Persistenz / Logs / Sitzungen (lokal)

Verifiziert:
- `~/.codex/history.jsonl` vorhanden (groesse im MB-Bereich)
- `~/.codex/sessions/` vorhanden, strukturierte Ablage nach Jahr/Monat/Tag
- `~/.codex/log/codex-tui.log` vorhanden (gross, detailreich)
- `~/.codex/models_cache.json`, `shell_snapshots/`, `tmp/`, `skills/`, `rules/` vorhanden

Momentaufnahme (verifiziert):
- Session-Dateien (`*.jsonl`) insgesamt: `353`
- `history.jsonl` Zeilen: `5478`

Relevanz fuer BRIDGE:
- Codex speichert standardmaessig viel lokale Historie/Session-Daten.
- Fuer sensible BRIDGE-Workflows muss Persistenzstrategie bewusst entschieden werden (`disable_response_storage`, `--ephemeral`, Isolation pro Agent).

### B7. Format der lokalen Session-Dateien (`~/.codex/sessions/...jsonl`)

Verifiziert (Schema-Metadaten, keine Inhalte):
- Event-Zeilen enthalten i. d. R. Keys:
  - `timestamp`
  - `type`
  - `payload`
- Beobachtete Event-Typen (Beispiele):
  - `session_meta`
  - `turn_context`
  - `event_msg`
  - `response_item`
  - `compacted` (selten, aber vorhanden)

Verifiziert im grossen Session-File (Beispiel):
- `turn_context`-Events enthalten u. a.:
  - `approval_policy`
  - `sandbox_policy`
  - `model`
  - `effort`
  - `summary`
  - `truncation_policy`
  - `cwd`
  - `user_instructions`

Relevanz fuer BRIDGE:
- Lokale Session-Dateien tragen kontextrelevante Betriebsmetadaten (Approval/Sandbox/Modell/Truncation/Summary).
- Diese Persistenz kann fuer Debugging extrem wertvoll sein, ist aber auch ein Datenschutz-/Leakage-Thema.

### B8. Lokale Compaction-/Context-Verwaltung (empirisch beobachtet)

Verifiziert (lokale Session-Metadaten):
- In den geprueften letzten 20 Sessions:
  - `turn_context_total = 608`
  - `turn_context.summary` war bei allen vorhanden (`608`)
  - `truncation_policy` einheitlich beobachtet als `{'mode': 'tokens', 'limit': 10000}`
- In einer grossen Session wurden Event-Typen inkl. `turn_context` und `response_item` in hoher Anzahl gesehen.

Verifiziert (lokales TUI-Log):
- Wiederkehrende Token-Usage-Logs mit:
  - `auto_compact_limit=244800`
  - `token_limit_reached=true/false`
- Bei Ueberschreiten des Limits folgt beobachtbar ein starker Rueckgang der Tokenzahl (Hinweis auf Compaction)
- `compact_remote`-Eintraege im Log vorhanden
- `ContextCompacted` / `thread/compacted` Ereignisse im Log vorhanden

Abgeleitet:
- Codex verwaltet Kontext aktiv und fuehrt (mindestens in dieser Installation) automatische Kompaktierung im Lauf durch.
- Context-Management ist sichtbar Teil der Runtime, nicht nur ein manueller `/compact`-Befehl.

### B9. Lokale MCP-Server-Konfiguration (Codex CLI)

Verifiziert (`codex mcp list/get`):
- `bridge`:
  - `enabled: true`
  - `transport: stdio`
  - `command: python3`
  - `args: /home/leo/Desktop/CC/BRIDGE/Backend/bridge_mcp.py`
- `ace`:
  - `enabled: true`
  - `transport: stdio`
  - Command + env konfiguriert
- `Auth: Unsupported` fuer diese stdio-Server (kein OAuth-Flow fuer stdio)

Relevanz fuer BRIDGE:
- BRIDGE-MCP ist lokal korrekt registriert und fuer Codex direkt nutzbar.
- Standard-stdio-Bridge hat keine OAuth-Absicherung auf MCP-Ebene; Sicherheit liegt dann auf lokalem Prozesskontext + Bridge-Server-Seite.

### B10. Aktive Codex-Prozesse (Momentaufnahme)

Verifiziert (Live-Prozesssnapshot):
- Es laufen zwei Codex-Binary-Prozesse (`codex`):
  - einer mit `cwd = /home/leo/Desktop/CC/BRIDGE` (`pts/8`)
  - einer mit `cwd = /home/leo/Desktop/CC/Codex` (`pts/9`)
- `acw_stellexa` tmux-Session zeigt:
  - `cwd = /home/leo/Desktop/CC/Codex`
  - `command = node` (Codex Wrapper)

Relevanz fuer BRIDGE:
- Es existiert aktuell parallel mindestens eine weitere Codex-Instanz ausserhalb der tmux-Stellexa-Session.
- Das ist fuer Identitaet/Tracing/Adressierung in BRIDGE technisch relevant.

---

## C) Context-Management (Fakten fuer Plattformdesign)

### C1. Was offiziell vorhanden ist (Codex-seitig)

Verifiziert:
- Session-Fortsetzung und Abzweigung:
  - `codex resume`
  - `codex fork`
- Manuelle Kontextkompaktierung:
  - Slash-Command `/compact` (Features Docs)
- Konfigurationshebel:
  - `project_doc_max_bytes`
  - `model_context_window`
  - `disable_response_storage`
  - `experimental_resume`
- Strukturierter Kontext ueber:
  - Rules (`AGENTS.md`/`CLAUDE.md`/etc.)
  - Skills (`SKILL.md`)
  - MCP-Server (Tools + ggf. Ressourcen)

### C2. Was lokal empirisch sichtbar ist (diese Installation)

Verifiziert:
- Codex erzeugt `turn_context`-Eintraege mit `summary` und `truncation_policy`
- TUI-Log zeigt automatische Context-/Token-Ueberwachung und Compaction-Ereignisse
- Session-Dateien und Logs sind reichhaltig genug fuer Debugging von Kontextproblemen

### C3. Harte Plattformimplikationen (faktisch ableitbar, ohne Priorisierung)

Faktisch ableitbar:
- "Kontext" in Codex kommt aus mehreren Schichten:
  1. laufende Session/Thread
  2. Projekt-/Regeldateien
  3. Skills
  4. MCP-Tools/Resources
  5. lokale Persistenz (History/Sessions)
- BRIDGE muss fuer reproduzierbares Verhalten entscheiden, welche Schichten pro Agent gelten sollen.
- Ohne klare Persistenz-/Workspace-Strategie entstehen inkonsistente Agentenidentitaeten und unterschiedliches Kontextverhalten.

---

## D) Quellen (offizielle / primaere Quellen)

OpenAI Developers (Codex):
- Overview: https://developers.openai.com/codex/overview
- CLI Features: https://developers.openai.com/codex/cli-features
- Command line options: https://developers.openai.com/codex/command-line-options
- Config basics: https://developers.openai.com/codex/config-basics
- Config advanced: https://developers.openai.com/codex/config-advanced
- Config reference: https://developers.openai.com/codex/config-reference
- AGENTS.md: https://developers.openai.com/codex/agents-md
- MCP guide: https://developers.openai.com/codex/mcp
- Rules: https://developers.openai.com/codex/rules
- Skills: https://developers.openai.com/codex/skills
- Multi-agents: https://developers.openai.com/codex/multi-agents
- Security: https://developers.openai.com/codex/security
- Non-interactive mode: https://developers.openai.com/codex/non-interactive-mode
- Prompting guide: https://developers.openai.com/codex/prompting-guide
- Long horizon tasks: https://developers.openai.com/codex/long-horizon-tasks

OpenAI Help Center:
- Codex CLI with ChatGPT: https://help.openai.com/en/articles/11096431-openai-codex-cli-getting-started

Lokal (diese Installation):
- `~/.nvm/versions/node/v24.11.1/bin/codex`
- `~/.nvm/versions/node/v24.11.1/lib/node_modules/@openai/codex/`
- `~/.codex/config.toml`
- `~/.codex/history.jsonl`
- `~/.codex/sessions/`
- `~/.codex/log/codex-tui.log`

---

## E) Noch offen / nicht belegt (Stand dieses Dokuments)

- Keine finale Aussage in diesem Dokument, wie BRIDGE die Codex-Integration priorisiert umbauen soll (kommt in separater Konsolidierung).
- Keine aktive Modifikation/Validierung neuer Codex-Einstellungen im Live-Betrieb (nur Analyse).

