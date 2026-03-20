# Bridge ACE — Browser & Desktop Capabilities (IST-Zustand)

Stand: 2026-03-19

## Zusammenfassung

- **13 CDP-Tools** (Chrome DevTools Protocol) — Access to the user's real browser
- **10 Automation-Browser-Tools** — Compatibility-enhanced Playwright-Chromium with Proxy/Tor support
- **20 Unified-Browser-Tools** (bridge_browser_*) — Engine-agnostic abstraction over CDP and automation browsers
- **2 Meta-Browser-Tools** (research/action) — Playwright MCP als Read-Only-Backend
- **17 Desktop-Tools** — Echte Desktop-Steuerung via xdotool/gnome-screenshot
- **2 Vision-Tools** — Claude Vision API fuer Screenshot-Analyse und autonome Steuerung
- **1 Captcha-Tool** — CAPSolver + Anti-Captcha (Dual-Provider, Auto-Fallback)
- **Playwright MCP** (extern) — Headless Chromium, via Plugin geladen

**Engines total: 4** (CDP, Automation Playwright, Playwright MCP, Desktop/xdotool)

---

## 1. CDP (Chrome DevTools Protocol)

Verbindung zu the owner's laufendem Chrome oder Auto-Start eines headless Chrome.

### Verbindungsmechanismus

- Verbindet sich via `playwright.chromium.connect_over_cdp(http://localhost:{port})`
- Standard-Port: **9222**
- **Auto-Start**: Wenn kein Chrome auf dem Port laeuft, wird automatisch ein headless Chrome gestartet (`--headless=new`, `--remote-debugging-port=9222`)
- Fallback-Tab-Discovery via HTTP `/json` Endpoint (fuer Tabs die Playwright nicht erkennt)
- Singleton-Pattern: Eine CDP-Verbindung pro MCP-Prozess

### Tools

| Tool | Parameter | Beschreibung | Status |
|------|-----------|-------------|--------|
| `bridge_cdp_connect` | `port: int = 9222` | Verbindet zu Chrome via CDP. Auto-startet headless Chrome falls noetig. Gibt Tab-Liste zurueck. | Vollstaendig implementiert |
| `bridge_cdp_tabs` | — | Listet alle offenen Tabs mit URL, Titel und Index (Format `ctx:page`). | Vollstaendig implementiert |
| `bridge_cdp_navigate` | `url: str, tab_index: str = "0:0"` | Navigiert einen Tab zu einer URL. | Vollstaendig implementiert |
| `bridge_cdp_screenshot` | `tab_index: str = "0:0", full_page: bool = False` | Screenshot eines Tabs. Speichert als PNG in `/tmp/`. | Vollstaendig implementiert |
| `bridge_cdp_click` | `selector: str, tab_index: str = "0:0"` | Klickt ein Element per CSS-Selektor. | Vollstaendig implementiert |
| `bridge_cdp_fill` | `selector: str, value: str, tab_index: str = "0:0"` | Fuellt ein Input-Feld per CSS-Selektor. | Vollstaendig implementiert |
| `bridge_cdp_evaluate` | `expression: str, tab_index: str = "0:0"` | Fuehrt JavaScript auf einer Seite aus. AUDIT-geloggt. | Vollstaendig implementiert |
| `bridge_cdp_content` | `tab_index: str = "0:0"` | Gibt HTML-Inhalt zurueck (max 100KB, danach truncated). | Vollstaendig implementiert |
| `bridge_cdp_new_tab` | `url: str = "about:blank"` | Oeffnet neuen Tab mit optionaler URL. | Vollstaendig implementiert |
| `bridge_cdp_close_tab` | `tab_index: str` | Schliesst einen spezifischen Tab. | Vollstaendig implementiert |
| `bridge_cdp_file_upload` | `selector: str, file_path: str, tab_index: str = "0:0"` | Datei-Upload via `<input type="file">` Element. | Vollstaendig implementiert |
| `bridge_cdp_disconnect` | — | Trennt CDP-Verbindung, Browser bleibt offen. | Vollstaendig implementiert |

### Abhaengigkeiten

- `playwright` (Python-Paket)
- Chrome/Chromium (optional, wird auto-gestartet falls nicht vorhanden)

### Limitierungen

