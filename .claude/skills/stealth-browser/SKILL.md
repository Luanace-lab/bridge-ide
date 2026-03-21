---
name: stealth-browser
description: >
  Browser automation for protected sites. This skill should be used
  when navigating websites with advanced protection layers (Cloudflare, DataDome, Akamai),
  performing browser automation that requires natural interaction patterns, or when standard
  Playwright fails due to compatibility issues. Covers Camoufox, CDP, Patchright, fingerprint
  management, captcha handling, and natural behavior simulation.
user-invocable: false
---

# Browser Automation for Protected Sites

## When to use this skill
- External websites with advanced protection (Cloudflare, Akamai, DataDome)
- Natural browser interaction patterns for reliable automation
- Captcha handling
- Web data collection on protected sites

## When NOT to use
- Internal Bridge pages (127.0.0.1:9111) — no special handling needed
- Simple API calls — curl/WebFetch is sufficient
- Sites without protection layers — Playwright MCP is sufficient

## Engine Selection (IMPORTANT)

### 1. Camoufox (DEFAULT — full compatibility)
```
bridge_stealth_start(engine="camoufox")
bridge_stealth_goto(session_id="...", url="https://target.com")
bridge_stealth_screenshot(session_id="...")
```
- Firefox fork with C++ patches — optimized for maximum browser compatibility
- CreepJS: 0% headless, 0% automation flags
- For: All external websites, protected site access

### 2. CDP (Real Chrome — full compatibility)
```
bridge_cdp_connect(port=9222)
bridge_cdp_navigate(url="https://target.com")
bridge_cdp_screenshot()
```
- The user's REAL Chrome browser — authentic fingerprint
- For: Maximum compatibility, account actions, OAuth flows
- Limitation: Only 1 session, shared with user's browser

### 3. Patchright (Fallback)
```
bridge_stealth_start(engine="patchright")
```
- Chromium with compatibility patches + JS injections
- CreepJS: ~44% like headless — NOT for strict protection
- For: Parallel sessions when Camoufox is busy

## Captcha Handling (free, local)

| Captcha Type | Tool | Method |
|-------------|------|---------|
| Text | `bridge_captcha_solve_native(type="text", image_path="...")` | Tesseract OCR |
| Audio/reCAPTCHA v2 | `bridge_captcha_solve_native(type="recaptcha_v2_audio", audio_path="...")` | Whisper STT |
| Cloudflare Turnstile | `bridge_captcha_solve_native(type="turnstile", session_id="...")` | Auto-Wait 30s |
| reCAPTCHA v2 Image | `bridge_captcha_solve_native(type="recaptcha_v2_image", image_path="...")` | YOLO (requires ultralytics) |
| hCaptcha Image | `bridge_captcha_solve_native(type="hcaptcha_image", image_path="...")` | LLaVA/Ollama |

## Natural Interaction Patterns

Desktop tools have built-in natural behavior simulation:
- `bridge_desktop_click` — Bezier curve mouse movement + micro-tremor
- `bridge_desktop_hover` — Natural curve to target
- `bridge_desktop_drag` — Bezier + gradual movement

## Anti-Patterns (FORBIDDEN)
- `headless=True` for external sites — ALWAYS use Camoufox or CDP
- Patchright for Cloudflare/Akamai — compatibility issues, use Camoufox
- Paid captcha services (CAPSolver) for text/audio — Tesseract/Whisper is free
- Multiple CDP sessions simultaneously — Only 1 allowed

## Typical Workflow
1. `bridge_stealth_start(engine="camoufox")` — Start session
2. `bridge_stealth_goto(session_id, url)` — Navigate
3. `bridge_stealth_screenshot(session_id)` — Check what's visible
4. If captcha: `bridge_captcha_solve_native(type="...", session_id=...)` — Handle it
5. `bridge_stealth_click/fill(session_id, selector, text)` — Interact
6. `bridge_stealth_close(session_id)` — Clean up
