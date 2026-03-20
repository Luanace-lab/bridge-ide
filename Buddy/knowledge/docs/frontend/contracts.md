# Frontend -> Backend Contracts

## Transport and base URLs

- HTTP base (UI pages): `http://127.0.0.1:9111`
- WebSocket base (chat/control): `ws://127.0.0.1:9112`
- Auth injection pattern: frontend appends `BRIDGE_UI_TOKEN` query/header for localhost bridge targets where configured.

## chat.html contract surface

Representative endpoints used by chat UI:

- Subscriptions:
  - `GET /subscriptions`
  - `POST /subscriptions`
  - `PUT /subscriptions/{id}`
  - `DELETE /subscriptions/{id}`
- Agent operations:
  - `GET /agents`, `GET /agents?source=team`
  - `PATCH /agents/{id}`
  - `PATCH /agents/{id}/mode`
  - `PATCH /agents/{id}/active`
  - `POST /agents/{id}/start`
  - `POST /agents/{id}/restart`
  - `PUT /agents/{id}/subscription`
- Messaging and history:
  - `POST /send`
  - `GET /history?since=...&limit=...`
  - `POST /messages/{id}/reaction`
- Tasks and teams:
  - `GET /task/queue`
  - `POST /task/create`
  - `GET /teams`, `GET /teams/{id}`, `POST /teams`
  - `GET /team/orgchart`
- Workflows and approvals:
  - `GET /workflows`, `GET /workflows/templates`
  - `PATCH /workflows/{id}/toggle`, `DELETE /workflows/{id}`
  - `POST /workflows/deploy-template`
  - `GET /approval/pending`
  - `POST /approval/{request_id}/edit`
  - `POST /approval/respond`
- Utilities:
  - `GET /activity`
  - `POST /chat/upload`
  - `GET /pick-directory`

## control_center.html contract surface

Representative endpoints:

- Health/overview:
  - `GET /health`, `GET /status`, `GET /activity`
  - `GET /tasks/summary`, `GET /task/queue`
  - `GET /history?limit=50`
- Project/team board:
  - `GET /team/projects`
  - `GET /board/projects`, `POST /board/projects`
  - `POST /board/projects/{project}/teams/{team}/members`
  - `DELETE /board/projects/{project}/teams/{team}/members/{agent}`
  - `GET /team/orgchart`
  - `POST /agents/{id}/parent`
- Workflows:
  - `GET /workflows`, `GET /workflows/templates`, `GET /workflows/capabilities`
  - `POST /workflows/compile`
  - `POST /workflows/deploy-template`
  - `PATCH /workflows/{id}/toggle`, `DELETE /workflows/{id}`
  - `GET /workflows/{id}/definition`
- Automations:
  - `GET /automations`, `POST /automations`
  - `PATCH /automations/{id}/active`
  - `POST /automations/{id}/run`
  - `PATCH /automations/{id}/pause`
  - `DELETE /automations/{id}`
- Task maintenance:
  - `PATCH /task/{id}`
  - `DELETE /task/{id}`
  - `GET /task/{id}/history`
- Ops signals:
  - `GET /whiteboard`, `GET /scope/locks`, `POST /escalation/{task_id}/resolve`

## project_config.html contract surface

- `GET /engines/models`
- `GET /api/context/scan?project_path=...`
- `POST /api/projects/create`
- `POST /runtime/configure`
- `GET /status`

## buddy_landing.html contract surface

- `POST /agents/{BUDDY_ID}/start`
- `GET /onboarding/status?user_id=...`
- `POST /send`
- `GET /receive/{USER_ID}?wait=0&limit=10`

## Payload patterns

Common payload schema patterns in frontend calls:

- Message payload:
  - `{ from, to, content }`
- Agent activation/start:
  - `{ from: "user" }` for start routes
- Agent patch payload:
  - `{ model }`, `{ mode }`, `{ active }`, `{ subscription_id }`
- Task create payload:
  - `{ title, description, assigned_to, priority, ... }` (assembled in page logic)
- Workflow template deploy:
  - `{ template_id, variables }`
- Approval response:
  - `{ request_id, decision, decided_by: "user" }`

## Source of truth note

Frontend reads operational state from backend APIs; no frontend local cache is treated as canonical across reloads.
