# Frontend Architecture and UI

## Runtime model

The frontend is plain HTML/CSS/JS (no build step, no framework). Main pages:

- `Frontend/chat.html` - chat workspace, settings modal, team panel, approvals, workflow panel
- `Frontend/control_center.html` - dashboard, orgchart, automation/workflow operations
- `Frontend/project_config.html` - project bootstrap and runtime configuration
- `Frontend/buddy_landing.html` - buddy onboarding entry with 3D widget and onboarding flow
- `Frontend/i18n.js` - multi-language dictionary and translation keys

## chat.html architecture

Key module blocks (single-file modular structure):

- Security helpers: `escapeHtml`, `safeFetch` (`chat.html:4206-4222`)
- Settings modal system: tabs for subscriptions/agents/design (`chat.html:4222+`)
- Theme apply and persistence via `bridge_theme` in `localStorage` (`chat.html:4231-4238`)
- Subscription management CRUD (`chat.html:4304-4452`)
- Agent management (mode/model/active/start/restart/subscription) (`chat.html:4600-4666`)
- Chat message send/history/reaction handling (`chat.html:5708-6093`)
- WebSocket client init via `new WebSocket(buildBridgeWsUrl(WS_URL))` (`chat.html:6226`)
- Team/orgchart/task/workflow side-panels (`chat.html:9317+`, `chat.html:9840+`, `chat.html:9941+`)
- Approval gate panel and decision flow (`chat.html:2701+` CSS, `chat.html:9085+` API)

## Event system and live updates

Event model in chat/control center is hybrid:

- Pull-based refresh via `fetch()` for state snapshots (`/history`, `/agents`, `/task/queue`, `/activity`)
- Push-based updates via WebSocket (`WS_URL` + `buildBridgeWsUrl`)
- UI-side escalation and state transitions trigger backend writes (`/send`, `/task/create`, `/approval/respond`)

This design gives resilience when WS reconnects are needed while preserving near-real-time UX.

## Settings system

### Modes and agent management

Settings controls in `chat.html` and `control_center.html` manage:

- agent mode updates (`PATCH /agents/{id}/mode`)
- model changes (`PATCH /agents/{id}`)
- active/start/restart actions (`PATCH /agents/{id}/active`, `POST /agents/{id}/start`, `POST /agents/{id}/restart`)
- subscription assignment (`PUT /agents/{id}/subscription`)

### Theme system

Theme state is applied via `data-theme` on `<html>` and persisted in `localStorage('bridge_theme')`.

Implemented theme set in current frontend:

- `warm`
- `light`
- `rose`
- `dark`
- `black`

Evidence:

- `project_config.html:815-819` theme buttons include `black`
- `control_center.html:3697-3710` theme menu includes `black`
- `chat.html` has separate dark/black panel rules for approval UI (`chat.html:2773-2774`)

## Buddy landing page

`buddy_landing.html` combines onboarding orchestration and animated UI:

- Start buddy agent: `POST /agents/{BUDDY_ID}/start` (`buddy_landing.html:467`)
- Check onboarding status: `GET /onboarding/status` (`buddy_landing.html:490`)
- Send user message to buddy: `POST /send` (`buddy_landing.html:505`)
- Poll receive endpoint for messages (`buddy_landing.html:520`)
- Browser TTS path is explicitly disabled (`buddy_landing.html:395` comment and `speak()` guard)
- 3D animation/particle helpers in the same file (geometry, easing, render loop blocks)

## Dashboard and team panel

`control_center.html` provides operational views:

- Dashboard cards and summaries: tasks, agents, health, costs, activity
- Task board and blocker/escalation handling
- Orgchart and drag/drop parent reassignment (`/agents/{id}/parent`)
- Workflow and automation management panels

Important API-backed panes:

- `/tasks/summary`, `/task/queue`, `/team/projects`, `/health`, `/activity`
- `/whiteboard`, `/scope/locks`, `/metrics/costs`
- `/workflows*`, `/automations*`

Status indicators are rendered from backend state snapshots plus live WS updates.

## CSS and responsive architecture

The frontend pages are self-themed with CSS custom properties defined per page.

Pattern:

- Base variables under `html[data-theme="warm|light|rose"]`
- Combined dark/black selectors with `html:is([data-theme="dark"],[data-theme="black"])`
- Selective split rules where dark and black diverge (e.g. modal backgrounds)

Layout behavior uses media-query breakpoints inline in each page (no external build pipeline).

## i18n

`i18n.js` provides dictionary-driven text for EN/DE/RU/ZH/ES and is consumed via `data-i18n` attributes and `t(key)` lookup helpers.
