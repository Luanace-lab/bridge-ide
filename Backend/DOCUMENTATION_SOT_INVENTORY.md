# Dokumentations-SoT Inventur
Stand: 2026-03-15 16:39 UTC
Task: 9850cd9f (von codex)
Autor: Ordo

---

## 1. Aktive CLAUDE.md (Source of Truth pro Agent/Projekt)

| Pfad | Zweck | Aktiv? |
|------|-------|--------|
| CC/CLAUDE.md | Projekt-Root — verweist auf CC/BRIDGE | JA |
| CC/BRIDGE/CLAUDE.md | Bridge IDE Hauptinstruktionen (Rollen, Regeln, Architektur) | JA — ZENTRALE SoT |
| CC/BRIDGE/.agent_sessions/ordo/CLAUDE.md | Ordo Agent-Instruktionen | JA |
| CC/BRIDGE/.agent_sessions/backend/CLAUDE.md | Backend Agent-Instruktionen | JA (Agent offline) |
| CC/BRIDGE/.agent_sessions/claude/CLAUDE.md | Claude Agent-Instruktionen | JA (Agent offline) |
| CC/BRIDGE/.agent_sessions/claude_probe_live/CLAUDE.md | Test-Agent | TEMPORAER |
| CC/BRIDGE/Frontend_persoenlich/.agent_sessions/frontend/CLAUDE.md | Frontend Agent | JA (Agent offline) |
| CC/Buddy/CLAUDE.md | Buddy Projekt-Root | JA |
| CC/Buddy/.agent_sessions/buddy/CLAUDE.md | Buddy Agent-Instruktionen | JA |
| CC/Viktor/CLAUDE.md | Viktor Projekt-Root | JA |
| CC/Viktor/.agent_sessions/viktor/CLAUDE.md | Viktor Agent-Instruktionen | JA |
| CC/Buddy/kai_context/CLAUDE.md | Kai Agent (Sub-Agent von Buddy) | UNKNOWN — pruefen ob aktiv |
| CC/BRIDGE/BRIDGE/CLAUDE.md | Verschachtelt — DUPLIKAT? | PRUEFEN |
| CC/BRIDGE/BRIDGE/.agents/teamlead/CLAUDE.md | Alter Teamlead — HISTORISCH | ARCHIVIERBAR |
| CC/BRIDGE/.mini_ace/CLAUDE.md | Mini ACE Test | TEMPORAER |
| CC/.agent_sessions/claude/CLAUDE.md | Root-Level Claude — VERALTET? | PRUEFEN |

## 2. Identitaets-Dateien (SOUL.md)

| Pfad | Agent | Aktiv? |
|------|-------|--------|
| CC/BRIDGE/.agent_sessions/ordo/SOUL.md | Ordo | JA |
| CC/Buddy/SOUL.md | Buddy | JA |
| CC/Buddy/kai_context/SOUL.md | Kai | UNKNOWN |
| CC/Viktor/SOUL.md | Viktor | JA |
| CC/BRIDGE/Knowledge/Agents/codex/SOUL.md | Codex | JA |

## 3. Konfigurations-SoT

| Pfad | Was | Einzige Quelle? |
|------|-----|-----------------|
| CC/BRIDGE/Backend/team.json | Agent-Definitionen (58 Agents, Engine, Rollen) | JA — SoT fuer Agents |
| CC/BRIDGE/Backend/config.py | Server-Konfiguration (Ports, Pfade, Timeouts) | JA |
| CC/BRIDGE/Backend/start_platform.sh | Bootstrap-Skript | JA |

## 4. Knowledge-System (Buddy)

| Pfad | Zweck |
|------|-------|
| CC/Buddy/knowledge/KNOWLEDGE_INDEX.md | Index aller Knowledge-Eintraege |
| CC/Buddy/knowledge/SYSTEM_MAP.md | Architektur-Ueberblick |
| CC/Buddy/knowledge/BUDDY_SYSTEM_SOT.md | Buddy-spezifische SoT |
| CC/Buddy/knowledge/docs/ | 7 Unter-Dokumente (Backend, Frontend, Config, etc.) |
| CC/Buddy/BRIDGE_OPERATOR_GUIDE.md | Betriebsanleitung |
| CC/Buddy/GEMINI.md | Gemini-Engine Instruktionen |
| CC/Buddy/QWEN.md | Qwen-Engine Instruktionen |

## 5. Knowledge-System (Bridge/Codex)

| Pfad | Zweck |
|------|-------|
| CC/BRIDGE/Knowledge/Agents/codex/ | Codex GROW, SKILLS, SOUL, PROJECT_MEMORY (15 Projekte) |
| CC/BRIDGE/Knowledge/Projects/ | 15+ Projekt-Dokumentationen |
| CC/BRIDGE/Knowledge/Shared/ | Competitor Analysis (2 Dateien) |
| CC/BRIDGE/Knowledge/Users/ | User-Profile (leo, susi, 4 Test-User) |

