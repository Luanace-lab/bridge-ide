# Tor Integration — Konsolidierte Analyse
Stand: 2026-03-19 | Autor: Assi (konsolidiert aus Viktor, Backend, eigener Recherche)

---

## 1. ALLE EMPFEHLUNGEN (zusammengefasst)

### Sofort machbar (kein sudo, kein neuer Service)
| # | Empfehlung | Aufwand | Status |
|---|-----------|---------|--------|
| 1 | Auto-Tor-Detection (Proxy 9050 → Firefox + alle Prefs) | ~50 LOC | ✓ DONE |
| 2 | 20 resistFingerprinting Firefox-Prefs | Config | ✓ DONE |
| 3 | WebRTC/WebGL/AudioContext/NetworkInfo Kill | Config | ✓ DONE |
| 4 | Tor Browser UA (ESR) | 1 Zeile | ✓ DONE |
| 5 | Viewport 1000x900 (Tor Standard) | 1 Zeile | ✓ DONE |
| 6 | DNS-over-HTTPS only (trr.mode=3) | 1 Zeile | ✓ DONE |
| 7 | Navigation-Jitter (Gauss 2.5s ±0.8s) | ~10 LOC | ✓ DONE |
| 8 | Cookie-Isolation bei Tor | 1 Zeile | ✓ DONE |
| 9 | Traffic Padding (20 Sites, Gauss-Intervall) | ~40 LOC | ✓ DONE |
| 10 | Obfs4 Bridge Config | ~50 LOC | ✓ DONE |
| 11 | VanguardsEnabled in torrc | 1 Zeile | ✓ DONE |
| 12 | bridge_tor_start/rotate/status MCP Tools | ~130 LOC | ✓ DONE |
| 13 | Automatischer DNS-Leak-Test | ~10 LOC | ✓ DONE |

### Braucht sudo
| # | Empfehlung | Aufwand | Status |
|---|-----------|---------|--------|
| 14 | Kloak (Keystroke-Anonymisierung) | Install + sudo | OFFEN |
| 15 | Xvfb (virtueller Bildschirm) | apt install | ✓ DONE |

### Braucht VM/Hardware
| # | Empfehlung | Aufwand | Status |
|---|-----------|---------|--------|
| 16 | Whonix VM (maximale Isolation) | KVM Setup | OFFEN |
| 17 | Öffentliches WiFi (ISP-Korrelation brechen) | Physisch | OFFEN |
| 18 | WebTunnel statt obfs4 (gegen Active Probing) | Plugin | OFFEN |

---

## 2. IST-ZUSTAND KONKRET

### Was FUNKTIONIERT (real verifiziert mit Screenshots)

| Test | Ergebnis | Evidenz |
|------|----------|---------|
| check.torproject.org | "Congratulations. This browser is configured to use Tor." | Screenshot |
| ipleak.net IP | 185.246.190.136 (Island, FlokiNET — Tor Exit) | Screenshot |
| ipleak.net WebRTC | "No leak, RTCPeerConnection not available" | Screenshot |
| ipleak.net DNS | 0 servers detected, 21 tests — KEIN Leak | Screenshot |
| ipleak.net IPv6 Fallback | Fail (timeout) — blockiert | Screenshot |
| CreepJS | 0% headless, 0% stealth, 0% like headless (BLOCKED) | Viktor-Test |
| UA | Firefox/140.0 (Linux) — kein HeadlessChrome | Verifiziert |
| Platform | Win32 (resistFingerprinting spooft) | Verifiziert |
| opsec_hardened | true | Session-Response |

### Was NICHT funktioniert / OFFEN

| Problem | Schwere | Grund |
|---------|---------|-------|
| AudioContext bei Camoufox | HOCH | Camoufox hat keinen block_audio Parameter |
| UA Version (Firefox 135 statt ESR 128) bei Camoufox | MITTEL | Camoufox akzeptiert keinen UA-Override |
| HTTP/2 Settings Frame | MITTEL | Playwright-Limit, nicht fixbar |
| Traffic Correlation (RECTor 85% TPR) | KRITISCH | Nur Traffic Padding hilft, nicht perfekt |
| Guard Discovery (17-78 Versuche) | HOCH | VanguardsEnabled gesetzt, aber Tor-Version prüfen |
| System-Level Leaks (kein Whonix) | MITTEL | Nur Whonix VM löst das |

