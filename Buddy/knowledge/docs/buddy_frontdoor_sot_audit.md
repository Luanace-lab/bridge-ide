# Buddy Frontdoor & SoT Audit
*Stand: 2026-03-15 — Task "Buddy Frontdoor und SoT fuer User-Onboarding auditieren"*

## 1. SoT hierarchy for Buddy / Bridge IDE

| Layer | Canonical source | Purpose / How Buddy uses it |
| --- | --- | --- |
| System SoT summary | `./Buddy/knowledge/BUDDY_SYSTEM_SOT.md` | Top-level statement of the truths Buddy relies on (SoT inventory, front door links, archival rules). |
| System Map | `./Buddy/knowledge/SYSTEM_MAP.md` | Live map of agents, engines, knowledge vault, and runtime endpoints; use first when explaining “how the Bridge functions.” |
| Knowledge Index | `./Buddy/knowledge/KNOWLEDGE_INDEX.md` | Entry-point to agent memory, knowledge vault, credentials, and tooling; referenced as “How do I find information?” |
| Operator guide | `./Buddy/BRIDGE_OPERATOR_GUIDE.md` | Procedure guide for Buddy: canonical project docs, front door list, user scope access, and the “do not” list. |
| Platform docs / backend refs | `./Bridge/Backend/docs/...` (e.g., `BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`) | Technical backups for runtime, persistence, and MCP architecture; surfaced when deeper architectural proof is required. |
| Buddy’s doc index | `./Buddy/knowledge/docs/DOCS_INDEX.md` | Quick pointer to the frontend/back-end docs and config SoT when comparing current workspace to release. |
| Config notes (team.json SoT) | `./Buddy/knowledge/docs/config/team-json.md` | Defines that `Backend/team.json` is the authoritative team graph; cite it under “so the org chart is canonical.” |
| User scope | `BRIDGE/Knowledge/Users/user/USER.md` | The canonical user profile; currently contains only “# user — User Profile,” so it is a placeholder that needs enrichment. |
| Legacy fallback | `./Buddy/memory/user_model.json` | Mentioned in `BUDDY_SYSTEM_SOT.md` as fallback only when the live user scope is empty. |

> Evidence: The canonical SoT is documented in `BUDDY_SYSTEM_SOT.md` (lines 1‑100) and the operator guide (lines 5‑25). Buddy should always present this hierarchy before claiming “I know the SoT.”

## 2. Buddy Frontdoor Playbook

1. **Welcome & System Orientation**
   - Open `BUDDY_SYSTEM_SOT.md` for “what you need to know” and point to the System Map + Knowledge Index for live reality checks.
   - Reference the Operator Guide to explain that the CLI, backend, and config invoices are the operative SoT.
2. **Link the four front door endpoints** (per `BUDDY_SYSTEM_SOT.md`, section “Frontdoor fuer den User”):
   - `buddy_landing.html`: home for onboarding status, SoT checklist, and special polling (documented by the front‑end gap analysis note).
   - `chat.html`: the primary messenger; mention it as the place to verify new messages and instructions (bridge_receive).
   - `control_center.html`: the operations dashboard; tie it to the operator guide’s “Flow for automation, tasks, and approvals.”
   - `project_config.html`: runtime/project setup; point out it links to actual configuration files (`Backend/team.json`, `config/*.json` per `team-json.md`).
3. **Show the documentation stack**
   - Present the `knowledge/docs` folder (DOCS_INDEX) as the single entry point.
   - Highlight the front-end gap analysis doc `frontend/gap-analysis-vs-release.md` to prove we already track missing buddy onboarding coverage.
4. **Reinforce verification steps**
   - Always validate that `Backend/team.json` is current (per config SoT note) before giving org chart guidance.
   - Use the `Users/user/USER.md` profile after it is expanded; for now, note that it exists but is a stub, so the user must rely on the folder of canonical docs.

## 3. Onboarding gaps discovered during the audit

1. **User scope is empty.** 
   - `BRIDGE/Knowledge/Users/user/USER.md` has only a single heading (`# user — User Profile`), which is insufficient for personalized onboarding. There is no data about the user’s recent activity, preferences, or assigned projects.
2. **No consolidated front door playbook.**
   - The front door endpoints are listed in `BUDDY_SYSTEM_SOT.md` but there is no single artifact that translates them into “this is what I walk a user through.” Without it, Buddy must piece together the script from multiple docs (SoT summary, operator guide, gap analysis).
3. **Buddy onboarding specifics are still missing in release docs.**
   - `knowledge/docs/frontend/gap-analysis-vs-release.md` explicitly states (item 6) “Missing buddy onboarding specifics” as a major gap, confirming that the public docs still lack the detail users need when they land on `buddy_landing.html`.
4. **Lack of interactive SoT narrative for new users.**
   - None of the current docs describe “when a new user logs in, these exact paths are checked.” All content is descriptive, not procedural. A simple playbook referencing the SoT stack would close this gap.

## 4. Next steps (proposed)

- Expand `Users/user/USER.md` with persona context (SoT references, onboarding status, front door checklist). 
- Create a dedicated “Buddy frontdoor playbook” inside `knowledge/docs/` that maps the four entry pages to the SoT references listed above (reuse this audit as the draft).
- Surface the gap-analysis item (missing buddy onboarding specifics) to the operations team by linking to it from the new playbook so it stays visible.
- Use `Backend/team.json` and the live APIs (per System Map notes) for every subsequent user question; treat this audit as the canonical pointer list.
