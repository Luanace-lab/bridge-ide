VERALTET

Diese Audit-Notiz ist nicht mehr die kanonische Referenz. Ihre noch gueltigen Befunde sind in den aktiven Resume-/Projekt-Doku-Satz integriert, insbesondere in:

- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/02_Gap_Map.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W06_Fehlerbilder_Inkonsistenzen_Bruchstellen_Risiken.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W08_Dokumentationslage_Konsistenzpruefung.md`

# BRIDGE Gap Register

## Scope

This note is the running, verified gap register for the working copy in `./BRIDGE`.

It started with the `Buddy (BRIDGE)` slice and now records verified gaps for:

- BRIDGE runtime and control plane
- BRIDGE frontend and clickpaths
- Buddy as the user-facing concierge/frontdoor agent
- reproducibility, packaging, and documentation consistency

This file is intentionally evidence-first.
Only locally verified findings belong here.

## Verified runtime basis

The following checks were executed locally on `2026-03-12`:

- `curl -fsS http://127.0.0.1:9111/status`
- `curl -fsS http://127.0.0.1:9111/runtime`
- `curl -fsS http://127.0.0.1:9111/platform/status`
- `curl -fsS http://127.0.0.1:9111/tasks/summary`
- `curl -fsS http://127.0.0.1:9111/team/orgchart`
- `curl -fsS http://127.0.0.1:9111/whiteboard`
- `curl -fsS http://127.0.0.1:9111/agents/buddy`
- `curl -fsS http://127.0.0.1:9111/agents/buddy/persistence`
- `curl -fsS 'http://127.0.0.1:9111/onboarding/status?user_id=user'`
- `curl -fsS 'http://127.0.0.1:9111/messages?limit=2'`
- `curl -fsS 'http://127.0.0.1:9111/history?limit=2'`
- `curl -fsS 'http://127.0.0.1:9111/logs?name=server&lines=2'`
- `curl -fsS 'http://127.0.0.1:9111/task/queue?limit=2'`
- `curl -fsS 'http://127.0.0.1:9111/agents'`
- `curl -fsS 'http://127.0.0.1:9111/agent/config?project_path=./BRIDGE&engine=claude'`
- `curl -fsS 'http://127.0.0.1:9111/agent/config?project_path=./BRIDGE&engine=codex'`
- `curl -fsS http://127.0.0.1:9111/workflows`
- `curl -fsS http://127.0.0.1:9111/workflows/templates`
- `curl -fsS http://127.0.0.1:9111/workflows/tools`
- `curl -fsS 'http://127.0.0.1:9111/n8n/executions?limit=5'`
- `curl -fsS http://127.0.0.1:9111/n8n/workflows`
- `curl -fsS http://127.0.0.1:9111/automations`
- `curl -fsS -X POST http://127.0.0.1:9111/chat/upload`
- `curl -fsS -X POST http://127.0.0.1:9111/send`
- `curl -fsS -X POST http://127.0.0.1:9111/agents/buddy/start`
- `python3 -c "import importlib.util; print(importlib.util.find_spec('bridge_ide'))"`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/control_center_n8n_degradation.spec.js --reporter=line`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/chat_workflow_buttons.spec.js --reporter=line`
- targeted Playwright browser probes for `landing.html`, `buddy_landing.html`, `task_tracker.html`, `project_config.html`, `control_center.html`, and `chat.html`

## Verified live snapshot

- Server was running on `127.0.0.1:9111`.
- Runtime was configured and active in `codex-claude` mode.
- `tasks/summary` reported `2281` total tasks, `243` done, `2032` failed.
- Buddy was `offline`, `active:false`, `auto_start:false`.
- Buddy persistence was `healthy:true`, `score:"4/4"`, but `registered:false`.
- For user `user`, onboarding returned `known_user:true`, `buddy_running:false`, `should_auto_start:false`.
- During the frontend audit, a concurrent hardening run restarted the live server. After restart, `GET /runtime` reported `configured:false`, `running_count:0`, and `agents_total:0`.

## Gap register

