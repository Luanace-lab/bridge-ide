# Sub-Agent Read-Only Runs (Dokumentation)

Stand: 2026-02-24  
Ort: `/home/user/bridge/BRIDGE`

## Zweck

Dokumentiert die gestarteten Read-Only Sub-Agents (A/B), ihre Vorgaben, die gesicherten Artefakte und den Abschlussstatus.

## Rahmenbedingungen (verifiziert)

- Beide Sub-Agents wurden als `codex exec` gestartet.
- Sandbox-Modus: `read-only`
- Approval-Policy: `never`
- Arbeitsverzeichnis: `/home/user/bridge/BRIDGE`
- Ziel: Pflichtdokumente lesen, danach gesamten Code lesen, optimierten Bericht erzeugen
- Schreibrechte im Projekt sollten nicht genutzt werden (nur Lesen)

## Startkommandos (verifiziert)

Beide Sub-Agents wurden mit diesem Muster gestartet:

- `codex -a never exec -s read-only -C /home/user/bridge/BRIDGE --skip-git-repo-check -o /tmp/subagent_<x>_report.txt -`

Hinweis:
- Die Prompts wurden per stdin-Datei zugeführt (`< /tmp/subagent_<x>_prompt.txt`)
- stdout/stderr wurden in `/tmp/subagent_<x>_stdout.txt` umgeleitet

## Pflichtvorgaben fuer beide Sub-Agents (verifiziert)

Beide mussten zuerst lesen:
- `STELLEXA_CLAUDE_VERGLEICH_VERIFIZIERUNG_2026-02-24.md`
- `CODEX_CLI_TECHNIK_UND_CONTEXT_FAKTEN_2026-02-24.md`

Danach:
- gesamten Code in `/home/user/bridge/BRIDGE` systematisch lesen
- keine Aenderungen ausfuehren
- Bericht mit Belegen liefern

## Abschlussstatus der Runs

Status:
- Beide Runs wurden **kontrolliert per `Ctrl-C`** beendet, nachdem umfangreiche Read-Only-Analysen und Code-Lektuere sichtbar dokumentiert waren.
- Grund: sehr lange laufende Analyse-Loops; fuer Dokumentation/Patch-Plan wurde ein stabiler Snapshot benoetigt.

Beobachtet:
- `subagent_a_report.txt` wurde bis zum Interrupt nicht erzeugt.
- `subagent_b_report.txt` wurde bis zum Interrupt nicht erzeugt.
- Stattdessen liegen umfangreiche Transkripte mit Befunden, Kommandos und Zwischenanalysen vor.

## Gesicherte Artefakte in /BRIDGE (verifiziert)

- `SUBAGENT_A_READONLY_PROMPT_2026-02-24.txt`
- `SUBAGENT_A_READONLY_TRANSKRIPT_2026-02-24.txt`
- `SUBAGENT_B_READONLY_PROMPT_2026-02-24.txt`
- `SUBAGENT_B_READONLY_TRANSKRIPT_2026-02-24.txt`

## Beobachtete Run-Enden (verifiziert)

Transkript-Ausschnitte am Ende:
- `task interrupted`
- `tokens used`

Beobachtete Token-Nutzung beim Interrupt:
- Sub-Agent A: `226,848`
- Sub-Agent B: `239,091`

## Nutzen der gesicherten Transkripte

Die Transkripte enthalten bereits verifizierte Zusatzbefunde, u. a.:
- weitere Quantifizierung des `bridge_watcher`-Logs
- Message-Log-Statistiken (`Backend/messages/bridge.jsonl`) fuer `codex` vs `stellexa`
- Frontend-/API-Endpunkt-Mismatch-Belege (`9111` vs `9222`)
- Live-tmux-/Prozesssnapshots
- Diffs aktive Dateien vs `Backup_P2_Start`
- Hinweise auf Testabdeckungsluecken (z. B. Adapterpfade)

Diese Snapshot-Artefakte wurden als Grundlage fuer den nachfolgenden Patch-Plan verwendet.