### Was der Agent tun muss

EIN Befehl: `bridge_stealth_start(proxy="socks5://127.0.0.1:9050")`

Alles andere ist AUTOMATISCH:
- Firefox-Engine (nicht Camoufox)
- 20 resistFingerprinting Prefs
- Tor Browser UA
- Viewport 1000x900
- DNS-over-HTTPS only
- Navigation-Jitter
- Traffic Padding (Hintergrund)
- DNS-Leak-Test im Return

---

## 3. GAP-ANALYSE (priorisiert)

### KRITISCH — Architektur-Limits

| Gap | Beschreibung | Lösung | Aufwand |
|-----|-------------|--------|---------|
| Traffic Correlation | ISP + Tor-Node-Überwachung korreliert Timing | WebTunnel + öffentliches WiFi | Hardware |
| System-Level Leaks | Malware/NIT kann echte IP außerhalb Tor leaken | Whonix VM (2-VM Isolation) | KVM Setup |
| Browser Exploit | FBI NIT-Methode: Exploit im Browser → IP-Leak | Whonix + JS off auf .onion | Architektur |

### HOCH — Fixbar

| Gap | Beschreibung | Lösung | Aufwand |
|-----|-------------|--------|---------|
| Camoufox AudioContext | Camoufox blockt Audio nicht | NUR Playwright Firefox für Tor (Auto-Tor macht das) | ✓ DONE |
| Keystroke Biometrics | 92-94% Identifizierung | Kloak installieren | sudo |
| ISP sieht Tor | NetFlow-Analyse erkennt Tor-Traffic | WebTunnel Bridge | Plugin |

### MITTEL — Akzeptabel

| Gap | Beschreibung | Lösung | Aufwand |
|-----|-------------|--------|---------|
| HTTP/2 Settings | Playwright ≠ echtes Tor Browser | Nicht fixbar (Playwright-Limit) | — |
| UA Mismatch bei Camoufox | Firefox 135 statt ESR 128 | Auto-Tor nutzt Firefox, nicht Camoufox | ✓ DONE |
| Kloak detektierbar | "Unnatürlich gleichmäßig" | Variable Delays + Noise | Kloak-Config |

### NIEDRIG — Akzeptiert als Known Limitation

| Gap | Beschreibung |
|-----|-------------|
| USB/HID/Serial APIs sichtbar | Fingerprint-Surface, selten geprüft |
| Plugins = 5 (PDF Viewer) | Tor Browser hat 0, aber Standard |
| Exit Node Kompromittierung | Inherent in Tor, nur .onion hilft |

---

## 4. BEDROHUNGSMATRIX

| Gegner | Methode | Unser Level | Nach Fixes |
|--------|---------|-------------|-----------|
| Cloudflare/Akamai | Anti-Bot Detection | 9/10 | 9/10 |
| Website-Betreiber | Fingerprinting | 8/10 | 9/10 |
| ISP | Tor-Traffic-Erkennung | 3/10 | 7/10 (obfs4/WebTunnel) |
| BKA/Europol | Timing-Analyse + ISP | 4/10 | 6/10 (Padding + obfs4) |
| FBI | Browser-Exploit (NIT) | 5/10 | 8/10 (Whonix + JS off) |
| NSA/GCHQ | QUANTUM + XKeyscore | 2/10 | 4/10 (WebTunnel + WiFi) |
| Mossad | Zero-Day + HUMINT | 1/10 | 2/10 (Whonix, aber Zero-Day = unbekannt) |

---

## 5. NÄCHSTE SCHRITTE (priorisiert)

1. ✓ Auto-Tor-Detection — DONE
2. ✓ Traffic Padding — DONE
3. ✓ Obfs4 + Vanguards — DONE
4. Kloak installieren (sudo) — NÄCHSTER SCHRITT
5. WebTunnel als obfs4-Alternative evaluieren
6. Whonix VM als Option für High-Security Tasks
7. JavaScript Kill-Switch für .onion Sites

Git: 15 Commits heute (063278a auf main).
