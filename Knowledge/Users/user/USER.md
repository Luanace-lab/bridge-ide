---
user: user
type: profile
---

# user — User Profile
- **Persona snapshot**: New Bridge IDE visitor who expects a concierge-level front door, wants clarity on the four main entry points (`buddy_landing`, `chat`, `control_center`, `project_config`), and relies on concise SoT guidance before exploring deeper.

- **Onboarding status today (2026-03-15)**:
  - Can list the canonical SoT artifacts (`BUDDY_SYSTEM_SOT.md`, `SYSTEM_MAP.md`, `KNOWLEDGE_INDEX.md`, `BRIDGE_OPERATOR_GUIDE.md`, platform docs).
  - Knows where to find Platform-level docs (`BRIDGE/Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md` and `knowledge/docs/DOCS_INDEX.md`).
  - Needs a procedural playbook that maps the Buddy landing experience to each SoT layer before continuing.

- **Minimum requirements for Buddy to function**:
  1. Visible SoT hierarchy + front door links (`buddy_landing`, `chat`, `control_center`, `project_config`).
  2. Access to `Backend/team.json` and the release `knowledge/docs` stack to verify org chart + config SoT.
  3. A statement that `Users/user/USER.md` will store active persona info and onboarding status for quick reference.

- **Dependencies call-out**:
  - Release-ready assets depend solely on the Buddy home docs listed above plus `Backend/team.json`.
  - Legacy fallback (Buddy memory `memory/user_model.json`) is only for cases when no live `Users/*/USER.md` entries exist.
  - There are no secrets or proprietary files required; everything is available from the documented SoT stack.