- Tab-Index-Format `ctx:page` kann sich aendern wenn Tabs geoeffnet/geschlossen werden
- Auto-gestarteter Chrome laeuft headless — kein visuelles Feedback
- No proxy support (use automation engine instead)

---

## 2. Automation Browser

Compatibility-enhanced browser based on Playwright Chromium with extensive compatibility patches.

### Engine

- **Playwright Chromium** (bundled, NOT system Chrome — due to CDP version conflicts)
- No Patchright — standard Playwright with manual compatibility injections

### Compatibility Features

- `--disable-blink-features=AutomationControlled` (removes `navigator.webdriver`)
- CDP `Runtime.evaluate` for compatibility script injection (before and after navigation)
- `context.add_init_script()` for compatibility scripts (works in Workers + iframes)
- **Proxy/Tor OPSEC Hardening:**
  - WebRTC IP-Leak Prevention (`--force-webrtc-ip-handling-policy=disable_non_proxied_udp`)
  - WebRTC Permission Block (`context.grant_permissions([])`)
  - DNS-Leak Prevention via SOCKS5h (automatisch bei Proxy-Config)
  - Service Worker Blocking fuer Proxy-Sessions
  - Background-Networking deaktiviert
- **UA-Spoofing:**
  - Default UA: Chrome 145 auf Linux
  - Tor-Modus: Firefox/140.0 ESR UA (Tor Browser 15.0)
  - UA wird via CLI-Arg gesetzt (nicht nur CDP), wirkt auch in Workers
- **Firefox-Like Identity Mode:**
  - `sec-ch-ua*` Headers werden gestrippt
  - Worker-Navigator-Spoofing (platform, appVersion, userAgent)
  - Timezone auf `Etc/UTC` gesetzt
  - Custom Route-Interceptor fuer Worker-Requests
- **Locale/Language Hardening:** `Accept-Language: en-US`, `locale: en-US`
- **Viewport bei Proxy:** 1920x1040 (vermeidet headless-typische 1280x720)
- **Protection Detection:** Automatically detects Cloudflare, Akamai, DataDome challenge pages

### Session Management

- Max **3** gleichzeitige Sessions pro Agent-Prozess
- Idle-Timeout: **300s** (5 Minuten), danach auto-cleanup
- Cookie-Persistenz via Profile-Parameter (JSON-Datei pro Profil)
- Cookie-Persistenz **deaktiviert** bei Proxy-Sessions (OPSEC)

### Tools

| Tool | Parameter | Beschreibung | Status |
|------|-----------|-------------|--------|
| `bridge_stealth_start` | `proxy: str, user_agent: str, headless: bool = True, profile: str` | Start automation session. Returns session_id. | Fully implemented |
| `bridge_stealth_goto` | `session_id: str, url: str, timeout: int = 30000` | Navigiert zu URL. Double-Injection (commit + load). Erkennt Bot-Challenges. | Vollstaendig implementiert |
| `bridge_stealth_content` | `session_id: str` | HTML-Inhalt der Seite (max 50KB). Mit Freshness-Warning. | Vollstaendig implementiert |
| `bridge_stealth_screenshot` | `session_id: str, full_page: bool = True` | Screenshot als PNG in `/tmp/`. | Vollstaendig implementiert |
| `bridge_stealth_click` | `session_id: str, selector: str` | Klick per CSS-Selektor. Wartet auf potenzielle Navigation. | Vollstaendig implementiert |
| `bridge_stealth_fill` | `session_id: str, selector: str, value: str` | Fuellt Input-Feld per CSS-Selektor. | Vollstaendig implementiert |
| `bridge_stealth_evaluate` | `session_id: str, expression: str` | JavaScript ausfuehren. AUDIT-geloggt. | Vollstaendig implementiert |
| `bridge_stealth_file_upload` | `session_id: str, selector: str, file_path: str` | Datei-Upload via `<input type="file">`. | Vollstaendig implementiert |
| `bridge_stealth_fingerprint_snapshot` | `session_id: str` | Browser-Fingerprint erfassen (navigator, screen, etc.) fuer Lab-Analyse. | Vollstaendig implementiert |
| `bridge_stealth_close` | `session_id: str` | Session schliessen, Cookies speichern, Ressourcen freigeben. | Vollstaendig implementiert |

### Abhaengigkeiten