## 6. Viktor Slice-Dokumentation

| Pfad | Zweck | Anzahl |
|------|-------|--------|
| CC/Viktor/Slice_00 bis Slice_109 | Server-Refactoring Slices | 109 Dateien |
| CC/Viktor/research/ | Recherche-Ergebnisse | 12 Dateien |
| CC/Viktor/gpt_*.md | GPT-generierte Analysen | 11 Dateien |
| CC/Viktor/Refaktoring_Plan_server_py.md | Hauptplan | 1 |
| CC/Viktor/SPEC_TASKLIST.md | Task-Liste | 1 |

## 7. Heute erstellte Dokumente (Ordo)

| Pfad | Zweck |
|------|-------|
| CC/BRIDGE/Backend/SYSTEM_MESSAGES_AUDIT.md | 57 System-Tags mit Codebeweis |
| CC/BRIDGE/Backend/SYSTEM_MESSAGES_STRATEGY.md | Reduktions-Strategie v2 |
| CC/BRIDGE/Backend/SYSTEM_MESSAGES_IMPLEMENTATION.md | Implementierungsvorlage |
| CC/BRIDGE/Backend/SYSTEM_MESSAGES_FINAL.md | Finaldokument (Routing, Bootstrap, Buddy) |

## 8. Archiv (Archiev/)

| Pfad | Inhalt | Status |
|------|--------|--------|
| CC/BRIDGE/Archiev/.agent_sessions/ | 8 alte Agent-Sessions | ARCHIVIERT — nicht loeschen |
| CC/BRIDGE/Archiev/Agent_Homes_Gebuendelt/ | Gebuendelte alte Agent-Homes + Ordo-Dokumente | ARCHIVIERT |
| CC/BRIDGE/Archiev/Projektleiter_persoenlich/ | Alte Ordo-Dokumente (26 Dateien) | ARCHIVIERT |
| CC/BRIDGE/Archiev/archive/ | Backup pre-Implementation 24.02 | ARCHIVIERT |

---

## 9. Duplikate / Drift

| Problem | Details |
|---------|---------|
| CC/BRIDGE/BRIDGE/CLAUDE.md | Verschachteltes BRIDGE/BRIDGE — Duplikat oder verwaist? Inhalt PRUEFEN |
| CC/.agent_sessions/claude/CLAUDE.md | Root-Level Session — moeglicherweise veraltet |
| Ordo-Dokumente in Archiev/ | AUDIT_TRIAGE.md, CODE_ANALYSIS.md, TEAM_STATUS.md in Archiev — moeglicherweise veraltete Kopien |
| Buddy AGENTS.md doppelt | CC/Buddy/AGENTS.md + CC/Buddy/.agent_sessions/buddy/AGENTS.md |
| Strategy/Planung nur in Archiev | Aktive Versionen von VISION/CONCEPTS/TODO existieren NICHT ausserhalb Archiev — DRIFT |

## 10. Vorschlag: Zentrale Projekt-SoT

```
CC/
├── CLAUDE.md                        ← Projekt-Root (existiert, verweist auf CC/BRIDGE)
├── BRIDGE/
│   ├── CLAUDE.md                    ← Bridge-SoT (existiert — ZENTRAL)
│   ├── Backend/
│   │   ├── team.json                ← Agent-SoT (existiert)
│   │   ├── config.py                ← Server-Config-SoT (existiert)
│   │   └── docs/                    ← NEU: Zentrale technische Doku
│   │       ├── SYSTEM_MESSAGES.md   ← Zusammenfuehrung AUDIT+STRATEGY+FINAL
│   │       ├── ARCHITECTURE.md      ← Server-Architektur (aus Viktor Slices destilliert)
│   │       └── OPERATIONS.md        ← Betriebshandbuch
│   ├── Knowledge/                   ← Knowledge-Vault (existiert)
│   └── .agent_sessions/             ← Agent-Workspaces (existiert)
├── Buddy/
│   ├── CLAUDE.md                    ← Buddy-SoT (existiert)
│   └── knowledge/                   ← Buddy-Knowledge (existiert)
└── Viktor/
    ├── CLAUDE.md                    ← Viktor-SoT (existiert)
    └── Slice_*/                     ← Refactoring-Doku (existiert — 109 Slices)
```

## 11. Archivierbar (erst nach Verifikation)

| Pfad | Begruendung |
|------|-------------|
| CC/BRIDGE/BRIDGE/ | Verschachtelt, wahrscheinlich Artefakt |
| CC/BRIDGE/.mini_ace/ | Test-Artefakt |
| CC/BRIDGE/.tmp_slice08_*/ | Temporaere Slice-Dateien |
| CC/.agent_sessions/ | Root-Level Session — wahrscheinlich veraltet |
| CC/Buddy/kai_context/ | Kai-Agent — Status UNKNOWN, pruefen ob aktiv |
