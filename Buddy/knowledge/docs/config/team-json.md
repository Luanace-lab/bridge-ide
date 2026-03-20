# Config and team.json

## Current files under /config

Present in working copy:

- `config/mcp_catalog.json`
- `config/capability_library.json`
- `config/industry_templates.json`

`team.json` is not in `/config` in the current working copy.

## Canonical team configuration file

The active team configuration is stored at:

- `Backend/team.json`

Evidence from file content:

- `version`, `owner`, `projects`, `teams`, `agents` sections present
- owner and project/team topology are defined there
- frontend views (`/team/orgchart`, `/teams`, `/agents`) consume backend-provided projections of this data

## SoT (source-of-truth) rules used in practice

- Team and agent graph SoT is backend-managed (serialized from backend-side team data)
- Frontend treats API responses as source, not hardcoded static team structures
- Theme preferences are user-local (`localStorage`) and are not team SoT

## Operational caution

Any release process should ensure `Backend/team.json` and runtime overlay behavior remain aligned, otherwise UI (orgchart/team panels) can show stale or partial structures.