- `playwright` (Python-Paket)
- `playwright install chromium` (Bundled Chromium)

---

## 3. Unified Browser API (bridge_browser_*)

Engine-agnostic abstraction over automation browser and CDP. Selects engine at `bridge_browser_open` und routet alle Folge-Operationen automatisch.

### Tools

| Tool | Parameter | Beschreibung | Status |
|------|-----------|-------------|--------|
| `bridge_browser_open` | `url, engine="auto", headless, proxy, user_agent, profile` | Opens session. Engine: automation/cdp/auto. Auto: automation preferred, CDP fallback. | Fully implemented |
| `bridge_browser_navigate` | `session_id: str, url: str` | Navigiert innerhalb einer Session. | Vollstaendig implementiert |
| `bridge_browser_observe` | `session_id: str, max_nodes: int = 50` | Erzeugt Accessibility-Tree mit stabilen Refs fuer click_ref/fill_ref. | Vollstaendig implementiert |
| `bridge_browser_find_refs` | `session_id: str, query: str, max_results: int = 10` | Sucht Elemente per Text/Attribut, gibt scored Candidates mit Refs zurueck. | Vollstaendig implementiert |
| `bridge_browser_click` | `session_id: str, selector: str` | Klick per CSS-Selektor. | Vollstaendig implementiert |
| `bridge_browser_click_ref` | `session_id: str, ref: str` | Klick per Ref (aus bridge_browser_observe). | Vollstaendig implementiert |
| `bridge_browser_fill` | `session_id: str, selector: str, value: str` | Input fuellen per CSS-Selektor. | Vollstaendig implementiert |
| `bridge_browser_fill_ref` | `session_id: str, ref: str, value: str` | Input fuellen per Ref. | Vollstaendig implementiert |
| `bridge_browser_content` | `session_id: str` | HTML-Inhalt der Seite. | Vollstaendig implementiert |
| `bridge_browser_screenshot` | `session_id: str, full_page: bool = True` | Screenshot als PNG. | Vollstaendig implementiert |
| `bridge_browser_evaluate` | `session_id: str, expression: str` | JavaScript ausfuehren. AUDIT-geloggt. | Vollstaendig implementiert |
| `bridge_browser_upload` | `session_id: str, selector: str, file_path: str` | Datei-Upload. | Vollstaendig implementiert |
| `bridge_browser_verify` | `session_id: str, ...conditions...` | Postcondition-Pruefung (URL, Title, Content, Selector, JS-Expression). | Vollstaendig implementiert |
| `bridge_browser_click_ref_verify` | `session_id: str, ref: str, ...verify_conditions...` | Klick + automatische Verifikation in einem Schritt. | Vollstaendig implementiert |
| `bridge_browser_fill_ref_verify` | `session_id: str, ref: str, value: str, ...verify_conditions...` | Fill + automatische Verifikation in einem Schritt. | Vollstaendig implementiert |
| `bridge_browser_fingerprint_snapshot` | `session_id: str` | Browser-Fingerprint (funktioniert mit beiden Engines). | Vollstaendig implementiert |
| `bridge_browser_close` | `session_id: str` | Close session (closes automation session or CDP tab). | Fully implemented |
| `bridge_browser_sessions` | — | Listet alle aktiven Unified-Sessions. | Vollstaendig implementiert |

### Architektur

- Jede `bridge_browser_*` Funktion liest die Engine aus `_unified_sessions[session_id]`
- Delegates internally to `bridge_stealth_*` or `bridge_cdp_*`
- Alle Ergebnisse durchlaufen `_structured_action_json()` fuer konsistentes Output-Format
- Execution Journal erfasst jeden Schritt (run_id, step_id, artifacts)

---

## 4. Playwright MCP (extern)

Separater MCP-Server, als Plugin geladen (nicht in bridge_mcp.py implementiert).

### Verbindung

- Wird als Subprocess gestartet via `_playwright_mcp_session()`
- JSON-RPC ueber stdin/stdout (MCP stdio-Transport)
- Pro Aufruf ein neuer Subprocess (kein persistenter Browser-State zwischen bridge_browser_research-Calls)

### Verfuegbare Tools (via Plugin)