| Severity | Scope | Gap | Verified evidence | Consequence |
| --- | --- | --- | --- | --- |
| critical | BRIDGE | Public read-surface leak for logs, messages, and history | `Backend/server.py` sets `_path_requires_auth_get()` to unconditional public access, see `server.py` around auth handling. The live endpoints `/logs`, `/messages`, and `/history` returned data without any token. | Operational data is readable without authenticated UI or agent context. This weakens the platform security model even while strict auth is enabled for write paths. |
| critical | BRIDGE | Public disclosure of agent guidance via `/agent/config` | `GET /agent/config` returned full `CLAUDE.md` and `AGENTS.md` contents for the project. Code path is visible in `Backend/server.py` where `instruction_content` is read and returned. | The system leaks full prompt and governance content of project agents to unauthenticated callers on the local HTTP surface. |
| high | BRIDGE | Public task queue exposure | `GET /task/queue?limit=2` returned full task records, including lifecycle history and descriptions, without auth. | Task content, ownership, internal reasoning traces, and project backlog details are exposed on the read surface. |
| high | BRIDGE | Public agent inventory exposure | `GET /agents` returned the full agent inventory, including roles, engine, config_dir, model, and active status. | The platform exposes internal topology and runtime metadata broadly on the read surface. |
| critical | BRIDGE | Public raw n8n workflow proxy leaks embedded secret material | `GET /n8n/workflows` returned raw n8n workflow definitions without auth. The payload included workflow node headers and credential-bearing request configuration. `Backend/server.py` proxies `/n8n/workflows` straight through `_n8n_request("GET", "/workflows")`. | Anyone with local HTTP access can read workflow internals plus embedded secret material, which breaks workflow boundary isolation and exposes live integration credentials. |
| high | BRIDGE | Public workflow execution history exposure | `GET /n8n/executions?limit=5` returned recent execution metadata without auth. `Backend/server.py` exposes `/n8n/executions` through the same raw proxy pattern. | Recent workflow activity and cadence are visible without authenticated operator context, weakening observability boundaries. |
| high | BRIDGE | Public automation inventory exposure | `GET /automations` returned full automation records without auth, including actors, trigger schedules, and message payloads. `Backend/server.py` serves `/automations` directly from `automation_engine.get_all_automations()`. | Automation topology, scheduled prompts, and notification content are readable on the local HTTP surface without the control-plane auth model. |
| high | BRIDGE | Public workflow tool registry exposure | `GET /workflows/tools` returned registered workflow tool bindings, including webhook URLs, without auth. `Backend/server.py` returns `_WORKFLOW_TOOLS` directly. | Managed workflow ingress endpoints are exposed to unauthenticated callers, increasing the attack and misuse surface around workflow triggers. |
| high | BRIDGE | Agent detail endpoint misreports `auto_start` | `Backend/server.py` sets `response["auto_start"] = team_agent.get("active", True)` in `GET /agents/{id}`. For `viktor`, `Backend/team.json` stores `active:true` and `auto_start:false`, but live `GET /agents/viktor` returned `auto_start:true`. | The agent detail API overstates startup behavior and weakens trust in the control-plane view of agent lifecycle configuration. |
| high | BRIDGE | Structural concentration in a few oversized active files | `Backend/server.py` has `21927` lines, `Backend/bridge_mcp.py` `11370`, `Frontend/chat.html` `10654`, `Frontend/control_center.html` `10187`. | Core runtime, tool surface, and UI control logic are concentrated in a few files, increasing regression risk and slowing localized verification. |
| high | BRIDGE | Operational task-system debt | `GET /tasks/summary` reported `2281` tasks, with `2032` failed and only `243` done. | The live task system carries a large failure backlog, which weakens trust in task state as an operational signal. |
| high | BRIDGE | Persisted response-state pollution in tasks | `Backend/tasks.json` contains `_claimability` on `2080` persisted tasks. Example: task `87a269ee-412d-4f38-9a00-e3527b2205ef` is stored as `state:"failed"` while `_claimability.reason` is `state=acked`. | Response-only UI or scheduling annotations have contaminated persisted task state, producing contradictory task truth and weakening lifecycle reliability. |
| high | BRIDGE | Documentation layout drift | `docs/README.md` states that working-copy docs are split across root notes, the resume package, `Archiev/docs/`, and `Backend/docs/`. | The canonical documentation home is unclear in the working copy, which increases onboarding friction and weakens reproducibility. |
| high | BRIDGE | Packaging entrypoint mismatch | `pyproject.toml` and `setup.py` declare `bridge_ide.cli:main`, but `python3 -c "import importlib.util; print(importlib.util.find_spec('bridge_ide'))"` returned `None`, and no root `bridge_ide/cli.py` exists in this working copy. | The declared package entrypoint does not match the current tree, so packaging metadata overstates installability of this working copy. |
| high | BRIDGE | Launch checklist overstates documentation completeness | `LAUNCH_CHECKLIST.md` marks `GETTING_STARTED.md`, `ONBOARDING.md`, `SETUP.md`, `API.md`, `ARCHITECTURE.md`, and `team.json.example` as complete at root, but those files are absent in this working copy. | Release-facing status signaling is not aligned with the actual file tree. |
| high | BRIDGE | Hardcoded localhost host/port coupling in active frontends | `Frontend/chat.html`, `Frontend/control_center.html`, `Frontend/project_config.html`, `Frontend/buddy_landing.html`, and `Frontend/buddy_widget.js` all hardcode `127.0.0.1:9111/9112` and restrict token-injection helpers to `127.0.0.1` or `localhost`. | The current UI layer is tightly coupled to one local deployment topology, which blocks straightforward use behind alternate hostnames, ports, or reverse proxies. |
| medium | BRIDGE | Attachment upload auth depends on page-wide fetch interception | `Frontend/chat.html` and `Frontend/control_center.html` call `/chat/upload` via direct `fetch(...)`, while auth is added indirectly by a global `window.fetch = bridgeFetch` override later in each page. The endpoint itself returned `401` when called without token. | Upload auth currently depends on an implicit page-wide fetch monkeypatch instead of explicit request wiring, which makes the clickpath brittle under refactors or alternate embedding contexts. |
| medium | BRIDGE | Inactive schedule automations keep stale `next_run` truth | `GET /automations` returned inactive schedule automations whose `next_run` remained in the past. In `Backend/automation_engine.py`, `set_automation_active()` only flips `active` and writes to disk, while schedule `next_run` is only initialized or advanced elsewhere. | Inactive automation records can still look scheduled, which weakens trust in automation state and complicates operator diagnosis. |
| high | BRIDGE | Hardcoded local machine paths across active team config | `Backend/team.json` binds projects and agents to `./...` and `~/.claude-sub2` paths across many entries, including Buddy, Viktor, Nova, and project roots. | The working copy depends on one machine layout and one user profile, which weakens foreign-machine reproducibility. |
| medium | BRIDGE | Start/stop scripts assume a specific repo placement and name | `Backend/start_platform.sh` and `Backend/stop_platform.sh` derive `ROOT_DIR` by walking up and then reconstruct `.../BRIDGE/Backend`, while also defaulting to `http://127.0.0.1:9111`. | Startup behavior assumes a specific directory topology and local port layout instead of a neutral canonical bootstrap contract. |
| high | BRIDGE frontend | `buddy_landing.html` is broken by CSP before its Buddy boot logic can run | Direct browser probe on `buddy_landing.html?skip_onboarding=1` produced 7 CSP console errors for jsDelivr-hosted `three.js` modules. The page rendered its controls but did not reach its expected start/send requests. | The documented Buddy frontdoor is currently broken at runtime even before auth/write-path issues are considered. |
| medium | BRIDGE frontend | `landing.html` still exposes placeholder product CTAs | Direct browser probe verified working hash navigation, but the docs/github CTAs still resolve to `#`, `#`, and `##readme`. | The public landing surface overstates product completeness and still contains dead-end calls to action. |
| medium | BRIDGE frontend | `task_tracker.html` export uses popup navigation instead of a download contract | Direct browser probe on `Export JSON` opened `/task/tracker?status=failed&format=json` in a popup window rather than producing a browser download event. | Export behavior is functional but inconsistent with a normal download expectation and easy to mis-test or misunderstand. |
| high | BRIDGE frontend | `project_config.html` path UI overpromises arbitrary target paths | Direct browser probe with `project_name=frontend-audit` and `base_dir=/tmp` received `400 {"error":"base_dir outside allowed projects directory"}`. The page visually presents a free path field labeled `Projektpfad` and `Durchsuchen`. | The create flow advertises a wider project-location contract than the backend actually accepts. |
| high | BRIDGE frontend | `chat.html` approval panel close control is blocked by another live layer | Direct browser click on `#panelClose` failed while `<header id="boardHeaderRight">` intercepted pointer events, and the panel remained open. | A visible close affordance is not reliably operable in the live chat layout. |
| medium | BRIDGE frontend | `chat.html` sidebar footer breaks under narrow dragged sidebar widths | Direct browser probe forcing `--sw:88px` measured `overlap:true` between the approval badge and the user-name area. A user screenshot shows the same issue. | The resizable sidebar can enter a visibly broken footer state with overlapping identity chrome. |
| medium | BRIDGE frontend | `control_center.html` conflates total-agent inventory with a green live pulse | The footer metric renders `metricAgents` plus a permanently green `.metric__pulse`, while the actual live count is separately shown in the top bar. A direct pre-restart probe measured `topLabel="4 online"` and `metricAgents="59"` with green pulse styling. | The footer visually implies liveness for the total-agent count and can overstate presence. |
| medium | BRIDGE frontend | Active frontend docs drift from the actual page surface | Browser/page inventory plus routing evidence showed `task_tracker.html` and later `mobile_buddy.html` as additional real surfaces, while `docs/frontend/README.md` had previously documented only `chat.html`, `control_center.html`, `project_config.html`, `buddy_landing.html`, and `i18n.js`. | Documentation understated the active or still-reachable UI surface, which weakens complete clickpath verification planning. |
| high | Buddy | Activation gap | `Backend/team.json` marks Buddy as `active:false` and `auto_start:false`. Live API state confirmed Buddy was `offline`. | Buddy exists as a designed frontdoor agent, but the runtime is currently configured not to come up automatically in the normal path. |
| high | Buddy | Returning-user frontdoor gap | `_get_buddy_frontdoor_status()` derives `should_auto_start` from `not known_user`, and the live onboarding check for `user` returned `known_user:true`, `buddy_running:false`, `should_auto_start:false`. | A returning user can land in a state where Buddy is down, but the frontdoor logic will not restart Buddy automatically. |
| high | Buddy | Dedicated landing page auth mismatch | `Frontend/buddy_landing.html` posts to `/agents/buddy/start` and `/send` without token injection, while the active auth model expects authenticated write access and `buddy_widget.js` explicitly injects `X-Bridge-Token`. Live POSTs to `/send` and `/agents/buddy/start` without token returned `401`. | The dedicated Buddy entry path is less aligned with the live auth model than the embedded widget path. |
| medium | Buddy | UI truth gap around Buddy presence | `Frontend/buddy_landing.html` proceeds into polling even after start failures, and `Frontend/buddy_widget.js` emits a local greeting after `/cli/detect` or a fallback branch. | The UI can make Buddy feel present even when the real Buddy process is offline, weakening CLI-as-SoT truthfulness. |
| high | BRIDGE + Buddy | Product coherence gap | BRIDGE exposes broad orchestration depth through the backend tool and task surface, but the user-facing Buddy path is split across an auth-misaligned landing page, a widget with local simulation behavior, and onboarding logic that does not revive Buddy for known users. | The combined system is stronger internally than its current frontdoor reliably projects. |

## Current judgment

The main weakness is not missing feature surface.
The main weakness is mismatch:

- between strict-looking platform controls and the actually public read surface
- between workflow/automation control surfaces and the fact that raw workflow internals are still publicly readable
- between broad orchestration capability and the reliability of the user-facing frontdoor
- between release/readme/checklist claims and the current working-copy layout
- between the desired CLI-as-SoT model and UI behavior that can simulate agent presence

## Next analysis slices

The next whole-BRIDGE slices to check and extend in this file are:

1. frontend-to-backend clickpath verification for remaining main pages
2. restart, reconnect, and recovery behavior
3. destructive-control coverage on a stable audit runtime
4. documentation vs runtime parity after ongoing hardening
5. task ownership and lease expiry semantics beyond `_claimability` pollution
6. further control-plane contract drift in `/agents/*`, `/team/*`, and runtime overlays
7. workflow creation, trigger, and write-path truth beyond the public read surface
