VERALTET

Diese Audit-Notiz ist nicht mehr die kanonische Referenz. Ihre noch gueltigen Befunde sind in den aktiven Resume-/Projekt-Doku-Satz integriert, insbesondere in:

- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W02_UI_Struktur_Interaktionslogik_und_Zustaende.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/02_Gap_Map.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W08_Dokumentationslage_Konsistenzpruefung.md`

# Frontend Clickpath Verification Matrix

## Scope

This note records the frontend pages that were actually exercised in a real browser on `2026-03-12`.
It complements the broad gap register with page-level clickpath evidence.

The initial manual audit happened on a changing live system, but the page-level verification in this note is now anchored by a stable automated rerun:

- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/frontend_clickpath_audit.spec.js --reporter=line`
  - Ergebnis: `5 passed`
- `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/bridge_runtime_urls.spec.js --reporter=line`
  - Ergebnis: `3 passed`
  - belegte reale Browserpfade fuer `127.0.0.1`, `localhost` und denselben Host hinter Reverse Proxy

## Page classification

Based on server routing, local docs, and active navigation wiring:

- Primary product pages:
  - `mobile_buddy.html`
  - `mobile_projects.html`
  - `mobile_tasks.html`
  - `control_center.html`
  - `chat.html`
  - `project_config.html`
  - `buddy_landing.html`
  - `task_tracker.html`
- Secondary or parallel pages still present:
  - `landing.html`
- Excluded from this matrix:
  - `buddy_design*.html`
  - `mockup_reply.html`
  - `buddy_onboarding*_backup.html`
  - older Buddy onboarding variants not linked from the active docs or main product routes

## Inventory snapshot

Visible controls were inventoried with a headless Playwright pass on the live pages.

| Page | Visible buttons | Total buttons | Visible selects | Total selects | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| `landing.html` | 0 | 0 | 0 | 0 | Link-only marketing surface |
| `mobile_buddy.html` | 5 | 55 | 0 | 0 | Mobile root with logo-triggered drawer, floating Buddy widget, settings sheet, and stacked Management/Team boards |
| `mobile_projects.html` | 24 | 58 | 5 | 17 | Mobile-native project bootstrap surface with native selects, quick picks, and collapsible leader/agent cards |
| `buddy_landing.html` | 3 | 3 | 0 | 0 | Initial static controls are `mic-btn`, `send-btn`, `vol-btn`; runtime-generated engine-choice buttons appear after CLI detection when multiple CLIs are available |
| `task_tracker.html` | 4 | 9 | 2 | 2 | Theme, filter, both exports, two native filters |
| `project_config.html` | 16 | 85 | 2 | 17 | Many button-backed disclosure controls plus two visible selects |
| `control_center.html` | 16 | 2744 | 0 | 22 | Very large hidden DOM/control surface on the default tab |
| `chat.html` | 122 | 149 | 2 | 2 | Extremely dense visible control surface |

## Verified clickpaths