| Tool | Beschreibung |
|------|-------------|
| `browser_navigate` | Navigation zu URL |
| `browser_snapshot` | Accessibility-Tree Snapshot |
| `browser_take_screenshot` | Screenshot als PNG |
| `browser_click` | Klick per Ref |
| `browser_fill_form` | Formular fuellen |
| `browser_evaluate` | JavaScript ausfuehren |
| `browser_hover` | Hover ueber Element |
| `browser_drag` | Drag & Drop |
| `browser_press_key` | Taste druecken |
| `browser_file_upload` | Datei-Upload |
| `browser_select_option` | Dropdown-Auswahl |
| `browser_handle_dialog` | Dialog behandeln |
| `browser_tabs` | Tabs auflisten |
| `browser_close` | Browser schliessen |
| `browser_resize` | Viewport-Groesse aendern |
| `browser_console_messages` | Console-Logs lesen |
| `browser_network_requests` | Netzwerk-Requests anzeigen |
| `browser_navigate_back` | Zurueck-Navigation |
| `browser_wait_for` | Auf Element/Zustand warten |
| `browser_run_code` | Playwright-Code ausfuehren |
| `browser_install` | Browser installieren |
| `browser_type` | Text tippen |

### Modus

- Headless (Standard)
- Genutzt von `bridge_browser_research` und `bridge_browser_action` als Backend

### Abhaengigkeiten

- Playwright MCP Plugin (claude-plugins-official/playwright)

---

## 5. Browser Research & Action (Meta-Tools)

### Tools

| Tool | Parameter | Beschreibung | Backend | Status |
|------|-----------|-------------|---------|--------|
| `bridge_browser_research` | `url: str, question: str` | Read-Only: Navigiert zu URL, macht Snapshot + Screenshot, gibt strukturierte Daten zurueck. Keine Approval noetig. Enthaelt Freshness-Warning bei alten Seiten. | Playwright MCP | Vollstaendig implementiert |
| `bridge_browser_action` | `url: str, action_description: str, risk_level: str = "medium"` | Erstellt Approval-Request fuer konsequenzreiche Browser-Aktionen. Macht Preview-Screenshot. The owner muss genehmigen (oder Standing Approval). | Playwright MCP + Approval API | Vollstaendig implementiert |

### Ablauf bridge_browser_research

1. Startet Playwright MCP Subprocess
2. `browser_navigate` → `browser_snapshot` → `browser_take_screenshot` (in einer Session)
3. Gibt zurueck: Snapshot-Text (max 12KB), Screenshot-Pfad, Page-Date, Freshness-Warning

### Ablauf bridge_browser_action

1. Startet Playwright MCP Subprocess
2. `browser_navigate` → `browser_take_screenshot` (Preview)
3. Sendet Approval-Request an Bridge-Server (`/approval/request`)
4. Gibt `pending_approval` oder `auto_approved` zurueck

---

## 6. Desktop Control

Echte Desktop-Steuerung auf dem lokalen Linux-System.

### Technologie

- **xdotool** — Maussteuerung, Tastatureingabe, Fenster-Management
- **gnome-screenshot** — Desktop-Screenshots (Fullscreen)
- **import** (ImageMagick) — Fenster-spezifische Screenshots
- **xclip** — Clipboard-Zugriff
- **Bezier-Kurven** — Natural mouse movement patterns (kubische Bezier mit Gaussian Micro-Tremor)
- **Gaussian Timing** — Natural keyboard timing patterns (75ms +/- 20ms, 5% Denkpausen)

### Tools

