# Buddy System SoT
Generated: 2026-03-15T17:26:52.900265+00:00

## Zweck

Dieses Dokument ist Buddys zentrale Einstiegskarte in die Bridge.
Es zeigt die autoritativen Quellen und die sichere Lesereihenfolge.

## Pfad-Wahrheit

- Buddy-Home laut Team-Konfiguration: `./Buddy`
- Buddys laufende Session: `./Buddy/.agent_sessions/buddy`
- Wenn in Buddys Instruktionen `knowledge/` steht, ist damit das Buddy-Home gemeint, nicht das Session-Unterverzeichnis.

## Liesereihenfolge fuer Buddy

1. `knowledge/BUDDY_SYSTEM_SOT.md`
2. `knowledge/SYSTEM_MAP.md`
3. `knowledge/KNOWLEDGE_INDEX.md`
4. `BRIDGE_OPERATOR_GUIDE.md`
5. `BRIDGE/Knowledge/Users/<user_id>/USER.md`
6. Live-Zustand nur ueber Bridge-APIs und Bridge-Tools

## Kanonische Quellen fuer Buddy

### User und Persona

- Kanonischer User-Scope: `BRIDGE/Knowledge/Users/<user_id>/USER.md`
- Legacy-Fallback nur falls noetig: `./Buddy/memory/user_model.json`

### Live-Systemzustand

- `/status`
- `/health`
- `/runtime`
- `/agents/{id}`
- `/task/queue`
- `/task/tracker`
- `/history`
- `/receive/{agent_id}`

### Architektur und Runtime

- Backend-Referenz: `BRIDGE/Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`
- Refactor-Leitstand: `BRIDGE/Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/03_Leitstand_9_Punkte_Refaktor.md`
- Projekt-Doku-Master-Index: `BRIDGE/Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/00_MASTER_INDEX.md`

### Produkt- und Plattformdoku

Diese Dokumente sind Mindestanforderung an den Code.
- Persistenz: `./Plattformen/PERSISTENZ_SYSTEM.md`
- MCP-/Capability-Library: `./Plattformen/MCP_LIBRARY_STRATEGIE.md`
- Skill-/MCP-Integration: `./Plattformen/SKILL_MCP_INTEGRATION_KONZEPT.md`
- Creator-Plattform: `./Plattformen/CREATOR_PLATTFORM.md`
- Big-Data-Plattform: `./Plattformen/BIG_DATA_PLATTFORM.md`
- Marketing-Plattform: `./Plattformen/MARKETING_PLATTFORM.md`
- Legal-Plattform: `./Plattformen/LEGAL_PLATTFORM.md`

### Vertiefende Specs unter Backend/docs

- Creator-Spec: `BRIDGE/Backend/docs/CREATOR_PLATFORM_RELIABILITY_SPEC.md`
- Big-Data-Spec: `BRIDGE/Backend/docs/BIG_DATA_ANALYSIS_PLATFORM_SPEC.md`
- Marketplace-/MCP-Analyse: `BRIDGE/Backend/docs/MARKETPLACE_ANALYSIS.md`

### Buddy-nahe Zusatzdoku

- Dokumentenindex: `./Buddy/knowledge/docs/DOCS_INDEX.md`
- Backend-/Infra-Snapshot: `./Buddy/knowledge/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`
- Frontend-Snapshot: `./Buddy/knowledge/docs/frontend/README.md`
- Frontend-Contracts: `./Buddy/knowledge/docs/frontend/contracts.md`

### Frontdoor fuer den User

- Buddy Landing: `BRIDGE/Frontend/buddy_landing.html`
- Hauptchat: `BRIDGE/Frontend/chat.html`
- Operatives Dashboard: `BRIDGE/Frontend/control_center.html`
- Projekt-/Runtime-Setup: `BRIDGE/Frontend/project_config.html`

## Buddy-Arbeitsregel

- Fuer Systemfragen zuerst `SYSTEM_MAP.md` und `KNOWLEDGE_INDEX.md`.
- Fuer Bedienlogik `BRIDGE_OPERATOR_GUIDE.md`.
- Fuer Produktziel und Mindeststandard die Plattformdoku unter `./Plattformen`.
- Fuer aktuelle Wahrheit nur Live-APIs und Bridge-Tools.
- Nicht `.agent_sessions/buddy` mit dem Buddy-Home verwechseln.

## Nicht tun

- Keine Credential-Dateien als Produkt-SoT lesen.
- `memory/user_model.json` nicht als primaere Wahrheit behandeln, wenn ein echter User-Scope existiert.