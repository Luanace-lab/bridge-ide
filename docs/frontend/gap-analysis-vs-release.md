# Gap Analysis vs current frontend docs

## Scope

This note compares the active frontend code in `/home/user/bridge/BRIDGE/Frontend/*`
with the documentation state that existed before this audit.

## Verified documentation drift

1. Root path drift
- `docs/frontend/` was empty in the current working copy.
- The only pre-existing detailed frontend docs were archived copies under `Archiev/docs/frontend/`.

2. chat.html coverage was too shallow
- Older docs mentioned chat, approvals, teams, and workflows at a high level.
- The active file also contains platform start/stop, board project loading, N8N execution polling, onboarding auto-start, workflow suggestions, file upload, and local multi-panel workspace state.

3. control_center.html contract details were incomplete
- The active page reads persistence health via `GET /agents/{id}/persistence`.
- It uses `PATCH /agents/{id}/parent`, not `POST`.
- It supports task creation plus attachments, liveboard alert views, avatar upload, workflow builder deploy/update paths, automation pause/run flows, and a persisted welcome overlay.

4. i18n scope was overstated implicitly
- `i18n.js` exists and provides 5 languages.
- In the active frontend it is loaded by `chat.html` only; `control_center.html`, `project_config.html`, and `buddy_landing.html` do not load it.

5. Auth/token handling was under-documented
- `chat.html`, `control_center.html`, and `project_config.html` wrap `window.fetch` to inject `X-Bridge-Token`.
- `chat.html` and `control_center.html` also append the token to WebSocket URLs.

6. buddy/onboarding behavior was split across pages
- `buddy_landing.html` has the dedicated buddy start/status/send/receive loop.
- `chat.html` also checks `/onboarding/status` and can trigger `POST /onboarding/start`.

## Result of this audit

- `docs/frontend/README.md` now documents the active page roles.
- `docs/frontend/contracts.md` now reflects the current endpoint surface and corrected HTTP methods.
- This file records the path drift and the main code-vs-doc gaps that were verified during the audit.