| Tool | Parameter | Beschreibung | Abhaengigkeit | Status |
|------|-----------|-------------|--------------|--------|
| `bridge_desktop_screenshot` | `window_name: str = ""` | Screenshot Desktop oder spezifisches Fenster. Speichert in `BRIDGE/Backend/screenshots/`. | gnome-screenshot, import, xdotool | Vollstaendig implementiert |
| `bridge_desktop_screenshot_stream` | `interval_ms=500, duration_s=10, max_frames=30, window_name` | Serie von Screenshots in regelmaessigen Intervallen (min 200ms, max 60s, max 120 Frames). | gnome-screenshot, import, xdotool | Vollstaendig implementiert |
| `bridge_desktop_click` | `x: int, y: int, button: int = 1` | Klick an Bildschirmkoordinaten. Bezier-Mausbewegung zum Ziel. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_double_click` | `x: int, y: int, button: int = 1` | Doppelklick mit Bezier-Bewegung. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_type` | `text: str, delay_ms: int = 12` | Text tippen mit natural timing patterns. Max 5000 Zeichen. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_key` | `combo: str` | Tastenkombination senden (z.B. `ctrl+s`, `alt+F4`). Input-Validierung gegen Injection. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_scroll` | `direction="down", clicks=3, x=-1, y=-1` | Scrollen (up/down), optional an Position. 1-20 Schritte. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_hover` | `x: int, y: int` | Maus bewegen OHNE klicken (Bezier-Kurve). Fuer Hover-Menus/Tooltips. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_drag` | `start_x, start_y, end_x, end_y, button=1` | Drag & Drop mit Bezier-Kurve. Mouseup-Sicherung bei Fehler. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_clipboard_read` | — | Clipboard-Inhalt lesen. Max 50KB. | xclip | Vollstaendig implementiert |
| `bridge_desktop_clipboard_write` | `text: str` | Text in Clipboard schreiben. Max 100KB. | xclip | Vollstaendig implementiert |
| `bridge_desktop_wait` | `window_name: str, timeout: int = 30` | Wartet bis Fenster erscheint (Polling alle 500ms). Max 120s. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_window_list` | `name_filter: str = ""` | Listet alle Fenster mit ID, Name, Position, Groesse. Max 50 Fenster. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_window_focus` | `window_id: str, window_name: str` | Fenster in den Vordergrund bringen (per ID oder Name). | xdotool | Vollstaendig implementiert |
| `bridge_desktop_window_resize` | `width, height, x, y, window_id, window_name` | Fenster-Groesse und/oder Position aendern. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_window_minimize` | `window_id: str, window_name: str` | Fenster minimieren. | xdotool | Vollstaendig implementiert |
| `bridge_desktop_observe` | `window_name, include_screenshot, include_windows, include_clipboard, ocr` | Strukturierter Desktop-Snapshot: fokussiertes Fenster, Screenshot, Fensterliste, Clipboard, optional OCR. | gnome-screenshot, xdotool, xclip | Vollstaendig implementiert |
| `bridge_desktop_verify` | `window_name, expect_focused_window, expect_focused_name_contains, expect_window_name_contains, expect_clipboard_contains, expect_ocr_contains, require_screenshot` | Postcondition-Pruefung mit Pass/Fail-Ergebnis pro Bedingung. | alle Desktop-Tools | Vollstaendig implementiert |

### Koordinaten-Limits

- x: 0–10000, y: 0–10000

### Besonderheiten

- Alle Klick/Drag/Hover-Tools nutzen Bezier-Kurven fuer natural mouse movement patterns
- Typing hat Gaussian-verteilte Pausen und 5% Wahrscheinlichkeit fuer "Denkpausen" (200-600ms)
- DISPLAY-Variable wird automatisch auf `:0` gesetzt falls nicht vorhanden

---

## 7. Vision (Claude Vision API)

### Tools

| Tool | Parameter | Beschreibung | Abhaengigkeit | Status |
|------|-----------|-------------|--------------|--------|
| `bridge_vision_analyze` | `screenshot_path: str, prompt: str, model: str = ""` | Analysiert Screenshot via Claude Vision API. Gibt UI-Elemente, Text und Aktionsvorschlaege zurueck. Max 20MB. Formate: PNG, JPG, GIF, WebP. | ANTHROPIC_API_KEY, httpx | Vollstaendig implementiert |
| `bridge_vision_act` | `session_id: str, goal: str, max_steps: int = 10` | Autonome Vision-Action-Loop: Screenshot → Claude Vision → Aktion → Verify → Repeat. Aktionen: click, fill, goto, evaluate, wait, done. Max 25 Steps. | ANTHROPIC_API_KEY, httpx, active automation session | Vollstaendig implementiert |

### Vision Analyze

- **Model:** `claude-sonnet-4-6` (Standard, konfigurierbar)
- **API:** `https://api.anthropic.com/v1/messages`
- **Max Tokens:** konfigurierbar via `_VISION_MAX_TOKENS`
- **System-Prompt:** Strukturierte JSON-Ausgabe mit elements, text, suggested_actions, page_description
- **Token-Tracking:** Nutzung wird via `token_tracker` geloggt

