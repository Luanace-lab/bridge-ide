---
name: stealth-browser
description: >
  Stealth browser automation for bot-detection bypass. This skill should be used
  when navigating websites with anti-bot protection (Cloudflare, DataDome, Akamai),
  performing browser automation that must appear human, or when standard Playwright
  fails due to detection. Covers Camoufox, CDP, Patchright, fingerprinting, captcha
  solving, and human-behavior simulation.
user-invocable: false
---

# Stealth Browser Automation Skill

## Wann diesen Skill nutzen
- Externe Websites mit Bot-Detection (Cloudflare, Akamai, DataDome)
- Account-Aktionen die menschlich wirken muessen
- Captcha-Loesungen
- Web-Scraping auf geschuetzten Seiten

## Wann NICHT nutzen
- Interne Bridge-Seiten (127.0.0.1:9111) — kein Stealth noetig
- Einfache API-Calls — curl/WebFetch reicht
- Seiten ohne Bot-Protection — Playwright MCP reicht

## Engine-Auswahl (WICHTIG)

### 1. Camoufox (DEFAULT — 0% Detection)
```
bridge_stealth_start(engine="camoufox")
bridge_stealth_goto(session_id="...", url="https://target.com")
bridge_stealth_screenshot(session_id="...")
```
- Firefox-Fork mit C++ Patches — NICHT per JS detektierbar
- CreepJS: 0% headless, 0% stealth
- Fuer: Alle externen Websites, Anti-Bot-Bypass

### 2. CDP (Echtes Chrome — 0% Detection)
```
bridge_cdp_connect(port=9222)
bridge_cdp_navigate(url="https://target.com")
bridge_cdp_screenshot()
```
- Leos ECHTER Chrome-Browser — real Fingerprint
- Fuer: Maximale Stealth, Account-Aktionen, OAuth-Flows
- Einschraenkung: Nur 1 Session, teilt sich mit Leos Browser

### 3. Patchright (Fallback)
```
bridge_stealth_start(engine="patchright")
```
- Chromium mit CDP-Leak-Patches + JS-Stealth-Injections
- CreepJS: ~44% like headless — NICHT fuer harte Targets
- Fuer: Parallele Sessions wenn Camoufox belegt

## Captcha-Loesung (kostenlos)

| Captcha-Typ | Tool | Methode |
|-------------|------|---------|
| Text | `bridge_captcha_solve_native(type="text", image_path="...")` | Tesseract OCR |
| Audio/reCAPTCHA v2 | `bridge_captcha_solve_native(type="recaptcha_v2_audio", audio_path="...")` | Whisper STT |
| Cloudflare Turnstile | `bridge_captcha_solve_native(type="turnstile", session_id="...")` | Auto-Wait 30s |
| reCAPTCHA v2 Image | `bridge_captcha_solve_native(type="recaptcha_v2_image", image_path="...")` | YOLO (braucht ultralytics) |
| hCaptcha Image | `bridge_captcha_solve_native(type="hcaptcha_image", image_path="...")` | LLaVA/Ollama |

## Menschliches Verhalten

Desktop-Tools haben eingebaute menschliche Simulation:
- `bridge_desktop_click` — Bezier-Mausbewegung + Micro-Tremor
- `bridge_desktop_hover` — Natuerliche Kurve zum Ziel
- `bridge_desktop_drag` — Bezier + langsame Bewegung

## Anti-Patterns (VERBOTEN)
- `headless=True` fuer externe Seiten → IMMER Camoufox oder CDP
- Patchright fuer Cloudflare/Akamai → Wird erkannt, nutze Camoufox
- Bezahlte Captcha-Services (CAPSolver) fuer Text/Audio → Tesseract/Whisper ist kostenlos
- Mehrere CDP-Sessions gleichzeitig → Nur 1 erlaubt

## Typischer Workflow
1. `bridge_stealth_start(engine="camoufox")` — Session starten
2. `bridge_stealth_goto(session_id, url)` — Navigieren
3. `bridge_stealth_screenshot(session_id)` — Pruefen was sichtbar ist
4. Bei Captcha: `bridge_captcha_solve_native(type="...", session_id=...)` — Loesen
5. `bridge_stealth_click/fill(session_id, selector, text)` — Interagieren
6. `bridge_stealth_close(session_id)` — Aufraeumen
