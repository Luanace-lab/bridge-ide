# Browser-Haertung & Native Captcha — Architekturplan
Stand: 2026-03-19

## Ziel
Bridge browser achieves full compatibility with modern website protection systems.
All captcha types solvable natively, without paid services.

## IST-Zustand (Quellen: Backend IST-Analyse, Viktor Web-Research, Assi Capabilities-Audit)

| Komponente | Status | Problem |
|------------|--------|---------|
| Automation Browser | Playwright + JS-Spoofing | ~20% creepjs, CDP-Leaks |
| Maussteuerung | xdotool teleport | Kein Bezier, kein Tremor |
| Tastatur | xdotool key | Kein realistisches Timing |
| Captcha | CAPSolver + Anti-Captcha | Bezahlt, extern |
| CDP | Real Chrome Attach | 0% Detection (gut) |
| Ghost MCP | Patchright + 5-Layer compatibility | Best compatibility, but separate system |

## SOLL-Zustand

| Komponente | Ziel | Technologie |
|------------|------|-------------|
| Automation Browser | <5% creepjs detection | Patchright + BrowserForge Fingerprints |
| Mouse Control | Natural interaction patterns | Bezier + Perlin-Noise + Micro-Tremor |
| Tastatur | Realistische WPM + Tippfehler | Gauss-Timing + Markov-Chain |
| Captcha (Text) | 95%+ Solve-Rate | Tesseract OCR (lokal, kostenlos) |
| Captcha (Audio) | 90%+ Solve-Rate | Whisper STT (lokal, kostenlos) |
| Captcha (Turnstile) | Auto-Solve | Patchright + compatibility wait |
| Captcha (reCAPTCHA v2 Image) | 80%+ Solve-Rate | Ghost DETR + YOLO |
| Captcha (reCAPTCHA v3) | Score-based | Compatibility mode + natural behavior |
| Captcha (hCaptcha) | Experimentell | LLaVA via Ollama (mittelfristig) |

## Umsetzungsplan

### Phase 1: ERLEDIGT (heute)
1. ✓ Patchright als Playwright-Ersatz (bridge_mcp.py, 3 Stellen)
2. ✓ Native Captcha-Solver (Tesseract + Whisper + Turnstile Auto-Solve)
3. ✓ Watcher smart_inject Prompt-Check (retry-Loop)

### Phase 2: Fingerprint Hardening (next iteration)
4. BrowserForge Integration — konsistente Fingerprints (UA, Canvas, WebGL, AudioContext)
5. Client Hints Spoofing — navigator.userAgentData vollstaendig
6. TLS-Fingerprint — JA4+ kompatibel (Patchright loest CDP-Leak, aber TLS bleibt)
7. HTTP/2 Settings-Frame — SETTINGS/PRIORITY korrekt fuer Chrome-Signatur
8. WebRTC Haertung — mDNS-Mode oder UDP-over-SOCKS5

### Phase 3: Natural UX Patterns (parallel to Phase 2)
9. Bezier mouse movements in bridge_desktop_* (OxyMouse or custom implementation)
10. Gaussian keystroke timing in bridge_desktop_type (50-120ms, Markov-Chain)
11. Scroll patterns with momentum + idle simulation
12. Loading behavior — wait after navigation like a real user

### Phase 4: Captcha-Erweiterung (mittelfristig)
13. reCAPTCHA v2 Image via YOLO (VisionAIRecaptchaSolver)
14. hCaptcha via LLaVA/Ollama (experimentell, lokales MLLM)
15. CAPSolver/Anti-Captcha als Fallback behalten, nicht als Default

### Phase 5: Consolidation
16. Ghost MCP + Bridge automation unify — one engine, best features of both
17. creepjs score as CI test (target: <5%)
18. Compatibility regression tests

## Testkriterien

| Test | Tool | Zielwert |
|------|------|----------|
| creepjs Score | https://abrahamjuliot.github.io/creepjs/ | <5% Detection |
| Compatibility | https://bot.sannysoft.com/ | 0 Fails |
| reCAPTCHA v2 Text | Tesseract | >95% Solve-Rate |
| reCAPTCHA v2 Audio | Whisper | >90% Solve-Rate |
| Turnstile | Auto-Solve | >85% Solve-Rate |
| Maus-Erkennung | https://kaliiiiiiiiii.github.io/brotern/ | Human-Score >0.8 |

## Abhaengigkeiten

- Patchright: `pip install patchright && patchright install chromium` ✓ installiert
- Tesseract: `apt install tesseract-ocr` ✓ verfuegbar
- Whisper: `pip install openai-whisper` — benoetigt GPU fuer Echtzeit
- YOLO: `pip install ultralytics` — fuer reCAPTCHA v2 Image
- BrowserForge: `pip install browserforge` — fuer Fingerprint-Generierung
- Ollama + LLaVA: Optional, fuer hCaptcha (GPU-intensiv)

## Arbeitsaufteilung

| Agent | Aufgabe |
|-------|---------|
| Backend | Code-Implementation (bridge_mcp.py, bridge_watcher.py) |
| Viktor | Code-Review + Architektur-Validierung |
| Assi | Koordination, Task-Management, Abnahme |

## Git-Workflow
Alle Aenderungen auf release branch → Review → Main merge → Push.
