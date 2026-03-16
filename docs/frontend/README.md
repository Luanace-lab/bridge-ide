# Frontend Architecture and UI

## Path note

`docs/frontend/` is the active frontend audit home in the root working copy.
Older archived copies still exist under `Archiev/docs/frontend/`.
This file documents the active frontend paths in `./Frontend`.

## Runtime model

The frontend is plain HTML/CSS/JS without a build step or framework.

Current audit scope:

- Primary product pages:
  - `Frontend/chat.html`
  - `Frontend/control_center.html`
  - `Frontend/project_config.html`
  - `Frontend/buddy_landing.html`
  - `Frontend/task_tracker.html`
- New mobile-root prototype:
  - `Frontend/mobile_buddy.html`
  - `Frontend/mobile_projects.html`
  - `Frontend/mobile_tasks.html`
- Secondary or parallel surfaces still present in the working copy:
  - `Frontend/landing.html`
- Shared support:
  - `Frontend/i18n.js`

Current audit notes in this directory:

- `docs/frontend/contracts.md`
- `docs/frontend/mobile-migration-matrix.md`
- `docs/frontend/mobile-route-audit.md`
- `docs/frontend/clickpath-verification-matrix.md` (veralteter Snapshot; kanonische Befunde stehen jetzt im Resume-/Projekt-Doku-Satz)
- `docs/frontend/design-theme-consistency-audit.md` (veralteter Snapshot; kanonische Befunde stehen jetzt im Resume-/Projekt-Doku-Satz)

## Current page roles

- `chat.html`
  Main user workspace with chat history, direct/team messaging, approval gate, settings modal, subscription management, agent mode/model/start/restart controls, task board, workflow list/template deploy, platform start/stop, N8N execution snapshot, onboarding auto-start, file upload, and multiple local workspace panels.
- `control_center.html`
  Operations console with status/health/activity overview, persistence health cards from `/agents/{id}/persistence`, cost widget, liveboard alerts, scope lock view, team/project board, task board with create/edit/delete/history, org chart drag and drop, agent editor with avatar upload, workflow builder compile/deploy/update, and automation CRUD/run/pause.
- `project_config.html`
  Project bootstrap screen for engine model lookup, context scan, project creation, runtime configuration, JSON export, and runtime status polling. Verifiziert durch Ausfuehrung: the create flow now looks up the allowed Bridge projects base via `GET /projects`, guards out-of-scope targets such as `/tmp` client-side, and still creates valid Desktop-scoped projects successfully.
- `buddy_landing.html`
  Buddy onboarding page with `three.js` animation, CLI detection, engine selection, Buddy-home materialization, explicit buddy start, onboarding status check, send/receive polling chat loop, disabled browser TTS, and draggable side panel persisted in `localStorage`. The live page now calls `GET /cli/detect?skip_runtime=1` as a fast frontdoor scan backed by a short server-side cache/single-flight guard, uses `POST /agents/buddy/setup-home` to materialize `BRIDGE_OPERATOR_GUIDE.md` plus engine-specific wrapper files, and only then starts Buddy. Verifiziert durch Ausfuehrung: with multiple detected CLIs the visible landing path prompts for the engine choice when no reusable Buddy engine exists; if Buddy already has a still-available engine, the page reuses that existing profile directly before start. A programmatic early-bootstrap path still falls back deterministically to `existingEngine || recommended || available[0]`.
- `mobile_buddy.html`
  Mobile-root prototype for Buddy. The current surface is Buddy-first but no longer single-pane: the main area is now a stacked `Management-Board` over `Team-Board`, derived from `chat.html` instead of a custom mobile chat shell. The condensed overview moved into the modal drawer and is fed from `/tasks/summary`, `/team/projects`, `/projects`, `/task/tracker`, and degraded `/workflows`. The visible top header is now reduced to the canonical `ace_logo.svg` only; the title/status copy was removed from the surface so the chat stack can start directly underneath, while runtime state remains available in the drawer/settings path. The live boards use `/agents/buddy/start`, `/send`, `/history`, `/board/projects`, and `/team/orgchart`; the top board stays Buddy-centric, while the lower board condenses a selected team and sends to its current lead. Both mobile composers now expose real attachment upload via the existing `/chat/upload` plus `meta.attachments` path from `chat.html`: each board has its own `+` button, hidden file input, inline preview, and attachment rendering inside the board feed after send. The lower board header is now further cleaned up for mobile width: the active team is shown directly inside the `Teams` picker, the separate summary pill is no longer part of the visible surface, the `Agenten` disclosure collapses to a compact count chip, and the board-focus toggle remains an icon-only control on the same row. The drawer itself is no longer treated like a mini desktop surface: it is now a single-column mobile overview with shorter copy, no horizontal overflow, tighter cards, and the same `warm` theme logic as the browser app. The board split is now no longer static: users can drag the divider between both boards to rebalance the visible area, or collapse one board entirely via a 48px header action button so the other board takes the full surface until restored. The outer shell was also visually tightened for mobile use: less frame waste, stronger management-board weight, card-like empty states instead of blank white voids, and the Buddy FAB starts deeper on the surface so it does not block the top board header by default. In `warm`, the shell and board chrome now follow `chat.html` exactly: `--bg:#fbf8f1`, board shell `#fdfcfa`, and white chat surfaces with the same light ridge/border/shadow stack used by the browser chat bubbles. The page also embeds the same Buddy widget used by `chat.html` via `buddy_widget.js`, but in a mobile-specific surface mode: the movable Buddy icon is mounted inside `#shell`, starts lower on the surface, toggles a compact `Sprechblase`, and locally suppresses the connector-tail so the bubble reads as a clean mobile overlay rather than a desktop callout. The page reuses the canonical BRIDGE browser themes (`warm`, `light`, `rose`, `dark`, `black`) and the shared `bridge_theme` localStorage key. Dedicated verification now covers two routed follow-up screens: `Projektstart` / Drawer `Neues Projekt` land on `mobile_projects.html`, and `Tasks -> Tracker`, Drawer `Task Tracker`, plus Drawer `Aufgaben` land on `mobile_tasks.html`. The broad `mobile_buddy_route_audit.spec.js` remains partially blocked by the known Buddy-widget route test and therefore is not yet the canonical evidence for every route target; see `docs/frontend/mobile-route-audit.md`.