| Page | Executed clickpath | Result | Evidence |
| --- | --- | --- | --- |
| `landing.html` | Anchor navigation via `Features` and `Get Started` | Works | Browser run changed the hash to `#get-started`; docs/github CTA hrefs were still placeholders: `#`, `#`, and `##readme` |
| `mobile_buddy.html` | Page load, stacked `Management-Board`/`Team-Board` visible, visible header reduced to logo-only, drawer-hosted overview visible after logo open, drawer remains single-column without horizontal overflow, prompt chip fills the management composer, grouped BRIDGE links visible, Buddy icon stays inside `#shell`, compact Buddy-`Sprechblase` opens and closes, widget send renders the user bubble, widget connector-tail stays suppressed on Mobile, both board composers expose visible `+` upload buttons, attachment preview works, attachment-only send works in both boards, settings sheet open, canonical browser theme persists via `bridge_theme`, lower `Team-Board` header is collapsed by default and expands `Teams` plus `Agenten` on demand, warm board shell/chat surfaces match `chat.html`, shell density and FAB placement remain mobile-usable after the design polish | Works | `Frontend/mobile_buddy.spec.js` now verifies the logo-only visible header, both stacked boards, footer-note removal, logo-triggered drawer toggle, single-column overflow-free drawer layout, overview cards, prompt-to-management-composer flow, destination links, Buddy icon placement inside `#shell`, lower default icon position, compact Buddy-bubble bounds, suppressed `::after` connector-tail, visible upload buttons in both composers, attachment preview plus attachment-send rendering in both board feeds, collapsed `Teams`/`Agenten` disclosures, the local settings sheet, and the canonical `black` theme written to `localStorage.bridge_theme`; a headless rerun on `2026-03-13` additionally proved that the summary cards no longer share the same top coordinate and therefore no longer render as a two-column drawer grid on the tested mobile viewport |
| `mobile_buddy.html` | Drag the board divider, collapse Management for Team focus, restore split, collapse Team for Management focus, restore split | Works | `Frontend/mobile_buddy_board_controls.spec.js` now verifies the draggable vertical split, 48px board toggle touch targets, `team-focus`, `management-focus`, and keyboard resize on the divider; additional headless screenshots captured the neutral split at `/tmp/mobile_buddy_split_default.png`, management-only focus at `/tmp/mobile_buddy_management_focus.png`, and team-only focus at `/tmp/mobile_buddy_team_focus.png` |
| `mobile_buddy.html` | Vollstaendiger Mobile-Route-Audit der In-Page-Aktionen sowie aller aktiven Summary-/Drawer-Exits | Teilweise | `Frontend/mobile_buddy_route_audit.spec.js` bleibt real am bekannten Buddy-Widget-Pfad blockiert (`widget.send`); deshalb ist der breite Audit nicht die alleinige Routen-Evidenz. Separat verifiziert sind aber bereits die mobilen Exits nach `mobile_projects.html` und `mobile_tasks.html` ueber deren dedizierte Specs. Offen bleiben weiterhin nicht-mobile Exits nach `chat.html`, `control_center.html`, `control_center.html?tab=hierarchie` und `control_center.html?tab=workflows`; zusaetzlich blieb `management.send` ohne belastbaren `/send`-Response und ist als aktiver Mobile-Blocker zu behandeln |
| `mobile_projects.html` | Mobile-Projektanlage: no-overflow load, Quick-Picks aus `/projects`, echter Scan, Export, Runtime-Start, Agent-hinzufuegen, echte Projektanlage, Rueckweg aus `mobile_buddy.html` | Works | `Frontend/mobile_projects.spec.js` lief real unter `430x932`; der Lauf verifizierte `GET /projects`, `GET /api/context/scan`, `POST /runtime/configure`, Download-Export, neues Agent-Card-Append, `POST /api/projects/create` sowie die Navigation von Drawer `Neues Projekt` nach `mobile_projects.html` |
| `mobile_tasks.html` | Mobile-Tasktracking: no-overflow load, Tracker/Fallback, Filter, Detail-Sheet, CSV/JSON-Export, Auto-Refresh, Navigation aus `mobile_buddy.html` | Works | `Frontend/mobile_tasks.spec.js` lief real unter `430x932`; der Lauf verifizierte initiales Laden ueber `GET /task/tracker` bzw. Fallback `GET /task/queue`, Status-Filter, Detail-Sheet eines echten Tasks, CSV-/JSON-Downloads, Auto-Refresh-Toggle sowie die Navigation von Drawer `Task Tracker`, Summary `Tracker` und Drawer `Aufgaben` nach `mobile_tasks.html` |
| `mobile_buddy.html` | Floating Buddy widget send -> real Buddy reply in the dedicated bubble | Blocked | Browser run confirmed `POST /send` from the widget with `201` and `ok:true`, but no new Buddy reply appeared in the widget within 35 seconds; reproduction via headless Playwright on `2026-03-13` |
| `buddy_landing.html` | Page load plus live clickpath audit | Works with authenticated writes and frontdoor start | `Frontend/frontend_clickpath_audit.spec.js` passed its Buddy slice after the page moved start/send to token-aware `bridgeFetch(...)`; `Frontend/buddy_frontdoor_returning_user.spec.js` additionally verified the returning-user path with `buddy_running:false` and a successful Buddy start from the landing page |
| `buddy_landing.html` | CLI scan, existing-engine reuse or explicit engine choice, Buddy-home materialization, then start | Works | `Frontend/buddy_landing_setup.spec.js` verified the cached fast scan `GET /cli/detect?skip_runtime=1`, `POST /agents/buddy/setup-home`, and `POST /agents/buddy/start`; depending on the current Buddy state the page either offers the multi-CLI choice or reuses the existing Buddy engine, then confirms the setup and shows the Buddy greeting |
| `task_tracker.html` | Initial load | Works | Browser run after restart showed title `Bridge – Task Tracker`, `500` rows, footer `500 Tasks gefunden` |
| `task_tracker.html` | Host-neutral runtime resolution via `127.0.0.1:9787` and `localhost:9787` | Works | `Frontend/bridge_runtime_urls.spec.js` verified that the page still fetched `task/tracker` from `:9111` while preserving the current hostname |
| `task_tracker.html` | Filter + `Export JSON` / `Export CSV` | Works | `Frontend/frontend_clickpath_audit.spec.js` verified authenticated browser download events with filenames `task_tracker.json` and `task_tracker.csv` |
| `task_tracker.html` | Row click + detail close | Works | Browser run changed `#detailPanel` from `detailPanel` to `detailPanel open` and back |
| `project_config.html` | Empty-state guard | Works | Browser run after restart showed `#scanBtn` and `#createBtn` disabled on initial load |
| `project_config.html` | Scan existing project path | Works | Browser run on `./BRIDGE` returned `Projekt erkannt. 23 von 42 Konfigurationen gefunden.` |
| `project_config.html` | Create project with `/tmp` as target path | Works with client-side guard | Browser run now shows `Projekt-Erstellung ist nur innerhalb von /home/user/projects erlaubt.` before the POST path is used; the same audit run then created `/path/to/projects/bridge_frontend_audit_<ts>/frontend-audit-<ts>` successfully |
| `control_center.html` | Theme switch + workflow tab | Works | Browser run with `bridge_theme=black` loaded `data-theme="black"`, switched to `data-tab="workflows"`, and rendered `4` automation cards |
| `control_center.html` | Existing workflow read-path regression spec | Works | `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/control_center_n8n_degradation.spec.js --reporter=line` passed (`2 passed`) |
| `chat.html` | Existing workflow panel spec | Works | `env NODE_PATH="$(npm root -g)" npx playwright test Frontend/chat_workflow_buttons.spec.js --reporter=line` passed (`3 passed`) |
| `chat.html` | Approval badge open | Works | Browser run opened `#approvalPanel` and set `approvalPanel approvalPanel--open` |
| `chat.html` | Approval panel close via `#panelClose` | Works | `Frontend/chat_approval_panel.spec.js` now opens `#approvalPanel` and closes it again through `#panelClose`; `Frontend/chat.html` raised the panel above `#boardHeaderRight` in the stacking order |
| `chat.html` | Sidebar footer under narrow sidebar width | Works | `Frontend/chat_sidebar_footer.spec.js` forces `--sw:88px`, waits for the sidebar transition to settle, and verifies that the approval badge no longer overlaps the user-name area; `Frontend/chat.html` now allows the footer to wrap while keeping the badge as a fixed action |

## Runtime truth during the audit

- `buddy_landing.html` no longer fails at the CSP/module-import layer, no longer emits bare unauthenticated Bridge writes, and no longer redirects known users blindly into a dead Buddy chat when `buddy_running:false`.
- `buddy_landing.html` is now also the verified Buddy setup entry: the page can detect multiple installed CLIs, let the user choose the initial Buddy engine, materialize `BRIDGE_OPERATOR_GUIDE.md` plus engine-specific wrapper files, and only then start Buddy.
- `buddy_landing.html` now benefits from a cached/single-flight `/cli/detect` backend path; repeated frontdoor scans no longer need to fan out into conflicting runtime-probe races.
- After the frontdoor start Buddy can still pass through a short `phantom:true` boot window, but the latest live state later converged to `phantom:false` with `cli_identity_source=cli_register`; cleanup no longer deletes Buddy while the tmux session is alive during that window.
- `task_tracker.html` now exports through authenticated blob downloads instead of popup navigation.
- The platform is still a shared live runtime, so this matrix records representative verified clickpaths and not a destructive click-every-button sweep.

## Exhaustiveness note

This matrix is intentionally not a literal destructive all-controls sweep.
It records the clickpaths that were actually executed and ties them to live browser evidence.
