# Gap Analysis vs release docs/frontend/README.md

Baseline compared:

- Release doc: `./docs/frontend/README.md`
- Current implementation: `BRIDGE/Frontend/*`

## Major gaps in release documentation

1. Theme count outdated
- Release doc states 4 themes.
- Current implementation includes 5 themes (`warm`, `light`, `rose`, `dark`, `black`).

2. Missing approval gate documentation
- chat UI has full approval panel/toast/history and decision endpoints.
- Not documented in release frontend README.

3. Missing workflow and automation UI coverage
- Both chat and control center include workflow deploy/toggle/delete and template flows.
- control center includes automation CRUD/run/pause.
- Not documented in release frontend README.

4. Missing team/orgchart/task-board depth
- Current UI has orgchart editing, team panel, task queue board variants, escalation resolution, whiteboard and scope lock views.
- Release doc describes pages only at high level.

5. Missing contract detail
- Release doc has generic fetch examples.
- Current frontend uses a large endpoint surface with concrete payload patterns and auth token handling.

6. Missing buddy onboarding specifics
- Current buddy_landing includes onboarding status checks, polling receive endpoint, and local 3D animation system.
- Release doc only mentions page purpose.

7. Config SoT ambiguity
- Release doc references team config generally, but current repo uses `Backend/team.json` as active source and `/config` for catalogs/templates.

## Recommended doc updates (implemented in this task)

- Add architecture-level frontend doc with module breakdown
- Add explicit frontend-backend contract list
- Add config/team-json SoT note
- Add explicit gap analysis to prevent future drift
