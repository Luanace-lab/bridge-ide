# Knowledge Index — Nachschlagewerk
Generated: 2026-03-15T17:26:52.875827+00:00

Dieses Dokument zeigt dir WO du Informationen findest.
Fuer Live-Daten (Agent-Status, Tasks) nutze die Bridge-Tools direkt.

## Agent-Memories

Jeder Claude-Agent hat ein persistentes Memory:
- Pattern: `~/.claude-agent-{AGENT_ID}/projects/*/memory/MEMORY.md`
- Zugriff: Datei direkt lesen (Read-Tool) oder `bridge_memory_search`

Agents mit Memory-Verzeichnis (40):
- alpha_lead, aria, assi, atlas, backend, bravo_lead, buddy, charlie_lead, claude, codex, finn, frontend, jura, kai, legal_compliance, legal_contract, legal_researcher, marketing_campaign, marketing_content, marketing_seo, mika, mira, mobile, nexus, nova, ordo, ordo.lock, scale_lab_alpha, scale_lab_beta, sec_all, sec_cookie, sec_dns, sec_evasion, sec_fingerprint, sec_tor, sec_webrtc, trading_analyst, trading_risk, trading_strategist, viktor

## Knowledge Vault (Shared)
- Pfad: `BRIDGE/Knowledge`
- Zugriff: `bridge_knowledge_read(path)`, `bridge_knowledge_search(query)`
- Struktur:
  - `Agents/` (1 Eintraege)
  - `Archiev/` (0 Eintraege)
  - `Decisions/` (0 Eintraege)
  - `Projects/` (17 Eintraege)
  - `Shared/` (2 Eintraege)
  - `Tasks/` (0 Eintraege)
  - `Teams/` (0 Eintraege)
  - `Users/` (7 Eintraege)

## Daily Logs
- Pattern: `BRIDGE/Knowledge/Agents/{agent_id}/DAILY/YYYY-MM-DD.md`
- Zugriff: `bridge_knowledge_read("Agents/{agent_id}/DAILY/YYYY-MM-DD.md")`
- Aktuell keine Daily Logs vorhanden

## Credentials & Accounts
- Zugriff: `bridge_credential_list(service)` — zeigt Metadaten
- Secrets: `bridge_credential_get(service, key)` — gibt verschluesselten Wert
- Speicher: `~/.config/bridge/` (verschluesselt, NICHT direkt lesen)

## Semantic Memory
- Zugriff: `bridge_memory_search(query, scope)`
- Speicher: `~/.config/bridge/memory/`
- Hybrid-Retrieval: Embeddings + BM25 (semantic_memory.py)

## Live-Daten (on-demand via Bridge-Tools)
- Agent-Status: `bridge_health` oder Dashboard
- Nachrichten: `bridge_receive()`, `bridge_history(limit=N)`
- Tasks: `bridge_task_queue(state='created')`, `bridge_task_get(task_id)`
- Aktivitaeten: `bridge_check_activity(agent_id)`

## Speicherorte (Uebersicht)
- Knowledge Vault: `BRIDGE/Knowledge`
- Agent State: `BRIDGE/Backend/agent_state`
- Message Log: `BRIDGE/Backend/messages/bridge.jsonl`
- Credential Store: `~/.config/bridge/` (verschluesselt)
- Semantic Memory: `~/.config/bridge/memory/`
- Media Workspace: `/tmp/bridge_creator_workspace/`

## Retrieval-Pfad (Reihenfolge)
1. `knowledge/` Dateien lesen (KNOWLEDGE_INDEX.md, SYSTEM_MAP.md)
2. `bridge_memory_search(query, scope)` — semantische Suche
3. `bridge_knowledge_search(query)` — Fulltext/Regex im Knowledge Vault
4. `bridge_credential_list(service)` — Credential-Metadaten

## Tooling-Familien
- Browser: `bridge_browser_*`, `bridge_stealth_*`
- Knowledge: `bridge_knowledge_*`
- Memory: `bridge_memory_*`
- Credentials: `bridge_credential_*`
- Tasks: `bridge_task_*`
- Email: `bridge_email_*`
- Slack: `bridge_slack_*`
- Telegram: `bridge_telegram_*`
- WhatsApp: `bridge_whatsapp_*`
- Creator: `bridge_creator_*`
- Desktop: `bridge_desktop_*`
- Voice: `bridge_voice_*`
- Capabilities: `bridge_capability_library_*`