- `mobile_projects.html`
  First mobile-native follow-up screen replacing the `Neues Projekt` / `Projektstart` exits from `mobile_buddy.html`. The page keeps the desktop backend SoT intact and reuses the same endpoints as `project_config.html`: `GET /projects`, `GET /engines/models`, `GET /api/context/scan`, `POST /api/projects/create`, `POST /runtime/configure`, and `GET /status`. The surface now also reuses the same warm mobile shell language as `mobile_buddy.html`: logo-only header, the same `#shell`, Buddy FAB mounted via `buddy_widget.js`, and an edge-to-edge compact viewport on narrow screens instead of a separate hero layout. The first screen was further compressed into a mobile-native status block with a 2x2 metric grid so the project form becomes visible immediately on phone-sized viewports. Functionally it stays mobile-first instead of a shrunken desktop wizard: recent-project quick picks, compact scan feedback, collapsible role cards for leader and agents, plus export and runtime-start actions in a footer action row. The page reads and applies the canonical `bridge_theme` value, injects the same `X-Bridge-Token` Bridge auth header logic as the desktop pages, and leaves `project_config.html` untouched.
- `mobile_tasks.html`
  Mobile-native replacement for the task-tracking exits from `mobile_buddy.html`. The page keeps the desktop task backend SoT intact and reuses the same tracker/export chain as `task_tracker.html`: `GET /task/tracker`, fallback `GET /task/queue`, and export via `format=csv|json` on the currently active endpoint. The surface follows the same Buddy shell language as `mobile_buddy.html` and `mobile_projects.html`: logo-only header, edge-to-edge `#shell`, Buddy FAB via `buddy_widget.js`, a compact top status board, mobile filters, card-based task list, and a bottom detail sheet instead of the desktop right sidebar. It preserves filter, fallback, export, auto-refresh, detail, and theme/token behavior without changing `task_tracker.html`.
- `task_tracker.html`
  Dedicated task listing view with server-side filtering, authenticated JSON/CSV export via blob download, and a right-side detail panel.
- `landing.html`
  Marketing-style landing page with anchor navigation and placeholder docs/github calls to action. This is not the active `/` entrypoint in the current server wiring.
- `i18n.js`
  Dictionary for `en`, `de`, `ru`, `zh`, `es`. In the current codebase it is loaded by `chat.html` only.

## Live update model

- `chat.html` and `control_center.html` use hybrid state sync: REST snapshot fetches plus WebSocket updates on `ws://127.0.0.1:9112`.
- `project_config.html`, `mobile_projects.html`, `mobile_tasks.html`, and `buddy_landing.html` are fetch/poll driven only.
- `chat.html`, `control_center.html`, `project_config.html`, `mobile_projects.html`, `mobile_tasks.html`, and `buddy_landing.html` inject `X-Bridge-Token` from `window.__BRIDGE_UI_TOKEN` for resolved Bridge HTTP requests.
- `buddy_landing.html` is now also the active setup/frontdoor path for Buddy runtime selection:
  - `GET /cli/detect?skip_runtime=1`
  - `POST /agents/buddy/setup-home`
  - `POST /agents/buddy/start`
- `buddy_widget.js` reads the same fast `/cli/detect?skip_runtime=1` endpoint only as a shallow greeting hint; the canonical setup/materialization path lives in `buddy_landing.html`.
- `chat.html` and `control_center.html` also append the same token to WebSocket URLs when present.

## Local UI state

Representative persisted state in the current implementation:

- `bridge_theme`
- `bridge_language`
- `bridge_agentPanel`
- team-board collapse state
- sidebar favorites
- workspace panel layout/state
- sidebar/feed heights
- `bridge_user_id`
- `bridge_welcome_seen`
- `buddy_panel_pos`

No local frontend cache is treated as canonical operational state across reloads.

## Aktuelle Browser-Evidenz

Verifiziert durch Ausführung:
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/frontend_clickpath_audit.spec.js --reporter=line`
  - Ergebnis: `5 passed`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/mobile_buddy_route_audit.spec.js --reporter=line`
  - Ergebnis: `1 passed`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/mobile_buddy_board_controls.spec.js --reporter=line`
  - Ergebnis: `1 passed`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/mobile_projects.spec.js --reporter=line`
  - Ergebnis: `1 passed`