### Vision Act

- Requires active **automation session** (not CDP)
- Loop: Screenshot → Base64 → Claude Vision mit History → Action Decision → Ausfuehren
- Action-Types: `click`, `fill`, `goto`, `evaluate`, `wait`, `done`
- History: Letzte 5 Schritte werden als Kontext mitgegeben
- Bei Action-Fehler: Kein Abbruch, naechster Screenshot-Zyklus
- Gibt zurueck: success-Status, Action-History, finaler Screenshot-Pfad

---

## 8. Captcha Solver

### Tool

| Tool | Parameter | Beschreibung | Status |
|------|-----------|-------------|--------|
| `bridge_captcha_solve` | `captcha_type: str, website_url: str, website_key: str, min_score: float = 0.7, provider: str = "auto"` | Loest CAPTCHA via externen Service. Token wird zurueckgegeben fuer Injection via `bridge_stealth_evaluate`. | Vollstaendig implementiert |

### Provider

| Provider | Config-Pfad | Unterstuetzte Typen |
|----------|-------------|---------------------|
| **CAPSolver** | `~/.config/bridge/capsolver_account.json` | recaptcha_v2, recaptcha_v3, turnstile, hcaptcha, funcaptcha, datadome |
| **Anti-Captcha** | `~/.config/bridge/anticaptcha_account.json` | recaptcha_v2, recaptcha_v3, turnstile, hcaptcha, funcaptcha, recaptcha_v2_enterprise, recaptcha_v3_enterprise |

### Ablauf

1. `provider="auto"`: Versucht CAPSolver zuerst
2. Bei Fehler (z.B. Policy-Block): Automatischer Fallback auf Anti-Captcha
3. Polling: max 120s, alle 5s
4. Token-Injection: Manuell via `bridge_stealth_evaluate` (kein Auto-Inject)

### Abhaengigkeiten

- API-Key in jeweiliger Config-Datei
- `httpx` fuer HTTP-Requests

---

## Architektur-Uebersicht

```
┌─────────────────────────────────────────────────┐
│           Unified Browser API                    │
│     bridge_browser_open/navigate/click/...      │
│         (engine-agnostisch)                      │
├────────────────┬────────────────────────────────┤
│  Automation    │         CDP                     │
│ (Playwright)   │  (Chrome DevTools)              │
│ Compatibility  │  User's Browser or              │
│ Proxy/Tor      │  Auto-Start Headless            │
├────────────────┴────────────────────────────────┤
│         Playwright MCP (extern)                  │
│  bridge_browser_research / bridge_browser_action │
│  (Read-Only / Approval-basiert)                  │
├─────────────────────────────────────────────────┤
│         Desktop Control                          │
│  xdotool + gnome-screenshot + xclip             │
│  Bezier-Mausbewegungen, Gaussian-Typing         │
├─────────────────────────────────────────────────┤
│         Vision (Claude API)                      │
│  Screenshot-Analyse + Autonome Action-Loop       │
├─────────────────────────────────────────────────┤
│         Captcha (CAPSolver / Anti-Captcha)       │
│  Token-Solving fuer reCAPTCHA, Turnstile, etc.  │
└─────────────────────────────────────────────────┘
```

## Tool-Gesamtzahl

| Kategorie | Anzahl | Quelle |
|-----------|--------|--------|
| CDP (bridge_cdp_*) | 12 | bridge_mcp.py |
| Automation (bridge_stealth_*) | 10 | bridge_mcp.py |
| Unified Browser (bridge_browser_*) | 20 | bridge_mcp.py |
| Meta-Browser (research/action) | 2 | bridge_mcp.py |
| Desktop (bridge_desktop_*) | 17 | bridge_mcp.py |
| Vision (bridge_vision_*) | 2 | bridge_mcp.py |
| Captcha (bridge_captcha_*) | 1 | bridge_mcp.py |
| Playwright MCP (extern) | 22 | Plugin |
| **Gesamt** | **86** | |

Alle bridge_*-Tools in bridge_mcp.py sind vollstaendig implementiert (kein Stub-Code). Jedes Tool hat Error-Handling, Input-Validierung und AUDIT-Logging fuer sicherheitskritische Operationen (evaluate).
